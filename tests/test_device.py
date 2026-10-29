"""Synthetic controller and host protocol checks; no network, mic, GPIO or cloud."""

from concurrent.futures import ThreadPoolExecutor
import copy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modulate.agent import AgentError, digest
from modulate.agent_provider import AgentProvider
from modulate.controls import neutral_input
from modulate.device import Controller
from modulate.device_activation import DeviceActivation
from modulate.device_transport import TransportError, save_private
from modulate.product import Product


class Button:
    def __init__(self):
        self.current = True
        self.error = False

    @property
    def value(self):
        if self.error:
            raise OSError("fake disconnected GPIO")
        return self.current


class ControllerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.buttons = [Button(), Button()]
        for name in ("Companion", "Screen", "Controls", "DeviceActivation", "VoiceListener", "Speaker"):
            patcher = patch("modulate.device." + name)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name, mock.return_value)
        self.Screen.buttons = self.buttons
        self.Speaker.snapshot.return_value = {"available": False, "state": "stopped", "error": None}
        self.Controls.capabilities.return_value = {"controls": ["encoder", "button_a", "button_b"],
                                                  "devices": [], "warnings": []}
        self.DeviceActivation.snapshot.return_value = {"revision": None, "kind": None, "ack": None}
        self.controller = Controller(self.directory, "synthetic-enrollment")
        self.controller.last_response = time.monotonic()

    def offer(self):
        self.controller.host = {"pairing": {"code": "12345678", "expires_at": time.time() + 120}}

    def test_voice_cancel_discards_unsent_request_without_network_action(self):
        self.controller.request('Make a game')
        self.assertTrue(self.controller.cancel_request())
        self.assertTrue(self.controller.requests.empty())
        self.assertIsNone(self.controller.build)
        self.Companion.post.assert_not_called()

    def test_voice_cancel_can_dismiss_exact_pending_question(self):
        self.controller.host={'clarification':{'job_id':'f'*32,'question':'What should change?'}}
        self.assertTrue(self.controller.cancel_request())
        self.assertEqual(self.controller.cancellations.get_nowait(),'f'*32)

    def test_busy_voice_cancel_sends_exact_heard_job_not_a_later_job(self):
        self.controller.build={'job_id':'a'*32,'awaiting_response':False}
        self.assertTrue(self.controller.cancel_request())
        self.controller.build={'job_id':'b'*32,'awaiting_response':False}
        self.Companion.post.side_effect=[{'cancelled':False},{'wake':True,'agent_running':True}]
        self.controller._network_step()
        self.assertEqual(self.Companion.post.call_args_list[0].args,('cancel',{'job_id':'a'*32}))
        self.assertEqual(self.controller.build['job_id'],'b'*32)

    def test_cancel_during_request_post_is_forwarded_after_acceptance(self):
        self.controller.request('Make a game')
        self.controller.requests.get_nowait()
        self.assertTrue(self.controller.cancel_request())
        self.assertTrue(self.controller.cancel_when_accepted)
        self.controller.requests.put_nowait('Make a game')
        self.Companion.post.side_effect=[{'wake':True}, {'accepted':True,'job_id':'a'*32,'job_sequence':1}]
        self.controller._network_step()
        self.assertEqual(self.controller.cancellations.get_nowait(),'a'*32)
        self.assertFalse(self.controller.cancel_when_accepted)

    def test_first_heartbeat_uses_restored_revision_before_render_loop(self):
        revision = "a" * 64
        failure = {"revision": "b" * 64, "restored_revision": revision,
                   "error": "Synthetic interrupted activation recovery"}
        for retained_failure in (None, failure):
            with self.subTest(retained_failure=retained_failure is not None):
                self.DeviceActivation.snapshot.return_value = {
                    "revision": revision, "kind": "game", "title": "Restored synthetic game",
                    "ack": None, "failure": retained_failure, "error": None,
                }
                self.Companion.post.return_value = {"wake": False, "activation": None}
                controller = Controller(self.directory, "synthetic-enrollment")
                controller._network_step()
                action, packet = self.Companion.post.call_args.args
                self.assertEqual(action, "heartbeat")
                self.assertEqual(packet["revision"], revision)
                self.assertEqual(controller.encoder_revision, revision)
                self.assertEqual(packet["input"]["encoder_delta"], 0)
                self.assertEqual(packet.get("failure"), retained_failure)
                self.DeviceActivation.tick.assert_not_called()
                self.VoiceListener.start.assert_not_called()

    def test_big_logical_game_buttons_cannot_pair_or_trigger_ptt(self):
        sample = {**neutral_input(), "button_a": True, "button_b": True}
        self.controller._handle_buttons(sample, 10)
        self.controller._handle_buttons(sample, 12)
        self.VoiceListener.request_ptt.assert_not_called()
        self.offer()
        self.controller._handle_buttons(sample, 13)
        self.controller._handle_buttons(sample, 15)
        self.assertTrue(self.controller.actions.empty())

    def test_pairing_requires_tft_release_after_offer_then_a_fresh_press(self):
        self.offer()
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 10)
        self.controller._handle_buttons(neutral_input(), 11)
        self.assertTrue(self.controller.actions.empty())
        self.buttons[0].current = True
        self.controller._handle_buttons(neutral_input(), 12)
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 13)
        self.assertEqual(self.controller.actions.get_nowait(), "12345678")
        self.controller._handle_buttons(neutral_input(), 14)
        self.assertTrue(self.controller.actions.empty())

    def test_gpio_failure_does_not_count_as_a_physical_release(self):
        self.offer()
        self.controller._handle_buttons(neutral_input(), 10)
        self.buttons[0].error = True
        self.controller._handle_buttons(neutral_input(), 11)
        self.buttons[0].error, self.buttons[0].current = False, False
        self.controller._handle_buttons(neutral_input(), 12)
        self.assertTrue(self.controller.actions.empty())

    def test_physical_tft_chord_triggers_one_ptt_and_suppresses_game_buttons(self):
        self.buttons[0].current = self.buttons[1].current = False
        sample = {**neutral_input(), "button_a": True, "button_b": True}
        self.controller._handle_buttons(sample, 10)
        processed = self.controller._handle_buttons(sample, 10.75)
        self.controller._handle_buttons(sample, 12)
        self.VoiceListener.request_ptt.assert_called_once()
        self.assertFalse(processed["button_a"])
        self.assertFalse(processed["button_b"])

    def test_tft_b_declines_pairing_without_recording(self):
        self.offer()
        self.controller._handle_buttons(neutral_input(), 10)
        self.buttons[1].current = False
        self.controller._handle_buttons(neutral_input(), 11)
        self.assertEqual(self.controller.dismissed_pairing, "12345678")
        self.assertTrue(self.controller.actions.empty())
        self.VoiceListener.request_ptt.assert_not_called()

    def test_uncertain_heartbeat_discards_sent_and_inflight_encoder_turns(self):
        controller = self.controller
        controller.state = {"revision": "a" * 64, "kind": "control"}
        controller.encoder_revision = "a" * 64
        controller.encoder_pending = 3
        packets = []

        def post(action, packet):
            packets.append(copy.deepcopy(packet))
            if len(packets) == 1:
                controller.encoder_pending += 5  # Movement while HTTP is uncertain.
                raise TransportError("synthetic timeout")
            return {"wake": False}

        self.Companion.post.side_effect = post
        controller._network_step()
        controller._network_step()
        self.assertEqual([packet["input"]["encoder_delta"] for packet in packets], [3, 0])
        self.assertEqual([packet["sequence"] for packet in packets], [1, 2])

    def test_revision_change_drops_old_actions_and_stale_drawing_commands(self):
        controller = self.controller
        controller.state = {"revision": "first", "kind": "game"}
        controller.encoder_revision = "first"
        controller.encoder_pending = 7
        controller.commands = [{"op": "sprite", "id": "old_asset"}]
        controller._publish({**neutral_input(), "encoder_delta": 3}, None,
                            {"revision": "second", "kind": "game"}, "first")
        self.assertEqual(controller.encoder_pending, 0)
        self.assertEqual(controller.sample["encoder_delta"], 0)
        self.assertEqual(controller.commands, [])
        controller._publish({**neutral_input(), "encoder_delta": 2}, None,
                            {"revision": "second", "kind": "game"}, "second")
        self.assertEqual(controller.encoder_pending, 2)

    def test_recovery_ack_is_applied_before_new_activation(self):
        response = {"wake": True, "agent_running": False,
                    "failure_ack": {"revision": "failed", "restored_revision": "base"},
                    "activation": {"phase": "stage"}}
        self.controller.responses.put(response)
        self.controller._apply_responses()
        calls = self.DeviceActivation.method_calls
        self.assertEqual(calls[-2][0], "acknowledge_failure")
        self.assertEqual(calls[-1][0], "process")
        self.VoiceListener.set_enabled.assert_called_once_with(True)

    def test_response_backpressure_does_not_block_or_kill_network_worker(self):
        for index in range(8):
            self.controller.responses.put({"old": index})
        self.Companion.post.return_value = {"fresh": True}
        self.controller._network_step()
        values = [self.controller.responses.get_nowait() for _ in range(8)]
        self.assertEqual(values[-1], {"fresh": True})

    def test_pairing_save_error_is_reported_without_stopping_network(self):
        controller = self.controller
        controller.actions.put("12345678")
        controller.pairing_in_flight = True
        self.Companion.post.side_effect = [{}, {"token": "t" * 43, "session_id": "session"}, {}]
        with patch("modulate.device.save_private", side_effect=OSError("disk full")):
            controller._network_step()
        self.assertFalse(controller.pairing_in_flight)
        self.assertIn("Could not save", controller.link_state)
        controller._network_step()
        self.assertEqual(controller.link_state, "Connected to Mac")

    def test_removed_or_invalid_private_pairing_file_clears_cached_authority(self):
        grant = {"token": "t" * 43, "session_id": "session"}
        save_private(self.controller.pairing_path, grant)
        self.controller.reload_pairing()
        self.assertEqual(self.controller.pairing, grant)
        self.controller.pairing_path.unlink()
        self.controller.reload_pairing()
        self.assertEqual(self.controller.pairing, {})
        save_private(self.controller.pairing_path, {"token": "bad"})
        self.controller.reload_pairing()
        self.assertEqual(self.controller.pairing, {})

    def test_request_inflight_and_queue_limit_prevent_parallel_voice_jobs(self):
        self.controller.request_in_flight = True
        self.assertFalse(self.controller.request("first"))
        self.controller.request_in_flight = False
        self.assertTrue(self.controller.request("first"))
        self.assertFalse(self.controller.request("second"))

    def job_response(self, identifier="a" * 32, *, sequence=1, running=True, status="running", phase="coding"):
        return {"wake": True, "agent_running": running,
                "agent_state": {"job_id": identifier, "job_sequence": sequence,
                                "request_id": None, "running": running,
                                "status": status, "phase": phase, "title": "Building your idea",
                                "role": "coder", "tool": "write_package", "summary": "Synthetic progress"}}

    def test_request_latches_loading_immediately_and_old_heartbeat_cannot_dismiss_it(self):
        controller = self.controller
        self.assertTrue(controller.request("synthetic request"))
        self.assertEqual(controller.build["title"], "Request queued")
        stale = self.job_response("b" * 32, running=False, status="completed", phase="ready")
        self.Companion.post.side_effect = [stale, {"accepted": True, "job_id": "a" * 32, "job_sequence": 1}]
        controller._network_step()
        self.assertEqual(controller.build["job_id"], "a" * 32)
        controller._apply_responses()
        self.assertEqual(controller.build["job_id"], "a" * 32)
        self.VoiceListener.set_enabled.assert_called_with(True)
        self.VoiceListener.set_busy.assert_called_with(True)

    def test_false_heartbeat_during_request_submission_keeps_local_queue_latch(self):
        self.assertTrue(self.controller.request("synthetic request"))
        self.controller.responses.put({"wake": True, "agent_running": False,
                                       "agent_state": {"job_id": None, "running": False, "status": "completed"}})
        self.controller._apply_responses()
        self.assertTrue(self.controller.build["awaiting_response"])
        self.assertEqual(self.controller.build["title"], "Request queued")

    def test_only_matching_terminal_job_releases_loading_and_stale_running_cannot_resurrect_it(self):
        self.controller._update_build(self.job_response())
        self.controller._update_build(self.job_response("b" * 32, running=False, status="completed"))
        self.assertIsNotNone(self.controller.build)
        self.controller._update_build(self.job_response(running=False, status="completed", phase="ready"))
        self.assertIsNone(self.controller.build)
        self.controller._update_build(self.job_response())
        self.assertIsNone(self.controller.build)

    def test_cancelling_job_stays_busy_until_worker_reports_terminal_state(self):
        self.controller._update_build(self.job_response())
        self.controller._update_build(self.job_response(running=True, status="running", phase="cancelled"))
        self.assertEqual(self.controller.build["phase"], "cancelled")
        self.controller._update_build(self.job_response(running=False, status="cancelled", phase="cancelled"))
        self.assertIsNone(self.controller.build)
        self.assertEqual(self.controller._feedback_card()["title"], "Build cancelled")
        self.assertNotIn("Previous program", self.controller._feedback_card()["detail"])

    def test_newer_job_recovers_a_missed_terminal_and_rejects_old_or_equal_different_jobs(self):
        controller = self.controller
        controller._update_build(self.job_response(sequence=4))
        controller._update_build(self.job_response("b" * 32, sequence=5))
        self.assertEqual(controller.build["job_id"], "b" * 32)
        for identifier, sequence in (("a" * 32, 4), ("c" * 32, 5)):
            controller._update_build(self.job_response(identifier, sequence=sequence, running=False, status="completed"))
            self.assertEqual(controller.build["job_id"], "b" * 32)
        controller._update_build(self.job_response("b" * 32, sequence=5, running=False, status="completed"))
        self.assertIsNone(controller.build)

    def test_newer_terminal_recovers_missed_job_without_stale_running_disabling_voice(self):
        controller = self.controller
        controller._update_build(self.job_response(sequence=4))
        controller.responses.put(self.job_response("b" * 32, sequence=5, running=False, status="completed"))
        controller._apply_responses()
        self.assertIsNone(controller.build)
        controller.responses.put(self.job_response(sequence=4))
        controller._apply_responses()
        self.assertFalse(controller._busy())
        self.assertIsNone(controller.build)
        self.VoiceListener.set_enabled.assert_called_with(True)

    def test_unconfirmed_local_request_ignores_even_newer_heartbeat_until_post_returns(self):
        self.assertTrue(self.controller.request("synthetic request"))
        self.controller._update_build(self.job_response("b" * 32, sequence=99))
        self.assertTrue(self.controller.build["awaiting_response"])
        self.assertIsNone(self.controller.build["job_id"])

    def test_invalid_job_sequences_do_not_supersede_a_running_job(self):
        self.controller._update_build(self.job_response(sequence=4))
        for sequence in (-1, True, "5", None):
            with self.subTest(sequence=sequence):
                self.controller._update_build(self.job_response("b" * 32, sequence=sequence))
                self.assertEqual(self.controller.build["job_id"], "a" * 32)

    def test_busy_tft_chord_does_not_open_microphone(self):
        self.controller._update_build(self.job_response())
        self.buttons[0].current = self.buttons[1].current = False
        self.controller._handle_buttons(neutral_input(), 10)
        self.controller._handle_buttons(neutral_input(), 10.8)
        self.VoiceListener.request_ptt.assert_not_called()
        self.assertEqual(self.controller._feedback_card()["title"], "Working")

    def test_request_http_failure_has_visible_feedback_without_an_eternal_loading_latch(self):
        self.assertTrue(self.controller.request("synthetic request"))
        self.Companion.post.side_effect = [{"wake": True, "agent_running": False},
                                          TransportError("Synthetic request rejected")]
        with patch("modulate.device.time.monotonic", return_value=100):
            self.controller._network_step()
            self.assertIsNone(self.controller.build)
            self.assertEqual(self.controller._feedback_card()["title"], "Request not confirmed")
        with patch("modulate.device.time.monotonic", return_value=103.9):
            self.assertIsNotNone(self.controller._feedback_card())
        with patch("modulate.device.time.monotonic", return_value=104):
            self.assertIsNone(self.controller._feedback_card())

    def test_disconnected_build_card_reports_unknown_without_animated_progress(self):
        self.controller._update_build(self.job_response())
        self.controller.last_response = 90
        with patch("modulate.device.time.monotonic", return_value=100):
            self.controller.draw_processing()
        self.assertIn("Connection lost", self.controller.status_key)
        self.assertIn("Build status unknown", self.controller.status_key)
        self.assertEqual(self.controller.status_key[-1], -1)
        draws = self.Screen.display.image.call_count
        with patch("modulate.device.time.monotonic", return_value=105):
            self.controller.draw_processing()
        self.assertEqual(self.Screen.display.image.call_count, draws)
        self.assertIsNotNone(self.controller.build)  # Retain identity for honest reconciliation.

    def test_processing_dots_animate_without_displaying_a_percentage(self):
        self.controller._update_build(self.job_response())
        self.controller.last_response = 100
        with patch("modulate.device.time.monotonic", return_value=100):
            self.controller.draw_processing()
            first = self.controller.status_key
        with patch("modulate.device.time.monotonic", return_value=100.25):
            self.controller.draw_processing()
        self.assertNotEqual(first[-1], self.controller.status_key[-1])
        self.assertNotIn("%", str(self.controller.status_key))

    def test_heartbeat_reports_latched_job_and_last_rendered_display_without_images(self):
        controller = self.controller
        controller._update_build(self.job_response(sequence=4))
        controller.draw_processing()
        self.Companion.post.return_value = {}
        controller._network_step()
        telemetry = self.Companion.post.call_args.args[1]["telemetry"]
        self.assertEqual(telemetry["processing"], {
            "busy": True, "job_id": "a" * 32, "job_sequence": 4,
            "phase": "coding", "title": "Building your idea",
        })
        self.assertEqual(telemetry["display"], {"kind": "processing", "title": "Building your idea"})
        controller.status("Listening", "Speak your request")
        self.assertEqual(controller.display_state, {"kind": "status", "title": "Listening"})
        controller.draw_volume()
        self.assertEqual(controller.display_state, {"kind": "control", "title": "Volume"})

    def test_loading_card_pauses_game_tick_without_replacing_runtime(self):
        self.controller._update_build(self.job_response())
        self.Controls.poll.return_value = neutral_input()
        self.DeviceActivation.snapshot.return_value = {"revision": "a" * 64, "kind": "game", "ack": None}
        runtime = self.controller.runtime

        def finish_iteration(timeout):
            self.controller.stop.set()

        with patch("modulate.device.threading.Thread"), \
                patch.object(self.controller.stop, "wait", side_effect=finish_iteration):
            self.controller.run()
        self.DeviceActivation.tick.assert_not_called()
        self.assertIs(self.controller.runtime, runtime)
        self.assertEqual(self.controller.status_key[0], "processing")


class FakeVolume:
    def __init__(self):
        self.volume = 40

    def capabilities(self):
        return {"supported": True, "platform": "synthetic"}

    def get(self):
        return {"volume": self.volume, "muted": False}

    def set_volume(self, value):
        self.volume = value


class ProductDeviceProtocolTests(unittest.TestCase):
    def test_synthetic_protocol_activate_apply_once_and_recover_lost_confirmation(self):
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=1) as pool:
            root = Path(directory)
            volume = FakeVolume()
            provider = AgentProvider({"provider": "ollama", "model": "llama3.2:3b"})
            host = Product(root / "host", provider, backend=volume)
            pairing = host.pair(host.create_pairing()["code"], "Synthetic controller")
            device = DeviceActivation(root / "device", lambda image: None,
                                      lambda: ["encoder"], lambda: pairing["session_id"])
            devices = [device]
            sequence = 0

            def exchange(*, apply=True, delta=0):
                nonlocal sequence
                sequence += 1
                state = device.snapshot()
                packet = {"session": "a" * 32, "sequence": sequence, "name": "Synthetic protocol fixture",
                          "capabilities": {"controls": ["encoder"], "devices": [], "warnings": []},
                          "revision": state["revision"], "ack": state["ack"],
                          "input": {"encoder_delta": delta}, "volume_token": pairing["token"]}
                if state["failure"]:
                    packet["failure"] = state["failure"]
                response = host.heartbeat(packet)
                if apply:
                    device.acknowledge_failure(response.get("failure_ack"))
                    device.process(response.get("activation"))
                return packet, response

            def begin(title, scale):
                package = {"kind": "control", "title": title, "target": pairing["session_id"],
                           "bindings": [{"control": "encoder", "action": "volume.delta", "scale": scale}]}
                report = {"passed": True, "candidate_id": digest(package), "checks": [{"name": "synthetic control gate", "passed": True}]}
                future = pool.submit(host.activate, package, report, base_revision=host.revision, timeout=3)
                with host.changed:
                    self.assertTrue(host.changed.wait_for(lambda: host.pending and host.pending["phase"] == "stage", timeout=1))
                return future

            try:
                exchange()
                first = begin("Synthetic first mapping", 2)
                for _ in range(3):
                    exchange()
                self.assertTrue(first.result(timeout=1)["activated"])
                first_revision = host.revision
                self.assertEqual(device.snapshot()["revision"], first_revision)
                packet, _ = exchange(delta=2)
                self.assertEqual(volume.volume, 44)
                with self.assertRaises(AgentError):
                    host.heartbeat(packet)
                self.assertEqual(volume.volume, 44)
                second = begin("Synthetic changed mapping", 3)
                exchange()  # stage -> ready
                exchange()  # commit -> activated, with durable base+intent
                _, lost_response = exchange(apply=False)  # host commits; reply is lost
                self.assertEqual(lost_response["activation"]["phase"], "confirmed")
                self.assertTrue(second.result(timeout=1)["activated"])
                device = DeviceActivation(root / "device", lambda image: None,
                                          lambda: ["encoder"], lambda: pairing["session_id"])
                devices.append(device)
                self.assertIsNotNone(device.snapshot()["failure"])
                _, recovery = exchange()
                self.assertIsNotNone(recovery["failure_ack"])
                self.assertEqual(host.revision, first_revision)
                self.assertEqual(device.snapshot()["revision"], first_revision)
                self.assertIsNone(device.snapshot()["failure"])
            finally:
                host.cancel()
                for item in reversed(devices):
                    item.close()


if __name__ == "__main__":
    unittest.main()
