"""Synthetic screen/controller tests. These never inspect or act on the desktop."""
import base64
import copy
import io
import subprocess
import threading
from types import SimpleNamespace
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from PIL import Image

from modulate.computer import (ComputerController, ComputerError, MacOSBackend,
                              _front_chrome_window, _image_bytes, _native_inspect, _release_input)


class FakeDesktop:
    def __init__(self):
        self.permissions = {"screen_recording": True, "accessibility": True}
        self.window = {"app": "com.google.Chrome", "pid": 123, "id": 45,
                       "bounds": [100, 50, 1600, 900], "primary": [0, 0, 1920, 1080]}
        self.calls = []
        self.inspections = 0
        self.on_capture = self.on_perform = None

    def inspect(self):
        self.inspections += 1
        return {"supported": True, "permissions": dict(self.permissions), "window": copy.deepcopy(self.window)}

    def capture(self, window, cancelled):
        self.calls.append(("capture", copy.deepcopy(window)))
        if self.on_capture:
            self.on_capture(cancelled)
        return {"width": 1280, "height": 720, "image_url": "data:image/jpeg;base64," + base64.b64encode(b"synthetic").decode()}

    def perform(self, window, action, cancelled):
        self.calls.append(("action", copy.deepcopy(window), dict(action)))
        if self.on_perform:
            self.on_perform(cancelled)


class NativeWindowSelectionTests(unittest.TestCase):
    primary = [0, 0, 1920, 1080]

    def window(self, identifier, width=1470, height=923, **changes):
        value = {"kCGWindowOwnerPID": 123, "kCGWindowLayer": 0,
                 "kCGWindowNumber": identifier, "kCGWindowIsOnscreen": True,
                 "kCGWindowAlpha": 1, "kCGWindowName": "Synthetic private page title",
                 "kCGWindowBounds": {"X": 10, "Y": 44, "Width": width, "Height": height}}
        value.update(changes)
        return value

    def test_small_sharing_badge_is_skipped_and_front_browser_wins_over_largest(self):
        badge = self.window(1, 66, 20)
        front = self.window(2, 900, 700)
        background = self.window(3, 1470, 923)
        result = _front_chrome_window([badge, front, background], 123, self.primary)
        self.assertEqual(result["id"], 2)
        self.assertEqual(result["bounds"], [10, 44, 900, 700])
        self.assertNotIn("private", repr(result))

    def test_nonbrowser_hidden_transparent_and_malformed_entries_are_skipped(self):
        excluded = [self.window(1, kCGWindowOwnerPID=999), self.window(2, kCGWindowLayer=3),
                    self.window(3, kCGWindowIsOnscreen=False), self.window(4, kCGWindowAlpha=0),
                    self.window(5, kCGWindowBounds={}), self.window(6, kCGWindowNumber=None),
                    self.window(7, kCGWindowBounds={"X": float("nan"), "Y": 44, "Width": 900, "Height": 700}),
                    self.window(8, 300, 900), self.window(9, 900, 150), None]
        self.assertEqual(_front_chrome_window(excluded + [self.window(10)], 123, self.primary)["id"], 10)
        self.assertIsNone(_front_chrome_window(excluded, 123, self.primary))
        self.assertIsNone(_front_chrome_window(None, 123, self.primary))

    def test_bridged_native_integers_are_normalized_before_strict_window_guard(self):
        class BridgedInt(int):
            pass
        result = _front_chrome_window([self.window(BridgedInt(2))], BridgedInt(123), self.primary)
        self.assertIs(type(result["id"]), int)
        self.assertIs(type(result["pid"]), int)
        ComputerController._valid_window(result)

    def test_front_browser_outside_primary_is_not_replaced_by_a_background_window(self):
        outside = self.window(1, kCGWindowBounds={"X": 1920, "Y": 44, "Width": 900, "Height": 700})
        result = _front_chrome_window([outside, self.window(2)], 123, self.primary)
        self.assertEqual(result["id"], 1)
        with self.assertRaisesRegex(ComputerError, "primary"):
            ComputerController._valid_window(result)

    def test_native_inspect_uses_filtered_quartz_order_without_real_native_calls(self):
        quartz = SimpleNamespace(
            CGPreflightScreenCaptureAccess=lambda: True, CGMainDisplayID=lambda: 1,
            CGDisplayBounds=lambda _: SimpleNamespace(origin=SimpleNamespace(x=0, y=0), size=SimpleNamespace(width=1920, height=1080)),
            CGWindowListCopyWindowInfo=Mock(return_value=[self.window(1, 66, 20), self.window(2), self.window(3)]),
            kCGWindowListOptionOnScreenOnly=1, kCGWindowListExcludeDesktopElements=16, kCGNullWindowID=0)
        app = SimpleNamespace(bundleIdentifier=lambda: "com.google.Chrome", processIdentifier=lambda: 123)
        appkit = SimpleNamespace(NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(frontmostApplication=lambda: app)))
        permissions = SimpleNamespace(AXIsProcessTrusted=lambda: True)
        with patch.dict("sys.modules", {"Quartz": quartz, "AppKit": appkit, "ApplicationServices": permissions}):
            self.assertEqual(_native_inspect()["window"]["id"], 2)
        quartz.CGWindowListCopyWindowInfo.assert_called_once_with(17, 0)


class ComputerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.desktop = FakeDesktop()
        self.controller = ComputerController(backend=self.desktop, clock=lambda: self.now, wall_clock=lambda: 1000)

    def observe(self):
        if self.controller.grant is None:
            self.controller.enable()
        return self.controller.observe()["observation_id"]

    def test_initially_disabled_and_status_has_no_window_content(self):
        state = self.controller.status()
        self.assertFalse(state["enabled"])
        self.assertTrue(state["supported"])
        self.assertEqual(set(state), {"supported", "enabled", "expires_at", "scope", "permissions", "error", "active"})
        self.assertEqual(self.desktop.calls, [])
        with self.assertRaises(ComputerError):
            self.controller.observe()
        with self.assertRaises(ComputerError):
            self.controller.act("invented", {"type": "key", "keys": ["enter"]})

    def test_enable_requires_both_permissions_and_the_actual_chrome_window(self):
        for key in self.desktop.permissions:
            self.desktop.permissions[key] = False
            with self.assertRaises(ComputerError):
                self.controller.enable()
            self.desktop.permissions[key] = True
        self.desktop.window["app"] = "com.apple.Terminal"
        with self.assertRaises(ComputerError):
            self.controller.enable()
        self.assertIsNone(self.controller.grant)

    def test_status_is_cached_but_enable_and_actions_recheck_permissions(self):
        for _ in range(8):
            self.controller.status()
        self.assertEqual(self.desktop.inspections, 1)
        self.now += 2
        self.controller.status()
        self.assertEqual(self.desktop.inspections, 2)
        self.controller.enable()
        self.assertEqual(self.desktop.inspections, 3)
        identifier = self.controller.observe()["observation_id"]
        self.desktop.permissions["accessibility"] = False
        self.assertTrue(self.controller.status()["permissions"]["accessibility"])
        with self.assertRaisesRegex(ComputerError, "permission"):
            self.controller.act(identifier, {"type": "key", "keys": ["enter"]})
        self.assertFalse(self.controller.status()["enabled"])

    def test_complete_window_must_fit_primary_screen(self):
        self.desktop.window["bounds"][0] = 1000
        with self.assertRaisesRegex(ComputerError, "primary"):
            self.controller.enable()

    def test_duration_is_bounded_and_expiry_uses_monotonic_time(self):
        for value in (True, 0, -1, 16, float("nan"), "15"):
            with self.assertRaises(ComputerError):
                self.controller.enable(value)
        session = self.controller.enable(1)
        self.assertEqual(session["expires_at"], 1060)
        identifier = self.controller.observe()["observation_id"]
        self.now += 60
        with self.assertRaises(ComputerError):
            self.controller.act(identifier, {"type": "key", "keys": ["enter"]})
        self.assertFalse(self.controller.status()["enabled"])
        self.assertEqual([call[0] for call in self.desktop.calls], ["capture"])

    def test_click_maps_observed_pixels_to_actual_window_coordinates(self):
        identifier = self.observe()
        result = self.controller.act(identifier, {"type": "click", "x": 640, "y": 360})
        self.assertTrue(result["performed"])
        self.assertEqual(self.desktop.calls[-1][2], {"type": "click", "x": 900, "y": 500})
        self.assertIsNone(self.controller.observation)
        with self.assertRaises(ComputerError):
            self.controller.act(identifier, {"type": "click", "x": 1, "y": 1})

    def test_stale_unknown_or_replaced_observation_cannot_act(self):
        identifier = self.observe()
        self.now += 30
        with self.assertRaises(ComputerError):
            self.controller.act(identifier, {"type": "key", "keys": ["enter"]})
        old = self.controller.observe()["observation_id"]
        self.controller.observe()
        with self.assertRaises(ComputerError):
            self.controller.act(old, {"type": "key", "keys": ["enter"]})
        self.assertFalse(any(call[0] == "action" for call in self.desktop.calls))

    def test_revoke_and_permission_loss_invalidate_observations(self):
        identifier = self.observe()
        self.controller.revoke()
        with self.assertRaises(ComputerError):
            self.controller.act(identifier, {"type": "key", "keys": ["enter"]})
        identifier = self.observe()
        self.desktop.permissions["accessibility"] = False
        with self.assertRaises(ComputerError):
            self.controller.act(identifier, {"type": "key", "keys": ["enter"]})
        self.assertIsNone(self.controller.grant)

    def test_focus_window_and_geometry_changes_fail_closed(self):
        for field, value in (("id", 46), ("pid", 222), ("bounds", [101, 50, 1600, 900]), ("app", "com.apple.Terminal")):
            with self.subTest(field=field):
                self.setUp()
                identifier = self.observe()
                self.desktop.window[field] = value
                with self.assertRaises(ComputerError):
                    self.controller.act(identifier, {"type": "click", "x": 5, "y": 5})
                self.assertFalse(any(call[0] == "action" for call in self.desktop.calls))

    def test_focus_change_during_capture_does_not_publish_observation(self):
        self.controller.enable()
        self.desktop.on_capture = lambda _: self.desktop.window.update(id=99)
        with self.assertRaises(ComputerError):
            self.controller.observe()
        self.assertIsNone(self.controller.observation)

    def test_invalid_actions_consume_observation_without_native_action(self):
        actions = [{"type": "shell", "command": "ignored"}, {"type": "click", "x": -1, "y": 2},
                   {"type": "click", "x": 1280, "y": 2}, {"type": "click", "x": 1, "y": float("nan")},
                   {"type": "click", "x": True, "y": 2}, {"type": "scroll", "dx": 0, "dy": 9},
                   {"type": "key", "keys": ["command", "v"]},
                   {"type": "key", "keys": ["command", "shift", "j"]},
                   {"type": "type_text", "text": "javascript:alert(1)"},
                   {"type": "type_text", "text": "file:///private"},
                   {"type": "type_text", "text": "data:text/html,ignored"},
                   {"type": "type_text", "text": "one\ntwo"},
                   {"type": "type_text", "text": "x" * 1001},
                   {"type": "type_text", "text": "hello", "extra": "ignored"}]
        for action in actions:
            with self.subTest(action_type=action["type"]):
                identifier = self.observe()
                with self.assertRaises(ComputerError):
                    self.controller.act(identifier, action)
                self.assertIsNone(self.controller.observation)
        self.assertFalse(any(call[0] == "action" for call in self.desktop.calls))

    def test_unicode_typing_and_navigation_are_not_saved_in_controller_state(self):
        value = "Synthetic café query"
        self.controller.act(self.observe(), {"type": "type_text", "text": value})
        self.controller.act(self.observe(), {"type": "key", "keys": ["command", "l"]})
        self.controller.act(self.observe(), {"type": "scroll", "dx": 0, "dy": -3})
        self.assertNotIn(value, repr(self.controller.__dict__))
        self.assertNotIn("image_url", repr(self.controller.observation))

    def test_action_limit_and_uncertain_errors_do_not_allow_replay(self):
        identifier = self.observe()
        self.controller.grant["actions"] = 99
        def fail(_):
            raise RuntimeError("Synthetic private native diagnostics")
        self.desktop.on_perform = fail
        with self.assertRaisesRegex(ComputerError, "Computer action failed") as result:
            self.controller.act(identifier, {"type": "key", "keys": ["enter"]})
        self.assertNotIn("private", str(result.exception))
        with self.assertRaisesRegex(ComputerError, "limit"):
            self.controller.act(self.observe(), {"type": "key", "keys": ["enter"]})
        self.assertEqual(len([call for call in self.desktop.calls if call[0] == "action"]), 1)

    def test_cancel_can_interrupt_an_inflight_native_call_without_waiting_for_controller_lock(self):
        entered = threading.Event()
        def blocked(cancelled):
            entered.set()
            self.assertTrue(cancelled.wait(1))
            raise ComputerError("Computer action cancelled")
        self.desktop.on_perform = blocked
        identifier = self.observe()
        with ThreadPoolExecutor(2) as pool:
            action = pool.submit(self.controller.act, identifier, {"type": "key", "keys": ["enter"]})
            self.assertTrue(entered.wait(1))
            inspections = self.desktop.inspections
            for _ in range(8):
                self.assertTrue(self.controller.status()["active"])
            self.assertEqual(self.desktop.inspections, inspections)
            pool.submit(self.controller.cancel).result(timeout=1)
            with self.assertRaises(ComputerError):
                action.result(timeout=1)
        self.assertIsNone(self.controller.observation)
        self.assertFalse(self.controller.active)

    def test_cancelled_capture_is_not_exposed_and_new_observation_can_resume(self):
        self.controller.enable()
        self.desktop.on_capture = lambda cancelled: cancelled.set()
        with self.assertRaises(ComputerError):
            self.controller.observe()
        self.assertIsNone(self.controller.observation)
        self.desktop.on_capture = None
        self.assertIn("image_url", self.controller.observe())

    def test_image_encoder_caps_dimensions_and_bytes_using_only_synthetic_pixels(self):
        image = Image.effect_noise((2400, 1600), 80).convert("RGB")
        data, width, height = _image_bytes(image)
        self.assertLess(len(data), 349000)
        self.assertLessEqual(max(width, height), 1280)
        self.assertEqual(Image.open(io.BytesIO(data)).size, (width, height))

    def test_corner_failsafe_does_not_prevent_releasing_an_already_pressed_key(self):
        automation = Mock(FAILSAFE=True)
        def release(*args, **kwargs):
            self.assertFalse(automation.FAILSAFE)
            raise RuntimeError("Synthetic release failure")
        automation.keyUp.side_effect = release
        with self.assertRaises(RuntimeError):
            _release_input(automation, "keyUp", "command")
        self.assertTrue(automation.FAILSAFE)

    def test_native_timeout_stops_helper_and_never_exposes_stderr(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("synthetic", .05), (b"", None)]
        process.poll.return_value = None
        with patch("modulate.computer.sys.platform", "darwin"), patch("modulate.computer.subprocess.Popen", return_value=process), patch("modulate.computer.time.monotonic", side_effect=[0, 0, 6]):
            with self.assertRaisesRegex(ComputerError, "timed out"):
                MacOSBackend().inspect()
        process.terminate.assert_called_once()

    def test_unresponsive_native_helper_is_killed_after_graceful_stop_deadline(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("synthetic", .05),
                                          subprocess.TimeoutExpired("synthetic", .25), (b"", None)]
        process.poll.return_value = None
        with patch("modulate.computer.sys.platform", "darwin"), patch("modulate.computer.subprocess.Popen", return_value=process), patch("modulate.computer.time.monotonic", side_effect=[0, 0, 6]):
            with self.assertRaises(ComputerError):
                MacOSBackend().inspect()
        process.terminate.assert_called_once()
        process.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
