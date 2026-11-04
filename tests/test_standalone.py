"""Synthetic standalone boundaries; physical and live-provider trials are separate."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from modulate.agent import AgentError, Ledger
from modulate.cloud_provider import GATEWAY_URL
from modulate.device_transport import save_private
from modulate.host_bridge import UnsupportedVolumeBackend
from modulate.product import Product
from modulate.remote_access import RemoteAccess
from modulate.setup_screen import SetupScreen
from modulate.standalone import validate_provisioning
from modulate.studio import customer_setup_status
from modulate.tts import _CharacterLedger, TTSError
from tests.test_assistant_io import FakeComputer, SyntheticProvider


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"MODULATE_CLOUD_URL": GATEWAY_URL,
                                                   "MODULATE_CLOUD_KEY": "a" * 40})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        ledger = Ledger(self.directory / "budget.json", 50)
        ledger.reserve(12000)  # Unknown usage must remain held across the move.
        _CharacterLedger(self.directory, 5000).reserve(100)

    def test_validation_keeps_both_ledgers_byte_identical_including_unknown_holds(self):
        paths = [self.directory / name for name in ("budget.json", "tts-character-ledger.json")]
        before = [p.read_bytes() for p in paths]
        validate_provisioning(self.directory)
        self.assertEqual(before, [p.read_bytes() for p in paths])
        self.assertEqual(Ledger(paths[0], 50).status()["charged_or_reserved_dollars"], .012)

    def test_missing_accounting_does_not_create_fresh_budget(self):
        path = self.directory / "budget.json"
        path.unlink()
        with self.assertRaises(ValueError):
            validate_provisioning(self.directory)
        self.assertFalse(path.exists())

    def test_moved_corrupt_or_public_ledger_blocks_startup(self):
        path = self.directory / "tts-character-ledger.json"
        for data in ({"migrated_to_pi": True}, {"version": 1}, {"version": -1}):
            save_private(path, data)
            with self.assertRaises((ValueError, TTSError)):
                validate_provisioning(self.directory)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            validate_provisioning(self.directory)

    def test_no_fallback_to_local_provider_key(self):
        with patch.dict(os.environ, {"MODULATE_CLOUD_URL": "", "MODULATE_CLOUD_KEY": "", "MODEL_API_KEY": "unused"}):
            with self.assertRaises(ValueError):
                validate_provisioning(self.directory)

    def test_explicit_speech_ceiling_change_preserves_cumulative_and_unknown_usage(self):
        ledger = _CharacterLedger(self.directory, 5000)
        ledger.reserve(4884)
        with self.assertRaises(TTSError):
            ledger.reserve(17)
        increased = _CharacterLedger(self.directory, 10000)
        increased.reserve(17)
        state = increased._change(0, check_only=True)
        self.assertEqual(state["reserved_characters"], 5001)
        self.assertEqual(state["uncertain_requests"], 3)


class StandaloneProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.product = Product(self.temp.name, SyntheticProvider([]), standalone=True,
                               backend=UnsupportedVolumeBackend("linux"), computer=FakeComputer())
        self.addCleanup(self.product.cancel)
        self.product.remote_access = RemoteAccess(self.product, Path(self.temp.name))
        self.packet = {"session": "a" * 32, "sequence": 1, "capabilities": {"controls": ["button_a"]},
                       "input": {}, "revision": None}
        self.host = self.product.heartbeat(self.packet)

    def test_no_mac_required_for_ready_browser_claim_and_library(self):
        status = self.product.connection_setup("status")
        self.assertTrue(status["local_ready"])
        self.assertFalse(status["paired_mac"])
        self.product.connection_setup("create_browser_code")
        code = self.product.connection_guide.device_offer()["code"]
        self.assertEqual(customer_setup_status(self.product)["browser_pairing"]["code"], code)
        self.product.remote_access.claim(code)
        self.assertTrue(self.product.capabilities()["app_library"]["supported"])
        self.assertIsNone(self.product.volume_token)

    def test_unpaired_local_boot_does_not_cover_app_with_mac_setup(self):
        screen = SetupScreen(time.monotonic() - 20)
        self.assertIsNone(screen.update(enrolled=True, fresh=True, host=self.host,
                                        now=time.monotonic(), wall=time.time()))
        screen.force = True
        card = screen.update(enrolled=True, fresh=True, host=self.host, now=time.monotonic(), wall=time.time())
        self.assertEqual(card["action"], "create_browser_code")

    def test_mac_tools_reject_without_claiming_local_pi_as_a_mac(self):
        with self.assertRaises(AgentError):
            self.product.create_pairing()
        with self.assertRaises(AgentError):
            self.product.system_control("volume.set", 60)
        self.assertIsNone(self.product.capabilities()["paired_host"])
        self.assertIsNone(self.product.pairing)
