"""Local transcription-based wake listening and single-owner push-to-talk.

Audio stays in bounded memory buffers and is never written to disk. This is a
prototype transcript matcher, not a dedicated wake-word model. It also accepts
Whisper's spelling "Hey Metta". A wake-only probe follows 500 ms of silence
while capture continues; final recognition may pause capture. Ambient inference
stays visually passive. Cached faster-whisper tiny.en weights must already exist.
During computer-audio playback, bounded rolling wake probes do not require a
silence gap. This remains transcript matching, not acoustic echo cancellation.

The selected USB microphone captures native 48 kHz mono int16 in 25-ms blocks.
PyAV/FFmpeg resamples on the worker to 16 kHz for bundled Silero VAD and Whisper; the microphone
is never replaced by a default device. Requests end after three seconds of
silence; audio reaching the 25-second cap is discarded, never auto-submitted.

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

from .speech_activity import SpeechActivity


SAMPLE_RATE = 16_000
BLOCK_SAMPLES = 400
BLOCK_BYTES = BLOCK_SAMPLES * 2
BLOCK_SECONDS = BLOCK_SAMPLES / SAMPLE_RATE
CAPTURE_RATE = 48_000
CAPTURE_BLOCK_SAMPLES = 1200
CAPTURE_BLOCK_BYTES = CAPTURE_BLOCK_SAMPLES * 2
MAX_AUDIO_BYTES = SAMPLE_RATE * 2 * 25
END_SILENCE_BLOCKS = 120
PTT_NO_SPEECH_BLOCKS = 320
WAKE_PATTERN = re.compile(r"^[\W_]*hey[\s,!.:;\-–—]*met(?:a|ta)\b", re.IGNORECASE)
PLAYBACK_WAKE_PATTERN = re.compile(r"(?<!\w)hey[\s,!.:;\-–—]*met(?:a|ta)\b", re.IGNORECASE)
PLAYBACK_PROBE_BLOCKS = 120  # At most three seconds of recent 16 kHz audio.
PLAYBACK_PROBE_INTERVAL_BLOCKS = 80  # No more than one start per two seconds.
VOCABULARY_PROMPT = "Modulate, Meta, kart, knob, coins."
INPUT_LATENCY_SECONDS = 0.25
CANCEL_PATTERN = re.compile(r"(?:cancel(?: (?:the )?(?:rebuild|build))?|stop(?: building)?)[.!?]*", re.IGNORECASE)
INCOMPLETE_REQUESTS = frozenset({"oh", "um", "uh", "hmm", "ah", "make a", "make an",
                               "change it to", "change to", "turn it into", "can you", "could you",
                               "i want", "i want to"})


class VoiceError(Exception):
    pass


def wake_remainder(text):
    """None means no anchored wake phrase; empty text means phrase-only."""
    match = WAKE_PATTERN.match(text)
    if match is None:
        return None
    remainder = text[match.end():].lstrip(" \t\r\n,!.:;-–—").strip()
    # Repeating the wake phrase is still an invocation, never a new request.
    while (match := WAKE_PATTERN.match(remainder)) is not None:
        remainder = remainder[match.end():].lstrip(" \t\r\n,!.:;-–—").strip()
    return remainder


def _playback_wake_text(text):
    """Only playback probes may skip preceding media text to find an invocation."""
    if type(text) is not str or len(text) > 2000:
        return None
    match = PLAYBACK_WAKE_PATTERN.search(text)
    return text[match.start():] if match is not None else None


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
    transcript: str | None = None
    invoked: bool = False
    followup_id: str | None = None
    playback_wake: bool = False


def pcm_rms(audio):
    values = array("h")
    values.frombytes(audio)
    return math.sqrt(sum(value * value for value in values) / len(values)) / 32768


class EnergyVAD:
    """25-ms blocks, 250-ms prebuffer, three-second silence, discard at 25s."""

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

    def feed(self, audio, timestamp, *, speaking=None):
        if len(audio) != BLOCK_BYTES:
            self.reset()
            raise VoiceError("Unexpected audio block size; partial recording discarded")
        # Production capture supplies the local speech model's classification.
        # Energy remains available for deterministic buffer-only tests.
        if speaking is None:
            speaking = pcm_rms(audio) >= self.threshold
        elif type(speaking) is not bool:
            raise VoiceError("Invalid speech activity classification")
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
        if len(self.chunks) * BLOCK_BYTES >= MAX_AUDIO_BYTES:
            self.reset()
            raise VoiceError("Speech reached the 25-second limit; nothing submitted. Try a shorter request")
        if self.silence < END_SILENCE_BLOCKS:
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

    request_ptt() queues one silence-ended recording even with wake disabled and
    returns False when stopped, already recording PTT, or transcribing.
    on_request(text) must enqueue promptly; returning False reports busy.
    Scoped answers use on_request(text, followup_id=identifier). Optional
    on_unclear(reason, followup_id=None) asks for a trusted local clarification.
    on_status receives only state/message, never transcript or audio.
    """

    def __init__(self, on_request, on_status, device=None, *, rms_threshold=0.015, on_cancel=None,
                 on_unclear=None):
        if device is not None and (type(device) is not int or device < 0):
            raise ValueError("Microphone device must be a sounddevice integer index")
        self.on_request, self.on_status = on_request, on_status
        self.on_cancel = on_cancel
        self.on_unclear = on_unclear
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
        self._model_lock = threading.Lock()
        self._probe_thread = None
        self._selected = None
        self._enabled = self._pending_ptt = self._ptt_active = self._transcribing = False
        self._busy = False
        self._playback_active = False
        self._playback_generation = 0
        self._followup_id = None
        self._followup_seen = deque(maxlen=64)
        self._followup_from = self._followup_until = 0.0
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
        return "Working; say Hey Meta cancel build" if self._busy else "Listening locally for Hey Meta"

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
            self._followup_id = None
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
                if not enabled:
                    self._followup_id = None
                self._epoch += 1  # Invalidate any in-flight wake transcription.
                # Heartbeats repeat the current setting. They must not wake a
                # two-second audio-error backoff four times each second.
                self._changed.set()

    def set_followup(self, identifier, *, seconds=20):
        """Grant one answer beginning within 1–30 s, after speaker/cooldown.

        A repeated ID never extends or reopens a grant, even after consumption
        or expiry. Clearing, muting, cancellation and busy mode invalidate it.
        The host independently validates the same ID and question context.
        """
        if identifier is not None and (not isinstance(identifier, str)
                                       or re.fullmatch(r"[0-9a-f]{32}", identifier) is None):
            raise ValueError("Follow-up identifier must be 32 lowercase hexadecimal characters")
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 30:
            raise ValueError("Follow-up listening must last 1–30 seconds")
        with self._lock:
            if identifier is None:
                if self._followup_id is None:
                    return False
                self._followup_id = None
            else:
                if (identifier in self._followup_seen or not self._enabled
                        or self._busy or self._stop.is_set()):
                    return False
                self._followup_id = identifier
                self._followup_seen.append(identifier)
                self._followup_from = time.monotonic()
                self._followup_until = self._followup_from + seconds
            self._epoch += 1
            self._changed.set()
            return True

    def set_playback_active(self, active):
        """Enable rolling wake checks without interrupting ordinary capture.

        A transition invalidates only a pending playback probe. Repeated state
        updates must not reset a request, follow-up window or the microphone.
        """
        if type(active) is not bool:
            raise ValueError("Playback active must be a boolean")
        with self._lock:
            if self._playback_active != active:
                self._playback_active = active
                self._playback_generation += 1

    def request_ptt(self):
        with self._lock:
            if (self._thread is None or not self._thread.is_alive() or self._stop.is_set()
                    or self._pending_ptt or self._ptt_active or self._transcribing or self._busy):
                return False
            self._pending_ptt = True
            self._changed.set()
            return True

    def set_busy(self, busy):
        if type(busy) is not bool:
            raise ValueError("Voice busy mode must be a boolean")
        with self._lock:
            if self._busy != busy:
                self._busy = busy
                if busy:
                    self._followup_id = None
                self._epoch += 1
                self._pending_ptt = False
                self._changed.set()

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
        # A wake-only probe runs while capture continues; final recognition
        # uses the same model serially, never two concurrent engine calls.
        with self._model_lock:
            return self._recognize(audio)

    def _recognize(self, audio):
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

    def _start_probe(self, audio, voiced):
        if self._probe_thread is not None and self._probe_thread.is_alive():
            return None
        probe = {"done": threading.Event(), "voiced": voiced, "text": None, "error": False, "handled": False}

        def recognize():
            try:
                probe["text"] = self._transcribe(audio)
            except Exception:
                probe["error"] = True
            finally:
                probe["done"].set()

        self._probe_thread = threading.Thread(target=recognize, name="modulate-wake-probe", daemon=True)
        self._probe_thread.start()
        return probe

    def _capture(self, ptt):
        with self._lock:
            if self._stop.is_set() or (not ptt and not self._enabled):
                return None
            epoch = self._epoch
            followup_id = (self._followup_id if not self._busy
                           and self._followup_from <= time.monotonic() < self._followup_until else None)
            followup_until = self._followup_until
        import sounddevice as sd

        if self._selected is None:
            self._selected = select_input_device(sd, self.device)
        index, identity = self._selected
        info = sd.query_devices(index, "input")
        if (info["name"], info["hostapi"]) != identity:
            raise VoiceError("Selected microphone changed; choose its index again instead of switching silently")
        self._clear_audio()
        converter = PCMResampler()
        try:
            activity = SpeechActivity()
        except Exception:
            raise VoiceError("Local speech activity model unavailable; check the installed speech dependencies") from None
        native_blocks = 0
        audio_blocks = playback_next_block = 0
        voiced = 0
        probe = completed = None
        completed_voiced = 0
        confirmed = False
        playback_confirmed = False
        last_audio = started = time.monotonic()
        awaiting_command = self._gate.armed(started)
        with sd.RawInputStream(device=index, channels=1, samplerate=CAPTURE_RATE,
                               blocksize=CAPTURE_BLOCK_SAMPLES, dtype="int16",
                               latency=INPUT_LATENCY_SECONDS, callback=self._callback) as stream:
            while not self._stop.is_set():
                with self._lock:
                    if epoch != self._epoch or (not ptt and (not self._enabled or self._pending_ptt)):
                        return None
                    playback = self._playback_active and not self._busy
                    playback_generation = self._playback_generation
                if (probe is not None and probe.get("playback") and not probe["handled"]
                        and (not playback or probe["playback_generation"] != playback_generation)):
                    # An old worker can finish, but cannot arm a new listening
                    # session after the route was stopped or replaced.
                    probe = None
                if followup_id and time.monotonic() >= followup_until and not self._vad.active:
                    return None  # The answer window ends silently; normal wake listening resumes.
                if self._overflow.is_set():
                    raise VoiceError(self._audio_problem or "Microphone audio gap; partial recording discarded")
                if not stream.active:
                    raise VoiceError("Selected microphone stream stopped; retrying the same device")
                if probe is not None and probe["done"].is_set() and not probe["handled"]:
                    if (probe.get("playback")
                            and not (completed is not None and completed.started_at == probe["segment_started_at"])
                            and not (self._vad.active and self._vad.started_at == probe["segment_started_at"])):
                        probe = None  # This rolling probe's audio has already been discarded.
                        continue
                    probe["handled"] = True
                    if probe["error"]:
                        raise VoiceError("Local wake recognition failed; partial recording discarded")
                    probe_text = probe["text"] or ""
                    if probe.get("playback"):
                        probe_text = _playback_wake_text(probe_text) or ""
                    remainder = wake_remainder(probe_text)
                    if remainder is not None:
                        # A fresh wake after rejected ambient speech belongs to
                        # its own request, without the earlier conversation.
                        offset = probe.get("offset", 0)
                        if offset:
                            origin = probe["segment_started_at"]
                            if completed is not None and completed.started_at == origin:
                                completed = Utterance(completed.audio[offset * BLOCK_BYTES:],
                                                      origin + offset * BLOCK_SECONDS)
                            elif self._vad.active and self._vad.started_at == origin:
                                self._vad.chunks = self._vad.chunks[offset:]
                                self._vad.started_at += offset * BLOCK_SECONDS
                            else:
                                raise VoiceError("Wake audio changed; partial recording discarded")
                        confirmed = True
                        playback_confirmed = bool(probe.get("playback"))
                        if not remainder:
                            self._gate.accept(probe_text, now=time.monotonic())
                            awaiting_command = True
                        self._emit("listening", "Wake phrase heard; pause three seconds when finished")
                    elif probe.get("playback"):
                        # Ambient playback need not retain a growing 25-second
                        # transcript. Trim only after a negative probe completes,
                        # never while a worker still refers to this buffer.
                        if (self._vad.active and completed is None
                                and self._vad.started_at == probe["segment_started_at"]):
                            trim = max(0, len(self._vad.chunks) - PLAYBACK_PROBE_BLOCKS)
                            self._vad.chunks = self._vad.chunks[trim:]
                            self._vad.started_at += trim * BLOCK_SECONDS
                        probe = None
                    elif playback:
                        # A normal silence-triggered probe may finish just
                        # after playback starts. Its negative result must not
                        # prevent the new rolling checks.
                        probe = None
                if completed is not None and not self._vad.active and (probe is None or probe["done"].is_set()):
                    if probe is not None and completed_voiced == probe["voiced"]:
                        text = probe["text"] or ""
                        if probe.get("playback"):
                            text = _playback_wake_text(text) or ""
                        remainder = wake_remainder(text)
                        if not remainder:
                            # Ambient speech or a bare/repeated wake phrase needs
                            # no second recognition gap. Keep this stream open,
                            # including any followup already in the VAD buffer.
                            completed, probe = None, None
                            confirmed = self._gate.armed(time.monotonic())
                            playback_confirmed = False
                        else:
                            return Utterance(completed.audio, completed.started_at, text, True,
                                             playback_wake=playback_confirmed)
                    else:
                        return Utterance(completed.audio, completed.started_at, invoked=confirmed,
                                         playback_wake=playback_confirmed)
                if ptt:
                    self._emit("listening", "Push-to-talk: pause three seconds when finished")
                elif followup_id:
                    self._emit("listening", "Listening for your answer; pause three seconds when finished")
                elif confirmed or self._gate.armed(time.monotonic()):
                    self._emit("listening", "Wake phrase heard; pause three seconds when finished")
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
                for audio in blocks:
                    audio_blocks += 1
                    speaking = activity.feed(audio)
                    voiced += int(speaking)
                    utterance = self._vad.feed(audio, timestamp, speaking=speaking)
                    if utterance is not None:
                        if ptt or followup_id:
                            if followup_id and utterance.started_at >= followup_until:
                                return None
                            return Utterance(utterance.audio, utterance.started_at,
                                             invoked=bool(followup_id), followup_id=followup_id)
                        if completed is not None:
                            joined = completed.audio + utterance.audio
                            if len(joined) >= MAX_AUDIO_BYTES:
                                raise VoiceError("Speech reached the 25-second limit; nothing submitted. Try a shorter request")
                            completed = Utterance(joined, completed.started_at)
                        else:
                            completed = utterance
                        completed_voiced = voiced
                    if (completed is not None and len(completed.audio) + len(self._vad.chunks) * BLOCK_BYTES >= MAX_AUDIO_BYTES):
                        raise VoiceError("Speech reached the 25-second limit; nothing submitted. Try a shorter request")
                    rolling = (playback and not ptt and not followup_id and not confirmed
                               and not self._gate.armed(timestamp))
                    if (rolling and probe is None and self._vad.active and self._vad.voiced >= 3
                            and audio_blocks >= playback_next_block
                            and len(self._vad.chunks) >= PLAYBACK_PROBE_INTERVAL_BLOCKS):
                        offset = max(0, len(self._vad.chunks) - PLAYBACK_PROBE_BLOCKS)
                        fresh = self._start_probe(b"".join(self._vad.chunks[offset:]), voiced)
                        if fresh is not None:
                            fresh.update(playback=True, playback_generation=playback_generation,
                                         offset=offset, end_chunk=len(self._vad.chunks),
                                         segment_started_at=self._vad.started_at)
                            probe = fresh
                            playback_next_block = audio_blocks + PLAYBACK_PROBE_INTERVAL_BLOCKS
                    retry_probe = (probe is not None and probe["handled"] and not probe.get("playback")
                                   and wake_remainder(probe["text"] or "") is None
                                   and voiced >= probe["voiced"] + 3 and completed is None)
                    if (not rolling and not ptt and not followup_id and (probe is None or retry_probe) and not confirmed
                            and not self._gate.armed(timestamp) and self._vad.active
                            and self._vad.silence >= 20 and self._vad.voiced >= 3):
                        offset = max(0, probe["end_chunk"] - 10) if retry_probe else 0
                        fresh = self._start_probe(b"".join(self._vad.chunks[offset:]), voiced)
                        if fresh is not None:
                            fresh.update(offset=offset, end_chunk=len(self._vad.chunks),
                                         segment_started_at=self._vad.started_at)
                            probe = fresh
                if confirmed and not self._gate.armed(time.monotonic()) and not self._vad.active and completed is None:
                    confirmed = False
                if awaiting_command and not self._gate.armed(time.monotonic()) and not self._vad.active and completed is None:
                    if self.on_unclear is not None:
                        self._gate.reset()
                        return Utterance(b"", started, transcript="", invoked=True)
                    awaiting_command = False
                if ptt and not self._vad.active and native_blocks >= PTT_NO_SPEECH_BLOCKS:
                    message = "No speech detected; try push-to-talk again"
                    self._feedback_message(message)
                    self._emit("idle", message)
                    if self.on_unclear is not None:
                        return Utterance(b"", started, transcript="", followup_id=followup_id)
                    return None
        return None

    def _clarify(self, reason, followup_id, epoch):
        with self._lock:
            if self._stop.is_set() or epoch != self._epoch or self._busy:
                return
            if followup_id:
                self._followup_id = None
            self._gate.reset()
        message = "Please say a complete request after Hey Meta, or use push-to-talk"
        if self.on_unclear is not None:
            try:
                accepted = self.on_unclear(reason, followup_id=followup_id)
            except Exception:
                raise VoiceError("Clarification handler failed; the question was not confirmed queued") from None
            message = ("Please repeat your request after the question" if accepted is not False
                       else "Could not ask for clarification; check the connection")
        self._feedback_message(message)
        self._emit("idle", message)

    def _deliver(self, text, utterance, ptt, epoch):
        with self._lock:
            if self._stop.is_set() or epoch != self._epoch or (not ptt and not self._enabled):
                return
            followup_id = utterance.followup_id
            if followup_id and (self._busy or followup_id != self._followup_id
                                or not self._followup_from <= utterance.started_at < self._followup_until):
                return
        now = time.monotonic()
        invoked = ptt or bool(followup_id) or utterance.invoked or self._gate.armed(utterance.started_at)
        if ptt or followup_id:
            text = text.strip()
            remainder = wake_remainder(text)
            request = text if remainder is None else remainder
        else:
            if utterance.playback_wake:
                # Never turn the media prefix into a command. If final ASR lost
                # the confirmed wake phrase, ask again instead of forwarding
                # arbitrary preceding audio as the user's instruction.
                text = _playback_wake_text(text) or ""
            request = self._gate.accept(text, now=now, started_at=utterance.started_at)
            if request is None and utterance.invoked and not utterance.playback_wake and wake_remainder(text) is None:
                # The trusted probe already heard the anchored wake phrase in
                # this same retained audio; final recognition may omit it.
                self._gate.reset()
                request = text.strip()
        if not request or not any(character.isalnum() for character in request):
            if invoked and (ptt or followup_id or wake_remainder(text) != ""):
                self._clarify("empty", followup_id, epoch)
                return
            if ptt:
                message = "No request recognized; try push-to-talk again"
                self._feedback_message(message)
                self._emit("idle", message)
            elif not self._gate.armed(now):
                self._emit("wake_listening", self._wake_status())
            return
        if len(request) > 2000:
            raise VoiceError("Local transcript exceeded the request limit")
        with self._lock:
            if self._stop.is_set() or epoch != self._epoch:
                return
            busy = self._busy
        if CANCEL_PATTERN.fullmatch(request.strip()):
            with self._lock:
                self._followup_id = None
                self._epoch += 1
                self._changed.set()
            try:
                accepted = self.on_cancel() if self.on_cancel is not None else False
            except Exception:
                raise VoiceError("Cancellation handler failed; cancellation was not confirmed") from None
            message = "Cancellation requested" if accepted is not False else "Nothing was cancelled; check Studio"
            self._feedback_message(message)
            self._emit("wake_listening" if busy else "idle", message)
            return
        if busy:
            self._emit("wake_listening", "Working; say Hey Meta cancel build")
            return
        if re.sub(r"[^a-z ]", "", request.lower()).strip() in INCOMPLETE_REQUESTS:
            self._clarify("incomplete", followup_id, epoch)
            return
        with self._lock:
            if self._stop.is_set() or epoch != self._epoch:
                return
            if followup_id:
                self._followup_id = None  # Consume once, even if the host rejects or disconnects.
        try:
            accepted = (self.on_request(request, followup_id=followup_id) if followup_id
                        else self.on_request(request))
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
                        if epoch != self._epoch or (not ptt and (self._pending_ptt or not self._enabled)):
                            continue
                        self._transcribing = True
                    if utterance.transcript is not None:
                        text = utterance.transcript
                    else:
                        if ptt or utterance.invoked or self._gate.armed(utterance.started_at):
                            self._emit("transcribing", "Transcribing locally; microphone is paused")
                        else:
                            self._emit("wake_listening", "Checking locally for Hey Meta; microphone is paused")
                        text = self._transcribe(utterance.audio)
                    self._deliver(text, utterance, ptt, epoch)
                    del text, utterance
                except Exception as error:
                    with self._lock:
                        if self._stop.is_set() or epoch != self._epoch:
                            continue
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
