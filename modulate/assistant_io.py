"""Trusted computer-task and ephemeral response/speech surfaces.

No screenshots, screen-derived answers or speech text are persisted here.
Computer grants are local, revocable, and independent of the volume pairing.
"""
import copy
import hashlib
import os
import re
import threading
import time
import uuid

from .agent import AgentError
from .computer import ComputerController, ComputerError
from .mac_access import MacAccess


class AssistantIO(MacAccess):
    def _init_assistant_io(self, computer=None):
        self.computer = computer if computer is not None else ComputerController()
        self._init_mac_access()
        self.response = None
        self.speech_message = None
        self.speech_stop_id = int(time.time() * 1000)
        self.computer_approval = None
        self.computer_approval_decision = None
        self.computer_approved_action = None
        self.computer_focus_pending = False
        self.tts = None
        self.speech_error = None
        self.speech_audio = None
        self.speech_pending = None
        self.speech_cancel = None
        self.speech_worker = None
        self.tts_provider = os.environ.get("MODULATE_TTS_PROVIDER") or "local"
        if self.tts_provider == "elevenlabs":
            from .tts import ElevenLabsTTS
            self.tts = ElevenLabsTTS(self.directory, max_chars=int(os.environ.get("MODULATE_TTS_CHARACTER_LIMIT", "5000")))
        elif self.tts_provider == "meta_mms":
            from .mms_tts import MMSTTS
            self.tts = MMSTTS()
        elif self.tts_provider != "local":
            raise ValueError("Unsupported speech provider; choose local, meta_mms or elevenlabs")

    def computer_status(self):
        self._sync_computer_pairing()
        value = self.computer.status()
        value["paused"] = self.computer_paused
        value["pending_approval"] = ({"id": self.computer_approval["id"],
                                      "description": self.computer_approval["description"]}
                                     if self.computer_approval else None)
        return value

    def computer_session(self, action, minutes=15):
        if action == "enable":
            self.require_permission("computer")
            if not self.connected():
                raise AgentError("Connect the controller before enabling computer control")
            if self.running:
                raise AgentError("Finish or cancel the current request first")
            self.computer_paused = False
            self._save_mac_access()
            self._sync_computer_pairing()
            return self.computer_status()
        if action != "revoke":
            raise AgentError("Unknown computer-session action")
        self.computer_paused = True
        self._save_mac_access()
        self.computer.revoke()
        self.stop_computer_audio()
        if self.camera:
            self.camera.stop()
        if self.running and self.agent.private_request:
            self.cancel()
        with self.changed:
            self.computer_approval = None
            self.computer_approval_decision = False
            self.computer_approved_action = None
            self.response = None
            self._stop_speech()
            self.changed.notify_all()
        return self.computer_status()

    def computer_authorized(self):
        self.check_request_access()
        self.require_permission("computer")
        self._require_mac()
        self._sync_computer_pairing()
        if not self.connected():
            self.computer.cancel()
            raise AgentError("Controller disconnected; computer work stopped")
        if not self.computer.status().get("enabled"):
            raise AgentError("Mac control needs its native Screen Recording and Accessibility permissions")
        if self.agent.cancelled.is_set():
            raise AgentError("Computer request cancelled")

    def computer_observe(self):
        self.computer_authorized()
        self._start_access_guard()
        try:
            with self.lock:
                focus = self.computer_focus_pending
                self.computer_focus_pending = False
            if focus:
                self.computer.focus()
                self.computer_authorized()
            return self.computer.observe()
        except ComputerError as error:
            raise AgentError(str(error)) from None

    def computer_act(self, observation_id, action, requires_confirmation, description):
        if (type(requires_confirmation) is not bool or not isinstance(description, str)
                or not 1 <= len(description.strip()) <= 240 or not description.strip().isprintable()):
            raise AgentError("Describe one computer action in 1–240 printable characters")
        self.computer_authorized()
        if requires_confirmation:
            receipt = self.computer_approved_action
            matches = (receipt and receipt["expires_at"] > time.monotonic()
                       and receipt["action"] == action and receipt["description"] == description.strip())
            if matches:
                if observation_id == receipt["previous_observation_id"]:
                    raise AgentError("Observe the page again after approval before acting")
                self.computer_approved_action = None
                requires_confirmation = False
        if requires_confirmation:
            with self.changed:
                self.computer_approval = {"id": uuid.uuid4().hex, "description": description.strip()}
                self.computer_approval_decision = None
                deadline = time.monotonic() + 120
                try:
                    while self.computer_approval_decision is None:
                        self.computer_authorized()
                        if time.monotonic() >= deadline:
                            raise AgentError("Computer action approval expired; nothing was clicked")
                        self.changed.wait(.25)
                    if self.computer_approval_decision is not True:
                        raise AgentError("Computer action declined; nothing was clicked")
                    self.computer_approved_action = {"action": copy.deepcopy(action),
                                                     "description": description.strip(),
                                                     "previous_observation_id": observation_id,
                                                     "expires_at": time.monotonic() + 90}
                finally:
                    self.computer_approval = None
            return {"approved": True, "performed": False,
                    "instruction": "Approval recorded. Observe the current page again, restore the target if needed, and verify it before repeating this exact action with requires_confirmation=true."}
        # Approval does not refresh a stale screenshot. The backend must reject
        # expired observations, changed windows, or revoked grants at execution.
        self.computer_authorized()
        try:
            result = self.computer.act(observation_id, action)
            self.computer_authorized()
            return {"action_result": result, **self.computer.observe()}
        except ComputerError as error:
            raise AgentError(str(error)) from None

    def approve_computer_action(self, identifier, approved):
        with self.changed:
            if (type(approved) is not bool or not self.computer_approval
                    or self.computer_approval["id"] != identifier):
                raise AgentError("That computer action is no longer waiting for approval")
            self.computer_approval_decision = approved
            self.changed.notify_all()
            return {"accepted": True}

    def _stop_speech(self):
        if self.speech_cancel:
            self.speech_cancel.set()
        self.speech_pending = None
        self.speech_audio = None
        self.speech_message = None
        self.speech_stop_id = max(self.speech_stop_id + 1, int(time.time() * 1000))

    def _queue_speech(self, text, job_id=None):
        if not self.permission_allowed("speaker"):
            return
        text = " ".join(str(text).split())
        if not text:
            return
        if len(text) > 1200:
            text = text[:1140].rsplit(" ", 1)[0] + ". The rest is in Studio."
        self._stop_speech()
        self.speech_error = None
        message = {"id": uuid.uuid4().hex, "job_id": job_id, "text": text,
                   "created_at": time.time(), "expires_at": time.time() + 120}
        if self.tts is None:
            self.speech_message = message
            return
        self.speech_pending = message
        if self.speech_worker is None or not self.speech_worker.is_alive():
            self.speech_worker = threading.Thread(target=self._synthesize_pending,
                                                   name="modulate-speech-synthesis", daemon=True)
            self.speech_worker.start()

    def _synthesize_pending(self):
        # Only one synthesis at a time; replacements cancel active work and
        # replace the single pending entry. No provider work holds the host lock.
        while True:
            with self.lock:
                message = self.speech_pending
                if message is None:
                    self.speech_worker = None
                    return
                if message["expires_at"] <= time.time():
                    self.speech_pending = None
                    continue
                cancel = self.speech_cancel = threading.Event()
            waiting_for_previous = False
            try:
                audio = self.tts.synthesize(message["text"], cancel)
                if type(audio) is not bytes or not audio or len(audio) > 4_320_000 or len(audio) % 2:
                    raise ValueError("Invalid speech audio")
                with self.lock:
                    if (not cancel.is_set() and self.speech_pending is message
                            and message["expires_at"] > time.time()):
                        descriptor = {"id": message["id"], "format": "pcm_s16le_24000_mono",
                                      "bytes": len(audio), "sha256": hashlib.sha256(audio).hexdigest()}
                        self.speech_audio = {"id": message["id"], "data": audio,
                                             "expires_at": message["expires_at"]}
                        self.speech_message = {**message, "audio": descriptor, "provider": self.tts_provider}
            except Exception as error:
                with self.lock:
                    if not cancel.is_set() and self.speech_pending is message:
                        # Cancellation can return before the provider's blocked
                        # socket worker exits. Busy means no request was sent;
                        # retain only the newest reply until that worker stops.
                        from .tts import TTSError
                        waiting_for_previous = (isinstance(error, TTSError)
                                                and error.category == "busy"
                                                and message["expires_at"] > time.time())
                        if not waiting_for_previous:
                            provider = "Meta MMS" if self.tts_provider == "meta_mms" else "ElevenLabs"
                            self.speech_error = provider + " could not produce this reply. The text is still available in Studio."
                if waiting_for_previous:
                    cancel.wait(.1)
            finally:
                with self.lock:
                    if self.speech_pending is message and not waiting_for_previous:
                        self.speech_pending = None
                    if self.speech_cancel is cancel:
                        self.speech_cancel = None

    def get_speech_audio(self, identifier):
        with self.lock:
            if self.speech_audio and self.speech_audio["expires_at"] <= time.time():
                self.speech_audio = None
            if (type(identifier) is not str or not re.fullmatch(r"[0-9a-f]{32}", identifier)
                    or not self.speech_audio or self.speech_audio["id"] != identifier):
                raise AgentError("That spoken reply is no longer available")
            return self.speech_audio["data"]

    def speech_status(self):
        return {"provider": self.tts_provider,
                "pending": self.speech_pending is not None, "error": self.speech_error}

    def _publish_response(self, text, job_id):
        text = str(text).strip()[:4000]
        if not text:
            return
        self.response = {"id": uuid.uuid4().hex, "text": text, "expires_at": time.time() + 120}
        self._queue_speech(text, job_id)

    def dismiss_response(self, identifier):
        with self.lock:
            if not self.response or self.response["id"] != identifier:
                raise AgentError("That response is no longer visible")
            self.response = None
            self._stop_speech()
        return {"dismissed": True}

    def speaker_action(self, action):
        with self.lock:
            if action == "stop":
                self.stop_computer_audio()
                self._stop_speech()
            elif action == "test":
                self.require_permission("speaker")
                if not self.connected():
                    raise AgentError("The controller is disconnected")
                self._queue_speech("Modulate speaker connected. I can read my answers aloud.")
            else:
                raise AgentError("Unknown speaker action")
        return {"accepted": True}

    def _assistant_heartbeat(self, packet):
        if self.speech_audio and self.speech_audio["expires_at"] <= time.time():
            self.speech_audio = None
        if self.speech_message and (self.speech_message["expires_at"] <= time.time()
                                    or packet.get("speech_ack") == self.speech_message["id"]):
            self.speech_message = None
        return {"speech": copy.deepcopy(self.speech_message), "speech_stop_id": self.speech_stop_id,
                "speech_pending": self.speech_pending is not None, "speech_error": self.speech_error,
                "speaker_enabled": self.permission_allowed("speaker")}

    def _response_state(self):
        if self.response and self.response["expires_at"] <= time.time():
            self.response = None
        return copy.deepcopy(self.response)
