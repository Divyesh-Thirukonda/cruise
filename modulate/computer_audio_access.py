"""Pair-scoped local system-audio delivery; never part of model media or packages."""
import base64
import importlib.util
import re
import sys
import threading
import time

from .agent import AgentError


class ComputerAudioAccess:
    def audio_status(self):
        audio = getattr(self, "system_audio", None)
        if audio is not None:
            result = audio.status()
            route = getattr(self, "audio_route", None)
            if route:
                result["route"] = route.status()
            return result
        return {"supported": sys.platform == "darwin" and importlib.util.find_spec("ScreenCaptureKit") is not None,
                "state": "stopped", "running": False, "session": None,
                "format": "pcm_s16le_48000_stereo", "mode": "mirror", "error": None}

    def _audio_authorized(self):
        paired = self._paired_session()
        return bool(paired and not self.computer_paused and self.permission_allowed("audio")
                    and self.permission_allowed("speaker")
                    and paired["session_id"] == getattr(self, "audio_pair", None))

    def computer_audio(self, action):
        if action not in {"start", "stop", "status"}:
            raise AgentError("Audio action must be start, stop or status")
        if action == "stop":
            return self.stop_computer_audio()
        with self.lock:
            if action == "start":
                self.check_request_access()
                self.require_permission("audio")
                self.require_permission("speaker")
            paired = self._require_mac()
            if action == "status":
                return self.audio_status()
            if not self.telemetry.get("speaker", {}).get("available"):
                raise AgentError("The Pi speaker is disconnected")
            if getattr(self, "system_audio", None) is None:
                from .system_audio import SystemAudio
                self.system_audio = SystemAudio()
            if getattr(self, "audio_pair", None) not in (None, paired["session_id"]):
                self.stop_computer_audio()
            self.audio_pair = paired["session_id"]
            if not self.system_audio.status().get("running"):
                self.audio_route_started = False
            result = self.system_audio.start()
            if result.get("state") == "error":
                raise AgentError(result.get("error") or "Mac audio capture could not start")
            if not getattr(self, "audio_guard", None) or not self.audio_guard.is_alive():
                self.audio_guard = threading.Thread(target=self._guard_audio, daemon=True, name="modulate-audio-access")
                self.audio_guard.start()
            return result

    def _guard_audio(self):
        while True:
            time.sleep(.25)
            with self.lock:
                if not self._audio_authorized():
                    self.stop_computer_audio()
                    return
                state = self.audio_status()
                if not state.get("running"):
                    self.stop_computer_audio()
                    return
                receiver = self.telemetry.get("computer_audio", {})
                if receiver.get("session") != state.get("session"):
                    continue
                if receiver.get("error"):
                    self.stop_computer_audio()
                    return
                if receiver.get("playing") and not getattr(self, "audio_route_started", False):
                    if getattr(self, "mac_link", None):
                        from .mac_link import RemoteAudioRoute
                        self.audio_route = RemoteAudioRoute(self.mac_link)
                    else:
                        from .audio_route import MacAudioRoute
                        self.audio_route = MacAudioRoute()
                    self.audio_route.start()
                    self.audio_route_started = True

    def stop_computer_audio(self, session=None):
        with self.lock:
            current = self.audio_status()
            # An old physical stop cannot stop a subsequently requested stream.
            if session is not None and session != current.get("session"):
                return {"stopped": False}
            self.audio_pair = None
            route = getattr(self, "audio_route", None)
            if route:
                route.stop()
            audio = getattr(self, "system_audio", None)
            return audio.stop() if audio else current

    def audio_offer(self):
        state = self.audio_status()
        if self._audio_authorized() and state.get("running"):
            return {"session": state["session"], "format": state["format"]}
        return None

    def audio_packet(self, session, after):
        if (type(session) is not str or re.fullmatch(r"[0-9a-f]{32}", session) is None
                or (after is not None and (type(after) is not int or not 0 <= after < 2 ** 53))):
            raise AgentError("Invalid computer audio cursor")
        with self.lock:
            offer = self.audio_offer()
            if not offer or session != offer["session"]:
                raise AgentError("Computer audio is stopped or its pairing expired")
            audio = self.system_audio
        # The long poll must not hold the product lock or stall heartbeats.
        packet = audio.chunk(after=after, session=session, timeout=.5)
        with self.lock:
            offer = self.audio_offer()
            if not offer or offer["session"] != session:
                raise AgentError("Computer audio stopped")
            if packet is None:
                return {"packet": None}
            return {"packet": {**packet, "pcm": base64.b64encode(packet["pcm"]).decode("ascii")}}
