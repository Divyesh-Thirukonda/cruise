"""Verified volume for the Pi's pinned Pulse sink, shared by speech and music.

The host queues an expiring command; a device worker applies it once and returns
actual Pulse readback. No initial level is imposed and no state is persisted.
"""
from collections import deque
import copy
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

_ID = re.compile(r"[a-f0-9]{32}\Z")
_SINK = re.compile(r"[A-Za-z0-9_.,:=+/-]{1,240}\Z")
_ERROR = "Pi speaker volume could not be verified"
_OFFLINE = "The Pi speaker is disconnected or unavailable"


class SpeakerVolumeError(ValueError):
    pass


def _id(value):
    return type(value) is str and bool(_ID.fullmatch(value))


def _sink(value):
    return type(value) is str and bool(_SINK.fullmatch(value)) and not value.startswith("-")


def _state(value):
    if (type(value) is not dict or type(value.get("volume")) is not int
            or not 0 <= value["volume"] <= 100 or type(value.get("muted")) is not bool):
        raise SpeakerVolumeError(_ERROR)
    return {"volume": value["volume"], "muted": value["muted"]}


def _action(action, value):
    valid = ((action == "get" and value is None)
             or (action == "set" and type(value) is int and 0 <= value <= 100)
             or (action == "delta" and type(value) is int and -10 <= value <= 10 and value != 0)
             or (action == "mute" and type(value) is bool))
    if not valid:
        raise SpeakerVolumeError("Use get, set 0–100, delta −10–10 points, or mute true/false")


class SpeakerVolume:
    """Host coordinator; control() must run outside the Product/render lock."""
    def __init__(self, *, clock=time.monotonic, wall_clock=time.time):
        self.clock, self.wall_clock = clock, wall_clock
        self._condition = threading.Condition(threading.RLock())
        self._operation = threading.Lock()
        self._epoch = uuid.uuid4().hex
        self._revision = 0
        self._session = self._actual = self._pending = self._result = None
        self._last_seen = 0

    def observe(self, telemetry, device_session):
        with self._condition:
            if not _id(device_session):
                self.disconnect()
                return
            if self._session != device_session:
                self._session, self._actual = device_session, None
                if self._pending:
                    self._result = SpeakerVolumeError("Pi restarted before speaker volume was confirmed")
            self._last_seen = self.clock()
            pending, ack = self._pending, telemetry.get("ack") if type(telemetry) is dict else None
            if (pending and type(ack) is dict and device_session == pending["device_session"]
                    and telemetry.get("sink") == pending["sink"] and ack.get("status") == "failed"
                    and all(ack.get(key) == pending[key] for key in ("id", "epoch", "revision"))):
                self._result = SpeakerVolumeError(_ERROR)
            if (type(telemetry) is not dict or telemetry.get("available") is not True
                    or not _sink(telemetry.get("sink"))):
                self._actual = None
                self._condition.notify_all()
                return
            try:
                actual = _state(telemetry)
            except SpeakerVolumeError:
                self._actual = None
                self._condition.notify_all()
                return
            self._actual = {**actual, "sink": telemetry["sink"]}
            pending, ack = self._pending, telemetry.get("ack")
            if (pending and type(ack) is dict and device_session == pending["device_session"]
                    and telemetry["sink"] == pending["sink"]
                    and all(ack.get(key) == pending[key] for key in ("id", "epoch", "revision"))):
                if ack.get("status") == "failed":
                    self._result = SpeakerVolumeError(_ERROR)
                elif ack.get("status") == "applied":
                    try:
                        before, after = _state(ack.get("before")), _state(ack.get("after"))
                        expected = dict(before)
                        if pending["action"] == "set":
                            expected["volume"] = pending["value"]
                        elif pending["action"] == "delta":
                            expected["volume"] = max(0, min(100, before["volume"] + pending["value"]))
                        elif pending["action"] == "mute":
                            expected["muted"] = pending["value"]
                        if after != expected:
                            raise SpeakerVolumeError(_ERROR)
                        self._result = {**after, "before": before, "after": after,
                                        "revision": pending["revision"], "verified": True}
                    except SpeakerVolumeError as error:
                        self._result = error
            self._condition.notify_all()

    def status(self):
        with self._condition:
            available = self._actual is not None and self.clock() - self._last_seen < 4
            return {"available": available, **(self._actual if available else {}),
                    "pending": self._pending is not None, "error": None if available else _OFFLINE}

    def offer(self, device_session):
        with self._condition:
            if (not self._pending or device_session != self._pending["device_session"]
                    or self.wall_clock() >= self._pending["expires_at"] or self._result is not None):
                return None
            return dict(self._pending)

    def disconnect(self):
        with self._condition:
            self._actual = self._session = None
            if self._pending:
                self._result = SpeakerVolumeError(_OFFLINE)
            self._condition.notify_all()

    def control(self, action, value=None, timeout=5):
        _action(action, value)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 8:
            raise SpeakerVolumeError("Speaker control timeout must be within eight seconds")
        deadline = time.monotonic() + timeout
        if not self._operation.acquire(timeout=timeout):
            raise SpeakerVolumeError("Another Pi speaker change is still pending")
        try:
            with self._condition:
                if not self.status()["available"]:
                    raise SpeakerVolumeError(_OFFLINE)
                self._revision += 1
                self._pending = {"id": uuid.uuid4().hex, "epoch": self._epoch, "revision": self._revision,
                    "device_session": self._session, "sink": self._actual["sink"], "action": action,
                    "value": value, "expires_at": self.wall_clock() + max(0, deadline - time.monotonic())}
                self._result = None
                while self._result is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SpeakerVolumeError("Pi speaker did not acknowledge the change; its outcome is unknown")
                    if self.clock() - self._last_seen >= 4:
                        raise SpeakerVolumeError(_OFFLINE)
                    self._condition.wait(min(remaining, .25))
                if isinstance(self._result, Exception):
                    raise self._result
                return copy.deepcopy(self._result)
        finally:
            with self._condition:
                self._pending = self._result = None
            self._operation.release()


class PulseVolumeBackend:
    """Fixed pactl CLI operations on the selected output; never @DEFAULT_SINK@.

    pactl documentation: https://manpages.debian.org/bookworm/pulseaudio-utils/pactl.1.en.html
    """
    def __init__(self):
        self.executable = None

    def _run(self, *args):
        self.executable = self.executable or shutil.which("pactl")
        if not self.executable:
            raise SpeakerVolumeError(_OFFLINE)
        try:
            result = subprocess.run([self.executable, *args], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=.7, check=True,
                env={**os.environ, "LC_ALL": "C"})
            if len(result.stdout) > 8192:
                raise SpeakerVolumeError(_ERROR)
            return result.stdout.decode("ascii")
        except (OSError, UnicodeError, subprocess.SubprocessError):
            raise SpeakerVolumeError(_ERROR) from None

    def get(self, sink):
        if not _sink(sink):
            raise SpeakerVolumeError(_ERROR)
        volume = self._run("get-sink-volume", sink)
        values = [int(value) for value in re.findall(r"\b(\d{1,3})%", volume)]
        muted = self._run("get-sink-mute", sink).strip()
        if not 1 <= len(values) <= 32 or any(not 0 <= value <= 100 for value in values) or muted not in {"Mute: yes", "Mute: no"}:
            raise SpeakerVolumeError(_ERROR)
        # Pulse channels can differ; report the highest level. Setting a scalar
        # percentage deliberately applies the requested level to every channel.
        return {"volume": max(values), "muted": muted == "Mute: yes"}

    def set_volume(self, sink, volume):
        _action("set", volume)
        if not _sink(sink):
            raise SpeakerVolumeError(_ERROR)
        self._run("set-sink-volume", sink, str(volume) + "%")

    def set_muted(self, sink, muted):
        _action("mute", muted)
        if not _sink(sink):
            raise SpeakerVolumeError(_ERROR)
        self._run("set-sink-mute", sink, "1" if muted else "0")


class SpeakerVolumeDevice:
    """Worker for the pinned sink. output_info() must be cached/nonblocking.

    start only reads the current level. offer() is safe on the render thread.
    Every revision is consumed before native I/O; uncertain writes never replay.
    """
    def __init__(self, output_info, device_session, backend=None, *, clock=time.monotonic, wall_clock=time.time):
        self.output_info, self.session = output_info, device_session
        self.backend = backend if backend is not None else PulseVolumeBackend()
        self.clock, self.wall_clock = clock, wall_clock
        self._condition = threading.Condition(threading.RLock())
        self._stop = threading.Event()
        self._thread = None
        self._pending = None
        self._active_id = None
        self._epoch = None
        self._revision = 0
        self._retired = deque(maxlen=64)
        self._connected_at = None
        self._state = {"available": False, "sink": None, "ack": None, "error": _OFFLINE}

    def snapshot(self):
        with self._condition:
            return copy.deepcopy(self._state)

    def start(self):
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="modulate-speaker-volume", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self.disconnect()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def disconnect(self):
        with self._condition:
            self._connected_at = None
            self._pending = None
            self._active_id = None
            self._condition.notify_all()

    def _output(self):
        info = self.output_info()
        if (type(info) is not dict or info.get("available") is not True
                or info.get("pcm_backend") != "paplay" or not _sink(info.get("output"))):
            raise SpeakerVolumeError(_OFFLINE)
        return info["output"]

    def offer(self, command):
        with self._condition:
            self._connected_at = self.clock()
            if command is None:
                self._pending = None
                self._active_id = None
                return False
            required = {"id", "epoch", "revision", "device_session", "sink", "action", "value", "expires_at"}
            if (type(command) is not dict or set(command) != required or not _id(command["id"])
                    or not _id(command["epoch"]) or command["device_session"] != self.session
                    or type(command["revision"]) is not int or not 1 <= command["revision"] < 2**53
                    or not _sink(command["sink"]) or type(command["expires_at"]) not in (int, float)
                    or not math.isfinite(command["expires_at"])
                    or not 0 < command["expires_at"] - self.wall_clock() <= 10):
                return False
            try:
                _action(command["action"], command["value"])
                if self._output() != command["sink"]:
                    return False
            except (SpeakerVolumeError, TypeError):
                return False
            epoch = command["epoch"]
            if epoch != self._epoch:
                if epoch in self._retired:
                    return False
                if self._epoch:
                    self._retired.append(self._epoch)
                self._epoch, self._revision = epoch, 0
            if command["revision"] <= self._revision:
                return False
            self._revision = command["revision"]
            self._active_id = command["id"]
            self._pending = dict(command)
            self._condition.notify_all()
            return True

    def _allowed(self, command):
        with self._condition:
            return (not self._stop.is_set() and self._connected_at is not None
                    and self.clock() - self._connected_at < 4 and self.wall_clock() < command["expires_at"]
                    and command["epoch"] == self._epoch and command["revision"] == self._revision
                    and command["id"] == self._active_id)

    def _apply(self, command):
        ack = {key: command[key] for key in ("id", "epoch", "revision")}
        ack.update(status="failed", error=_ERROR)
        before = after = None
        sink = command["sink"]
        try:
            if not self._allowed(command) or self._output() != sink:
                raise SpeakerVolumeError(_OFFLINE)
            before = _state(self.backend.get(sink))
            if not self._allowed(command) or self._output() != sink:
                raise SpeakerVolumeError(_OFFLINE)
            expected = dict(before)
            if command["action"] in {"set", "delta"}:
                expected["volume"] = (command["value"] if command["action"] == "set" else
                                      max(0, min(100, before["volume"] + command["value"])))
                self.backend.set_volume(sink, expected["volume"])
            elif command["action"] == "mute":
                expected["muted"] = command["value"]
                self.backend.set_muted(sink, command["value"])
            after = before if command["action"] == "get" else _state(self.backend.get(sink))
            if after != expected or self._output() != sink:
                raise SpeakerVolumeError(_ERROR)
            ack.update(status="applied", error=None, before=before, after=after)
        except Exception:
            pass  # Native errors may contain private output identifiers.
        with self._condition:
            if command["epoch"] != self._epoch or command["revision"] != self._revision:
                return
            if after is not None:
                self._state = {**after, "available": True, "sink": sink, "error": None, "ack": ack}
            else:
                self._state = {"available": False, "sink": sink, "error": _ERROR, "ack": ack}

    def _refresh(self):
        try:
            sink = self._output()
            actual = _state(self.backend.get(sink))
            with self._condition:
                ack = self._state.get("ack") if self._state.get("sink") == sink else None
                self._state = {**actual, "available": True, "sink": sink, "error": None, "ack": ack}
        except Exception:
            with self._condition:
                self._state = {**self._state, "available": False, "error": _OFFLINE}

    def _run(self):
        refresh_at = 0
        while not self._stop.is_set():
            with self._condition:
                command, self._pending = self._pending, None
                refresh = self.clock() >= refresh_at
                if command is None and not refresh:
                    self._condition.wait(min(.5, max(0, refresh_at - self.clock())))
                    continue
            if command is not None:
                self._apply(command)
            else:
                self._refresh()
            refresh_at = self.clock() + 2
