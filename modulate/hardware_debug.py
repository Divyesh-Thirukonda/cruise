"""Durable, supervised Qwiic-button setup; no model-supplied register writes.

I2C identity cannot prove a board's color or that two identical devices are not
sharing an address. Physical isolation is a direct user assertion, never an
inference from a scan. A boot ID proves a reboot, not removal of power.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re
import string
import threading
import time
import uuid


_ID = re.compile(r"[a-f0-9]{32}\Z")
_TARGETS = (0x6E, 0x6D, 0x6C, 0x6B, 0x69, 0x68, 0x67, 0x66,
            0x65, 0x64, 0x63, 0x62, 0x61, 0x60)
_RESERVED = {0x20, 0x36, 0x39, 0x6A, 0x6F}
_PHRASES = {"awaiting_isolation": "isolated button ready",
            "awaiting_power_cycle": "button power cycled",
            "awaiting_reconnect": "modules reconnected"}
_PHASES = set(_PHRASES) | {"write_pending", "complete", "cancelled"}


class HardwareDebugError(ValueError):
    pass


def _id(value):
    return type(value) is str and bool(_ID.fullmatch(value))


def _boot(value):
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _report(value):
    if type(value) is not dict:
        raise HardwareDebugError("Missing hardware report")
    addresses, buttons = value.get("addresses"), value.get("buttons")
    if (type(addresses) is not list or len(addresses) > 112
            or any(type(a) is not int or not 8 <= a <= 0x77 for a in addresses)
            or len(set(addresses)) != len(addresses)
            or type(buttons) is not list or len(buttons) > 32
            or type(value.get("bus_available")) is not bool
            or not _id(value.get("scan_id"))
            or type(value.get("controls")) is not dict
            or type(value.get("warnings")) is not list
            or len(value["warnings"]) > 32
            or any(type(w) is not str or len(w) > 500 for w in value["warnings"])):
        raise HardwareDebugError("Invalid hardware report")
    clean = []
    for button in buttons:
        if (type(button) is not dict or type(button.get("address")) is not int
                or button["address"] not in addresses or type(button.get("id")) is not int
                or button["id"] != 93 or type(button.get("firmware")) is not int
                or not 0 <= button["firmware"] <= 65535
                or type(button.get("configured_address")) is not int
                or not 8 <= button["configured_address"] <= 0x77):
            raise HardwareDebugError("Invalid button identity report")
        clean.append({key: button[key] for key in ("address", "id", "firmware", "configured_address")})
    if len({b["address"] for b in clean}) != len(clean):
        raise HardwareDebugError("Duplicate button report")
    if len(json.dumps(value, allow_nan=False).encode()) > 32000:
        raise HardwareDebugError("Hardware report is too large")
    result = {"addresses": sorted(addresses), "buttons": clean,
            "controls": copy.deepcopy(value["controls"]), "warnings": list(value["warnings"]),
            "bus_available": value["bus_available"], "scan_id": value["scan_id"]}
    if "driver_setup" in value:
        if type(value["driver_setup"]) is not dict:
            raise HardwareDebugError("Invalid driver setup report")
        result["driver_setup"] = copy.deepcopy(value["driver_setup"])
    return result


def _button(report, address):
    return any(b["address"] == address and b["configured_address"] == address and b["firmware"] == 259
               for b in report["buttons"])


def _save(path, workflow):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".pending")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump({"version": 1, "workflow": workflow}, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class HardwareDebug:
    """Host coordinator. call() waits at most eight seconds outside Product.lock.

    confirm() and note_user() are human-input entry points, not agent tools.
    The Pi independently validates every command and journals mutations before
    dispatch. The host never repeats a possibly dispatched address write.
    """
    def __init__(self, path, *, clock=time.monotonic, wall_clock=time.time, timeout=8):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 8:
            raise ValueError("Hardware command timeout must be within eight seconds")
        self.path, self.clock, self.wall_clock, self.timeout = Path(path), clock, wall_clock, timeout
        self._condition = threading.Condition(threading.RLock())
        self._operation = threading.Lock()
        self._session = self._boot = self._report = None
        self._seen = None
        self._supported = False
        self._pending = self._result = self._confirmation = None
        self._workflow = None
        self._error = None
        self._generation = 0
        self._load_error = False
        try:
            if self.path.exists():
                if self.path.stat().st_size > 16000:
                    raise ValueError
                data = json.loads(self.path.read_text())
                if type(data) is not dict or data.get("version") != 1:
                    raise ValueError
                workflow = data.get("workflow")
                if workflow is not None:
                    self._validate_workflow(workflow)
                    self._workflow = workflow
                    if workflow["phase"] == "write_pending":
                        self._transition("awaiting_power_cycle", error="The write outcome is unknown after host restart; it will not be repeated.")
                    elif workflow["phase"] in _PHRASES:
                        self._transition(workflow["phase"], error=workflow.get("error"))
        except (OSError, ValueError, TypeError, KeyError):
            self._load_error = True
            self._error = "Saved hardware setup could not be read. Cancel setup before starting another; no write was retried."

    @staticmethod
    def _validate_workflow(w):
        if (type(w) is not dict or not _id(w.get("id")) or w.get("phase") not in _PHASES
                or type(w.get("target")) is not int or w["target"] not in _TARGETS
                or w.get("source") != 0x6F or not _boot(w.get("anchor_boot"))
                or type(w.get("label")) is not str or not 1 <= len(w["label"]) <= 40
                or any(c not in string.printable or ord(c) < 32 or ord(c) > 126 for c in w["label"])
                or type(w.get("baseline_addresses")) is not list
                or any(type(a) is not int or not 8 <= a <= 0x77 for a in w["baseline_addresses"])
                or len(w["baseline_addresses"]) > 112
                or not _id(w.get("confirmation_step"))):
            raise ValueError("Invalid saved hardware workflow")

    def _connected(self):
        return self._supported and self._seen is not None and self.clock() - self._seen < 4

    def observe(self, snapshot, session):
        """Cache validated evidence; only the exact command ack releases a waiter."""
        with self._condition:
            try:
                if (type(snapshot) is not dict or snapshot.get("supported") is not True
                        or not _id(session) or snapshot.get("session") != session
                        or not _boot(snapshot.get("boot_id"))):
                    raise HardwareDebugError("Hardware debugger is unavailable")
                report = _report(snapshot.get("report"))
            except (HardwareDebugError, ValueError, TypeError, RecursionError):
                self._supported = False
                if self._pending:
                    self._result = HardwareDebugError("Hardware debugger disconnected; command outcome may be unknown")
                self._condition.notify_all()
                return
            if self._pending and (session != self._pending["session"] or snapshot["boot_id"] != self._pending["boot_id"]):
                self._result = HardwareDebugError("Pi restarted before the hardware command was confirmed")
            if (self._session != session or self._boot != snapshot["boot_id"]) and self._confirmation:
                try:
                    self._transition(self._workflow["phase"], error=self._workflow.get("error"))
                except OSError:
                    self._confirmation = None
                    self._load_error = True
                    self._error = "Hardware confirmation could not be invalidated durably; cancel setup before continuing"
            self._session, self._boot, self._report = session, snapshot["boot_id"], report
            self._seen, self._supported = self.clock(), True
            pending, ack = self._pending, snapshot.get("ack")
            if (pending and self._result is None and type(ack) is dict
                    and session == pending["session"] and self._boot == pending["boot_id"]
                    and ack.get("id") == pending["id"] and ack.get("action") == pending["action"]):
                if ack.get("status") == "done":
                    try:
                        result = _report(ack.get("result"))
                        if result["scan_id"] != pending["id"]:
                            raise HardwareDebugError("Hardware scan did not match this request")
                        self._result = result
                    except (HardwareDebugError, ValueError, TypeError, RecursionError):
                        self._result = HardwareDebugError("Hardware command returned invalid verification")
                elif ack.get("status") in {"failed", "uncertain"}:
                    if pending['action'] == 'install_driver':
                        message = ack.get('error')
                        self._result = HardwareDebugError(message if type(message) is str and len(message) <= 240
                                                          else 'Driver setup failed; inspect current hardware state')
                    else:
                        self._result = HardwareDebugError("Hardware command failed" if ack["status"] == "failed"
                                                      else "Hardware command outcome is uncertain; do not repeat the address write")
            self._condition.notify_all()

    def offer(self, session):
        with self._condition:
            if (self._pending and self._result is None and self._connected()
                    and session == self._pending["session"] == self._session
                    and self._boot == self._pending["boot_id"]
                    and self.wall_clock() < self._pending["expires_at"]):
                return dict(self._pending)
            return None

    def _transition(self, phase, *, anchor=None, error=None):
        workflow = {**self._workflow, "phase": phase,
                    "confirmation_step": uuid.uuid4().hex, "error": error}
        if anchor is not None:
            workflow["anchor_boot"] = anchor
        _save(self.path, workflow)  # Failure here prevents publishing the next command.
        self._workflow, self._confirmation = workflow, None

    def _instructions(self, workflow):
        target = f"0x{workflow['target']:02x}"
        return {
            "awaiting_isolation": "Shut down and unplug the Pi. Connect only the new Qwiic button directly to the TFT QT port. Leave every other I2C module disconnected, then boot the Pi and confirm isolation.",
            "write_pending": "An address write may be in progress. Do not reconnect other modules or retry it.",
            "awaiting_power_cycle": f"Shut down and unplug the Pi, keeping this button isolated. Power it up again, then confirm the power cycle so its stored {target} address can be checked. The write will not be repeated.",
            "awaiting_reconnect": "Shut down and unplug the Pi, reconnect all original modules plus the newly addressed button, then boot and confirm reconnection.",
            "complete": f"Button verified at {target}; original bus addresses are present and input drivers were reinitialized. Extra buttons do not automatically become new game controls.",
            "cancelled": "Setup cancelled. Any address write already performed is not undone. Inspect the bus before reconnecting modules.",
        }[workflow["phase"]]

    def inspect(self):
        with self._condition:
            workflow = copy.deepcopy(self._workflow)
            if workflow:
                workflow.update(instructions=self._instructions(workflow),
                    required_phrase=_PHRASES.get(workflow["phase"]),
                    confirmation_received=self._valid_confirmation(),
                    reboot_observed=self._connected() and self._boot != workflow["anchor_boot"],
                    limitation="A scan cannot prove physical isolation, button color, or removal of power; these steps require your direct confirmation.")
            return {"supported": self._supported, "connected": self._connected(),
                    "report": copy.deepcopy(self._report), "workflow": workflow,
                    "pending": self._pending is not None, "error": self._error}

    def _valid_confirmation(self):
        c, w = self._confirmation, self._workflow
        return bool(c and w and c["id"] == w["id"] and c["step"] == w["confirmation_step"]
                    and c["session"] == self._session and c["boot"] == self._boot
                    and self.clock() < c["expires"] and self._connected())

    def confirm(self, identifier, step):
        """Only direct UI/user input may call this; not exposed to model arguments."""
        with self._condition:
            w = self._workflow
            if (not w or identifier != w["id"] or step != w["confirmation_step"]
                    or w["phase"] not in _PHRASES or self._load_error):
                raise HardwareDebugError("Hardware confirmation is stale")
            if not self._connected() or self._boot == w["anchor_boot"]:
                raise HardwareDebugError("Reconnect after shutting down and unplugging the Pi before confirming this step")
            if self._confirmation is not None:
                if not self._valid_confirmation():
                    self._transition(w["phase"])
                    raise HardwareDebugError("Hardware confirmation expired; use the current setup step")
                raise HardwareDebugError("This setup confirmation was already received")
            self._confirmation = {"id": identifier, "step": step, "session": self._session,
                                  "boot": self._boot, "expires": self.clock() + 120}
            return self.inspect()

    def note_user(self, text):
        if type(text) is not str or len(text) > 200:
            return False
        phrase = " ".join(text.lower().strip().strip(string.punctuation).split())
        phrase = re.sub(r"^hey[ ,]+meta[ ,:]+", "", phrase)
        with self._condition:
            w = self._workflow
            if not w or phrase != _PHRASES.get(w["phase"]):
                return False
            self.confirm(w["id"], w["confirmation_step"])
            return True

    def disconnect(self):
        """Withdraw commands on revocation/disconnect without losing setup history."""
        with self._condition:
            self._supported = False
            had_confirmation = self._confirmation is not None
            self._confirmation = None
            self._generation += 1
            if self._pending:
                self._result = HardwareDebugError("Hardware connection withdrawn; an issued write may already have occurred")
            self._pending = None
            self._condition.notify_all()
            if had_confirmation:
                self._transition(self._workflow["phase"], error=self._workflow.get("error"))

    def withdraw(self):
        """Orderly host shutdown: withdraw RPCs/grants, preserve durable setup."""
        self.disconnect()

    def _rpc(self, action, deadline, generation, target=None, *, expected=None):
        with self._condition:
            if generation != self._generation or not self._connected():
                raise HardwareDebugError("Hardware debugger is disconnected or this operation was cancelled")
            if expected is not None and (self._session, self._boot) != expected:
                raise HardwareDebugError("Pi restarted after physical confirmation; no address write was dispatched")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HardwareDebugError("Hardware operation timed out")
            command = {"id": uuid.uuid4().hex, "session": self._session, "boot_id": self._boot,
                       "expires_at": self.wall_clock() + remaining, "action": action, "target": target}
            self._pending, self._result = command, None
            try:
                while self._result is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not self._connected():
                        raise HardwareDebugError("Pi did not confirm the command; its outcome may be unknown")
                    self._condition.wait(min(remaining, .1))
                if isinstance(self._result, Exception):
                    raise self._result
                if generation != self._generation:
                    raise HardwareDebugError("Hardware operation was cancelled")
                if not self._result["bus_available"]:
                    raise HardwareDebugError("I2C bus is unavailable; check wiring and Pi configuration")
                return copy.deepcopy(self._result)
            finally:
                self._pending = self._result = None

    def _cancel(self):
        with self._condition:
            self._generation += 1
            self._confirmation = None
            self._pending = None
            self._result = HardwareDebugError("Hardware setup cancelled")
            self._condition.notify_all()
            if self._workflow:
                self._transition("cancelled")
            else:
                _save(self.path, None)
            self._load_error, self._error = False, None
            return self.inspect()

    def call(self, action, label=None, driver=None):
        if action not in {"inspect", "scan", "reinitialize", "install_driver", "begin_button_repair", "continue", "cancel"}:
            raise HardwareDebugError("Unknown hardware diagnostic action")
        if (action == 'install_driver' and driver != 'lsm6ds3trc'
                or action != 'install_driver' and driver is not None):
            raise HardwareDebugError("Select a supported driver only for install_driver")
        if label is not None and (action != "begin_button_repair" or type(label) is not str
                or not 1 <= len(label) <= 40 or any(not 32 <= ord(c) <= 126 for c in label)):
            raise HardwareDebugError("Use a printable button label of at most 40 characters")
        if action == "inspect":
            return self.inspect()
        if action == "cancel":
            return self._cancel()
        deadline = time.monotonic() + (55 if action == 'install_driver' else self.timeout)
        if not self._operation.acquire(timeout=self.timeout):
            raise HardwareDebugError("Another hardware operation is still pending")
        try:
            with self._condition:
                if self._load_error and action != "scan":
                    raise HardwareDebugError(self._error)
                generation = self._generation
            if action == 'install_driver':
                with self._condition:
                    if self._workflow and self._workflow['phase'] not in {'complete', 'cancelled'}:
                        raise HardwareDebugError('Finish or cancel the physical repair before installing a driver')
                self._rpc(action, deadline, generation, target=driver)
            elif action in {"scan", "reinitialize"}:
                self._rpc(action, deadline, generation)
            elif action == "begin_button_repair":
                with self._condition:
                    if self._workflow and self._workflow["phase"] not in {"complete", "cancelled"}:
                        raise HardwareDebugError("Finish or cancel the existing button setup first")
                report = self._rpc("scan", deadline, generation)
                with self._condition:
                    if generation != self._generation:
                        raise HardwareDebugError("Hardware operation was cancelled")
                    if not _button(report, 0x6F):
                        raise HardwareDebugError("No supported Qwiic button with firmware 259 was identified at 0x6f; inspect its wiring and firmware first")
                    target = next((a for a in _TARGETS if a not in set(report["addresses"]) | _RESERVED), None)
                    if target is None:
                        raise HardwareDebugError("No supported unused button address is available")
                    workflow = {"id": uuid.uuid4().hex, "label": label or "new Qwiic button",
                                "source": 0x6F, "target": target, "baseline_addresses": report["addresses"],
                                "anchor_boot": self._boot, "phase": "awaiting_isolation",
                                "confirmation_step": uuid.uuid4().hex, "error": None}
                    _save(self.path, workflow)
                    self._workflow, self._confirmation = workflow, None
            else:
                self._continue(deadline, generation)
            return self.inspect()
        finally:
            self._operation.release()

    def _continue(self, deadline, generation):
        with self._condition:
            w = copy.deepcopy(self._workflow)
            if not w or w["phase"] in {"complete", "cancelled"}:
                raise HardwareDebugError("No active button setup to continue")
            if w["phase"] == "write_pending":
                self._transition("awaiting_power_cycle", error="Write outcome is unknown; it will not be repeated.")
                return
            if not self._valid_confirmation():
                if self._confirmation is not None:
                    self._transition(w["phase"])
                return
            confirmed_boot, confirmed_session = self._boot, self._session
            # Consume and rotate the persisted step before any reads or writes.
            # A stale UI POST cannot rearm a failed attempt with its old nonce.
            self._transition(w["phase"])
        report = self._rpc("scan", deadline, generation)
        with self._condition:
            if (generation != self._generation or self._boot != confirmed_boot
                    or self._session != confirmed_session):
                raise HardwareDebugError("Pi connection changed during hardware verification")
            if w["phase"] == "awaiting_isolation":
                if report["addresses"] != [0x6F] or not _button(report, 0x6F):
                    raise HardwareDebugError("Isolation check failed: only the supported button at 0x6f may be connected")
                self._transition("write_pending", anchor=confirmed_boot)
            elif w["phase"] == "awaiting_power_cycle":
                if report["addresses"] != [w["target"]] or not _button(report, w["target"]):
                    raise HardwareDebugError("The isolated button's stored target address was not verified. Do not repeat the write; inspect wiring or cancel setup.")
                self._transition("awaiting_reconnect", anchor=confirmed_boot)
                return
            elif w["phase"] == "awaiting_reconnect":
                expected = set(w["baseline_addresses"]) | {w["target"]}
                if not expected.issubset(report["addresses"]) or not _button(report, w["target"]):
                    raise HardwareDebugError("Some original bus addresses or the newly addressed button are missing; reconnect all original modules")
        if w["phase"] == "awaiting_isolation":
            error = None
            try:
                result = self._rpc("readdress_button", deadline, generation, w["target"],
                                   expected=(confirmed_session, confirmed_boot))
                if result["addresses"] != [w["target"]] or not _button(result, w["target"]):
                    raise HardwareDebugError("Immediate target verification failed; the write will not be repeated")
            except HardwareDebugError as failure:
                error = str(failure)
            finally:
                with self._condition:
                    if self._workflow["id"] == w["id"] and self._workflow["phase"] == "write_pending":
                        self._transition("awaiting_power_cycle", anchor=confirmed_boot, error=error)
        else:
            report = self._rpc("reinitialize", deadline, generation)
            with self._condition:
                if (generation != self._generation or self._boot != confirmed_boot
                        or self._session != confirmed_session
                        or not (set(w["baseline_addresses"]) | {w["target"]}).issubset(report["addresses"])
                        or not _button(report, w["target"])):
                    raise HardwareDebugError("The reinitialized bus did not retain the verified modules")
                self._transition("complete", anchor=confirmed_boot)
