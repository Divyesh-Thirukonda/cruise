"""Malformed model turns are rejected, billed when known, and retried boundedly."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from modulate.agent import Ledger, Orchestrator
from modulate.agent_provider import AgentProviderError
from tests.test_agent import FakeService, ScriptedProvider, reply


class ReservedProvider(ScriptedProvider):
    def request_budget(self, messages, tools):
        self.real.request_budget(messages, tools)
        return {"reserved_cost_microdollars": 1000}


def rejected(*, billed=7, repairable=True):
    error = AgentProviderError("Model requested an unavailable tool.")
    error.billed_cost_microdollars = billed
    error.repairable = repairable
    return error


class ProtocolRepairTests(unittest.TestCase):
    def run_agent(self, script):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        ledger = Ledger(Path(temporary.name) / "budget.json", 1)
        service = FakeService()
        provider = ReservedProvider(script)
        return Orchestrator(provider, service, temporary.name, ledger), provider, service, ledger

    def test_rejected_turn_is_billed_and_can_repair_without_executing_it(self):
        agent, provider, service, ledger = self.run_agent([rejected(), reply(content="Recovered")])
        self.assertEqual(agent.run("Use the available tools"), "Recovered")
        self.assertEqual(ledger.data["charged"], 7)
        self.assertEqual(len(provider.requests), 2)
        self.assertIn("No action", provider.requests[1][0][-1]["content"])
        self.assertEqual(service.activations, [])
        self.assertEqual(service.candidates, [])

    def test_protocol_repair_is_bounded_to_two_and_all_received_turns_are_billed(self):
        agent, provider, service, ledger = self.run_agent([rejected(), rejected(), rejected(), reply(content="Never")])
        with self.assertRaises(AgentProviderError):
            agent.run("Use the available tools")
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(ledger.data["charged"], 21)
        self.assertEqual(service.activations, [])

    def test_unknown_transport_or_usage_keeps_its_hold_and_is_not_retried(self):
        agent, provider, _, ledger = self.run_agent([rejected(billed=None, repairable=False), reply(content="Never")])
        with self.assertRaises(AgentProviderError):
            agent.run("Use the available tools")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(ledger.data["charged"], 1000)
        self.assertEqual(ledger.data["calls"][0]["status"], "reserved")

    def test_cancellation_during_rejected_turn_prevents_retry(self):
        agent, provider, _, ledger = self.run_agent([])
        def cancel_then_reject(messages, tools):
            agent.cancelled.set()
            raise rejected()
        provider.script = [cancel_then_reject, reply(content="Never")]
        with self.assertRaises(AgentProviderError):
            agent.run("Use the available tools")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(ledger.data["charged"], 7)
