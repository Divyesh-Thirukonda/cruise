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
from modulate.device import Controller, main as device_main
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
        self.assertEqual(self.screen.buttons(card, True, False, True), "start_pairing")
        self.assertIsNone(self.screen.buttons(card, True, False, True))

    def test_native_pairing_and_browser_pairing_are_distinct_next_actions(self):
        self.assertEqual(self.update(host={"paired": False, "setup_status": {
            "remote_enabled": True, "browser_count": 0}})["action"], "start_pairing")
        self.assertEqual(self.update(host={"paired": False, "setup_status": {
            "remote_enabled": True, "browser_count": 1}})["action"], "start_pairing")
        self.assertEqual(self.update(host={"paired": False, "setup_status": {
            "remote_enabled": False, "browser_count": 0}})["action"], "start_pairing")
        self.screen.force = True
        self.assertEqual(self.update(host={"paired": True, "setup_status": {
            "remote_enabled": True, "browser_count": 0}})["action"], "create_browser_code")
        self.assertEqual(self.update(host={"paired": True, "setup_status": {
            "remote_enabled": False, "browser_count": 0}})["action"], "next")

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
        self.assertEqual(self.controller.setup_actions.get_nowait(), "start_pairing")
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
        self.assertEqual(self.controller.setup_actions.get_nowait(), "start_pairing")

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


class DeviceEnrollmentUITests(unittest.TestCase):
    """Physical release/confirmation and display privacy; no network or GPIO."""
    setUp = device_fixtures.ControllerTests.setUp

    def bootstrap(self, *, code=None, pending=None):
        self.controller.companion = PendingCompanion(self.directory / "absent-enrollment.json")
        self.controller.last_response = 0
        self.controller.host = {}
        service = Mock()
        service.snapshot.return_value = {"available": True, "address": "192.168.100.123", "port": 8790,
            "fingerprint": "0123456789abcdef0123", "code": code, "pending": pending}
        service.confirm.return_value = True
        self.controller.enrollment_setup = service
        self.controller.draw_setup(self.controller._setup_card())
        return service

    def press(self, a=False, b=False, now=10):
        self.buttons[0].current, self.buttons[1].current = not a, not b
        return self.controller._handle_buttons(neutral_input(), now)

    def test_only_fresh_small_a_opens_enrollment_window(self):
        service = self.bootstrap()
        self.press(a=True)
        service.open_window.assert_not_called()
        self.press()
        self.controller._handle_buttons({**neutral_input(), "button_a": True}, 11)
        service.open_window.assert_not_called()
        self.press(a=True, now=12)
        self.press(a=True, now=13)
        service.open_window.assert_called_once_with()
        service.confirm.assert_not_called()
        self.assertTrue(self.controller.actions.empty())
        self.assertTrue(self.controller.setup_actions.empty())

    def test_new_pending_request_requires_render_then_release_before_approval(self):
        service = self.bootstrap(code="07873334")
        self.press()
        self.press(a=True)
        pending = {"id": "a" * 32, "host_address": "192.168.100.20"}
        service.snapshot.return_value["pending"] = pending
        self.press(a=True)
        self.press()
        self.press(a=True)
        service.confirm.assert_not_called()
        self.controller.draw_setup(self.controller._setup_card())
        self.press(a=True)
        service.confirm.assert_not_called()
        self.press()
        self.press(a=True)
        self.press(a=True)
        service.confirm.assert_called_once_with(pending["id"])
        self.assertTrue(self.controller.actions.empty())

    def test_chord_and_invalid_gpio_cannot_approve_enrollment(self):
        pending = {"id": "b" * 32, "host_address": "192.168.100.20"}
        service = self.bootstrap(code="07873334", pending=pending)
        self.press()
        self.press(a=True, b=True)
        self.press(a=True)
        service.confirm.assert_not_called()
        self.press()
        self.buttons[0].error = True
        self.press(a=True)
        self.buttons[0].error = False
        self.press(a=True)
        service.confirm.assert_not_called()
        self.press()
        self.press(a=True)
        service.confirm.assert_called_once_with(pending["id"])

    def test_b_rejects_request_and_hides_bootstrap_until_explicit_wake(self):
        service = self.bootstrap(code="07873334", pending={"id": "c" * 32, "host_address": "192.168.100.20"})
        self.press()
        self.press(b=True)
        service.close_window.assert_called_once_with()
        service.confirm.assert_not_called()
        self.assertIsNone(self.controller._setup_card())
        service.snapshot.return_value.update(code=None, pending=None)
        self.controller.setup_screen.wake()
        self.assertEqual(self.controller._setup_card()["action"], "open_enrollment")
        service.open_window.assert_not_called()

    def test_expired_proposal_does_not_show_success_or_queue_pairing(self):
        service = self.bootstrap(code="07873334", pending={"id": "d" * 32, "host_address": "192.168.100.20"})
        service.confirm.return_value = False
        self.press()
        self.press(a=True)
        self.assertEqual(self.controller.feedback["title"], "Setup not confirmed")
        self.assertTrue(self.controller.actions.empty())
        self.assertTrue(self.controller.setup_actions.empty())

    def test_missing_network_can_be_rechecked_without_restarting_device(self):
        service = self.bootstrap()
        service.snapshot.return_value.update(address=None, error="No network address yet")
        card = self.controller._setup_card()
        self.assertEqual(card["title"], "Connect to your network")
        self.controller.draw_setup(card)
        self.press()
        self.press(a=True)
        service.open_window.assert_called_once_with()
        service.confirm.assert_not_called()

    def test_complete_ipv6_address_key_code_and_request_fit_without_overlap(self):
        service = self.bootstrap(code="07873334")
        real_draw = ImageDraw.Draw
        addresses = ("192.168.100.123", "2001:db8:abcd:ffff:1234:5678:90ab:cdef",
                     "2001:aaaa:aaaa:aaaa:aaaa:aaaa:aaaa:aaaa")
        for address in addresses:
            for confirming in (False, True):
                with self.subTest(address=address, confirming=confirming):
                    service.snapshot.return_value.update(address=address, pending=(
                        {"id": "f" * 24 + "abcd1234", "host_address": address} if confirming else None))
                    self.controller.status_key = None
                    card = self.controller._setup_card()
                    drawings = []
                    def capture(image):
                        drawing = Mock(wraps=real_draw(image))
                        drawings.append(drawing)
                        return drawing
                    with patch("modulate.device.ImageDraw.Draw", side_effect=capture):
                        self.controller.draw_setup(card)
                    texts, address_fragments, boxes = [], [], []
                    for call in drawings[0].text.call_args_list:
                        (x, y), text = call.args
                        texts.append(text)
                        if y in (44, 56):
                            address_fragments.append(text)
                        left, top, right, bottom = call.kwargs["font"].getbbox(text)
                        box = (x + left, y + top, x + right, y + bottom)
                        self.assertGreaterEqual(box[0], 0)
                        self.assertLess(box[2], 240, text)
                        self.assertLess(box[3], 135, text)
                        for previous in boxes:
                            self.assertFalse(min(box[2], previous[2]) > max(box[0], previous[0]) and
                                             min(box[3], previous[3]) > max(box[1], previous[1]), text)
                        boxes.append(box)
                    expected = address if confirming else (f"[{address}]:8790" if ":" in address else f"{address}:8790")
                    self.assertEqual("".join(address_fragments), expected)
                    if confirming:
                        self.assertIn("ABCD1234", texts)
                    else:
                        self.assertIn("07873334", texts)
                        self.assertIn("Key: 0123456789 ABCDEF0123", texts)

    def test_bootstrap_credentials_fit_screen_and_never_enter_telemetry(self):
        service = self.bootstrap(code="07873334")
        real_draw = ImageDraw.Draw
        for pending in (None, {"id": "e" * 32, "host_address": "192.168.100.20"}):
            service.snapshot.return_value["pending"] = pending
            card = self.controller._setup_card()
            self.controller.status_key = None
            drawings = []
            def capture(image):
                drawing = Mock(wraps=real_draw(image))
                drawings.append(drawing)
                return drawing
            with patch("modulate.device.ImageDraw.Draw", side_effect=capture):
                self.controller.draw_setup(card)
            for call in drawings[0].text.call_args_list:
                (x, y), text = call.args
                left, top, right, bottom = call.kwargs["font"].getbbox(text)
                self.assertGreaterEqual(x + left, 0)
                self.assertLess(x + right, 240, text)
                self.assertLess(y + bottom, 135, text)
                if text == "07873334":
                    self.assertLess(y + bottom, 111, text)
            self.controller.companion = self.Companion
            self.Companion.post.return_value = {"paired": False}
            self.controller._network_step()
            packet = self.Companion.post.call_args.args[1]
            text = json.dumps(packet)
            self.assertNotIn("07873334", text)
            self.assertNotIn(service.snapshot.return_value["fingerprint"], text)
            self.assertNotIn("e" * 32, text)
            self.controller.companion = PendingCompanion(self.directory / "absent-enrollment.json")


class DeviceEnrollmentLifecycleTests(unittest.TestCase):
    def test_existing_files_and_dangling_symlinks_never_open_enrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ("invalid_file", "dangling_symlink"):
                enrollment = root / (kind + ".json")
                if kind == "invalid_file":
                    enrollment.write_text("invalid enrollment must be repaired, not replaced")
                else:
                    enrollment.symlink_to(root / "missing-target")
                with self.subTest(kind=kind), patch("sys.argv", ["modulate.device", "--state-dir", str(root / kind),
                        "--enrollment", str(enrollment)]), patch("modulate.device.Controller") as controller, \
                        patch("modulate.device.signal.signal"), patch("modulate.device.os.umask"), \
                        patch("modulate.device_enrollment.EnrollmentServer") as service:
                    device_main()
                    controller.return_value.run.assert_called_once_with()
                    service.assert_not_called()
                self.assertTrue(enrollment.is_symlink() if kind == "dangling_symlink" else enrollment.is_file())

    def test_first_boot_attaches_local_service_and_always_closes_it(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            enrollment = Path(directory) / "device-enrollment.json"
            with patch("sys.argv", ["modulate.device", "--state-dir", str(state), "--enrollment", str(enrollment)]), \
                    patch("modulate.device.Controller") as controller, patch("modulate.device.signal.signal"), \
                    patch("modulate.device.os.umask"), patch("modulate.device_enrollment.EnrollmentServer") as service:
                controller.return_value.run.side_effect = RuntimeError("synthetic display failure")
                with self.assertRaisesRegex(RuntimeError, "synthetic display failure"):
                    device_main()
                service.assert_called_once_with(state / "setup", str(enrollment))
                self.assertIs(controller.return_value.enrollment_setup, service.return_value)
                service.return_value.start.assert_called_once_with()
                service.return_value.close.assert_called_once_with()
                self.assertFalse(enrollment.exists())


if __name__ == "__main__":
    unittest.main()
