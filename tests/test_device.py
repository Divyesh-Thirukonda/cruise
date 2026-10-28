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
        for name in ("Companion", "Screen", "Controls", "DeviceActivation", "VoiceListener"):
            patcher = patch("modulate.device." + name)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name, mock.return_value)
        self.Screen.buttons = self.buttons
        self.Controls.capabilities.return_value = {"controls": ["encoder", "button_a", "button_b"],
                                                  "devices": [], "warnings": []}
        self.DeviceActivation.snapshot.return_value = {"revision": None, "kind": None, "ack": None}
        self.controller = Controller(self.directory, "synthetic-enrollment")
        self.controller.last_response = time.monotonic()

    def offer(self):
        self.controller.host = {"pairing": {"code": "12345678", "expires_at": time.time() + 120}}

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
