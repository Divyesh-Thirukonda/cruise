"""Trusted, serialized Pi diagnostics and one explicitly isolated button repair.

The host obtains fresh physical-isolation confirmation. This worker independently
checks the boot, session, deadline and bus evidence. Generated code never receives
register access. An uncertain EEPROM operation is consumed, never retried.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid

from .controls import BUTTON_TARGETS
from .driver_setup import DRIVER_ID, DriverSetupError

_HEX_ID = re.compile(r"[0-9a-f]{32}\Z")
_ACTIONS = {"scan", "reinitialize", "readdress_button", "install_driver"}
_MAX_JOURNAL = 256  # Never prune consumed mutations and silently make them replayable.


def _id(value):
    return isinstance(value, str) and _HEX_ID.fullmatch(value) is not None


def _boot_id():
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if str(uuid.UUID(value)) != value:
        raise ValueError("Invalid kernel boot identity")
    return value


class HardwareDevice:
    def __init__(self, controls, directory, session, *, backend=None,
                 clock=time.time, boot_id=None, sleep=time.sleep, driver_setup=None):
        if not _id(session):
            raise ValueError("Invalid device session")
        self.controls, self.session = controls, session
        self.driver_setup = driver_setup
        self._backend = backend
        self._clock, self._sleep = clock, sleep
        try:
            self.boot_id = _boot_id() if boot_id is None else str(uuid.UUID(boot_id))
            self.supported = True
        except (OSError, ValueError, TypeError, AttributeError):
            self.boot_id, self.supported = None, False
        self._path = Path(directory) / "hardware-repairs.json"
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self._thread = None
        self._pending = None
        self._generation = 0
        self._active = None
        self._seen = {}
        self._report, self._ack = None, None
        self._last_discovery = 0
        self._journal = {}
        self._journal_ok = True
        self._load()

    def _load(self):
        try:
            if not self._path.exists():
                return
            if self._path.stat().st_size > 512_000:
                raise ValueError("Oversized journal")
            data = json.loads(self._path.read_text())
            if (not isinstance(data, dict) or set(data) != {"version", "consumed"}
                    or data["version"] != 1 or not isinstance(data["consumed"], dict)
                    or len(data["consumed"]) > _MAX_JOURNAL):
                raise ValueError("Invalid journal")
            for identifier, record in data["consumed"].items():
                if (not _id(identifier) or not isinstance(record, dict)
                        or set(record) != {"target", "status"}
                        or type(record["target"]) is not int or record["target"] not in BUTTON_TARGETS
                        or record["status"] not in {"consumed", "done", "uncertain"}):
                    raise ValueError("Invalid journal record")
            self._journal = data["consumed"]
        except (OSError, ValueError, TypeError):
            # Missing history is not permission to repeat a persistent operation.
            self._journal_ok = False

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({"version": 1, "consumed": self._journal},
                         separators=(",", ":"), allow_nan=False).encode()
        fd, name = tempfile.mkstemp(prefix=".hardware-repairs-", dir=self._path.parent)
        temporary = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
            # Rename durability matters before an EEPROM write, not just process exit.
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def start(self):
        with self._lock:
            if self._closed or self._thread is not None or not self.supported:
                return
            self._thread = threading.Thread(target=self._run, name="hardware-diagnostics", daemon=True)
            self._thread.start()

    def close(self):
        with self._lock:
            self._closed = True
            self._generation += 1
            self._pending = self._active = None
            self._wake.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)

    def snapshot(self):
        with self._lock:
            return deepcopy({"supported": self.supported, "boot_id": self.boot_id,
                             "session": self.session, "report": self._report, "ack": self._ack})

    def _validate(self, command):
        if (not isinstance(command, dict) or set(command) !=
                {"id", "session", "boot_id", "expires_at", "action", "target"}
                or not _id(command["id"]) or command["session"] != self.session
                or command["boot_id"] != self.boot_id or not isinstance(command["action"], str)
                or command["action"] not in _ACTIONS
                or type(command["expires_at"]) not in (int, float)
                or not math.isfinite(command["expires_at"])
                or not self._clock() < command["expires_at"] <= self._clock() + 60):
            return False
        return ((command["action"] == "readdress_button" and type(command["target"]) is int
                 and command["target"] in BUTTON_TARGETS)
                or (command["action"] == "install_driver" and command["target"] == DRIVER_ID
                    and self.driver_setup is not None)
                or (command["action"] in {"scan", "reinitialize"} and command["target"] is None))

    def offer(self, command):
        with self._lock:
            if command is None:
                if self._active is not None or self._pending is not None:
                    self._generation += 1
                    self._active = self._pending = None
                return True
            if self._closed or not self.supported or not self._validate(command):
                return False
            identifier = command["id"]
            if identifier in self._seen:
                self._ack = deepcopy(self._seen[identifier])
                return True
            if identifier == self._active:
                return True
            self._generation += 1
            self._active = identifier
            self._pending = (dict(command), self._generation)
            self._wake.set()
            return True

    def _allowed(self, command, generation):
        # Caller holds _lock when this guards a mutation.
        return (not self._closed and generation == self._generation
                and self._active == command["id"] and self._validate(command))

    def _scan(self, identifier):
        report = self.controls.hardware_scan(identifier, backend=self._backend)
        if self.driver_setup is not None:
            report["driver_setup"] = self.driver_setup.inspect(self.controls)
        if not self._journal_ok:
            report["warnings"].append("Repair history is unreadable; address changes are disabled")
        with self._lock:
            self._report = deepcopy(report)
            self._last_discovery = time.monotonic()
        return report

    def _finish(self, command, generation, status, result, error=None):
        ack = {"id": command["id"], "action": command["action"],
               "status": status, "result": deepcopy(result), "error": error}
        with self._lock:
            self._seen[command["id"]] = ack
            if len(self._seen) > 128:
                self._seen.pop(next(iter(self._seen)))
            # A withdrawn command can have completed; retain its ack, but never
            # overwrite a different command's current acknowledgement.
            if self._active in (None, command["id"]):
                self._ack = ack
            if self._active == command["id"]:
                self._active = None

    def _run(self):
        try:
            self._scan(uuid.uuid4().hex)  # Startup is read-only, never journal replay.
        except Exception:
            pass
        while True:
            signalled = self._wake.wait(5)
            with self._lock:
                self._wake.clear()
                if self._closed:
                    return
                pending, self._pending = self._pending, None
            if pending is not None:
                self._execute(*pending)
            elif not signalled:
                try:
                    # Only known, identity-checking drivers are reopened; no
                    # EEPROM/address writes or model calls. Outside frame loop.
                    self.refresh_inventory()
                except Exception:
                    pass

    def refresh_inventory(self):
        self.controls.hardware_reinitialize(refresh_missing=True)
        if time.monotonic() - self._last_discovery >= 15:
            self._scan(uuid.uuid4().hex)

    def _execute(self, command, generation):
        report = {}
        attempted = False
        try:
            if command["action"] == "install_driver":
                # Downloads run without bus_lock. Installer takes it only for
                # identity/read verification and atomic activation.
                self.driver_setup.install(command["target"], self.controls,
                                          lambda: self._allowed(command, generation), lambda: self._lock)
                report = self._scan(command["id"])
                self._finish(command, generation, "done", report)
                return
            with self.controls.bus_lock:
                with self._lock:
                    if not self._allowed(command, generation):
                        self._finish(command, generation, "failed", {}, "Command expired or withdrawn")
                        return
                report = self._scan(command["id"])
                if not report["bus_available"]:
                    raise ValueError("I2C scan failed")
                if command["action"] == "scan":
                    self._finish(command, generation, "done", report)
                    return
                if command["action"] == "reinitialize":
                    with self._lock:
                        if not self._allowed(command, generation):
                            raise ValueError("Command expired or withdrawn")
                        self.controls.hardware_reinitialize()
                    report = self._scan(command["id"])
                    self._finish(command, generation, "done" if report["bus_available"] else "failed",
                                 report, None if report["bus_available"] else "I2C scan failed")
                    return
                with self._lock:
                    previous = self._journal.get(command["id"])
                    if previous is not None:
                        # Even a successful past command needs fresh reconciliation;
                        # its original physical isolation cannot be reused after restart.
                        self._finish(command, generation, "uncertain", report,
                                     "Address operation was already consumed; inspect the current bus")
                        return
                source = next((b for b in report["buttons"] if b["address"] == 0x6F), None)
                if (report["addresses"] != [0x6F] or source is None
                        or source["id"] != 0x5D or source["firmware"] != 259
                        or source["configured_address"] != 0x6F):
                    self._finish(command, generation, "failed", report,
                                 "Requires only one isolated factory-address Qwiic Button with firmware 1.03")
                    return
                backend = self._backend if self._backend is not None else self.controls.hardware_backend()
                with self._lock:
                    if not self._allowed(command, generation):
                        raise ValueError("Command expired or withdrawn")
                    if not self._journal_ok or len(self._journal) >= _MAX_JOURNAL:
                        raise ValueError("Repair history unavailable or full")
                    self._journal[command["id"]] = {"target": command["target"], "status": "consumed"}
                try:
                    self._save()  # Do not prevent withdrawal while disk I/O is in progress.
                except Exception:
                    with self._lock:
                        self._journal_ok = False
                    raise ValueError("Could not durably record address operation") from None
                with self._lock:
                    # Serialize the final cancellation check and single write.
                    # Withdrawal before this boundary cancels; afterwards the
                    # physical operation may already have happened and must be read back.
                    if not self._allowed(command, generation):
                        raise ValueError("Command expired or withdrawn")
                    attempted = True
                    backend.readdress_factory_button(command["target"])
                self._sleep(0.02)
                report = self._scan(command["id"])
                target = next((b for b in report["buttons"] if b["address"] == command["target"]), None)
                if (not report["bus_available"] or report["addresses"] != [command["target"]]
                        or target is None or target["firmware"] != 259
                        or target["configured_address"] != command["target"]):
                    raise OSError("Address readback failed")
                with self._lock:
                    self._journal[command["id"]]["status"] = "done"
                    self._save()
                self._finish(command, generation, "done", report)
        except Exception as failure:
            if command["action"] == "install_driver":
                report = self._scan(command["id"])
                message = str(failure) if isinstance(failure, DriverSetupError) else "Driver setup unavailable; previous drivers retained"
                self._finish(command, generation, "failed", report, message)
                return
            status = "uncertain" if attempted else "failed"
            error = ("Address write outcome is uncertain; inspect and power-cycle the isolated button before any new repair"
                     if attempted else "Hardware operation rejected or unavailable; inspect the diagnostic report")
            if attempted:
                with self._lock:
                    self._journal[command["id"]]["status"] = "uncertain"
                    try:
                        self._save()
                    except Exception:
                        self._journal_ok = False
            self._finish(command, generation, status, report, error)
