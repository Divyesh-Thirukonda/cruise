"""Paired primary-desktop computer control, separate from generated app workers.

Native operations run in a short-lived helper with a deadline. No shell,
clipboard, browser profile, or file-content interface is exposed. Screenshots
and typed text remain in memory; callers must not write observations to traces.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid


MAX_IMAGE_BYTES = 349_000
MAX_ACTIONS = 100
OBSERVATION_SECONDS = 30
STATUS_CACHE_SECONDS = 2
SCOPE = "Paired Mac: full primary desktop"
MODIFIERS = {"command", "ctrl", "alt", "shift"}
KEY_NAMES = set("abcdefghijklmnopqrstuvwxyz0123456789`-=[]\\;',./") | {
    "enter", "esc", "tab", "up", "down", "left", "right", "pageup", "pagedown",
    "home", "end", "space", "backspace", "delete", "capslock"} | {f"f{n}" for n in range(1, 21)}
BUNDLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*(?:\.[A-Za-z0-9][A-Za-z0-9-]*)+\Z")



class ComputerError(ValueError):
    """Public error without screenshot contents, typed text, or OS diagnostics."""


def _same_desktop(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and all(left.get(key) == right.get(key) for key in ("id", "bounds")))


def _image_bytes(image):
    """Encode a bounded image without writing it to disk."""
    from PIL import Image
    image = image.convert("RGB")
    image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
    for _ in range(5):
        for quality in (82, 65, 45):
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            encoded = output.getvalue()
            if len(encoded) < MAX_IMAGE_BYTES:
                return encoded, image.width, image.height
        image = image.resize((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)))
    raise ComputerError("Screen image could not fit the capture limit")


class MacOSBackend:
    """Fixed native helper; importing this class does not inspect the desktop."""
    def _call(self, operation, payload=None, *, cancelled=None):
        if sys.platform != "darwin":
            raise ComputerError("Computer control is available on macOS only")
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve()), "--native", operation],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
            )
            deadline = time.monotonic() + 5
            first = True
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise ComputerError("Computer action cancelled")
                if time.monotonic() >= deadline:
                    raise ComputerError("Computer helper timed out; inspect before retrying")
                try:
                    output, _ = process.communicate(
                        json.dumps(payload or {}).encode() if first else None, timeout=0.05)
                    break
                except subprocess.TimeoutExpired:
                    first = False
            if process.returncode or len(output) > 600_000:
                raise ComputerError("Computer helper failed; inspect before retrying")
            result = json.loads(output)
            if not isinstance(result, dict) or not result.get("ok"):
                raise ComputerError("Computer helper unavailable; check its permissions and dependencies")
            return result["result"]
        except ComputerError:
            raise
        except (OSError, ValueError, KeyError):
            raise ComputerError("Computer helper unavailable; check its permissions and dependencies") from None
        finally:
            if process is not None and process.poll() is None:
                # Give the helper a brief chance to release any injected keys
                # or mouse button before enforcing the hard process deadline.
                process.terminate()
                try:
                    process.communicate(timeout=0.25)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()

    def inspect(self):
        return self._call("inspect")

    def capture(self, desktop, cancelled):
        return self._call("capture", {"desktop": desktop}, cancelled=cancelled)

    def perform(self, desktop, action, cancelled):
        return self._call("action", {"desktop": desktop, "action": action}, cancelled=cancelled)


class ComputerController:
    def __init__(self, *, backend=None, clock=time.monotonic, wall_clock=time.time):
        self.backend = backend if backend is not None else MacOSBackend()
        self.clock, self.wall_clock = clock, wall_clock
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.grant = self.observation = None
        self.active = False
        self.error = None
        self._cached_info = {"supported": False,
                             "permissions": {"screen_recording": False, "accessibility": False}}
        self._cached_at = float("-inf")

    def _inspect(self):
        try:
            info = self.backend.inspect()
            if not isinstance(info, dict) or type(info.get("supported")) is not bool:
                raise ComputerError("Computer helper returned invalid status")
            permissions = info.get("permissions")
            if (not isinstance(permissions, dict)
                    or any(type(permissions.get(key)) is not bool for key in ("screen_recording", "accessibility"))):
                raise ComputerError("Computer helper returned invalid permissions")
            self._cached_info = {"supported": info["supported"], "permissions": dict(permissions)}
            self._cached_at = self.clock()
            return info
        except ComputerError:
            raise
        except Exception:
            raise ComputerError("Computer permissions could not be checked") from None

    def sync_pairing(self, session_id):
        """Trusted owner supplies only a currently connected, authorized pairing.

        The owner validates expiry/revocation on every heartbeat/tool and sends
        None when disconnected. Pairing survives restart in the owner, not here.
        Repeated sync never clears cancellation or resets the per-task limit.
        """
        if session_id is None:
            return self.revoke()
        if (type(session_id) is not str or not 1 <= len(session_id) <= 128
                or not session_id.isascii() or not session_id.isprintable()
                or any(c.isspace() for c in session_id)):
            raise ComputerError("Invalid paired computer session")
        if self.grant and self.grant["session_id"] == session_id:
            return self._status_snapshot()  # Heartbeats must not wait behind native work.
        self.cancelled.set()  # A changed pairing interrupts work owned by the old one.
        with self.lock:
            if not self.grant or self.grant["session_id"] != session_id:
                self.grant = {"session_id": session_id, "actions": 0}
                self.observation = None
                self.cancelled.clear()
                self.error = None
            return self._status_snapshot()

    def _status_snapshot(self, *, active=None):
        enabled = (self.grant is not None and self._cached_info["supported"]
                   and all(self._cached_info["permissions"].values()))
        return {"supported": self._cached_info["supported"], "enabled": enabled,
                "expires_at": None, "scope": SCOPE,
                "permissions": dict(self._cached_info["permissions"]), "error": self.error,
                "active": self.active if active is None else active}

    def status(self):
        if not self.lock.acquire(blocking=False):
            return self._status_snapshot(active=True)
        try:
            try:
                if self.clock() - self._cached_at >= STATUS_CACHE_SECONDS:
                    self._inspect()
                if self.grant and (not self._cached_info["supported"]
                                   or not all(self._cached_info["permissions"].values())):
                    self.observation = None
                    self.error = "Allow Screen Recording and Accessibility for the computer helper"
            except ComputerError as error:
                self._cached_info = {"supported": False,
                                     "permissions": {"screen_recording": False, "accessibility": False}}
                self._cached_at = self.clock()
                self.error = str(error)
                self.observation = None
            return self._status_snapshot()
        finally:
            self.lock.release()

    def enable(self, minutes=None):
        """Compatibility check only; authorization comes exclusively from pairing."""
        with self.lock:
            self._check()
            return self._status_snapshot()

    @staticmethod
    def _valid_desktop(desktop):
        if (type(desktop) is not dict or type(desktop.get("id")) is not int or desktop["id"] < 0
                or set(desktop) != {"id", "bounds"}):
            raise ComputerError("Primary display identity is unavailable")
        values = desktop["bounds"]
        if (type(values) is not list or len(values) != 4 or any(type(value) is not int for value in values)
                or not 1 <= values[2] <= 32768 or not 1 <= values[3] <= 32768
                or any(abs(value) > 32768 for value in values[:2])):
            raise ComputerError("Primary display geometry is unavailable")

    def _check(self):
        if not self.grant:
            raise ComputerError("Pair and connect the controller before using this Mac")
        if self.cancelled.is_set():
            raise ComputerError("Computer action cancelled; start a new request to continue")
        info = self._inspect()
        if not info["supported"] or not all(info["permissions"].values()):
            self.observation = None
            raise ComputerError("Allow Screen Recording and Accessibility for the computer helper")
        self._valid_desktop(info.get("desktop"))
        return info["desktop"]

    def observe(self):
        with self.lock:
            self.observation = None
            desktop = self._check()
            self.active = True
            try:
                capture = self.backend.capture(desktop, self.cancelled)
                if not _same_desktop(desktop, self._check()):
                    raise ComputerError("Primary display changed during capture; observe again")
                image_url = capture.get("image_url")
                width, height = capture.get("width"), capture.get("height")
                if (type(width) is not int or type(height) is not int or not 1 <= width <= 1280
                        or not 1 <= height <= 1280 or not isinstance(image_url, str)
                        or not image_url.startswith("data:image/jpeg;base64,")
                        or len(image_url) > MAX_IMAGE_BYTES * 4 // 3 + 30):
                    raise ComputerError("Computer helper returned an invalid screenshot")
                identifier = uuid.uuid4().hex
                self.observation = {"id": identifier, "at": self.clock(), "desktop": desktop}
                self.error = None
                return {"observation_id": identifier, "width": width, "height": height,
                        "coordinate_space": "normalized_1000", "scope": SCOPE, "image_url": image_url}
            except ComputerError as error:
                self.error = str(error)
                raise
            except Exception:
                self.error = "Screen capture failed"
                raise ComputerError(self.error) from None
            finally:
                self.active = False

    def begin_task(self):
        with self.lock:
            self.cancelled.clear()
            self.observation = None
            if self.grant:
                self.grant["actions"] = 0

    def focus(self):
        """Compatibility check; full-desktop tasks never force an app forward."""
        with self.lock:
            self._check()
            return {"focused": False, "scope": SCOPE}

    def act(self, observation_id, action):
        with self.lock:
            desktop = self._check()
            observation, self.observation = self.observation, None
            if (not observation or observation_id != observation["id"]
                    or self.clock() - observation["at"] >= OBSERVATION_SECONDS
                    or not _same_desktop(observation["desktop"], desktop)):
                raise ComputerError("Observe the current primary desktop again before acting")
            if self.grant["actions"] >= MAX_ACTIONS:
                raise ComputerError("Computer request action limit reached")
            action = self._action(action, observation, desktop)
            self.grant["actions"] += 1
            self.active = True
            try:
                if not _same_desktop(desktop, self._check()):
                    raise ComputerError("Primary display changed; observe again")
                self.backend.perform(desktop, action, self.cancelled)
                if self.cancelled.is_set():
                    raise ComputerError("Computer action cancelled; inspect the current result")
                self.error = None
                return {"performed": True, "action": action["type"],
                        "remaining_actions": MAX_ACTIONS - self.grant["actions"]}
            except ComputerError as error:
                self.error = str(error)
                raise
            except Exception:
                self.error = "Computer action failed; observe before retrying"
                raise ComputerError(self.error) from None
            finally:
                self.active = False

    @staticmethod
    def _action(action, observation, desktop):
        if not isinstance(action, dict):
            raise ComputerError("Invalid computer action")
        kind = action.get("type")
        schemas = {"click": {"type", "x", "y"}, "double_click": {"type", "x", "y"},
                   "right_click": {"type", "x", "y"}, "drag": {"type", "x", "y", "to_x", "to_y"},
                   "scroll": {"type", "dx", "dy"}, "type_text": {"type", "text"},
                   "key": {"type", "keys"}, "launch_app": {"type", "bundle_id"}}
        if not isinstance(kind, str) or kind not in schemas or set(action) != schemas[kind]:
            raise ComputerError("Unknown computer action or arguments")
        result = dict(action)
        if kind in {"click", "double_click", "right_click", "drag"}:
            # Spark uses the exact screenshot's 0–1000 grid, including Retina:
            # https://dev.meta.ai/docs/image-understanding#coordinate-system
            x, y, width, height = desktop["bounds"]
            for horizontal, vertical in (("x", "y"), ("to_x", "to_y")) if kind == "drag" else (("x", "y"),):
                if any(type(action[key]) is not int or not 0 <= action[key] <= 1000 for key in (horizontal, vertical)):
                    raise ComputerError("Coordinates must be normalized integers from 0 to 1000")
                result[horizontal] = x + min(width - 1, round(action[horizontal] * width / 1000))
                result[vertical] = y + min(height - 1, round(action[vertical] * height / 1000))
        elif kind == "scroll":
            if any(type(action[key]) is not int or not -8 <= action[key] <= 8 for key in ("dx", "dy")):
                raise ComputerError("Scroll must contain bounded integer ticks")
        elif kind == "type_text":
            text = action["text"]
            if (type(text) is not str or not 1 <= len(text) <= 1000
                    or any(not character.isprintable() and character not in "\n\t" for character in text)):
                raise ComputerError("Type at most 1000 printable characters, newlines or tabs")
        elif kind == "key":
            keys = action["keys"]
            if type(keys) is not list or not 1 <= len(keys) <= 5 or any(type(key) is not str for key in keys):
                raise ComputerError("Invalid key combination")
            aliases = {"cmd": "command", "control": "ctrl", "option": "alt", "escape": "esc", "return": "enter"}
            keys = [aliases.get(key.lower(), key.lower()) for key in keys]
            if (len(set(keys)) != len(keys) or any(key not in MODIFIERS for key in keys[:-1])
                    or keys[-1] not in KEY_NAMES):
                raise ComputerError("Invalid key combination")
            result["keys"] = keys
        elif kind == "launch_app":
            identifier = action["bundle_id"]
            if type(identifier) is not str or len(identifier) > 180 or not BUNDLE_ID.fullmatch(identifier):
                raise ComputerError("Use an installed application's bundle identifier")
        return result

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            self.observation = None
        return {"cancelled": True}

    def revoke(self):
        self.cancelled.set()
        with self.lock:
            self.grant = self.observation = None
            self.error = None
        return {"enabled": False}


def _native_inspect():
    import ApplicationServices
    import Quartz
    permissions = {"screen_recording": bool(Quartz.CGPreflightScreenCaptureAccess()),
                   "accessibility": bool(ApplicationServices.AXIsProcessTrusted())}
    result = {"supported": True, "permissions": permissions, "desktop": None}
    if all(permissions.values()):
        identifier = Quartz.CGMainDisplayID()
        screen = Quartz.CGDisplayBounds(identifier)
        result["desktop"] = {"id": int(identifier), "bounds": [int(screen.origin.x), int(screen.origin.y),
                              int(screen.size.width), int(screen.size.height)]}
        ComputerController._valid_desktop(result["desktop"])
    return result


def _native_guard(desktop):
    current = _native_inspect()
    if not all(current["permissions"].values()) or not _same_desktop(current["desktop"], desktop):
        raise ComputerError("Computer permission or primary display changed")
    ComputerController._valid_desktop(current["desktop"])


def _native_launch_app(bundle_id):
    # Resolve only an installed bundle, with no arbitrary URL/arguments/shell.
    # Apple documents completion on a concurrent queue, so a bounded Event wait
    # does not need an AppKit UI loop in this short-lived helper.
    # https://developer.apple.com/documentation/appkit/nsworkspace/urlforapplication(withbundleidentifier:)
    # https://developer.apple.com/documentation/appkit/nsworkspace/openapplication(at:configuration:completionhandler:)
    import AppKit
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    url = workspace.URLForApplicationWithBundleIdentifier_(bundle_id)
    if url is None:
        raise ComputerError("The requested application is not installed")
    configuration = AppKit.NSWorkspaceOpenConfiguration.configuration()
    configuration.setActivates_(True)
    complete = threading.Event()
    outcome = {}
    def finished(app, error):
        outcome["success"] = app is not None and error is None
        complete.set()
    workspace.openApplicationAtURL_configuration_completionHandler_(url, configuration, finished)
    if not complete.wait(3) or not outcome.get("success"):
        raise ComputerError("Application launch was not confirmed; observe the desktop before retrying")
    return {"performed": True}


def _release_input(automation, method, *arguments, **keywords):
    # A corner stop must still permit releasing an input we already pressed.
    # All movement/press operations keep the failsafe enabled.
    enabled = automation.FAILSAFE
    try:
        automation.FAILSAFE = False
        getattr(automation, method)(*arguments, _pause=False, **keywords)
    finally:
        automation.FAILSAFE = enabled


def _native(operation, payload):
    if operation == "inspect":
        # Fail truthfully if capture/input dependencies are not installed.
        import importlib.util
        if any(importlib.util.find_spec(name) is None for name in ("mss", "pyautogui", "Quartz", "AppKit", "ApplicationServices")):
            raise ComputerError("Computer dependencies unavailable")
        return _native_inspect()
    window = payload["desktop"]
    _native_guard(window)
    if operation == "capture":
        from mss import MSS
        from PIL import Image
        x, y, w, h = window["bounds"]
        with MSS() as capture:
            frame = capture.grab({"left": x, "top": y, "width": w, "height": h})
            image = Image.frombytes("RGB", frame.size, frame.rgb)
        _native_guard(window)
        data, width, height = _image_bytes(image)
        return {"width": width, "height": height,
                "image_url": "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")}
    if operation != "action":
        raise ComputerError("Unknown native operation")
    import pyautogui
    import Quartz
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
    pyautogui.failSafeCheck()
    action = payload["action"]
    kind = action["type"]
    _native_guard(window)
    if kind == "launch_app":
        return _native_launch_app(action["bundle_id"])
    if kind in {"click", "double_click", "right_click"}:
        pyautogui.moveTo(action["x"], action["y"], duration=0.15)
        for _ in range(2 if kind == "double_click" else 1):
            _native_guard(window)
            try:
                pyautogui.mouseDown(button="right" if kind == "right_click" else "left", _pause=False)
            finally:
                _release_input(pyautogui, "mouseUp", button="right" if kind == "right_click" else "left")
            time.sleep(0.1)
    elif kind == "drag":
        pyautogui.moveTo(action["x"], action["y"], duration=0.15)
        _native_guard(window)
        try:
            pyautogui.mouseDown(_pause=False)
            pyautogui.moveTo(action["to_x"], action["to_y"], duration=0.4)
            _native_guard(window)
        finally:
            _release_input(pyautogui, "mouseUp")
    elif kind == "scroll":
        x, y, w, h = window["bounds"]
        pyautogui.moveTo(x + w // 2, y + h // 2, duration=0.1)
        _native_guard(window)
        if action["dy"]:
            pyautogui.scroll(action["dy"])
        if action["dx"]:
            _native_guard(window)
            pyautogui.hscroll(action["dx"])
    elif kind == "key":
        held = []
        try:
            for key in action["keys"]:
                held.append(key)
                pyautogui.keyDown(key, _pause=False)
        finally:
            for key in reversed(held):
                _release_input(pyautogui, "keyUp", key)
    elif kind == "type_text":
        # Unicode key events avoid the clipboard and shell. Deliver small chunks
        # so permissions and display identity are checked during longer text entry.
        text = action["text"]
        for offset in range(0, len(text), 20):
            _native_guard(window)
            pyautogui.failSafeCheck()
            chunk = text[offset:offset + 20]
            units = len(chunk.encode("utf-16-le")) // 2
            try:
                event = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
                Quartz.CGEventKeyboardSetUnicodeString(event, units, chunk)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            finally:
                event = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
                Quartz.CGEventKeyboardSetUnicodeString(event, units, chunk)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    else:
        raise ComputerError("Unknown native action")
    return {"performed": True}


if __name__ == "__main__":
    try:
        import signal
        def interrupted(signum, frame):
            raise ComputerError("Computer helper stopped")
        signal.signal(signal.SIGTERM, interrupted)
        if sys.platform != "darwin" or len(sys.argv) != 3 or sys.argv[1] != "--native":
            raise ComputerError("Unavailable")
        raw = sys.stdin.buffer.read(16_385)
        if len(raw) > 16_384:
            raise ComputerError("Oversized operation")
        result = _native(sys.argv[2], json.loads(raw))
        print(json.dumps({"ok": True, "result": result}))
    except Exception:
        print(json.dumps({"ok": False}))
