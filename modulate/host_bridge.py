"""Trusted volume/brightness bridge. This module never starts a network listener.

The companion server must protect local pairing administration separately and
carry bearer tokens over authenticated TLS. Generated programs receive neither
these tokens nor access to this module. macOS uses Apple's standard volume
commands, not UI scripting:
https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_cmds.html
"""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid


ACTIONS = ("volume.get", "volume.delta", "volume.mute", "volume.set")
BRIGHTNESS_ACTIONS = ("brightness.get", "brightness.delta", "brightness.set")
PAIRING_SECONDS = 120
SESSION_SECONDS = 8 * 60 * 60
ATTEMPT_WINDOW = 60
MAX_ATTEMPTS = 5
MAX_SESSIONS = 32
MAX_SEQUENCE = (1 << 53) - 1


class BridgeError(Exception):
    """A public, credential-free bridge error."""


class AuthenticationError(BridgeError):
    pass


class PairingError(BridgeError):
    pass


class RateLimitError(PairingError):
    pass


class ReplayError(BridgeError):
    pass


class BackendError(BridgeError):
    pass


class StateError(BridgeError):
    pass


class UnsupportedPlatformError(BackendError):
    pass


def _volume_result(result):
    if (not isinstance(result, dict) or type(result.get("volume")) is not int
            or not 0 <= result["volume"] <= 100 or type(result.get("muted")) is not bool):
        raise BackendError("Host returned invalid volume state")
    return {"volume": result["volume"], "muted": result["muted"]}


class MacOSVolumeBackend:
    """Fixed native OS actions; no app names, commands, or source from a caller."""

    _GET = ('set volumeSettings to get volume settings\n'
            'return ((output volume of volumeSettings) as text) & "," & '
            '((output muted of volumeSettings) as text)')
    _SET_VOLUME = ('on run argv\n'
                   'set volume output volume ((item 1 of argv) as integer)\n'
                   'end run')
    _SET_MUTED = ('on run argv\n'
                  'set volume output muted ((item 1 of argv) is "true")\n'
                  'end run')

    def capabilities(self):
        if not hasattr(self, "_brightness_supported"):
            try:
                self.get_brightness()
                self._brightness_supported = True
            except BackendError:
                self._brightness_supported = False
        return {"supported": True, "platform": "macos", "brightness": self._brightness_supported}

    @staticmethod
    def _brightness(action, value=None):
        args = [sys.executable, "-m", "modulate.system_settings", action]
        if value is not None:
            args.append(str(value))
        try:
            result = subprocess.run(args, cwd=Path(__file__).resolve().parent.parent,
                                    env={"LANG": "C.UTF-8"}, capture_output=True, text=True,
                                    check=True, timeout=3)
            data = json.loads(result.stdout)
            value = data["brightness"]
            if type(value) is not int or not 0 <= value <= 100:
                raise ValueError
            return value
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            raise BackendError("Native brightness is unavailable for this display") from None

    def get_brightness(self):
        return self._brightness("get")

    def set_brightness(self, value):
        if type(value) is not int or not 0 <= value <= 100:
            raise BackendError("Brightness must be an integer from 0 to 100")
        return self._brightness("set", value)

    @staticmethod
    def _run(script, *arguments):
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e", script, *arguments],
                check=True, capture_output=True, text=True, timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            # stderr can contain local information; it is not an HTTP response.
            raise BackendError("Native macOS volume command failed") from None
        return result.stdout.strip()

    def get(self):
        parts = self._run(self._GET).split(",")
        if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in ("true", "false"):
            raise BackendError("Native macOS volume response was invalid")
        return _volume_result({"volume": int(parts[0]), "muted": parts[1] == "true"})

    def set_volume(self, value):
        if type(value) is not int or not 0 <= value <= 100:
            raise BackendError("Volume must be an integer from 0 to 100")
        self._run(self._SET_VOLUME, str(value))

    def set_muted(self, value):
        if type(value) is not bool:
            raise BackendError("Mute must be a boolean")
        self._run(self._SET_MUTED, "true" if value else "false")


class UnsupportedVolumeBackend:
    def __init__(self, platform):
        self.platform = platform

    def capabilities(self):
        return {"supported": False, "platform": self.platform,
                "reason": "Native OS volume control is currently implemented for macOS only"}

    def get(self):
        raise UnsupportedPlatformError(self.capabilities()["reason"])


def default_backend():
    if sys.platform == "darwin":
        return MacOSVolumeBackend()
    platform = "windows" if sys.platform == "win32" else sys.platform
    return UnsupportedVolumeBackend(platform)


def _token_hash(token):
    if not isinstance(token, str) or not 32 <= len(token) <= 128 or not token.isascii():
        raise AuthenticationError("Invalid or expired bridge session")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _code_hash(code, salt):
    return hashlib.scrypt(code.encode("ascii"), salt=bytes.fromhex(salt),
                          n=16384, r=8, p=1).hex()


class BridgeStore:
    """One-time pairing and durable, at-most-once volume commands.

    Sequences start at 1. A native failure consumes its sequence because the OS
    may have applied the action before a timeout. Query session.next_sequence
    and issue volume.get to reconcile; never replay an uncertain delta.
    """

    def __init__(self, state_dir, backend=None, *, clock=None):
        self.directory = Path(state_dir)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "host-bridge.json"
        self.backend = backend if backend is not None else default_backend()
        self.clock = clock or time.time
        self._mutex = threading.RLock()

    def capabilities(self):
        info = self.backend.capabilities()
        supported = info.get("supported") is True
        result = {"supported": supported, "platform": info.get("platform", "unknown"),
                  "actions": list(ACTIONS) if supported else [], "delta_limit": 10}
        if supported and info.get("brightness") is True:
            result["actions"].extend(BRIGHTNESS_ACTIONS)
        if not supported:
            result["reason"] = info.get("reason", "OS volume control is unavailable")
        return result

    @contextmanager
    def _locked(self):
        # The lock spans read/modify/save AND native I/O, including across Store
        # instances/processes, so concurrent deltas cannot lose updates.
        with self._mutex:
            fd = os.open(self.directory / ".host-bridge.lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                if os.name == "nt":
                    import msvcrt
                    if os.fstat(fd).st_size == 0:
                        os.write(fd, b"\0")
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    def _read(self):
        try:
            if not self.path.exists():
                return {"version": 1, "pairing": None, "sessions": [], "failures": []}
            if self.path.stat().st_size > 1_000_000:
                raise ValueError()
            state = json.loads(self.path.read_text())
            if (state["version"] != 1 or type(state["sessions"]) is not list
                    or len(state["sessions"]) > MAX_SESSIONS
                    or type(state["failures"]) is not list
                    or not all(type(t) in (int, float) and math.isfinite(t) for t in state["failures"])):
                raise ValueError()
            for session in state["sessions"]:
                if (not isinstance(session["token_hash"], str) or len(session["token_hash"]) != 64
                        or len(bytes.fromhex(session["token_hash"])) != 32
                        or not isinstance(session["session_id"], str)
                        or not isinstance(session["device_name"], str)
                        or type(session["last_sequence"]) is not int
                        or not 0 <= session["last_sequence"] <= MAX_SEQUENCE
                        or type(session["expires_at"]) not in (int, float)
                        or not math.isfinite(session["expires_at"])):
                    raise ValueError()
            pairing = state["pairing"]
            if pairing is not None:
                if (not isinstance(pairing["salt"], str) or len(bytes.fromhex(pairing["salt"])) != 16
                        or not isinstance(pairing["hash"], str) or len(pairing["hash"]) != 128
                        or len(bytes.fromhex(pairing["hash"])) != 64
                        or type(pairing["expires_at"]) not in (int, float)
                        or not math.isfinite(pairing["expires_at"])):
                    raise ValueError()
            return state
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            raise StateError("Bridge state is unreadable; refusing to reset authorization") from None

    def _save(self, state):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False,
                                             prefix=".host-bridge-") as handle:
                temporary = handle.name
                os.chmod(temporary, 0o600)
                json.dump(state, handle, separators=(",", ":"), allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except (OSError, ValueError):
            raise StateError("Could not persist bridge authorization state") from None
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    def _require_supported(self):
        capabilities = self.capabilities()
        if not capabilities["supported"]:
            raise UnsupportedPlatformError(capabilities["reason"])

    def create_pairing(self):
        self._require_supported()
        with self._locked():
            state = self._read()
            code = f"{secrets.randbelow(100_000_000):08d}"
            salt = secrets.token_hex(16)
            expires_at = self.clock() + PAIRING_SECONDS
            state["pairing"] = {"hash": _code_hash(code, salt), "salt": salt,
                                "expires_at": expires_at}
            # Creating a fresh code must not reset the brute-force throttle.
            self._save(state)
            return {"code": code, "expires_at": expires_at}

    def pair(self, code, device_name):
        self._require_supported()
        if (not isinstance(device_name, str) or not 1 <= len(device_name.strip()) <= 80
                or any(ord(c) < 32 or ord(c) == 127 for c in device_name)):
            raise PairingError("Device name must contain 1 to 80 printable characters")
        with self._locked():
            state = self._read()
            now = self.clock()
            state["failures"] = [t for t in state["failures"] if t > now - ATTEMPT_WINDOW]
            if len(state["failures"]) >= MAX_ATTEMPTS:
                raise RateLimitError("Too many pairing attempts; wait one minute")
            pairing = state["pairing"]
            valid_format = isinstance(code, str) and len(code) == 8 and code.isascii() and code.isdigit()
            valid = (pairing is not None and now < pairing["expires_at"] and valid_format
                     and secrets.compare_digest(_code_hash(code, pairing["salt"]), pairing["hash"]))
            if not valid:
                state["failures"].append(now)
                self._save(state)
                raise PairingError("Invalid, expired, or already used pairing code")
            sessions = [s for s in state["sessions"] if now < s["expires_at"]]
            if len(sessions) >= MAX_SESSIONS:
                raise PairingError("Session limit reached; revoke an existing pairing first")
            token = secrets.token_urlsafe(32)
            sessions.append({"session_id": str(uuid.uuid4()), "token_hash": _token_hash(token),
                             "device_name": device_name.strip(), "expires_at": now + SESSION_SECONDS,
                             "last_sequence": 0})
            state.update(pairing=None, sessions=sessions)
            self._save(state)
            return token

    def _authenticate(self, state, token):
        digest = _token_hash(token)
        found = None
        for session in state["sessions"]:
            if secrets.compare_digest(digest, session["token_hash"]):
                found = session
        if found is None or self.clock() >= found["expires_at"]:
            raise AuthenticationError("Invalid or expired bridge session")
        return found

    def session(self, token):
        with self._locked():
            session = self._authenticate(self._read(), token)
            return {"session_id": session["session_id"], "device_name": session["device_name"],
                    "expires_at": session["expires_at"], "next_sequence": session["last_sequence"] + 1,
                    "capabilities": self.capabilities()}

    def execute(self, token, sequence, action, value=None):
        self._require_supported()
        with self._locked():
            state = self._read()
            session = self._authenticate(state, token)
            if type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE:
                raise ReplayError("Sequence must be a positive safe integer")
            if sequence <= session["last_sequence"]:
                raise ReplayError("Command sequence was already used or is stale")
            if action not in self.capabilities()["actions"]:
                raise BridgeError("Unsupported host action")
            if action.endswith(".delta") and (type(value) is not int or not -10 <= value <= 10):
                raise BridgeError("Volume delta must be an integer between -10 and 10")
            if action.endswith(".set") and (type(value) is not int or not 0 <= value <= 100):
                raise BridgeError("Setting must be an integer between 0 and 100")
            if action == "volume.mute" and type(value) is not bool:
                raise BridgeError("Mute value must be a boolean")
            if action.endswith(".get") and value is not None:
                raise BridgeError("Volume get takes no value")
            session["last_sequence"] = sequence
            # Write ahead: a timeout/crash must never make a delta replayable.
            self._save(state)
            try:
                if action.startswith("brightness."):
                    if action == "brightness.set":
                        self.backend.set_brightness(value)
                    elif action == "brightness.delta":
                        current = self.backend.get_brightness()
                        if type(current) is not int or not 0 <= current <= 100:
                            raise BackendError("Host returned invalid brightness")
                        self.backend.set_brightness(max(0, min(100, current + value)))
                    current = self.backend.get_brightness()
                    if type(current) is not int or not 0 <= current <= 100:
                        raise BackendError("Host returned invalid brightness")
                    return {"brightness": current, "sequence": sequence}
                if action == "volume.set":
                    self.backend.set_volume(value)
                elif action == "volume.delta":
                    current = _volume_result(self.backend.get())
                    self.backend.set_volume(max(0, min(100, current["volume"] + value)))
                elif action == "volume.mute":
                    self.backend.set_muted(value)
                result = _volume_result(self.backend.get())
            except BridgeError:
                raise
            except Exception:
                raise BackendError("Host volume operation failed; sequence was consumed") from None
            return {**result, "sequence": sequence}

    def revoke(self, token):
        with self._locked():
            state = self._read()
            session = self._authenticate(state, token)
            state["sessions"].remove(session)
            self._save(state)

    def revoke_all(self):
        with self._locked():
            state = self._read()
            state.update(sessions=[], pairing=None)
            self._save(state)

    def rotate(self, token):
        with self._locked():
            state = self._read()
            session = self._authenticate(state, token)
            new_token = secrets.token_urlsafe(32)
            session.update(token_hash=_token_hash(new_token), last_sequence=0)
            self._save(state)
            return new_token
