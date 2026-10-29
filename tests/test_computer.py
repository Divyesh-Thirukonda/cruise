"""Synthetic primary-desktop tests; never capture or act on the actual Mac."""
import base64
import copy
import io
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from modulate.computer import (ComputerController, ComputerError, MacOSBackend,
                              _image_bytes, _native, _native_guard, _native_inspect,
                              _native_launch_app, _release_input)


class FakeDesktop:
    def __init__(self):
        self.permissions = {"screen_recording": True, "accessibility": True}
        self.desktop = {"id": 1, "bounds": [0, 0, 1920, 1080]}
        self.calls = []
        self.inspections = 0
        self.on_capture = self.on_perform = None
        self.foreground = "com.apple.TextEdit"
        self.image_size = (1280, 720)

    def inspect(self):
        self.inspections += 1
        return {"supported": True, "permissions": dict(self.permissions), "desktop": copy.deepcopy(self.desktop)}

    def capture(self, desktop, cancelled):
        self.calls.append(("capture", copy.deepcopy(desktop)))
        if self.on_capture:
            self.on_capture(cancelled)
        return {"width": self.image_size[0], "height": self.image_size[1],
                "image_url": "data:image/jpeg;base64," + base64.b64encode(b"synthetic").decode()}

    def perform(self, desktop, action, cancelled):
        self.calls.append(("action", copy.deepcopy(desktop), dict(action)))
        if self.on_perform:
            self.on_perform(cancelled)


class ComputerTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.desktop = FakeDesktop()
        self.controller = ComputerController(backend=self.desktop, clock=lambda: self.now, wall_clock=lambda: 1000)

    def pair(self, identifier="a" * 32):
        self.controller.sync_pairing(identifier)

    def observe(self):
        if self.controller.grant is None:
            self.pair()
        return self.controller.observe()["observation_id"]

    def test_no_pairing_cannot_observe_act_or_self_authorize(self):
        self.assertFalse(self.controller.status()["enabled"])
        for call in (self.controller.observe, self.controller.enable,
                     lambda: self.controller.act("invented", {"type": "key", "keys": ["enter"]})):
            with self.assertRaises(ComputerError): call()
        self.assertEqual(self.desktop.calls, [])

    def test_pairing_has_no_independent_expiry_and_restart_requires_owner_restoration(self):
        self.pair()
        self.now += 1_000_000
        state = self.controller.status()
        self.assertTrue(state["enabled"])
        self.assertIsNone(state["expires_at"])
        self.assertIn("full primary desktop", state["scope"])
        reopened = ComputerController(backend=self.desktop)
        with self.assertRaises(ComputerError): reopened.observe()
        reopened.sync_pairing("a" * 32)
        self.assertIn("image_url", reopened.observe())

    def test_invalid_pairing_identity_never_creates_a_grant(self):
        for value in (True, 1, "", "x" * 129, "with space", "bad\0id", "é"):
            with self.subTest(value=value), self.assertRaises(ComputerError):
                self.controller.sync_pairing(value)
        self.assertIsNone(self.controller.grant)

    def test_same_pairing_never_resets_cancel_or_action_count(self):
        self.pair()
        self.controller.grant["actions"] = 9
        self.controller.cancel()
        self.pair()
        self.assertTrue(self.controller.cancelled.is_set())
        self.assertEqual(self.controller.grant["actions"], 9)
        with self.assertRaises(ComputerError): self.controller.observe()
        self.controller.begin_task()
        self.assertEqual(self.controller.grant["actions"], 0)
        self.assertIn("image_url", self.controller.observe())

    def test_changed_pairing_and_revocation_invalidate_observations(self):
        old = self.observe()
        self.pair("b" * 32)
        with self.assertRaises(ComputerError): self.controller.act(old, {"type": "key", "keys": ["enter"]})
        fresh = self.controller.observe()["observation_id"]
        self.controller.sync_pairing(None)
        self.controller.begin_task()
        with self.assertRaises(ComputerError): self.controller.act(fresh, {"type": "key", "keys": ["enter"]})
        self.assertFalse(self.controller.status()["enabled"])

    def test_both_os_permissions_required_and_can_recover_without_repairing(self):
        self.pair()
        for name in self.desktop.permissions:
            self.desktop.permissions[name] = False
            with self.assertRaisesRegex(ComputerError, "Screen Recording"):
                self.controller.observe()
            self.assertIsNone(self.controller.observation)
            self.desktop.permissions[name] = True
        self.assertIn("image_url", self.controller.observe())
        self.assertTrue(self.controller.status()["enabled"])

    def test_status_cached_but_capture_and_actions_recheck_permissions(self):
        self.pair()
        for _ in range(8): self.controller.status()
        self.assertEqual(self.desktop.inspections, 1)
        old = self.controller.observe()["observation_id"]
        self.desktop.permissions["accessibility"] = False
        with self.assertRaises(ComputerError): self.controller.act(old, {"type": "key", "keys": ["enter"]})
        self.assertFalse(any(call[0] == "action" for call in self.desktop.calls))

    def test_any_foreground_app_is_allowed_and_focus_does_not_raise_an_app(self):
        self.pair()
        self.assertFalse(self.controller.focus()["focused"])
        self.assertEqual(self.desktop.calls, [])
        old = self.controller.observe()["observation_id"]
        self.desktop.foreground = "com.apple.systempreferences"
        self.assertTrue(self.controller.act(old, {"type": "key", "keys": ["tab"]})["performed"])

    def test_normalized_center_edges_drag_and_retina_use_primary_display(self):
        self.desktop.desktop["bounds"] = [10, 20, 800, 450]
        for size in ((800, 450), (1280, 720), (640, 360)):
            self.desktop.image_size = size
            self.controller.act(self.observe(), {"type": "click", "x": 500, "y": 500})
            self.assertEqual(self.desktop.calls[-1][2], {"type": "click", "x": 410, "y": 245})
        self.controller.act(self.observe(), {"type": "drag", "x": 0, "y": 0, "to_x": 1000, "to_y": 1000})
        self.assertEqual(self.desktop.calls[-1][2], {"type": "drag", "x": 10, "y": 20, "to_x": 809, "to_y": 469})
        self.controller.act(self.observe(), {"type": "right_click", "x": 1000, "y": 0})
        self.assertEqual(self.desktop.calls[-1][2]["x"], 809)

    def test_stale_replaced_and_replayed_observations_cannot_act(self):
        old = self.observe()
        self.now += 30
        with self.assertRaises(ComputerError): self.controller.act(old, {"type": "key", "keys": ["enter"]})
        old = self.observe()
        self.controller.observe()
        with self.assertRaises(ComputerError): self.controller.act(old, {"type": "key", "keys": ["enter"]})
        fresh = self.observe()
        self.controller.act(fresh, {"type": "key", "keys": ["enter"]})
        with self.assertRaises(ComputerError): self.controller.act(fresh, {"type": "key", "keys": ["enter"]})

    def test_display_changes_require_new_observation_without_revoking_pairing(self):
        old = self.observe()
        self.desktop.desktop["bounds"][2] = 1600
        with self.assertRaisesRegex(ComputerError, "Observe"):
            self.controller.act(old, {"type": "click", "x": 500, "y": 500})
        fresh = self.controller.observe()["observation_id"]
        self.controller.act(fresh, {"type": "click", "x": 500, "y": 500})
        self.assertEqual(self.desktop.calls[-1][2]["x"], 800)

    def test_display_change_or_cancellation_during_capture_drops_image(self):
        self.pair()
        for callback in (lambda _: self.desktop.desktop.update(id=2), lambda event: event.set()):
            self.desktop.desktop["id"] = 1
            self.controller.begin_task()
            self.desktop.on_capture = callback
            with self.assertRaises(ComputerError): self.controller.observe()
            self.assertIsNone(self.controller.observation)

    def test_invalid_desktop_geometry_is_rejected(self):
        self.pair()
        for value in ({}, {"id": True, "bounds": [0, 0, 800, 600]}, {"id": 1, "bounds": [0, 0, 0, 600]},
                      {"id": 1, "bounds": [0, 0, float('nan'), 600]}, {"id": 1, "bounds": [0, 0, 100000, 600]}):
            self.desktop.desktop = value
            with self.assertRaises(ComputerError): self.controller.observe()

    def test_invalid_actions_consume_observation_without_native_side_effect(self):
        actions = [{"type": "shell", "command": "ignored"}, {"type": "click", "x": -1, "y": 2},
                   {"type": "drag", "x": 0, "y": 0, "to_x": 1001, "to_y": 0},
                   {"type": "click", "x": True, "y": 2}, {"type": "click", "x": 1.5, "y": 2},
                   {"type": "scroll", "dx": 0, "dy": 9}, {"type": "key", "keys": ["command", "cmd", "v"]},
                   {"type": "key", "keys": ["a", "b"]}, {"type": "key", "keys": ["unknown"]},
                   {"type": "launch_app", "bundle_id": "com.apple.TextEdit;open"},
                   {"type": "launch_app", "bundle_id": "/Applications/TextEdit.app"},
                   {"type": "launch_app", "bundle_id": "com.apple.TextEdit", "args": ["ignored"]},
                   {"type": "type_text", "text": "bad\0text"}, {"type": "type_text", "text": "x" * 1001}]
        for action in actions:
            with self.subTest(action=action), self.assertRaises(ComputerError):
                self.controller.act(self.observe(), action)
            self.assertIsNone(self.controller.observation)
        self.assertFalse(any(call[0] == "action" for call in self.desktop.calls))

    def test_modifiers_app_launch_unicode_paragraphs_and_clipboard_hotkeys_are_bounded(self):
        for keys in (["command", "tab"], ["command", "space"], ["command", "shift", "v"],
                     ["ctrl", "alt", "shift", "command", "f1"]):
            self.controller.act(self.observe(), {"type": "key", "keys": keys})
        self.controller.act(self.observe(), {"type": "launch_app", "bundle_id": "com.apple.systempreferences"})
        text = "Synthetic café\nSecond paragraph\tTabbed"
        self.controller.act(self.observe(), {"type": "type_text", "text": text})
        self.assertNotIn(text, repr(self.controller.__dict__))
        self.assertNotIn("image_url", repr(self.controller.observation))

    def test_action_limit_and_uncertain_errors_count_once_and_reset_only_on_new_task(self):
        self.pair()
        self.controller.grant["actions"] = 99
        def fail(_): raise RuntimeError("Synthetic private diagnostics")
        self.desktop.on_perform = fail
        with self.assertRaisesRegex(ComputerError, "Computer action failed") as error:
            self.controller.act(self.observe(), {"type": "key", "keys": ["enter"]})
        self.assertNotIn("private", str(error.exception))
        self.pair()
        with self.assertRaisesRegex(ComputerError, "limit"):
            self.controller.act(self.observe(), {"type": "key", "keys": ["enter"]})
        self.controller.begin_task()
        self.desktop.on_perform = None
        self.controller.act(self.observe(), {"type": "key", "keys": ["enter"]})
        self.assertEqual(self.controller.grant["actions"], 1)

    def test_cancel_interrupts_native_work_and_status_and_pair_sync_do_not_block(self):
        entered = threading.Event()
        def blocked(cancelled):
            entered.set()
            self.assertTrue(cancelled.wait(1))
            raise ComputerError("Computer action cancelled")
        self.desktop.on_perform = blocked
        old = self.observe()
        with ThreadPoolExecutor(2) as pool:
            work = pool.submit(self.controller.act, old, {"type": "key", "keys": ["enter"]})
            self.assertTrue(entered.wait(1))
            for _ in range(8):
                self.assertTrue(self.controller.status()["active"])
                self.pair()
            pool.submit(self.controller.cancel).result(1)
            with self.assertRaises(ComputerError): work.result(1)
        self.assertFalse(self.controller.active)
        with self.assertRaises(ComputerError): self.controller.observe()

    def test_pairing_change_interrupts_old_work_before_new_session_is_installed(self):
        entered = threading.Event()
        def blocked(cancelled):
            entered.set()
            self.assertTrue(cancelled.wait(1))
            raise ComputerError("Computer action cancelled")
        self.desktop.on_perform = blocked
        old = self.observe()
        with ThreadPoolExecutor(2) as pool:
            work = pool.submit(self.controller.act, old, {"type": "key", "keys": ["enter"]})
            self.assertTrue(entered.wait(1))
            pool.submit(self.controller.sync_pairing, "b" * 32).result(1)
            with self.assertRaises(ComputerError): work.result(1)
        self.assertEqual(self.controller.grant["session_id"], "b" * 32)
        self.assertIsNone(self.controller.observation)


class NativeHelperTests(unittest.TestCase):
    def test_inspect_primary_display_does_not_depend_on_front_app_or_window(self):
        class BridgedInt(int): pass
        quartz = SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: True,
            CGMainDisplayID=lambda: BridgedInt(1), CGDisplayBounds=lambda _: SimpleNamespace(
                origin=SimpleNamespace(x=0, y=0), size=SimpleNamespace(width=1920, height=1080)))
        with patch.dict("sys.modules", {"Quartz": quartz, "ApplicationServices": SimpleNamespace(AXIsProcessTrusted=lambda: True)}):
            self.assertEqual(_native_inspect()["desktop"], {"id": 1, "bounds": [0, 0, 1920, 1080]})

    def test_native_guard_rejects_permission_and_topology_changes(self):
        desktop = {"id": 1, "bounds": [0, 0, 1920, 1080]}
        for value in ({"desktop": desktop, "permissions": {"screen_recording": False, "accessibility": True}},
                      {"desktop": {**desktop, "id": 2}, "permissions": {"screen_recording": True, "accessibility": True}}):
            with patch("modulate.computer._native_inspect", return_value=value), self.assertRaises(ComputerError):
                _native_guard(desktop)

    def test_bundle_launch_uses_only_native_lookup_and_reports_missing_or_failed_apps(self):
        workspace, configuration = Mock(), Mock()
        workspace.URLForApplicationWithBundleIdentifier_.return_value = "synthetic-installed-url"
        workspace.openApplicationAtURL_configuration_completionHandler_.side_effect = lambda url, cfg, done: done(object(), None)
        appkit = SimpleNamespace(NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace),
                                 NSWorkspaceOpenConfiguration=SimpleNamespace(configuration=lambda: configuration))
        with patch.dict("sys.modules", {"AppKit": appkit}):
            self.assertTrue(_native_launch_app("com.apple.TextEdit")["performed"])
            workspace.URLForApplicationWithBundleIdentifier_.assert_called_once_with("com.apple.TextEdit")
            configuration.setActivates_.assert_called_once_with(True)
            workspace.URLForApplicationWithBundleIdentifier_.return_value = None
            with self.assertRaisesRegex(ComputerError, "not installed"): _native_launch_app("com.example.Missing")
            workspace.URLForApplicationWithBundleIdentifier_.return_value = "synthetic-installed-url"
            workspace.openApplicationAtURL_configuration_completionHandler_.side_effect = lambda url, cfg, done: done(None, object())
            with self.assertRaisesRegex(ComputerError, "not confirmed"): _native_launch_app("com.apple.TextEdit")

    def test_drag_releases_mouse_even_if_display_changes_mid_drag(self):
        automation = Mock(FAILSAFE=True)
        payload = {"desktop": {"id": 1, "bounds": [0, 0, 1920, 1080]},
                   "action": {"type": "drag", "x": 20, "y": 30, "to_x": 200, "to_y": 300}}
        with patch.dict("sys.modules", {"pyautogui": automation, "Quartz": Mock()}), \
             patch("modulate.computer._native_guard", side_effect=[None, None, None, ComputerError("Display changed")]):
            with self.assertRaises(ComputerError): _native("action", payload)
        automation.mouseDown.assert_called_once_with(_pause=False)
        automation.mouseUp.assert_called_once_with(_pause=False)
        self.assertTrue(automation.FAILSAFE)

    def test_corner_failsafe_does_not_prevent_key_release(self):
        automation = Mock(FAILSAFE=True)
        def release(*args, **kwargs):
            self.assertFalse(automation.FAILSAFE)
            raise RuntimeError("Synthetic release failure")
        automation.keyUp.side_effect = release
        with self.assertRaises(RuntimeError): _release_input(automation, "keyUp", "command")
        self.assertTrue(automation.FAILSAFE)

    def test_image_encoder_bounds_synthetic_retina_image(self):
        data, width, height = _image_bytes(Image.effect_noise((2400, 1600), 80).convert("RGB"))
        self.assertLess(len(data), 349000)
        self.assertLessEqual(max(width, height), 1280)
        self.assertEqual(Image.open(io.BytesIO(data)).size, (width, height))

    def test_native_timeout_stops_helper_without_exposing_diagnostics(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("synthetic", .05), (b"", None)]
        process.poll.return_value = None
        with patch("modulate.computer.sys.platform", "darwin"), patch("modulate.computer.subprocess.Popen", return_value=process), \
             patch("modulate.computer.time.monotonic", side_effect=[0, 0, 6]):
            with self.assertRaisesRegex(ComputerError, "timed out"): MacOSBackend().inspect()
        process.terminate.assert_called_once()

    def test_unresponsive_helper_is_killed_after_release_grace(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("synthetic", .05),
                                          subprocess.TimeoutExpired("synthetic", .25), (b"", None)]
        process.poll.return_value = None
        with patch("modulate.computer.sys.platform", "darwin"), patch("modulate.computer.subprocess.Popen", return_value=process), \
             patch("modulate.computer.time.monotonic", side_effect=[0, 0, 6]):
            with self.assertRaises(ComputerError): MacOSBackend().inspect()
        process.kill.assert_called_once()


if __name__ == '__main__':
    unittest.main()
