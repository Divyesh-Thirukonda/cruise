"""Opt-in Chrome-window computer control, separate from generated app workers.

Native operations run in a short-lived helper with a deadline. No shell,
clipboard, browser profile, or file-content interface is exposed. Screenshots
and typed text remain in memory; callers must not write observations to traces.
"""
from __future__ import annotations

import base64
import io
import json
import math
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
MIN_BROWSER_WIDTH = 320
MIN_BROWSER_HEIGHT = 200
STATUS_CACHE_SECONDS = 2
SCOPE = "Google Chrome: the window selected when access was enabled"
KEYS = {("enter",), ("esc",), ("tab",), ("shift", "tab"),
        ("up",), ("down",), ("left",), ("right",), ("pageup",),
        ("pagedown",), ("home",), ("end",), ("space",), ("backspace",),
        ("command", "l"), ("command", "f"), ("command", "a"),
        ("command", "r"), ("command", "t"), ("command", "["),
        ("command", "]")}


class ComputerError(ValueError):
    """Public error without screenshot contents, typed text, or OS diagnostics."""


def _same_window(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and all(left.get(key) == right.get(key) for key in ("pid", "id", "bounds", "primary")))


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

    def capture(self, window, cancelled):
        return self._call("capture", {"window": window}, cancelled=cancelled)

    def focus(self, window, cancelled):
        return self._call("focus", {"window": window}, cancelled=cancelled)

    def perform(self, window, action, cancelled):
        return self._call("action", {"window": window, "action": action}, cancelled=cancelled)


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

    def _expire(self):
        if self.grant and self.clock() >= self.grant["deadline"]:
            self.grant = self.observation = None
            self.cancelled.set()
            self.error = "Computer access expired"

    def _status_snapshot(self, *, active=None):
        grant = self.grant
        enabled = grant is not None and self.clock() < grant["deadline"]
        return {"supported": self._cached_info["supported"], "enabled": enabled,
                "expires_at": grant["expires_at"] if enabled else None, "scope": SCOPE,
                "permissions": dict(self._cached_info["permissions"]), "error": self.error,
                "active": self.active if active is None else active}

    def status(self):
        # UI polling must not queue permission helpers behind an active action.
        # This snapshot is display metadata; observe/act always inspect afresh.
        if not self.lock.acquire(blocking=False):
            return self._status_snapshot(active=True)
        try:
            self._expire()
            try:
                if self.clock() - self._cached_at >= STATUS_CACHE_SECONDS:
                    self._inspect()
                if self.grant and (not self._cached_info["supported"]
                                   or not all(self._cached_info["permissions"].values())):
                    self.grant = self.observation = None
                    self.cancelled.set()
                    self.error = "Computer permission was removed"
            except ComputerError as error:
                self._cached_info = {"supported": False,
                                     "permissions": {"screen_recording": False, "accessibility": False}}
                self._cached_at = self.clock()
                self.error = str(error)
                self.grant = self.observation = None
            return self._status_snapshot()
        finally:
            self.lock.release()

    def enable(self, minutes=15):
        if type(minutes) not in (int, float) or not math.isfinite(minutes) or not 1 <= minutes <= 120:
            raise ComputerError("Computer access must last 1–120 minutes")
        with self.lock:
            info = self._inspect()
            if not info["supported"] or not all(info["permissions"].values()):
                raise ComputerError("Allow Screen Recording and Accessibility for the computer helper first")
            window = info.get("window")
            self._valid_window(window)
            self.grant = {"session_id": uuid.uuid4().hex, "window": window,
                          "deadline": self.clock() + minutes * 60,
                          "expires_at": self.wall_clock() + minutes * 60, "actions": 0}
            self.observation = None
            self.cancelled.clear()
            self.error = None
            return {"session_id": self.grant["session_id"], "enabled": True,
                    "expires_at": self.grant["expires_at"], "scope": SCOPE}

    @staticmethod
    def _valid_window(window):
        if (not isinstance(window, dict) or type(window.get("id")) is not int
                or type(window.get("pid")) is not int or window.get("app") != "com.google.Chrome"):
            raise ComputerError("Bring the Google Chrome window to the front first")
        for key in ("bounds", "primary"):
            values = window.get(key)
            if (not isinstance(values, list) or len(values) != 4
                    or any(type(value) is not int for value in values) or min(values[2:]) <= 0):
                raise ComputerError("Computer window geometry is unavailable")
        x, y, w, h = window["bounds"]
        px, py, pw, ph = window["primary"]
        if x < px or y < py or x + w > px + pw or y + h > py + ph:
            raise ComputerError("Keep the complete Chrome window on the primary display")

    def _check(self):
        self._expire()
        if not self.grant:
            raise ComputerError("Computer access is disabled or expired")
        if self.cancelled.is_set():
            raise ComputerError("Computer action cancelled; observe again before continuing")
        info = self._inspect()
        if not info["supported"] or not all(info["permissions"].values()):
            self.grant = self.observation = None
            raise ComputerError("Computer permission was removed")
        self._valid_window(info.get("window"))
        if not _same_window(self.grant["window"], info["window"]):
            self.observation = None
            raise ComputerError("Chrome focus or window geometry changed; enable access again")
        return info["window"]

    def observe(self):
        with self.lock:
            self.cancelled.clear()
            self.observation = None
            window = self._check()
            self.active = True
            try:
                capture = self.backend.capture(window, self.cancelled)
                self._check()
                image_url = capture.get("image_url")
                width, height = capture.get("width"), capture.get("height")
                if (type(width) is not int or type(height) is not int or not 1 <= width <= 1280
                        or not 1 <= height <= 1280 or not isinstance(image_url, str)
                        or not image_url.startswith("data:image/jpeg;base64,")
                        or len(image_url) > MAX_IMAGE_BYTES * 4 // 3 + 30):
                    raise ComputerError("Computer helper returned an invalid screenshot")
                identifier = uuid.uuid4().hex
                self.observation = {"id": identifier, "at": self.clock(), "width": width, "height": height}
                self.error = None
                return {"observation_id": identifier, "width": width, "height": height,
                        "coordinate_space": "normalized_1000", "image_url": image_url}
            except ComputerError as error:
                self.error = str(error)
                raise
            except Exception:
                self.error = "Screen capture failed"
                raise ComputerError(self.error) from None
            finally:
                self.active = False

    def begin_task(self):
        """A new user request may resume a cancelled, still-valid grant."""
        with self.lock:
            self.cancelled.clear()
            self.observation = None

    def focus(self):
        """Bring only the granted window forward; caller limits this to once per task."""
        with self.lock:
            self._expire()
            if not self.grant:
                raise ComputerError("Computer access is disabled or expired")
            if self.cancelled.is_set():
                raise ComputerError("Computer action cancelled")
            info = self._inspect()
            if not info["supported"] or not all(info["permissions"].values()):
                self.grant = self.observation = None
                raise ComputerError("Computer permission was removed")
            self.observation = None
            self.active = True
            try:
                self.backend.focus(self.grant["window"], self.cancelled)
                self._check()
                self.error = None
                return {"focused": True}
            except ComputerError as error:
                self.error = str(error)
                raise
            except Exception:
                self.error = "Could not focus the granted Chrome window; bring it forward and start a new request"
                raise ComputerError(self.error) from None
            finally:
                self.active = False

    def act(self, observation_id, action):
        with self.lock:
            window = self._check()
            observation, self.observation = self.observation, None
            if (not observation or observation_id != observation["id"]
                    or self.clock() - observation["at"] >= OBSERVATION_SECONDS):
                raise ComputerError("Observe the Chrome window again before acting")
            if self.grant["actions"] >= MAX_ACTIONS:
                raise ComputerError("Computer session action limit reached")
            action = self._action(action, observation, window)
            self.grant["actions"] += 1  # An uncertain OS result must not be replayed.
            self.active = True
            try:
                self._check()
                self.backend.perform(window, action, self.cancelled)
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
    def _action(action, observation, window):
        if not isinstance(action, dict):
            raise ComputerError("Invalid computer action")
        kind = action.get("type")
        schemas = {"click": {"type", "x", "y"}, "double_click": {"type", "x", "y"},
                   "scroll": {"type", "dx", "dy"}, "type_text": {"type", "text"}, "key": {"type", "keys"}}
        if not isinstance(kind, str) or kind not in schemas or set(action) != schemas[kind]:
            raise ComputerError("Unknown computer action or arguments")
        result = dict(action)
        if kind in {"click", "double_click"}:
            # Muse Spark grounds points on the exact image's 0–1000 grid:
            # https://dev.meta.ai/docs/image-understanding#coordinate-system
            # https://dev.meta.ai/docs/cookbook/computer-use-macos
            for coordinate in ("x", "y"):
                value = action[coordinate]
                if type(value) is not int or not 0 <= value <= 1000:
                    raise ComputerError("Click coordinates must be normalized integers from 0 to 1000")
            x, y, w, h = window["bounds"]
            # Map the cropped screenshot's proportions to logical window pixels.
            # This also works for Retina/downscaled images; no display offset or
            # screenshot-size correction belongs in the model's coordinates.
            result.update(x=x + min(w - 1, round(action["x"] * w / 1000)),
                          y=y + min(h - 1, round(action["y"] * h / 1000)))
        elif kind == "scroll":
            if any(type(action[key]) is not int or not -8 <= action[key] <= 8 for key in ("dx", "dy")):
                raise ComputerError("Scroll must contain bounded integer ticks")
        elif kind == "type_text":
            value = action["text"]
            if not isinstance(value, str) or not 1 <= len(value) <= 1000 or not value.isprintable():
                raise ComputerError("Type one printable line of at most 1000 characters")
            scheme = re.match(r"\s*([a-z][a-z0-9+.-]*):", value, re.I)
            if scheme and scheme[1].lower() not in {"http", "https"}:
                raise ComputerError("Executable and local URL schemes are unavailable")
        elif kind == "key":
            keys = action["keys"]
            if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys) or tuple(keys) not in KEYS:
                raise ComputerError("That key combination is unavailable")
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


def _front_chrome_window(windows, pid, primary):
    """Select the front browser-sized window, excluding Chrome accessory UI.

    Quartz's on-screen list is in front-to-back order. Preserve that order;
    choosing the largest window could target a different browser in back.
    https://developer.apple.com/documentation/coregraphics/cgwindowlistoption/optiononscreenonly
    """
    for window in windows or ():
        try:
            if (window.get("kCGWindowOwnerPID") != pid or window.get("kCGWindowLayer") != 0
                    or not window.get("kCGWindowIsOnscreen", True)):
                continue
            alpha = window.get("kCGWindowAlpha", 1)
            if not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or alpha <= 0:
                continue
            box = window["kCGWindowBounds"]
            values = [box[key] for key in ("X", "Y", "Width", "Height")]
            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in values):
                continue
            x, y, width, height = values
            left, top = math.ceil(x), math.ceil(y)
            bounds = [left, top, math.floor(x + width) - left, math.floor(y + height) - top]
            # Chrome's screen-sharing badge is itself a layer-zero window.
            # Require usable browser dimensions, in logical display pixels.
            if bounds[2] < MIN_BROWSER_WIDTH or bounds[3] < MIN_BROWSER_HEIGHT:
                continue
            identifier = window["kCGWindowNumber"]
            if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
                continue
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
        return {"app": "com.google.Chrome", "pid": int(pid), "id": int(identifier),
                "bounds": bounds, "primary": list(primary)}
    return None


def _native_inspect():
    import ApplicationServices
    import AppKit
    import Quartz
    permissions = {"screen_recording": bool(Quartz.CGPreflightScreenCaptureAccess()),
                   "accessibility": bool(ApplicationServices.AXIsProcessTrusted())}
    result = {"supported": True, "permissions": permissions, "window": None}
    if not all(permissions.values()):
        return result
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None or app.bundleIdentifier() != "com.google.Chrome":
        return result
    pid = int(app.processIdentifier())
    screen = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    primary = [int(screen.origin.x), int(screen.origin.y), int(screen.size.width), int(screen.size.height)]
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID)
    result["window"] = _front_chrome_window(windows, pid, primary)
    return result


def _native_guard(window):
    current = _native_inspect()
    if not all(current["permissions"].values()) or not _same_window(current["window"], window):
        raise ComputerError("Computer permission or focused window changed")
    ComputerController._valid_window(current["window"])


def _native_focus_target(window):
    """Resolve an existing visible grant without requiring it to be frontmost."""
    import ApplicationServices as AX
    import AppKit
    import Quartz
    ComputerController._valid_window(window)
    if not Quartz.CGPreflightScreenCaptureAccess() or not AX.AXIsProcessTrusted():
        raise ComputerError("Computer permission was removed")
    app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(window["pid"])
    if app is None or app.bundleIdentifier() != "com.google.Chrome":
        raise ComputerError("The granted Chrome window is no longer available")
    screen = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    primary = [int(screen.origin.x), int(screen.origin.y), int(screen.size.width), int(screen.size.height)]
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID)
    candidates = [_front_chrome_window([entry], window["pid"], primary) for entry in windows or ()]
    matching = [entry for entry in candidates if entry and entry["bounds"] == window["bounds"]]
    # AX exposes geometry, not a public CGWindowID mapping. Refuse ambiguity
    # rather than raising another window that happens to have the same bounds.
    if len(matching) != 1 or not _same_window(matching[0], window):
        raise ComputerError("The granted Chrome window changed or cannot be identified uniquely")
    return app


def _native_focus(window):
    import ApplicationServices as AX
    import AppKit
    app = _native_focus_target(window)
    application = AX.AXUIElementCreateApplication(window["pid"])
    error, windows = AX.AXUIElementCopyAttributeValue(application, AX.kAXWindowsAttribute, None)
    if error:
        raise ComputerError("Chrome's accessible windows could not be read")
    matches = []
    for candidate in windows or ():
        p_error, position = AX.AXUIElementCopyAttributeValue(candidate, AX.kAXPositionAttribute, None)
        s_error, size = AX.AXUIElementCopyAttributeValue(candidate, AX.kAXSizeAttribute, None)
        if p_error or s_error:
            continue
        p_ok, point = AX.AXValueGetValue(position, AX.kAXValueCGPointType, None)
        s_ok, extent = AX.AXValueGetValue(size, AX.kAXValueCGSizeType, None)
        if not p_ok or not s_ok:
            continue
        bounds = [math.ceil(point.x), math.ceil(point.y),
                  math.floor(point.x + extent.width) - math.ceil(point.x),
                  math.floor(point.y + extent.height) - math.ceil(point.y)]
        if bounds == window["bounds"]:
            matches.append(candidate)
    if len(matches) != 1:
        raise ComputerError("The granted Chrome window cannot be raised unambiguously")
    _native_focus_target(window)  # Recheck identity/geometry immediately before changing focus.
    if AX.AXUIElementPerformAction(matches[0], AX.kAXRaiseAction):
        raise ComputerError("The granted Chrome window could not be raised")
    if not app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps):
        raise ComputerError("The granted Chrome window could not be activated")
    # App activation is asynchronous. Never retry the focus action itself.
    deadline = time.monotonic() + .4
    while True:
        try:
            _native_guard(window)
            return {"focused": True}
        except ComputerError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.02)


def _release_input(automation, method, *arguments):
    # A corner stop must still permit releasing an input we already pressed.
    # All movement/press operations keep the failsafe enabled.
    enabled = automation.FAILSAFE
    try:
        automation.FAILSAFE = False
        getattr(automation, method)(*arguments, _pause=False)
    finally:
        automation.FAILSAFE = enabled


def _native(operation, payload):
    if operation == "inspect":
        # Fail truthfully if capture/input dependencies are not installed.
        import importlib.util
        if any(importlib.util.find_spec(name) is None for name in ("mss", "pyautogui", "Quartz", "AppKit", "ApplicationServices")):
            raise ComputerError("Computer dependencies unavailable")
        return _native_inspect()
    window = payload["window"]
    if operation == "focus":
        return _native_focus(window)
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
    if kind in {"click", "double_click"}:
        pyautogui.moveTo(action["x"], action["y"], duration=0.15)
        for _ in range(2 if kind == "double_click" else 1):
            _native_guard(window)
            try:
                pyautogui.mouseDown(_pause=False)
            finally:
                _release_input(pyautogui, "mouseUp")
            time.sleep(0.1)
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
        # so focus is checked again during longer text entry.
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
