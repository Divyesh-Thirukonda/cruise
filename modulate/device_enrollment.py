"""Physical, bounded first enrollment for a preloaded Modulate gadget.

This service accepts a companion origin/certificate/credential, never executable
code or a caller-selected file path. The Mac pins the on-screen TLS fingerprint
before sending the one-use code; a separate fresh device-button press commits it.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit

MAX_BODY = 16_384
WINDOW_SECONDS = 300
MAX_ATTEMPTS = 5


class EnrollmentError(Exception):
    def __init__(self, message, status=400, reason="invalid_enrollment"):
        super().__init__(message)
        self.status = status
        self.reason = reason


def _address(value):
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise EnrollmentError("Use a literal local-network address") from None
    if address.version == 6 and address.scope_id is not None:
        raise EnrollmentError("Use an address without a scope identifier")
    # A dual-stack IPv6 listener reports IPv4 peers as ::ffff:a.b.c.d.
    if address.version == 6 and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def usable_address(value):
    address = _address(value)
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
        raise EnrollmentError("Use a reachable local-network address")
    return str(address)


def local_address(family=socket.AF_UNSPEC):
    """Read configured addresses; never probe an Internet service for discovery."""
    candidates = []
    try:
        candidates = subprocess.run(["hostname", "-I"], capture_output=True, text=True,
                                    timeout=2, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        candidates += [entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_UNSPEC)]
    except OSError:
        pass
    addresses = []
    for candidate in candidates:
        try:
            address = _address(usable_address(candidate))
            if family == socket.AF_INET and address.version != 4:
                continue
            if address not in addresses:
                addresses.append(address)
        except EnrollmentError:
            pass
    # Campus/guest networks can isolate their IPv4 addresses while local IPv6
    # remains reachable. Prefer a configured global IPv6 address, then IPv4.
    addresses.sort(key=lambda address: 0 if address.version == 6 and address.is_global
                   else 1 if address.version == 4 else 2)
    return str(addresses[0]) if addresses else None


def _exists(path):
    return path.exists() or path.is_symlink()


def _private_bytes(path, content):
    """Exclusive creation: never follow a symlink or replace an existing file."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        path.unlink(missing_ok=True)
        raise


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("non-finite")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


class EnrollmentServer:
    def __init__(self, directory, enrollment_path, port=8790, *, clock=None, address=None):
        self.directory = Path(directory)
        self.enrollment_path = Path(enrollment_path)
        self.port = port
        self.clock = clock or time.monotonic
        self.address = address
        self.address_override = address
        self.lock = threading.RLock()
        self.server = None
        self.worker = None
        self.fingerprint = None
        self.error = None
        self.code = None
        self.deadline = 0.0
        self.attempts = 0
        self.generation = 0
        self.pending = None
        self.receipt = None
        self.closed_reason = "setup_closed"

    def start(self):
        with self.lock:
            if self.server is not None:
                return True
            if _exists(self.enrollment_path):
                return False
            try:
                if self.directory.is_symlink():
                    raise ValueError("Setup directory cannot be a symlink")
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.directory.chmod(0o700)
                cert = self.directory / "setup-cert.pem"
                key = self.directory / "setup-key.pem"
                if _exists(cert) != _exists(key):
                    raise ValueError("Incomplete setup identity")
                if not _exists(cert):
                    with tempfile.TemporaryDirectory(dir=self.directory) as temporary:
                        staging = Path(temporary)
                        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                                        "ec_paramgen_curve:prime256v1", "-sha256", "-nodes", "-days", "365",
                                        "-subj", "/CN=Modulate device setup", "-keyout", str(staging / "key.pem"),
                                        "-out", str(staging / "cert.pem")], check=True, capture_output=True, timeout=10)
                        _private_bytes(key, (staging / "key.pem").read_bytes())
                        _private_bytes(cert, (staging / "cert.pem").read_bytes())
                if cert.is_symlink() or key.is_symlink() or key.stat().st_mode & 0o077:
                    raise ValueError("Setup identity permissions")
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                context.load_cert_chain(cert, key)
                self.fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()[:20]
                self.address = self.address or local_address()
                try:
                    self.server = _IPv6Server(("::", self.port), _handler(self), context)
                except OSError:
                    self.server = _Server(("0.0.0.0", self.port), _handler(self), context)
                    if self.address and _address(self.address).version != 4:
                        self.address = local_address(socket.AF_INET)
                self.port = self.server.server_address[1]
                self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
                self.worker.start()
                self.error = None
                return True
            except (OSError, ValueError, ssl.SSLError, subprocess.SubprocessError):
                if self.server:
                    self.server.server_close()
                self.server = None
                self.error = "Device setup is unavailable; ask for a device software update."
                return False

    def close(self):
        with self.lock:
            server, worker = self.server, self.worker
            self.server = None
            self.code = None
            self.pending = None
        if server:
            server.shutdown()
            server.server_close()
        if worker:
            worker.join(timeout=4)

    def _expire(self):
        if self.code is not None and self.clock() >= self.deadline:
            if self.pending:
                self._record("expired")
            self.pending = None
            self.code = None
            self.closed_reason = "setup_expired"
        if self.receipt and self.clock() >= self.receipt["until"]:
            self.receipt = None

    def snapshot(self):
        with self.lock:
            self._expire()
            result = {"available": self.server is not None and not _exists(self.enrollment_path),
                      "address": self.address, "port": self.port, "fingerprint": self.fingerprint,
                      "expires_in": max(0, int(self.deadline - self.clock())) if self.code else 0,
                      "completed": bool(self.receipt and self.receipt["status"] == "complete")}
            if self.code:
                result["code"] = self.code
            if self.pending:
                result["pending"] = {"id": self.pending["id"], "host_address": self.pending["host_address"]}
            if self.error:
                result["error"] = self.error
            return result

    def open_window(self):
        """Call only from a fresh physical A-button action, never a network route."""
        with self.lock:
            if self.server is None or _exists(self.enrollment_path):
                return self.snapshot()
            self.generation += 1
            self.code = None
            self.pending = None
            self.receipt = None
            self.attempts = 0
            self.closed_reason = "setup_closed"
            family = socket.AF_INET if self.server.address_family == socket.AF_INET else socket.AF_UNSPEC
            self.address = self.address_override or local_address(family)
            if self.address and family == socket.AF_INET and _address(self.address).version != 4:
                self.address = local_address(socket.AF_INET)
            if not self.address:
                self.error = "Connect the device to Wi-Fi, then press A to retry."
                return self.snapshot()
            self.code = f"{secrets.randbelow(100_000_000):08d}"
            self.deadline = self.clock() + WINDOW_SECONDS
            self.error = None
            return self.snapshot()

    def _record(self, status, reason=None):
        if self.pending:
            self.receipt = {"id": self.pending["id"], "peer": self.pending["host_address"],
                            "code": self.code, "status": status, "until": self.clock() + WINDOW_SECONDS}
            if reason:
                self.receipt["reason"] = reason

    def close_window(self, reason="setup_closed"):
        with self.lock:
            self._record("rejected", reason)
            self.pending = None
            self.code = None
            self.closed_reason = reason
            self.generation += 1

    def _failed_attempt(self):
        self.attempts += 1
        if self.attempts >= MAX_ATTEMPTS:
            self.close_window("attempts_exhausted")
            self.error = "Too many attempts. Press A for a new setup code."

    def _authorize(self, code):
        self._expire()
        if _exists(self.enrollment_path):
            raise EnrollmentError("This device is already linked", 409, "already_enrolled")
        if self.code is None or self.server is None:
            reason = self.closed_reason if self.server is not None else "setup_closed"
            raise EnrollmentError("Open setup on the device first", 409, reason)
        if type(code) is not str or not secrets.compare_digest(code, self.code):
            self._failed_attempt()
            reason = "attempts_exhausted" if self.attempts >= MAX_ATTEMPTS else "wrong_code"
            raise EnrollmentError("Setup code not accepted", 403, reason)

    def malformed(self):
        with self.lock:
            self._expire()
            if self.code is not None:
                self._failed_attempt()

    def propose(self, body, peer):
        with self.lock:
            self._authorize(body.get("code") if type(body) is dict else None)
            if self.pending:
                raise EnrollmentError("A setup request is already waiting on the device", 409, "request_pending")
            generation = self.generation
        try:
            if type(body) is not dict or set(body) != {"code", "enrollment"}:
                raise EnrollmentError("Invalid setup request")
            enrollment, host_address = self._validate(body["enrollment"], peer)
        except EnrollmentError:
            self.malformed()
            raise
        with self.lock:
            self._authorize(body["code"])
            if generation != self.generation or self.pending:
                raise EnrollmentError("Setup window changed; try the current code", 409, "setup_closed")
            request_id = secrets.token_hex(16)
            self.pending = {"id": request_id, "host_address": host_address, "enrollment": enrollment}
            return {"id": request_id, "status": "awaiting_confirmation"}

    def _validate(self, data, peer):
        if type(data) is not dict or set(data) != {"host_url", "device_key", "ca_pem"}:
            raise EnrollmentError("Only companion enrollment is accepted")
        if type(data["host_url"]) is not str or len(data["host_url"]) > 150:
            raise EnrollmentError("Invalid companion origin")
        try:
            url = urlsplit(data["host_url"])
            host = usable_address(url.hostname)
            if (url.scheme != "https" or url.port != 8788 or url.username or url.password
                    or url.path not in ("", "/") or url.query or url.fragment):
                raise ValueError()
            if host != usable_address(peer):
                raise EnrollmentError("Companion address must match the connecting Mac", 403, "source_mismatch")
        except (ValueError, TypeError):
            raise EnrollmentError("Use the Mac's HTTPS device endpoint on port 8788") from None
        key, pem = data["device_key"], data["ca_pem"]
        if type(key) is not str or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key) is None:
            raise EnrollmentError("Invalid companion credential")
        if (type(pem) is not str or len(pem) > 8192 or re.fullmatch(
                r"-----BEGIN CERTIFICATE-----\r?\n[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*", pem) is None):
            raise EnrollmentError("Use one public companion certificate")
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(cadata=pem)
            with tempfile.NamedTemporaryFile(dir=self.directory, mode="w", suffix=".pem") as stream:
                stream.write(pem)
                stream.flush()
                result = subprocess.run(["openssl", "x509", "-in", stream.name, "-noout", "-checkip", host],
                                        capture_output=True, timeout=3)
                # Some deployed OpenSSL versions exit zero even when -checkip
                # reports a mismatch. Require the exact positive result; empty,
                # negative or unfamiliar output must never authorize enrollment.
                expected = f"IP {host} does match certificate".encode("ascii")
                if result.returncode != 0 or result.stdout.strip() != expected:
                    raise ValueError("Certificate address mismatch")
        except (OSError, ValueError, ssl.SSLError, subprocess.SubprocessError):
            raise EnrollmentError("Companion certificate does not match its address") from None
        return {"host_url": data["host_url"].rstrip("/"), "device_key": key, "ca_pem": pem}, host

    def status(self, body, peer):
        peer = str(_address(peer))
        with self.lock:
            self._expire()
            if type(body) is not dict or set(body) != {"id", "code"}:
                raise EnrollmentError("Invalid setup receipt")
            if type(body["id"]) is not str or type(body["code"]) is not str:
                raise EnrollmentError("Invalid setup receipt")
            receipt = self.receipt
            if (receipt and secrets.compare_digest(body["id"], receipt["id"])
                    and secrets.compare_digest(body["code"], receipt["code"] or "")
                    and peer == receipt["peer"]):
                result = {"id": receipt["id"], "status": receipt["status"]}
                if receipt.get("reason"):
                    result["reason"] = receipt["reason"]
                return result
            self._authorize(body["code"])
            if self.pending and body["id"] == self.pending["id"] and peer == self.pending["host_address"]:
                return {"id": body["id"], "status": "awaiting_confirmation"}
            self._failed_attempt()
            raise EnrollmentError("Setup receipt not found", 404, "receipt_not_found")

    def confirm(self, request_id):
        """Commit one exact, unexpired proposal after a fresh physical press."""
        with self.lock:
            self._expire()
            if not self.pending or self.pending["id"] != request_id or _exists(self.enrollment_path):
                return False
            cert_path = None
            cert_created = False
            temporary = None
            try:
                parent = self.enrollment_path.parent
                parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                data = self.pending["enrollment"]
                cert_path = parent / ("enrolled-cert-" + secrets.token_hex(16) + ".pem")
                _private_bytes(cert_path, data["ca_pem"].encode("ascii"))
                cert_created = True
                with tempfile.NamedTemporaryFile(dir=parent, prefix=".enrollment-", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(json.dumps({"host_url": data["host_url"], "device_key": data["device_key"],
                                             "ca_file": cert_path.name}).encode())
                    stream.flush()
                    os.fsync(stream.fileno())
                # link is atomic and refuses any existing target, including a symlink.
                # Do not use replace(), which could overwrite a concurrent enrollment.
                os.link(temporary, self.enrollment_path)
                self._record("complete")
                self.pending = None
                self.code = None
                self.error = None
                return True
            except (OSError, ValueError, UnicodeError):
                if cert_created:
                    try:
                        cert_path.unlink(missing_ok=True)
                    except OSError:
                        pass  # An orphan public certificate grants no access.
                self.error = "Setup could not be saved. Keep the current configuration and try again."
                self._record("rejected", "save_failed")
                self.pending = None
                self.code = None
                return False
            finally:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass  # Keep the committed enrollment valid after success.


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 4

    def __init__(self, address, handler, context):
        self.context = context
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(address, handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3)
        try:
            return self.context.wrap_socket(connection, server_side=True), address
        except (OSError, ssl.SSLError):
            connection.close()
            raise

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # No request bodies, credentials or traceback locals in service logs.


class _IPv6Server(_Server):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _handler(owner):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def send(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def do_GET(self):
            self.send(404, {"error": "Only device enrollment is available"})

        def do_POST(self):
            try:
                if self.path not in {"/enroll", "/status"}:
                    return self.send(404, {"error": "Unknown setup action"})
                if (self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1
                        or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json"):
                    raise ValueError()
                size = int(self.headers["Content-Length"])
                if not 0 < size <= MAX_BODY:
                    raise ValueError()
                body = _json(self.rfile.read(size))
                if type(body) is not dict:
                    raise ValueError()
                action = owner.propose if self.path == "/enroll" else owner.status
                self.send(200, action(body, str(_address(self.client_address[0]))))
            except EnrollmentError as error:
                self.send(error.status, {"error": str(error), "reason": error.reason})
            except (ValueError, TypeError, RecursionError, OSError):
                owner.malformed()
                try:
                    self.send(400, {"error": "Expected a bounded setup request", "reason": "invalid_enrollment"})
                except OSError:
                    pass
    return Handler
