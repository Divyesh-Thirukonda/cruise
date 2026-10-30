"""Invoked-command Muse ASR; ambient wake recognition remains on the Pi.

Official contract/pricing checked October 30, 2026:
https://dev.meta.ai/docs/speech-to-text
https://dev.meta.ai/docs/pricing-rate-limits
Audio exists only in memory. No retries or implicit provider fallback.
"""
import base64
import io
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
import wave

from .agent import AgentError
from .cloud_provider import CloudProvider
from .device_transport import NoRedirect

MODEL = "muse-voice-transcribe-1.0"
RATE = 16000
MAX_PCM = RATE * 2 * 25


def decode_pcm(data):
    if (type(data) is not dict or set(data) != {"pcm"} or type(data["pcm"]) is not str
            or len(data["pcm"]) > 4 * math.ceil(MAX_PCM / 3)):
        raise AgentError("Expected a bounded mono 16 kHz command recording")
    try:
        pcm = base64.b64decode(data["pcm"], validate=True)
    except (ValueError, UnicodeError):
        raise AgentError("Invalid command audio encoding") from None
    if not 2 <= len(pcm) <= MAX_PCM or len(pcm) % 2:
        raise AgentError("Command recording must be at most 25 seconds of mono PCM")
    return pcm


class MuseTranscriber:
    def __init__(self, ledger):
        self.ledger = ledger
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(NoRedirect())

    @property
    def provider(self):
        return "meta_muse" if os.environ.get("MODULATE_ASR_PROVIDER", "local") == "meta_muse" else "local"

    def transcribe(self, data, require_access):
        pcm = decode_pcm(data)
        if self.provider != "meta_muse":
            raise AgentError("Muse transcription is not enabled")
        if not self.lock.acquire(blocking=False):
            raise AgentError("A command is already being transcribed; try again shortly")
        try:
            require_access()
            try:
                cloud = CloudProvider()
                if not cloud.enabled:
                    raise ValueError()
                stream = io.BytesIO()
                with wave.open(stream, "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE)
                    wav.writeframes(pcm)
                payload = {"wav": base64.b64encode(stream.getvalue()).decode("ascii")}
                url, headers, payload = cloud.request("transcribe", payload)
            except ValueError:
                raise AgentError("Muse transcription gateway is not configured") from None
            # $0.18/hour = 50 microdollars/second. Round reservation up;
            # retain it on uncertain errors, as for existing generation calls.
            duration_ms = len(pcm) * 1000 // (RATE * 2)
            reservation = self.ledger.reserve(math.ceil(len(pcm) / (RATE * 2)) * 50)
            started = time.monotonic()
            request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
            require_access()
            try:
                with self.opener.open(request, timeout=12) as response:
                    raw = response.read(16385)
                    if len(raw) > 16384:
                        raise ValueError()
                    result = json.loads(raw)
                if (type(result) is not dict or result.get("model") != MODEL
                        or type(result.get("transcript")) is not str or len(result["transcript"]) > 2000
                        or any(ord(c) < 32 and c not in "\n\t" for c in result["transcript"])
                        or type(result.get("audioDurationMs")) is not int
                        or not 0 <= result["audioDurationMs"] - duration_ms <= 80):
                    raise ValueError()
            except urllib.error.HTTPError as error:
                error.close()  # Do not read a provider body containing private details.
                raise AgentError("Muse transcription unavailable; request discarded. Try again or use Studio.") from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                raise AgentError("Muse transcription unavailable; request discarded. Try again or use Studio.") from None
            self.ledger.settle(reservation, result["audioDurationMs"] // 1000 * 50)
            require_access()  # Revocation during the upload cannot deliver a command.
            return {"text": result["transcript"].strip(), "provider": "meta_muse", "model": MODEL,
                    "audio_ms": duration_ms, "transcription_ms": round((time.monotonic() - started) * 1000)}
        finally:
            self.lock.release()
