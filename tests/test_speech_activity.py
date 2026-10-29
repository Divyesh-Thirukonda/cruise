"""Synthetic streaming-model tests; no audio capture, downloads or inference."""
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

try:
    import numpy as np
except ImportError:
    np = None

from modulate.speech_activity import SpeechActivity, SpeechActivityError


def pcm(start=0):
    return np.arange(start, start + 400, dtype="<i2").tobytes()


class FakeSession:
    def __init__(self, probabilities=(.7,)):
        self.probabilities = list(probabilities)
        self.inputs = []

    def run(self, outputs, inputs):
        assert outputs is None
        self.inputs.append({key: value.copy() for key, value in inputs.items()})
        index = len(self.inputs)
        probability = self.probabilities[min(index - 1, len(self.probabilities) - 1)]
        return [np.array([[probability]], dtype=np.float32),
                np.full((1, 1, 128), index, dtype=np.float32),
                np.full((1, 1, 128), -index, dtype=np.float32)]


@unittest.skipIf(np is None, "NumPy is a Pi speech dependency, absent from this host environment")
class SpeechActivityTests(unittest.TestCase):
    def test_lazy_constructor_uses_only_bundled_model_and_reset_does_not_reload(self):
        model = Mock(return_value=SimpleNamespace(session=FakeSession()))
        with patch.dict(sys.modules, {"faster_whisper.vad": SimpleNamespace(get_vad_model=model)}):
            detector = SpeechActivity()
            detector.reset()
        model.assert_called_once_with()

    def test_missing_model_fails_clearly_without_exposing_native_diagnostic(self):
        model = Mock(side_effect=RuntimeError("SYNTHETIC_PRIVATE_PATH"))
        with patch.dict(sys.modules, {"faster_whisper.vad": SimpleNamespace(get_vad_model=model)}):
            with self.assertRaisesRegex(SpeechActivityError, "bundled faster-whisper") as raised:
                SpeechActivity()
        self.assertNotIn("PRIVATE", str(raised.exception))

    def test_consecutive_blocks_preserve_every_sample_context_and_recurrent_state(self):
        backend = FakeSession()
        detector = SpeechActivity(backend)
        self.assertIs(detector.feed(pcm(0)), False)
        self.assertEqual(backend.inputs, [])
        for index in range(1, 10):
            self.assertIs(detector.feed(pcm(index * 400)), True)
            self.assertEqual(detector._pending.size, ((index + 1) * 400) % 512)
            self.assertLess(detector._pending.size, 512)
        self.assertEqual(len(backend.inputs), 4000 // 512)
        for index, inputs in enumerate(backend.inputs):
            self.assertEqual(set(inputs), {"input", "h", "c"})
            self.assertEqual(inputs["input"].shape, (1, 576))
            self.assertEqual(inputs["input"].dtype, np.float32)
            expected = np.arange(index * 512, (index + 1) * 512, dtype=np.float32) / 32768
            np.testing.assert_array_equal(inputs["input"][0, 64:], expected)
            context = np.zeros(64, dtype=np.float32) if index == 0 else np.arange(index * 512 - 64, index * 512, dtype=np.float32) / 32768
            np.testing.assert_array_equal(inputs["input"][0, :64], context)
            np.testing.assert_array_equal(inputs["h"], np.full((1, 1, 128), index, dtype=np.float32))
            np.testing.assert_array_equal(inputs["c"], np.full((1, 1, 128), -index, dtype=np.float32))

    def test_hysteresis_uses_last_decision_until_a_complete_window(self):
        backend = FakeSession((.34, .35, .3, .20, .19, .34, .9))
        detector = SpeechActivity(backend)
        expected = [False, True, True, True, False, False, True]
        previous = False
        for _ in range(10):
            before = len(backend.inputs)
            result = detector.feed(bytes(800))
            if len(backend.inputs) > before:
                previous = expected[len(backend.inputs) - 1]
            self.assertIs(result, previous)

    def test_soft_speech_candidate_is_retained_without_promoting_low_noise(self):
        # These are synthetic model probabilities, not a real-world accuracy
        # claim. The old generic onset loses the .4 candidate entirely.
        softer = SpeechActivity(FakeSession((.1, .4, .3, .1)))
        previous = SpeechActivity(FakeSession((.1, .4, .3, .1)), start_threshold=.5, end_threshold=.35)
        current_results, previous_results = [], []
        for _ in range(6):
            current_results.append(softer.feed(bytes(800)))
            previous_results.append(previous.feed(bytes(800)))
        self.assertTrue(any(current_results))
        self.assertFalse(any(previous_results))
        self.assertFalse(current_results[0])
        self.assertFalse(current_results[-1])

    def test_sensitivity_configuration_cannot_disable_speech_gating(self):
        for start, end in ((True, .2), (.35, False), (.35, 0), (.35, .35), (.2, .35),
                           (1.1, .2), (float("nan"), .2), (.35, float("inf"))):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    SpeechActivity(FakeSession(), start_threshold=start, end_threshold=end)

    def test_reset_clears_audio_context_hidden_state_and_speech_decision(self):
        backend = FakeSession()
        detector = SpeechActivity(backend)
        detector.feed(pcm())
        self.assertTrue(detector.feed(pcm(400)))
        detector.reset()
        self.assertEqual(detector._pending.size, 0)
        self.assertFalse(detector.feed(bytes(800)))
        detector.feed(bytes(800))
        for value in backend.inputs[-1].values():
            self.assertFalse(np.any(value))

    def test_malformed_audio_discards_all_partial_state(self):
        for bad in (b"", bytes(798), bytes(802), "x" * 800, None, np.zeros(400, dtype=np.int16)):
            with self.subTest(kind=type(bad).__name__):
                detector = SpeechActivity(FakeSession())
                detector.feed(pcm())
                with self.assertRaisesRegex(SpeechActivityError, "audio block"):
                    detector.feed(bad)
                self.assertEqual(detector._pending.size, 0)
                self.assertFalse(detector._speaking)

    def test_malformed_model_outputs_fail_closed_and_discard_state(self):
        valid_state = np.zeros((1, 1, 128), dtype=np.float32)
        bad_outputs = [None, [np.array([.8], dtype=np.float32)],
                       [np.array([float("nan")]), valid_state, valid_state],
                       [np.array([1.1]), valid_state, valid_state],
                       [np.array([.8, .9]), valid_state, valid_state],
                       [np.array([.8]), np.zeros(128, dtype=np.float32), valid_state],
                       [np.array([.8]), valid_state.astype(np.float64), valid_state],
                       [np.array([.8]), valid_state, np.full((1, 1, 128), np.inf, dtype=np.float32)]]
        for result in bad_outputs:
            with self.subTest(result_type=type(result).__name__):
                detector = SpeechActivity(SimpleNamespace(run=Mock(return_value=result)))
                detector.feed(pcm())
                with self.assertRaisesRegex(SpeechActivityError, "detector failed"):
                    detector.feed(pcm(400))
                self.assertEqual(detector._pending.size, 0)
                self.assertFalse(detector._speaking)

    def test_model_failure_is_not_replaced_by_an_energy_fallback(self):
        backend = SimpleNamespace(run=Mock(side_effect=RuntimeError("SYNTHETIC_PRIVATE_MODEL_DETAIL")))
        detector = SpeechActivity(backend)
        detector.feed(pcm())
        with self.assertRaises(SpeechActivityError) as raised:
            detector.feed(pcm(400))
        self.assertNotIn("PRIVATE", str(raised.exception))
        self.assertEqual(detector._pending.size, 0)


if __name__ == "__main__":
    unittest.main()
