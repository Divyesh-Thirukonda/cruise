"""Pi-owned, local-network RPC link to an optional Mac helper.

Only physical device pairing activates a candidate. The helper has no model
credentials or cost ledger. Commands are bounded, single-delivery and expiring;
unknown outcomes are never retried. Media stays on the pinned local TLS link.
"""
import base64
import copy
import hashlib
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import secrets
import threading
import time
import uuid

from .host_bridge import BackendError, BridgeError, SESSION_SECONDS
from .computer import ComputerError
from .device_transport import save_private

MAX_BODY = 2 * 1024 * 1024


class MacLink:
    def __init__(self, directory):
        self.path = Path(directory) / "mac-link.json"
        self.changed = threading.Condition(threading.RLock())
        self.saved = json.loads(self.path.read_text()) if self.path.exists() else None
        self.pending = None
        self.last_seen = 0
        self.info = {}
        self.command = self.result = None
        self.epoch = 0
        self.attempts = []
        self.endpoint = {}

    def _save(self):
        save_private(self.path, self.saved)

    def online(self):
        return bool(self.saved and self.saved.get("expires_at", 0) > time.time()
                    and time.monotonic() - self.last_seen < 3)

    def candidate(self):
        return bool(self.pending and self.pending["expires_at"] > time.time())

    def join(self, name, info):
        if (type(name) is not str or not 1 <= len(name) <= 80 or not name.isprintable()
                or type(info) is not dict or info.get("platform") != "macos"
                or type(info.get("brightness")) is not bool):
            raise BridgeError("Invalid Mac helper description")
        with self.changed:
            if self.saved and self.saved.get("expires_at", 0) > time.time():
                raise BridgeError("A Mac session exists. Reconnect that helper or revoke it before pairing another Mac.")
            now = time.time()
            self.attempts = [t for t in self.attempts if t > now - 60]
            if len(self.attempts) >= 5 or self.candidate():
                raise BridgeError("A pairing request is already pending; check Modulate")
            self.attempts.append(now)
            token = secrets.token_urlsafe(32)
            self.pending = {"hash": hashlib.sha256(token.encode()).hexdigest(), "name": name,
                            "expires_at": now + 120, "info": copy.deepcopy(info)}
            return token

    def _auth(self, token, pending=False):
        if type(token) is not str or not 32 <= len(token) <= 128:
            raise BridgeError("Mac connection expired or was revoked")
        value = self.pending if pending and self.candidate() else self.saved
        if (not value or value["expires_at"] <= time.time()
                or not secrets.compare_digest(value["hash"], hashlib.sha256(token.encode()).hexdigest())):
            raise BridgeError("Mac connection expired or was revoked")
        return value

    def authorize(self, session):
        with self.changed:
            if not self.candidate():
                raise BridgeError("Start the Mac helper and compare its code on Modulate")
            self.saved = {**self.pending, "session_id": session["session_id"],
                          "expires_at": min(session["expires_at"], time.time() + SESSION_SECONDS), "sequence": 0}
            self.info = copy.deepcopy(self.pending["info"])
            self.pending = None
            self.last_seen = time.monotonic()
            self._save()
            self.changed.notify_all()

    def revoke(self):
        with self.changed:
            self.saved = self.pending = None
            self.command = self.result = None
            self.info = {}
            self.epoch += 1
            self._save()
            self.changed.notify_all()

    def cancel(self):
        with self.changed:
            self.epoch += 1
            self.command = None
            self.changed.notify_all()

    def poll(self, token, data):
        with self.changed:
            session = self._auth(token, pending=True)
            if session is self.pending:
                return {"authorized": False, "expires_at": session["expires_at"]}
            self.last_seen = time.monotonic()
            if type(data.get("info")) is dict:
                self.info = copy.deepcopy(data["info"])
            result = data.get("result")
            ack = None
            if type(result) is dict:
                ack = result.get("id")
                if self.command and result.get("id") == self.command["id"]:
                    self.result = result
                    self.changed.notify_all()
            command = None
            if self.command and not self.command["sent"] and self.command["deadline"] > time.time():
                self.command["sent"] = True
                command = {key: value for key, value in self.command.items() if key != "sent"}
            return {"authorized": True, "session_id": session["session_id"], "expires_at": session["expires_at"],
                    "epoch": self.epoch, "command": command, "ack": ack}

    def call(self, operation, args=None, timeout=2):
        with self.changed:
            if not self.online():
                raise BackendError("The paired Mac helper is disconnected")
            if self.command is not None:
                raise BackendError("The Mac helper is busy; no additional action was sent")
            self.saved["sequence"] += 1
            self._save()  # Write ahead, including reads: no command sequence can be reused.
            command = {"id": uuid.uuid4().hex, "sequence": self.saved["sequence"], "operation": operation,
                       "args": args or {}, "deadline": time.time() + timeout, "epoch": self.epoch, "sent": False}
            self.command, self.result = command, None
            try:
                end = time.monotonic() + timeout
                while self.result is None:
                    if self.command is not command or not self.online() or time.monotonic() >= end:
                        raise BackendError("Mac operation was not acknowledged; do not replay an uncertain action")
                    self.changed.wait(min(.1, end - time.monotonic()))
                if self.result.get("error"):
                    raise BackendError(str(self.result["error"])[:200])
                return self.result.get("value")
            finally:
                self.command = self.result = None


class RemoteMacBackend:
    def __init__(self, link): self.link = link
    def capabilities(self):
        pending = self.link.pending if self.link.candidate() else None
        info = pending["info"] if pending else self.link.info
        return {"supported": bool(pending or self.link.online()), "platform": "macos",
                "brightness": info.get("brightness") is True}
    def get(self): return self.link.call("volume.get")
    def set_volume(self, value): return self.link.call("volume.set", {"value": value})
    def set_muted(self, value): return self.link.call("volume.mute", {"value": value})
    def get_brightness(self): return self.link.call("brightness.get")["brightness"]
    def set_brightness(self, value): return self.link.call("brightness.set", {"value": value})["brightness"]


class RemoteComputer:
    def __init__(self, link):
        self.link, self.paired = link, None
    def status(self):
        value = copy.deepcopy(self.link.info.get("computer", {}))
        return {"supported": False, "enabled": False, "permissions": {}, **value,
                "enabled": bool(self.paired and self.link.online() and value.get("enabled"))}
    def sync_pairing(self, identifier):
        if self.paired and identifier is None: self.link.cancel()
        self.paired = identifier
        return self.status()
    def _call(self, operation, args=None):
        try: return self.link.call("computer." + operation, args, timeout=12)
        except BridgeError as error: raise ComputerError(str(error)) from None
    def begin_task(self):
        if self.paired and self.link.online(): return self._call("begin")
    def focus(self): return self._call("focus")
    def observe(self): return self._call("observe")
    def act(self, observation_id, action): return self._call("act", {"observation_id": observation_id, "action": action})
    def cancel(self): self.link.cancel()
    def revoke(self):
        if self.paired: self.link.cancel()
        self.paired = None


class RemoteCamera:
    def __init__(self, link): self.link = link
    def status(self):
        return {"supported": False, "state": "stopped", "running": False, "permission": "not_checked", "error": None,
                **(copy.deepcopy(self.link.info.get("camera", {})) if self.link.online() else {})}
    def start(self): return self.link.call("camera.start")
    def stop(self):
        if self.link.online() and self.status().get("running"): return self.link.call("camera.stop")
        return self.status()
    def refresh_access(self): return self.link.call("camera.status")
    def frame(self):
        value = self.link.info.get("camera_frame") if self.link.online() and self.status().get("running") else None
        return {**value, "jpeg": base64.b64decode(value["jpeg"], validate=True)} if value else None


class RemoteAudio:
    def __init__(self, link): self.link = link
    def status(self):
        return {"supported": False, "state": "stopped", "running": False, "session": None,
                "format": "pcm_s16le_48000_stereo", "error": None,
                **(copy.deepcopy(self.link.info.get("audio", {})) if self.link.online() else {})}
    def start(self): return self.link.call("audio.start")
    def stop(self):
        if self.link.online() and self.status().get("running"): return self.link.call("audio.stop")
        return self.status()
    def chunk(self, after=0, session=None, timeout=.5):
        value = self.link.call("audio.chunk", {"after": after, "session": session})
        return {**value, "pcm": base64.b64decode(value["pcm"], validate=True)} if value else None


class RemoteAudioRoute:
    def __init__(self, link): self.link, self.active = link, False
    def start(self):
        value = self.link.call("audio.route_start")
        self.active = True
        return value
    def stop(self):
        if self.active and self.link.online(): self.link.call("audio.route_stop")
        self.active = False
        return self.status()
    def status(self): return {"active": self.active, "mode": "remote_mac"}


def handler_for(product):
    link = product.mac_link
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            try:
                self.connection.settimeout(4)
                length = int(self.headers.get("Content-Length", "0"))
                if (len(self.headers.get_all("Content-Length", [])) != 1 or self.headers.get("Transfer-Encoding")
                        or not 0 < length <= MAX_BODY or self.headers.get("Content-Type") != "application/json"):
                    raise BridgeError("Expected bounded JSON")
                data = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if type(data) is not dict: raise BridgeError("Expected JSON object")
                if self.path == "/mac/join":
                    with product.lock:
                        if not product.connected(): raise BridgeError("Modulate is offline")
                        token = link.join(data.get("name"), data.get("info"))
                        try: pairing = product.create_pairing()
                        except Exception:
                            link.pending = None
                            raise
                        value = {"token": token, **pairing}
                elif self.path == "/mac/poll":
                    value = link.poll(self.headers.get("Authorization", "").removeprefix("Bearer "), data)
                elif self.path == "/mac/revoke":
                    with product.lock:
                        link._auth(self.headers.get("Authorization", "").removeprefix("Bearer "))
                        product.revoke()
                        value = {"revoked": True}
                else: raise BridgeError("Unknown Mac operation")
                status = 200
            except (BridgeError, ValueError, TypeError):
                status, value = 400, {"error": "Mac connection rejected; check pairing and the device screen"}
            raw = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)
    return Handler
