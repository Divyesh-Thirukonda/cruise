"""Synthetic provider/service fixtures for tests only; no demo or live model path."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modulate.agent import AgentError, Ledger, Orchestrator, digest
from modulate.agent_provider import AgentProvider


def reply(*calls, content=""):
    return {"content": content, "tool_calls": [
        {"id": f"call_{index}", "name": name, "arguments": arguments}
        for index, (name, arguments) in enumerate(calls)
    ], "usage": {}, "provider": "ollama", "model": "llama3.2:3b"}


def result_for(messages, name):
    return json.loads(next(message["content"] for message in reversed(messages)
                           if message.get("role") == "tool" and message.get("name") == name))


def control_package(title="Synthetic control test"):
    return {"kind": "control", "title": title, "target": "test-session",
            "bindings": [{"control": "encoder", "action": "volume.delta", "scale": 2}]}


def game_package(control="button_a"):
    # Tests only: shape-valid code and one visible pixel, never a shipped game.
    return {"kind": "game", "title": "Synthetic validation test", "controls": [control],
            "code": "function init(){return {}}; function update(s,i,d){return s}; function draw(s){return []}",
            "assets": {"sprites": {"test_pixel": {"width": 1, "height": 1,
                "palette": ["#FFFFFF"], "pixels": [[0]]}}}}


class ScriptedProvider:
    """Replay explicit test decisions while using the real request preflight."""
    def __init__(self, script):
        self.real = AgentProvider({"provider": "ollama", "model": "llama3.2:3b"})
        self.config = self.real.config
        self.script = list(script)
        self.requests = []
        self.call_number = 0

    def request_budget(self, messages, tools):
        return self.real.request_budget(messages, tools)

    def complete(self, messages, tools):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        value = step(messages, tools) if callable(step) else copy.deepcopy(step)
        # Tool IDs must be unique across a single replayed conversation.
        self.call_number += 1
        for call in value["tool_calls"]:
            call["id"] = f"turn_{self.call_number}_{call['id']}"
        return value


class FakeService:
    """Test service records requests; it never controls a device or a host."""
    def __init__(self):
        self.revision = "revision-0"
        self.manifest = {"controls": ["encoder", "button_a"], "display": {"width": 240, "height": 135},
                         "paired_hosts": [{"session_id": "test-session", "actions": ["volume.delta"]}],
                         "paired_host": {"session_id": "a" * 32}}
        self.events, self.activations, self.candidates = [], [], []
        self.package = None
        self.checked = 0
        self.check_passes = True
        self.on_event = None
        self.questions = []
        self.camera_actions, self.system_actions, self.camera_checks = [], [], []

    def event(self, event):
        self.events.append(copy.deepcopy(event))
        if self.on_event:
            self.on_event(event)

    def capabilities(self):
        return copy.deepcopy(self.manifest)

    def current_package(self):
        return copy.deepcopy(self.package)

    def request_clarification(self, question):
        self.questions.append(question)
        return {"question": question}

    def camera_control(self, action):
        self.camera_actions.append(action)
        return {"state": "starting" if action == "start" else "ready" if action == "status" else "stopped",
                "target": "a" * 32}

    def system_control(self, action, value=None):
        self.system_actions.append((action, value))
        return {"action": action, "value": value, "performed": True}

    def validate_camera(self, package):
        self.camera_checks.append(copy.deepcopy(package))
        if package["camera"]["target"] != (self.manifest.get("paired_host") or {}).get("session_id"):
            raise AgentError("Synthetic camera target is not paired")

    def validate_control(self, package):
        if set(package) != {"kind", "title", "target", "bindings"} or package["target"] != "test-session":
            raise AgentError("Invalid synthetic control package")
        return copy.deepcopy(package)

    def verify_control(self, package):
        self.checked += 1
        return {"passed": self.check_passes, "checks": [{"name": "synthetic_grant_check", "passed": self.check_passes}]}

    def candidate_changed(self, identifier, package):
        self.candidates.append((identifier, copy.deepcopy(package)))

    def activate(self, package, report, *, base_revision):
        if self.revision != base_revision:
            raise AgentError("Stale synthetic device revision")
        self.activations.append(copy.deepcopy(package))
        self.package = copy.deepcopy(package)
        self.revision = f"revision-{len(self.activations)}"
        return {"acknowledged": True, "revision": self.revision, "candidate_id": digest(package)}


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = FakeService()

    def make(self, script, max_calls=18):
        provider = ScriptedProvider(script)
        ledger = Ledger(self.root / "ledger.json", limit_dollars=0)
        agent = Orchestrator(provider, self.service, self.root / "agent", ledger, max_calls=max_calls)
        return agent, provider

    def prepare(self):
        agent, provider = self.make([reply(content="Ready for synthetic test")])
        agent.run("Synthetic test request")
        return agent, provider

    def candidate(self, agent, *, checked=True):
        result = agent.dispatch("write_package", {"package": control_package()}, "orchestrator")
        identifier = result["candidate_id"]
        if checked:
            agent.dispatch("test_package", {"candidate_id": identifier}, "orchestrator")
        return identifier

    def test_text_only_answer_does_not_force_tools_or_activation(self):
        agent, provider = self.make([reply(content="A paired computer is needed.")])
        self.assertEqual(agent.run("Synthetic request"), "A paired computer is needed.")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.service.activations, [])
        self.assertFalse(any(item["type"] == "tool_started" for item in self.service.events))
        self.assertEqual(agent.ledger.status()["charged_or_reserved_dollars"], 0)

    def test_repeated_identical_tool_failure_stops_and_counter_resets_for_new_request(self):
        failing = reply(("read_current_package", {}))
        agent, provider = self.make([failing, failing, failing, reply(content="Must not be called")])
        def unavailable():
            raise AgentError("Synthetic operation unavailable")
        self.service.current_package = unavailable
        with self.assertRaisesRegex(AgentError, "same operation failed three times"):
            agent.run("Synthetic request")
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(self.service.activations, [])
        provider.script = [failing, reply(content="This operation is unavailable.")]
        self.assertEqual(agent.run("A new request"), "This operation is unavailable.")

    def test_model_selects_order_then_writes_checks_and_activates_exact_candidate(self):
        def build(messages, tools):
            self.assertIn("runtime", result_for(messages, "read_runtime_api"))
            self.assertIn("encoder", result_for(messages, "inspect_capabilities")["controls"])
            return reply(("write_package", {"package": control_package()}))

        def check(messages, tools):
            return reply(("test_package", {"candidate_id": result_for(messages, "write_package")["candidate_id"]}))

        def activate(messages, tools):
            report = result_for(messages, "test_package")
            self.assertTrue(report["passed"])
            return reply(("activate_package", {"candidate_id": report["candidate_id"]}))

        def final(messages, tools):
            self.assertTrue(result_for(messages, "activate_package")["acknowledged"])
            return reply(content="Turn the encoder to change volume.")

        agent, _ = self.make([reply(("read_runtime_api", {}), ("inspect_capabilities", {})), build, check, activate, final])
        self.assertIn("encoder", agent.run("Synthetic control request"))
        started = [event["tool"] for event in self.service.events if event["type"] == "tool_started"]
        self.assertEqual(started, ["read_runtime_api", "inspect_capabilities", "write_package", "test_package", "activate_package"])
        self.assertEqual(len(self.service.activations), 1)
        self.assertEqual(agent.base_revision, self.service.revision)
        self.assertEqual(self.service.checked, 1)

    def test_tool_failure_is_observation_and_model_can_choose_a_different_tool(self):
        def recover(messages, tools):
            self.assertIn("error", result_for(messages, "write_package"))
            return reply(("inspect_capabilities", {}))

        agent, _ = self.make([reply(("write_package", {"package": None})), recover, reply(content="Need different controls.")])
        self.assertEqual(agent.run("Synthetic request"), "Need different controls.")
        self.assertEqual(self.service.activations, [])
        self.assertEqual([event["status"] for event in self.service.events if event["type"] == "tool_finished"], ["failed", "passed"])

    def test_specialist_role_has_restricted_tools_and_shared_call_budget(self):
        def specialist(messages, tools):
            self.assertIn("artist specialist", messages[0]["content"])
            names = {item["function"]["name"] for item in tools}
            self.assertNotIn("activate_package", names)
            self.assertNotIn("delegate_task", names)
            self.assertNotIn("ask_user", names)
            self.assertNotIn("camera_control", names)
            self.assertNotIn("system_control", names)
            return reply(("read_runtime_api", {}))

        def final(messages, tools):
            result = result_for(messages, "delegate_task")
            self.assertEqual(result["specialist"], "artist")
            self.assertEqual(result["report"], "Synthetic art review complete")
            return reply(content="Review received")

        agent, provider = self.make([reply(("delegate_task", {"role": "artist", "task": "Review the sprite format"})),
                                    specialist, reply(content="Synthetic art review complete"), final], max_calls=4)
        self.assertEqual(agent.run("Synthetic art request"), "Review received")
        self.assertEqual(agent.calls, 4)
        self.assertEqual(agent.ledger.status()["calls"], 4)
        self.assertEqual(len(provider.requests), 4)

    def test_specialist_exhaustion_cannot_create_extra_provider_calls(self):
        agent, provider = self.make([reply(("delegate_task", {"role": "coder", "task": "Inspect hardware"})),
                                    reply(("inspect_capabilities", {}))], max_calls=2)
        with self.assertRaisesRegex(AgentError, "Shared agent-call limit"):
            agent.run("Synthetic request")
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(agent.ledger.status()["calls"], 2)
        self.assertEqual(self.service.activations, [])

    def test_delegate_limit_and_specialist_permissions_are_runtime_enforced(self):
        agent, _ = self.prepare()
        for name, arguments in (("activate_package", {"candidate_id": "unknown"}),
                                ("delegate_task", {"role": "coder", "task": "test"})):
            with self.assertRaisesRegex(AgentError, "Specialists cannot"):
                agent.dispatch(name, arguments, "reviewer")
        agent.delegations = 2
        with self.assertRaisesRegex(AgentError, "Specialist limit"):
            agent.dispatch("delegate_task", {"role": "coder", "task": "test"}, "orchestrator")

    def test_activation_requires_successful_fixed_checks(self):
        agent, _ = self.prepare()
        identifier = self.candidate(agent, checked=False)
        with self.assertRaisesRegex(AgentError, "fixed checks"):
            agent.dispatch("activate_package", {"candidate_id": identifier}, "orchestrator")
        self.service.check_passes = False
        agent.dispatch("test_package", {"candidate_id": identifier}, "orchestrator")
        with self.assertRaisesRegex(AgentError, "fixed checks"):
            agent.dispatch("activate_package", {"candidate_id": identifier}, "orchestrator")
        self.assertEqual(self.service.activations, [])

    def test_changed_candidate_or_report_cannot_reuse_passed_check(self):
        for change in ("package", "candidate_id", "manifest_revision", "passed"):
            with self.subTest(change=change):
                agent, _ = self.prepare()
                identifier = self.candidate(agent)
                candidate = agent.candidates[identifier]
                if change == "package":
                    candidate["package"]["title"] = "Changed after verification"
                else:
                    candidate["report"][change] = "not-the-verified-value"
                for action in ("activate_package", "preview_package"):
                    with self.assertRaises(AgentError):
                        agent.dispatch(action, {"candidate_id": identifier}, "orchestrator")
        self.assertEqual(self.service.activations, [])

    def test_capability_change_and_stale_base_revision_block_activation(self):
        for change in ("capability", "revision"):
            with self.subTest(change=change):
                agent, _ = self.prepare()
                identifier = self.candidate(agent)
                if change == "capability":
                    self.service.manifest["controls"].remove("encoder")
                else:
                    self.service.revision = "external-activation"
                with self.assertRaisesRegex(AgentError, "changed"):
                    agent.dispatch("activate_package", {"candidate_id": identifier}, "orchestrator")
        self.assertEqual(self.service.activations, [])

    def test_missing_controls_and_semantic_tool_arguments_are_rejected(self):
        agent, _ = self.prepare()
        for arguments in ({"package": None}, {"package": []}, {"package": {"kind": "shell"}},
                          {"package": control_package(), "untrusted": "extra"}, {}):
            with self.assertRaises(AgentError):
                agent.dispatch("write_package", arguments, "orchestrator")
        with self.assertRaisesRegex(AgentError, "absent"):
            agent.dispatch("write_package", {"package": game_package("joystick")}, "orchestrator")
        for arguments in ({"role": [], "task": "test"}, {"role": "coder", "task": ""}, {"role": "coder", "task": 3}):
            with self.assertRaises(AgentError):
                agent.dispatch("delegate_task", arguments, "orchestrator")
        self.assertEqual(self.service.candidates, [])

    def test_camera_control_returns_metadata_without_entering_screen_private_mode(self):
        def after_start(messages, tools):
            self.assertEqual(result_for(messages, "camera_control")["state"], "starting")
            self.assertIn("write_package", {item["function"]["name"] for item in tools})
            self.assertFalse(any(isinstance(message["content"], list) for message in messages))
            return reply(("camera_control", {"action": "status"}))

        agent, provider = self.make([reply(("camera_control", {"action": "start"})), after_start,
                                    reply(content="Synthetic camera metadata is ready.")])
        self.assertIn("ready", agent.run("Synthetic camera request"))
        self.assertEqual(self.service.camera_actions, ["start", "status"])
        self.assertFalse(agent.private_request)
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(self.service.questions, [])
        self.assertEqual(self.service.activations, [])

    def test_camera_and_system_actions_are_orchestrator_only_and_cancelled_before_dispatch(self):
        agent, _ = self.prepare()
        for name, arguments in (("camera_control", {"action": "start"}),
                                ("system_control", {"action": "brightness.set", "value": 65})):
            with self.subTest(tool=name):
                for role in ("coder", "artist", "reviewer"):
                    with self.assertRaisesRegex(AgentError, "Specialists cannot"):
                        agent.dispatch(name, arguments, role)
                agent.cancelled.set()
                with self.assertRaisesRegex(AgentError, "Cancelled"):
                    agent.dispatch(name, arguments, "orchestrator")
                agent.cancelled.clear()
        self.assertEqual((self.service.camera_actions, self.service.system_actions), ([], []))

    def test_camera_actions_reject_unknown_or_extra_arguments(self):
        agent, _ = self.prepare()
        for arguments in ({}, {"action": "capture_and_upload"}, {"action": []},
                          {"action": "start", "target": "unpaired"},
                          {"action": "status", "image_url": "synthetic-private-image"}):
            with self.subTest(arguments=arguments), self.assertRaises(AgentError):
                agent.dispatch("camera_control", arguments, "orchestrator")
        self.assertEqual(self.service.camera_actions, [])

    def test_system_actions_validate_operation_specific_values_before_service(self):
        agent, _ = self.prepare()
        good = [("volume.get", None), ("brightness.get", None), ("volume.set", 0),
                ("brightness.set", 100), ("volume.delta", -10), ("brightness.delta", 10),
                ("volume.mute", True), ("volume.mute", False)]
        for action, value in good:
            arguments = {"action": action} if value is None else {"action": action, "value": value}
            self.assertTrue(agent.dispatch("system_control", arguments, "orchestrator")["performed"])
        self.assertEqual(self.service.system_actions, good)
        self.assertFalse(agent.private_request)
        self.service.system_actions.clear()
        bad = [("volume.get", 1), ("brightness.get", None), ("volume.set", True),
               ("brightness.set", -1), ("volume.set", 101), ("brightness.set", 50.0),
               ("volume.delta", -11), ("brightness.delta", 11), ("volume.delta", False),
               ("volume.mute", 1), ("volume.mute", "yes"), ("brightness.mute", True)]
        for action, value in bad:
            with self.subTest(action=action, value=value), self.assertRaises(AgentError):
                agent.dispatch("system_control", {"action": action, "value": value}, "orchestrator")
        for action in ("volume.set", "brightness.set", "volume.delta", "brightness.delta", "volume.mute"):
            with self.subTest(missing_value=action), self.assertRaises(AgentError):
                agent.dispatch("system_control", {"action": action}, "orchestrator")
        with self.assertRaises(AgentError):
            agent.dispatch("system_control", {"action": "volume.get", "target": "other-host"}, "orchestrator")
        self.assertEqual(self.service.system_actions, [])

    def test_private_task_can_adjust_system_or_stop_camera_but_cannot_write_or_delegate(self):
        agent, _ = self.prepare()
        agent.private_request = True
        agent.dispatch("camera_control", {"action": "stop"}, "orchestrator")
        agent.dispatch("system_control", {"action": "volume.delta", "value": -2}, "orchestrator")
        for name, arguments in (("write_package", {"package": game_package()}),
                                ("delegate_task", {"role": "artist", "task": "Copy synthetic screen text"})):
            with self.assertRaisesRegex(AgentError, "cannot be written"):
                agent.dispatch(name, arguments, "orchestrator")
        self.assertTrue(agent.private_request)
        self.assertEqual(self.service.camera_actions, ["stop"])
        self.assertEqual(self.service.system_actions, [("volume.delta", -2)])
        self.assertEqual(self.service.candidates, [])
        self.assertEqual(list(agent.directory.glob("*.json")), [])

    def test_camera_package_requires_actual_paired_target_and_trusted_validation(self):
        agent, _ = self.prepare()
        package = {**game_package(), "camera": {"target": "a" * 32}}
        candidate = agent.dispatch("write_package", {"package": package}, "orchestrator")
        self.assertEqual(candidate["candidate_id"], digest(package))
        self.assertEqual(self.service.camera_checks, [package])
        self.assertEqual(agent.candidate(candidate["candidate_id"])["package"]["camera"], package["camera"])
        with self.assertRaisesRegex(AgentError, "fixed checks"):
            agent.dispatch("activate_package", {"candidate_id": candidate["candidate_id"]}, "orchestrator")
        self.assertEqual(self.service.activations, [])

    def test_camera_wrong_or_missing_pairing_is_rejected_before_persisting_candidate(self):
        agent, _ = self.prepare()
        for paired in (None, {}, {"session_id": "b" * 32}):
            with self.subTest(paired=paired):
                agent.manifest["paired_host"] = paired
                with self.assertRaisesRegex(AgentError, "currently paired"):
                    agent.dispatch("write_package", {"package": {**game_package(), "camera": {"target": "a" * 32}}},
                                   "orchestrator")
        self.assertEqual(self.service.camera_checks, [])
        self.assertEqual(self.service.candidates, [])
        self.assertEqual(list(agent.directory.glob("*.json")), [])

    def test_failed_camera_validation_does_not_create_candidate(self):
        agent, _ = self.prepare()
        with patch.object(self.service, "validate_camera", side_effect=AgentError("Synthetic camera permission missing")):
            with self.assertRaisesRegex(AgentError, "camera permission"):
                agent.dispatch("write_package", {"package": {**game_package(), "camera": {"target": "a" * 32}}},
                               "orchestrator")
        self.assertEqual(self.service.candidates, [])
        self.assertEqual(list(agent.directory.glob("*.json")), [])

    def test_camera_candidate_still_uses_independent_game_verifier_and_exact_hash(self):
        agent, _ = self.prepare()
        package = {**game_package(), "camera": {"target": "a" * 32}}
        candidate = agent.dispatch("write_package", {"package": package}, "orchestrator")
        # Synthetic verifier report tests orchestration only, not camera hardware.
        with patch("modulate.agent.verify", return_value={"passed": False, "checks": []}) as verifier:
            report = agent.dispatch("test_package", {"candidate_id": candidate["candidate_id"]}, "orchestrator")
        verifier.assert_called_once_with(package)
        self.assertEqual(report["candidate_id"], digest(package))
        self.assertEqual(report["manifest_revision"], agent.manifest_revision)
        with self.assertRaisesRegex(AgentError, "fixed checks"):
            agent.dispatch("activate_package", {"candidate_id": candidate["candidate_id"]}, "orchestrator")
        self.assertEqual(self.service.activations, [])

    def test_cancellation_during_text_or_tool_model_reply_stops_actions(self):
        for response in (reply(content="Finished"), reply(("inspect_capabilities", {}))):
            with self.subTest(response=response):
                def cancel(messages, tools):
                    agent.cancelled.set()
                    return copy.deepcopy(response)

                agent, _ = self.make([cancel])
                with self.assertRaisesRegex(AgentError, "Cancelled"):
                    agent.run("Synthetic request")
                self.assertFalse(any(event["type"] == "request_finished" for event in self.service.events))
                self.service.events.clear()

    def test_cancellation_before_first_call_spends_nothing(self):
        agent, provider = self.make([])
        self.service.on_event = lambda event: agent.cancelled.set() if event["type"] == "request_started" else None
        with self.assertRaisesRegex(AgentError, "Cancelled"):
            agent.run("Synthetic request")
        self.assertEqual(provider.requests, [])
        self.assertEqual(agent.ledger.status()["calls"], 0)

    def test_cancellation_after_reservation_before_dispatch_does_not_call_model(self):
        agent, provider = self.make([])
        self.service.on_event = lambda event: agent.cancelled.set() if event["type"] == "model_call" else None
        with self.assertRaisesRegex(AgentError, "Cancelled"):
            agent.run("Synthetic request")
        self.assertEqual(provider.requests, [])
        self.assertEqual(agent.ledger.data["calls"][0]["status"], "settled")

    def test_concurrent_request_does_not_reset_active_state(self):
        agent, _ = self.prepare()
        original_id = agent.request_id
        agent.run_lock.acquire()
        try:
            with self.assertRaisesRegex(AgentError, "already running"):
                agent.run("Conflicting synthetic request")
        finally:
            agent.run_lock.release()
        self.assertEqual(agent.request_id, original_id)

    def test_cloud_failure_retains_reservation_and_restart_budget(self):
        class FailedCloudProvider:
            def __init__(self):
                self.real = AgentProvider({"provider": "meta", "model": "muse-spark-1.3", "max_tokens": 8192})
                self.config = self.real.config
                self.calls = 0

            def request_budget(self, messages, tools):
                return self.real.request_budget(messages, tools)

            def complete(self, messages, tools):
                self.calls += 1
                raise AgentError("Synthetic timeout after dispatch")

        path = self.root / "cloud-ledger.json"
        provider = FailedCloudProvider()
        ledger = Ledger(path, limit_dollars=2)
        agent = Orchestrator(provider, self.service, self.root / "cloud-agent", ledger)
        with self.assertRaisesRegex(AgentError, "Synthetic timeout"):
            agent.run("Synthetic paid-call failure")
        self.assertEqual(ledger.data["charged"], 1345536)
        restarted = Ledger(path, limit_dollars=2)
        agent.ledger = restarted
        with self.assertRaisesRegex(AgentError, "approved model budget"):
            agent.run("Second synthetic request")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(restarted.status()["calls"], 1)

    def test_incomplete_request_can_ask_one_question_without_creating_or_activating(self):
        question = "What would you like the controller to become?"
        agent, provider = self.make([reply(("ask_user", {"question": question}))])
        self.assertEqual(agent.run("Can you make it..."), question)
        self.assertEqual(self.service.questions, [question])
        self.assertEqual((self.service.candidates, self.service.activations), ([], []))
        self.assertEqual(len(provider.requests), 1)
        result = next(event["detail"] for event in self.service.events
                      if event["type"] == "tool_finished" and event["tool"] == "ask_user")
        self.assertEqual(result, {"clarification_required": True, "question": question})

    def test_clarification_preempts_same_batch_writes_and_activation_in_either_order(self):
        question = "Which app do you want to change?"
        for before in (True, False):
            with self.subTest(ask_first=before):
                calls = [("write_package", {"package": control_package()}),
                         ("activate_package", {"candidate_id": "not-verified"})]
                call = ("ask_user", {"question": question})
                calls = [call, *calls] if before else [*calls, call]
                agent, provider = self.make([reply(*calls)])
                self.assertEqual(agent.run("Change that one"), question)
                self.assertEqual(len(provider.requests), 1)
        self.assertEqual((self.service.candidates, self.service.activations), ([], []))

    def test_question_accepts_printable_unicode_but_not_multiline_or_oversized_text(self):
        agent, _ = self.prepare()
        for question in ("", "   ", "First question\nSecond question", "x" * 181, "What\x00app?"):
            with self.assertRaises(AgentError):
                agent.dispatch("ask_user", {"question": question}, "orchestrator")
        question = "Quel jeu voulez-vous créer ?"
        self.assertEqual(agent.dispatch("ask_user", {"question": question}, "orchestrator")["question"], question)
        with self.assertRaisesRegex(AgentError, "Waiting"):
            agent.dispatch("write_package", {"package": control_package()}, "orchestrator")

    def test_specialist_cannot_request_user_clarification(self):
        agent, _ = self.prepare()
        with self.assertRaisesRegex(AgentError, "Specialists cannot"):
            agent.dispatch("ask_user", {"question": "What should I build?"}, "coder")
        self.assertEqual(self.service.questions, [])

    def test_failed_clarification_delivery_stops_without_running_other_tools(self):
        agent, provider = self.make([reply(("ask_user", {"question": "Which app?"}),
                                          ("write_package", {"package": control_package()}))])
        def fail(question):
            raise AgentError("Synthetic clarification delivery failure")
        self.service.request_clarification = fail
        with self.assertRaisesRegex(AgentError, "Could not request clarification"):
            agent.run("Change it")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(self.service.candidates, [])

    def test_new_user_request_resets_clarification_waiting_state(self):
        agent, provider = self.make([reply(("ask_user", {"question": "Which app?"})), reply(content="Thanks for clarifying.")])
        agent.run("Change it")
        self.assertEqual(agent.run("The currently active game"), "Thanks for clarifying.")
        self.assertIsNone(agent.clarification)
        self.assertEqual(len(provider.requests), 2)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.json"

    def test_settlement_and_unknown_usage_survive_restart(self):
        ledger = Ledger(self.path, 1)
        first = ledger.reserve(400000)
        second = ledger.reserve(500000)
        ledger.settle(first, 100000)
        ledger.settle(second, None)
        restarted = Ledger(self.path, 1)
        self.assertEqual(restarted.data["charged"], 600000)
        self.assertEqual([item["status"] for item in restarted.data["calls"]], ["settled", "reserved"])
        restarted.reserve(400000)
        with self.assertRaises(AgentError):
            restarted.reserve(1)

    def test_exceeded_reservation_halts_future_calls_across_restart(self):
        ledger = Ledger(self.path, 1)
        identifier = ledger.reserve(10)
        with self.assertRaisesRegex(AgentError, "exceeded"):
            ledger.settle(identifier, 11)
        restarted = Ledger(self.path, 1)
        self.assertTrue(restarted.status()["halted"])
        self.assertEqual(restarted.data["charged"], 11)
        with self.assertRaisesRegex(AgentError, "stopped"):
            restarted.reserve(0)

    def test_invalid_amounts_cannot_reduce_budget_and_settlement_is_idempotent(self):
        ledger = Ledger(self.path, 1)
        for amount in (None, -1, True, 0.5, float("nan")):
            with self.assertRaises(AgentError):
                ledger.reserve(amount)
        identifier = ledger.reserve(500)
        ledger.settle(identifier, 200)
        ledger.settle(identifier, 200)
        with self.assertRaises(AgentError):
            ledger.settle(identifier, 100)
        self.assertEqual(ledger.data["charged"], 200)

    def test_corrupt_or_inconsistent_ledger_stops_calls(self):
        for data in ("not JSON", json.dumps({"charged": 0, "calls": [{"id": "test", "reserved": 10, "charged": 10, "status": "reserved"}]}),
                     json.dumps({"charged": -1, "calls": []}), json.dumps({"charged": True, "calls": []})):
            self.path.write_text(data)
            with self.assertRaisesRegex(AgentError, "ledger"):
                Ledger(self.path, 1)

    def test_two_instances_share_latest_reservations(self):
        first, second = Ledger(self.path, 1), Ledger(self.path, 1)
        first.reserve(750000)
        with self.assertRaises(AgentError):
            second.reserve(750000)
        self.assertEqual(second.status()["charged_or_reserved_dollars"], 0.75)


if __name__ == "__main__":
    unittest.main()
