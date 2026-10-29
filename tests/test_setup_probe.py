"""Synthetic setup-probe checks; no live network, device or provider access."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "plugins/modulate-setup/skills/modulate-setup/scripts/inspect_setup.py"
SPEC = importlib.util.spec_from_file_location("setup_probe", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class SetupProbeTests(unittest.TestCase):
    def read_status(self, studio, helper):
        return lambda port, path: studio if port == 8787 else helper

    def test_summary_never_exports_private_state_or_unrecognized_fields(self):
        studio = {"device": {"connected": True, "name": "private device"}, "paired": True,
                  "remote": {"enabled": False, "code": "12345678"}, "events": ["private email"],
                  "active": {"code": "private program"}, "pairing": {"code": "87654321"}}
        helper = {"status": "complete", "next_action": "open_studio", "message": "private IP and request",
                  "code": "01234567", "fingerprint": "private identity", "error_code": "PRIVATE_TOKEN"}
        result = probe.live_status(self.read_status(studio, helper))
        self.assertEqual(result["studio"], {"status": "available", "device_online": True,
                         "pairing_saved": True,
                         "native_pairing_active": True, "local_connection_ready": True,
                         "remote_gateway_configured": False, "computer_control_enabled": None,
                         "computer_paused": None,
                         "native_permissions": {"screen_recording": None, "accessibility": None}})
        self.assertEqual(result["enrollment_helper"], {"status": "complete", "next_action": "open_studio"})
        rendered = json.dumps(result)
        for secret in ("private", "12345678", "87654321", "01234567", "PRIVATE_TOKEN"):
            self.assertNotIn(secret, rendered)

    def test_completed_helper_or_saved_pairing_does_not_prove_online_device(self):
        state = {"device": {"connected": False}, "paired": True, "remote": {"enabled": True}}
        result = probe.live_status(self.read_status(state, {"status": "complete"}))
        self.assertFalse(result["studio"]["local_connection_ready"])
        self.assertTrue(result["studio"]["pairing_saved"])
        self.assertFalse(result["studio"]["native_pairing_active"])

    def test_completion_handoffs_support_current_and_legacy_helpers_without_private_urls(self):
        for action in ("open_setup", "open_studio", "PRIVATE_ACTION"):
            with self.subTest(action=action):
                helper = {"status": "complete", "next_action": action,
                          "companion_setup_url": "http://private-host/setup", "message": "private details"}
                result = probe.live_status(self.read_status({}, helper))["enrollment_helper"]
                expected = {"status": "complete"}
                if action != "PRIVATE_ACTION":
                    expected["next_action"] = action
                self.assertEqual(result, expected)

    def test_online_but_unpaired_device_is_not_ready(self):
        state = {"device": {"connected": True}, "paired": False, "remote": {"enabled": False}}
        result = probe.live_status(self.read_status(state, {"status": "awaiting_confirmation"}))
        self.assertFalse(result["studio"]["local_connection_ready"])
        self.assertFalse(result["studio"]["pairing_saved"])
        self.assertFalse(result["studio"]["native_pairing_active"])
        self.assertEqual(result["enrollment_helper"]["status"], "awaiting_confirmation")

    def test_online_pairing_does_not_claim_paused_or_permission_denied_computer_control(self):
        for computer in (
                {"enabled": False, "paused": True, "permissions": {"screen_recording": True, "accessibility": True}},
                {"enabled": False, "paused": False, "permissions": {"screen_recording": False, "accessibility": True}},
                {"enabled": True, "paused": True, "permissions": {"screen_recording": True, "accessibility": True}}):
            with self.subTest(computer=computer):
                state = {"device": {"connected": True}, "paired": True, "remote": {"enabled": False}, "computer": computer}
                result = probe.live_status(self.read_status(state, {"status": "complete"}))["studio"]
                self.assertTrue(result["native_pairing_active"])
                self.assertTrue(result["local_connection_ready"])
                self.assertFalse(result["computer_control_enabled"])
                self.assertEqual(result["computer_paused"], computer["paused"])
                self.assertEqual(result["native_permissions"], computer["permissions"])

    def test_control_status_outputs_only_boolean_or_unknown_permission_values(self):
        state = {"device": {"connected": True}, "paired": True, "remote": {"enabled": False},
                 "computer": {"enabled": True, "paused": False, "error": "PRIVATE",
                              "permissions": {"screen_recording": True, "accessibility": True, "private": "SECRET"}}}
        result = probe.live_status(self.read_status(state, {"status": "complete"}))["studio"]
        self.assertTrue(result["computer_control_enabled"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("SECRET", json.dumps(result))
        state["computer"] = {"enabled": "PRIVATE", "paused": 0,
                             "permissions": {"screen_recording": 1, "accessibility": "SECRET"}}
        result = probe.live_status(self.read_status(state, {"status": "complete"}))["studio"]
        self.assertIsNone(result["computer_control_enabled"])
        self.assertIsNone(result["computer_paused"])
        self.assertEqual(result["native_permissions"], {"screen_recording": None, "accessibility": None})

    def test_incomplete_or_wrongly_typed_state_remains_unknown(self):
        for state in ([], {}, {"device": {"connected": "true"}, "paired": True, "remote": {"enabled": False}},
                      {"device": {"connected": True}, "paired": 1, "remote": {"enabled": True}}):
            with self.subTest(state=state):
                result = probe.live_status(self.read_status(state, {"status": ["complete"]}))
                self.assertEqual(result["studio"], {"status": "unavailable_or_unrecognized"})
                self.assertEqual(result["enrollment_helper"], {"status": "unavailable_or_unrecognized"})

    def test_known_error_and_next_action_are_retained_without_message(self):
        for error_code, next_action in (("setup_expired", "new_setup_code"), ("save_failed", "check_device")):
            with self.subTest(error_code=error_code):
                result = probe.live_status(self.read_status({}, {"status": "error", "error_code": error_code,
                                                                "next_action": next_action, "message": "private"}))
                self.assertEqual(result["enrollment_helper"], {"status": "error", "error_code": error_code,
                                                              "next_action": next_action})

    def test_feature_warnings_do_not_become_false_connection_failures_or_leak_details(self):
        state = {"device": {"connected": True, "telemetry": {"voice": {"state": "error", "message": "private microphone"}},
                            "capabilities": {"warnings": ["private hardware"]}},
                 "paired": True, "remote": {"enabled": False}}
        summary = probe.live_status(self.read_status(state, {"status": "complete"}))["studio"]
        self.assertTrue(summary["local_connection_ready"])
        self.assertEqual(summary["voice_state"], "error")
        self.assertEqual(summary["hardware_warning_count"], 1)
        self.assertNotIn("private", json.dumps(summary))
        state["device"]["telemetry"]["voice"]["state"] = "private text"
        self.assertNotIn("voice_state", probe.live_status(self.read_status(state, {}))["studio"])

    def test_read_errors_do_not_echo_exception_content(self):
        def unavailable(*args):
            raise OSError("SECRET connection details")
        self.assertNotIn("SECRET", json.dumps(probe.live_status(unavailable)))

    def test_network_reader_only_accepts_fixed_local_status_destinations(self):
        with patch.object(probe.urllib.request, "build_opener") as build:
            for port, path in ((8787, "//example.com"), (8789, "/status"), (8791, "/enroll")):
                with self.assertRaises(ValueError):
                    probe.local_json(port, path)
            build.assert_not_called()

    def test_reader_disables_proxies_redirects_and_bounds_the_body(self):
        opener = Mock()
        with patch.object(probe.urllib.request, "build_opener", return_value=opener) as build:
            opener.open.return_value = io.BytesIO(b'{"status":"complete"}')
            self.assertEqual(probe.local_json(8791, "/status"), {"status": "complete"})
            handlers = build.call_args.args
            self.assertEqual(handlers[0].proxies, {})
            self.assertIsInstance(handlers[1], probe.NoRedirect)
            self.assertIsNone(handlers[1].redirect_request(None, None, 302, None, None, "https://example.com"))
            opener.open.assert_called_once_with("http://127.0.0.1:8791/status", timeout=2)
            opener.open.return_value = io.BytesIO(b"x" * (probe.MAX_RESPONSE + 1))
            with self.assertRaises(ValueError):
                probe.local_json(8791, "/status")

    def test_default_probe_does_not_read_live_application_state(self):
        with patch.object(probe, "live_status") as live, patch.object(probe, "reachable", return_value=False):
            result = probe.inspect(Path("/nonexistent/modulate"))
        live.assert_not_called()
        self.assertNotIn("live", result)
        self.assertNotIn("8788", result["loopback_ports_listening"])
        self.assertIn("8791", result["loopback_ports_listening"])


if __name__ == "__main__":
    unittest.main()
