"""A controller credential can access only its enrolled, certificate-pinned host."""
from __future__ import annotations

import json
import base64
import hashlib
import http.client
import os
from pathlib import Path
import ssl
import tempfile
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .deployment import CONNECT_LABEL

class TransportError(Exception):
    pass


SPEECH_FORMAT = "pcm_s16le_24000_mono"
MAX_SPEECH_BYTES = 4_320_000  # 90 s of 24 kHz mono signed 16-bit PCM.


def speech_descriptor(value):
    """Validate only the fixed, authenticated in-memory audio contract."""
    if (not isinstance(value, dict) or set(value) != {"id", "format", "bytes", "sha256"}
            or not isinstance(value["id"], str) or re.fullmatch(r"[0-9a-f]{32}", value["id"]) is None
            or value["format"] != SPEECH_FORMAT or type(value["bytes"]) is not int
            or not 2 <= value["bytes"] <= MAX_SPEECH_BYTES or value["bytes"] % 2
            or not isinstance(value["sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None):
        raise TransportError("Invalid speech audio descriptor")
    return dict(value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportError("Companion redirect refused")


class PendingCompanion:
    """Keep first-run guidance alive while strict enrollment is unavailable."""
    def __init__(self, enrollment):
        self.enrollment = enrollment
        self.delegate = None
        self.next_retry = 0.0

    @property
    def configured(self):
        return self.delegate is not None

    def _ready(self):
        if self.delegate is None and time.monotonic() >= self.next_retry:
            self.next_retry = time.monotonic() + 3
            try:
                self.delegate = Companion(self.enrollment)
            except (OSError, ValueError, KeyError, TypeError, TransportError):
                pass
        if self.delegate is None:
            raise TransportError(f"Device enrollment needed; follow {CONNECT_LABEL} setup")
        return self.delegate

    def post(self, action, data):
        return self._ready().post(action, data)

    def speech_audio(self, descriptor, cancel):
        return self._ready().speech_audio(descriptor, cancel)

    def transcribe_audio(self, audio):
        return self._ready().transcribe_audio(audio)


class Companion:
    def __init__(self, enrollment):
        path = Path(enrollment).resolve()
        if path.stat().st_mode & 0o077:
            raise TransportError("Enrollment must be readable only by its owner")
        self.configuration = json.loads(path.read_text())
        self.path = path
        url = urllib.parse.urlsplit(self.configuration["host_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
            raise TransportError("Enrollment requires an HTTPS companion origin")
        self.origin = self.configuration["host_url"].rstrip("/")
        self.key = self.configuration["device_key"]
        if not isinstance(self.key, str) or len(self.key) < 32 or not self.key.isascii() or any(c.isspace() for c in self.key):
            raise TransportError("Invalid controller credential")
        ca = path.parent / self.configuration["ca_file"]
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_verify_locations(cafile=str(ca))
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                 urllib.request.HTTPSHandler(context=context))

    def post(self, action, data):
        if action not in {"heartbeat", "request", "pair", "rollback", "cancel", "unclear", "audio", "audio/stop", "setup", "library"}:
            raise TransportError("Unknown companion action")
        try:
            body = json.dumps(data, allow_nan=False).encode()
        except (ValueError, TypeError, RecursionError):
            raise TransportError("Companion request must contain finite JSON") from None
        if len(body) > 256 * 1024:
            raise TransportError("Companion request is too large")
        request = urllib.request.Request(self.origin + "/device/" + action, data=body,
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        try:
            with self.opener.open(request, timeout=3) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise TransportError("Companion response is too large")
                result = json.loads(raw, parse_constant=_invalid_constant)
                if not isinstance(result, dict):
                    raise TransportError("Malformed companion response")
                return result
        except urllib.error.HTTPError as error:
            # Server validation messages are bounded, trusted application text.
            try:
                detail = json.loads(error.read(4096)).get("error", "Request rejected")
            except Exception:
                detail = "Request rejected"
            raise TransportError(str(detail)[:300]) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise TransportError("Companion unavailable; check the Mac studio and network") from None
        except (ValueError, TypeError):
            raise TransportError("Malformed companion response") from None

    def speech_audio(self, descriptor, cancel):
        """Fetch one enrolled host's bounded PCM on the speech worker only.

        No redirect or URL is accepted from the descriptor. Cancellation is
        checked between reads; a blocked connection/read has a three-second
        socket timeout. Expiry and authorization are checked again by the host.
        """
        descriptor = speech_descriptor(descriptor)
        if cancel.is_set():
            raise TransportError("Speech audio request cancelled")
        url = self.origin + "/device/speech"
        request = urllib.request.Request(url, data=json.dumps({"id": descriptor["id"]}).encode(),
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        deadline = time.monotonic() + 90
        try:
            with self.opener.open(request, timeout=3) as response:
                if response.geturl() != url:
                    raise TransportError("Speech audio redirect refused")
                if response.headers.get_content_type() not in {"application/octet-stream", "audio/pcm"}:
                    raise TransportError("Unexpected speech audio format")
                declared_format = response.headers.get("X-Modulate-Audio-Format")
                if declared_format is not None and declared_format != SPEECH_FORMAT:
                    raise TransportError("Unexpected speech audio format")
                declared_size = response.headers.get("Content-Length")
                if declared_size is not None and declared_size != str(descriptor["bytes"]):
                    raise TransportError("Speech audio length does not match its descriptor")
                raw = bytearray()
                while len(raw) <= descriptor["bytes"]:
                    if cancel.is_set():
                        raise TransportError("Speech audio request cancelled")
                    if time.monotonic() >= deadline:
                        raise TransportError("Speech audio request timed out")
                    chunk = response.read(min(65_536, descriptor["bytes"] + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                if cancel.is_set():
                    raise TransportError("Speech audio request cancelled")
                if time.monotonic() >= deadline:
                    raise TransportError("Speech audio request timed out")
                if len(raw) != descriptor["bytes"] or hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
                    raise TransportError("Speech audio integrity check failed")
                return bytes(raw)
        except urllib.error.HTTPError as error:
            # Error bodies can contain request or provider details; never read them.
            code = error.code
            error.close()
            raise TransportError(f"Speech audio unavailable or expired (HTTP {code})") from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise TransportError("Speech audio unavailable; check the companion connection") from None

    def transcribe_audio(self, audio):
        if type(audio) is not bytes or not 2 <= len(audio) <= 800000 or len(audio) % 2:
            raise TransportError("Invalid command recording")
        request = urllib.request.Request(self.origin + "/device/transcribe",
            data=json.dumps({"pcm": base64.b64encode(audio).decode("ascii")}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key})
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(16385)
                if len(raw) > 16384:
                    raise ValueError()
                result = json.loads(raw)
            if (type(result) is not dict or result.get("provider") != "meta_muse"
                    or type(result.get("text")) is not str or len(result["text"]) > 2000):
                raise ValueError()
            return result["text"]
        except urllib.error.HTTPError as error:
            error.close()
            raise TransportError("Muse transcription unavailable; request discarded. Try again or use Studio.") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, http.client.HTTPException):
            raise TransportError("Muse transcription unavailable; request discarded. Try again or use Studio.") from None


def save_private(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".private-", delete=False) as stream:
            temporary = Path(stream.name)
            temporary.chmod(0o600)
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _invalid_constant(value):
    raise ValueError("Non-finite JSON constant")
