"""Offline/bootstrap and physical setup behavior without network, GPIO or models."""

import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import ImageDraw

from modulate.controls import neutral_input
from modulate.deployment import CONNECT_HOST
from modulate.device import Controller
from modulate.device_transport import Companion, PendingCompanion, TransportError, save_private
from modulate.setup_screen import CONNECT_URL, SetupScreen
from tests import test_device as device_fixtures


class SetupScreenTests(unittest.TestCase):
    def setUp(self):
        self.screen = SetupScreen(started=100)

    def update(self, *, enrolled=True, fresh=True, host=None, now=110, wall=1000):
        return self.screen.update(enrolled=enrolled, fresh=fresh, host=host or {"paired": False},
                                  now=now, wall=wall)

    def dismiss(self, card):
        self.screen.buttons(card, False, False, True)
        self.assertEqual(self.screen.buttons(card, False, True, True), "dismiss")

    def test_paired_boot_has_no_overlay_and_first_run_does(self):
        self.assertIsNone(self.update(host={"paired": True}))
        card = self.update(enrolled=False, fresh=False, host={}, now=100)
        self.assertEqual(card["connect_url"], CONNECT_URL)
        self.assertEqual(card["action"], "next")
        self.assertEqual(self.screen.reason, "enrollment")

    def test_unreachable_companion_waits_for_startup_grace(self):
        self.assertIsNone(self.update(fresh=False, now=107.9))
        card = self.update(fresh=False, now=108)
        self.assertEqual(self.screen.reason, "offline")
        self.assertEqual(card["action"], "next")
        self.assertIsNone(self.update(host={"paired": True}, now=109))

    def test_dismissal_survives_repeated_heartbeats_but_wake_and_restart_resurface(self):
        host = {"paired": False, "setup_status": {"remote_enabled": True, "browser_count": 0}}
        self.dismiss(self.update(host=host))
        for now in (111, 112, 180):
            self.assertIsNone(self.update(host=copy.deepcopy(host), now=now))
        self.screen.wake()
        self.assertIsNotNone(self.update(host=host, now=181))
        self.dismiss(self.update(host=host, now=182))
        restarted = SetupScreen(started=200)
        self.assertIsNotNone(restarted.update(enrolled=True, fresh=True, host=host, now=200, wall=1000))

    def test_recovery_ends_dismissal_so_a_later_pair_expiry_has_a_new_reminder(self):
        self.dismiss(self.update())
        self.assertIsNone(self.update(host={"paired": True}))
        self.assertIsNotNone(self.update(host={"paired": False}))

    def test_actions_need_a_real_release_after_the_card_and_after_gpio_failure(self):
        host = {"paired": False, "setup_status": {"remote_enabled": True, "browser_count": 0}}
        card = self.update(host=host)
        self.assertIsNone(self.screen.buttons(card, True, False, True))
        self.assertIsNone(self.screen.buttons(card, False, True, True))
        self.assertFalse(self.screen.dismissed)
        self.screen.buttons(card, False, False, True)
        self.screen.buttons(card, False, False, False)
        self.assertIsNone(self.screen.buttons(card, True, False, True))
        self.screen.buttons(card, False, False, True)
        self.assertEqual(self.screen.buttons(card, True, False, True), "create_browser_code")
        self.assertIsNone(self.screen.buttons(card, True, False, True))

    def test_native_pairing_and_browser_pairing_are_distinct_next_actions(self):
        self.assertEqual(self.update(host={"paired": False, "setup_status": {
            "remote_enabled": True, "browser_count": 0}})["action"], "create_browser_code")
        self.assertEqual(self.update(host={"paired": False, "setup_status": {
            "remote_enabled": True, "browser_count": 1}})["action"], "start_pairing")
        self.assertEqual(self.update(host={"paired": False, "setup_status": {
            "remote_enabled": False, "browser_count": 0}})["action"], "start_pairing")

    def test_dismissed_browser_code_does_not_return_until_a_different_offer(self):
        offer = {"id": "a" * 32, "kind": "browser_code", "title": "Connect a browser",
                 "lines": ["Enter this on your computer"], "connect_url": CONNECT_URL,
                 "code": "12345678", "expires_at": 1200}
        host = {"paired": True, "setup": offer}
        card = self.update(host=host)
        self.dismiss(card)
        self.assertIsNone(self.update(host=copy.deepcopy(host)))
        host["setup"] = {**offer, "id": "b" * 32, "code": "87654321"}
        card = self.update(host=host)
        self.assertEqual(card["code"], "87654321")
        self.assertIsNone(self.screen.buttons(card, True, False, True))

    def test_expired_untrusted_and_stale_code_offers_never_display(self):
        offer = {"id": "a" * 32, "kind": "browser_code", "title": "Connect a browser",
                 "lines": [], "connect_url": CONNECT_URL, "code": "12345678", "expires_at": 1200}
        invalid = ({"expires_at": 1000}, {"expires_at": float("nan")}, {"expires_at": 1601},
                   {"connect_url": "https://untrusted.invalid"},
                   {"connect_url": "https://divy.live/connect"}, {"code": "https://x"},
                   {"lines": ["bad\nline"]}, {"id": "../private"})
        for change in invalid:
            with self.subTest(change=change):
                self.assertIsNone(self.update(host={"paired": True, "setup": {**offer, **change}}))
        card = self.update(fresh=False, host={"paired": True, "setup": offer})
        self.assertNotIn("code", card)


class PendingCompanionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "enrollment.json"
        self.config = {"host_url": "https://127.0.0.1:8788", "device_key": "x" * 40, "ca_file": "cert.pem"}

    def test_missing_enrollment_keeps_a_bounded_retry_without_network(self):
        pending = PendingCompanion(self.path)
        with patch("modulate.device_transport.time.monotonic", return_value=10), \
                patch("modulate.device_transport.Companion", wraps=Companion) as create, \
                patch("modulate.device_transport.urllib.request.build_opener") as opener:
            for _ in range(3):
                with self.assertRaises(TransportError):
                    pending.post("heartbeat", {})
            self.assertEqual(create.call_count, 1)
            opener.assert_not_called()
        self.assertFalse(pending.configured)

    def test_recovery_still_requires_private_https_enrollment_and_a_pinned_certificate(self):
        pending = PendingCompanion(self.path)
        now = 10
        with patch("modulate.device_transport.time.monotonic", side_effect=lambda: now), \
                patch("modulate.device_transport.ssl.SSLContext") as tls, \
                patch("modulate.device_transport.urllib.request.build_opener") as build:
            invalid = ({**self.config, "host_url": "http://127.0.0.1:8788"},
                       {**self.config, "device_key": "short"})
            for config in invalid:
                save_private(self.path, config)
                with self.assertRaises(TransportError):
                    pending.post("heartbeat", {})
                self.assertFalse(pending.configured)
                now += 3
            save_private(self.path, self.config)
            self.path.chmod(0o644)
            with self.assertRaises(TransportError):
                pending.post("heartbeat", {})
            build.assert_not_called()
            now += 3
            self.path.chmod(0o600)
            tls.return_value.load_verify_locations.side_effect = OSError("missing pin")
            with self.assertRaises(TransportError):
                pending.post("heartbeat", {})
            build.assert_not_called()
            now += 3
            tls.return_value.load_verify_locations.side_effect = None
            response = build.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"paired":false}'
            self.assertEqual(pending.post("heartbeat", {}), {"paired": False})
            self.assertTrue(pending.configured)
            tls.return_value.load_verify_locations.assert_called_with(cafile=str(self.path.resolve().parent / "cert.pem"))
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://127.0.0.1:8788/device/heartbeat")
            self.assertEqual(request.get_header("Authorization"), "Bearer " + self.config["device_key"])


class SetupControllerTests(unittest.TestCase):
    # Reuse the mocks without inheriting and rerunning the original test methods.
    setUp = device_fixtures.ControllerTests.setUp

    def test_new_deployment_address_and_code_fit_the_physical_display(self):
        screen = SetupScreen(started=0)
        guide = screen.update(enrolled=False, fresh=False, host={}, now=1, wall=1000)
        code = {"kind": "browser_code", "id": "a" * 32, "title": "Connect this browser",
                "lines": [CONNECT_HOST, "/connect"], "code": "12345678", "action": "next"}
        real_draw = ImageDraw.Draw
        for card in (guide, code):
            with self.subTest(kind=card["kind"]):
                drawings = []
                def capture(image):
                    drawing = Mock(wraps=real_draw(image))
                    drawings.append(drawing)
                    return drawing
                with patch("modulate.device.ImageDraw.Draw", side_effect=capture):
                    self.controller.draw_setup(card)
                texts = [call.args[1] for call in drawings[0].text.call_args_list]
                self.assertIn(CONNECT_HOST, texts)
                self.assertIn("/connect", texts)
                for call in drawings[0].text.call_args_list:
                    (x, y), text = call.args
                    left, top, right, bottom = call.kwargs["font"].getbbox(text)
                    self.assertGreaterEqual(x + left, 0)
                    self.assertLess(x + right, 240, text)
                    self.assertLess(y + bottom, 135, text)
                    if text in (CONNECT_HOST, "/connect"):
                        self.assertLess(y + bottom, 111, text)
                    if text == code["code"]:
                        self.assertGreaterEqual(y, 74)
                        self.assertLess(y + bottom, 111)

    def show_unpaired(self):
        self.controller.host = {"paired": False, "wake": True,
                                "setup_status": {"remote_enabled": True, "browser_count": 0}}
        self.controller.last_response = time.monotonic()
        card = self.controller._setup_card()
        self.controller.draw_setup(card)
        return card

    def test_controller_boots_to_local_guide_for_missing_or_invalid_enrollment(self):
        for error in (FileNotFoundError(), ValueError("bad json"), TransportError("invalid enrollment")):
            with self.subTest(error=type(error).__name__), patch("modulate.device.Companion", side_effect=error):
                controller = Controller(self.directory, "synthetic-enrollment")
                self.assertIsInstance(controller.companion, PendingCompanion)
                self.assertEqual(controller._setup_card()["action"], "next")
                self.assertTrue(controller.requests.empty())
                self.assertIsNone(controller.build)

    def test_large_buttons_cannot_start_setup_or_pairing(self):
        self.show_unpaired()
        sample = {**neutral_input(), "button_a": True, "button_b": True}
        self.controller._handle_buttons(sample, 10)
        self.controller._handle_buttons(sample, 12)
        self.assertTrue(self.controller.setup_actions.empty())
        self.assertTrue(self.controller.actions.empty())
        self.VoiceListener.request_ptt.assert_not_called()

    def test_setup_a_needs_release_and_only_queues_setup_not_native_approval(self):
        self.show_unpaired()
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 10)
        self.assertTrue(self.controller.setup_actions.empty())
        self.buttons[0].current = True
        self.controller._handle_buttons(neutral_input(), 11)
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 12)
        self.assertEqual(self.controller.setup_actions.get_nowait(), "create_browser_code")
        self.assertTrue(self.controller.actions.empty())
        self.VoiceListener.request_ptt.assert_not_called()

    def test_ptt_chord_cannot_become_setup_action_when_one_button_releases(self):
        self.show_unpaired()
        self.controller._handle_buttons(neutral_input(), 9)
        self.buttons[0].current = self.buttons[1].current = False
        self.controller._handle_buttons(neutral_input(), 10)
        self.controller._handle_buttons(neutral_input(), 11)
        self.VoiceListener.request_ptt.assert_called_once()
        self.buttons[1].current = True
        self.controller._handle_buttons(neutral_input(), 12)
        self.assertTrue(self.controller.setup_actions.empty())
        self.assertTrue(self.controller.actions.empty())
        self.buttons[0].current = True
        self.controller._handle_buttons(neutral_input(), 13)
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 14)
        self.assertEqual(self.controller.setup_actions.get_nowait(), "create_browser_code")

    def test_setup_b_is_local_dismissal_and_wake_resurfaces_without_queueing(self):
        self.show_unpaired()
        self.controller._handle_buttons(neutral_input(), 10)
        self.buttons[1].current = False
        self.controller._handle_buttons(neutral_input(), 11)
        self.assertIsNone(self.controller._setup_card())
        self.controller.voice_status({"state": "listening", "message": "Wake phrase heard; speak your request"})
        self.assertIsNotNone(self.controller._setup_card())
        self.assertTrue(self.controller.actions.empty())
        self.assertTrue(self.controller.requests.empty())
        self.assertTrue(self.controller.setup_actions.empty())

    def test_held_setup_a_cannot_accept_the_next_native_pair_offer(self):
        self.controller.host = {"paired": False, "setup_status": {"remote_enabled": False}}
        self.controller.draw_setup(self.controller._setup_card())
        self.controller._handle_buttons(neutral_input(), 10)
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 11)
        self.assertEqual(self.controller.setup_actions.get_nowait(), "start_pairing")
        self.controller.host["pairing"] = {"code": "12345678", "expires_at": time.time() + 120}
        self.controller._handle_buttons(neutral_input(), 12)
        self.assertTrue(self.controller.actions.empty())
        self.buttons[0].current = True
        self.controller._handle_buttons(neutral_input(), 13)
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 14)
        self.assertEqual(self.controller.actions.get_nowait(), "12345678")

    def test_holding_small_a_reopens_dismissed_guide_without_granting_access(self):
        self.show_unpaired()
        self.controller._handle_buttons(neutral_input(), 10)
        self.buttons[1].current = False
        self.controller._handle_buttons(neutral_input(), 11)
        self.buttons[1].current = True
        self.controller._handle_buttons(neutral_input(), 12)
        self.buttons[0].current = False
        self.controller._handle_buttons(neutral_input(), 13)
        self.assertIsNone(self.controller._setup_card())
        self.controller._handle_buttons(neutral_input(), 14.1)
        self.assertIsNotNone(self.controller._setup_card())
        self.assertTrue(self.controller.actions.empty())
        self.assertTrue(self.controller.setup_actions.empty())

    def test_rendered_browser_code_is_not_sent_back_in_telemetry(self):
        card = {"kind": "browser_code", "id": "c" * 32, "title": "Connect a browser",
                "lines": [], "code": "12345678", "action": "next"}
        self.controller.draw_setup(card)
        self.Companion.post.return_value = {"paired": True, "wake": True}
        self.controller._network_step()
        packet = self.Companion.post.call_args.args[1]
        self.assertEqual(packet["telemetry"]["display"]["kind"], "setup")
        self.assertNotIn(card["code"], json.dumps(packet))

    def test_setup_overlay_pauses_saved_app_without_replacing_runtime(self):
        self.show_unpaired()
        self.Controls.poll.return_value = neutral_input()
        retained = {"revision": "a" * 64, "kind": "game", "title": "Saved game", "ack": None}
        self.DeviceActivation.snapshot.return_value = retained
        self.controller.computer_audio = Mock()
        self.controller.computer_audio.snapshot.return_value = {"enabled": False}
        self.controller.hardware_debugger = Mock()
        self.controller.speaker_volume = Mock()
        runtime = self.controller.runtime

        def finish_iteration(timeout):
            self.controller.stop.set()

        with patch("modulate.device.threading.Thread"), \
                patch.object(self.controller.stop, "wait", side_effect=finish_iteration):
            self.controller.run()
        self.assertIs(self.controller.runtime, runtime)
        self.DeviceActivation.tick.assert_not_called()
        self.DeviceActivation.process.assert_not_called()
        self.assertEqual(self.controller.state["revision"], retained["revision"])
        self.assertEqual(self.controller.display_state["kind"], "setup")

    def test_uncertain_setup_delivery_is_not_replayed_after_reconnect(self):
        self.controller.setup_actions.put_nowait("start_pairing")
        self.controller.setup_in_flight = True
        self.Companion.post.side_effect = TransportError("companion offline")
        self.controller._network_step()
        self.assertTrue(self.controller.setup_actions.empty())
        self.assertFalse(self.controller.setup_in_flight)
        self.Companion.post.reset_mock()
        self.Companion.post.side_effect = None
        self.Companion.post.return_value = {"paired": False, "wake": True}
        self.controller._network_step()
        self.assertEqual([call.args[0] for call in self.Companion.post.call_args_list], ["heartbeat"])


if __name__ == "__main__":
    unittest.main()
