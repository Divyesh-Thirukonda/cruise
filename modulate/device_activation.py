"""Device-side verification, staged display activation, and durable recovery.

Only confirmed packages survive restart. Driver completion acknowledges a
software render, not optical readback. No host action is executed here.
"""

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from .game_runtime import Game, GameError, validate_package, verify
from .rendering import Renderer


TIMEOUT_SECONDS = 12
_REVISION = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_LOG = logging.getLogger(__name__)


class ActivationError(ValueError):
    pass


def digest(package):
    try:
        encoded = json.dumps(package, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise ActivationError("Package must be finite JSON") from None
    return hashlib.sha256(encoded).hexdigest()


def _copy(value):
    return json.loads(json.dumps(value))


@dataclass
class _Running:
    revision: str
    package: dict
    game: object
    renderer: object
    frame: dict
    image: object

    def close(self):
        if self.game is not None:
            try:
                self.game.close()
            except Exception:
                pass  # Cleanup failure cannot undo an already committed pointer.

    def record(self):
        return {"revision": self.revision, "package": _copy(self.package)}


class DeviceActivation:
    def __init__(self, directory, present, controls, paired_target):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "device-active.json"
        self.present, self.controls, self.paired_target = present, controls, paired_target
        self._lock = threading.RLock()
        self._active = self._previous = self._pending = None
        self._ack = self._failure = None
        self._error = None
        self._finished = set()
        self._closed = False
        self._load()

    def _validate(self, package):
        if type(package) is not dict:
            raise ActivationError("Package must be an object")
        available = set(self.controls())
        if package.get("kind") == "game":
            normalized = validate_package(package)
            if not set(normalized["controls"]) <= available:
                raise ActivationError("A required game control is unavailable")
            return normalized
        if set(package) != {"kind", "title", "target", "bindings"} or package.get("kind") != "control":
            raise ActivationError("Unsupported control package fields")
        title = package["title"]
        if (type(title) is not str or not 1 <= len(title) <= 80 or not title.strip()
                or any(ord(char) < 32 or ord(char) > 126 for char in title)):
            raise ActivationError("Control title must contain 1 to 80 printable ASCII characters")
        target = package["target"]
        if type(target) is not str or not target or len(target) > 128 or target != self.paired_target():
            raise ActivationError("Control target does not match the current paired session")
        if "encoder" not in available:
            raise ActivationError("Encoder control is unavailable")
        bindings = package["bindings"]
        if type(bindings) is not list or len(bindings) != 1:
            raise ActivationError("Exactly one encoder binding is required")
        binding = bindings[0]
        if (type(binding) is not dict or set(binding) != {"control", "action", "scale"}
                or binding["control"] != "encoder" or binding["action"] != "volume.delta"
                or type(binding["scale"]) is not int or not 1 <= abs(binding["scale"]) <= 10):
            raise ActivationError("Only encoder to volume.delta with nonzero scale -10 to 10 is allowed")
        return _copy(package)

    def _prepare(self, package):
        package = self._validate(package)
        game = None
        try:
            if package["kind"] == "game":
                report = verify(package)
                if report.get("passed") is not True:
                    raise ActivationError("Device's independent game verification failed")
                game = Game(package)
                frame = game.initial_frame
            else:
                frame = {"state": {}, "commands": [
                    {"op": "clear", "color": "#101820"},
                    {"op": "text", "x": 8, "y": 10, "text": package["title"][:25], "size": 14, "color": "#64E3B5"},
                    {"op": "text", "x": 8, "y": 52, "text": "Turn encoder for volume", "size": 12, "color": "#FFFFFF"},
                    {"op": "text", "x": 8, "y": 88, "text": "Paired computer", "size": 12, "color": "#D6DFE7"},
                ]}
            renderer = Renderer(package)
            image = renderer.render(frame["commands"])
            return _Running(digest(package), package, game, renderer, frame, image)
        except BaseException:
            if game is not None:
                game.close()
            raise

    def _idle(self):
        return Renderer({}).render([
            {"op": "clear", "color": "#101820"},
            {"op": "text", "x": 10, "y": 30, "text": "No active program", "size": 14, "color": "#FFFFFF"},
        ])

    def _read(self):
        if self.path.stat().st_size > 512_000:
            raise ActivationError("Saved device state is oversized")
        record = json.loads(self.path.read_text())
        if type(record) is not dict or record.get("version") != 1:
            raise ActivationError("Invalid saved device state")
        for key in ("active", "previous"):
            item = record.get(key)
            if item is not None and (type(item) is not dict or set(item) != {"revision", "package"}
                                     or item["revision"] != digest(item["package"])):
                raise ActivationError("Saved package integrity check failed")
        failure = record.get("failure")
        if failure is not None and (type(failure) is not dict
                or set(failure) != {"revision", "restored_revision", "error"}
                or type(failure["revision"]) is not str or not _REVISION.fullmatch(failure["revision"])
                or (failure["restored_revision"] is not None
                    and (type(failure["restored_revision"]) is not str
                         or not _REVISION.fullmatch(failure["restored_revision"])))
                or type(failure["error"]) is not str or len(failure["error"]) > 300):
            raise ActivationError("Invalid saved failure state")
        intent = record.get("intent")
        if intent is not None and (type(intent) is not dict or set(intent) != {"id", "revision", "base_revision"}
                or type(intent["id"]) is not str or not _IDENTIFIER.fullmatch(intent["id"])
                or type(intent["revision"]) is not str or not _REVISION.fullmatch(intent["revision"])
                or intent["base_revision"] != (record["active"]["revision"] if record.get("active") else None)):
            raise ActivationError("Invalid saved activation intent")
        return record

    def _save(self, active, previous, failure=None, intent=None):
        record = {"version": 1, "active": active, "previous": previous, "failure": failure, "intent": intent}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix=".device-active-", delete=False) as handle:
                temporary = handle.name
                os.chmod(temporary, 0o600)
                json.dump(record, handle, allow_nan=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            # Atomic replacement is the commit point. Nothing fallible follows
            # it here; interruption recovery also checks the persisted record.
            os.replace(temporary, self.path)
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _load(self):
        if not self.path.exists():
            return
        record = None
        try:
            record = self._read()
            self._previous = record.get("previous")
            self._failure = record.get("failure")
            if self._failure:
                self._error = self._failure["error"]
            if record.get("active") is not None:
                active = self._prepare(record["active"]["package"])
                try:
                    self.present(active.image)
                except BaseException:
                    active.close()
                    raise
                self._active = active
        except Exception:
            self._error = "Saved program could not be verified or presented"
            # Only a structurally valid, integrity-checked record can supply a
            # predecessor. Never overwrite unreadable state with a new guess.
            if record and record.get("active"):
                recovered = None
                if self._previous:
                    try:
                        recovered = self._prepare(self._previous["package"])
                        self.present(recovered.image)
                        self._active = recovered
                    except Exception:
                        if recovered:
                            recovered.close()
                self._previous = None
                self._failure = {"revision": record["active"]["revision"],
                                 "restored_revision": self._active.revision if self._active else None,
                                 "error": "Saved active program failed independent startup verification or presentation"}
                try:
                    self._save(self._active.record() if self._active else None, None, self._failure)
                except Exception:
                    self._error += "; recovery could not be persisted"
        if record and record.get("intent"):
            self._failure = {"revision": record["intent"]["revision"],
                             "restored_revision": self._active.revision if self._active else None,
                             "error": "Restart interrupted activation before confirmation"}
            self._error = self._failure["error"]
            try:
                self._save(self._active.record() if self._active else None, self._previous, self._failure)
            except Exception:
                self._error += "; recovery could not be persisted"

    def _finish(self, transaction, phase, error=None):
        self._ack = {"id": transaction["id"], "revision": transaction["revision"], "phase": phase}
        if error:
            self._ack["error"] = error
            self._error = error
        self._finished.add(transaction["id"])
        if len(self._finished) > 128:
            # Only the current transaction needs exact replay response. Bases
            # and package hashes still protect older evicted transaction IDs.
            self._finished = {transaction["id"]}
        self._pending = None

    def _rollback_pending(self, error):
        pending = self._pending
        if pending is None:
            return
        if pending["phase"] == "activated":
            self._active = pending["old"]
            try:
                self.present(self._active.image if self._active else self._idle())
            except Exception:
                error += "; previous display could not be presented"
            self._failure = {"revision": pending["revision"],
                             "restored_revision": self._active.revision if self._active else None,
                             "error": error}
            try:
                self._save(self._active.record() if self._active else None, self._previous, self._failure)
            except Exception:
                error += "; recovery could not be persisted"
        pending["candidate"].close()
        self._finish(pending, "failed", error)

    def _expire(self):
        if self._pending and time.monotonic() >= self._pending["deadline"]:
            self._rollback_pending("Device activation timed out before confirmation")

    @staticmethod
    def _envelope(message):
        if type(message) is not dict or not {"id", "revision", "base_revision", "phase"} <= message.keys():
            raise ActivationError("Activation message is missing required fields")
        if (type(message["id"]) is not str or not _IDENTIFIER.fullmatch(message["id"])
                or type(message["revision"]) is not str or not _REVISION.fullmatch(message["revision"])
                or (message["base_revision"] is not None
                    and (type(message["base_revision"]) is not str or not _REVISION.fullmatch(message["base_revision"])))):
            raise ActivationError("Invalid activation identity or revision")
        if message["phase"] not in ("stage", "commit", "confirmed", "abort"):
            raise ActivationError("Unknown activation phase")
        fields = {"id", "revision", "base_revision", "phase"}
        if message["phase"] == "stage":
            fields.add("package")
        if set(message) != fields:
            raise ActivationError("Unexpected activation message fields")

    def process(self, message):
        with self._lock:
            self._expire()
            if message is None or self._closed:
                return self._snapshot()
            try:
                self._envelope(message)
            except ActivationError as error:
                self._error = str(error)
                return self._snapshot()
            if message["id"] in self._finished:
                return self._snapshot()
            pending = self._pending
            if pending is not None:
                if any(message[key] != pending[key] for key in ("id", "revision", "base_revision")):
                    return self._snapshot()  # A foreign/stale phase cannot affect this transaction.
                if message["phase"] == "stage":
                    try:
                        matches = digest(message["package"]) == pending["revision"]
                    except ActivationError:
                        matches = False
                    if not matches:
                        self._rollback_pending("Staged package changed within the activation transaction")
                    return self._snapshot()
            elif message["phase"] != "stage":
                return self._snapshot()
            try:
                phase = message["phase"]
                if phase == "stage":
                    if self._failure is not None:
                        raise ActivationError("Host must acknowledge runtime recovery before another activation")
                    base = self._active.revision if self._active else None
                    if message["base_revision"] != base:
                        raise ActivationError("Stale base revision; current program preserved")
                    if digest(message["package"]) != message["revision"]:
                        raise ActivationError("Candidate revision does not match package contents")
                    deadline = time.monotonic() + TIMEOUT_SECONDS
                    candidate = self._prepare(message["package"])
                    self._pending = {**message, "candidate": candidate, "old": self._active,
                                     "deadline": deadline, "phase": "ready"}
                    if candidate.revision != message["revision"]:
                        raise ActivationError("Normalized package revision changed")
                    if time.monotonic() >= deadline:
                        raise ActivationError("Device verification exceeded activation deadline")
                    self._error = None
                    self._ack = {"id": message["id"], "revision": candidate.revision, "phase": "ready"}
                elif phase == "commit":
                    if pending["phase"] == "activated":
                        return self._snapshot()
                    self._validate(pending["candidate"].package)
                    if (self._active.revision if self._active else None) != pending["base_revision"]:
                        raise ActivationError("Active program changed before commit")
                    # Mark rollback ownership before a driver that could update
                    # the physical display and then fail or be interrupted.
                    pending["phase"] = "activated"
                    self._save(self._active.record() if self._active else None, self._previous,
                               intent={key: pending[key] for key in ("id", "revision", "base_revision")})
                    self.present(pending["candidate"].image)
                    self._active = pending["candidate"]
                    pending["deadline"] = time.monotonic() + TIMEOUT_SECONDS
                    self._ack = {"id": pending["id"], "revision": pending["revision"], "phase": "activated"}
                elif phase == "confirmed":
                    if pending["phase"] != "activated":
                        raise ActivationError("Confirmation arrived before device activation")
                    self._validate(self._active.package)
                    previous = pending["old"].record() if pending["old"] else None
                    self._save(self._active.record(), previous)
                    self._previous = previous
                    if pending["old"]:
                        pending["old"].close()
                    self._finish(pending, "confirmed")
                elif phase == "abort":
                    self._rollback_pending("Host aborted device activation")
            except BaseException as error:
                # An interruption immediately after atomic replacement must
                # reconcile with that commit instead of displaying old state.
                committed = False
                if self._pending and self._pending["phase"] == "activated" and message["phase"] == "confirmed":
                    try:
                        saved = self._read()
                        committed = saved["active"] == self._active.record()
                    except Exception:
                        pass
                if committed:
                    self._previous = saved.get("previous")
                    if self._pending["old"]:
                        self._pending["old"].close()
                    self._finish(self._pending, "confirmed")
                elif self._pending:
                    self._rollback_pending(str(error) if isinstance(error, ActivationError)
                                           else "Device activation failed; previous program preserved")
                else:
                    self._finish(message, "failed", str(error) if isinstance(error, ActivationError)
                                 else "Device rejected candidate verification or setup")
                if not isinstance(error, Exception):
                    raise
            return self._snapshot()

    @staticmethod
    def _failure_category(stage, error):
        """Keep arbitrary generated exception messages out of logs and state."""
        if stage == "present":
            return "display_error"
        if stage == "render":
            return "render_error"
        if isinstance(error, GameError):
            message = str(error)
            known = {
                "Game worker exceeded its wall-clock deadline": "worker_deadline",
                "Game worker is closed": "worker_closed",
                "Game worker exited without a result": "worker_exit",
                "Game worker output is oversized": "worker_output_limit",
                "Worker request is oversized": "worker_input_limit",
                "Unexpected extra worker output": "worker_protocol",
                "Worker response sequence mismatch": "worker_protocol",
                "Invalid game worker response": "worker_protocol",
            }
            if message in known:
                return known[message]
            if message.split("\n", 1)[0] == "InternalError: interrupted":
                return "engine_interrupt"
            return "game_error"
        return "step_error"

    def _runtime_failed(self, diagnostic=""):
        failed = self._active
        if self._pending and self._pending["phase"] == "activated":
            self._rollback_pending("Candidate runtime failed before confirmation" + diagnostic)
            return
        if self._pending:
            self._rollback_pending("Current runtime failed while staging a candidate")
        revision = failed.revision
        failed.close()
        self._active = None
        recovered = None
        if self._previous is not None:
            try:
                recovered = self._prepare(self._previous["package"])
                self.present(recovered.image)
                self._active = recovered
            except Exception:
                if recovered:
                    recovered.close()
        if self._active is None:
            try:
                self.present(self._idle())
            except Exception:
                pass
        self._previous = None
        self._failure = {"revision": revision, "restored_revision": self._active.revision if self._active else None,
                         "error": ("Game runtime or display failed; previous verified package restored"
                         if self._active else "Game runtime or display failed; no usable previous package") + diagnostic}
        self._error = self._failure["error"]
        self._ack = None
        try:
            self._save(self._active.record() if self._active else None, None, self._failure)
        except Exception:
            self._error += "; recovery could not be persisted"

    def tick(self, input, dt):
        with self._lock:
            self._expire()
            if self._closed or self._active is None or self._active.game is None:
                return None
            stage = "step"
            started = time.monotonic()
            try:
                frame = self._active.game.step(input, dt)
                stage, started = "render", time.monotonic()
                image = self._active.renderer.render(frame["commands"])
                stage, started = "present", time.monotonic()
                self.present(image)
                self._active.frame, self._active.image = frame, image
                return _copy(frame)
            except Exception as error:
                elapsed_ms = max(0, min(60_000, round((time.monotonic() - started) * 1000)))
                category = self._failure_category(stage, error)
                _LOG.error("Game runtime failure stage=%s category=%s elapsed_ms=%d", stage, category, elapsed_ms)
                self._runtime_failed(f" [stage={stage} category={category} elapsed_ms={elapsed_ms}]")
                return None

    def acknowledge_failure(self, value):
        with self._lock:
            if (self._failure is not None and type(value) is dict
                    and value.get("revision") == self._failure["revision"]
                    and value.get("restored_revision") == self._failure["restored_revision"]):
                try:
                    self._save(self._active.record() if self._active else None, self._previous, None)
                except Exception:
                    self._error = "Runtime recovery acknowledgment could not be persisted"
                    return False
                self._failure = None
                return True
            return False

    def _snapshot(self):
        active = self._active
        return {"revision": active.revision if active else None,
                "kind": active.package["kind"] if active else None,
                "title": active.package["title"] if active else None,
                "ack": _copy(self._ack), "error": self._error, "failure": _copy(self._failure),
                "pending": self._pending["phase"] if self._pending else None}

    def snapshot(self):
        with self._lock:
            self._expire()
            return self._snapshot()

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self._pending:
                self._rollback_pending("Device stopped before activation confirmation")
            if self._active:
                self._active.close()
            self._closed = True
