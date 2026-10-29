"""Synthetic speaker/controller integration; no audio, network or GPIO."""

import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modulate.controls import neutral_input
from modulate.device import Controller


class FakeSpeaker:
    def __init__(self, on_status):
        self.on_status = on_status
        self.value = {"available": True, "state": "idle", "backend": "synthetic",
                      "output": "synthetic-sink", "error": None, "request_id": None}
        self.spoken = []
        self.cancelled = self.started = self.stopped = 0

    def snapshot(self):
        return dict(self.value)

    def emit(self, state):
        self.value["state"] = state
        self.on_status(self.snapshot())

    def start(self):
        self.started += 1
        self.emit("idle")

    def stop(self):
        self.stopped += 1
        self.emit("stopped")

    def speak(self, text):
        if not self.value["available"]:
            return False
        self.spoken.append(text)
        self.value["request_id"] = len(self.spoken)
        self.emit("queued")
        return True

    def cancel(self):
        self.cancelled += 1
        if self.value["state"] in {"queued", "speaking", "stopping"}:
            self.emit("stopping")


class DeviceSpeakerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        for name in ("Companion", "Screen", "Controls", "DeviceActivation", "VoiceListener"):
            patcher = patch("modulate.device." + name)
            mocked = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name, mocked.return_value)
        self.Screen.buttons = [SimpleNamespace(value=True), SimpleNamespace(value=True)]
        self.Controls.capabilities.return_value = {"controls": ["encoder"], "devices": [], "warnings": []}
        self.Controls.poll.return_value = neutral_input()
        self.DeviceActivation.snapshot.return_value = {"revision": "a" * 64, "kind": "game", "title": "Current app", "ack": None}
        patcher = patch("modulate.device.Speaker", FakeSpeaker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.controller = Controller(Path(self.temporary.name), "synthetic")
        self.controller.last_response = time.monotonic()
        self.controller.host = {"wake": True}
        self.speaker = self.controller.speaker

    def response(self, identifier="b" * 32, **changes):
        now = time.time()
        speech = {"id": identifier, "text": "PRIVATE_EMAIL_SUMMARY", "created_at": now,
                  "expires_at": now + 120, "job_id": "c" * 32}
        speech.update(changes)
        return {"wake": True, "speaker_enabled": True, "speech_stop_id": 0, "speech": speech}

    def apply(self, response):
        self.controller.responses.put(response)
        self.controller._apply_responses()

    def test_reply_is_accepted_once_and_host_ack_clear_does_not_stop_playback(self):
        response = self.response()
        self.apply(response)
        self.apply(response)
        self.apply({"wake": True, "speech": None, "speaker_enabled": True})
        self.assertEqual(self.speaker.spoken, ["PRIVATE_EMAIL_SUMMARY"])
        self.assertEqual(self.speaker.cancelled, 0)
        self.assertEqual(self.controller.speech_ack, "b" * 32)
        self.assertTrue(self.controller._speaker_active())

    def test_ack_and_speaker_metadata_contain_no_reply_text(self):
        self.apply(self.response())
        self.Companion.post.return_value = {}
        self.controller._network_step()
        packet = self.Companion.post.call_args.args[1]
        self.assertEqual(packet["speech_ack"], "b" * 32)
        self.assertEqual(packet["telemetry"]["speaker"]["state"], "queued")
        self.assertNotIn("PRIVATE_EMAIL_SUMMARY", json.dumps(packet))

    def test_jobless_system_speaker_test_is_accepted_but_malformed_job_is_rejected(self):
        self.apply(self.response(job_id=None, text="Speaker test"))
        self.assertEqual(self.speaker.spoken, ["Speaker test"])
        self.assertEqual(self.controller.speech_ack, "b" * 32)
        self.apply(self.response("d" * 32, job_id="malformed", text="Must not play"))
        self.assertEqual(self.speaker.spoken, ["Speaker test"])
        self.assertEqual(self.controller.speech_ack, "b" * 32)

    def test_old_expired_invalid_and_unavailable_speech_is_not_acknowledged(self):
        cases = [{"created_at": self.controller.booted_at - 0.1},
                 {"expires_at": time.time() - 1}, {"created_at": float("nan")},
                 {"job_id": "invalid"}, {"text": "x" * 1201}, {"text": None}]
        for changes in cases:
            self.apply(self.response(**changes))
        self.assertEqual(self.speaker.spoken, [])
        self.assertIsNone(self.controller.speech_ack)
        self.speaker.value["available"] = False
        self.apply(self.response())
        self.assertIsNone(self.controller.speech_ack)

    def test_older_replies_cannot_replace_a_newer_accepted_reply(self):
        first = self.response()
        newer = self.response("d" * 32, created_at=first["speech"]["created_at"] + 0.1)
        self.apply(newer)
        self.apply(first)
        self.assertEqual(self.controller.speech_ack, "d" * 32)
        self.assertEqual(len(self.speaker.spoken), 1)

    def test_monotonic_stop_cancels_once_and_old_stop_cannot_cancel_new_reply(self):
        self.apply(self.response())
        self.apply({"wake": True, "speech_stop_id": 2, "speech": None})
        self.apply({"wake": True, "speech_stop_id": 2, "speech": None})
        self.assertEqual(self.speaker.cancelled, 1)
        self.speaker.emit("idle")
        self.apply(self.response("d" * 32))
        self.apply({"wake": True, "speech_stop_id": 1, "speech": None})
        self.assertEqual(self.speaker.cancelled, 1)

    def test_disabling_speaker_stops_audio_without_queueing_another_reply(self):
        self.apply(self.response())
        response = self.response("d" * 32)
        response["speaker_enabled"] = False
        self.apply(response)
        self.assertEqual(self.speaker.cancelled, 1)
        self.assertEqual(len(self.speaker.spoken), 1)

    def test_mic_pauses_for_audio_and_cooldown_then_allows_busy_generation_cancel(self):
        self.apply(self.response())
        self.VoiceListener.set_enabled.assert_called_with(False)
        with patch("modulate.device.time.monotonic", return_value=100):
            self.speaker.emit("idle")
        with patch("modulate.device.time.monotonic", return_value=100.34):
            self.controller._sync_voice()
            self.VoiceListener.set_enabled.assert_called_with(False)
        self.controller.build = {"job_id": "f" * 32}
        with patch("modulate.device.time.monotonic", return_value=100.35):
            self.controller._sync_voice()
        self.VoiceListener.set_busy.assert_called_with(True)
        self.VoiceListener.set_enabled.assert_called_with(True)

    def test_microphone_is_disabled_before_speaker_receives_text(self):
        speak = self.speaker.speak
        def checked(text):
            self.VoiceListener.set_enabled.assert_called_with(False)
            return speak(text)
        with patch.object(self.speaker, "speak", side_effect=checked):
            self.apply(self.response())

    def test_big_game_buttons_do_not_stop_speech_but_tft_b_does(self):
        self.apply(self.response())
        sample = {**neutral_input(), "button_b": True}
        self.assertTrue(self.controller._handle_buttons(sample, 100)["button_b"])
        self.assertEqual(self.speaker.cancelled, 0)
        self.Screen.buttons[1].value = False
        self.assertFalse(self.controller._handle_buttons(sample, 101)["button_b"])
        self.controller._handle_buttons(sample, 102)
        self.assertEqual(self.speaker.cancelled, 1)

    def test_both_tft_buttons_interrupt_then_start_ptt_after_cooldown(self):
        self.apply(self.response())
        self.Screen.buttons[0].value = self.Screen.buttons[1].value = False
        sample = {**neutral_input(), "button_a": True, "button_b": True}
        with patch("modulate.device.time.monotonic", return_value=100):
            self.controller._handle_buttons(sample, 100)
        self.assertEqual(self.speaker.cancelled, 1)
        with patch("modulate.device.time.monotonic", return_value=100.1):
            self.speaker.emit("idle")
        with patch("modulate.device.time.monotonic", return_value=100.75):
            result = self.controller._handle_buttons(sample, 100.75)
            self.controller._handle_buttons(sample, 101)
        self.VoiceListener.request_ptt.assert_called_once()
        self.assertFalse(result["button_a"] or result["button_b"])

    def test_ptt_waits_for_slow_audio_stop_and_cooldown_without_losing_chord(self):
        self.apply(self.response())
        self.Screen.buttons[0].value = self.Screen.buttons[1].value = False
        with patch("modulate.device.time.monotonic", return_value=100):
            self.controller._handle_buttons(neutral_input(), 100)
        with patch("modulate.device.time.monotonic", return_value=100.8):
            self.controller._handle_buttons(neutral_input(), 100.8)
        self.VoiceListener.request_ptt.assert_not_called()
        with patch("modulate.device.time.monotonic", return_value=101):
            self.speaker.emit("idle")
        with patch("modulate.device.time.monotonic", return_value=101.36):
            self.controller._handle_buttons(neutral_input(), 101.36)
        self.VoiceListener.request_ptt.assert_called_once()

    def test_local_cancel_stops_speech_even_without_an_active_model_job(self):
        self.apply(self.response())
        self.assertTrue(self.controller.cancel_request())
        self.assertEqual(self.speaker.cancelled, 1)
        self.assertTrue(self.controller.cancellations.empty())

    def test_run_shows_generic_speaker_card_and_pauses_game_without_private_text(self):
        self.controller.responses.put(self.response())
        def finish(timeout):
            self.controller.stop.set()
        with patch("modulate.device.threading.Thread"), \
                patch.object(self.controller.stop, "wait", side_effect=finish):
            self.controller.run()
        self.DeviceActivation.tick.assert_not_called()
        self.assertEqual(self.controller.display_state, {"kind": "speaker", "title": "Replying aloud"})
        self.assertNotIn("PRIVATE_EMAIL_SUMMARY", str(self.Screen.status.call_args_list))
        self.assertEqual((self.speaker.started, self.speaker.stopped), (1, 1))


if __name__ == "__main__":
    unittest.main()
