"""Host-only ElevenLabs synthesis with transient PCM and durable input limits.

REST: https://elevenlabs.io/docs/api-reference/text-to-speech/stream
PCM: https://elevenlabs.io/docs/overview/capabilities/text-to-speech
Models: https://elevenlabs.io/docs/overview/models

The character ledger is an application input ceiling, not an account credit or
dollar balance. Unknown outcomes retain their full reservation. No text, audio,
API key, provider response body or request URL is written to that ledger.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request

from .cloud_provider import CloudConfigurationError, CloudProvider


MAX_TEXT_CHARACTERS = 1200
MAX_TEXT_BYTES = 4800
SAMPLE_RATE = 24_000
MAX_AUDIO_BYTES = SAMPLE_RATE * 2 * 90
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_ORIGIN = "https://api.elevenlabs.io"
_MESSAGES = {
    "configuration": "ElevenLabs speech is not configured",
    "text": "Speech text is empty, unsupported or too long",
    "budget": "The configured speech character ceiling has been reached",
    "ledger": "Speech accounting is unavailable; no further synthesis was started",
    "busy": "Another speech synthesis request is still stopping or running",
    "cancelled": "Speech synthesis was cancelled",
    "timeout": "ElevenLabs speech synthesis timed out",
    "http": "ElevenLabs rejected the speech request",
    "network": "ElevenLabs speech is temporarily unavailable",
    "redirect": "ElevenLabs speech redirect was refused",
    "audio": "ElevenLabs returned invalid or oversized speech audio",
}


class TTSError(Exception):
    """A content-free error suitable for UI and telemetry."""

    def __init__(self, category="network", *, status=None):
        self.category = category if category in _MESSAGES else "network"
        self.status = status if type(status) is int and 100 <= status <= 599 else None
        suffix = f" (HTTP {self.status})" if self.category == "http" and self.status else ""
        super().__init__(_MESSAGES[self.category] + suffix)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TTSError("redirect")


class _CharacterLedger:
    def __init__(self, directory, limit):
        if type(limit) is not int or not 0 <= limit <= 1_000_000:
            raise ValueError("Speech character ceiling must be an integer from 0 to 1000000")
        self.directory = Path(directory)
        self.path = self.directory / "tts-character-ledger.json"
        self.lock_path = self.directory / "tts-character-ledger.lock"
        self.limit = limit

    def _change(self, characters, *, settled=False):
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(descriptor, "a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if self.path.exists():
                    if self.path.stat().st_size > 4096:
                        raise ValueError("Invalid ledger")
                    def unique_fields(pairs):
                        value = {}
                        for name, item in pairs:
                            if name in value:
                                raise ValueError("Duplicate ledger field")
                            value[name] = item
                        return value
                    value = json.loads(self.path.read_text(), object_pairs_hook=unique_fields)
                    fields = {"version", "reserved_characters", "settled_characters",
                              "requests", "uncertain_requests"}
                    if (type(value) is not dict or set(value) != fields
                            or any(type(value[key]) is not int or value[key] < 0 for key in fields)
                            or value["version"] != 1
                            or value["settled_characters"] > value["reserved_characters"]
                            or value["uncertain_requests"] > value["requests"]):
                        raise ValueError("Invalid ledger")
                else:
                    value = {"version": 1, "reserved_characters": 0, "settled_characters": 0,
                             "requests": 0, "uncertain_requests": 0}
                if settled:
                    if (value["uncertain_requests"] < 1
                            or value["settled_characters"] + characters > value["reserved_characters"]):
                        raise ValueError("Invalid settlement")
                    value["settled_characters"] += characters
                    value["uncertain_requests"] -= 1
                else:
                    if value["reserved_characters"] + characters > self.limit:
                        raise TTSError("budget")
                    value["reserved_characters"] += characters
                    value["requests"] += 1
                    value["uncertain_requests"] += 1
                with tempfile.NamedTemporaryFile(mode="w", dir=self.directory,
                                                 prefix=".tts-ledger-", delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(value, stream, separators=(",", ":"))
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(self.path)
                temporary = None
                directory_fd = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        except TTSError:
            raise
        except (OSError, ValueError, TypeError, RecursionError):
            raise TTSError("ledger") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def reserve(self, characters):
        self._change(characters)

    def settle(self, characters):
        self._change(characters, settled=True)


class ElevenLabsTTS:
    """One bounded synthesis at a time; cancellation never returns late audio.

    The worker can remain in a bounded socket read after caller cancellation.
    Until it exits, another request is rejected rather than spawning more work.
    Inject an opener with open(request, timeout=...) for network-free tests.
    """

    def __init__(self, state_dir, *, api_key=None, voice_id=None, model_id=None,
                 max_chars=5000, opener=None, timeout=10, total_timeout=45):
        try:
            self._cloud = CloudProvider()
        except CloudConfigurationError:
            raise TTSError("configuration") from None
        self._key = api_key if api_key is not None else os.environ.get("ELEVENLABS_API_KEY", "")
        self.voice_id = voice_id if voice_id is not None else os.environ.get("ELEVENLABS_VOICE_ID", "")
        self.model_id = model_id if model_id is not None else os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")
        if (type(self._key) is not str or len(self._key) > 1024
                or (self._key and (not self._key.isascii() or not self._key.isprintable()
                                   or any(char.isspace() for char in self._key)))
                or type(self.voice_id) is not str
                or (self.voice_id and not _IDENTIFIER.fullmatch(self.voice_id))
                or type(self.model_id) is not str or not _IDENTIFIER.fullmatch(self.model_id)):
            raise TTSError("configuration")
        for number in (timeout, total_timeout):
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 < number <= 120:
                raise ValueError("Speech timeouts must be positive and no more than 120 seconds")
        self.timeout = min(timeout, total_timeout)
        self.total_timeout = total_timeout
        self._ledger = _CharacterLedger(state_dir, max_chars)
        self._opener = opener if opener is not None else urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())
        self._active = threading.Lock()

    def status(self):
        return {"provider": "elevenlabs", "model": self.model_id, "voice": self.voice_id or None,
                "configured": bool((self._key or self._cloud.enabled) and self.voice_id)}

    @staticmethod
    def _text(text):
        try:
            if (type(text) is not str or not text.strip() or len(text) > MAX_TEXT_CHARACTERS
                    or len(text.encode("utf-8")) > MAX_TEXT_BYTES
                    or any((ord(char) < 32 and char not in "\r\n\t") or ord(char) == 127 for char in text)):
                raise ValueError("Invalid text")
        except (ValueError, UnicodeError):
            raise TTSError("text") from None
        return text

    def synthesize(self, text, cancel_event):
        text = self._text(text)
        if not self.status()["configured"]:
            raise TTSError("configuration")
        if cancel_event.is_set():
            raise TTSError("cancelled")
        if not self._active.acquire(blocking=False):
            raise TTSError("busy")
        done, abort = threading.Event(), threading.Event()
        result = {}
        deadline = time.monotonic() + self.total_timeout
        try:
            self._ledger.reserve(len(text))
            worker = threading.Thread(target=self._synthesize, args=(text, cancel_event, abort, deadline, result, done),
                                      name="modulate-elevenlabs", daemon=True)
            worker.start()
        except TTSError:
            self._active.release()
            raise
        except Exception:
            self._active.release()
            raise TTSError("network") from None
        while not done.wait(0.025):
            if cancel_event.is_set():
                abort.set()
                raise TTSError("cancelled")
            if time.monotonic() >= deadline:
                abort.set()
                raise TTSError("timeout")
        if cancel_event.is_set() or abort.is_set():
            raise TTSError("cancelled")
        if time.monotonic() >= deadline:
            raise TTSError("timeout")
        if "error" in result:
            raise result["error"] from None
        return result["audio"]

    def _synthesize(self, text, cancelled, abort, deadline, result, done):
        def check():
            if cancelled.is_set() or abort.is_set():
                raise TTSError("cancelled")
            if time.monotonic() >= deadline:
                raise TTSError("timeout")

        try:
            check()
            url = _ORIGIN + "/v1/text-to-speech/" + self.voice_id + "/stream?output_format=pcm_24000"
            payload = {"text": text, "model_id": self.model_id}
            headers = {"xi-api-key": self._key, "Content-Type": "application/json", "Accept": "audio/pcm"}
            if self._cloud.enabled:
                url, headers, payload = self._cloud.request("speech", {"voice_id": self.voice_id, "payload": payload})
            request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            # The gateway validates/buffers PCM before returning headers. Its
            # first byte may take longer than the direct provider's streaming
            # socket timeout; keep the existing overall deadline authoritative.
            socket_timeout = (max(.1, min(self.total_timeout, deadline - time.monotonic()))
                              if self._cloud.enabled else self.timeout)
            with self._opener.open(request, timeout=socket_timeout) as response:
                check()
                if response.geturl() != url:
                    raise TTSError("redirect")
                status = response.getcode()
                if status != 200:
                    raise TTSError("http", status=status)
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        expected = int(length)
                    except (ValueError, TypeError):
                        raise TTSError("audio") from None
                    if not 0 < expected <= MAX_AUDIO_BYTES or expected % 2:
                        raise TTSError("audio")
                else:
                    expected = None
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if mime not in {"audio/pcm", "audio/x-pcm", "audio/raw", "application/octet-stream"}:
                    raise TTSError("audio")
                data = bytearray()
                read = getattr(response, "read1", response.read)
                while True:
                    check()
                    chunk = read(min(65_536, MAX_AUDIO_BYTES + 1 - len(data)))
                    check()
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise TTSError("audio")
                    data.extend(chunk)
                    if len(data) > MAX_AUDIO_BYTES:
                        raise TTSError("audio")
                if not data or len(data) % 2 or (expected is not None and len(data) != expected):
                    raise TTSError("audio")
            check()
            self._ledger.settle(len(text))
            check()
            result["audio"] = bytes(data)
        except TTSError as error:
            result["error"] = error
        except urllib.error.HTTPError as error:
            result["error"] = TTSError("http", status=error.code)
            try:
                error.close()
            except OSError:
                pass
        except (TimeoutError,):
            result["error"] = TTSError("timeout")
        except Exception:
            result["error"] = TTSError("network")
        finally:
            self._active.release()
            done.set()
