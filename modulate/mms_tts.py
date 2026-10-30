"""Local Meta MMS speech. A separate CPU worker holds weights in memory.

No provider calls, character accounting, text files or audio files. Cancellation
kills the worker so a late reply cannot escape into the next request.
"""
import json
import os
from pathlib import Path
import selectors
import struct
import subprocess
import threading
import time

from .tts import TTSError, MAX_AUDIO_BYTES, MAX_TEXT_CHARACTERS, MAX_TEXT_BYTES


class MMSError(TTSError):
    def __init__(self, category):
        self.category, self.status = category, None
        Exception.__init__(self, "Meta MMS speech " + {
            "configuration": "is not installed", "text": "text is empty or too long",
            "busy": "is still running", "cancelled": "was cancelled",
            "timeout": "timed out", "audio": "returned invalid audio",
            "worker": "is temporarily unavailable"}.get(category, "is unavailable"))


class MMSTTS:
    def __init__(self, *, python=None, model_dir=None, timeout=90, command=None):
        self.python = python or os.environ.get("MODULATE_MMS_PYTHON", "")
        self.model_dir = model_dir or os.environ.get("MODULATE_MMS_MODEL_DIR", "")
        self.timeout = timeout
        self.command = command  # Dependency injection for process-boundary tests.
        self.process = None
        self.lock = threading.Lock()

    def status(self):
        return {"provider": "meta_mms", "model": "facebook/mms-tts-eng", "local": True,
                "configured": bool(self.command or self.python and self.model_dir
                                   and Path(self.python).is_file() and Path(self.model_dir).is_dir())}

    def close(self):
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=.3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            process.stdin.close()
            process.stdout.close()

    def _read(self, size, cancel, deadline):
        data = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while len(data) < size:
                if cancel.is_set(): raise MMSError("cancelled")
                if time.monotonic() >= deadline: raise MMSError("timeout")
                if not selector.select(.05): continue
                chunk = os.read(self.process.stdout.fileno(), min(size-len(data), 65536))
                if not chunk: raise MMSError("worker")
                data.extend(chunk)
        return bytes(data)

    def synthesize(self, text, cancel):
        if (type(text) is not str or not text.strip() or len(text) > MAX_TEXT_CHARACTERS
                or len(text.encode("utf-8")) > MAX_TEXT_BYTES or "\x00" in text):
            raise MMSError("text")
        if cancel.is_set(): raise MMSError("cancelled")
        if not self.lock.acquire(blocking=False): raise MMSError("busy")
        try:
            if not self.status()["configured"]: raise MMSError("configuration")
            if self.process is None or self.process.poll() is not None:
                self.close()
                command = self.command or [self.python, "-I", str(Path(__file__).with_name("mms_worker.py")), self.model_dir]
                self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                stderr=subprocess.DEVNULL, bufsize=0,
                                                env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
            self.process.stdin.write((json.dumps({"text": text}, ensure_ascii=False) + "\n").encode())
            deadline = time.monotonic() + self.timeout
            size = struct.unpack("!I", self._read(4, cancel, deadline))[0]
            if not 0 < size <= MAX_AUDIO_BYTES or size % 2: raise MMSError("audio")
            audio = self._read(size, cancel, deadline)
            if cancel.is_set(): raise MMSError("cancelled")
            return audio
        except MMSError:
            self.close()
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            self.close()
            raise MMSError("worker") from None
        finally:
            self.lock.release()
