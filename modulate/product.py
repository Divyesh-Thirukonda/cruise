"""Trusted product state, agent jobs, pairing and acknowledged device activation."""
from __future__ import annotations

from collections import deque
import copy
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

from .agent import AgentError, Ledger, Orchestrator, digest
from .game_runtime import validate_commands, validate_input, validate_package
from .host_bridge import BridgeStore, BridgeError
from .rendering import Renderer, png


_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_REVISION = re.compile(r"[0-9a-f]{64}\Z")
_CONTROLS = {"joystick", "encoder", "button_a", "button_b", "encoder_pressed"}


def _save_json(path, value):
    temporary = path.with_suffix(".pending")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        stream.write(json.dumps(value, allow_nan=False))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class Product:
    def __init__(self, state_dir, provider, *, budget=0, backend=None):
        self.directory = Path(state_dir)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.events = deque(maxlen=150)
        self.event_id = 0
        self.provider = provider
        self.ledger = Ledger(self.directory / "budget.json", budget)
        self.bridge = BridgeStore(self.directory / "bridge", backend)
        self.agent = Orchestrator(provider, self, self.directory / "requests", self.ledger)
        self.running = False
        self.summary = "Connect the controller, then say what it should become."
        self.device = {"name": "Controller", "controls": [], "devices": [], "warnings": [], "button_sources": {}}
        self.last_seen = None
        self.input = {}
        self.device_revision = None
        self.active_path = self.directory / "active.json"
        self.active = json.loads(self.active_path.read_text()) if self.active_path.exists() else None
        self.pending = None
        self.candidate = None
        self.volume_token = None
        self.volume = None
        self.volume_read_at = None
        self.preview_bytes = b""
        self.preview_version = 0
        self.candidate_preview_bytes = b""
        self.candidate_preview_version = 0
        self.renderer = None
        self.wake = True
        self.telemetry = {}
        self.sequence_path = self.directory / "device-sequences.json"
        try:
            replay = json.loads(self.sequence_path.read_text()) if self.sequence_path.exists() else {
                "source": None, "last_sequence": -1, "retired": []}
            source, sequence, retired = replay["source"], replay["last_sequence"], replay["retired"]
            if (source is not None and (not isinstance(source, str) or not _SESSION.fullmatch(source))
                    or type(sequence) is not int or not -1 <= sequence < 2**53
                    or not isinstance(retired, list) or len(retired) > 4096
                    or any(not isinstance(value, str) or not _SESSION.fullmatch(value) for value in retired)
                    or len(set(retired)) != len(retired) or source in retired):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise AgentError("Device replay state is unreadable; refusing to reset it") from None
        self.source_session, self.last_packet, self.retired_sessions = source, sequence, set(retired)
        self.recovery_path = self.directory / "device-recovery.json"
        self.recovery = json.loads(self.recovery_path.read_text()) if self.recovery_path.exists() else None
        self.intent_path = self.directory / "activation-intent.json"
        self.last_intent = json.loads(self.intent_path.read_text()) if self.intent_path.exists() else None
        self.pairing = None

    @property
    def revision(self):
        return self.active["revision"] if self.active else None

    def connected(self):
        return self.last_seen is not None and time.monotonic() - self.last_seen < 4

    def event(self, entry):
        with self.lock:
            self.event_id += 1
            self.events.append({"id": self.event_id, "at": time.time(), **entry})

    def preview(self, data):
        """A verifier preview is not evidence of the physical device's frame."""
        with self.lock:
            self.candidate_preview_bytes = data
            self.candidate_preview_version += 1

    def _device_preview(self, data):
        with self.lock:
            self.preview_bytes = data
            self.preview_version += 1

    def current_package(self):
        with self.lock:
            return copy.deepcopy(self.active["package"]) if self.active else None

    def capabilities(self):
        with self.lock:
            paired = None
            if self.volume_token:
                try:
                    session = self.bridge.session(self.volume_token)
                    if session["capabilities"].get("supported") is not True:
                        raise BridgeError("Host volume is unavailable")
                    paired = {"name": "This Mac", "session_id": session["session_id"], "actions": session["capabilities"]["actions"]}
                except BridgeError:
                    self.volume_token = None
                    self.volume = None
            return {"display": {"width": 240, "height": 135}, "runtime": "modulate-game-v1",
                    "device_connected": self.connected(), "controls": list(self.device["controls"]) if self.connected() else [],
                    "devices": copy.deepcopy(self.device["devices"]), "warnings": list(self.device["warnings"]),
                    "button_sources": dict(self.device["button_sources"]),
                    "paired_host": paired}

    def candidate_changed(self, identifier, package):
        with self.lock:
            self.candidate = {"revision": identifier, "package": copy.deepcopy(package)}
            self.candidate_preview_bytes = b""
            self.candidate_preview_version += 1

    def validate_control(self, package):
        if not isinstance(package, dict) or set(package) != {"kind", "title", "target", "bindings"} or package.get("kind") != "control":
            raise AgentError("Control package requires kind, title, target and bindings")
        if not isinstance(package["title"], str) or not 1 <= len(package["title"]) <= 80:
            raise AgentError("Control title must contain 1–80 characters")
        capabilities = self.capabilities()
        paired = capabilities["paired_host"]
        if not paired or package["target"] != paired["session_id"] or "volume.delta" not in paired["actions"]:
            raise AgentError("Pair and grant this computer's volume control before generating a binding")
        if "encoder" not in capabilities["controls"]:
            raise AgentError("The encoder is unavailable")
        bindings = package["bindings"]
        if not isinstance(bindings, list) or len(bindings) != 1:
            raise AgentError("The first control runtime supports one encoder volume binding")
        binding = bindings[0]
        if not isinstance(binding, dict) or set(binding) != {"control", "action", "scale"}:
            raise AgentError("Binding requires control, action, scale")
        if binding["control"] != "encoder" or binding["action"] != "volume.delta":
            raise AgentError("Only encoder → volume.delta is supported by this host grant")
        if type(binding["scale"]) is not int or not 1 <= abs(binding["scale"]) <= 10:
            raise AgentError("Encoder scale must be a nonzero integer within -10..10")
        return json.loads(json.dumps(package))

    def verify_control(self, package):
        try:
            self.validate_control(package)
            return {"passed": True, "checks": [{"name": "paired target and allowed action", "passed": True},
                    {"name": "connected encoder and bounded scale", "passed": True}],
                    "errors": [], "metrics": {"effects_during_check": 0}}
        except AgentError as error:
            return {"passed": False, "checks": [], "errors": [str(error)], "metrics": {}}

    def request(self, text, source="website"):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise AgentError("Request must contain 1–4000 characters")
        with self.lock:
            if self.running:
                raise AgentError("The agent is already working; cancel it or wait")
            if not self.connected():
                raise AgentError("The physical controller is not connected")
            if self.device_revision != self.revision:
                raise AgentError("Wait for the controller and host to finish synchronizing")
            self.running = True
            self.summary = "The agent is deciding what to build."

        def work():
            try:
                self.summary = self.agent.run(text)
            except Exception as error:
                self.summary = str(error)[:500]
            finally:
                with self.lock:
                    self.running = False
        threading.Thread(target=work, name="modulate-agent", daemon=True).start()
        return {"accepted": True, "source": source}

    def cancel(self):
        self.agent.cancelled.set()
        with self.changed:
            if self.pending and self.pending["phase"] not in {"confirmed", "abort"}:
                self.pending.update(phase="abort", error="Cancelled by user")
                self.changed.notify_all()
        return {"cancelled": True}

    def _commit(self, record):
        renderer = Renderer(record["package"]) if record and record["package"]["kind"] == "game" else None
        try:
            _save_json(self.active_path, record)
        except Exception:
            # An error after replacement must not acknowledge rollback while
            # the durable pointer already names the newly displayed program.
            try:
                persisted = json.loads(self.active_path.read_text())
            except (OSError, ValueError):
                raise AgentError("Could not persist active program") from None
            if persisted != record:
                raise AgentError("Could not persist active program") from None
        self.active = record
        self.renderer = renderer
        self.preview_bytes = b""
        self.preview_version += 1

    def activate(self, package, report, *, base_revision, timeout=15):
        with self.changed:
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 60:
                raise AgentError("Activation timeout must be between 0 and 60 seconds")
            if not isinstance(package, dict) or package.get("kind") not in ("game", "control"):
                raise AgentError("Invalid activation package")
            package = validate_package(package) if package["kind"] == "game" else self.validate_control(package)
            revision = digest(package)
            if (not isinstance(report, dict) or report.get("passed") is not True
                    or report.get("candidate_id") != revision):
                raise AgentError("Activation requires passing checks for the exact package")
            if base_revision != self.revision:
                raise AgentError("Stale active revision; previous program preserved")
            if not self.connected():
                raise AgentError("Controller disconnected before activation")
            if self.device_revision != base_revision:
                raise AgentError("Controller revision does not match the active host revision")
            if package["kind"] == "control":
                self.validate_control(package)
            else:
                if not set(package["controls"]) <= set(self.device["controls"]):
                    raise AgentError("A required input is unavailable")
            if self.pending and self.pending["phase"] not in {"confirmed", "abort"}:
                raise AgentError("Another activation is pending")
            token = uuid.uuid4().hex
            pending = {"id": token, "revision": revision, "package": package,
                       "report": copy.deepcopy(report), "phase": "stage", "base_revision": base_revision,
                       "source_session": self.source_session, "capabilities": digest(self.capabilities())}
            self._record_intent(pending)
            self.pending = pending
            self.changed.notify_all()
            deadline = time.monotonic() + timeout
            while pending["phase"] not in {"confirmed", "abort"}:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self.connected() or self.agent.cancelled.is_set():
                    pending.update(phase="abort", error="Activation timed out, disconnected or cancelled")
                    break
                self.changed.wait(min(remaining, 0.5))
            if pending["phase"] != "confirmed":
                raise AgentError(pending.get("error", "Activation failed"))
            return {"activated": True, "revision": revision, "device_acknowledged": True,
                    "kind": package["kind"], "title": package["title"]}

    def _acknowledge(self, ack):
        pending = self.pending
        if not pending or not isinstance(ack, dict) or ack.get("id") != pending["id"] or ack.get("revision") != pending["revision"]:
            return
        if pending["phase"] in {"confirmed", "abort"}:
            return
        if ((self.agent.cancelled.is_set() and not pending.get("recovery")) or pending["source_session"] != self.source_session
                or pending.get("host_base_revision", pending["base_revision"]) != self.revision or not self.connected()
                or pending["capabilities"] != digest(self.capabilities())):
            pending.update(phase="abort", error="Activation context changed or was cancelled")
            self.changed.notify_all()
            return
        phase = ack.get("phase")
        if phase == "failed" and pending["phase"] not in {"confirmed", "abort"}:
            pending.update(phase="abort", error=str(ack.get("error", "Device rejected activation"))[:300])
            self.event({"type": "device_activation_failed", "title": "Device rejected activation",
                        "detail": {"revision": pending["revision"], "error": pending["error"]}})
        elif phase == "ready" and pending["phase"] == "stage" and self.device_revision == pending["base_revision"]:
            pending["phase"] = "commit"
        elif phase == "activated" and pending["phase"] == "commit" and self.device_revision == pending["revision"]:
            try:
                if pending["package"]["kind"] == "control":
                    self.validate_control(pending["package"])
                if not pending.get("recovery"):
                    predecessor = {**self.active, "previous": None} if self.active else None
                    record = {"revision": pending["revision"], "package": pending["package"],
                              "report": pending["report"], "previous": predecessor,
                              "activated_at": time.time()}
                    self._commit(record)
                pending["phase"] = "confirmed"
            except Exception:
                pending.update(phase="abort", error="Host could not commit activation")
        self.changed.notify_all()

    def heartbeat(self, packet):
        """Called only after device bearer authentication on the pinned TLS listener."""
        with self.changed:
            try:
                if not isinstance(packet, dict) or len(json.dumps(packet, allow_nan=False).encode()) > 256 * 1024:
                    raise ValueError
            except (ValueError, TypeError, RecursionError):
                raise AgentError("Invalid or oversized heartbeat") from None
            session_id, sequence = packet.get("session"), packet.get("sequence")
            if (not isinstance(session_id, str) or not _SESSION.fullmatch(session_id)
                    or type(sequence) is not int or not 0 <= sequence < 2**53):
                raise AgentError("Invalid device session or sequence")
            if session_id in self.retired_sessions or session_id == self.source_session and sequence <= self.last_packet:
                raise AgentError("Stale or duplicate device packet")
            switching = session_id != self.source_session
            if switching and len(self.retired_sessions) >= 4096:
                raise AgentError("Device session history is full; re-enroll the controller")
            controls = packet.get("capabilities", {})
            if not isinstance(controls, dict):
                raise AgentError("Invalid controller manifest")
            names = controls.get("controls", [])
            devices, warnings = controls.get("devices", []), controls.get("warnings", [])
            button_sources = controls.get("button_sources", {})
            if (not isinstance(names, list) or any(not isinstance(name, str) or name not in _CONTROLS for name in names)
                    or len(set(names)) != len(names) or not isinstance(devices, list) or len(devices) > 12
                    or any(not isinstance(item, dict) for item in devices) or not isinstance(warnings, list)
                    or len(warnings) > 12 or any(not isinstance(item, str) or len(item) > 1000 for item in warnings)):
                raise AgentError("Invalid controller manifest")
            if (not isinstance(button_sources, dict) or set(button_sources) - {"button_a", "button_b"}
                    or any(not isinstance(value, str) or len(value) > 160 for value in button_sources.values())):
                raise AgentError("Invalid button source metadata")
            name = packet.get("name", "Modulate Pi")
            if not isinstance(name, str) or not 1 <= len(name) <= 80:
                raise AgentError("Invalid controller name")
            sample = validate_input(packet.get("input", {}))
            revision = packet.get("revision")
            if revision is not None and (not isinstance(revision, str) or not _REVISION.fullmatch(revision)):
                raise AgentError("Invalid controller revision")
            telemetry = packet.get("telemetry", {})
            if not isinstance(telemetry, dict):
                raise AgentError("Invalid controller telemetry")
            failure = packet.get("failure")
            recovered = self._validate_failure(failure, revision) if failure is not None else None
            if failure is None and revision != self.revision:
                pending_revision = self.pending and self.pending["phase"] in {"commit", "abort"} and revision == self.pending["revision"]
                previous = self.active.get("previous") if self.active else None
                known_base = self.active and revision == (previous["revision"] if previous else None)
                if not pending_revision and not known_base:
                    raise AgentError("Unknown controller revision; resynchronization required")
            frame_package = self.active["package"] if self.active and revision == self.revision else None
            if recovered and recovered.get("previous"):
                frame_package = recovered["previous"]["package"]
            if self.pending and revision == self.pending["revision"] and self.pending["phase"] == "commit":
                frame_package = self.pending["package"]
            commands = packet.get("commands")
            if commands and frame_package and frame_package["kind"] == "game":
                commands = validate_commands(commands, frame_package["assets"]["sprites"])
            retired = self.retired_sessions | ({self.source_session} if switching and self.source_session else set())
            # Persist the anti-replay watermark before acknowledgements or host actions.
            _save_json(self.sequence_path, {"source": session_id, "last_sequence": sequence, "retired": sorted(retired)})
            self.source_session, self.last_packet, self.retired_sessions = session_id, sequence, retired
            self.device = {"name": name, "controls": list(names), "devices": copy.deepcopy(devices),
                           "warnings": list(warnings), "button_sources": dict(button_sources)}
            self.last_seen = time.monotonic()
            self.input, self.device_revision, self.telemetry = sample, revision, copy.deepcopy(telemetry)
            if switching:
                self.volume_token = None
                self.volume = None
            if "volume_token" in packet:
                try:
                    self.bridge.session(packet["volume_token"])
                    self.volume_token = packet["volume_token"]
                except BridgeError:
                    self.volume_token = None
                    self.volume = None
            if recovered is not None:
                self._restore_failure(failure, recovered)
            if self.pending and self.pending["phase"] not in {"confirmed", "abort"} and (
                    self.pending["source_session"] != self.source_session
                    or self.pending["capabilities"] != digest(self.capabilities())):
                self.pending.update(phase="abort", error="Connected capabilities or device session changed")
                self.changed.notify_all()
            self._acknowledge(packet.get("ack"))
            if failure is None:
                self._restore_host_program()
            if self.active and self.device_revision == self.revision:
                if self.active["package"]["kind"] == "game" and commands:
                    commands = validate_commands(commands, self.active["package"]["assets"]["sprites"])
                    if not self.renderer:
                        self.renderer = Renderer(self.active["package"])
                    self._device_preview(png(self.renderer.render(commands)))
                elif self.active["package"]["kind"] == "control" and self.volume_token:
                    package = self.active["package"]
                    try:
                        self.validate_control(package)
                        session = self.bridge.session(self.volume_token)
                        delta = max(-10, min(10, self.input["encoder_delta"] * package["bindings"][0]["scale"]))
                        if delta:
                            self.volume_read_at = time.monotonic()
                            self.volume = self.bridge.execute(self.volume_token, session["next_sequence"], "volume.delta", delta)
                            self.volume_read_at = time.monotonic()
                        elif self.volume_read_at is None or time.monotonic() - self.volume_read_at >= 1:
                            # Poll only the trusted host bridge. A failed poll also
                            # consumes this interval, even if the token is resent.
                            self.volume_read_at = time.monotonic()
                            self.volume = self.bridge.execute(self.volume_token, session["next_sequence"], "volume.get")
                            self.volume_read_at = time.monotonic()
                    except (BridgeError, AgentError):
                        self.volume_token = None
                        self.volume = None
            pending = None
            if self.pending:
                pending = {key: self.pending[key] for key in ("id", "revision", "phase", "base_revision")}
                if self.pending["phase"] == "stage":
                    pending["package"] = self.pending["package"]
            return {"activation": pending, "active_revision": self.revision, "wake": self.wake,
                    "agent_running": self.running, "volume": self.volume, "paired": bool(self.capabilities()["paired_host"]),
                    "failure_ack": ({key: failure[key] for key in ("revision", "restored_revision")} if failure is not None else None),
                    "pairing": (copy.deepcopy(self.pairing) if self.pairing and time.time() < self.pairing["expires_at"]
                                and not self.capabilities()["paired_host"] else None)}

    def _record_intent(self, pending):
        intent = {key: pending[key] for key in ("id", "revision", "base_revision")}
        _save_json(self.intent_path, intent)
        self.last_intent = intent

    def _restore_host_program(self):
        if (self.device_revision == self.revision or not self.active
                or self.pending and self.pending["phase"] != "confirmed"):
            return
        previous = self.active.get("previous")
        if self.device_revision != (previous["revision"] if previous else None):
            return  # An abort response tells a provisional device to restore first.
        package, report = self.active["package"], self.active["report"]
        if report.get("passed") is not True or report.get("candidate_id") != digest(package):
            raise AgentError("Stored program lacks matching checks; resynchronization stopped")
        if package["kind"] == "control":
            self.validate_control(package)
        elif not set(package["controls"]) <= set(self.device["controls"]):
            raise AgentError("Stored program needs unavailable controls; resynchronization stopped")
        pending = {"id": uuid.uuid4().hex, "revision": self.revision, "package": copy.deepcopy(package),
                   "report": copy.deepcopy(report), "phase": "stage", "base_revision": self.device_revision,
                   "host_base_revision": self.revision, "source_session": self.source_session,
                   "capabilities": digest(self.capabilities()), "recovery": True}
        self._record_intent(pending)
        self.pending = pending
        self.event({"type": "device_resynchronizing", "title": "Restoring the confirmed program",
                    "detail": {"revision": self.revision, "device_revision": self.device_revision}})

    def _validate_failure(self, failure, revision):
        if (not isinstance(failure, dict) or set(failure) != {"revision", "restored_revision", "error"}
                or not isinstance(failure["revision"], str) or not _REVISION.fullmatch(failure["revision"])
                or failure["restored_revision"] != revision or not isinstance(failure["error"], str)
                or len(failure["error"]) > 500):
            raise AgentError("Invalid device failure report; resynchronization required")
        if (self.recovery and failure["revision"] == self.recovery.get("revision")
                and revision == self.recovery.get("restored_revision") and self.revision == revision):
            return {"repeat": True}
        if (self.last_intent and failure["revision"] == self.last_intent.get("revision")
                and revision == self.last_intent.get("base_revision") and self.revision == revision):
            return {"already_restored": True}
        previous = self.active.get("previous") if self.active else None
        if (not self.active or failure["revision"] != self.revision
                or revision != (previous["revision"] if previous else None)):
            raise AgentError("Device failure does not match the active predecessor; resynchronization required")
        return {"previous": copy.deepcopy(previous)}

    def _restore_failure(self, failure, recovery):
        if recovery.get("repeat"):
            return
        _save_json(self.recovery_path, failure)
        if not recovery.get("already_restored"):
            self._commit(recovery["previous"])
        self.recovery = copy.deepcopy(failure)
        if self.pending and self.pending["revision"] == failure["revision"]:
            self.pending.update(phase="abort", error="Active runtime failed and restored its predecessor")
            self.changed.notify_all()
        self.event({"type": "device_runtime_failed", "title": "Device runtime stopped",
                    "detail": {"revision": failure["revision"], "restored_revision": self.revision,
                               "error": failure["error"], "rollback_acknowledged": True}})

    def pair(self, code, name):
        with self.lock:
            token = self.bridge.pair(code, name)
            try:
                session = self.bridge.session(token)
                self.volume_read_at = time.monotonic()
                volume = self.bridge.execute(token, session["next_sequence"], "volume.get")
            except BridgeError:
                self.pairing = None
                self.volume = None
                self.bridge.revoke(token)
                raise
            self.volume_token, self.volume = token, volume
            self.volume_read_at = time.monotonic()
            self.pairing = None
            return {"token": token, "session_id": session["session_id"], "capabilities": session["capabilities"]}

    def create_pairing(self):
        with self.lock:
            self.pairing = self.bridge.create_pairing()
            return copy.deepcopy(self.pairing)

    def revoke(self):
        with self.lock:
            self.bridge.revoke_all()
            self.volume_token = None
            self.volume = None
            self.volume_read_at = None
            self.pairing = None
            if self.pending and self.pending["phase"] not in {"confirmed", "abort"} and self.pending["package"]["kind"] == "control":
                self.pending.update(phase="abort", error="Host control grant revoked")
                self.changed.notify_all()
        return {"revoked": True}

    def rollback(self):
        with self.lock:
            if self.running:
                raise AgentError("Wait for or cancel the agent before rollback")
            if self.pending and self.pending["phase"] not in {"confirmed", "abort"}:
                raise AgentError("Another activation is pending")
            previous = self.active and self.active.get("previous")
            if not previous:
                raise AgentError("No previous program")
            base = self.revision
            self.agent.cancelled.clear()
        return self.activate(previous["package"], previous["report"], base_revision=base)

    def state(self):
        with self.lock:
            return {"provider": self.provider.config.provider, "model": self.provider.config.model,
                    "budget": self.ledger.status(), "device": {"connected": self.connected(), "name": self.device["name"],
                    "capabilities": self.capabilities(), "input": self.input, "telemetry": self.telemetry},
                    "active": self.active, "candidate": self.candidate,
                    "agent": {"running": self.running, "request_id": self.agent.request_id, "summary": self.summary},
                    "events": list(self.events), "volume": self.volume,
                    "paired": bool(self.capabilities()["paired_host"]), "wake": self.wake,
                    "preview_version": self.preview_version,
                    "candidate_preview_version": self.candidate_preview_version}
