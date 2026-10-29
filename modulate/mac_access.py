"""Paired Mac capabilities and transient camera delivery, outside generated code."""
import base64
import importlib.util
import json
import sys
import threading
import time
import uuid

from .agent import AgentError
from .host_bridge import BridgeError
from .computer_audio_access import ComputerAudioAccess


class MacAccess(ComputerAudioAccess):
    def _init_mac_access(self):
        self.computer_paused = False
        self.camera = None
        self.camera_suspended = False
        self.camera_requested_until = 0.0
        self.camera_guard = None
        self.camera_session = uuid.uuid4().hex
        self.access_guard = None
        path = self.directory / "mac-access.json"
        if path.exists():
            try:
                stored = json.loads(path.read_text())
                if type(stored) is not dict or any(type(stored.get(key)) is not bool for key in ("paused", "camera_suspended")):
                    raise ValueError
                self.computer_paused = stored["paused"]
                self.camera_suspended = stored["camera_suspended"]
            except (OSError, ValueError):
                self.computer_paused = self.camera_suspended = True

    def _save_mac_access(self):
        from .device_transport import save_private
        save_private(self.directory / "mac-access.json", {"paused": self.computer_paused,
                                                        "camera_suspended": self.camera_suspended})

    def _paired_session(self):
        if not self.connected() or not self.volume_token:
            return None
        try:
            return self.bridge.session(self.volume_token)
        except (BridgeError, OSError):
            return None

    def _sync_computer_pairing(self):
        paired = self._paired_session()
        identifier = paired["session_id"] if paired and not self.computer_paused and self.permission_allowed("computer") else None
        self.computer.sync_pairing(identifier)
        return paired

    def _require_mac(self):
        paired = self._paired_session()
        if not paired:
            self.computer.revoke()
            if self.camera:
                self.camera.stop()
            raise AgentError("The paired Mac is disconnected or its pairing expired")
        if self.computer_paused:
            raise AgentError("Mac assistant access is paused in Studio")
        if self.agent.cancelled.is_set():
            raise AgentError("Request cancelled")
        return paired

    def _start_access_guard(self):
        if self.access_guard and self.access_guard.is_alive():
            return
        def guard():
            while self.running:
                time.sleep(.25)
                if not self._paired_session() or self.computer_paused:
                    self.computer.cancel()
                    return
        self.access_guard = threading.Thread(target=guard, daemon=True, name="modulate-mac-access")
        self.access_guard.start()

    def system_control(self, action, value=None):
        with self.lock:
            self.check_request_access()
            self.require_permission("system")
            paired = self._require_mac()
            if action not in paired["capabilities"]["actions"]:
                raise AgentError("That system setting is unavailable; inspect the current capabilities")
            try:
                before = None
                if not action.endswith(".get"):
                    before = self.bridge.execute(self.volume_token, paired["next_sequence"], action.split(".")[0] + ".get")
                    paired = self.bridge.session(self.volume_token)
                result = self.bridge.execute(self.volume_token, paired["next_sequence"], action, value)
                self.volume = dict(result)
                self.volume_read_at = time.monotonic()
                return {**result, **({"before": before, "after": dict(result)} if before is not None else {})}
            except BridgeError as error:
                raise AgentError(str(error)) from None

    def camera_status(self):
        if self.camera is None:
            available = sys.platform == "darwin" and importlib.util.find_spec("AVFoundation") is not None
            return {"supported": available, "state": "stopped", "running": False,
                    "permission": "not_checked", "error": None}
        return self.camera.status()

    def _camera_instance(self):
        if self.camera is None:
            from .camera import Camera
            self.camera = Camera()
        return self.camera

    def camera_control(self, action):
        if action not in {"start", "stop", "status"}:
            raise AgentError("Camera action must be start, stop or status")
        with self.lock:
            if action == "start":
                self.check_request_access()
                self.require_permission("camera")
            self._require_mac()
            camera = self._camera_instance()
            if action == "stop":
                return self.stop_camera()
            if action == "status":
                return camera.refresh_access()
            self.camera_suspended = False
            self._save_mac_access()
            self.camera_requested_until = time.monotonic() + 120
            result = camera.start()
            self._start_camera_guard()
            return result

    def stop_camera(self):
        with self.lock:
            self.camera_suspended = True
            self.camera_requested_until = 0
            self._save_mac_access()
            result = self.camera.stop() if self.camera else self.camera_status()
            if (self.active or {}).get("package", {}).get("camera"):
                self.preview_bytes = b""
            return result

    def validate_camera(self, package):
        if package.get("camera"):
            self.require_permission("camera")
            paired = self._require_mac()
            if package["camera"]["target"] != paired["session_id"]:
                raise AgentError("Camera source must be the currently paired Mac")
            if not self.camera_status()["supported"]:
                raise AgentError("The Mac camera adapter is not installed")

    def _camera_wanted(self):
        paired = self._paired_session()
        if not paired or self.computer_paused or self.camera_suspended or not self.permission_allowed("camera"):
            return False
        package = (self.active or {}).get("package", {})
        return (package.get("camera", {}).get("target") == paired["session_id"]
                or self.running and self.camera_requested_until > time.monotonic())

    def _start_camera_guard(self):
        if self.camera_guard and self.camera_guard.is_alive():
            return
        def guard():
            while True:
                time.sleep(.5)
                with self.lock:
                    if not self._camera_wanted():
                        self.camera.stop()
                        return
        self.camera_guard = threading.Thread(target=guard, daemon=True, name="modulate-camera-access")
        self.camera_guard.start()

    def _sync_camera(self):
        if self._camera_wanted():
            camera = self._camera_instance()
            # start() is idempotent. Failed access is retried only by an explicit
            # camera_start, not every heartbeat or macOS permission dismissal.
            if camera.status()["state"] == "stopped":
                camera.start()
            self._start_camera_guard()
        elif self.camera is not None:
            self.camera.stop()

    def _camera_packet(self):
        package = (self.active or {}).get("package", {})
        if not package.get("camera") or not self._camera_wanted() or self.camera is None:
            return None
        frame = self.camera.frame()
        if frame is None:
            return None
        return {"revision": self.revision, "session": self.camera_session, "sequence": frame["sequence"],
                "jpeg": base64.b64encode(frame["jpeg"]).decode("ascii")}
