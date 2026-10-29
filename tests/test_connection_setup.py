"""Connection setup uses synthetic Pi/OS state; no cloud, UI or native actions."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from modulate.agent import AgentError, digest
from modulate.connection_setup import CONNECT_URL
from modulate.product import Product
from modulate.remote_access import RemoteAccess
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend


class ConnectionSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.backend = FakeBackend()
        self.computer = FakeComputer()
        self.product = Product(self.directory, SyntheticProvider([]), backend=self.backend, computer=self.computer)
        self.addCleanup(self.product.cancel)
        self.remote = self.product.remote_access = RemoteAccess(self.product, self.directory)
        self.sequence = 0
        self.heartbeat()

    def heartbeat(self):
        self.sequence += 1
        return self.product.heartbeat({"session": "a" * 32, "sequence": self.sequence,
            "name": "Synthetic controller", "capabilities": {"controls": ["encoder", "button_a"],
            "devices": [], "warnings": []}, "input": {}, "revision": self.product.revision})

    def test_unpaired_status_does_not_authorize_or_observe_the_mac(self):
        status = self.product.connection_setup("status")
        self.assertFalse(status["paired_mac"])
        self.assertTrue(status["remote_enabled"])
        self.assertEqual(status["native_permissions"], self.computer.permissions)
        self.assertIsNone(self.product.volume_token)
        self.assertFalse(self.computer.enabled)
        self.assertEqual(self.computer.observations, 0)
        self.assertEqual(self.computer.actions, [])
        self.assertEqual(self.backend.actions, [])

    def test_pairing_setup_requires_existing_device_confirmation_and_preserves_app(self):
        active = {"revision": "f" * 64, "package": {"kind": "game", "title": "Saved app"}}
        self.product.active = copy.deepcopy(active)
        before_reads = self.backend.get_calls
        result = self.product.connection_setup("start_pairing")
        self.assertTrue(result["pairing_started"])
        self.assertFalse(result["displayed"])
        self.assertIsNone(self.product.volume_token)
        self.assertFalse(self.computer.enabled)
        self.assertEqual(self.backend.get_calls, before_reads)
        self.assertEqual(self.product.active, active)
        code = self.product.pairing["code"]
        self.assertNotIn(code, json.dumps(result))
        self.product.pair(code, "Synthetic physical confirmation")
        status = self.product.connection_setup("status")
        self.assertTrue(status["paired_mac"])
        self.assertGreater(status["pairing_expires_at"], time.time())
        token = self.product.volume_token
        self.assertFalse(self.product.connection_setup("start_pairing")["pairing_started"])
        self.assertEqual(self.product.volume_token, token)

    def test_setup_display_confirmation_requires_fresh_matching_telemetry(self):
        self.product.connection_setup("show")
        offer = self.product.setup_offer
        status = self.product.connection_setup("status")["display_status"]
        self.assertEqual(status, {"offer_id": offer["id"], "visible": False})
        for display in ("malformed", {"kind": "program", "offer_id": offer["id"]},
                        {"kind": "setup", "offer_id": "b" * 32},
                        {"kind": "setup"}):
            self.product.telemetry["display"] = display
            self.assertFalse(self.product.connection_setup("status")["display_status"]["visible"])
        self.product.telemetry["display"] = {"kind": "setup", "offer_id": offer["id"]}
        self.assertTrue(self.product.connection_setup("status")["display_status"]["visible"])
        self.product.last_seen = time.monotonic() - 5
        self.assertFalse(self.product.connection_setup("status")["display_status"]["visible"])
        self.product.last_seen = time.monotonic()
        with patch("modulate.connection_setup.time.time", return_value=offer["expires_at"] + 1):
            self.assertEqual(self.product.connection_setup("status")["display_status"],
                             {"offer_id": None, "visible": False})

    def test_browser_code_only_reaches_device_offer_and_is_single_use(self):
        before = digest(self.product.capabilities())
        result = self.product.connection_setup("create_browser_code")
        offer = self.heartbeat()["setup"]
        self.assertEqual(offer["kind"], "browser_code")
        self.assertEqual(offer["connect_url"], CONNECT_URL)
        self.assertEqual(offer["browser_count"], 0)
        code = offer["code"]
        for public in (result, self.product.state(), self.product.capabilities(), self.product.connection_setup("status")):
            self.assertNotIn(code, json.dumps(public))
        self.assertEqual(digest(self.product.capabilities()), before)
        self.assertIsNone(self.product.volume_token)
        claim = self.remote.claim(code)
        self.assertTrue(claim["connected"])
        self.assertIsNone(self.heartbeat()["setup"])
        self.assertEqual(self.heartbeat()["setup_status"]["browser_count"], 1)
        self.assertFalse(self.product.connection_setup("status")["paired_mac"])

    def test_expired_replaced_and_revoked_browser_codes_leave_no_stale_offer(self):
        self.product.connection_setup("create_browser_code")
        offer = self.product.setup_offer
        with patch("modulate.connection_setup.time.time", return_value=offer["expires_at"] + 1):
            self.assertIsNone(self.product.connection_guide.device_offer())
        self.product.connection_setup("create_browser_code")
        self.remote.create_pairing()
        self.assertIsNone(self.product.connection_guide.device_offer())
        self.product.connection_setup("create_browser_code")
        self.remote.revoke(all_sessions=True)
        self.assertIsNone(self.product.connection_guide.device_offer())

    def test_missing_gateway_and_offline_device_cannot_mint_a_browser_code(self):
        self.remote.gateway_enabled = False
        with self.assertRaisesRegex(AgentError, "not configured"):
            self.product.connection_setup("create_browser_code")
        self.assertIsNone(self.remote.pairing)
        result = self.product.connection_setup("show")
        self.assertFalse(result["remote_enabled"])
        self.assertIn("Continue on your Mac", self.product.setup_offer["lines"][0])
        self.product.last_seen = None
        self.assertFalse(self.product.connection_setup("status")["device_connected"])
        for action in ("show", "start_pairing", "create_browser_code"):
            with self.assertRaisesRegex(AgentError, "offline"):
                self.product.connection_setup(action)
        self.assertIsNone(self.product.pairing)
        self.assertIsNone(self.remote.pairing)

    def test_offers_are_ephemeral_and_do_not_change_permission_choices(self):
        self.remote.set_permissions({"computer": False, "voice": False})
        before = self.remote.local_status()["permissions"]
        self.product.connection_setup("show")
        self.assertEqual(self.remote.local_status()["permissions"], before)
        reopened = Product(self.directory, SyntheticProvider([]), backend=self.backend, computer=FakeComputer())
        self.addCleanup(reopened.cancel)
        self.assertIsNone(reopened.setup_offer)
        self.assertEqual(reopened.remote_access.local_status()["permissions"], before)

    def test_local_pairing_completes_without_remote_gateway_and_offline_is_not_ready(self):
        self.remote.gateway_enabled = False
        self.product.connection_setup("start_pairing")
        self.product.pair(self.product.pairing["code"], "Synthetic physical confirmation")
        status = self.product.connection_setup("status")
        self.assertTrue(status["local_ready"])
        self.assertFalse(status["remote_enabled"])
        self.assertEqual(status["companion_setup_url"], "http://127.0.0.1:8787/setup")
        self.assertFalse(status["browser_linked"])
        self.assertNotIn("local_studio_url", status)
        self.assertTrue(any("website connection still needs setup" in line for line in status["instructions"]))
        self.assertFalse(any("vercel.app" in line for line in status["instructions"]))
        self.product.connection_setup("show")
        self.assertNotIn("code", self.product.setup_offer)
        self.assertIsNone(self.remote.pairing)
        self.product.last_seen = time.monotonic() - 5
        status = self.product.connection_setup("status")
        self.assertTrue(status["pairing_saved"])
        self.assertFalse(status["paired_mac"])
        self.assertFalse(status["local_ready"])
        self.assertFalse(status["device_connected"])

    def test_only_orchestrator_can_prepare_setup_and_arguments_are_bounded(self):
        agent = self.product.agent
        for role in ("coder", "artist", "reviewer"):
            with self.subTest(role=role), self.assertRaises(AgentError):
                agent.dispatch("connection_setup", {"action": "create_browser_code"}, role)
        for arguments in ({"action": "shell"}, {"action": "show", "code": "12345678"}, {"action": []}):
            with self.subTest(arguments=arguments), self.assertRaises(AgentError):
                agent.dispatch("connection_setup", arguments, "orchestrator")
        self.assertIsNone(self.product.setup_offer)
        self.assertIsNone(self.remote.pairing)
        agent.private_request = True
        self.assertFalse(agent.dispatch("connection_setup", {"action": "status"}, "orchestrator")["paired_mac"])


if __name__ == "__main__":
    unittest.main()
