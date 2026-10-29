"""Bridge system-setting semantics with fake hardware; no native settings change."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from modulate.host_bridge import (
    AuthenticationError, BackendError, BridgeError, BridgeStore,
    MacOSVolumeBackend, PairingError, RateLimitError, ReplayError,
    StateError, UnsupportedPlatformError, default_backend,
)


class FakeBackend:
    def __init__(self):
        self.volume = 40
        self.muted = False
        self.calls = []
        self.brightness = 55
        self.brightness_supported = False

    def capabilities(self):
        return {"supported": True, "platform": "test", "brightness": self.brightness_supported}

    def get(self):
        self.calls.append("get")
        return {"volume": self.volume, "muted": self.muted}

    def set_volume(self, value):
        self.calls.append(("set_volume", value))
        self.volume = value

    def set_muted(self, value):
        self.calls.append(("set_muted", value))
        self.muted = value

    def get_brightness(self):
        self.calls.append("get_brightness")
        return self.brightness

    def set_brightness(self, value):
        self.calls.append(("set_brightness", value))
        self.brightness = value


class BridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.now = 1_000_000.0
        self.backend = FakeBackend()
        self.store = self.reopen()

    def reopen(self):
        return BridgeStore(self.directory, self.backend, clock=lambda: self.now)

    def pair(self, name="Modulate Pi"):
        code = self.store.create_pairing()["code"]
        return self.store.pair(code, name)

    def test_one_time_code_creates_supported_session_without_persisting_credentials(self):
        with patch("modulate.host_bridge.secrets.randbelow", return_value=12003456):
            pairing = self.store.create_pairing()
        self.assertEqual(pairing, {"code": "12003456", "expires_at": self.now + 120})
        self.assertNotIn(pairing["code"], self.store.path.read_text())
        token = self.store.pair(pairing["code"], "Modulate Pi")
        self.assertNotIn(token, self.store.path.read_text())
        session = self.reopen().session(token)
        self.assertEqual(session["next_sequence"], 1)
        self.assertEqual(session["expires_at"], self.now + 8 * 60 * 60)
        self.assertEqual(session["capabilities"]["actions"],
                         ["volume.get", "volume.delta", "volume.mute", "volume.set"])
        self.assertNotIn("token_hash", session)
        with self.assertRaises(PairingError):
            self.store.pair(pairing["code"], "Other Pi")
        self.assertEqual(self.backend.calls, [])
        if os.name != "nt":
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)

    def test_code_expiry_is_enforced_at_boundary(self):
        pairing = self.store.create_pairing()
        self.now = pairing["expires_at"]
        with self.assertRaises(PairingError):
            self.store.pair(pairing["code"], "Pi")

    def test_new_pairing_code_invalidates_previous(self):
        with patch("modulate.host_bridge.secrets.randbelow", side_effect=[12345678, 87654321]):
            older = self.store.create_pairing()["code"]
            newer = self.store.create_pairing()["code"]
        with self.assertRaises(PairingError):
            self.store.pair(older, "Pi")
        self.assertTrue(self.store.session(self.store.pair(newer, "Pi")))

    def test_throttle_persists_across_restarts_and_code_replacement(self):
        for _ in range(5):
            with self.assertRaises(PairingError):
                self.reopen().pair("invalid", "Pi")
        pairing = self.reopen().create_pairing()
        with self.assertRaises(RateLimitError):
            self.reopen().pair(pairing["code"], "Pi")
        self.now += 60
        self.assertTrue(self.reopen().session(self.reopen().pair(pairing["code"], "Pi")))

    def test_invalid_tokens_and_expired_sessions_never_call_backend(self):
        token = self.pair()
        for invalid in (None, "", "x" * 43, "é" * 43, token[:-1]):
            with self.subTest(token=invalid):
                with self.assertRaises(AuthenticationError):
                    self.store.execute(invalid, 1, "volume.delta", 1)
        self.now = self.store.session(token)["expires_at"]
        with self.assertRaises(AuthenticationError):
            self.store.execute(token, 1, "volume.get")
        self.assertEqual(self.backend.calls, [])

    def test_delta_reads_actual_host_volume_and_clamps_at_both_limits(self):
        token = self.pair()
        self.assertEqual(self.store.execute(token, 1, "volume.delta", 7),
                         {"volume": 47, "muted": False, "sequence": 1})
        self.backend.volume = 98  # An external host control changed volume.
        self.assertEqual(self.store.execute(token, 2, "volume.delta", 10)["volume"], 100)
        self.backend.volume = 3
        self.assertEqual(self.store.execute(token, 3, "volume.delta", -10)["volume"], 0)
        self.assertTrue(self.store.execute(token, 4, "volume.mute", True)["muted"])
        self.assertFalse(self.store.execute(token, 5, "volume.mute", False)["muted"])
        self.assertEqual(self.store.execute(token, 6, "volume.get")["volume"], 0)

    def test_stale_and_duplicate_sequence_rejected_after_restart(self):
        token = self.pair()
        self.store.execute(token, 3, "volume.delta", 5)
        self.backend.calls.clear()
        for sequence in (1, 2, 3, 0, -1, True, 1.5, "4", 1 << 53):
            with self.subTest(sequence=sequence):
                with self.assertRaises(ReplayError):
                    self.reopen().execute(token, sequence, "volume.delta", 5)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.reopen().session(token)["next_sequence"], 4)

    def test_invalid_actions_and_values_do_not_consume_sequence(self):
        token = self.pair()
        invalid = [("shell.run", "synthetic forbidden action"), ("volume.set", -1), ("volume.set", 101),
                   ("volume.set", True), ("volume.set", 50.0), ("volume.set", None), ("volume.delta", 11),
                   ("volume.delta", -11), ("volume.delta", True), ("volume.delta", 2.5),
                   ("volume.delta", "3"), ("volume.mute", 1), ("volume.mute", "false"),
                   ("volume.get", {}), ("volume.delta", None)]
        for action, value in invalid:
            with self.subTest(action=action, value=value):
                with self.assertRaises(BridgeError):
                    self.store.execute(token, 1, action, value)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.store.session(token)["next_sequence"], 1)

    def test_paired_volume_set_needs_no_second_code_or_approval_and_retains_replay_guard(self):
        token = self.pair()
        self.assertEqual(self.store.execute(token, 1, "volume.set", 75),
                         {"volume": 75, "muted": False, "sequence": 1})
        self.assertEqual(self.backend.calls, [("set_volume", 75), "get"])
        self.backend.calls.clear()
        with self.assertRaises(ReplayError):
            self.reopen().execute(token, 1, "volume.set", 0)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.reopen().execute(token, 2, "volume.set", 0)["volume"], 0)
        self.assertNotIn(token, self.store.path.read_text())

    def test_brightness_advertises_only_when_supported_and_rechecks_before_action(self):
        token = self.pair()
        self.assertFalse(any(action.startswith("brightness.") for action in self.store.capabilities()["actions"]))
        with self.assertRaises(BridgeError):
            self.store.execute(token, 1, "brightness.set", 50)
        self.backend.brightness_supported = True
        self.assertTrue({"brightness.get", "brightness.set", "brightness.delta"} <=
                        set(self.store.session(token)["capabilities"]["actions"]))
        self.backend.brightness_supported = False
        with self.assertRaises(BridgeError):
            self.store.execute(token, 1, "brightness.get")
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.store.session(token)["next_sequence"], 1)

    def test_brightness_uses_actual_value_clamps_and_shares_volume_sequence(self):
        self.backend.brightness_supported = True
        token = self.pair()
        self.assertEqual(self.store.execute(token, 1, "brightness.get"), {"brightness": 55, "sequence": 1})
        self.assertEqual(self.store.execute(token, 2, "brightness.set", 75), {"brightness": 75, "sequence": 2})
        self.backend.brightness = 98  # Synthetic external setting change.
        self.assertEqual(self.store.execute(token, 3, "brightness.delta", 10)["brightness"], 100)
        self.backend.brightness = 2
        self.assertEqual(self.store.execute(token, 4, "brightness.delta", -10)["brightness"], 0)
        self.backend.calls.clear()
        for action in ("brightness.set", "volume.set"):
            with self.assertRaises(ReplayError):
                self.reopen().execute(token, 4, action, 60)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.reopen().session(token)["next_sequence"], 5)

    def test_invalid_brightness_values_never_call_backend_or_consume_sequence(self):
        self.backend.brightness_supported = True
        token = self.pair()
        bad = [("brightness.set", -1), ("brightness.set", 101), ("brightness.set", True),
               ("brightness.set", 50.0), ("brightness.set", "50"), ("brightness.set", None),
               ("brightness.delta", -11), ("brightness.delta", 11), ("brightness.delta", False),
               ("brightness.delta", float("nan")), ("brightness.get", 0), ("brightness.mute", True)]
        for action, value in bad:
            with self.subTest(action=action, value=value), self.assertRaises(BridgeError):
                self.store.execute(token, 1, action, value)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.store.session(token)["next_sequence"], 1)

    def test_invalid_current_brightness_never_becomes_a_write(self):
        self.backend.brightness_supported = True
        token = self.pair()
        for sequence, value in enumerate((True, -1, 101, 1.5, "50", None), 1):
            self.backend.calls.clear()
            self.backend.brightness = value
            with self.subTest(value=value), self.assertRaises(BackendError):
                self.store.execute(token, sequence, "brightness.delta", 1)
            self.assertFalse(any(isinstance(call, tuple) and call[0] == "set_brightness"
                                 for call in self.backend.calls))
        self.assertEqual(self.reopen().session(token)["next_sequence"], 7)

    def test_uncertain_brightness_failure_consumes_sequence_without_private_error_or_replay(self):
        self.backend.brightness_supported = True
        token = self.pair()

        def apply_then_fail(value):
            self.backend.brightness = value
            raise TimeoutError("SYNTHETIC_PRIVATE_BRIGHTNESS_ERROR")

        with patch.object(self.backend, "set_brightness", side_effect=apply_then_fail):
            with self.assertRaises(BackendError) as caught:
                self.store.execute(token, 1, "brightness.set", 70)
        self.assertNotIn("SYNTHETIC_PRIVATE", str(caught.exception))
        self.assertNotIn("SYNTHETIC_PRIVATE", self.store.path.read_text())
        self.assertEqual(self.backend.brightness, 70)
        self.backend.calls.clear()
        with self.assertRaises(ReplayError):
            self.reopen().execute(token, 1, "brightness.delta", 10)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.reopen().execute(token, 2, "brightness.get")["brightness"], 70)

    def test_brightness_rejects_unauthorized_and_revoked_session_without_host_calls(self):
        self.backend.brightness_supported = True
        token = self.pair()
        for invalid in (None, "", "x" * 43):
            with self.assertRaises(AuthenticationError):
                self.store.execute(invalid, 1, "brightness.set", 70)
        self.store.revoke(token)
        with self.assertRaises(AuthenticationError):
            self.reopen().execute(token, 1, "brightness.delta", 10)
        self.assertEqual(self.backend.calls, [])

    def test_revocation_is_visible_to_existing_store_instances(self):
        token = self.pair()
        other = self.reopen()
        self.store.revoke(token)
        with self.assertRaises(AuthenticationError):
            other.execute(token, 1, "volume.delta", 10)
        self.assertEqual(self.backend.calls, [])

    def test_revoke_all_also_invalidates_pending_pairing_code(self):
        first, second = self.pair("First"), self.pair("Second")
        code = self.store.create_pairing()["code"]
        self.store.revoke_all()
        for token in (first, second):
            with self.assertRaises(AuthenticationError):
                self.store.session(token)
        with self.assertRaises(PairingError):
            self.store.pair(code, "Third")

    def test_token_rotation_invalidates_old_token_without_extending_expiry(self):
        token = self.pair()
        expires = self.store.session(token)["expires_at"]
        self.store.execute(token, 1, "volume.delta", 1)
        self.now += 10
        replacement = self.reopen().rotate(token)
        self.assertNotEqual(replacement, token)
        with self.assertRaises(AuthenticationError):
            self.store.session(token)
        session = self.store.session(replacement)
        self.assertEqual(session["expires_at"], expires)
        self.assertEqual(session["next_sequence"], 1)

    def test_uncertain_backend_failure_consumes_sequence_and_is_not_replayed(self):
        token = self.pair()

        def apply_then_fail(value):
            self.backend.volume = value
            raise TimeoutError("PRIVATE DIAGNOSTIC")

        with patch.object(self.backend, "set_volume", side_effect=apply_then_fail):
            with self.assertRaises(BackendError) as caught:
                self.store.execute(token, 1, "volume.delta", 5)
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertEqual(self.backend.volume, 45)
        with self.assertRaises(ReplayError):
            self.reopen().execute(token, 1, "volume.delta", 5)
        self.assertEqual(self.reopen().execute(token, 2, "volume.get")["volume"], 45)

    def test_persistence_failure_prevents_host_action(self):
        token = self.pair()
        with patch("modulate.host_bridge.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(StateError):
                self.store.execute(token, 1, "volume.delta", 10)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.store.session(token)["next_sequence"], 1)
        self.assertEqual(list(self.directory.glob(".host-bridge-*")), [])

    def test_corrupt_state_fails_closed_without_resetting_authentication(self):
        token = self.pair()
        self.store.path.write_text('{"version": 1, "sessions":')
        with self.assertRaises(StateError):
            self.store.execute(token, 1, "volume.delta", 10)
        with self.assertRaises(StateError):
            self.store.create_pairing()
        self.assertEqual(self.backend.calls, [])

    def test_duplicate_concurrent_commands_apply_once_across_store_instances(self):
        token = self.pair()

        def execute(_):
            try:
                return self.reopen().execute(token, 1, "volume.delta", 5)
            except ReplayError:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(execute, range(4)))
        self.assertEqual(sum(response is not None for response in responses), 1)
        self.assertEqual(self.backend.volume, 45)

    def test_two_sessions_serialize_read_modify_write(self):
        tokens = [self.pair("First"), self.pair("Second")]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda token: self.reopen().execute(token, 1, "volume.delta", 5), tokens))
        self.assertEqual(self.backend.volume, 50)


class BackendTests(unittest.TestCase):
    def test_brightness_helper_has_fixed_arguments_no_secret_environment_and_timeout(self):
        backend = MacOSVolumeBackend()
        response = subprocess.CompletedProcess([], 0, stdout='{"brightness":64}')
        with patch.dict(os.environ, {"SYNTHETIC_TEST_SECRET": "must-not-reach-helper"}), \
             patch("modulate.host_bridge.subprocess.run", return_value=response) as run:
            self.assertEqual(backend.get_brightness(), 64)
            self.assertEqual(backend.set_brightness(72), 64)
        self.assertEqual(run.call_args_list[0].args[0],
                         [sys.executable, "-m", "modulate.system_settings", "get"])
        self.assertEqual(run.call_args_list[1].args[0],
                         [sys.executable, "-m", "modulate.system_settings", "set", "72"])
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 3)
            self.assertNotIn("shell", call.kwargs)
            self.assertNotIn("SYNTHETIC_TEST_SECRET", call.kwargs["env"])

    def test_invalid_native_brightness_never_starts_helper(self):
        backend = MacOSVolumeBackend()
        with patch("modulate.host_bridge.subprocess.run") as run:
            for value in (True, "42", -1, 101, None, 42.0, float("nan")):
                with self.subTest(value=value), self.assertRaises(BackendError):
                    backend.set_brightness(value)
            run.assert_not_called()

    def test_native_brightness_rejects_malformed_output_and_sanitizes_errors(self):
        backend = MacOSVolumeBackend()
        for stdout in ('{"brightness":true}', '{"brightness":-1}', '{"brightness":101}',
                       '{"brightness":42.0}', '{"brightness":"42"}', '{}', 'null',
                       'SYNTHETIC_PRIVATE_ERROR'):
            response = subprocess.CompletedProcess([], 0, stdout=stdout)
            with self.subTest(stdout=stdout), patch("modulate.host_bridge.subprocess.run", return_value=response):
                with self.assertRaises(BackendError) as caught:
                    backend.get_brightness()
                self.assertNotIn("SYNTHETIC_PRIVATE", str(caught.exception))
        with patch("modulate.host_bridge.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("synthetic-helper", 3, output="SYNTHETIC_PRIVATE")):
            with self.assertRaises(BackendError) as caught:
                backend.get_brightness()
            self.assertNotIn("SYNTHETIC_PRIVATE", str(caught.exception))

    def test_brightness_capability_probe_is_bounded_and_unavailable_is_truthful(self):
        for output in (60, BackendError("Synthetic unavailable display")):
            backend = MacOSVolumeBackend()
            probe = patch.object(backend, "get_brightness", side_effect=output) if isinstance(output, Exception) \
                else patch.object(backend, "get_brightness", return_value=output)
            with probe as get:
                self.assertEqual(backend.capabilities()["brightness"], not isinstance(output, Exception))
                self.assertEqual(backend.capabilities()["brightness"], not isinstance(output, Exception))
                self.assertEqual(get.call_count, 1)

    def test_mac_commands_are_fixed_scripts_with_separate_validated_arguments(self):
        backend = MacOSVolumeBackend()
        response = subprocess.CompletedProcess([], 0, stdout="40,false\n")
        with patch("modulate.host_bridge.subprocess.run", return_value=response) as run:
            self.assertEqual(backend.get(), {"volume": 40, "muted": False})
            backend.set_volume(42)
            backend.set_muted(True)
        self.assertEqual(run.call_args_list[1].args[0],
                         ["/usr/bin/osascript", "-e", backend._SET_VOLUME, "42"])
        self.assertEqual(run.call_args_list[2].args[0],
                         ["/usr/bin/osascript", "-e", backend._SET_MUTED, "true"])
        for call in run.call_args_list:
            self.assertNotIn("shell", call.kwargs)
            self.assertEqual(call.kwargs["timeout"], 3)

    def test_invalid_native_values_never_reach_subprocess(self):
        backend = MacOSVolumeBackend()
        with patch("modulate.host_bridge.subprocess.run") as run:
            for value in (True, "42", -1, 101, "do shell script"):
                with self.assertRaises(BackendError):
                    backend.set_volume(value)
            with self.assertRaises(BackendError):
                backend.set_muted("true")
            run.assert_not_called()

    def test_native_errors_and_malformed_output_do_not_escape_as_success(self):
        backend = MacOSVolumeBackend()
        for stdout in ("40", "101,false", "40,unknown", "PRIVATE ERROR"):
            response = subprocess.CompletedProcess([], 0, stdout=stdout)
            with patch("modulate.host_bridge.subprocess.run", return_value=response):
                with self.assertRaises(BackendError):
                    backend.get()
        with patch("modulate.host_bridge.subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "osascript", stderr="PRIVATE")):
            with self.assertRaises(BackendError) as caught:
                backend.get()
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_other_platforms_report_unsupported_without_claiming_volume_capability(self):
        for platform, label in (("win32", "windows"), ("linux", "linux")):
            with self.subTest(platform=platform), patch("modulate.host_bridge.sys.platform", platform):
                with tempfile.TemporaryDirectory() as directory:
                    store = BridgeStore(directory)
                    self.assertFalse(store.capabilities()["supported"])
                    self.assertEqual(store.capabilities()["platform"], label)
                    self.assertEqual(store.capabilities()["actions"], [])
                    with self.assertRaises(UnsupportedPlatformError):
                        store.create_pairing()
        with patch("modulate.host_bridge.sys.platform", "darwin"):
            self.assertIsInstance(default_backend(), MacOSVolumeBackend)


if __name__ == "__main__":
    unittest.main()
