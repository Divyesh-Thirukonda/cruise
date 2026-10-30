"""Synthetic faults and work-budget exhaustion; no provider or device calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modulate.agent import AgentError, AttemptIncomplete, Ledger, Orchestrator, digest
from modulate.agent_provider import AgentProviderError
from modulate.product import Product
from tests.test_agent import FakeService, reply, result_for, control_package
from tests.test_agent_protocol_repair import ReservedProvider


class AgentReliabilityTests(unittest.TestCase):
    def make(self, script, max_calls=32, budget=1):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        service = FakeService()
        provider = ReservedProvider(script)
        ledger = Ledger(Path(temp.name) / "budget.json", budget)
        agent = Orchestrator(provider, service, temp.name, ledger, max_calls=max_calls)
        # Advance backoff without wall-clock waits; cancellation tests override it.
        wait = patch.object(agent.cancelled, "wait", return_value=False)
        wait.start()
        self.addCleanup(wait.stop)
        return agent, provider, service, ledger

    def test_specialist_hands_off_written_candidate_after_its_last_turn(self):
        package = control_package()
        key = digest(package)
        def finish(messages, tools):
            result = result_for(messages, "delegate_task")
            self.assertIn("partial handoff", result["report"])
            self.assertEqual(result["candidates"][0]["candidate_id"], key)
            self.assertFalse(result["candidates"][0]["verified"])
            return reply(("test_package", {"candidate_id": key}))
        agent, provider, service, _ = self.make([
            reply(("delegate_task", {"role": "coder", "task": "Make a control"})),
            *[reply(("inspect_capabilities", {})) for _ in range(4)],
            reply(("write_package", {"package": package})), finish,
            reply(("activate_package", {"candidate_id": key})), reply(content="Activated")])
        self.assertEqual(agent.run("Make a control"), "Activated")
        self.assertEqual(service.activations, [package])
        self.assertEqual(len(provider.requests), 9)

    def test_delegation_reserves_parent_calls_even_near_global_limit(self):
        agent, provider, _, _ = self.make([
            *[reply(("inspect_capabilities", {})) for _ in range(3)],
            reply(("delegate_task", {"role": "reviewer", "task": "Review"})),
            reply(("read_runtime_api", {})), reply(("read_runtime_api", {})),
            reply(content="Parent finished")], max_calls=8)
        self.assertEqual(agent.run("Review"), "Parent finished")
        self.assertIn("partial handoff", result_for(provider.requests[-1][0], "delegate_task")["report"])
        self.assertIn("2 model calls left", provider.requests[-1][0][0]["content"])
        self.assertEqual(agent.calls, 7)

    def test_exhaustion_reports_acknowledged_progress_without_claiming_full_success(self):
        agent, _, _, _ = self.make([reply(("inspect_capabilities", {}))], max_calls=1)
        with self.assertRaises(AttemptIncomplete) as caught:
            agent.run("Unfinished task")
        text, question = Product._failure_guidance(caught.exception)
        self.assertIn("couldn't confirm", text)
        self.assertIsNone(question)  # Do not suggest blindly replaying the whole task.
        text, _ = Product._failure_guidance(AttemptIncomplete([
            {"tool": "activate_package", "observed": {"activated": True}}]))
        self.assertIn("device confirmed the new app", text)
        self.assertIn("couldn't finish every part", text)

    def test_transient_inference_retry_keeps_cost_hold_and_does_not_repeat_tool(self):
        agent, provider, service, ledger = self.make([
            reply(("system_control", {"action": "volume.get"})),
            AgentProviderError("Provider HTTP 503", transient=True), reply(content="Read completed")])
        self.assertEqual(agent.run("Read volume"), "Read completed")
        self.assertEqual(service.system_actions, [("volume.get", None)])
        # Budget notices change, but the actual conversation/tool results do not.
        self.assertEqual(provider.requests[1][0][1:], provider.requests[2][0][1:])
        self.assertEqual(ledger.data["charged"], 1000)
        self.assertEqual(ledger.data["calls"][1]["status"], "reserved")
        self.assertEqual(agent.transport_retries, 1)

    def test_retries_are_bounded_and_auth_errors_are_not_retried(self):
        for transient, count in ((True, 3), (False, 1)):
            with self.subTest(transient=transient):
                agent, provider, _, ledger = self.make([
                    AgentProviderError("Provider failed", transient=transient) for _ in range(4)])
                with self.assertRaises(AgentProviderError):
                    agent.run("Try")
                self.assertEqual(len(provider.requests), count)
                self.assertEqual(ledger.data["charged"], count * 1000)

    def test_cancellation_during_backoff_prevents_second_inference(self):
        agent, provider, _, _ = self.make([AgentProviderError("Timeout", transient=True)])
        agent.cancelled.wait.side_effect = lambda _: (agent.cancelled.set() or True)
        with self.assertRaisesRegex(AgentError, "Cancelled"):
            agent.run("Try")
        self.assertEqual(len(provider.requests), 1)

    def test_retry_cannot_exceed_remaining_spending_ceiling(self):
        agent, provider, _, ledger = self.make([
            AgentProviderError("Timeout", transient=True), reply(content="Must not run")], budget=.001)
        with self.assertRaisesRegex(AgentError, "budget"):
            agent.run("Try")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(ledger.data["charged"], 1000)


if __name__ == "__main__":
    unittest.main()
