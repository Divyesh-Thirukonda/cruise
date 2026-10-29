"""Bounded streaming adapter for faster-whisper 1.2.1's bundled Silero VAD.

The recurrent ONNX interface follows the dependency's implementation:
https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/vad.py
Its public array callable resets state for each call. We retain independent
h/c state and 64 context samples across 512-sample windows instead, so each
audio sample is inferred once. Model loading uses the installed asset only.
No audio or model output is logged or persisted. Construct on the capture
worker, never in the PortAudio callback or game/heartbeat thread.
"""


class SpeechActivityError(RuntimeError):
    """A fixed diagnostic without audio or native exception contents."""


class SpeechActivity:
    """Consume 400 signed little-endian int16 samples at 16 kHz per feed.

    Start speech at probability >= .35; end it below .20. Between complete
    512-sample model windows, return the most recent decision (initially False).
    Inference adds at most 31 ms of classification delay. The caller owns its
    prebuffer and request-ending silence timer; this class only detects speech.

    ``session`` is an injectable ONNX-shaped test backend, not a fallback.
    Each instance is owned by one capture worker and is not thread-safe.
    """

    def __init__(self, session=None, *, start_threshold=.35, end_threshold=.20):
        # On a small desktop microphone the generic .50 onset can classify a
        # soft greeting as silence. This is only a capture candidate threshold:
        # the voice worker still requires an explicit recognized wake phrase.
        if (type(start_threshold) not in (int, float) or type(end_threshold) not in (int, float)
                or not 0 < end_threshold < start_threshold <= 1):
            raise ValueError("Speech thresholds require 0 < end < start <= 1")
        try:
            import numpy as np
            if session is None:
                from faster_whisper.vad import get_vad_model
                session = get_vad_model().session
            if not callable(getattr(session, "run", None)):
                raise ValueError
        except Exception:
            raise SpeechActivityError("Local speech detector unavailable; check the bundled faster-whisper model") from None
        self._np = np
        self._session = session
        # Compare values in the ONNX output's float32 precision at boundaries.
        self._start_threshold = float(np.float32(start_threshold))
        self._end_threshold = float(np.float32(end_threshold))
        self.reset()

    def reset(self):
        """Discard residual audio and recurrent state between capture epochs."""
        np = self._np
        self._pending = np.empty(0, dtype=np.float32)
        self._context = np.zeros(64, dtype=np.float32)
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._speaking = False

    def feed(self, audio):
        if not isinstance(audio, (bytes, bytearray)) or len(audio) != 800:
            self.reset()
            raise SpeechActivityError("Unexpected speech-detector audio block; partial recording discarded")
        np = self._np
        try:
            samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
            pending = np.concatenate((self._pending, samples))
            if pending.size < 512:
                self._pending = pending
                return self._speaking
            # 400-sample feeds and <512 carry permit exactly one model window.
            window = pending[:512]
            self._pending = pending[512:].copy()
            frame = np.concatenate((self._context, window)).reshape(1, 576)
            result = self._session.run(None, {"input": frame, "h": self._h, "c": self._c})
            if not isinstance(result, (tuple, list)) or len(result) != 3:
                raise ValueError
            probability, h, c = (np.asarray(item) for item in result)
            if probability.size != 1 or probability.dtype.kind != "f":
                raise ValueError
            value = float(probability.reshape(-1)[0])
            if not 0 <= value <= 1:
                raise ValueError
            for state in (h, c):
                if state.shape != (1, 1, 128) or state.dtype != np.float32 or not np.isfinite(state).all():
                    raise ValueError
            self._context = window[-64:].copy()
            self._h, self._c = h.copy(), c.copy()
            if value >= self._start_threshold:
                self._speaking = True
            elif value < self._end_threshold:
                self._speaking = False
            return self._speaking
        except Exception:
            self.reset()
            raise SpeechActivityError("Local speech detector failed; partial recording discarded") from None
