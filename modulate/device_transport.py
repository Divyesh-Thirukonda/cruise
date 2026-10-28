"""A controller credential can access only its enrolled, certificate-pinned host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request


class TransportError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransportError("Companion redirect refused")


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
        if action not in {"heartbeat", "request", "pair", "rollback"}:
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
                raw = response.read(256 * 1024 + 1)
                if len(raw) > 256 * 1024:
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
