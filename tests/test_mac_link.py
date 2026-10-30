"""Synthetic transport checks, not physical Mac/device evidence."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from modulate.host_bridge import BridgeError
from modulate.mac_link import MacLink, RemoteMacBackend


class MacLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.link = MacLink(self.temp.name)
        self.token = self.link.join("Synthetic Mac", {"platform": "macos", "brightness": True})

    def activate(self):
        self.link.authorize({"session_id": "synthetic-session", "expires_at": time.time() + 500})

    def test_pending_mac_cannot_run_commands_and_another_candidate_cannot_replace_it(self):
        self.assertFalse(self.link.poll(self.token, {})["authorized"])
        with self.assertRaises(BridgeError): self.link.call("volume.get", timeout=.01)
        with self.assertRaises(BridgeError): self.link.join("Different Mac", {"platform": "macos", "brightness": True})

    def test_wrong_token_expiry_and_revocation_are_enforced(self):
        with self.assertRaises(BridgeError): self.link.poll("x" * 43, {})
        self.activate()
        self.assertTrue(self.link.poll(self.token, {})["authorized"])
        with patch("modulate.mac_link.time.time", return_value=time.time() + 1000):
            with self.assertRaises(BridgeError): self.link.poll(self.token, {})
        self.link.revoke()
        with self.assertRaises(BridgeError): self.link.poll(self.token, {})

    def test_single_delivery_matching_ack_and_unknown_outcome(self):
        self.activate()
        outcome = []
        def invoke():
            try: outcome.append(self.link.call("brightness.get", timeout=.5))
            except BridgeError: outcome.append("failed")
        worker = threading.Thread(target=invoke)
        worker.start()
        for _ in range(100):
            packet = self.link.poll(self.token, {})
            if packet["command"]: break
            time.sleep(.001)
        command = packet["command"]
        self.assertIsNotNone(command)
        self.assertIsNone(self.link.poll(self.token, {})["command"])
        self.link.poll(self.token, {"result": {"id": "stale", "value": {"brightness": 99}}})
        self.assertTrue(worker.is_alive())
        self.link.poll(self.token, {"result": {"id": command["id"], "value": {"brightness": 46}}})
        worker.join(1)
        self.assertEqual(outcome, [{"brightness": 46}])
        with self.assertRaises(BridgeError): self.link.call("volume.set", {"value": 50}, timeout=.02)
        restored = MacLink(self.temp.name)
        self.assertEqual(restored.saved["sequence"], command["sequence"] + 1)
        self.assertFalse(restored.online())
        self.assertIsNone(self.link.poll(self.token, {})["command"])

    def test_offline_backend_cannot_claim_native_capabilities(self):
        self.activate()
        self.assertTrue(RemoteMacBackend(self.link).capabilities()["brightness"])
        self.link.last_seen = time.monotonic() - 4
        self.assertFalse(RemoteMacBackend(self.link).capabilities()["supported"])

    def test_cancellation_unblocks_waiter_without_replaying(self):
        self.activate()
        errors = []
        def invoke():
            try: self.link.call("computer.act", timeout=1)
            except BridgeError as error: errors.append(str(error))
        worker = threading.Thread(target=invoke)
        worker.start()
        for _ in range(100):
            if self.link.command: break
            time.sleep(.001)
        self.link.cancel()
        worker.join(1)
        self.assertTrue(errors)
        self.assertIsNone(self.link.poll(self.token, {})["command"])
