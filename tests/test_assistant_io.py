"""Assistant I/O integration with synthetic provider, computer and device data.

No OS access, screenshots of a real desktop, speaker playback or network calls.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from modulate.agent import AgentError
from modulate.agent_provider import AgentProviderError
from modulate.computer import ComputerError
from modulate.product import Product
from tests.test_agent import ScriptedProvider, reply
from tests.test_product import FakeBackend


class SyntheticProvider(ScriptedProvider):
    def request_budget(self, messages, tools):
        # These are I/O lifecycle tests, not image decoding or provider tests.
        # The synthetic screenshot marker deliberately contains no real pixels.
        return {"reserved_cost_microdollars": 0}


class FakeComputer:
    def __init__(self):
        self.enabled = False
        self.actions = []
        self.observations = 0
        self.cancellations = 0
        self.focuses = 0
        self.task_starts = 0
        self.on_focus = None

    def status(self):
        return {"supported": True, "enabled": self.enabled, "expires_at": None,
                "scope": "Synthetic Chrome window", "active": False, "error": None,
                "permissions": {"screen_recording": True, "accessibility": True}}

    def enable(self, minutes):
        self.enabled = True
        return self.status()

    def revoke(self):
        self.enabled = False
        self.cancel()

    def cancel(self):
        self.cancellations += 1

    def begin_task(self):
        self.task_starts += 1

    def focus(self):
        self.focuses += 1
        if self.on_focus:
            self.on_focus()

    def observe(self):
        if not self.enabled:
            raise ComputerError("Synthetic grant is disabled")
        self.observations += 1
        return {"observation_id": f"synthetic-{self.observations}", "width": 1, "height": 1,
                "image_url": "data:image/jpeg;base64,U1lOVEhFVElDX1BSSVZBVEVfSU1BR0U="}

    def act(self, observation_id, action):
        if not self.enabled:
            raise ComputerError("Synthetic grant is disabled")
        self.actions.append((observation_id, copy.deepcopy(action)))
        return {"performed": True}


class AssistantIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.provider = SyntheticProvider([])
        self.computer = FakeComputer()
        self.product = Product(self.directory, self.provider, backend=FakeBackend(), computer=self.computer)
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown, wait=True)
        self.addCleanup(self.product.cancel)
        self.sequence = 0

    def packet(self, **changes):
        self.sequence += 1
        packet = {"session": "a" * 32, "sequence": self.sequence, "name": "Synthetic controller",
                  "capabilities": {"controls": ["encoder", "button_a"], "devices": [], "warnings": []},
                  "input": {}, "revision": self.product.revision}
        packet.update(changes)
        return packet

    def heartbeat(self, **changes):
        return self.product.heartbeat(self.packet(**changes))

    def connect_computer(self):
        self.heartbeat()
        self.product.computer_session("enable")

    def wait_finished(self):
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: not self.product.running, timeout=3))

    def request(self, text="Read the synthetic screen"):
        accepted = self.product.request(text)
        self.wait_finished()
        return accepted

    def assert_not_persisted(self, *private_values):
        for path in self.directory.rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                for value in private_values:
                    self.assertNotIn(value.encode(), content, str(path))
        events = json.dumps(list(self.product.events))
        for value in private_values:
            self.assertNotIn(value, events)

    def test_disabled_computer_cannot_observe_or_act(self):
        self.heartbeat()
        for operation in (self.product.computer_observe,
                          lambda: self.product.computer_act("old", {"type": "click", "x": 0, "y": 0}, False, "Read a message")):
            with self.assertRaisesRegex(AgentError, "Enable computer control"):
                operation()
        self.assertEqual(self.computer.observations, 0)
        self.assertEqual(self.computer.actions, [])

    def test_revocation_and_disconnect_block_observation_and_actions(self):
        for reason in ("revoked", "disconnected"):
            with self.subTest(reason=reason):
                self.connect_computer()
                self.product.agent.cancelled.clear()
                observation = self.product.computer_observe()
                previous = self.computer.observations
                if reason == "revoked":
                    self.product.computer_session("revoke")
                else:
                    self.product.last_seen = None
                for operation in (self.product.computer_observe,
                                  lambda: self.product.computer_act(observation["observation_id"], {"type": "click", "x": 0, "y": 0}, False, "Open a message")):
                    with self.assertRaises(AgentError):
                        operation()
                self.assertEqual(self.computer.observations, previous)
                self.assertEqual(self.computer.actions, [])
        self.assertGreater(self.computer.cancellations, 0)

    def test_approval_requires_exact_pending_id_and_boolean(self):
        self.connect_computer()
        future = self.pool.submit(self.product.computer_act, "synthetic-1", {"type": "click", "x": 0, "y": 0}, True, "Submit this form")
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: self.product.computer_approval is not None, timeout=1))
            identifier = self.product.computer_approval["id"]
        for value, approved in (("stale", True), (identifier, 1), (identifier, "false")):
            with self.assertRaises(AgentError):
                self.product.approve_computer_action(value, approved)
        self.assertFalse(future.done())
        self.assertEqual(self.computer.actions, [])
        self.assertTrue(self.product.approve_computer_action(identifier, False)["accepted"])
        with self.assertRaisesRegex(AgentError, "declined"):
            future.result(timeout=1)
        self.assertIsNone(self.product.computer_status()["pending_approval"])
        with self.assertRaises(AgentError):
            self.product.approve_computer_action(identifier, True)
        self.assertEqual(self.computer.actions, [])

    def test_revoke_while_waiting_for_approval_never_performs_action(self):
        self.connect_computer()
        future = self.pool.submit(self.product.computer_act, "synthetic-1", {"type": "click", "x": 0, "y": 0}, True, "Confirm a change")
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: self.product.computer_approval is not None, timeout=1))
        self.product.computer_session("revoke")
        with self.assertRaises(AgentError):
            future.result(timeout=1)
        self.assertEqual(self.computer.actions, [])
        self.assertIsNone(self.product.computer_status()["pending_approval"])

    def test_approval_records_consent_without_clicking_until_fresh_observation(self):
        self.connect_computer()
        initial = self.product.computer_observe()
        action = {"type": "click", "x": 0, "y": 0}
        future = self.pool.submit(self.product.computer_act, initial["observation_id"], action, True, "Submit the synthetic form")
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: self.product.computer_approval is not None, timeout=1))
            identifier = self.product.computer_approval["id"]
        self.product.approve_computer_action(identifier, True)
        receipt = future.result(timeout=1)
        self.assertTrue(receipt["approved"])
        self.assertFalse(receipt["performed"])
        self.assertEqual(self.computer.actions, [])
        with self.assertRaisesRegex(AgentError, "Observe the page again"):
            self.product.computer_act(initial["observation_id"], action, True, "Submit the synthetic form")
        self.assertEqual(self.computer.actions, [])
        self.assertIsNotNone(self.product.computer_approved_action, "Rejected old observation must not consume consent")
        fresh = self.product.computer_observe()
        self.assertNotEqual(fresh["observation_id"], initial["observation_id"])
        result = self.product.computer_act(fresh["observation_id"], action, True, "Submit the synthetic form")
        self.assertTrue(result["action_result"]["performed"])
        self.assertEqual(self.computer.actions, [(fresh["observation_id"], action)])
        self.assertIsNone(self.product.computer_approved_action, "Successful action consumes consent")
        self.assertNotEqual(result["observation_id"], fresh["observation_id"], "Action is followed by another observation")
        # An old UI approval cannot grant another action after being consumed.
        with self.assertRaises(AgentError):
            self.product.approve_computer_action(identifier, True)

    def test_screen_answer_and_speech_stay_out_of_trace_and_saved_job(self):
        self.connect_computer()
        private = "SYNTHETIC_PRIVATE_ANSWER_83ba: the appointment is Friday."
        self.provider.script = [reply(("computer_observe", {})), reply(content=private)]
        accepted = self.request("SYNTHETIC_PRIVATE_REQUEST_a82b")
        self.assertEqual(self.product.state()["response"]["text"], private)
        speech = self.heartbeat()["speech"]
        self.assertEqual(speech["text"], private)
        self.assertEqual(speech["job_id"], accepted["job_id"])
        self.assert_not_persisted(private, "SYNTHETIC_PRIVATE_REQUEST_a82b", "U1lOVEhFVElDX1BSSVZBVEVfSU1BR0U=")
        saved = json.loads(self.product.job_path.read_text())
        self.assertEqual(saved["summary"], "Task complete. Response available in Studio.")
        reopened = Product(self.directory, self.provider, backend=FakeBackend(), computer=FakeComputer())
        self.assertIsNone(reopened.state()["response"])
        self.assertIsNone(reopened.speech_message)

    def test_new_user_job_focuses_once_before_first_observation_only(self):
        self.connect_computer()
        self.provider.script = [reply(("computer_observe", {})), reply(("computer_observe", {})),
                                reply(content="First synthetic result"),
                                reply(("computer_observe", {})), reply(content="Next synthetic result")]
        self.request()
        self.assertEqual(self.computer.focuses, 1)
        self.assertEqual(self.computer.observations, 2)
        self.request("A fresh computer task")
        self.assertEqual(self.computer.focuses, 2)
        self.assertEqual(self.computer.observations, 3)
        self.assertEqual(self.computer.task_starts, 2)

    def test_failed_focus_consumes_allowance_and_cancel_prevents_capture(self):
        self.connect_computer()
        self.product.computer_focus_pending = True

        def failed_focus():
            raise ComputerError("Synthetic window changed")

        self.computer.on_focus = failed_focus
        with self.assertRaisesRegex(AgentError, "window changed"):
            self.product.computer_observe()
        self.assertEqual(self.computer.observations, 0)
        self.computer.on_focus = None
        self.product.computer_observe()
        self.assertEqual(self.computer.focuses, 1, "A tool retry must not take focus again")
        self.product.computer_focus_pending = True
        self.computer.on_focus = self.product.agent.cancelled.set
        with self.assertRaisesRegex(AgentError, "cancelled"):
            self.product.computer_observe()
        self.assertEqual(self.computer.observations, 1, "Cancellation after focus blocks capture")

    def test_disabled_or_cancelled_job_cannot_consume_focus(self):
        self.connect_computer()
        self.product.computer_focus_pending = True
        self.product.agent.cancelled.set()
        with self.assertRaises(AgentError):
            self.product.computer_observe()
        self.product.agent.cancelled.clear()
        self.product.computer_session("revoke")
        with self.assertRaises(AgentError):
            self.product.computer_observe()
        self.assertEqual(self.computer.focuses, 0)

    def test_private_failure_explains_and_speaks_without_persisting_error(self):
        self.connect_computer()
        failure = "Synthetic provider could not read this screen. Please try again."
        private_request = "SYNTHETIC_PRIVATE_FAILED_REQUEST_6ca9"
        self.provider.script = [reply(("computer_observe", {})), AgentProviderError(failure)]
        accepted = self.request(private_request)
        state = self.product.state()
        self.assertEqual(state["agent"]["status"], "failed")
        expected = "I couldn't finish that computer request. " + failure
        self.assertEqual(state["response"]["text"], expected)
        speech = self.heartbeat()["speech"]
        self.assertEqual(speech["text"], expected)
        self.assertEqual(speech["job_id"], accepted["job_id"])
        self.assert_not_persisted(failure, private_request, "U1lOVEhFVElDX1BSSVZBVEVfSU1BR0U=")
        saved = json.loads(self.product.job_path.read_text())
        self.assertEqual(saved["summary"], "Computer request stopped.")
        failed = next(event for event in self.product.events if event["type"] == "request_failed")
        self.assertEqual(failed["exception_type"], "AgentProviderError")
        self.assertNotIn("detail", failed)
        reopened = Product(self.directory, self.provider, backend=FakeBackend(), computer=FakeComputer())
        self.assertIsNone(reopened.state()["response"])
        self.assertIsNone(reopened.speech_message)

    def test_unexpected_private_exception_does_not_speak_raw_payload(self):
        self.connect_computer()
        private = "SYNTHETIC_PRIVATE_EXCEPTION_PAYLOAD_93b2"
        self.provider.script = [reply(("computer_observe", {})), RuntimeError(private)]
        self.request()
        self.assertIn("unexpected computer error", self.product.state()["response"]["text"])
        self.assertNotIn(private, self.product.state()["response"]["text"])
        self.assertNotIn(private, self.heartbeat()["speech"]["text"])
        self.assert_not_persisted(private)

    def test_cancelled_private_failure_remains_quiet(self):
        self.connect_computer()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        failure = "SYNTHETIC_PRIVATE_LATE_FAILURE_226c"

        def delayed_failure(messages, tools):
            entered.set()
            self.assertTrue(release.wait(2))
            raise AgentProviderError(failure)

        self.provider.script = [reply(("computer_observe", {})), delayed_failure]
        accepted = self.product.request("Read the synthetic screen")
        self.assertTrue(entered.wait(1))
        self.product.cancel(accepted["job_id"])
        release.set()
        self.wait_finished()
        self.assertEqual(self.product.state()["agent"]["status"], "cancelled")
        self.assertIsNone(self.product.state()["response"])
        self.assertIsNone(self.heartbeat()["speech"])
        self.assert_not_persisted(failure)

    def test_only_exact_current_speech_acknowledgement_clears_message(self):
        self.heartbeat()
        self.product._publish_response("First synthetic reply", "first-job")
        first = self.heartbeat()["speech"]["id"]
        self.product._publish_response("Second synthetic reply", "second-job")
        current = self.heartbeat()["speech"]
        for stale in (first, "unknown", None, {"id": current["id"]}):
            with self.subTest(ack=stale):
                result = self.heartbeat(speech_ack=stale)
                self.assertEqual(result["speech"]["id"], current["id"])
        self.assertIsNone(self.heartbeat(speech_ack=current["id"])["speech"])
        self.assertIsNone(self.heartbeat()["speech"])

    def test_private_clarification_answer_without_new_screen_read_is_not_persisted(self):
        self.connect_computer()
        private = "SYNTHETIC_PRIVATE_MAIL_7d41"
        question = f"Should I summarize {private}?"
        self.provider.script = [reply(("computer_observe", {})), reply(("ask_user", {"question": question})),
                                reply(content=f"The answer about {private} is ready.")]
        self.request("Help me read this screen")
        self.assertEqual(self.product.state()["clarification"]["question"], question)
        self.request("Yes")
        self.assertIn(private, self.product.state()["response"]["text"])
        self.assertEqual(self.computer.observations, 1, "Reply needs no additional screen read")
        self.assert_not_persisted(private)

    def test_stale_device_packet_cannot_acknowledge_current_speech(self):
        packet = self.packet()
        self.product.heartbeat(packet)
        self.product._publish_response("Synthetic reply", "job")
        identifier = self.product.speech_message["id"]
        with self.assertRaisesRegex(AgentError, "Stale"):
            self.product.heartbeat({**packet, "speech_ack": identifier})
        self.assertEqual(self.product.speech_message["id"], identifier)

    def test_response_and_speech_expire_without_device_acknowledgement(self):
        self.heartbeat()
        with patch("modulate.assistant_io.time.time", return_value=1000):
            self.product._publish_response("Expiring synthetic reply", "job")
        with patch("modulate.assistant_io.time.time", return_value=1121):
            self.assertIsNone(self.product.state()["response"])
            self.assertIsNone(self.heartbeat()["speech"])
        self.assertIsNone(self.product.response)
        self.assertIsNone(self.product.speech_message)

    def test_stale_dismiss_cannot_remove_new_response_or_speech(self):
        self.product._publish_response("Old reply", "old")
        old_id = self.product.response["id"]
        self.product._publish_response("New reply", "new")
        new_id = self.product.response["id"]
        with self.assertRaises(AgentError):
            self.product.dismiss_response(old_id)
        self.assertEqual(self.product.response["id"], new_id)
        self.assertEqual(self.product.speech_message["text"], "New reply")
        stop = self.product.speech_stop_id
        self.product.dismiss_response(new_id)
        self.assertIsNone(self.product.response)
        self.assertIsNone(self.product.speech_message)
        self.assertGreater(self.product.speech_stop_id, stop)

    def test_cancel_clears_reply_and_speech_and_rejects_late_private_output(self):
        self.connect_computer()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def delayed_reply(messages, tools):
            entered.set()
            self.assertTrue(release.wait(2))
            return reply(content="SYNTHETIC_LATE_PRIVATE_RESULT")

        self.provider.script = [reply(("computer_observe", {})), delayed_reply]
        accepted = self.product.request("Read the screen")
        self.assertTrue(entered.wait(1))
        self.product._publish_response("Earlier private result", accepted["job_id"])
        stop = self.product.speech_stop_id
        self.product.cancel(accepted["job_id"])
        self.assertIsNone(self.product.response)
        self.assertIsNone(self.product.speech_message)
        self.assertGreater(self.product.speech_stop_id, stop)
        release.set()
        self.wait_finished()
        self.assertIsNone(self.product.state()["response"])
        self.assertIsNone(self.heartbeat()["speech"])
        self.assert_not_persisted("SYNTHETIC_LATE_PRIVATE_RESULT", "Earlier private result")

    def test_new_request_drops_previous_output_before_model_finishes(self):
        self.heartbeat()
        self.product._publish_response("Previous private result", "old-job")
        old_speech = self.product.speech_message["id"]
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def delayed_reply(messages, tools):
            entered.set()
            self.assertTrue(release.wait(2))
            return reply(content="Fresh synthetic reply")

        self.provider.script = [delayed_reply]
        accepted = self.product.request("Say hello")
        self.assertTrue(entered.wait(1))
        self.assertIsNone(self.product.state()["response"])
        self.assertIsNone(self.heartbeat(speech_ack=old_speech)["speech"])
        release.set()
        self.wait_finished()
        current = self.heartbeat(speech_ack=old_speech)["speech"]
        self.assertEqual(current["job_id"], accepted["job_id"])
        self.assertEqual(current["text"], "Fresh synthetic reply")
        self.assertNotEqual(current["id"], old_speech)


if __name__ == "__main__":
    unittest.main()
