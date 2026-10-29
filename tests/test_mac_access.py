"""Paired Mac authority and transient camera flow; no native calls or real frames."""
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from modulate.agent import AgentError
from modulate.product import Product
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend


class SettingsBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.brightness = 50
        self.brightness_supported = True
        self.brightness_calls = []

    def capabilities(self):
        return {**super().capabilities(), "brightness": self.brightness_supported}

    def get_brightness(self):
        return self.brightness

    def set_brightness(self, value):
        self.brightness_calls.append(value)
        self.brightness = value


class FakeCamera:
    def __init__(self):
        self.supported = True
        self.state = "stopped"
        self.starts = self.stops = self.refreshes = 0
        self.stopped = threading.Event()
        self.image = {"sequence": 1, "jpeg": b"SYNTHETIC_PRIVATE_CAMERA_BYTES"}

    def status(self):
        return {"supported": self.supported, "state": self.state, "running": self.state == "running",
                "permission": "authorized", "error": None}

    def start(self):
        self.starts += 1
        self.state = "running"
        self.stopped.clear()
        return self.status()

    def stop(self):
        self.stops += 1
        self.state = "stopped"
        self.stopped.set()
        return self.status()

    def refresh_access(self):
        self.refreshes += 1
        return self.status()

    def frame(self):
        return dict(self.image) if self.state == "running" else None


class MacAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = SettingsBackend()
        self.computer = FakeComputer()
        self.product = Product(Path(self.temp.name), SyntheticProvider([]), backend=self.backend, computer=self.computer)
        self.addCleanup(self.product.cancel)
        self.camera = self.product.camera = FakeCamera()
        self.now = 1000
        self.product.bridge.clock = lambda: self.now
        self.product.last_seen = time.monotonic()
        self.guard = patch.object(self.product, '_start_camera_guard')
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def pair(self):
        self.product.last_seen = time.monotonic()
        code = self.product.create_pairing()['code']
        result = self.product.pair(code, 'Synthetic controller')
        self.product._sync_computer_pairing()
        return result

    def camera_app(self, target):
        self.product.active = {'revision': 'f' * 64, 'package': {'kind': 'game', 'camera': {'target': target}}}
        self.camera.state = 'running'

    def test_system_settings_use_pairing_without_screen_recording_or_accessibility(self):
        self.pair()
        self.computer.permissions = {'screen_recording': False, 'accessibility': False}
        self.assertFalse(self.product.computer_status()['enabled'])
        self.assertEqual(self.product.system_control('volume.set', 61)['volume'], 61)
        self.assertEqual(self.product.system_control('brightness.set', 73)['brightness'], 73)
        self.assertEqual(self.backend.actions, [61])
        self.assertEqual(self.backend.brightness_calls, [73])
        self.assertEqual(self.computer.actions, [])
        self.assertEqual(self.computer.observations, 0)

    def test_missing_expired_or_paused_pairing_cannot_change_settings(self):
        with self.assertRaises(AgentError): self.product.system_control('volume.set', 10)
        self.pair()
        self.product.computer_session('revoke')
        with self.assertRaises(AgentError): self.product.system_control('volume.set', 10)
        self.product.computer_session('enable')
        self.now += 8 * 60 * 60
        with self.assertRaises(AgentError): self.product.system_control('volume.set', 10)
        self.assertEqual(self.backend.actions, [])

    def test_unadvertised_actions_and_arbitrary_commands_cannot_reach_backend(self):
        self.pair()
        self.backend.brightness_supported = False
        for action in ('shell', 'volume.execute', 'brightness.set'):
            with self.assertRaises(AgentError): self.product.system_control(action, 50)
        with self.assertRaises(AgentError): self.product.camera_control('execute')
        self.assertEqual(self.backend.actions, [])
        self.assertEqual(self.backend.brightness_calls, [])
        self.assertEqual(self.camera.starts, 0)

    def test_system_values_keep_bridge_type_and_range_checks(self):
        self.pair()
        for action, value in (('volume.set', True), ('volume.set', 101), ('brightness.set', -1),
                              ('brightness.delta', 11), ('volume.get', 1)):
            with self.subTest(action=action, value=value), self.assertRaises(AgentError):
                self.product.system_control(action, value)
        self.assertEqual(self.backend.actions, [])
        self.assertEqual(self.backend.brightness_calls, [])

    def test_pairing_revoke_stops_desktop_and_camera(self):
        grant = self.pair()
        self.camera_app(grant['session_id'])
        self.product.revoke()
        self.assertFalse(self.computer.enabled)
        self.assertTrue(self.computer.cancelled)
        self.assertFalse(self.camera.status()['running'])
        self.assertIsNone(self.product._camera_packet())

    def test_disconnect_or_expiry_failed_authorization_cancels_desktop_and_camera(self):
        for reason in ('disconnect', 'expiry'):
            with self.subTest(reason=reason):
                grant = self.pair()
                self.camera_app(grant['session_id'])
                before = self.computer.cancellations
                if reason == 'disconnect': self.product.last_seen = None
                else: self.now += 8 * 60 * 60
                with self.assertRaises(AgentError): self.product.computer_observe()
                self.assertGreater(self.computer.cancellations, before)
                self.assertFalse(self.computer.enabled)
                self.assertFalse(self.camera.status()['running'])

    def test_repeated_pairing_sync_cannot_undo_manual_stop(self):
        grant = self.pair()
        self.camera_app(grant['session_id'])
        self.product.computer_session('revoke')
        for _ in range(5):
            self.product._sync_computer_pairing()
            self.product._sync_camera()
        self.assertFalse(self.computer.enabled)
        self.assertFalse(self.camera.status()['running'])
        self.assertTrue(self.product.computer_paused)
        self.product.computer_session('enable')
        self.assertEqual(self.computer.session_id, grant['session_id'])
        self.assertTrue(self.product.computer_status()['enabled'])

    def test_manual_pause_survives_companion_restart_with_same_valid_pairing(self):
        grant = self.pair()
        self.product.computer_session('revoke')
        computer = FakeComputer()
        reopened = Product(Path(self.temp.name), SyntheticProvider([]), backend=self.backend, computer=computer)
        self.addCleanup(reopened.cancel)
        reopened.bridge.clock = lambda: self.now
        reopened.last_seen = time.monotonic()
        reopened.volume_token = grant['token']  # Simulates the authenticated controller restoring its token.
        reopened._sync_computer_pairing()
        self.assertTrue(reopened.computer_paused)
        self.assertFalse(computer.enabled)
        with self.assertRaises(AgentError): reopened.system_control('volume.set', 20)

    def test_disconnect_guards_stop_desktop_and_camera_without_ui_or_new_tool_calls(self):
        grant = self.pair()
        self.camera_app(grant['session_id'])
        self.product.running = True
        self.guard.stop()  # Exercise the actual bounded background guards.
        self.product._start_camera_guard()
        self.product._start_access_guard()
        self.product.last_seen = None
        self.product.access_guard.join(timeout=1.5)
        self.product.camera_guard.join(timeout=1.5)
        self.product.running = False
        self.assertFalse(self.product.access_guard.is_alive())
        self.assertFalse(self.product.camera_guard.is_alive())
        self.assertTrue(self.computer.cancelled)
        self.assertFalse(self.camera.status()['running'])

    def test_camera_requires_pair_before_any_permission_request_or_start(self):
        for action in ('start', 'status'):
            with self.assertRaises(AgentError): self.product.camera_control(action)
        self.assertEqual((self.camera.starts, self.camera.refreshes), (0, 0))
        self.pair()
        self.product.running = True
        self.assertTrue(self.product.camera_control('start')['running'])
        self.assertEqual(self.camera.starts, 1)
        self.assertEqual(self.computer.observations, 0)

    def test_camera_target_must_match_current_pairing_and_supported_adapter(self):
        grant = self.pair()
        with self.assertRaises(AgentError): self.product.validate_camera({'camera': {'target': 'wrong'}})
        self.product.validate_camera({'camera': {'target': grant['session_id']}})
        self.camera.supported = False
        with self.assertRaises(AgentError): self.product.validate_camera({'camera': {'target': grant['session_id']}})

    def test_camera_packets_are_revision_bound_and_never_persisted_or_exposed_in_metadata(self):
        grant = self.pair()
        self.camera_app(grant['session_id'])
        packet = self.product._camera_packet()
        self.assertEqual(packet['revision'], self.product.revision)
        self.assertEqual(base64.b64decode(packet['jpeg']), self.camera.image['jpeg'])
        self.assertEqual(packet['sequence'], 1)
        self.assertNotIn('PRIVATE_CAMERA', json.dumps(self.product.camera_status()))
        for path in Path(self.temp.name).rglob('*'):
            if path.is_file(): self.assertNotIn(b'PRIVATE_CAMERA', path.read_bytes())
        self.product.last_seen = None
        self.assertIsNone(self.product._camera_packet())

    def test_explicit_camera_stop_survives_same_app_sync_and_requires_new_start(self):
        grant = self.pair()
        self.camera_app(grant['session_id'])
        self.product.camera_control('stop')
        self.product._sync_camera()
        self.assertIsNone(self.product._camera_packet())
        self.assertEqual(self.camera.starts, 0)
        self.product.camera_control('start')
        self.assertEqual(self.camera.starts, 1)
        self.assertIsNotNone(self.product._camera_packet())

    def test_failed_camera_is_not_restarted_each_sync(self):
        grant = self.pair()
        self.camera_app(grant['session_id'])
        self.camera.state = 'error'
        for _ in range(5): self.product._sync_camera()
        self.assertEqual(self.camera.starts, 0)
        self.product.camera_control('start')
        self.assertEqual(self.camera.starts, 1)


if __name__ == '__main__':
    unittest.main()
