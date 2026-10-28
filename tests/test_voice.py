"""Wake/VAD and audio ownership tests. All audio is synthetic; no mic opens."""

from array import array
from contextlib import contextmanager
import importlib.util
import math
import queue
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

from modulate.voice import (
    BLOCK_BYTES, BLOCK_SAMPLES, BLOCK_SECONDS, CAPTURE_BLOCK_SAMPLES, EnergyVAD, MAX_AUDIO_BYTES,
    PCMResampler, PTT_BYTES, Utterance, VoiceError, VoiceListener, WakeGate,
    select_input_device, wake_remainder,
)


SILENCE = bytes(BLOCK_BYTES)
SPEECH = array("h", [3000] * BLOCK_SAMPLES).tobytes()
NATIVE_SPEECH = array("h", [3000] * CAPTURE_BLOCK_SAMPLES).tobytes()
NATIVE_SILENCE = bytes(CAPTURE_BLOCK_SAMPLES * 2)


class WakeTests(unittest.TestCase):
    def test_wake_is_anchored_case_insensitive_and_tolerates_punctuation(self):
        for text in ("Hey Meta, make a game", "HEY META! make a game",
                     "…Hey, Meta—make a game", "Hey Metta: make a game", "HeyMeta, make a game"):
            with self.subTest(text=text):
                self.assertEqual(wake_remainder(text), "make a game")
        for text in ("hello hey meta make a game", "make a game", "hey metaphor",
                     "hey metal make a game", "they meta", "metaverse"):
            with self.subTest(text=text):
                self.assertIsNone(wake_remainder(text))

    def test_wake_and_command_in_one_utterance_does_not_arm_a_second_command(self):
        gate = WakeGate()
        self.assertEqual(gate.accept("Hey Meta, make a game", now=10), "make a game")
        self.assertIsNone(gate.accept("change the game", now=11))

    def test_phrase_only_arms_one_followup_for_six_seconds(self):
        gate = WakeGate()
        self.assertIsNone(gate.accept("Hey Meta!", now=10))
        self.assertTrue(gate.armed(15.99))
        self.assertEqual(gate.accept("make a game", now=15.99), "make a game")
        self.assertFalse(gate.armed(15.99))
        self.assertIsNone(gate.accept("second request", now=15.99))

    def test_expired_window_drops_nonwake_audio_at_boundary(self):
        gate = WakeGate()
        gate.accept("hey meta", now=10)
        self.assertFalse(gate.armed(16))
        self.assertIsNone(gate.accept("make a game", now=16))

    def test_window_uses_speech_onset_not_delayed_inference_completion(self):
        gate = WakeGate()
        gate.accept("hey meta", now=10)
        self.assertEqual(gate.accept("make a game", now=20, started_at=15), "make a game")
        gate.accept("hey meta", now=30)
        self.assertIsNone(gate.accept("make a game", now=40, started_at=36))

    def test_reset_and_empty_or_overlong_transcripts_do_not_issue_requests(self):
        gate = WakeGate()
        gate.accept("hey meta", now=10)
        gate.reset()
        self.assertIsNone(gate.accept("game", now=11))
        self.assertIsNone(gate.accept(" ", now=11))
        self.assertIsNone(gate.accept("hey meta " + "x" * 2001, now=11))


class VADTests(unittest.TestCase):
    def test_silence_memory_is_bounded_to_quarter_second(self):
        vad = EnergyVAD()
        for index in range(1000):
            self.assertIsNone(vad.feed(SILENCE, index * BLOCK_SECONDS))
        self.assertEqual(len(vad.prebuffer), 10)
        self.assertEqual(vad.chunks, [])
        self.assertFalse(vad.active)

    def test_prebuffer_and_half_second_silence_end_utterance(self):
        vad = EnergyVAD()
        for _ in range(10):
            vad.feed(SILENCE, 1)
        for _ in range(4):
            self.assertIsNone(vad.feed(SPEECH, 2))
        for _ in range(19):
            self.assertIsNone(vad.feed(SILENCE, 3))
        utterance = vad.feed(SILENCE, 4)
        self.assertEqual(utterance.started_at, 2)
        self.assertEqual(len(utterance.audio), (9 + 4 + 20) * BLOCK_BYTES)
        self.assertTrue(utterance.audio.startswith(SILENCE * 9))
        self.assertFalse(vad.active)
        self.assertEqual(vad.chunks, [])

    def test_continuous_sound_cannot_exceed_eight_seconds(self):
        vad = EnergyVAD()
        utterance = None
        for index in range(320):
            utterance = vad.feed(SPEECH, index * BLOCK_SECONDS)
        self.assertIsNotNone(utterance)
        self.assertEqual(len(utterance.audio), MAX_AUDIO_BYTES)
        self.assertFalse(vad.active)

    def test_isolated_click_and_incomplete_blocks_are_discarded(self):
        vad = EnergyVAD()
        vad.feed(SPEECH, 0)
        for index in range(20):
            self.assertIsNone(vad.feed(SILENCE, index * BLOCK_SECONDS))
        self.assertFalse(vad.active)
        vad.feed(SPEECH, 1)
        with self.assertRaises(VoiceError):
            vad.feed(b"bad", 2)
        self.assertFalse(vad.active)
        self.assertEqual(vad.chunks, [])


class FakeSoundDevice:
    def __init__(self, devices=None):
        self.devices = devices or [dict(name="USB PnP microphone", hostapi=0, max_input_channels=1)]
        self.opens = self.closes = 0
        self.settings = None
        self.stream_settings = None

    def query_devices(self, device=None, kind=None):
        return self.devices if device is None else self.devices[device]

    def check_input_settings(self, **kwargs):
        self.settings = kwargs

    @contextmanager
    def RawInputStream(self, **kwargs):
        self.opens += 1
        self.stream_settings = kwargs
        try:
            yield SimpleNamespace(active=True)
        finally:
            self.closes += 1


class SyntheticQueue:
    def __init__(self, block=NATIVE_SPEECH):
        self.block = block
        self.reads = 0

    def get_nowait(self):
        raise queue.Empty()

    def get(self, timeout):
        self.reads += 1
        return time.monotonic(), self.block


class ListenerTests(unittest.TestCase):
    def setUp(self):
        self.requests, self.statuses = [], []
        self.listener = VoiceListener(self.requests.append, self.statuses.append)
        self.addCleanup(self.listener.stop)
        # Ownership tests use a fake converter; real filtering is tested below.
        def feed(block):
            values = array("h")
            values.frombytes(block)
            return [array("h", values[::3]).tobytes()]

        patcher = patch("modulate.voice.PCMResampler",
                        return_value=SimpleNamespace(feed=feed, flush=lambda: []))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_disabled_listener_does_not_load_model_or_open_capture(self):
        with patch.object(self.listener, "_capture") as capture, patch.object(self.listener, "_load_model") as load:
            self.listener.start()
            self.assertTrue(self.listener.stop())
        capture.assert_not_called()
        load.assert_not_called()
        self.assertEqual(self.statuses[-1]["state"], "muted")

    def test_ptt_is_allowed_while_wake_disabled_but_not_while_transcribing(self):
        self.assertFalse(self.listener.request_ptt())
        self.listener._thread = SimpleNamespace(is_alive=lambda: True, join=lambda timeout: None)
        self.assertTrue(self.listener.request_ptt())
        self.assertFalse(self.listener.request_ptt())
        self.listener._pending_ptt = False
        self.listener._transcribing = True
        self.assertFalse(self.listener.request_ptt())
        self.listener._thread = None

    def test_callback_queue_is_bounded_and_overflow_marks_audio_unusable(self):
        for _ in range(100):
            self.listener._callback(NATIVE_SPEECH, CAPTURE_BLOCK_SAMPLES, None, False)
        self.assertEqual(self.listener._audio.qsize(), 32)
        self.assertTrue(self.listener._overflow.is_set())
        self.listener._clear_audio()
        self.assertEqual(self.listener._audio.qsize(), 0)
        self.assertFalse(self.listener._overflow.is_set())
        self.listener._callback(NATIVE_SPEECH, CAPTURE_BLOCK_SAMPLES, None, True)
        self.assertTrue(self.listener._overflow.is_set())

    def test_ptt_uses_one_stream_and_exact_six_second_memory_buffer(self):
        sd = FakeSoundDevice()
        audio = SyntheticQueue()
        self.listener._audio = audio
        with patch.dict("sys.modules", {"sounddevice": sd}):
            utterance = self.listener._capture(ptt=True)
        self.assertEqual(len(utterance.audio), PTT_BYTES)
        self.assertEqual(audio.reads, 240)
        self.assertEqual((sd.opens, sd.closes), (1, 1))
        self.assertEqual(sd.stream_settings["latency"], 0.25)
        self.assertEqual(sd.stream_settings["samplerate"], 48000)
        self.assertEqual(sd.stream_settings["blocksize"], 1200)

    def test_silent_ptt_does_not_send_audio_to_recognition(self):
        sd = FakeSoundDevice()
        self.listener._audio = SyntheticQueue(NATIVE_SILENCE)
        with patch.dict("sys.modules", {"sounddevice": sd}):
            self.assertIsNone(self.listener._capture(ptt=True))
        self.assertIn("No speech", self.statuses[-1]["message"])

    def test_disabled_wake_capture_never_opens_a_stream(self):
        sd = FakeSoundDevice()
        with patch.dict("sys.modules", {"sounddevice": sd}):
            self.assertIsNone(self.listener._capture(ptt=False))
        self.assertEqual(sd.opens, 0)

    def test_device_identity_change_refuses_silent_switch(self):
        sd = FakeSoundDevice()
        self.listener._audio = SyntheticQueue()
        with patch.dict("sys.modules", {"sounddevice": sd}):
            self.listener._capture(ptt=True)
            sd.devices[0]["name"] = "Other USB microphone"
            with self.assertRaisesRegex(VoiceError, "changed"):
                self.listener._capture(ptt=True)
        self.assertEqual(sd.opens, 1)

    def test_request_delivery_strips_wake_and_never_puts_transcript_in_status(self):
        self.listener.set_enabled(True)
        secret_request = "make a game with PRIVATE_REQUEST_MARKER"
        self.listener._deliver("Hey Meta, " + secret_request, Utterance(b"", time.monotonic()),
                               False, self.listener._epoch)
        self.assertEqual(self.requests, [secret_request])
        self.assertNotIn("PRIVATE_REQUEST_MARKER", str(self.statuses))

    def test_disable_during_inference_invalidates_wake_delivery_but_ptt_still_works(self):
        self.listener.set_enabled(True)
        epoch = self.listener._epoch
        self.listener.set_enabled(False)
        utterance = Utterance(b"", time.monotonic())
        self.listener._deliver("Hey Meta, old request", utterance, False, epoch)
        self.assertEqual(self.requests, [])
        self.listener._deliver("new PTT request", utterance, True, epoch)
        self.assertEqual(self.requests, ["new PTT request"])

    def test_busy_handler_reports_rejection_and_stop_suppresses_late_results(self):
        self.listener.on_request = Mock(return_value=False)
        utterance = Utterance(b"", time.monotonic())
        self.listener._deliver("make a game", utterance, True, 0)
        self.assertIn("not queued", self.statuses[-1]["message"])
        self.listener.stop()
        self.listener._deliver("late request", utterance, True, 0)
        self.listener.on_request.assert_called_once_with("make a game")

    def test_cached_model_loads_once_and_uses_bounded_cpu(self):
        constructor = Mock()
        with patch.dict("sys.modules", {"faster_whisper": SimpleNamespace(WhisperModel=constructor)}):
            self.listener._load_model()
            self.listener._load_model()
        constructor.assert_called_once_with("tiny.en", device="cpu", compute_type="int8", cpu_threads=2,
                                            local_files_only=True)

    def test_same_wake_setting_does_not_interrupt_retry_backoff(self):
        self.listener.set_enabled(True)
        self.assertTrue(self.listener._changed.is_set())
        self.listener._changed.clear()
        for _ in range(8):
            self.listener.set_enabled(True)
        self.assertFalse(self.listener._changed.is_set())
        self.listener.set_enabled(False)
        self.assertTrue(self.listener._changed.is_set())

    def test_consumed_wakeup_does_not_skip_audio_error_backoff(self):
        self.listener.set_enabled(True)
        waits = []

        def backoff(seconds):
            waits.append(seconds)
            self.assertFalse(self.listener._changed.is_set())
            self.listener.set_enabled(True)  # An ordinary repeated heartbeat.
            self.assertFalse(self.listener._changed.is_set())
            self.listener._stop.set()
            return False

        with patch.object(self.listener, "_load_model"), \
                patch.object(self.listener, "_capture", side_effect=VoiceError("Synthetic microphone gap")), \
                patch.object(self.listener._changed, "wait", side_effect=backoff):
            self.listener._run()
        self.assertEqual(waits, [2])
        self.assertTrue(any(item["state"] == "error" for item in self.statuses))

    def test_audio_errors_distinguish_source_overflow_bad_block_and_full_queue(self):
        self.listener._callback(NATIVE_SPEECH, CAPTURE_BLOCK_SAMPLES, None,
                                SimpleNamespace(input_overflow=True, input_underflow=False))
        self.assertIn("input overflow", self.listener._audio_problem)
        self.listener._clear_audio()
        self.listener._callback(NATIVE_SPEECH, 1, None, False)
        self.assertIn("block size changed", self.listener._audio_problem)
        self.listener._clear_audio()
        for _ in range(33):
            self.listener._callback(NATIVE_SPEECH, CAPTURE_BLOCK_SAMPLES, None, False)
        self.assertIn("queue is full", self.listener._audio_problem)

    def test_unrecognized_wake_feedback_is_sticky_and_never_retains_transcript(self):
        self.listener.set_enabled(True)
        with patch("modulate.voice.time.monotonic", return_value=100):
            self.listener._deliver("UNRELATED_PRIVATE_SPEECH", Utterance(b"", 99), False,
                                   self.listener._epoch)
        self.assertEqual(self.requests, [])
        self.assertNotIn("UNRELATED_PRIVATE_SPEECH", str(self.statuses))
        self.assertNotIn("UNRELATED_PRIVATE_SPEECH", self.listener._feedback)
        with patch("modulate.voice.time.monotonic", return_value=103.9):
            self.assertIn("Wake phrase not recognized", self.listener._wake_status())
        with patch("modulate.voice.time.monotonic", return_value=104):
            self.assertEqual(self.listener._wake_status(), "Listening locally for Hey Meta")

    def test_transcription_vocabulary_does_not_inject_the_wake_phrase(self):
        class FakeArray:
            def astype(self, dtype):
                return self

            def __truediv__(self, value):
                return self

        numpy = SimpleNamespace(frombuffer=Mock(return_value=FakeArray()), int16="int16", float32="float32")
        self.listener._model = Mock()
        self.listener._model.transcribe.return_value = ([SimpleNamespace(text="Hey Meta, make a kart")], None)
        with patch.dict("sys.modules", {"numpy": numpy}):
            self.assertEqual(self.listener._transcribe(SPEECH), "Hey Meta, make a kart")
        kwargs = self.listener._model.transcribe.call_args.kwargs
        self.assertEqual(kwargs["initial_prompt"], "Modulate, Meta, kart, knob, coins.")
        self.assertNotIn("Hey Meta", kwargs["initial_prompt"])
        self.assertFalse(kwargs["condition_on_previous_text"])

    def test_worker_delivers_one_ptt_request_and_clears_transcription_state(self):
        delivered = threading.Event()

        def accept(text):
            self.requests.append(text)
            delivered.set()
            return True

        self.listener.on_request = accept
        utterance = Utterance(SPEECH, time.monotonic())
        with patch.object(self.listener, "_load_model"), \
                patch.object(self.listener, "_capture", return_value=utterance) as capture, \
                patch.object(self.listener, "_transcribe", return_value="make a game"):
            self.listener.start()
            self.assertTrue(self.listener.request_ptt())
            self.assertTrue(delivered.wait(1), "voice worker did not deliver the fake PTT result")
            self.assertTrue(self.listener.stop())
        self.assertEqual(self.requests, ["make a game"])
        capture.assert_called_once_with(True)
        self.assertFalse(self.listener._transcribing)
        self.assertFalse(self.listener._ptt_active)
        self.assertEqual(self.listener._audio.qsize(), 0)

    def test_audio_gap_discards_partial_ptt_and_closes_stream(self):
        sd = FakeSoundDevice()
        audio = SyntheticQueue()
        original_get = audio.get

        def get(timeout):
            self.listener._overflow.set()
            return original_get(timeout)

        audio.get = get
        self.listener._audio = audio
        with patch.dict("sys.modules", {"sounddevice": sd}):
            with self.assertRaisesRegex(VoiceError, "discarded"):
                self.listener._capture(ptt=True)
        self.assertEqual((sd.opens, sd.closes), (1, 1))
        self.assertEqual(self.requests, [])


class MicrophoneSelectionTests(unittest.TestCase):
    def test_only_one_usb_input_can_be_selected_automatically(self):
        sd = FakeSoundDevice()
        self.assertEqual(select_input_device(sd)[0], 0)
        self.assertEqual(sd.settings["samplerate"], 48000)
        sd.devices.append(dict(name="USB second mic", hostapi=0, max_input_channels=1))
        with self.assertRaises(VoiceError):
            select_input_device(sd)
        self.assertEqual(select_input_device(sd, 1)[0], 1)

    def test_no_usb_input_does_not_fall_back_to_default_laptop_microphone(self):
        sd = FakeSoundDevice([dict(name="Built-in microphone", hostapi=0, max_input_channels=1)])
        with self.assertRaises(VoiceError):
            select_input_device(sd)
        self.assertEqual(select_input_device(sd, 0)[0], 0)

    def test_alsa_names_and_boolean_indices_are_not_sounddevice_indices(self):
        for device in ("plughw:CARD=Device,DEV=0", True, -1):
            with self.subTest(device=device), self.assertRaises(ValueError):
                VoiceListener(Mock(), Mock(), device=device)


@unittest.skipUnless(importlib.util.find_spec("av"), "PyAV is a Pi speech dependency")
class RealResamplerTests(unittest.TestCase):
    def resample_tone(self, frequency):
        converter = PCMResampler()
        blocks = []
        for block in range(40):
            audio = array("h", [round(10000 * math.sin(2 * math.pi * frequency *
                                  (block * CAPTURE_BLOCK_SAMPLES + i) / 48000))
                                for i in range(CAPTURE_BLOCK_SAMPLES)]).tobytes()
            blocks.extend(converter.feed(audio))
            self.assertLess(len(converter.pending), BLOCK_BYTES)
        blocks.extend(converter.flush())
        values = array("h")
        values.frombytes(b"".join(blocks))
        self.assertEqual(len(values), 16000)
        return values[1000:-1000]

    def test_real_resampler_preserves_voice_band_and_filters_aliasing(self):
        voice = self.resample_tone(1000)
        rms = math.sqrt(sum(value * value for value in voice) / len(voice))
        self.assertAlmostEqual(rms, 10000 / math.sqrt(2), delta=200)
        above_nyquist = self.resample_tone(12000)
        aliased_rms = math.sqrt(sum(value * value for value in above_nyquist) / len(above_nyquist))
        self.assertLess(aliased_rms, 100)

    def test_six_seconds_native_pcm_gives_exact_six_seconds_for_whisper(self):
        converter = PCMResampler()
        blocks = []
        for _ in range(240):
            blocks.extend(converter.feed(NATIVE_SILENCE))
            self.assertLess(len(converter.pending), BLOCK_BYTES)
        blocks.extend(converter.flush())
        self.assertEqual(sum(len(block) for block in blocks), PTT_BYTES)
        self.assertEqual(converter.pending, b"")
        self.assertTrue(all(len(block) == BLOCK_BYTES for block in blocks))

    def test_incomplete_native_block_is_rejected(self):
        with self.assertRaises(VoiceError):
            PCMResampler().feed(SPEECH)


if __name__ == "__main__":
    unittest.main()
