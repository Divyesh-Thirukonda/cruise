"""Synthetic playback/wake arbitration only: no microphone, speaker or model."""

from contextlib import contextmanager
from types import SimpleNamespace
import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

from modulate.voice import (BLOCK_BYTES, CAPTURE_BLOCK_BYTES, END_SILENCE_BLOCKS,
                            PLAYBACK_PROBE_BLOCKS, PLAYBACK_PROBE_INTERVAL_BLOCKS,
                            Utterance, VoiceError, VoiceListener)


SPEECH = b"\x01\x10" * (CAPTURE_BLOCK_BYTES // 2)
SILENCE = bytes(CAPTURE_BLOCK_BYTES)


class Audio:
    def __init__(self, owner, *, speech_blocks=10000, stop_after=3000, hook=None):
        self.owner = owner
        self.speech_blocks, self.stop_after, self.hook = speech_blocks, stop_after, hook
        self.reads = self.max_buffer = 0

    def get_nowait(self):
        raise queue.Empty

    def get(self, timeout):
        self.reads += 1
        self.max_buffer = max(self.max_buffer, len(self.owner._vad.chunks))
        if self.hook:
            self.hook(self.reads)
        if self.reads >= self.stop_after:
            self.owner.set_enabled(False)
        return time.monotonic(), SPEECH if self.reads <= self.speech_blocks else SILENCE


class PlaybackWakeTests(unittest.TestCase):
    def setUp(self):
        self.requests, self.statuses = [], []
        self.listener = VoiceListener(self.requests.append, self.statuses.append)
        self.listener.set_enabled(True)
        self.listener.set_playback_active(True)
        self.listener._selected = (0, ("synthetic USB microphone", 0))

        @contextmanager
        def stream(**kwargs):
            yield SimpleNamespace(active=True)

        device = SimpleNamespace(query_devices=lambda *args: {
            "name": "synthetic USB microphone", "hostapi": 0}, RawInputStream=stream)
        for patcher in (patch.dict("sys.modules", {"sounddevice": device}),
                        patch("modulate.voice.PCMResampler", return_value=SimpleNamespace(
                            feed=lambda block: [block[:BLOCK_BYTES]])),
                        patch("modulate.voice.SpeechActivity", return_value=SimpleNamespace(
                            feed=lambda block: block != bytes(BLOCK_BYTES)))):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def probe(text, voiced, *, done=True):
        event = threading.Event()
        if done:
            event.set()
        return {"done": event, "voiced": voiced, "text": text, "error": False, "handled": False}

    def test_playback_updates_do_not_restart_capture_or_change_followup_epoch(self):
        self.listener._vad.feed(SPEECH[:BLOCK_BYTES], 1, speaking=True)
        epoch = self.listener._epoch
        generation = self.listener._playback_generation
        for _ in range(5):
            self.listener.set_playback_active(True)
        self.assertEqual(self.listener._playback_generation, generation)
        self.listener.set_playback_active(False)
        self.assertEqual(self.listener._playback_generation, generation + 1)
        self.assertEqual(self.listener._epoch, epoch)
        self.assertTrue(self.listener._vad.active)
        with self.assertRaises(ValueError):
            self.listener.set_playback_active(1)

    def test_continuous_playback_probes_are_recent_bounded_and_rate_limited(self):
        audio = self.listener._audio = Audio(self.listener, stop_after=2400)
        starts, sizes = [], []

        def probe(data, voiced):
            starts.append(audio.reads)
            sizes.append(len(data))
            return self.probe("Synthetic media without an invocation", voiced)

        with patch.object(self.listener, "_start_probe", side_effect=probe):
            self.assertIsNone(self.listener._capture(False))
        self.assertGreater(len(starts), 10)
        self.assertTrue(all(right - left >= PLAYBACK_PROBE_INTERVAL_BLOCKS
                            for left, right in zip(starts, starts[1:])))
        self.assertLessEqual(max(sizes), PLAYBACK_PROBE_BLOCKS * BLOCK_BYTES)
        self.assertLess(audio.max_buffer, PLAYBACK_PROBE_BLOCKS * 2)
        self.assertEqual(self.requests, [])
        self.assertFalse(any(s["state"] == "listening" for s in self.statuses))

    def test_confirmed_wake_waits_for_normal_silence_and_discards_media_prefix(self):
        audio = self.listener._audio = Audio(self.listener, speech_blocks=160)
        texts = iter(("Earlier media", "Media dialogue. Hey Meta, stop the music."))
        with patch.object(self.listener, "_start_probe", side_effect=lambda data, voiced: self.probe(next(texts), voiced)):
            utterance = self.listener._capture(False)
        self.assertEqual(audio.reads, 160 + END_SILENCE_BLOCKS)
        self.assertTrue(utterance.playback_wake)
        self.assertEqual(utterance.transcript, "Hey Meta, stop the music.")
        self.listener._deliver(utterance.transcript, utterance, False, self.listener._epoch)
        self.assertEqual(self.requests, ["stop the music."])

    def test_audio_arriving_during_slow_probe_is_preserved_after_confirmation(self):
        pending = self.probe("Earlier media. Hey Meta, change the lights", 80, done=False)

        def release(reads):
            if reads == 120:
                pending["done"].set()

        audio = self.listener._audio = Audio(self.listener, speech_blocks=160, hook=release)
        with patch.object(self.listener, "_start_probe", return_value=pending) as start:
            utterance = self.listener._capture(False)
        start.assert_called_once()
        self.assertEqual(audio.reads, 160 + END_SILENCE_BLOCKS)
        self.assertEqual(len(utterance.audio), (160 + END_SILENCE_BLOCKS) * BLOCK_BYTES)
        self.assertIsNone(utterance.transcript)  # Later speech requires final recognition.
        self.listener._deliver("Earlier media. Hey Meta, change the lights blue instead.",
                               utterance, False, self.listener._epoch)
        self.assertEqual(self.requests, ["change the lights blue instead."])

    def test_bare_wake_ducks_then_accepts_one_followup_in_same_stream(self):
        listener = self.listener

        class BareWakeThenCommand(Audio):
            def get(self, timeout):
                timestamp, _ = super().get(timeout)
                block = SPEECH if self.reads <= 80 or 200 < self.reads <= 240 else SILENCE
                return timestamp, block

        def status(value):
            self.statuses.append(value)
            if value["state"] == "listening":
                listener.set_playback_active(False)  # Controller ducks the route.

        listener.on_status = status
        audio = listener._audio = BareWakeThenCommand(listener)
        with patch.object(listener, "_start_probe", side_effect=lambda data, voiced:
                          self.probe("Media. Hey Meta! Hey Meta.", voiced)) as start:
            utterance = listener._capture(False)
        start.assert_called_once()
        self.assertEqual(audio.reads, 240 + END_SILENCE_BLOCKS)
        self.assertFalse(utterance.playback_wake)
        listener._deliver("turn the music down", utterance, False, listener._epoch)
        self.assertEqual(self.requests, ["turn the music down"])
        listener._deliver("another task", Utterance(b"synthetic", time.monotonic()), False, listener._epoch)
        self.assertEqual(self.requests, ["turn the music down"])

    def test_route_stopped_then_restarted_rejects_old_probe_result(self):
        pending = self.probe("Hey Meta, do this stale task", 80, done=False)

        def stop_and_release(reads):
            if reads == 100:
                self.listener.set_playback_active(False)
                self.listener.set_playback_active(True)
                pending["done"].set()

        self.listener._audio = Audio(self.listener, stop_after=220, hook=stop_and_release)
        results = iter((pending, self.probe("Media only", 160)))
        with patch.object(self.listener, "_start_probe", side_effect=lambda *args: next(results)):
            self.assertIsNone(self.listener._capture(False))
        self.assertFalse(any(s["state"] == "listening" for s in self.statuses))
        self.assertEqual(self.requests, [])

    def test_muting_invalidates_probe_without_dispatch(self):
        pending = self.probe("Hey Meta, do this stale task", 80, done=False)

        def mute(reads):
            if reads == 100:
                self.listener.set_enabled(False)
                pending["done"].set()

        self.listener._audio = Audio(self.listener, hook=mute)
        with patch.object(self.listener, "_start_probe", return_value=pending):
            self.assertIsNone(self.listener._capture(False))
        self.assertEqual(self.requests, [])
        self.assertFalse(any(s["state"] == "listening" for s in self.statuses))

    def test_regular_nonplayback_capture_still_discards_continuous_25_seconds(self):
        self.listener.set_playback_active(False)
        self.listener._audio = Audio(self.listener)
        with patch.object(self.listener, "_start_probe") as probe:
            with self.assertRaisesRegex(VoiceError, "25-second"):
                self.listener._capture(False)
        probe.assert_not_called()

    def test_ptt_and_direct_answer_do_not_start_rolling_probes(self):
        for ptt in (True, False):
            with self.subTest(ptt=ptt):
                if not ptt:
                    self.assertTrue(self.listener.set_followup("a" * 32))
                self.listener._audio = Audio(self.listener, speech_blocks=80)
                with patch.object(self.listener, "_start_probe") as probe:
                    utterance = self.listener._capture(ptt)
                probe.assert_not_called()
                self.assertFalse(utterance.playback_wake)

    def test_final_recognition_missing_confirmed_wake_never_forwards_media(self):
        unclear = self.listener.on_unclear = Mock(return_value=True)
        utterance = Utterance(b"synthetic", time.monotonic(), invoked=True, playback_wake=True)
        self.listener._deliver("background dialogue", utterance, False, self.listener._epoch)
        self.assertEqual(self.requests, [])
        unclear.assert_called_once_with("empty", followup_id=None)

    def test_nonplayback_mid_sentence_wake_is_still_ignored(self):
        utterance = Utterance(b"synthetic", time.monotonic())
        self.listener._deliver("media says Hey Meta change this", utterance, False, self.listener._epoch)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
