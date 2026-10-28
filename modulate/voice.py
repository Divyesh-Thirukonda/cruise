"""Local transcription-based wake listening and single-owner push-to-talk.

Audio stays in bounded memory buffers and is never written to disk. This is a
prototype transcript matcher, not a dedicated wake-word model. It also accepts
Whisper's spelling "Hey Metta". Inference pauses capture, a visible listening
gap. Cached faster-whisper tiny.en weights must already exist.

The selected USB microphone captures native 48 kHz mono int16 in 25-ms blocks.
PyAV/FFmpeg resamples on the worker to 16 kHz for VAD and Whisper; the microphone
is never replaced by a default device. Six-second push-to-talk flushes the
resampler's filter delay to retain exactly 96,000 samples at 16 kHz.

Driver APIs: https://python-sounddevice.readthedocs.io/en/0.5.3/api/raw-streams.html
Recognition: https://github.com/SYSTRAN/faster-whisper
"""

from array import array
from collections import deque
from dataclasses import dataclass
import math
import queue
import re
import threading
import time


SAMPLE_RATE = 16_000
BLOCK_SAMPLES = 400
BLOCK_BYTES = BLOCK_SAMPLES * 2
BLOCK_SECONDS = BLOCK_SAMPLES / SAMPLE_RATE
CAPTURE_RATE = 48_000
CAPTURE_BLOCK_SAMPLES = 1200
CAPTURE_BLOCK_BYTES = CAPTURE_BLOCK_SAMPLES * 2
MAX_AUDIO_BYTES = SAMPLE_RATE * 2 * 8
PTT_BYTES = SAMPLE_RATE * 2 * 6
WAKE_PATTERN = re.compile(r"^[\W_]*hey[\s,!.:;\-–—]*met(?:a|ta)\b", re.IGNORECASE)
VOCABULARY_PROMPT = "Modulate, Meta, kart, knob, coins."
INPUT_LATENCY_SECONDS = 0.25


class VoiceError(Exception):
    pass


def wake_remainder(text):
    """None means no anchored wake phrase; empty text means phrase-only."""
    match = WAKE_PATTERN.match(text)
    if match is None:
        return None
    return text[match.end():].lstrip(" \t\r\n,!.:;-–—").strip()


class WakeGate:
    def __init__(self):
        self.armed_until = 0.0

    def reset(self):
        self.armed_until = 0.0

    def armed(self, now):
        return now < self.armed_until

    def accept(self, text, *, now, started_at=None):
        text = text.strip()
        if not text or len(text) > 2000:
            return None
        remainder = wake_remainder(text)
        if remainder is not None:
            self.reset()
            if remainder:
                return remainder
            self.armed_until = now + 6
            return None
        # The speech must BEGIN in the window. Inference may finish later.
        if (now if started_at is None else started_at) < self.armed_until:
            self.reset()
            return text
        self.reset()
        return None


@dataclass(frozen=True)
class Utterance:
    audio: bytes
    started_at: float


def pcm_rms(audio):
    values = array("h")
    values.frombytes(audio)
    return math.sqrt(sum(value * value for value in values) / len(values)) / 32768


class EnergyVAD:
    """25-ms PCM blocks, 250-ms prebuffer, 500-ms silence, eight-second cap."""

    def __init__(self, threshold=0.015):
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold < 1:
            raise ValueError("RMS threshold must be between zero and one")
        self.threshold = threshold
        self.prebuffer = deque(maxlen=10)
        self.chunks = []
        self.started_at = None
        self.silence = 0
        self.voiced = 0

    @property
    def active(self):
        return self.started_at is not None

    def reset(self):
        self.prebuffer.clear()
        self.chunks.clear()
        self.started_at = None
        self.silence = self.voiced = 0

    def feed(self, audio, timestamp):
        if len(audio) != BLOCK_BYTES:
            self.reset()
            raise VoiceError("Unexpected audio block size; partial recording discarded")
        speaking = pcm_rms(audio) >= self.threshold
        if not self.active:
            self.prebuffer.append(audio)
            if not speaking:
                return None
            self.started_at = timestamp
            self.chunks = list(self.prebuffer)
            self.prebuffer.clear()
        else:
            self.chunks.append(audio)
        self.voiced += int(speaking)
        self.silence = 0 if speaking else self.silence + 1
        if self.silence < 20 and len(self.chunks) * BLOCK_BYTES < MAX_AUDIO_BYTES:
            return None
        # Isolated clicks should not trigger Whisper or arm a request.
        result = Utterance(b"".join(self.chunks)[:MAX_AUDIO_BYTES], self.started_at) if self.voiced >= 3 else None
        self.reset()
        return result


class PCMResampler:
    """FFmpeg/PyAV streaming 48 kHz -> 16 kHz conversion on the worker.

    Never resample in PortAudio's callback. The residual buffer is less than
    one 25-ms output block; PyAV owns its small filter-delay state.
    """

    def __init__(self):
        import av
        self.av = av
        self.converter = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        self.pending = bytearray()

    def _blocks(self, frames):
        for frame in frames:
            self.pending.extend(bytes(frame.planes[0])[:frame.samples * 2])
        if len(self.pending) > BLOCK_BYTES * 4:
            raise VoiceError("Unexpected resampler output; partial recording discarded")
        blocks = []
        while len(self.pending) >= BLOCK_BYTES:
            blocks.append(bytes(self.pending[:BLOCK_BYTES]))
            del self.pending[:BLOCK_BYTES]
        return blocks

    def feed(self, audio):
        if len(audio) != CAPTURE_BLOCK_BYTES:
            raise VoiceError("Unexpected native microphone block size")
        frame = self.av.AudioFrame(format="s16", layout="mono", samples=CAPTURE_BLOCK_SAMPLES)
        frame.sample_rate = CAPTURE_RATE
        frame.planes[0].update(audio)
        return self._blocks(self.converter.resample(frame))

    def flush(self):
        return self._blocks(self.converter.resample(None))


def select_input_device(sounddevice, requested=None):
    """Choose one explicit index or exactly one USB input, never a default mic."""
    if requested is None:
        devices = sounddevice.query_devices()
        matches = [index for index, item in enumerate(devices)
                   if item["max_input_channels"] >= 1 and "usb" in item["name"].lower()]
        if len(matches) != 1:
            raise VoiceError("Choose an explicit microphone index: exactly one USB input was not found")
        requested = matches[0]
    info = sounddevice.query_devices(requested, "input")
    if info["max_input_channels"] < 1:
        raise VoiceError("Selected device has no microphone input")
    # The owned USB PnP microphone accepts native 48 kHz, not 16 kHz ALSA hw
    # capture. Conversion below is explicit and never changes the selected mic.
    sounddevice.check_input_settings(device=requested, channels=1, dtype="int16", samplerate=CAPTURE_RATE)
    return requested, (info["name"], info["hostapi"])


class VoiceListener:
    """start() is initially muted; set_enabled(True) enables wake capture.

    request_ptt() queues one six-second recording even with wake disabled and
    returns False when stopped, already recording PTT, or transcribing.
    on_request(text) must enqueue promptly; returning False reports busy.
    on_status receives only state/message, never transcript or audio.
    """

    def __init__(self, on_request, on_status, device=None, *, rms_threshold=0.015):
        if device is not None and (type(device) is not int or device < 0):
            raise ValueError("Microphone device must be a sounddevice integer index")
        self.on_request, self.on_status = on_request, on_status
        self.device = device
        self._vad = EnergyVAD(rms_threshold)
        self._gate = WakeGate()
        self._lock = threading.RLock()
        self._changed = threading.Event()
        self._stop = threading.Event()
        self._overflow = threading.Event()
        self._audio_problem = None
        self._audio = queue.Queue(maxsize=32)  # At most 800 ms native PCM, 76.8 KiB.
        self._thread = None
        self._model = None
        self._selected = None
        self._enabled = self._pending_ptt = self._ptt_active = self._transcribing = False
        self._epoch = 0
        self._last_status = None
        self._feedback = None
        self._feedback_until = 0.0

    def _feedback_message(self, message):
        # Only fixed generic outcomes, never transcript fragments.
        self._feedback = message
        self._feedback_until = time.monotonic() + 4

    def _wake_status(self):
        if self._feedback and time.monotonic() < self._feedback_until:
            return self._feedback
        return "Listening locally for Hey Meta"

    def _emit(self, state, message):
        item = (state, message)
        if item == self._last_status:
            return
        self._last_status = item
        try:
            self.on_status({"state": state, "message": message})
        except Exception:
            pass  # A disconnected UI must not kill the audio-owner thread.

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop.is_set():
                    raise VoiceError("Previous voice worker is still stopping")
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="modulate-voice", daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            self._stop.set()
            self._pending_ptt = False
            self._epoch += 1
            self._changed.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        return thread is None or not thread.is_alive()

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Wake enabled must be a boolean")
        with self._lock:
            if self._enabled != enabled:
                self._enabled = enabled
                self._epoch += 1  # Invalidate any in-flight wake transcription.
                # Heartbeats repeat the current setting. They must not wake a
                # two-second audio-error backoff four times each second.
                self._changed.set()

    def request_ptt(self):
        with self._lock:
            if (self._thread is None or not self._thread.is_alive() or self._stop.is_set()
                    or self._pending_ptt or self._ptt_active or self._transcribing):
                return False
            self._pending_ptt = True
            self._changed.set()
            return True

    def _callback(self, indata, frames, time_info, status):
        problem = None
        if frames != CAPTURE_BLOCK_SAMPLES or len(indata) != CAPTURE_BLOCK_BYTES:
            problem = "Microphone block size changed; partial recording discarded"
        elif status:
            if getattr(status, "input_overflow", False):
                problem = "Microphone input overflow; partial recording discarded"
            elif getattr(status, "input_underflow", False):
                problem = "Microphone input underflow; partial recording discarded"
            else:
                problem = "Microphone stream reported an audio gap; partial recording discarded"
        if problem:
            if self._audio_problem is None:
                self._audio_problem = problem
            self._overflow.set()
            return
        try:
            self._audio.put_nowait((time.monotonic(), bytes(indata)))
        except queue.Full:
            if self._audio_problem is None:
                self._audio_problem = "Microphone processing queue is full; partial recording discarded"
            self._overflow.set()

    def _clear_audio(self):
        self._overflow.clear()
        self._audio_problem = None
        self._vad.reset()
        while True:
            try:
                self._audio.get_nowait()
            except queue.Empty:
                return

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._emit("idle", "Loading cached local speech model; microphone is closed")
            self._model = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=2,
                                       local_files_only=True)

    def _transcribe(self, audio):
        import numpy as np

        waveform = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768
        segments, _ = self._model.transcribe(
            waveform, language="en", beam_size=1, temperature=0,
            condition_on_previous_text=False, vad_filter=False,
            initial_prompt=VOCABULARY_PROMPT,
        )
        # Consume lazily generated segments here, on the single model owner.
        parts, size = [], 0
        for segment in segments:
            value = segment.text.strip()
            size += len(value) + 1
            if size > 2000:
                raise VoiceError("Local transcript exceeded the request limit")
            parts.append(value)
        return " ".join(parts).strip()

    def _capture(self, ptt):
        with self._lock:
            if self._stop.is_set() or (not ptt and not self._enabled):
                return None
        import sounddevice as sd

        if self._selected is None:
            self._selected = select_input_device(sd, self.device)
        index, identity = self._selected
        info = sd.query_devices(index, "input")
        if (info["name"], info["hostapi"]) != identity:
            raise VoiceError("Selected microphone changed; choose its index again instead of switching silently")
        self._clear_audio()
        converter = PCMResampler()
        chunks, voiced, native_blocks = [], 0, 0
        last_audio = started = time.monotonic()
        with sd.RawInputStream(device=index, channels=1, samplerate=CAPTURE_RATE,
                               blocksize=CAPTURE_BLOCK_SAMPLES, dtype="int16",
                               latency=INPUT_LATENCY_SECONDS, callback=self._callback) as stream:
            while not self._stop.is_set():
                with self._lock:
                    if not ptt and (not self._enabled or self._pending_ptt):
                        return None
                if self._overflow.is_set():
                    raise VoiceError(self._audio_problem or "Microphone audio gap; partial recording discarded")
                if not stream.active:
                    raise VoiceError("Selected microphone stream stopped; retrying the same device")
                if ptt:
                    self._emit("listening", "Push-to-talk: recording for six seconds locally")
                elif self._vad.active:
                    self._emit("listening", "Speech detected; checking the wake phrase locally")
                elif self._gate.armed(time.monotonic()):
                    self._emit("listening", "Wake phrase heard; say your request within six seconds")
                else:
                    self._emit("wake_listening", self._wake_status())
                try:
                    timestamp, audio = self._audio.get(timeout=0.1)
                except queue.Empty:
                    if time.monotonic() - last_audio > 2:
                        raise VoiceError("Selected microphone produced no audio; retrying the same device")
                    continue
                last_audio = time.monotonic()
                if len(audio) != CAPTURE_BLOCK_BYTES:
                    raise VoiceError("Invalid microphone block; partial recording discarded")
                native_blocks += 1
                blocks = converter.feed(audio)
                ptt_complete = ptt and native_blocks >= 240
                if ptt_complete:
                    blocks.extend(converter.flush())
                for audio in blocks:
                    if ptt:
                        chunks.append(audio)
                        voiced += int(pcm_rms(audio) >= self._vad.threshold)
                    else:
                        utterance = self._vad.feed(audio, timestamp)
                        if utterance is not None:
                            return utterance
                if ptt_complete:
                    if len(chunks) * BLOCK_BYTES != PTT_BYTES:
                        raise VoiceError("Resampling did not produce the complete six-second recording")
                    if voiced < 3:
                        message = "No speech detected; try push-to-talk again"
                        self._feedback_message(message)
                        self._emit("idle", message)
                        return None
                    return Utterance(b"".join(chunks), started)
        return None

    def _deliver(self, text, utterance, ptt, epoch):
        with self._lock:
            if self._stop.is_set() or (not ptt and (not self._enabled or epoch != self._epoch)):
                return
        now = time.monotonic()
        if ptt:
            text = text.strip()
            remainder = wake_remainder(text)
            request = text if remainder is None else remainder
        else:
            request = self._gate.accept(text, now=now, started_at=utterance.started_at)
        if not request:
            if ptt:
                message = "No request recognized; try push-to-talk again"
                self._feedback_message(message)
                self._emit("idle", message)
            elif not self._gate.armed(now):
                message = ("Wake phrase not recognized; say Hey Meta or use both screen buttons"
                           if text.strip() else "No clear speech recognized; try both screen buttons")
                self._feedback_message(message)
                self._emit("wake_listening", message)
            return
        if len(request) > 2000:
            raise VoiceError("Local transcript exceeded the request limit")
        try:
            accepted = self.on_request(request)
        except Exception:
            raise VoiceError("Request handler failed; request was not confirmed queued") from None
        if accepted is False:
            message = "Request was not queued; check connection or wait for the current build"
            self._feedback_message(message)
        else:
            message = "Voice request queued"
            self._feedback = None
        self._emit("idle", message)

    def _run(self):
        seen_epoch = -1
        try:
            while not self._stop.is_set():
                with self._lock:
                    enabled, epoch = self._enabled, self._epoch
                    ptt = self._pending_ptt
                    if ptt:
                        self._pending_ptt = False
                        self._ptt_active = True
                        self._feedback = None
                    # Consume a configuration/PTT wakeup with its state while
                    # holding the same lock used by the setters. It must not
                    # survive into the error handler as a spurious retry.
                    self._changed.clear()
                if epoch != seen_epoch or ptt:
                    self._gate.reset()
                    seen_epoch = epoch
                if not enabled and not ptt:
                    if self._last_status is None or self._last_status[0] != "error":
                        self._emit("muted", "Wake listening is off; microphone is closed")
                    self._changed.wait(0.1)
                    continue
                try:
                    utterance = text = None
                    self._load_model()
                    if self._stop.is_set():
                        break
                    utterance = self._capture(ptt)
                    self._clear_audio()  # Drop unused trailing blocks before inference.
                    if utterance is None:
                        continue
                    with self._lock:
                        if not ptt and (self._pending_ptt or not self._enabled or epoch != self._epoch):
                            continue
                        self._transcribing = True
                    self._emit("transcribing", "Transcribing locally; microphone is paused")
                    text = self._transcribe(utterance.audio)
                    self._deliver(text, utterance, ptt, epoch)
                    del text, utterance
                except Exception as error:
                    message = str(error) if isinstance(error, VoiceError) else (
                        "Local speech or selected microphone unavailable; check cached tiny.en weights and the chosen input")
                    self._feedback_message(message)
                    self._emit("error", message)
                    with self._lock:
                        self._ptt_active = self._transcribing = False
                    # Retry only while wake is enabled. Failed explicit PTT is
                    # not silently restarted as an unsolicited recording.
                    self._changed.wait(2)
                finally:
                    utterance = text = None  # Drop PCM/transcript references on failure too.
                    self._clear_audio()
                    with self._lock:
                        self._ptt_active = self._transcribing = False
        finally:
            self._clear_audio()
            self._gate.reset()
            self._emit("muted", "Voice listener stopped; microphone is closed")
