"""Device transaction/recovery tests; fake workers and software display only."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modulate.device_activation import DeviceActivation, digest
from modulate.game_runtime import GameError


def game(title="First", color="#112233"):
    return {"kind": "game", "title": title, "code": "function init(){return {}}",
            "controls": ["encoder"], "assets": {"sprites": {
                "pixel": {"width": 1, "height": 1, "palette": [color], "pixels": [[0]]}}}}


def control():
    return {"kind": "control", "title": "Volume", "target": "paired-session",
            "bindings": [{"control": "encoder", "action": "volume.delta", "scale": 2}]}


class FakeGame:
    instances = []

    def __init__(self, package):
        self.package = copy.deepcopy(package)
        self.closed = self.fail = False
        self.frame = {"state": {"ticks": 0}, "commands": [
            {"op": "clear", "color": package["assets"]["sprites"]["pixel"]["palette"][0]}]}
        self.initial_frame = copy.deepcopy(self.frame)
        self.instances.append(self)

    def step(self, input, dt):
        if self.fail or self.closed:
            raise RuntimeError("generated worker failed with private diagnostics")
        self.frame["state"]["ticks"] += 1
        return copy.deepcopy(self.frame)

    def close(self):
        self.closed = True


class Display:
    def __init__(self):
        self.calls = []
        self.visible = None
        self.fail_once = False

    def __call__(self, image):
        self.visible = image.getpixel((0, 0))
        self.calls.append(self.visible)
        if self.fail_once:
            self.fail_once = False
            raise OSError("partial display write")


class DeviceActivationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.now = 100.0
        self.available = ["encoder", "button_a", "button_b"]
        self.target = "paired-session"
        self.display = Display()
        FakeGame.instances = []
        patcher = patch("modulate.device_activation.Game", FakeGame)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("modulate.device_activation.verify", return_value={"passed": True})
        self.verify = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("modulate.device_activation.time.monotonic", side_effect=lambda: self.now)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = self.reopen()
        self.counter = 0

    def reopen(self):
        manager = DeviceActivation(self.directory, self.display, lambda: self.available, lambda: self.target)
        self.addCleanup(manager.close)
        return manager

    def transaction(self, package, base=None):
        self.counter += 1
        return {"id": f"transaction-{self.counter}", "revision": digest(package),
                "base_revision": self.manager.snapshot()["revision"] if base is None else base,
                "phase": "stage", "package": copy.deepcopy(package)}

    def phase(self, message, phase):
        return {key: value for key, value in {**message, "phase": phase}.items() if key != "package"}

    def activate(self, package):
        message = self.transaction(package)
        self.assertEqual(self.manager.process(message)["ack"]["phase"], "ready")
        self.assertEqual(self.manager.process(self.phase(message, "commit"))["ack"]["phase"], "activated")
        self.assertEqual(self.manager.process(self.phase(message, "confirmed"))["ack"]["phase"], "confirmed")
        return message

    def saved(self):
        return json.loads(self.manager.path.read_text())

    def test_stage_checks_offscreen_and_ack_keeps_base_revision(self):
        first = self.activate(game())
        calls = len(self.display.calls)
        second = self.transaction(game("Second", "#445566"))
        snapshot = self.manager.process(second)
        self.assertEqual(snapshot["revision"], first["revision"])
        self.assertEqual(snapshot["ack"], {"id": second["id"], "revision": second["revision"], "phase": "ready"})
        self.assertEqual(len(self.display.calls), calls)
        self.assertEqual(self.saved()["active"]["revision"], first["revision"])
        self.assertEqual(self.verify.call_count, 2)

    def test_commit_persists_intent_before_present_and_confirmation_closes_old_worker(self):
        first = self.activate(game())
        old = FakeGame.instances[-1]
        second = self.transaction(game("Second", "#445566"))
        self.manager.process(second)
        present = self.manager.present

        def verify_intent(image):
            self.assertEqual(self.saved()["active"]["revision"], first["revision"])
            self.assertEqual(self.saved()["intent"]["revision"], second["revision"])
            present(image)

        with patch.object(self.manager, "present", side_effect=verify_intent):
            snapshot = self.manager.process(self.phase(second, "commit"))
        self.assertEqual(snapshot["revision"], second["revision"])
        self.assertFalse(old.closed)
        self.manager.process(self.phase(second, "confirmed"))
        self.assertTrue(old.closed)
        self.assertEqual(self.saved()["active"]["revision"], second["revision"])
        self.assertEqual(self.saved()["previous"]["revision"], first["revision"])
        self.assertIsNone(self.saved()["intent"])

    def test_bad_digest_and_unavailable_controls_leave_active_untouched(self):
        first = self.activate(game())
        for malformed in (True, False):
            message = self.transaction(game("Bad"))
            if malformed:
                message["revision"] = "0" * 64
            else:
                self.available = []
            snapshot = self.manager.process(message)
            self.assertEqual(snapshot["ack"]["phase"], "failed")
            self.assertEqual(snapshot["revision"], first["revision"])
        self.assertEqual(self.saved()["active"]["revision"], first["revision"])

    def test_fixed_device_verification_failure_does_not_create_candidate_worker(self):
        self.verify.return_value = {"passed": False, "errors": ["bad code"]}
        snapshot = self.manager.process(self.transaction(game()))
        self.assertEqual(snapshot["ack"]["phase"], "failed")
        self.assertEqual(FakeGame.instances, [])
        self.assertEqual(self.display.calls, [])

    def test_stale_base_and_foreign_commit_cannot_replace_current_program(self):
        first = self.activate(game())
        stale = self.transaction(game("Stale"), base="0" * 64)
        self.assertEqual(self.manager.process(stale)["ack"]["phase"], "failed")
        staged = self.transaction(game("Second"))
        self.manager.process(staged)
        foreign = {**self.phase(staged, "commit"), "id": "foreign"}
        self.assertEqual(self.manager.process(foreign)["revision"], first["revision"])
        self.assertEqual(self.manager.snapshot()["ack"]["phase"], "ready")

    def test_duplicate_phases_are_idempotent_and_do_not_extend_deadline(self):
        staged = self.transaction(game())
        self.manager.process(staged)
        self.now += 11
        self.manager.process(staged)
        self.assertEqual(self.verify.call_count, 1)
        self.now += 1
        snapshot = self.manager.process(staged)
        self.assertEqual(snapshot["ack"]["phase"], "failed")
        self.assertIsNone(snapshot["revision"])
        self.assertTrue(FakeGame.instances[-1].closed)

    def test_commit_timeout_restores_base_and_retains_matching_failure(self):
        first = self.activate(game())
        second = self.transaction(game("Second", "#445566"))
        self.manager.process(second)
        self.manager.process(self.phase(second, "commit"))
        self.now += 12
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot["revision"], first["revision"])
        self.assertEqual(snapshot["failure"]["revision"], second["revision"])
        self.assertEqual(snapshot["failure"]["restored_revision"], first["revision"])
        self.assertEqual(self.display.visible, (17, 34, 51))
        self.assertEqual(self.saved()["failure"], snapshot["failure"])

    def test_restart_after_commit_restores_base_and_reports_uncertain_candidate(self):
        first = self.activate(game())
        second = self.transaction(game("Second", "#445566"))
        self.manager.process(second)
        self.manager.process(self.phase(second, "commit"))
        recovered = self.reopen()
        snapshot = recovered.snapshot()
        self.assertEqual(snapshot["revision"], first["revision"])
        self.assertEqual(snapshot["failure"]["revision"], second["revision"])
        self.assertEqual(snapshot["failure"]["restored_revision"], first["revision"])
        self.assertIsNone(self.saved()["intent"])

    def test_first_unconfirmed_activation_restart_has_no_preloaded_game(self):
        staged = self.transaction(game())
        self.manager.process(staged)
        self.manager.process(self.phase(staged, "commit"))
        recovered = self.reopen()
        self.assertIsNone(recovered.snapshot()["revision"])
        self.assertIsNone(recovered.snapshot()["failure"]["restored_revision"])

    def test_partial_display_failure_restores_prior_frame_and_fails_ack(self):
        first = self.activate(game())
        second = self.transaction(game("Second", "#445566"))
        self.manager.process(second)
        self.display.fail_once = True
        snapshot = self.manager.process(self.phase(second, "commit"))
        self.assertEqual(snapshot["revision"], first["revision"])
        self.assertEqual(snapshot["ack"]["phase"], "failed")
        self.assertEqual(self.display.visible, (17, 34, 51))

    def test_confirmation_write_failure_restores_previous_and_durable_base(self):
        first = self.activate(game())
        second = self.transaction(game("Second", "#445566"))
        self.manager.process(second)
        self.manager.process(self.phase(second, "commit"))
        with patch("modulate.device_activation.os.replace", side_effect=OSError("disk full")):
            snapshot = self.manager.process(self.phase(second, "confirmed"))
        self.assertEqual(snapshot["revision"], first["revision"])
        self.assertEqual(snapshot["ack"]["phase"], "failed")
        self.assertEqual(self.saved()["active"]["revision"], first["revision"])
        self.assertEqual(list(self.directory.glob(".device-active-*")), [])

    def test_interrupt_after_atomic_confirmation_reconciles_committed_revision(self):
        first = self.activate(game())
        second = self.transaction(game("Second", "#445566"))
        self.manager.process(second)
        self.manager.process(self.phase(second, "commit"))
        replace = os.replace

        def replace_then_interrupt(*args):
            replace(*args)
            raise KeyboardInterrupt()

        with patch("modulate.device_activation.os.replace", side_effect=replace_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.manager.process(self.phase(second, "confirmed"))
        self.assertEqual(self.manager.snapshot()["revision"], second["revision"])
        self.assertEqual(self.manager.snapshot()["ack"]["phase"], "confirmed")
        self.assertEqual(self.saved()["active"]["revision"], second["revision"])

    def test_runtime_failure_restores_previous_and_survives_restart_until_exact_ack(self):
        first = self.activate(game())
        second = self.activate(game("Second", "#445566"))
        FakeGame.instances[-1].fail = True
        self.assertIsNone(self.manager.tick({}, 0.03))
        failure = self.manager.snapshot()["failure"]
        self.assertEqual((failure["revision"], failure["restored_revision"]), (second["revision"], first["revision"]))
        self.assertNotIn("private", json.dumps(self.manager.snapshot()))
        recovered = self.reopen()
        self.assertEqual(recovered.snapshot()["failure"], failure)
        self.assertFalse(recovered.acknowledge_failure({"revision": "0" * 64, "restored_revision": first["revision"]}))
        self.assertIsNotNone(recovered.snapshot()["failure"])
        self.assertTrue(recovered.acknowledge_failure({key: failure[key] for key in ("revision", "restored_revision")}))
        self.assertIsNone(recovered.snapshot()["failure"])
        self.assertIsNone(self.saved()["failure"])

    def test_runtime_diagnostic_distinguishes_step_render_and_present_without_exception_text(self):
        for stage, category in (("step", "worker_deadline"), ("render", "render_error"), ("present", "display_error")):
            with self.subTest(stage=stage):
                self.activate(control())
                self.activate(game("Diagnostic " + stage))
                active = self.manager._active
                target, method = ((active.game, "step") if stage == "step" else
                                  (active.renderer, "render") if stage == "render" else (self.manager, "present"))
                original = getattr(target, method)
                calls = 0

                def fail_once(*args):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        self.now += 0.375
                        if stage == "step":
                            raise GameError("Game worker exceeded its wall-clock deadline")
                        raise RuntimeError("private generated content must not appear")
                    return original(*args)

                with patch.object(target, method, side_effect=fail_once), \
                        self.assertLogs("modulate.device_activation", level="ERROR") as logs:
                    self.assertIsNone(self.manager.tick({}, 0.03))
                diagnostic = f"stage={stage} category={category} elapsed_ms=375"
                self.assertIn(diagnostic, logs.output[0])
                self.assertIn(diagnostic, self.manager.snapshot()["failure"]["error"])
                self.assertNotIn("private", str(logs.output) + json.dumps(self.saved()))
                self.assertEqual(self.reopen().snapshot()["failure"], self.manager.snapshot()["failure"])
                self.assertTrue(self.manager.acknowledge_failure(self.manager.snapshot()["failure"]))

    def test_runtime_error_categories_are_allowlisted_and_timing_is_bounded(self):
        self.activate(game())
        self.assertEqual(self.manager._failure_category("step", GameError("InternalError: interrupted\n private")),
                         "engine_interrupt")
        self.assertEqual(self.manager._failure_category("step", GameError("private arbitrary program error")),
                         "game_error")
        self.assertEqual(self.manager._failure_category("step", GameError("Game worker exited without a result")),
                         "worker_exit")

        def delayed_failure(*args):
            self.now += 1000
            raise RuntimeError("private")

        with patch.object(self.manager._active.game, "step", side_effect=delayed_failure), \
                self.assertLogs("modulate.device_activation", level="ERROR"):
            self.manager.tick({}, 0.03)
        self.assertIn("elapsed_ms=60000", self.manager.snapshot()["failure"]["error"])

    def test_changed_saved_source_fails_integrity_before_starting_any_worker(self):
        self.activate(game())
        record = self.saved()
        record["active"]["package"]["code"] = "tampered"
        self.manager.path.write_text(json.dumps(record))
        count = len(FakeGame.instances)
        recovered = self.reopen()
        self.assertIsNone(recovered.snapshot()["revision"])
        self.assertEqual(len(FakeGame.instances), count)
        self.assertIn("could not", recovered.snapshot()["error"])

    def test_boot_missing_controls_preserves_both_durable_packages_without_workers(self):
        first = self.activate(game())
        second = self.activate(game("Second"))
        self.manager.close()
        before = self.manager.path.read_bytes()
        workers, verifies, presents = len(FakeGame.instances), self.verify.call_count, len(self.display.calls)
        self.available = ["button_a", "button_b"]
        recovered = self.reopen()
        snapshot = recovered.snapshot()
        self.assertEqual((snapshot["revision"], snapshot["title"], snapshot["kind"]),
                         (second["revision"], "Second", "game"))
        self.assertTrue(snapshot["suspended"])
        self.assertEqual(snapshot["suspension_reason"], "required_controls_unavailable")
        self.assertIsNone(snapshot["failure"])
        for _ in range(50):
            self.now += 0.01
            self.assertIsNone(recovered.tick({"encoder_delta": 100}, 0.03))
        self.assertEqual((len(FakeGame.instances), self.verify.call_count, len(self.display.calls)),
                         (workers, verifies, presents))
        self.assertEqual(self.manager.path.read_bytes(), before)
        self.assertEqual(self.saved()["previous"]["revision"], first["revision"])
        recovered.close()
        self.assertEqual(self.manager.path.read_bytes(), before)
        self.assertTrue(self.reopen().snapshot()["suspended"])

    def test_suspended_retry_is_bounded_and_resumes_only_after_independent_verification(self):
        active = self.activate(game())
        self.manager.close()
        self.available = []
        recovered = self.reopen()
        with patch.object(recovered, "_prepare", wraps=recovered._prepare) as prepare:
            self.now += 1
            for _ in range(20):
                recovered.tick({}, 0.03)
            self.assertEqual(prepare.call_count, 1)
            self.available = ["encoder"]
            self.now += 0.9
            recovered.tick({}, 0.03)
            self.assertTrue(recovered.snapshot()["suspended"])
            self.now += 0.1
            self.assertIsNone(recovered.tick({"encoder_delta": 100}, 0.03))
            self.assertEqual(prepare.call_count, 2)
        self.assertFalse(recovered.snapshot()["suspended"])
        self.assertIsNone(recovered.snapshot()["error"])
        self.assertEqual(recovered.snapshot()["revision"], active["revision"])
        self.assertEqual(FakeGame.instances[-1].frame["state"]["ticks"], 0)
        self.assertEqual(recovered.tick({"encoder_delta": 0}, 0.03)["state"]["ticks"], 1)
        self.assertEqual(self.verify.call_count, 2)

    def test_suspended_program_accepts_verified_adaptation_and_preserves_predecessor(self):
        self.activate(game())
        active = self.activate(game("Second"))
        self.manager.close()
        self.available = []
        self.manager = self.reopen()
        replacement = game("Adapted")
        replacement["controls"] = []
        self.activate(replacement)
        self.assertFalse(self.manager.snapshot()["suspended"])
        self.assertEqual(self.saved()["previous"]["revision"], active["revision"])
        self.assertEqual(self.manager.tick({}, .03)["state"]["ticks"], 1)
        self.assertEqual(self.reopen().snapshot()["title"], "Adapted")

    def test_failed_adaptation_restores_suspended_predecessor_on_abort_and_restart(self):
        active = self.activate(game())
        self.manager.close()
        self.available = []
        self.manager = self.reopen()
        replacement = game("Adapted")
        replacement["controls"] = []
        message = self.transaction(replacement)
        self.manager.process(message)
        self.manager.process(self.phase(message, "commit"))
        self.assertFalse(self.manager.snapshot()["suspended"])
        snapshot = self.manager.process(self.phase(message, "abort"))
        self.assertTrue(snapshot["suspended"])
        self.assertEqual(snapshot["revision"], active["revision"])
        self.assertIsNone(self.manager.tick({}, .03))
        recovered = self.reopen()
        self.assertTrue(recovered.snapshot()["suspended"])
        self.assertEqual(recovered.snapshot()["revision"], active["revision"])

    def test_suspended_base_cannot_resume_while_replacement_is_staged(self):
        self.activate(game())
        self.manager.close()
        self.available = []
        self.manager = self.reopen()
        replacement = game("Adapted")
        replacement["controls"] = []
        message = self.transaction(replacement)
        self.manager.process(message)
        self.available = ["encoder"]
        self.now += 2
        count = len(FakeGame.instances)
        self.assertIsNone(self.manager.tick({}, .03))
        self.assertEqual(len(FakeGame.instances), count)
        self.manager.process(self.phase(message, "commit"))
        self.manager.process(self.phase(message, "confirmed"))
        self.assertFalse(self.manager.snapshot()["suspended"])
        self.assertEqual(self.manager.snapshot()["title"], "Adapted")

    def test_missing_hardware_does_not_hide_structurally_invalid_saved_package(self):
        fallback = game("Fallback")
        fallback["controls"] = []
        first = self.activate(fallback)
        self.activate(game("Broken"))
        self.manager.close()
        record = self.saved()
        record["active"]["package"]["code"] = ""
        record["active"]["revision"] = digest(record["active"]["package"])
        self.manager.path.write_text(json.dumps(record))
        self.available = []
        recovered = self.reopen()
        self.assertFalse(recovered.snapshot()["suspended"])
        self.assertEqual(recovered.snapshot()["revision"], first["revision"])
        self.assertEqual(recovered.snapshot()["failure"]["revision"], record["active"]["revision"])

    def test_resume_verification_or_presentation_failure_still_rolls_back(self):
        for failure in ("verification", "presentation"):
            with self.subTest(failure=failure):
                fallback = game("Fallback")
                fallback["controls"] = []
                first = self.activate(fallback)
                second = self.activate(game("Second"))
                self.manager.close()
                self.available = []
                recovered = self.reopen()
                self.available = ["encoder"]
                if failure == "verification":
                    self.verify.side_effect = lambda package: {"passed": package["title"] != "Second"}
                else:
                    self.display.fail_once = True
                self.now += 1
                self.assertIsNone(recovered.tick({}, 0.03))
                self.assertFalse(recovered.snapshot()["suspended"])
                self.assertEqual(recovered.snapshot()["revision"], first["revision"])
                self.assertEqual(recovered.snapshot()["failure"]["revision"], second["revision"])
                self.assertEqual(self.saved()["active"]["revision"], first["revision"])
                self.verify.side_effect = None
                self.assertTrue(recovered.acknowledge_failure(recovered.snapshot()["failure"]))
                self.manager = recovered

    def test_interrupted_commit_recovery_retains_suspended_base_and_failure_ack(self):
        first = self.activate(game())
        second = self.transaction(game("Second"))
        self.manager.process(second)
        self.manager.process(self.phase(second, "commit"))
        self.available = []
        recovered = self.reopen()
        snapshot = recovered.snapshot()
        self.assertTrue(snapshot["suspended"])
        self.assertEqual(snapshot["revision"], first["revision"])
        self.assertEqual(snapshot["failure"]["revision"], second["revision"])
        self.assertEqual(snapshot["failure"]["restored_revision"], first["revision"])
        self.assertTrue(recovered.acknowledge_failure(snapshot["failure"]))
        self.assertEqual(self.saved()["active"]["revision"], first["revision"])
        self.assertIsNone(self.saved()["intent"])
        self.assertIsNone(self.saved()["failure"])

    def test_live_control_loss_closes_worker_before_any_step_without_changing_disk(self):
        active = self.activate(game())
        worker = FakeGame.instances[-1]
        before = self.manager.path.read_bytes()
        self.available = []
        self.assertIsNone(self.manager.tick({"encoder_delta": 999}, 0.03))
        self.assertTrue(worker.closed)
        self.assertEqual(worker.frame["state"]["ticks"], 0)
        self.assertTrue(self.manager.snapshot()["suspended"])
        self.assertEqual(self.manager.snapshot()["revision"], active["revision"])
        self.assertEqual(self.manager.path.read_bytes(), before)

    def test_control_package_suspends_and_resumes_without_a_game_worker(self):
        active = self.activate(control())
        self.manager.close()
        self.available = []
        recovered = self.reopen()
        self.assertEqual(recovered.snapshot()["kind"], "control")
        self.assertTrue(recovered.snapshot()["suspended"])
        self.available = ["encoder"]
        self.now += 1
        recovered.tick({}, 0.03)
        self.assertFalse(recovered.snapshot()["suspended"])
        self.assertEqual(recovered.snapshot()["revision"], active["revision"])
        self.assertEqual(FakeGame.instances, [])

    def test_control_binding_is_strict_and_has_no_host_side_effect(self):
        for mutate in (lambda p: p.update(target="other-session"),
                       lambda p: p["bindings"][0].update(action="shell.run"),
                       lambda p: p["bindings"][0].update(scale=True),
                       lambda p: p["bindings"][0].update(scale=11),
                       lambda p: p["bindings"][0].update(scale=0),
                       lambda p: p.update(code="arbitrary")):
            package = control()
            mutate(package)
            self.assertEqual(self.manager.process(self.transaction(package))["ack"]["phase"], "failed")
        valid = control()
        valid["bindings"][0]["scale"] = -10
        self.activate(valid)
        self.assertEqual(self.manager.snapshot()["kind"], "control")
        self.assertIsNone(self.manager.tick({"encoder_delta": 10}, 0.03))
        self.assertEqual(FakeGame.instances, [])

    def test_pairing_revoked_between_stage_and_commit_rejects_candidate(self):
        staged = self.transaction(control())
        self.manager.process(staged)
        self.target = None
        snapshot = self.manager.process(self.phase(staged, "commit"))
        self.assertEqual(snapshot["ack"]["phase"], "failed")
        self.assertIsNone(snapshot["revision"])

    def test_confirmation_before_commit_and_abort_preserve_base(self):
        first = self.activate(game())
        for phase in ("confirmed", "abort"):
            staged = self.transaction(game(phase))
            self.manager.process(staged)
            snapshot = self.manager.process(self.phase(staged, phase))
            self.assertEqual(snapshot["revision"], first["revision"])
            self.assertEqual(snapshot["ack"]["phase"], "failed")

    def test_tick_presents_valid_frame_and_snapshot_cannot_mutate_state(self):
        self.activate(game())
        frame = self.manager.tick({}, 0.03)
        self.assertEqual(frame["state"]["ticks"], 1)
        snapshot = self.manager.snapshot()
        snapshot["ack"]["phase"] = "malicious"
        self.assertEqual(self.manager.snapshot()["ack"]["phase"], "confirmed")


if __name__ == "__main__":
    unittest.main()
