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
from .agent_provider import AgentProviderError
from .game_runtime import validate_commands, validate_input, validate_package
from .host_bridge import BridgeStore, BridgeError
from .rendering import Renderer, png
from .assistant_io import AssistantIO
from .intent_memory import IntentMemory
from .speaker_volume import SpeakerVolume, SpeakerVolumeError
from .hardware_debug import HardwareDebug
from .connection_setup import ConnectionSetup
from .library import LibraryManager


_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_REVISION = re.compile(r"[0-9a-f]{64}\Z")
_CONTROLS = {"joystick", "encoder", "button_a", "button_b", "encoder_pressed"}
_FOLLOWUP_SECONDS = 120
_MAX_QUESTIONS = 4
_PHASES = {"queued", "planning", "coding", "checking", "previewing", "activating", "ready", "error", "cancelled"}
_TOOL_PROGRESS = {
    "load_skill": ("planning", "Choosing the right skill"),
    "read_recent_context": ("planning", "Remembering the last request"),
    "speaker_control": ("planning", "Adjusting the Modulate speaker"),
    "inspect_capabilities": ("planning", "Reading the connected controls"),
    "read_runtime_api": ("planning", "Checking what the controller supports"),
    "read_current_package": ("coding", "Reading the current app"),
    "write_package": ("coding", "Writing your app"),
    "test_package": ("checking", "Checking your app"),
    "preview_package": ("previewing", "Preparing a preview"),
    "activate_package": ("activating", "Starting it on the controller"),
    "delegate_task": ("planning", "Working with a specialist"),
    "ask_user": ("planning", "One quick question"),
    "computer_observe": ("planning", "Looking at the computer"),
    "computer_act": ("planning", "Using the computer"),
    "camera_control": ("planning", "Connecting the Mac camera"),
    "computer_audio": ("planning", "Connecting computer audio"),
    "system_control": ("planning", "Adjusting the Mac"),
    "hardware_debug": ("planning", "Checking the hardware"),
    "connection_setup": ("planning", "Preparing connection setup"),
    "app_library": ("planning", "Opening your app library"),
}


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


class Product(AssistantIO):
    def __init__(self, state_dir, provider, *, budget=0, backend=None, computer=None):
        self.directory = Path(state_dir)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.remote_access = None
        self.changed = threading.Condition(self.lock)
        self.events = deque(maxlen=150)
        self.intent_memory = IntentMemory(self.directory / "recent-context.json")
        self.memory_generation = 0
        self.memory_error = None
        self.speaker_volume = SpeakerVolume()
        self.hardware = HardwareDebug(self.directory / "hardware-repair.json")
        self.event_id = 0
        self.provider = provider
        self.ledger = Ledger(self.directory / "budget.json", budget)
        self.bridge = BridgeStore(self.directory / "bridge", backend)
        self.agent = Orchestrator(provider, self, self.directory / "requests", self.ledger)
        self.running = False
        self.summary = "Connect the controller, then say what it should become."
        self.job_context = threading.local()
        self.job_path = self.directory / "agent-job.json"
        self.progress = {"job_id": None, "job_sequence": 0, "request_id": None, "phase": "ready", "title": "Ready",
                         "tool": None, "role": None}
        self._load_job()
        self.voice_draft = None
        self.draft_deadline = None
        self.clarification = None
        self.conversation = None
        self.current_request = None
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
        self.setup_offer = None
        self.connection_guide = ConnectionSetup(self)
        self.app_library = LibraryManager(self)
        self._init_assistant_io(computer)
        # Permission denials survive launching the companion without its cloud
        # gateway configuration. Omitting a secret cannot restore authority.
        if (self.directory / "remote-access.json").exists():
            from .remote_access import RemoteAccess
            self.remote_access = RemoteAccess(self, self.directory, gateway_enabled=False)

    @property
    def revision(self):
        return self.active["revision"] if self.active else None

    def connected(self):
        return self.last_seen is not None and time.monotonic() - self.last_seen < 4

    def permission_allowed(self, name):
        remote = getattr(self, "remote_access", None)
        return remote is None or remote.allowed(name)

    def require_permission(self, name):
        if not self.permission_allowed(name):
            raise AgentError(f"{name.replace('_', ' ').capitalize()} access is off in device permissions")

    def check_request_access(self):
        remote = getattr(self, "remote_access", None)
        if remote is not None:
            remote.require_job()

    def intent_context(self, include_private=False):
        with self.lock:
            package = (self.active or {}).get("package", {})
            return {"recent": self.intent_memory.snapshot(include_private),
                    "current": {"app": {key: copy.deepcopy(package[key]) for key in
                                ("title", "kind", "controls", "bindings", "camera") if key in package},
                                "revision": self.revision,
                                "computer_audio": {key: value for key, value in self.audio_status().items()
                                                   if key in {"running", "state"}},
                                "pi_speaker": {key: value for key, value in self.speaker_volume.status().items()
                                               if key in {"volume", "muted", "available"}},
                                "last_observed_mac_setting": copy.deepcopy(self.volume),
                                "paired": bool(self._paired_session())},
                    "hardware": self.hardware.inspect(),
                    "library": {"open": self.app_library.view["open"],
                                "tab": self.app_library.view["tab"],
                                "selected_id": self.app_library.selected()}}

    def hardware_debug(self, action, label=None):
        if action != "cancel":
            self.require_permission("hardware")
        with self.lock:
            if self.agent.cancelled.is_set() and action != "cancel":
                raise AgentError("Hardware request cancelled")
        # Device acknowledgements arrive on the network thread; never wait
        # while holding Product.lock.
        result = self.hardware.call(action, label=label)
        with self.lock:
            return {**result, "device_health": {
                "connected": self.connected(),
                "controls": copy.deepcopy(self.device),
                "voice": copy.deepcopy(self.telemetry.get("voice", {})),
                "speaker": copy.deepcopy(self.telemetry.get("speaker", {})),
                "speaker_volume": self.speaker_volume.status(),
                "display": copy.deepcopy(self.telemetry.get("display", {})),
                "runtime_error": self.telemetry.get("error"),
                "app_revision": self.revision}}

    def connection_setup(self, action):
        return self.connection_guide.call(action)

    def library_action(self, data, *, device=False, agent=False):
        return self.app_library.call(data, origin="agent" if agent else "device" if device else "web")

    def hardware_confirm(self, identifier, step):
        self.require_permission("hardware")
        with self.lock:
            if self.running:
                raise AgentError("Finish or cancel the current request before confirming wiring")
        self.hardware.confirm(identifier, step)
        return self.request("Continue the current hardware repair using my confirmed physical step.")

    def hardware_cancel(self):
        with self.changed:
            if self.running:
                return self.cancel()
            result = self.hardware.call("cancel")
            self.clarification = None
            self.conversation = self.current_request = None
            self.response = None
            self._stop_speech()
            self.changed.notify_all()
            return result

    def clear_context(self):
        with self.lock:
            if self.running:
                raise AgentError("Finish or cancel the current request before forgetting context")
            self.intent_memory.clear()
            self.memory_generation += 1
            self.memory_error = None
            self.clarification = self.conversation = self.current_request = None
            self._stop_speech()
            return {"cleared": True}

    def speaker_control(self, action, value=None):
        self.require_permission("speaker")
        with self.lock:
            if not self.connected() or self.agent.cancelled.is_set():
                raise AgentError("Pi speaker request is disconnected or cancelled")
        try:
            return self.speaker_volume.control(action, value)
        except SpeakerVolumeError as error:
            raise AgentError(str(error)) from None

    def event(self, entry):
        with self.lock:
            self.event_id += 1
            worker_job = getattr(self.job_context, "job_id", None)
            record = {"id": self.event_id, "at": time.time(), **entry}
            if worker_job:
                record["job_id"] = worker_job
            self.events.append(record)
            if self.running and worker_job and worker_job == self.progress["job_id"]:
                self._progress_event(entry)

    def _load_job(self):
        if not self.job_path.exists():
            return
        try:
            saved = json.loads(self.job_path.read_text())
            sequence = saved.get("job_sequence", 0) if isinstance(saved, dict) else None
            if (not isinstance(saved, dict) or not isinstance(saved.get("job_id"), str)
                    or not _SESSION.fullmatch(saved["job_id"]) or type(saved.get("running")) is not bool
                    or type(sequence) is not int or not 0 <= sequence < 2**53
                    or saved.get("phase") not in _PHASES
                    or any(not isinstance(saved.get(key), str) or len(saved[key]) > limit
                           for key, limit in (("title", 100), ("summary", 500)))
                    or saved.get("request_id") is not None and (
                        not isinstance(saved["request_id"], str) or not _SESSION.fullmatch(saved["request_id"]))
                    or any(saved.get(key) is not None and (not isinstance(saved[key], str) or len(saved[key]) > 80)
                           for key in ("tool", "role"))):
                raise ValueError
            self.progress = {key: saved.get(key) for key in self.progress}
            self.progress["job_sequence"] = sequence
            self.summary = saved["summary"]
            if saved["running"]:
                self.progress.update(phase="error", title="Request interrupted", tool=None, role=None)
                self.summary = "The companion restarted before this request finished. Please submit it again."
                self._save_job()
        except (OSError, ValueError, TypeError, KeyError):
            raise AgentError("Saved request status is unreadable; refusing to replace its identity") from None

    def _save_job(self):
        _save_json(self.job_path, {**self.progress, "running": self.running, "summary": self.summary[:500]})

    def agent_state(self):
        with self.lock:
            status = "running" if self.running else {
                "error": "failed", "cancelled": "cancelled"}.get(self.progress["phase"], "completed")
            return {**self.progress, "running": self.running, "status": status, "summary": self.summary[:500]}

    def _progress_event(self, entry):
        kind, request_id = entry.get("type"), entry.get("request_id")
        if kind == "request_started" and self.progress["request_id"] is None:
            if not isinstance(request_id, str) or not _SESSION.fullmatch(request_id):
                return
            self.progress["request_id"] = request_id
        if not request_id or request_id != self.progress["request_id"]:
            return
        if self.progress["phase"] == "cancelled":
            # Orchestrator initializes its cancellation event at run entry; a
            # cancellation received while queued must survive that initialization.
            self.agent.cancelled.set()
            return
        role = entry.get("role") if entry.get("role") in {"orchestrator", "coder", "artist", "reviewer"} else None
        if kind == "request_started":
            self.progress.update(phase="planning", title="Understanding your request", role=role, tool=None)
        elif kind == "model_call":
            phase, title = {"coder": ("coding", "Writing your app"), "artist": ("coding", "Creating the artwork"),
                            "reviewer": ("checking", "Reviewing your app")}.get(role, ("planning", "Planning the next step"))
            self.progress.update(phase=phase, title=title, role=role, tool=None)
        elif kind in {"tool_started", "tool_finished"}:
            tool = entry.get("tool")
            phase, title = _TOOL_PROGRESS.get(tool, ("planning", "Working on your request"))
            if kind == "tool_finished":
                if entry.get("status") == "failed":
                    phase, title = "planning", "Adjusting the app"
                else:
                    title = {"write_package": "App written", "test_package": "Reviewing check results",
                             "preview_package": "Preview prepared", "activate_package": "Controller acknowledged",
                             "delegate_task": "Specialist finished"}.get(tool, "Planning the next step")
            self.progress.update(phase=phase, title=title, role=role, tool=tool if tool in _TOOL_PROGRESS else None)
        elif kind == "request_failed":
            cancelled = self.agent.cancelled.is_set()
            self.progress.update(phase="cancelled" if cancelled else "error",
                                 title="Request cancelled" if cancelled else "Could not finish", tool=None, role=role)
        elif kind == "request_finished":
            self.progress.update(phase="ready", title="Ready", tool=None, role=role)

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
                    paired = {"name": "This Mac", "session_id": session["session_id"], "actions":
                              session["capabilities"]["actions"] if self.permission_allowed("system") else []}
                except BridgeError:
                    self.volume_token = None
                    self.volume = None
            return {"display": {"width": 240, "height": 135}, "runtime": "modulate-game-v1",
                    "device_connected": self.connected(), "controls": list(self.device["controls"]) if self.connected() else [],
                    "devices": copy.deepcopy(self.device["devices"]), "warnings": list(self.device["warnings"]),
                    "button_sources": dict(self.device["button_sources"]),
                    "permissions": ({key: self.permission_allowed(key) for key in
                                    ("computer", "system", "camera", "audio", "voice", "speaker", "hardware")}),
                    "hardware_debug": {"supported": self.permission_allowed("hardware") and self.hardware.inspect().get("supported", False),
                                       "guided_button_address_repair": True},
                    "paired_host": paired,
                    "app_library": {"supported": True, "persistent": True, "voice_navigation": True},
                    "connection_setup": {"supported": True, "needs_pairing": paired is None,
                                         "actions": ["status", "show", "start_pairing", "create_browser_code"],
                                         "connect_url": "https://divy.live/connect"},
                    "computer": {key: value for key, value in self.computer_status().items()
                                 if key in {"supported", "enabled", "scope"}},
                    "computer_audio": {"supported": self.permission_allowed("audio") and self.permission_allowed("speaker") and self.audio_status()["supported"],
                                       "source": "paired_mac", "local_stream_only": True,
                                       "format": "pcm_s16le_48000_stereo"},
                    "camera": {"supported": self.permission_allowed("camera") and self.camera_status()["supported"],
                               "source": "paired_mac", "local_stream_only": True,
                               "width": 240, "height": 135},
                    "speaker": {"available": self.permission_allowed("speaker") and self.telemetry.get("speaker", {}).get("available", False),
                                "volume_control": self.speaker_volume.status()["available"],
                                "actions": ["get", "set", "delta", "mute"], "target": "Modulate Pi speaker"}}

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
        if not paired or package["target"] != paired["session_id"]:
            raise AgentError("Pair this Mac before generating a control binding")
        if "encoder" not in capabilities["controls"]:
            raise AgentError("The encoder is unavailable")
        bindings = package["bindings"]
        if not isinstance(bindings, list) or len(bindings) != 1:
            raise AgentError("The control runtime supports one encoder setting binding")
        binding = bindings[0]
        if not isinstance(binding, dict) or set(binding) != {"control", "action", "scale"}:
            raise AgentError("Binding requires control, action, scale")
        if (binding["control"] != "encoder" or binding["action"] not in {"volume.delta", "brightness.delta"}
                or binding["action"] not in paired["actions"]):
            raise AgentError("The paired Mac must support the requested encoder setting")
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

    def _clarification_state(self):
        if self.clarification and self.clarification["expires_at"] <= time.time():
            self.clarification = None
            self.conversation = self.current_request = None
        return ({key: self.clarification[key] for key in
                 ("id", "question", "job_id", "request_id", "expires_at", "kind")}
                if self.clarification else None)

    def _followup(self, identifier):
        self._clarification_state()
        if identifier is not None and (type(identifier) is not str or not _SESSION.fullmatch(identifier)
                or not self.clarification or self.clarification["id"] != identifier):
            raise AgentError("That conversation has ended. Say Hey Meta and repeat your full request.")
        return copy.deepcopy(self.clarification)

    def _question(self, question, *, kind="clarification"):
        context = self.conversation or {"original": "", "history": [], "questions": 0, "recoveries": 0}
        if context["questions"] >= _MAX_QUESTIONS:
            raise AgentError("Conversation question limit reached; start again with the full request")
        context["questions"] += 1
        self.conversation = context
        self.clarification = {"id": uuid.uuid4().hex, "question": question,
                              "request_id": self.progress["request_id"], "job_id": self.progress["job_id"],
                              "expires_at": time.time() + _FOLLOWUP_SECONDS, "kind": kind,
                              "private": bool(self.agent.private_request), "context": copy.deepcopy(context)}

    def unclear(self, reason, followup_id=None):
        """A confirmed invocation with no usable speech needs no guessed intent."""
        if type(reason) is not str or reason not in {"empty", "incomplete"}:
            raise AgentError("Unknown speech clarification reason")
        with self.lock:
            if self.running or not self.connected():
                raise AgentError("Wait for the current request and controller connection")
            if self.progress["job_sequence"] + 1 >= 2**53:
                raise AgentError("Request sequence limit reached")
            followup = self._followup(followup_id)
            self.conversation = (followup["context"] if followup else
                                 {"original": "", "history": [], "questions": 0, "recoveries": 0})
            self.agent.private_request = bool(followup and followup.get("private"))
            job_id = uuid.uuid4().hex
            self.progress = {"job_id": job_id, "job_sequence": self.progress["job_sequence"] + 1,
                             "request_id": None, "phase": "ready", "title": "One quick question",
                             "tool": None, "role": "orchestrator"}
            question = followup["question"] if followup else "I heard you call me, but missed the request. What would you like me to do?"
            self._stop_speech()
            self.clarification = None
            try:
                self._question(question, kind=followup["kind"] if followup else "clarification")
                if followup and followup.get("kind") == "library_purge":
                    self.clarification["library_confirmation"] = followup["library_confirmation"]
            except AgentError:
                question = "I still couldn't understand the request. Please type it in Studio, or say Hey Meta and start again."
                self.conversation = self.current_request = None
            self._publish_response(question, job_id)
            self.summary = "Waiting for a clearer request." if self.clarification else "Speech clarification ended."
            self._save_job()
            return {"accepted": True, "job_id": job_id, "job_sequence": self.progress["job_sequence"]}

    @staticmethod
    def _failure_guidance(error):
        """Fixed operational explanations; never echo exception payloads or invent intent."""
        message = str(error).lower()
        if isinstance(error, AgentProviderError):
            if any(word in message for word in ("credential", "http 401", "http 403", "configuration", "endpoint")):
                return ("Meta access isn't available. Check the provider credentials and account access in the companion, then start a new request.", None)
            if any(word in message for word in ("usage", "cost", "model identifier", "refused")):
                return ("The provider could not safely complete this request. Check its access and billing status in Studio before starting again.", None)
            return ("I couldn't get a usable reply from the model. The connection or provider may be unavailable.",
                    "Check the connection. Would you like me to try your original request once more?")
        if isinstance(error, AgentError):
            if any(word in message for word in ("budget", "accounting", "reserved cost", "reported usage")):
                return ("The model spending limit or billing check stopped this request. Review the budget in Studio; I won't raise it or retry automatically.", None)
            if "declined" in message or "approval expired" in message:
                return ("That computer action was not approved, so I stopped. Start a new request if you want to reconsider it.", None)
            if any(word in message for word in ("permission", "enable computer", "access is disabled", "chrome", "helper unavailable")):
                return ("The Mac's native access or paired connection is unavailable. Check the Mac permission status in Studio.",
                        "Once access is restored, should I continue the original request?")
            if any(word in message for word in ("disconnected", "synchroniz", "acknowledg", "activation", "timed out")):
                return ("I couldn't confirm the operation with the device or computer. Check the connection and what is currently visible before retrying.",
                        "After checking the connection and current result, should I try the original request once more?")
            if "question limit" in message:
                return ("I still need a clearer goal. Please start a new request that says what should happen and which app or device to use.", None)
            if "limit" in message or "same operation failed" in message:
                return ("I tried to repair the request but reached the attempt limit. Your current app is still available; the details are in Studio.", None)
        return ("An unexpected error stopped this request. Your active app is still available. Check Studio and describe what happened before starting a new request.", None)

    def request(self, text, source="website", followup_id=None, *, _library_entry=None):
        if source == "microphone":
            self.require_permission("voice")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
            raise AgentError("Request must contain 1–4000 characters")
        with self.lock:
            if self.running:
                raise AgentError("The agent is already working; cancel it or wait")
            if not self.connected():
                raise AgentError("The physical controller is not connected")
            if self.device_revision != self.revision:
                raise AgentError("Wait for the controller and host to finish synchronizing")
            followup = self._followup(followup_id) if _library_entry is None else None
            job_sequence = self.progress["job_sequence"] + 1
            if job_sequence >= 2**53:
                raise AgentError("Request sequence limit reached")
            self.running = True
            self.response = None
            self._stop_speech()
            self.computer_approved_action = None
            self.computer.begin_task()
            self.agent.turn_actions = []
            self.agent.loaded_skills = []
            self.agent.cancelled.clear()
            self.agent.clarification = None
            self.agent.private_request = bool(followup and followup.get("private"))
            self.computer_focus_pending = True
            job_id = uuid.uuid4().hex
            self.progress = {"job_id": job_id, "job_sequence": job_sequence, "request_id": None, "phase": "queued",
                             "title": "Request received", "tool": None, "role": "orchestrator"}
            self.summary = "Your request is queued."
            self.clarification = None
            self.conversation = (followup["context"] if followup else
                                 {"original": text.strip(), "history": [], "questions": 0, "recoveries": 0})
            if followup and followup["kind"] == "recovery":
                self.conversation["recoveries"] += 1
            self.current_request = text.strip()
            memory_generation = self.memory_generation
            if source == "microphone":
                self.voice_draft = {"job_id": job_id, "text": text.strip(),
                                    "send_at": time.time() + 3, "editing": False}
                self.draft_deadline = time.monotonic() + 3
                self.progress["title"] = "Review in Studio"
                self.summary = "Heard your request. Edit in Studio or say Hey Meta, cancel rebuild."
            try:
                self._save_job()
            except Exception:
                self.running = False
                self.voice_draft = None
                self.draft_deadline = None
                self.conversation = self.current_request = None
                self.progress.update(phase="error", title="Could not start")
                self.summary = "The companion could not save the request status."
                raise AgentError(self.summary) from None

        def work():
            self.job_context.job_id = job_id
            outcome = "ready"
            summary = "The request stopped before returning a result."
            try:
                with self.changed:
                    while self.voice_draft and self.voice_draft["job_id"] == job_id:
                        if self.progress["phase"] == "cancelled":
                            break
                        remaining = None if self.draft_deadline is None else self.draft_deadline - time.monotonic()
                        if remaining is not None and remaining <= 0:
                            break
                        self.changed.wait(0.25 if remaining is None else min(remaining, 0.25))
                    if self.progress["phase"] == "cancelled":
                        raise AgentError("Cancelled by user")
                    request_text = self.voice_draft["text"] if self.voice_draft else text.strip()
                    self.voice_draft = None
                    self.draft_deadline = None
                    raw_human_reply = request_text
                    if followup:
                        answer = request_text
                        if not self.conversation["original"]:
                            self.conversation["original"] = answer
                        history = "\n".join("Question: " + item["question"] + "\nReply: " + item["answer"]
                                            for item in self.conversation["history"])
                        request_text = ("Previous request: " + self.conversation["original"] +
                                        "\nEarlier conversation: " + history +
                                        "\nClarifying question: " + followup["question"] +
                                        "\nUser's reply (may replace the request): " + answer)
                        self.conversation["history"] = (self.conversation["history"] +
                            [{"question": followup["question"], "answer": answer}])[-_MAX_QUESTIONS:]
                    self.current_request = request_text
                try:
                    self.hardware.note_user(raw_human_reply)
                except ValueError as error:
                    request_text += "\nHardware step was not confirmed: " + str(error)[:300]
                self.check_request_access()
                if _library_entry is not None:
                    opened = self.app_library.launch(_library_entry)
                    result = "Opened “" + opened["title"] + "”."
                elif followup and followup.get("kind") == "library_purge":
                    result = self.app_library.human_reply(followup["library_confirmation"], raw_human_reply)
                else:
                    result = (self.agent.run(request_text, private=True) if followup and followup.get("private")
                              else self.agent.run(request_text))
                summary = result if isinstance(result, str) else "Request finished."
            except Exception as error:
                summary, question = self._failure_guidance(error)
                with self.lock:
                    if (question and self.conversation and not self.agent.cancelled.is_set()
                            and self.conversation["recoveries"] < 1
                            and self.conversation["questions"] < _MAX_QUESTIONS):
                        self._question(question, kind="recovery")
                        summary += " " + question
                    elif question:
                        summary += " I've stopped retrying. Start a new request when you're ready."
                outcome = "error"
            finally:
                with self.lock:
                    if self.progress["job_id"] == job_id:
                        if self.progress["phase"] == "cancelled":
                            outcome = "cancelled"
                        self.running = False
                        self.voice_draft = None
                        self.draft_deadline = None
                        if outcome in {"ready", "error"}:
                            self._publish_response(summary, job_id)
                        self.summary = ("Task complete. Response available in Studio." if self.agent.private_request
                                        and outcome == "ready" else "Computer request stopped." if self.agent.private_request
                                        else summary[:500])
                        self.progress.update(phase=outcome, title={"ready": "Ready", "error": "Could not finish",
                                             "cancelled": "Request cancelled"}[outcome], tool=None, role="orchestrator")
                        if memory_generation == self.memory_generation:
                            try:
                                self.intent_memory.append(self.current_request or text.strip(), summary,
                                    "awaiting_answer" if self.clarification else {"ready": "completed", "error": "failed", "cancelled": "cancelled"}[outcome],
                                    actions=self.agent.turn_actions, skills=self.agent.loaded_skills,
                                    private=self.agent.private_request)
                                self.memory_error = None
                            except (OSError, ValueError, TypeError):
                                self.memory_error = "Recent context could not be saved"
                        if self.clarification:
                            self.progress["title"] = "One quick question"
                        else:
                            self.conversation = self.current_request = None
                        try:
                            self._save_job()
                        except Exception:
                            self.progress.update(phase="error", title="Could not save request status")
                            self.summary = "The request ended, but its status could not be saved."
                        self.changed.notify_all()
                del self.job_context.job_id
        try:
            threading.Thread(target=work, name="modulate-agent", daemon=True).start()
        except Exception:
            with self.lock:
                self.running = False
                self.voice_draft = None
                self.draft_deadline = None
                self.conversation = self.current_request = None
                self.progress.update(phase="error", title="Could not start")
                self.summary = "The companion could not start this request."
                self._save_job()
            raise AgentError(self.summary) from None
        return {"accepted": True, "source": source, "job_id": job_id, "job_sequence": job_sequence}

    def request_clarification(self, question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 180 or not question.strip().isprintable():
            raise AgentError("Ask one short, printable question")
        with self.lock:
            if (not self.running or self.agent.cancelled.is_set()
                    or getattr(self.job_context, "job_id", None) != self.progress["job_id"]):
                raise AgentError("This request is no longer active")
            self._question(question.strip())
            return {"clarification_required": True, "question": question.strip()}

    def draft(self, job_id, action, text=None):
        with self.changed:
            if (not self.running or not self.voice_draft or self.voice_draft["job_id"] != job_id
                    or self.progress["phase"] == "cancelled"):
                raise AgentError("That voice draft has already been sent or discarded")
            if action == "discard":
                return self.cancel(job_id)
            if action not in {"pause", "send"}:
                raise AgentError("Unknown draft action")
            if text is not None:
                if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
                    raise AgentError("Draft must contain 1–2000 characters")
                self.voice_draft["text"] = text.strip()
            self.voice_draft["editing"] = action == "pause"
            self.voice_draft["send_at"] = None if action == "pause" else time.time()
            self.draft_deadline = None if action == "pause" else 0
            self.changed.notify_all()
            return {"accepted": True, "job_id": job_id, "action": action}

    def cancel(self, job_id=None, *, shutdown=False):
        with self.changed:
            if job_id is not None and job_id != self.progress["job_id"]:
                return {"cancelled": False, "reason": "That request has already finished"}
            if job_id is not None and not self.running and not (
                    self.clarification and job_id == self.clarification["job_id"]):
                return {"cancelled": False, "reason": "That request has already finished"}
            if shutdown:
                self.hardware.withdraw()
            else:
                self.hardware.call("cancel")
            if (not self.running and self.clarification
                    and (job_id is None or job_id == self.clarification["job_id"])):
                self.clarification = None
                self.conversation = self.current_request = None
                self._stop_speech()
                self.response = None
                return {"cancelled": True, "dismissed_question": True}
            if job_id is not None and (not self.running or job_id != self.progress["job_id"]):
                return {"cancelled": False, "reason": "That request has already finished"}
            self.agent.cancelled.set()
            self.speaker_volume.disconnect()
            self.stop_computer_audio()
            self.computer.cancel()
            self._stop_speech()
            self.response = None
            self.computer_approval_decision = False
            self.computer_approved_action = None
            self.clarification = None
            self.conversation = self.current_request = None
            if self.running:
                self.progress.update(phase="cancelled", title="Stopping the request", tool=None)
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
        self.app_library.note_activation(record)
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
                self.validate_camera(package)
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
                commands = validate_commands(commands, frame_package["assets"]["sprites"], bool(frame_package.get("camera")))
            retired = self.retired_sessions | ({self.source_session} if switching and self.source_session else set())
            # Persist the anti-replay watermark before acknowledgements or host actions.
            _save_json(self.sequence_path, {"source": session_id, "last_sequence": sequence, "retired": sorted(retired)})
            self.source_session, self.last_packet, self.retired_sessions = session_id, sequence, retired
            self.device = {"name": name, "controls": list(names), "devices": copy.deepcopy(devices),
                           "warnings": list(warnings), "button_sources": dict(button_sources)}
            self.last_seen = time.monotonic()
            self.input, self.device_revision, self.telemetry = sample, revision, copy.deepcopy(telemetry)
            self.speaker_volume.observe(telemetry.get("speaker_volume"), session_id)
            self.hardware.observe(telemetry.get("hardware"), session_id)
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
            self._sync_computer_pairing()
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
            if isinstance(packet.get("audio_stopped"), str):
                self.stop_computer_audio(packet["audio_stopped"])
            self._sync_camera()
            if self.active and self.device_revision == self.revision:
                if self.active["package"]["kind"] == "game" and commands:
                    commands = validate_commands(commands, self.active["package"]["assets"]["sprites"], bool(self.active["package"].get("camera")))
                    if not self.renderer:
                        self.renderer = Renderer(self.active["package"])
                    camera_image = None
                    if self.active["package"].get("camera") and self.camera and self._camera_wanted():
                        camera_frame = self.camera.frame()
                        if camera_frame:
                            from io import BytesIO
                            from PIL import Image
                            camera_image = Image.open(BytesIO(camera_frame["jpeg"])).convert("RGB")
                    self._device_preview(png(self.renderer.render(commands, camera_image)))
                elif (self.active["package"]["kind"] == "control" and self.volume_token
                      and not self.app_library.view["open"] and self.permission_allowed("system")):
                    package = self.active["package"]
                    try:
                        self.validate_control(package)
                        session = self.bridge.session(self.volume_token)
                        setting_action = package["bindings"][0]["action"]
                        delta = max(-10, min(10, self.input["encoder_delta"] * package["bindings"][0]["scale"]))
                        if delta:
                            self.volume_read_at = time.monotonic()
                            self.volume = self.bridge.execute(self.volume_token, session["next_sequence"], setting_action, delta)
                            self.volume_read_at = time.monotonic()
                        elif self.volume_read_at is None or time.monotonic() - self.volume_read_at >= 1:
                            # Poll only the trusted host bridge. A failed poll also
                            # consumes this interval, even if the token is resent.
                            self.volume_read_at = time.monotonic()
                            self.volume = self.bridge.execute(self.volume_token, session["next_sequence"], setting_action.replace(".delta", ".get"))
                            self.volume_read_at = time.monotonic()
                    except (BridgeError, AgentError):
                        self.volume_token = None
                        self.volume = None
            pending = None
            if self.pending:
                pending = {key: self.pending[key] for key in ("id", "revision", "phase", "base_revision")}
                if self.pending["phase"] == "stage":
                    pending["package"] = self.pending["package"]
            return {**self._assistant_heartbeat(packet),
                    "hardware_command": self.hardware.offer(session_id),
                    "hardware_workflow": self.hardware.inspect().get("workflow"),
                    "speaker_volume": self.speaker_volume.offer(session_id),
                    "camera_frame": self._camera_packet(), "computer_audio": self.audio_offer(),
                    "activation": pending, "active_revision": self.revision, "wake": self.wake and self.permission_allowed("voice"),
                    "agent_running": self.running, "agent_state": self.agent_state(),
                    "clarification": self._clarification_state(),
                    "setup_status": self.connection_guide.brief(),
                    "setup": self.connection_guide.device_offer(),
                    "library": self.app_library.device_state(),
                    "volume": self.volume, "paired": bool(self.capabilities()["paired_host"]),
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
            self.intent_memory.clear()
            self.memory_generation += 1
            self.volume_read_at = time.monotonic()
            self.pairing = None
            return {"token": token, "session_id": session["session_id"], "capabilities": session["capabilities"]}

    def create_pairing(self):
        with self.lock:
            self.pairing = self.bridge.create_pairing()
            return copy.deepcopy(self.pairing)

    def revoke(self):
        with self.lock:
            self.intent_memory.clear()
            self.memory_generation += 1
            self.speaker_volume.disconnect()
            self.hardware.call("cancel")
            self.bridge.revoke_all()
            self.volume_token = None
            self.volume = None
            self.volume_read_at = None
            self.pairing = None
            self.computer.revoke()
            self.stop_computer_audio()
            if self.camera:
                self.camera.stop()
            if self.running:
                self.cancel()
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
                    "agent": self.agent_state(),
                    "selected_skills": list(self.agent.loaded_skills),
                    "hardware": self.hardware.inspect(),
                    "computer": self.computer_status(), "response": self._response_state(),
                    "camera": self.camera_status(), "computer_audio": self.audio_status(),
                    "speaker_volume": self.speaker_volume.status(),
                    "memory": {"turns": len(self.intent_memory.snapshot()), "limit": self.intent_memory.LIMIT,
                               "error": self.memory_error, "hours": self.intent_memory.TTL // 3600},
                    "speech": self.speech_status(),
                    "voice_draft": copy.deepcopy(self.voice_draft),
                    "clarification": self._clarification_state(),
                    "events": list(self.events), "volume": self.volume,
                    "paired": bool(self.capabilities()["paired_host"]), "wake": self.wake and self.permission_allowed("voice"),
                    "remote": self.remote_access.local_status() if self.remote_access else {"enabled": False},
                    "setup_status": self.connection_guide.status(),
                    "library": self.app_library.snapshot(),
                    "preview_version": self.preview_version,
                    "candidate_preview_version": self.candidate_preview_version}
