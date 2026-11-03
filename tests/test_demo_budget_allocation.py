import json
from pathlib import Path
import tempfile
import unittest

from modulate.agent import AgentError, Ledger
from scripts.allocate_demo_budget import allocate


class DemoAllocationTests(unittest.TestCase):
    def test_reservation_is_idempotent_and_shared_with_native_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.json"
            ledger = Ledger(path, limit_dollars=50)
            ledger.reserve(10_000_000)
            first = allocate(path)
            self.assertEqual(first, allocate(path))
            self.assertEqual(ledger.status()["charged_or_reserved_dollars"], 15)
            self.assertEqual(ledger.status()["calls"], 2)
            with self.assertRaises(AgentError):
                ledger.reserve(36_000_000)

    def test_missing_halted_and_insufficient_ledgers_are_not_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.json"
            with self.assertRaises(AgentError):
                allocate(path)
            ledger = Ledger(path, limit_dollars=50)
            ledger.reserve(46_000_000)
            before = path.read_bytes()
            with self.assertRaises(AgentError):
                allocate(path)
            self.assertEqual(path.read_bytes(), before)
            ledger.data["halted"] = True
            ledger.save()
            with self.assertRaisesRegex(AgentError, "halted"):
                allocate(path)
