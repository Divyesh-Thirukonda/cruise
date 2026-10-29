"""Local comparison-code behavior with synthetic device and Mac state only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from modulate.product import Product
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend


class LocalPairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.product = Product(Path(self.temp.name), SyntheticProvider([]), backend=FakeBackend(), computer=FakeComputer())
        self.addCleanup(self.product.cancel)
        self.product.heartbeat({"session": "a" * 32, "sequence": 1,
                                "name": "Synthetic device", "capabilities": {"controls": [], "devices": [], "warnings": []},
                                "input": {}, "revision": None})

    def test_device_started_pairing_is_readable_without_replacing_it_or_leaking_to_general_state(self):
        self.product.connection_setup("start_pairing")
        original = dict(self.product.pairing)
        self.assertEqual(self.product.local_pairing(), original)
        self.assertEqual(self.product.local_pairing(), original)
        self.assertEqual(self.product.pairing, original)
        for public in (self.product.state(), self.product.capabilities(), self.product.connection_setup("status")):
            self.assertNotIn(original["code"], json.dumps(public))
        read = self.product.local_pairing()
        read["code"] = "changed"
        self.assertEqual(self.product.pairing, original)

    def test_expiry_pairing_and_revocation_remove_local_comparison(self):
        original = self.product.create_pairing()
        with patch("modulate.product.time.time", return_value=original["expires_at"]):
            self.assertIsNone(self.product.local_pairing())
        self.product.pair(original["code"], "Synthetic device confirmation")
        self.assertIsNone(self.product.local_pairing())
        self.product.revoke()
        self.assertIsNone(self.product.local_pairing())
        self.assertFalse(self.product.state()["paired"])

    def test_saved_pairing_and_current_device_presence_are_separate(self):
        code = self.product.create_pairing()["code"]
        self.product.pair(code, "Synthetic device confirmation")
        self.assertTrue(self.product.state()["device"]["connected"])
        self.assertTrue(self.product.state()["paired"])
        self.product.last_seen = time.monotonic() - 5
        status = self.product.state()
        self.assertTrue(status["paired"])
        self.assertFalse(status["device"]["connected"])
        self.assertIsNone(self.product._paired_session())
