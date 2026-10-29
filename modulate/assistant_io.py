"""Trusted computer-task and ephemeral response/speech surfaces.

No screenshots, screen-derived answers or speech text are persisted here.
Computer grants are local, revocable, and independent of the volume pairing.
"""
import copy
import time
import uuid

from .agent import AgentError
from .computer import ComputerController, ComputerError


class AssistantIO:
    def _init_assistant_io(self, computer=None):
        self.computer = computer if computer is not None else ComputerController()
        self.response = None
        self.speech_message = None
        self.speech_stop_id = int(time.time() * 1000)
        self.computer_approval = None
        self.computer_approval_decision = None
        self.computer_approved_action = None
        self.computer_focus_pending = False

    def computer_status(self):
        value = self.computer.status()
        value["pending_approval"] = ({"id": self.computer_approval["id"],
                                      "description": self.computer_approval["description"]}
                                     if self.computer_approval else None)
        return value

    def computer_session(self, action):
        if action == "enable":
            if not self.connected():
                raise AgentError("Connect the controller before enabling computer control")
            if self.running:
                raise AgentError("Finish or cancel the current request first")
            try:
                return self.computer.enable(minutes=15)
            except ComputerError as error:
                raise AgentError(str(error)) from None
        if action != "revoke":
            raise AgentError("Unknown computer-session action")
        self.computer.revoke()
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
        if not self.connected():
            self.computer.cancel()
            raise AgentError("Controller disconnected; computer work stopped")
        if not self.computer.status().get("enabled"):
            raise AgentError("Enable computer control in Studio before asking me to use the Mac")
        if self.agent.cancelled.is_set():
            raise AgentError("Computer request cancelled")

    def computer_observe(self):
        self.computer_authorized()
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
        self.speech_message = None
        self.speech_stop_id = max(self.speech_stop_id + 1, int(time.time() * 1000))

    def _queue_speech(self, text, job_id=None):
        text = " ".join(str(text).split())
        if not text:
            return
        if len(text) > 1200:
            text = text[:1140].rsplit(" ", 1)[0] + ". The rest is in Studio."
        self.speech_message = {"id": uuid.uuid4().hex, "job_id": job_id, "text": text,
                               "created_at": time.time(), "expires_at": time.time() + 120}

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
                self._stop_speech()
            elif action == "test":
                if not self.connected():
                    raise AgentError("The controller is disconnected")
                self._queue_speech("Modulate speaker connected. I can read my answers aloud.")
            else:
                raise AgentError("Unknown speaker action")
        return {"accepted": True}

    def _assistant_heartbeat(self, packet):
        if self.speech_message and (self.speech_message["expires_at"] <= time.time()
                                    or packet.get("speech_ack") == self.speech_message["id"]):
            self.speech_message = None
        return {"speech": copy.deepcopy(self.speech_message), "speech_stop_id": self.speech_stop_id,
                "speaker_enabled": True}

    def _response_state(self):
        if self.response and self.response["expires_at"] <= time.time():
            self.response = None
        return copy.deepcopy(self.response)
