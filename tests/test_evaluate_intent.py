"""Intent runner oracle regressions; synthetic Studio responses only."""
import contextlib
import copy
import io
import json
import unittest
from unittest.mock import Mock, patch

from scripts import evaluate_intent as evaluation


JOB = "a" * 32
PAIR = "a1319b9b-6148-4fd1-a73b-2a8402100001"
OLD, NEW = "a" * 64, "b" * 64


def state(rev=OLD, kind="game", **package_fields):
    package = {"kind": kind, "controls": ["joystick", "button_a"], **package_fields}
    return {"agent": {"job_id": JOB, "running": False, "status": "completed"},
            "device": {"connected": True, "capabilities": {"paired_host": {"session_id": PAIR}}},
            "paired": True, "active": {"revision": rev, "package": package},
            "speaker_volume": {"available": True, "volume": 40, "muted": False},
            "volume": {"volume": 30, "muted": False},
            "computer_audio": {"running": False, "session": None},
            "budget": {"calls": 10, "charged_or_reserved_dollars": 1}, "events": []}


def event(number, tool, detail=None, **values):
    return {"id": number, "job_id": JOB, "type": "tool_finished", "tool": tool,
            "status": "passed", "detail": detail or {}, **values}


def activity(*events):
    return evaluation.event_summary({item["id"]: item for item in events})


def checks(expect, before, after, summary):
    return {item["name"]: item["passed"] for item in evaluation.verify(expect, before, after, summary)}


class IntentOracleTests(unittest.TestCase):
    def test_scenarios_require_task_specific_skills_and_each_turn_must_load_one(self):
        for name, skill in {"speaker": "hardware-controls", "mac": "hardware-controls",
                            "remap": "hardware-controls", "game": "games", "app": "device-apps"}.items():
            for item in evaluation.SCENARIOS[name]:
                self.assertEqual(item["expect"]["expected_skill"], skill)
        value = state()
        expected = {"expected_skill": "games"}
        self.assertFalse(checks(expected, value, value, activity())["appropriate_skill_loaded"])
        passed = activity(event(1, "load_skill", skill="games"))
        self.assertTrue(checks(expected, value, value, passed)["appropriate_skill_loaded"])
        failed = activity(event(1, "load_skill", {"id": "games"}, status="failed"))
        self.assertFalse(checks(expected, value, value, failed)["appropriate_skill_loaded"])

    def test_exact_product_activation_ack_and_uuid_pair_target_pass_control_oracle(self):
        before = state()
        after = state(NEW, "control", target=PAIR, bindings=[{"control": "encoder", "action": "brightness.delta", "scale": -1}])
        observed = activity(event(1, "load_skill", {"id": "hardware-controls"}),
                            event(2, "activate_package", {"activated": True, "revision": NEW,
                                  "device_acknowledged": True, "kind": "control", "title": "PRIVATE_TITLE"}))
        result = checks({"binding": ["brightness.delta", -1], "expected_skill": "hardware-controls"}, before, after, observed)
        self.assertTrue(all(result.values()), result)
        self.assertNotIn(PAIR, json.dumps(evaluation.snapshot(after)))
        self.assertNotIn("PRIVATE_TITLE", json.dumps(observed))

    def test_old_ack_or_missing_device_ack_cannot_prove_new_activation(self):
        before, after = state(), state(NEW)
        for detail in ({"activated": True, "revision": NEW},
                       {"device_acknowledged": True, "revision": OLD},
                       {"device_acknowledged": False, "revision": NEW}):
            with self.subTest(detail=detail):
                result = checks({"new_game": True}, before, after, activity(event(1, "activate_package", detail)))
                self.assertFalse(result["new_acknowledged_revision"])

    def test_wrong_pair_target_and_wrong_binding_do_not_pass(self):
        before = state()
        after = state(NEW, "control", target="old-pair", bindings=[{"control": "encoder", "action": "volume.delta", "scale": 1}])
        observed = activity(event(1, "activate_package", {"device_acknowledged": True, "revision": NEW}))
        result = checks({"binding": ["volume.delta", -1]}, before, after, observed)
        self.assertFalse(result["binding_targets_paired_mac"])
        self.assertFalse(result["exact_encoder_binding"])

    def test_game_refinement_checks_new_ack_and_same_controls_without_claiming_speed(self):
        before, after = state(), state(NEW)
        observed = activity(event(1, "load_skill", skill="games"),
                            event(2, "activate_package", {"device_acknowledged": True, "revision": NEW}))
        expected = evaluation.SCENARIOS["game"][1]["expect"]
        self.assertTrue(all(checks(expected, before, after, observed).values()))
        self.assertIn("manual", expected)
        after["active"]["package"]["controls"] = ["encoder"]
        self.assertFalse(checks(expected, before, after, observed)["same_controls"])

    def test_native_mac_readback_overrides_stale_cached_state_for_exact_oracle(self):
        before, after = state(), state()
        after["volume"] = {"volume": 12, "muted": False}
        observed = activity(event(1, "system_control", {"volume": 40, "before": {"volume": 30},
                                   "after": {"volume": 40}}, operation="volume.delta"))
        result = checks({"mac": 40, "preserve_speaker": True}, before, after, observed)
        self.assertTrue(all(result.values()), result)
        self.assertFalse(checks({"mac": 40}, before, after, activity())["exact_native_mac_readback"])

    def test_wrong_mac_target_mutation_cannot_hide_behind_correct_pi_readback(self):
        before, after = state(), state()
        after["speaker_volume"]["volume"] = 50
        observed = activity(event(1, "system_control", {"volume": 40}, operation="volume.delta"))
        result = checks({"speaker": 50, "preserve_mac": True}, before, after, observed)
        self.assertTrue(result["exact_pi_speaker_level"])
        self.assertFalse(result["no_mac_volume_mutation"])

    def test_missing_context_allows_read_only_inspection_but_failed_write_still_counts(self):
        before, after = state(), state()
        after["clarification"] = {"question": "PRIVATE_QUESTION"}
        expected = evaluation.SCENARIOS["missing-context"][0]["expect"]
        reads = [event(1, "system_control", {"volume": 30}, operation="volume.get"),
                 event(2, "computer_audio", {"running": False}, operation="status"), event(3, "ask_user")]
        self.assertTrue(all(checks(expected, before, after, activity(*reads)).values()))
        failed_write = activity(*reads, event(4, "computer_act", status="failed"))
        self.assertEqual(failed_write["tool_failure_count"], 1)
        self.assertFalse(checks(expected, before, after, failed_write)["no_mutating_tools"])

    def test_event_summary_discards_private_fields_and_counts_fixed_metadata_only(self):
        observed = activity(event(1, "load_skill", {"id": "device-apps", "instructions": "PRIVATE_SKILL_BODY"}),
                            event(2, "computer_act", {"image_url": "PRIVATE_SCREEN", "text": "PRIVATE_TYPED"}, status="failed"),
                            event(3, "unknown_private_tool", {"private": "PRIVATE_PAYLOAD"}))
        encoded = json.dumps(observed)
        self.assertNotIn("PRIVATE", encoded)
        self.assertEqual(observed["skills"], ["device-apps"])
        self.assertEqual(observed["tool_failures"], {"computer_act": 1})


class IntentRunnerTests(unittest.TestCase):
    def test_dry_plan_never_constructs_client_or_echoes_custom_request(self):
        output = io.StringIO()
        with patch.object(evaluation, "Studio", side_effect=AssertionError("No network")), contextlib.redirect_stdout(output):
            self.assertEqual(evaluation.main(["--request", "PRIVATE_CUSTOM_REQUEST"]), 0)
        evidence = json.loads(output.getvalue())
        self.assertEqual(evidence["status"], "not_run")
        self.assertNotIn("PRIVATE_CUSTOM_REQUEST", output.getvalue())

    def test_scenario_stops_at_first_failed_step_without_automatic_restore_or_clear(self):
        output = io.StringIO()
        client = Mock()
        with patch.object(evaluation, "Studio", return_value=client), \
             patch.object(evaluation, "run_step", return_value={"status": "failed", "manual_inspection_required": None}) as run, \
             contextlib.redirect_stdout(output):
            self.assertEqual(evaluation.main(["--scenario", "speaker", "--run"]), 1)
        self.assertEqual(run.call_count, 1)
        client.call.assert_not_called()
        self.assertEqual(len(json.loads(output.getvalue())["results"]), 1)

    def test_missing_context_run_requires_explicit_clear_flag(self):
        client, output = Mock(), io.StringIO()
        with patch.object(evaluation, "Studio", return_value=client), contextlib.redirect_stdout(output):
            self.assertEqual(evaluation.main(["--scenario", "missing-context", "--run"]), 1)
        client.call.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["error"], "missing_context_scenario_requires_explicit_clear_context")

    def test_mismatched_job_identity_stops_before_any_following_request(self):
        client = Mock()
        after = state()
        after["agent"]["job_id"] = "c" * 32
        client.call.side_effect = [state(), {"job_id": JOB}, after]
        with self.assertRaisesRegex(evaluation.EvaluationError, "job_superseded"):
            evaluation.run_step(client, evaluation.SCENARIOS["mac"][0], 150, .5)
        self.assertEqual([call.args[0] for call in client.call.call_args_list],
                         ["/api/state", "/api/request", "/api/state"])

    def test_run_step_ignores_other_jobs_events_and_produces_only_sanitized_evidence(self):
        before, after = state(), state()
        after["speaker_volume"]["volume"] = 50
        after["budget"] = {"calls": 12, "charged_or_reserved_dollars": 1.125}
        after["response"] = {"text": "PRIVATE_RESPONSE"}
        after["events"] = [event(1, "load_skill", skill="hardware-controls"),
                           event(2, "speaker_control", {"volume": 50}, operation="delta"),
                           event(3, "system_control", {"volume": 99}, operation="volume.set", job_id="c" * 32)]
        client = Mock()
        client.call.side_effect = [before, {"job_id": JOB}, after]
        result = evaluation.run_step(client, evaluation.SCENARIOS["speaker"][1], 150, .5)
        self.assertEqual(result["status"], "passed_automated_checks")
        self.assertEqual(result["budget_delta"], {"calls": 2, "charged_or_reserved_dollars": .125})
        self.assertNotIn("system_control", result["activity"]["tools"])
        self.assertNotIn("PRIVATE_RESPONSE", json.dumps(result))

    def test_client_rejects_external_origins_and_credentials_before_network(self):
        for url in ("https://external.invalid", "http://127.0.0.1:8787/path", "http://user@localhost:8787", "http://localhost:8787/?secret=x"):
            with self.subTest(url=url), patch.object(evaluation.urllib.request, "build_opener") as opened:
                with self.assertRaises(evaluation.EvaluationError):
                    evaluation.Studio(url)
                opened.assert_not_called()

    def test_client_fetches_csrf_and_sends_same_origin_header_with_mutation(self):
        opener = Mock()
        token, accepted = Mock(), Mock()
        token.__enter__ = Mock(return_value=token); token.__exit__ = Mock(return_value=False)
        accepted.__enter__ = Mock(return_value=accepted); accepted.__exit__ = Mock(return_value=False)
        token.read.return_value = b'{"token":"synthetic-token"}'
        accepted.read.return_value = json.dumps({"job_id": JOB}).encode()
        opener.open.side_effect = [token, accepted]
        with patch.object(evaluation.urllib.request, "build_opener", return_value=opener):
            client = evaluation.Studio("http://127.0.0.1:8787")
        self.assertEqual(client.call("/api/request", {"text": "Synthetic"}), {"job_id": JOB})
        requests = [call.args[0] for call in opener.open.call_args_list]
        self.assertEqual(requests[0].full_url, "http://127.0.0.1:8787/api/csrf")
        self.assertEqual(requests[1].get_header("X-csrf-token"), "synthetic-token")
        self.assertEqual(requests[1].get_header("Origin"), client.origin)


if __name__ == "__main__":
    unittest.main()
