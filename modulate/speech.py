"""Bounded local Meta wav2vec 2.0 recognition in a persistent CPU worker.

Weights are installed explicitly; runtime never downloads models, uploads audio,
or inherits provider credentials. Audio and transcripts stay in memory.
"""
import io
import json
import os
from pathlib import Path
import selectors
import struct
import subprocess
import threading
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
MAX_PCM = 16000 * 2 * 25


class SpeechError(RuntimeError):
    pass


class LocalSpeech:
    def __init__(self, *, python=None, model_dir=None, timeout=30, command=None):
        self.python = python or os.environ.get("MODULATE_ASR_PYTHON") or str(ROOT / ".venv-asr/bin/python")
        self.model_dir = model_dir or os.environ.get("MODULATE_ASR_MODEL_DIR") or str(ROOT / "brain/models/wav2vec2-base-960h")
        self.timeout, self.command = timeout, command
        self.process = None
        self.lock = threading.Lock()

    def close(self):
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=.3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            process.stdin.close()
            process.stdout.close()

    def _transfer(self, value, cancel, deadline, *, writing=False):
        stream = self.process.stdin if writing else self.process.stdout
        data = memoryview(value) if writing else bytearray()
        size, offset = len(value) if writing else value, 0
        with selectors.DefaultSelector() as selector:
            selector.register(stream, selectors.EVENT_WRITE if writing else selectors.EVENT_READ)
            while offset < size:
                if cancel.is_set():
                    raise SpeechError("Meta speech recognition was cancelled")
                if time.monotonic() >= deadline:
                    raise SpeechError("Meta speech recognition timed out")
                if not selector.select(.05):
                    continue
                try:
                    if writing:
                        offset += os.write(stream.fileno(), data[offset:offset + 65536])
                    else:
                        chunk = os.read(stream.fileno(), min(size - offset, 65536))
                        if not chunk:
                            raise SpeechError("Meta speech worker stopped")
                        data.extend(chunk)
                        offset += len(chunk)
                except BlockingIOError:
                    continue
        return bytes(data) if not writing else None

    def transcribe_pcm(self, audio, cancel=None):
        if type(audio) is not bytes or not 2 <= len(audio) <= MAX_PCM or len(audio) % 2:
            raise SpeechError("Expected at most 25 seconds of mono 16 kHz PCM")
        cancel = cancel if cancel is not None else threading.Event()
        if cancel.is_set():
            raise SpeechError("Meta speech recognition was cancelled")
        if not self.lock.acquire(blocking=False):
            raise SpeechError("Meta speech recognition is busy")
        try:
            if self.process is None or self.process.poll() is not None:
                self.close()
                if not self.command and not (Path(self.python).is_file() and Path(self.model_dir).is_dir()):
                    raise SpeechError("Local Meta speech model is not installed; run scripts/install_meta_asr.py")
                command = self.command or [self.python, "-I", str(Path(__file__).with_name("asr_worker.py")), self.model_dir]
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HF_HUB_OFFLINE": "1",
                         "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"})
                os.set_blocking(self.process.stdin.fileno(), False)
                os.set_blocking(self.process.stdout.fileno(), False)
            deadline = time.monotonic() + self.timeout
            self._transfer(struct.pack("!I", len(audio)) + audio, cancel, deadline, writing=True)
            size = struct.unpack("!I", self._transfer(4, cancel, deadline))[0]
            if not 2 <= size <= 8192:
                raise SpeechError("Meta speech worker returned invalid text")
            value = json.loads(self._transfer(size, cancel, deadline))
            if (type(value) is not str or len(value) > 2000
                    or any(ord(c) < 32 for c in value) or cancel.is_set()):
                raise SpeechError("Meta speech worker returned invalid or cancelled text")
            return value.strip()
        except SpeechError:
            self.close()
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            self.close()
            raise SpeechError("Local Meta speech recognition is unavailable") from None
        finally:
            self.lock.release()

    def transcribe(self, wav_bytes):
        if type(wav_bytes) is not bytes or len(wav_bytes) > MAX_PCM + 4096:
            raise SpeechError("Invalid WAV recording")
        try:
            with wave.open(io.BytesIO(wav_bytes)) as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, 16000, "NONE"):
                    raise ValueError()
                pcm = wav.readframes(400001)
                if len(pcm) != wav.getnframes() * 2:
                    raise ValueError()
        except (ValueError, wave.Error, EOFError):
            raise SpeechError("Expected a complete mono 16-bit 16 kHz WAV recording") from None
        return self.transcribe_pcm(pcm)
