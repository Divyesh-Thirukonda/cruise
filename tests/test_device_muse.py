"""Synthetic presentation lifecycle checks; no device, network or model calls."""
from collections import deque
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from modulate.device import Controller
from modulate.controls import neutral_input
from tests import test_device as device_fixture


class MuseDeviceTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller.__new__(Controller)
        self.controller.lock = threading.RLock()
        self.controller.celebration = None
        self.controller.celebrated_activations = deque(maxlen=128)
        self.controller.screen = SimpleNamespace(display=SimpleNamespace(image=Mock()))
        self.controller.status_key = None
        self.controller.display_state = {}
        self.identifier, self.revision = "a" * 32, "b" * 64
        self.message = {"id": self.identifier, "revision": self.revision,
                        "base_revision": "c" * 64, "phase": "confirmed"}
        self.before = {"pending": "activated", "ack": {"id": self.identifier,
                       "revision": self.revision, "phase": "activated"}}
        self.current = {"revision": self.revision, "kind": "game", "title": "New game",
                        "ack": {"id": self.identifier, "revision": self.revision,
                                "phase": "confirmed"}, "pending": None}

    def confirm(self, now=100):
        with patch("modulate.device.time.monotonic", return_value=now):
            self.controller._activation_celebration(self.message, self.before, self.current)

    def test_only_matching_durable_new_revision_can_celebrate(self):
        cases = [
            ({**self.message, "phase": "stage"}, self.before, self.current),
            ({**self.message, "phase": "commit"}, self.before, self.current),
            (self.message, {**self.before, "pending": None}, self.current),
            (self.message, self.before, {**self.current, "ack": {**self.current["ack"], "phase": "activated"}}),
            (self.message, self.before, {**self.current, "ack": {**self.current["ack"], "id": "d" * 32}}),
            ({**self.message, "base_revision": self.revision}, self.before, self.current),
            (self.message, self.before, {**self.current, "error": "Display failed"}),
            (self.message, self.before, {**self.current, "failure": {"error": "Rolled back"}}),
            (self.message, self.before, {**self.current, "suspended": True}),
            (None, None, self.current),  # Restored/stale confirmed heartbeat.
        ]
        for message, before, current in cases:
            with self.subTest(message=message, current=current):
                self.controller._activation_celebration(message, before, current)
                self.assertIsNone(self.controller.celebration)
        self.confirm()
        self.assertEqual(self.controller.celebration["revision"], self.revision)

    def test_celebration_is_short_once_and_never_restarts_from_duplicate_ack(self):
        self.confirm()
        card = self.controller._success_card(self.current, blocked=False, now=100)
        self.assertEqual(card["until"], 101.25)
        self.assertIsNone(self.controller._success_card(self.current, blocked=False, now=101.25))
        self.confirm(102)
        self.assertIsNone(self.controller.celebration)

    def test_existing_guidance_takes_priority_and_delayed_celebration_expires(self):
        self.confirm()
        self.assertIsNone(self.controller._success_card(self.current, blocked=True, now=102))
        self.assertIsNone(self.controller.celebration["until"])
        self.assertEqual(self.controller._success_card(self.current, blocked=False, now=103)["until"], 104.25)
        self.controller.celebration["until"] = None
        self.assertIsNone(self.controller._success_card(self.current, blocked=True, now=108))
        self.assertIsNone(self.controller.celebration)

    def test_runtime_failure_or_revision_change_discards_pending_success(self):
        for change in ({"failure": {"error": "runtime crash"}}, {"revision": "e" * 64},
                       {"suspended": True}, {"error": "Display disconnected"}):
            with self.subTest(change=change):
                self.controller.celebrated_activations.clear()
                self.confirm()
                self.assertIsNone(self.controller._success_card({**self.current, **change}, blocked=False, now=101))
                self.assertIsNone(self.controller.celebration)

    def test_job_text_completion_never_creates_a_success_and_failure_clears_it(self):
        controller = self.controller
        controller.job_sequence, controller.latest_job_id = 0, None
        controller.finished_jobs, controller.feedback, controller.build = deque(maxlen=32), None, None
        state = {"job_id": self.identifier, "job_sequence": 1, "running": False, "status": "completed"}
        controller._update_build({"agent_state": state})
        self.assertIsNone(controller.celebration)
        for status in ("failed", "cancelled"):
            with self.subTest(status=status):
                controller.finished_jobs.clear()
                controller.celebrated_activations.clear()
                controller.build = {"job_id": self.identifier, "job_sequence": 1}
                self.confirm()
                controller._update_build({"agent_state": {**state, "status": status}})
                self.assertIsNone(controller.celebration)

    def test_animation_throttles_writes_and_keeps_full_explanation(self):
        detail = "The microphone is unavailable. Reconnect the USB microphone and then answer without saying Hey Meta."
        with patch("modulate.device.render_card", return_value=Image.new("RGB", (240, 135))) as render:
            for now in (100, 100.04, 100.09):
                with patch("modulate.device.time.monotonic", return_value=now):
                    self.controller.status("Quick question", detail, mode="clarify", footer="Answer directly")
            self.assertEqual(render.call_count, 1)
            self.assertEqual(render.call_args.args, ("clarify", "Quick question", detail))
            with patch("modulate.device.time.monotonic", return_value=100.13):
                self.controller.status("Quick question", detail, mode="clarify", footer="Answer directly")
            self.assertEqual(render.call_count, 2)
        self.assertEqual(self.controller.screen.display.image.call_count, 2)

    def test_talking_pose_requires_actual_playback_not_fetch_or_queue(self):
        with patch("modulate.device.render_card", return_value=Image.new("RGB", (240, 135))) as render:
            for state in ("queued", "fetching", "speaking", "stopping"):
                with self.subTest(state=state):
                    self.controller.status_key = None
                    self.controller.speaker_state = {"state": state}
                    self.controller.draw_speech()
                    self.assertEqual(render.call_args.args[0], "speaking" if state == "speaking" else "thinking")
                    self.assertEqual(self.controller.display_state["kind"], "speaker")


class MuseLoopTests(unittest.TestCase):
    def setUp(self):
        device_fixture.ControllerTests.setUp(self)
        self.controller._setup_card = Mock(return_value=None)
        self.controller._library_card = Mock(return_value=False)
        self.controller.last_response = 100
        self.controller.host = {"wake": True, "paired": True}
        self.Controls.poll.return_value = neutral_input()
        self.current = {"revision": "b" * 64, "kind": "game", "title": "Generated game", "ack": None}
        self.DeviceActivation.snapshot.return_value = self.current
        self.DeviceActivation.tick.return_value = {"commands": []}

    def test_brief_success_pauses_game_then_returns_to_the_actual_runtime(self):
        clock = [100]
        self.controller.celebration = {"revision": self.current["revision"], "title": "Generated game",
                                       "queued_at": 100, "until": None}
        displayed = []

        def next_iteration(_timeout):
            displayed.append(dict(self.controller.display_state))
            if clock[0] == 100:
                clock[0] = 101.3
            else:
                self.controller.stop.set()

        with patch("modulate.device.threading.Thread"), \
                patch("modulate.device.time.monotonic", side_effect=lambda: clock[0]), \
                patch.object(self.controller.stop, "wait", side_effect=next_iteration):
            self.controller.run()
        self.assertEqual([item["kind"] for item in displayed], ["success", "game"])
        self.DeviceActivation.tick.assert_called_once()
        self.assertIsNone(self.controller.celebration)

    def test_ambient_wake_monitoring_does_not_cover_game(self):
        self.controller.voice_state = {"state": "wake_listening", "message": "Waiting for wake phrase"}
        with patch("modulate.device.threading.Thread"), \
                patch("modulate.device.time.monotonic", return_value=100), \
                patch.object(self.controller.stop, "wait", side_effect=lambda _timeout: self.controller.stop.set()):
            self.controller.run()
        self.DeviceActivation.tick.assert_called_once()
        self.assertEqual(self.controller.display_state["kind"], "game")

    def test_active_listening_has_priority_over_pending_celebration(self):
        self.controller.voice_state = {"state": "listening", "message": "Wake phrase heard"}
        self.controller.celebration = {"revision": self.current["revision"], "title": "Generated game",
                                       "queued_at": 100, "until": None}
        with patch("modulate.device.threading.Thread"), \
                patch("modulate.device.time.monotonic", return_value=100), \
                patch("modulate.device.render_card", return_value=Image.new("RGB", (240, 135))) as render, \
                patch.object(self.controller.stop, "wait", side_effect=lambda _timeout: self.controller.stop.set()):
            self.controller.run()
        self.DeviceActivation.tick.assert_not_called()
        self.assertEqual(render.call_args.args[0], "listening")
        self.assertIsNone(self.controller.celebration["until"])


if __name__ == "__main__":
    unittest.main()
