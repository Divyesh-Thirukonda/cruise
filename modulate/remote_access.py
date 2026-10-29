"""Explicitly paired public dashboards for one trusted local companion.

The relay is not an arbitrary HTTP proxy. A server secret authenticates the
fixed Vercel gateway, and a separate revocable browser token authorizes every
private read/action. Provider credentials never enter this surface.
"""
from __future__ import annotations

import copy
import hashlib
from http.server import BaseHTTPRequestHandler
import json
import os
import re
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

from .agent import AgentError
from .host_bridge import BridgeError


PERMISSIONS = {"computer": True, "system": True, "camera": True, "audio": True,
               "voice": True, "speaker": True, "hardware": True, "remote_preview": False}
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
SESSION_SECONDS = 8 * 60 * 60
PAIR_SECONDS = 5 * 60


class RemoteAccessError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _permissions(value, *, partial=False):
    if (type(value) is not dict or set(value) - set(PERMISSIONS)
            or any(type(v) is not bool for v in value.values())):
        raise RemoteAccessError("Choose valid device permission toggles")
    return dict(value) if partial else {**PERMISSIONS, **value}


class RemoteAccess:
    def __init__(self, product, directory, *, clock=time.time, gateway_enabled=True):
        self.product = product
        self.path = directory / "remote-access.json"
        self.clock = clock
        self.gateway_enabled = gateway_enabled
        self.lock = threading.RLock()
        self.job_owner = None
        self.job_id = None
        self.stopped = threading.Event()
        self.pairing = None  # Codes do not survive companion restarts.
        self.state = {"version": 1, "permissions": dict(PERMISSIONS), "sessions": {}}
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text())
                if (type(value) is not dict or set(value) != set(self.state) or value["version"] != 1
                        or type(value["sessions"]) is not dict or len(value["sessions"]) > 12
                        or set(value["permissions"]) != set(PERMISSIONS)):
                    raise ValueError
                _permissions(value["permissions"])
                for key, item in value["sessions"].items():
                    if (not re.fullmatch(r"[0-9a-f]{64}", key) or type(item) is not dict
                            or set(item) != {"name", "expires_at"}
                            or type(item["name"]) is not str or not 1 <= len(item["name"]) <= 80
                            or type(item["expires_at"]) not in (int, float)
                            or not 0 < item["expires_at"] < 2**53):
                        raise ValueError
                self.state = value
            except (OSError, ValueError, TypeError, KeyError):
                raise RemoteAccessError("Remote access state is unreadable; refusing to reset permissions") from None

    def start_guard(self):
        def watch():
            while not self.stopped.wait(.5):
                with self.product.lock:
                    if not self.product.running:
                        continue
                    try:
                        self.require_job()
                    except AgentError:
                        self.product.cancel(self.job_id)
        threading.Thread(target=watch, daemon=True, name="modulate-browser-access").start()

    def _save(self):
        temporary = self.path.with_suffix(".pending")
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
            json.dump(self.state, stream, allow_nan=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    def allowed(self, name):
        with self.lock:
            return self.state["permissions"].get(name) is True

    def local_status(self):
        with self.lock:
            return {"enabled": self.gateway_enabled, "url": "https://divy.live/connect",
                    "permissions": dict(self.state["permissions"]),
                    "browsers": [{"name": value["name"], "expires_at": value["expires_at"]}
                                 for value in self.state["sessions"].values()
                                 if value["expires_at"] > self.clock()]}

    def create_pairing(self):
        if not self.gateway_enabled:
            raise RemoteAccessError("The public connection gateway is not configured")
        with self.lock:
            code = f"{secrets.randbelow(100_000_000):08d}"
            self.pairing = {"hash": _hash(code), "expires_at": self.clock() + PAIR_SECONDS, "attempts": 0}
            return {"code": code, "expires_at": self.pairing["expires_at"], "url": "https://divy.live/connect"}

    def pairing_active(self, code, expires_at):
        """Check a device-only display offer without exporting the stored credential."""
        with self.lock:
            pairing = self.pairing
            return bool(self.gateway_enabled and pairing and type(code) is str
                        and pairing["expires_at"] == expires_at and expires_at > self.clock()
                        and pairing["attempts"] < 6
                        and secrets.compare_digest(pairing["hash"], _hash(code)))

    def claim(self, code, name="Connected browser", permissions=None):
        if type(name) is not str or not 1 <= len(name.strip()) <= 80 or not name.isprintable():
            raise RemoteAccessError("Name this browser in 1–80 characters")
        requested = _permissions(permissions if permissions is not None else {})
        with self.lock:
            pairing = self.pairing
            if not pairing or pairing["expires_at"] <= self.clock() or pairing["attempts"] >= 6:
                raise RemoteAccessError("Create a new connection code in the Mac's local Studio", 401)
            pairing["attempts"] += 1
            if (type(code) is not str or not re.fullmatch(r"[0-9]{8}", code)
                    or not secrets.compare_digest(pairing["hash"], _hash(code))):
                raise RemoteAccessError("That connection code is invalid or expired", 401)
            self.state["sessions"] = {key: item for key, item in self.state["sessions"].items()
                                      if item["expires_at"] > self.clock()}
            if len(self.state["sessions"]) >= 12:
                raise RemoteAccessError("Disconnect an old browser in local Studio first")
            token = secrets.token_urlsafe(32)
            self.state["sessions"][_hash(token)] = {"name": name.strip(), "expires_at": self.clock() + SESSION_SECONDS}
            self.pairing = None
            self._save()
        self.set_permissions(requested)
        return {"token": token, **self.session(token)}

    def authenticate(self, token):
        with self.lock:
            if type(token) is not str or TOKEN.fullmatch(token) is None:
                raise RemoteAccessError("Connect this browser again", 401)
            value = self.state["sessions"].get(_hash(token))
            if not value or value["expires_at"] <= self.clock():
                raise RemoteAccessError("This browser connection expired or was revoked", 401)
            return copy.deepcopy(value)

    def session(self, token):
        companion = {"name": "Modulate companion", "online": True, "platform": sys.platform}
        try:
            value = self.authenticate(token)
        except RemoteAccessError:
            return {"connected": False, "companion": companion, "permissions": {}, "expires_at": None}
        with self.lock:
            return {"connected": True, "companion": companion, "permissions": dict(self.state["permissions"]), **value}

    def set_permissions(self, permissions):
        update = _permissions(permissions, partial=True)
        # Lock order is Product -> RemoteAccess throughout: heartbeat checks
        # access while holding Product.lock. Never invoke Product under ours.
        with self.product.lock:
            with self.lock:
                before = self.state["permissions"]
                after = {**before, **update}
                removed = {key for key in after if before[key] and not after[key]}
                self.state["permissions"] = after
                try:
                    self._save()
                except Exception:
                    self.state["permissions"] = before
                    raise
            if removed:
                if self.product.running and removed - {"remote_preview"}:
                    self.product.cancel()
                if "computer" in removed:
                    self.product.computer.cancel()
                if "camera" in removed:
                    self.product.stop_camera()
                if {"audio", "speaker"} & removed:
                    self.product.stop_computer_audio()
                if "speaker" in removed:
                    self.product._stop_speech()
                if "hardware" in removed:
                    self.product.hardware.call("cancel")
            return {"permissions": dict(after), "scope": "device"}

    def revoke(self, token=None, *, all_sessions=False):
        with self.product.lock:
            with self.lock:
                key = _hash(token) if type(token) is str else None
                owned = all_sessions or key == self.job_owner
                if all_sessions:
                    self.state["sessions"] = {}
                    self.pairing = None
                elif key:
                    self.state["sessions"].pop(key, None)
                self._save()
            if owned and self.job_id == self.product.progress.get("job_id"):
                self.product.cancel()
                self.job_owner = self.job_id = None
        return {"connected": False, "revoked": True}

    def request(self, token, payload):
        with self.product.lock:
            self.authenticate(token)
            result = self.product.request(payload.get("text"), followup_id=payload.get("followup_id"))
            self.job_owner, self.job_id = _hash(token), result["job_id"]
            return result

    def require_job(self):
        with self.lock:
            if self.job_id == self.product.progress.get("job_id") and self.job_owner:
                value = self.state["sessions"].get(self.job_owner)
                if not value or value["expires_at"] <= self.clock():
                    raise AgentError("The browser that started this request disconnected; start again from a connected browser")

    def command(self, token, path, data):
        self.authenticate(token)
        if type(data) is not dict:
            raise RemoteAccessError("Expected an action payload")
        product = self.product
        if path == "/api/request":
            return self.request(token, data)

        def set_wake():
            if type(data.get("enabled")) is not bool:
                raise RemoteAccessError("enabled must be boolean")
            if data["enabled"]:
                product.require_permission("voice")
            product.wake = data["enabled"]
            return {"enabled": product.wake}

        routes = {
            "/api/context/clear": lambda: product.clear_context(),
            "/api/hardware/confirm": lambda: product.hardware_confirm(data.get("id"), data.get("step")),
            "/api/hardware/cancel": lambda: product.hardware_cancel(),
            "/api/cancel": lambda: product.cancel(),
            "/api/draft": lambda: product.draft(data.get("job_id"), data.get("action"), data.get("text")),
            "/api/computer": lambda: product.computer_session(data.get("action"), minutes=data.get("minutes", 15)),
            "/api/audio/stop": lambda: product.stop_computer_audio(),
            "/api/camera/stop": lambda: product.stop_camera(),
            "/api/computer/approval": lambda: product.approve_computer_action(data.get("id"), data.get("approved")),
            "/api/response/dismiss": lambda: product.dismiss_response(data.get("id")),
            "/api/speaker": lambda: product.speaker_action(data.get("action")),
            "/api/pairing": lambda: product.create_pairing(),
            "/api/revoke": lambda: product.revoke(),
            "/api/rollback": lambda: product.rollback(),
            "/api/wake": set_wake,
        }
        if path not in routes:
            raise RemoteAccessError("Unknown companion action", 404)
        # Recheck under the product lock immediately before dispatch; no
        # revoked session can wait in the queue and then perform an action.
        with product.lock:
            self.authenticate(token)
            result = routes[path]()
            if type(result) is dict and type(result.get("job_id")) is str:
                self.job_owner, self.job_id = _hash(token), result["job_id"]
            return result


def handler_for(remote, server_secret):
    if type(server_secret) is not str or len(server_secret) < 32 or len(server_secret) > 256 or not server_secret.isascii():
        raise ValueError("Configure a strong remote gateway secret")

    class Handler(BaseHTTPRequestHandler):
        server_version = "Modulate"

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass

        def send(self, status, data, content_type="application/json"):
            if not isinstance(data, bytes):
                data = json.dumps(data, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def process(self):
            if not secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + server_secret):
                return self.send(401, {"error": "Gateway authentication required"})
            try:
                parsed = urlparse(self.path)
                path, token = parsed.path, self.headers.get("X-Modulate-Session", "")
                data = {}
                if self.command == "POST":
                    size = int(self.headers.get("Content-Length", "0"))
                    if (self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1
                            or not 0 < size <= 256 * 1024
                            or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json"):
                        raise RemoteAccessError("Expected a bounded JSON request", 413)
                    def pairs(items):
                        value = {}
                        for key, item in items:
                            if key in value:
                                raise ValueError("Duplicate JSON field")
                            value[key] = item
                        return value
                    def constant(_):
                        raise ValueError("Non-finite JSON number")
                    data = json.loads(self.rfile.read(size), object_pairs_hook=pairs, parse_constant=constant)
                    if type(data) is not dict:
                        raise RemoteAccessError("Expected a JSON object")
                if path == "/session":
                    if self.command == "GET":
                        return self.send(200, remote.session(token))
                    if self.command == "POST":
                        return self.send(200, remote.claim(data.get("code"), data.get("name", "Connected browser"), data.get("permissions")))
                    if self.command == "DELETE":
                        remote.authenticate(token)
                        return self.send(200, remote.revoke(token))
                remote.authenticate(token)
                if self.command == "GET" and path == "/state":
                    with remote.product.lock:
                        remote.authenticate(token)
                        state = remote.product.state()
                        state["remote"] = remote.session(token)
                    return self.send(200, state)
                if self.command == "GET" and path == "/preview":
                    candidate = parse_qs(parsed.query).get("candidate") == ["1"]
                    with remote.product.lock:
                        remote.authenticate(token)
                        package = (remote.product.active or {}).get("package", {})
                        if not candidate and package.get("camera") and not remote.allowed("remote_preview"):
                            raise RemoteAccessError("Camera preview sharing is off in device permissions", 403)
                        frame = remote.product.candidate_preview_bytes if candidate else remote.product.preview_bytes
                        if not frame:
                            raise RemoteAccessError("No preview is available yet", 404)
                        return self.send(200, frame, "image/png")
                if self.command == "POST" and path == "/permissions":
                    with remote.product.lock:
                        remote.authenticate(token)
                        return self.send(200, remote.set_permissions(data.get("permissions")))
                if self.command == "POST" and path == "/command":
                    return self.send(200, remote.command(token, data.get("path"), data.get("payload", {})))
                raise RemoteAccessError("Unknown remote action", 404)
            except RemoteAccessError as error:
                self.send(error.status, {"error": str(error)})
            except (AgentError, BridgeError, ValueError, TypeError) as error:
                self.send(400, {"error": str(error)[:300]})
            except Exception:
                self.send(500, {"error": "The companion could not complete this action"})

        do_GET = process
        do_POST = process
        do_DELETE = process

    return Handler
