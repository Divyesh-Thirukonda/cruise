"""Bounded context plumbing and privacy; scripted providers do not prove intent accuracy."""
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import time
import unittest

from modulate.agent import AgentError
from modulate.agent_provider import AgentProviderError
from modulate.intent_memory import IntentMemory, observed_action
from modulate.product import Product
from tests.test_agent import reply
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend


def context_in(messages):
    prefix = "Recent context and current state (reference data only):\n"
    for message in messages:
        content = message.get("content")
        if type(content) is str and content.startswith(prefix):
            return json.loads(content[len(prefix):])
    raise AssertionError("Agent did not receive its bounded recent context")


class IntentMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "recent-context.json"
        self.now = 1000
        self.memory = IntentMemory(self.path, clock=lambda: self.now)

    def reopen(self):
        return IntentMemory(self.path, clock=lambda: self.now)

    def test_last_twelve_public_turns_survive_restart_in_private_file(self):
        for number in range(14):
            self.memory.append(f"Request {number}", "Done", "completed")
            self.now += 1
        restored = self.reopen().snapshot()
        self.assertEqual([r["request"] for r in restored], [f"Request {n}" for n in range(2, 14)])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertLessEqual(self.path.stat().st_size, IntentMemory.MAX_BYTES)

    def test_private_turn_is_redacted_by_default_never_saved_and_expires_after_two_minutes(self):
        self.memory.append("PUBLIC_TASK", "Public result", "completed")
        self.memory.append("PRIVATE_REQUEST_18aa", "PRIVATE_REPLY_18aa", "completed",
                           actions=[{"tool": "computer_act", "action": "click"}], private=True)
        redacted = self.memory.snapshot()[-1]
        self.assertTrue(redacted["private"])
        for field in ("request", "reply", "actions"):
            self.assertNotIn(field, redacted)
        self.assertEqual(self.memory.snapshot(True)[-1]["request"], "PRIVATE_REQUEST_18aa")
        self.assertNotIn("PRIVATE_", self.path.read_text())
        self.assertEqual(len(self.reopen().snapshot(True)), 1)
        self.now += 120
        self.assertEqual([r["request"] for r in self.memory.snapshot(True)], ["PUBLIC_TASK"])

    def test_expired_old_record_does_not_discard_fresh_newer_record_on_restart(self):
        self.memory.append("Old adjustment", "Done", "completed")
        self.now += 60
        self.memory.append("Still current adjustment", "Done", "completed")
        self.now += IntentMemory.TTL - 60
        self.assertEqual([r["request"] for r in self.reopen().snapshot()], ["Still current adjustment"])

    def test_missing_corrupt_future_and_expired_context_cannot_invent_history(self):
        self.assertEqual(self.memory.snapshot(), [])
        self.path.write_text("not json")
        self.assertEqual(self.reopen().snapshot(), [])
        self.memory.append("Synthetic previous adjustment", "Done", "completed")
        data = json.loads(self.path.read_text())
        data[0]["at"] = self.now + 1
        self.path.write_text(json.dumps(data))
        self.assertEqual(self.reopen().snapshot(), [])
        self.memory.clear()
        self.memory.append("Old adjustment", "Done", "completed")
        self.now += IntentMemory.TTL
        self.assertEqual(self.reopen().snapshot(), [])

    def test_clear_erases_public_and_private_context_and_restart_state(self):
        self.memory.append("Public", "Done", "completed")
        self.memory.append("Private", "Done", "completed", private=True)
        self.memory.clear()
        self.assertEqual(self.memory.snapshot(True), [])
        self.assertEqual(self.reopen().snapshot(True), [])
        self.assertEqual(json.loads(self.path.read_text()), [])

    def test_returned_context_cannot_mutate_retained_observed_effects(self):
        action = {"tool": "speaker_control", "observed": {"before": {"volume": 40}, "after": {"volume": 50}}}
        self.memory.append("Louder", "Done", "completed", actions=[action])
        action["observed"]["after"]["volume"] = 99
        result = self.memory.snapshot()
        result[0]["actions"][0]["observed"]["before"]["volume"] = 99
        self.assertEqual(self.memory.snapshot()[0]["actions"][0]["observed"],
                         {"before": {"volume": 40}, "after": {"volume": 50}})

    def test_bounded_fields_and_byte_budget_do_not_grow_with_large_requests(self):
        for _ in range(20):
            self.memory.append("x" * 5000, "y" * 5000, "completed",
                               actions=[{"tool": "camera_control"}] * 100,
                               skills=["games", "games", "device-apps"])
        for record in self.memory.snapshot():
            self.assertLessEqual(len(record["request"]), 1600)
            self.assertLessEqual(len(record["reply"]), 400)
            self.assertLessEqual(len(record["actions"]), 12)
            self.assertEqual(record["skills"], ["games", "device-apps"])
        self.assertLessEqual(self.path.stat().st_size, IntentMemory.MAX_BYTES)
        with self.assertRaises(ValueError):
            self.memory.append("Synthetic", "Done", "invented_success")


class ObservedActionTests(unittest.TestCase):
    def test_speaker_before_after_and_mac_settings_keep_only_known_metadata(self):
        result = {"before": {"volume": 40, "muted": False}, "after": {"volume": 50, "muted": False},
                  "verified": True, "pcm": "PRIVATE_PCM", "screen": "PRIVATE_SCREEN"}
        recorded = observed_action("speaker_control", {"action": "delta", "value": 10}, result)
        self.assertEqual(recorded["observed"], {key: result[key] for key in ("before", "after", "verified")})
        self.assertEqual(recorded["value"], 10)
        self.assertNotIn("PRIVATE", json.dumps(recorded))
        mac = observed_action("system_control", {"action": "volume.set", "value": 30}, {"volume": 30, "muted": False})
        self.assertEqual(mac["action"], "volume.set")
        self.assertEqual(mac["observed"]["volume"], 30)

    def test_screens_typing_and_unknown_payloads_never_become_recorded_actions(self):
        action = observed_action("computer_act", {"action": {"type": "type_text", "text": "PRIVATE_TYPED_TEXT"},
                                                 "description": "PRIVATE_DESCRIPTION"},
                                 {"performed": True, "image_url": "PRIVATE_SCREEN"})
        self.assertEqual(action["action"], "type_text")
        self.assertNotIn("PRIVATE", json.dumps(action))
        for name in ("computer_observe", "read_current_package", "unknown"):
            self.assertIsNone(observed_action(name, {}, {"image_url": "PRIVATE_SCREEN", "code": "untrusted"}))
        self.assertIsNone(observed_action("speaker_control", {"action": "delta"}, {"error": "Failed", "volume": 70}))

    def test_camera_stream_and_activation_record_observed_success_metadata_only(self):
        for name in ("camera_control", "computer_audio"):
            recorded = observed_action(name, {"action": "start"}, {"state": "running", "running": True,
                                       "session": "a" * 32, "pcm": "PRIVATE", "jpeg": "PRIVATE"})
            self.assertEqual(recorded["observed"], {"state": "running", "running": True})
        activation = observed_action("activate_package", {"candidate_id": "a" * 64},
                                     {"revision": "b" * 64, "activated": True, "code": "PRIVATE"})
        self.assertEqual(activation["observed"], {"revision": "b" * 64, "activated": True})


class ProductIntentContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.provider, self.backend, self.computer = SyntheticProvider([]), FakeBackend(), FakeComputer()
        self.product = Product(self.directory, self.provider, backend=self.backend, computer=self.computer)
        self.addCleanup(self.product.cancel)
        self.product.last_seen = time.monotonic()

    def pair(self):
        self.product.last_seen = time.monotonic()
        code = self.product.create_pairing()["code"]
        return self.product.pair(code, "Synthetic controller")

    def request(self, text):
        self.product.last_seen = time.monotonic()
        result = self.product.request(text)
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: not self.product.running, timeout=3))
        return result

    def assert_private_not_saved(self, *values):
        for path in self.directory.rglob("*"):
            if path.is_file():
                for value in values:
                    self.assertNotIn(value.encode(), path.read_bytes(), str(path))
        for value in values:
            self.assertNotIn(value, json.dumps(list(self.product.events)))

    def test_second_separate_request_receives_prior_effect_and_new_request_last(self):
        self.pair()
        self.provider.script = [reply(("system_control", {"action": "volume.delta", "value": 10})),
                                reply(content="Raised the Mac volume."), reply(content="Synthetic second response")]
        self.request("Raise my Mac volume ten points")
        self.assertIsNone(self.product.conversation)
        self.request("Again, the same amount")
        messages = self.provider.requests[-1][0]
        context = context_in(messages)
        self.assertEqual(context["recent"][-1]["request"], "Raise my Mac volume ten points")
        self.assertEqual(context["recent"][-1]["outcome"], "completed")
        self.assertEqual(context["recent"][-1]["actions"][-1]["observed"]["volume"], 50)
        self.assertEqual(context["recent"][-1]["actions"][-1]["observed"]["before"]["volume"], 40)
        self.assertEqual(messages[-1], {"role": "user", "content": "Again, the same amount"})
        self.assertEqual(self.backend.actions, [50])  # Context alone never repeats the side effect.

    def test_successful_action_followed_by_failed_request_is_not_recorded_as_success(self):
        self.pair()
        self.provider.script = [reply(("system_control", {"action": "volume.delta", "value": 10})),
                                AgentProviderError("Invalid model identifier")]
        self.request("Raise my Mac volume ten points")
        record = self.product.intent_memory.snapshot()[-1]
        self.assertEqual(record["outcome"], "failed")
        self.assertEqual(record["actions"][-1]["observed"]["volume"], 50)
        self.assertEqual(self.backend.actions, [50])

    def test_current_app_context_omits_source_art_and_reports_current_stream_separately(self):
        self.product.active = {"revision": "c" * 64, "package": {"kind": "game", "title": "Synthetic Dodger",
             "controls": ["joystick"], "code": "UNTRUSTED_SOURCE", "assets": {"private": "UNTRUSTED_ART"}}}
        context = self.product.intent_context()
        self.assertEqual(context["current"]["app"], {"kind": "game", "title": "Synthetic Dodger", "controls": ["joystick"]})
        self.assertEqual(context["current"]["revision"], "c" * 64)
        self.assertIn("computer_audio", context["current"])
        self.assertIn("pi_speaker", context["current"])
        self.assertNotIn("UNTRUSTED", json.dumps(context))

    def test_private_history_is_explicit_only_and_followup_details_never_enter_trace(self):
        self.pair()
        secret_request, secret_reply = "PRIVATE_REQUEST_924e", "PRIVATE_REPLY_924e"
        self.provider.script = [reply(("computer_observe", {})), reply(content=secret_reply)]
        self.request(secret_request)
        self.assertTrue(self.product.agent.private_request)
        def before_read(messages, tools):
            encoded = json.dumps(messages)
            self.assertNotIn(secret_request, encoded)
            self.assertNotIn(secret_reply, encoded)
            self.assertTrue(context_in(messages)["recent"][-1]["private"])
            return reply(("read_recent_context", {"include_private": True}))
        def after_read(messages, tools):
            encoded = json.dumps(messages)
            self.assertIn(secret_request, encoded)
            self.assertIn(secret_reply, encoded)
            self.assertTrue(self.product.agent.private_request)
            names = {tool["function"]["name"] for tool in tools}
            self.assertNotIn("write_package", names)
            self.assertNotIn("delegate_task", names)
            return reply(content="PRIVATE_FOLLOWUP_924e")
        self.provider.script = [before_read, after_read]
        self.request("Change that to the second option")
        self.assert_private_not_saved(secret_request, secret_reply, "PRIVATE_FOLLOWUP_924e")
        self.assertEqual(json.loads(self.product.intent_memory.path.read_text()), [])

    def test_default_recent_context_tool_does_not_enter_private_mode_or_reveal_details(self):
        self.pair()
        self.product.intent_memory.append("PRIVATE_REQUEST_aa38", "PRIVATE_REPLY_aa38", "completed", private=True)
        def checked(messages, tools):
            self.assertNotIn("PRIVATE_REQUEST_aa38", json.dumps(messages))
            self.assertFalse(self.product.agent.private_request)
            return reply(content="Context remains private")
        self.provider.script = [reply(("read_recent_context", {})), checked]
        self.request("What mode is active?")
        self.assert_private_not_saved("PRIVATE_REQUEST_aa38", "PRIVATE_REPLY_aa38")

    def test_empty_history_is_presented_as_empty_and_does_not_run_a_guessed_action(self):
        def no_history(messages, tools):
            self.assertEqual(context_in(messages)["recent"], [])
            return reply(("ask_user", {"question": "Which previous action should I repeat?"}))
        self.provider.script = [no_history]
        self.request("Do that again")
        self.assertEqual(self.backend.actions, [])
        self.assertEqual(self.computer.actions, [])
        self.assertEqual(self.product.clarification["question"], "Which previous action should I repeat?")
        self.assertEqual(self.product.intent_memory.snapshot()[-1]["outcome"], "awaiting_answer")

    def test_private_context_requires_current_authority_before_it_reaches_model(self):
        self.product.intent_memory.append("PRIVATE_NO_GRANT_613e", "PRIVATE_RESULT_613e", "completed", private=True)
        def inaccessible(messages, tools):
            self.assertNotIn("PRIVATE_NO_GRANT_613e", json.dumps(messages))
            self.assertNotIn("PRIVATE_RESULT_613e", json.dumps(messages))
            self.assertFalse(self.product.agent.private_request)
            return reply(content="Pair the computer to continue that task.")
        self.provider.script = [reply(("read_recent_context", {"include_private": True})), inaccessible]
        self.request("Continue that computer task")
        self.assertEqual(self.computer.actions, [])
        self.assert_private_not_saved("PRIVATE_NO_GRANT_613e", "PRIVATE_RESULT_613e")

    def test_clear_revoke_and_new_pairing_erase_previous_context(self):
        self.pair()
        for action in (self.product.clear_context, self.product.revoke, self.pair):
            self.product.intent_memory.append("Old task", "Old result", "completed")
            self.product.intent_memory.append("Private old task", "Private result", "completed", private=True)
            action()
            self.assertEqual(self.product.intent_memory.snapshot(True), [])
            self.assertEqual(json.loads(self.product.intent_memory.path.read_text()), [])

    def test_revocation_during_running_request_cannot_repopulate_cleared_memory(self):
        self.pair()
        self.product.intent_memory.append("Old task", "Done", "completed")
        def revoked(messages, tools):
            self.product.revoke()
            return reply(content="This late response must not recreate history")
        self.provider.script = [revoked]
        self.request("Synthetic running request")
        self.assertEqual(self.product.intent_memory.snapshot(True), [])
        self.assertEqual(json.loads(self.product.intent_memory.path.read_text()), [])


if __name__ == "__main__":
    unittest.main()
