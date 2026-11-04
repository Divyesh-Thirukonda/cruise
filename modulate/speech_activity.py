"""Streaming adapter for the independently installed Silero 6.2 activity model.

MIT model: https://github.com/snakers4/silero-vad/tree/v6.2
This detector remains an explicit non-Meta dependency, separate from recognition.
Only installation downloads assets; inference is local with bounded recurrent state.
"""
import functools
import hashlib
from pathlib import Path

MODEL_SHA256 = "7ed98ddbad84ccac4cd0aeb3099049280713df825c610a8ed34543318f1b2c49"


@functools.lru_cache(maxsize=1)
def _load_session():
    import numpy as np
    import onnxruntime as ort
    path = Path(__file__).resolve().parents[1] / "brain/models/silero-vad.onnx"
    model = path.read_bytes()
    if hashlib.sha256(model).hexdigest() != MODEL_SHA256:
        raise ValueError("Speech detector checksum mismatch")
    options = ort.SessionOptions()
    options.inter_op_num_threads = options.intra_op_num_threads = 1
    session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])

    class StreamingSession:
        def run(self, _, inputs):
            output, state = session.run(None, {"input": inputs["input"],
                "state": np.concatenate((inputs["h"], inputs["c"])), "sr": np.array(16000, dtype=np.int64)})
            return [output, state[:1], state[1:]]

    return StreamingSession()


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
                session = _load_session()
            if not callable(getattr(session, "run", None)):
                raise ValueError
        except Exception:
            raise SpeechActivityError("Local speech detector unavailable; run scripts/install_meta_asr.py and install the device dependencies") from None
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
