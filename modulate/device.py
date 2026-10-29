"""Physical Modulate controller: trusted IO, local games, voice and companion link."""
from __future__ import annotations

import argparse
import base64
from collections import deque
import fcntl
import json
import math
import os
from pathlib import Path
import queue
import signal
import threading
import textwrap
import time
import uuid
from io import BytesIO

from PIL import Image, ImageDraw

from .controls import Controls, neutral_input
from .device_activation import DeviceActivation
from .device_transport import Companion, TransportError, save_private
from .hardware import Screen
from .rendering import font
from .speaker import Speaker
from .audio_receiver import AudioReceiver
from .voice import VoiceListener


class Controller:
    def __init__(self, directory, enrollment, *, microphone=None):
        self.booted_at = time.time()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.companion = Companion(enrollment)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.responses = queue.Queue(maxsize=8)
        self.requests = queue.Queue(maxsize=1)
        self.actions = queue.Queue(maxsize=1)
        self.cancellations = queue.Queue(maxsize=1)
        self.cancel_when_accepted = False
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.screen = Screen(self.directory / "screen.png")
        self.screen.status("Connecting", "Starting physical controls")
        self.display_state = {"kind": "status", "title": "Connecting"}
        self.controls = Controls(self.screen)
        self.sample = neutral_input()
        self.encoder_pending = 0
        self.encoder_revision = None
        self.request_in_flight = False
        self.build = None
        self.job_sequence = 0
        self.latest_job_id = None
        self.finished_jobs = deque(maxlen=32)
        self.feedback = None
        self.commands = []
        self.state = {"revision": None, "ack": None}
        self.voice_state = {"state": "idle", "message": "Starting voice"}
        self.voice_history = deque(maxlen=12)
        self.speaker_state = {"available": False, "state": "stopped", "error": None}
        self.speech_seen = deque(maxlen=128)
        self.speech_ack = None
        self.speech_stop_id = 0
        self.speech_created_at = self.booted_at
        self.speech_cooldown = 0.0
        self.speech_button_held = False
        self.link_state = "Connecting to Mac"
        self.host = {}
        self.last_response = 0
        self.fps = 0
        self.pairing = {}
        self.pairing_path = self.directory / "pairing.json"
        self.pairing_mtime = None
        self.reload_pairing()
        self.camera_image = None
        self.camera_identity = None
        self.camera_received_at = 0.0
        self.camera_frames_received = 0
        self.camera_watermarks = {}
        self.camera_session = None
        self.runtime = DeviceActivation(self.directory / "runtime", self.present,
                                        lambda: self.controls.capabilities()["controls"],
                                        lambda: self.pairing.get("session_id"), self._live_camera_image)
        # The first heartbeat must advertise the restored durable revision,
        # before the render loop runs, so the host does not stage a false recovery.
        self.state = self.runtime.snapshot()
        self.encoder_revision = self.state.get("revision")
        self.voice = VoiceListener(self.request, self.voice_status, device=microphone,
                                   on_cancel=self.cancel_request, on_unclear=self.unclear)
        self.speaker = Speaker(self.speaker_status, audio_fetch=self.companion.speech_audio)
        self.speaker_state = self.speaker.snapshot()
        self.computer_audio = AudioReceiver(self._fetch_computer_audio,
            sink=self.speaker_state.get("output") if self.speaker_state.get("pcm_backend") == "paplay" else None)
        self.audio_blocked = None
        self.status_key = None
        self.dismissed_pairing = None
        self.pairing_in_flight = False
        self.pair_offer = None
        self.pair_buttons_released = False
        self.chord_start = None
        self.chord_fired = False

    def reload_pairing(self):
        try:
            stamp = self.pairing_path.stat().st_mtime_ns
            if stamp != self.pairing_mtime:
                if self.pairing_path.stat().st_mode & 0o077:
                    raise ValueError("Pairing file must be private")
                pairing = json.loads(self.pairing_path.read_text())
                self._validate_pairing(pairing)
                with self.lock:
                    self.pairing, self.pairing_mtime = pairing, stamp
        except FileNotFoundError:
            with self.lock:
                self.pairing, self.pairing_mtime = {}, None
        except (OSError, ValueError, TypeError, TransportError):
            with self.lock:
                self.pairing, self.pairing_mtime = {}, None
                self.link_state = "Saved pairing is invalid; pair again in Studio"

    @staticmethod
    def _validate_pairing(pairing):
        if (type(pairing) is not dict or type(pairing.get("token")) is not str
                or not 32 <= len(pairing["token"]) <= 128 or not pairing["token"].isascii()
                or any(c.isspace() for c in pairing["token"])
                or type(pairing.get("session_id")) is not str or not 1 <= len(pairing["session_id"]) <= 128):
            raise TransportError("Companion returned an invalid pairing grant")

    def present(self, image):
        # Main thread is the only display owner; no disk writes at frame rate.
        self.screen.display.image(image, rotation=90)
        with self.lock:
            self.display_state = {"kind": "program", "title": "Program"}

    def _displayed(self, kind, title):
        with self.lock:
            self.display_state = {"kind": kind, "title": str(title)[:40]}

    def voice_status(self, status):
        with self.lock:
            self.voice_state = status
            self.voice_history.append({"at": time.time(), **status})
            if status.get("state") == "idle" and status.get("message", "").startswith("Please say a complete"):
                self._feedback("Say a little more", 'Say "Hey Meta"\nthen the full request')

    def _speaker_active(self):
        return self.speaker_state.get("state") in {"queued", "fetching", "speaking", "stopping"}

    def speaker_status(self, status):
        with self.lock:
            was_active = self._speaker_active()
            self.speaker_state = dict(status)
            if was_active and not self._speaker_active():
                self.speech_cooldown = time.monotonic() + 0.35

    def _speech_guard(self):
        with self.lock:
            return self._speaker_active() or time.monotonic() < self.speech_cooldown

    def _stop_speech(self):
        with self.lock:
            active = self._speaker_active()
        self.speaker.cancel()
        return active

    def _sync_voice(self):
        self.voice.set_busy(bool(self._busy()))
        self.voice.set_enabled(bool(self.host.get("wake")) and not self._speech_guard())
        question = self.host.get("clarification")
        speech = self.host.get("speech")
        awaiting_audio = (type(speech) is dict and self._job_id(speech.get("id"))
                          and speech["id"] not in self.speech_seen)
        identifier = None
        if (not self._busy() and not self._speech_guard() and not awaiting_audio
                and not self.host.get("speech_pending") and self.host.get("wake")
                and time.monotonic() - self.last_response <= 4 and type(question) is dict
                and self._job_id(question.get("id")) and type(question.get("expires_at")) in (int, float)
                and math.isfinite(question["expires_at"]) and question["expires_at"] > time.time()):
            identifier = question["id"]
        self.voice.set_followup(identifier, seconds=20)
        self._sync_computer_audio()

    def _fetch_computer_audio(self, session, after, cancel):
        if cancel.is_set():
            return None
        result = self.companion.post("audio", {"session": session, "after": after})
        return None if cancel.is_set() else result.get("packet")

    def _sync_computer_audio(self):
        receiver = getattr(self, "computer_audio", None)
        if receiver is None:
            return
        if (receiver.snapshot().get("output") is None and self.speaker_state.get("pcm_backend") == "paplay"
                and self.speaker_state.get("output")):
            receiver.set_sink(self.speaker_state["output"])
        offer = self.host.get("computer_audio") or {}
        session = offer.get("session")
        enabled = (self._job_id(session) and offer.get("format") == "pcm_s16le_48000_stereo"
                   and session != self.audio_blocked and time.monotonic() - self.last_response < 4)
        receiver.set_enabled(bool(enabled), session)
        voice = self.voice_state
        listening = voice.get("state") == "transcribing" or (voice.get("state") == "listening" and
                    voice.get("message", "").startswith(("Push-to-talk", "Wake phrase heard", "Listening for your answer")))
        receiver.set_ducked(bool(self._speech_guard() or self._busy() or listening
                                or self.host.get("clarification") or self.host.get("speech_pending")))
        if hasattr(self.voice, "set_playback_active"):
            audio_state = receiver.snapshot()
            self.voice.set_playback_active(audio_state["enabled"] and not audio_state["ducked"])

    def _stop_computer_audio(self):
        receiver = getattr(self, "computer_audio", None)
        if receiver is None:
            return False
        state = receiver.snapshot()
        if state["enabled"]:
            self.audio_blocked = state["session"]
            receiver.set_enabled(False)
            return True
        return False

    def _update_speech(self, response):
        stop_id = response.get("speech_stop_id", 0)
        if type(stop_id) is int and stop_id > self.speech_stop_id:
            self.speech_stop_id = stop_id
            self._stop_speech()
        if response.get("speaker_enabled", True) is not True:
            if self._speaker_active():
                self._stop_speech()
            return
        speech = response.get("speech")
        if type(speech) is not dict or not self._job_id(speech.get("id")):
            return
        identifier = speech["id"]
        if identifier in self.speech_seen:
            return
        created, expires = speech.get("created_at"), speech.get("expires_at")
        if (type(created) not in (int, float) or type(expires) not in (int, float)
                or not math.isfinite(created) or not math.isfinite(expires)
                or created < self.speech_created_at or created > time.time() + 5
                or expires <= time.time() or expires <= created
                or (speech.get("job_id") is not None and not self._job_id(speech["job_id"]))):
            return
        text = speech.get("text")
        if type(text) is not str or not text.strip() or len(text) > 1200:
            return
        audio = {}
        if "audio" in speech:
            if type(speech["audio"]) is not dict or speech["audio"].get("id") != identifier:
                return
            audio["audio"] = speech["audio"]
        try:
            # Only accepted speech interrupts capture. Unavailable output is
            # retried by heartbeat without invalidating every wake recording.
            accepted = self.speaker.speak(text, before_playback=lambda: self.voice.set_enabled(False), **audio)
        except ValueError:
            accepted = False
        if accepted:
            self.speech_seen.append(identifier)
            self.speech_created_at = created
            self.speech_ack = identifier  # Accepted by the queue, not heard.

    def unclear(self, reason, followup_id=None):
        if type(reason) is not str or reason not in {"empty", "incomplete"}:
            return False
        return self.request("", followup_id=followup_id, _unclear=reason)

    def request(self, text, *, followup_id=None, _unclear=None):
        with self.lock:
            question = self.host.get("clarification")
            if followup_id is not None and (type(question) is not dict or question.get("id") != followup_id
                    or type(question.get("expires_at")) not in (int, float)
                    or not math.isfinite(question["expires_at"]) or question["expires_at"] <= time.time()):
                self._feedback("Conversation ended", "Say Hey Meta\nthen the full request")
                return False
            if self._speech_guard():
                self._feedback("Replying aloud", "Hold both screen buttons\nto interrupt and speak")
                return False
            if self._busy():
                self._feedback("Working", "Please wait for this build")
                return False
            if time.monotonic() - self.last_response > 4:
                self._feedback("Not connected", "Check the Mac connection\nRequest was not queued")
                return False
            try:
                self.requests.put_nowait({"text": text, "followup_id": followup_id, "unclear": _unclear}
                                         if followup_id is not None or _unclear else text)
            except queue.Full:
                self._feedback("Working", "Please wait for this build")
                return False
            self.build = {"job_id": None, "phase": "queued", "title": "Request queued",
                          "role": None, "tool": None, "awaiting_response": True}
            self.feedback = None
            self.encoder_pending = 0
            return True

    def cancel_request(self):
        stopped_audio = self._stop_speech()
        stopped_audio = self._stop_computer_audio() or stopped_audio
        with self.lock:
            if self.build and self.build.get("awaiting_response"):
                try:
                    self.requests.get_nowait()
                    self.build = None
                    self._feedback("Request discarded", "Nothing was sent")
                except queue.Empty:
                    self.cancel_when_accepted = True
                return True
            state = self.host.get("agent_state") or {}
            identifier = (self.build or {}).get("job_id") or (state.get("job_id") if state.get("running") else None)
            if identifier is None:
                identifier = (self.host.get("clarification") or {}).get("job_id")
            if not self._job_id(identifier):
                if stopped_audio:
                    self._feedback("Speech stopped", "Your current app stays active")
                    return True
                self._feedback("Nothing to cancel", "Your current app stays active")
                return False
            try:
                self.cancellations.put_nowait(identifier)
            except queue.Full:
                pass
            return True

    def _busy(self):
        # Structured progress is ordered by job_sequence. A stale legacy flag
        # alongside it must not resurrect work that has already finished.
        legacy_busy = self.host.get("agent_running", False) and type(self.host.get("agent_state")) is not dict
        return self.build is not None or self.request_in_flight or legacy_busy

    def _feedback(self, title, detail):
        self.feedback = {"title": title, "detail": str(detail)[:110], "until": time.monotonic() + 4}

    def _feedback_card(self):
        with self.lock:
            return dict(self.feedback) if self.feedback and time.monotonic() < self.feedback["until"] else None

    @staticmethod
    def _job_id(value):
        return type(value) is str and len(value) == 32 and all(c in "0123456789abcdef" for c in value)

    @staticmethod
    def _job_sequence(value):
        return type(value) is int and value >= 0

    def _update_build(self, response):
        """Order jobs durably, including when an older terminal heartbeat was lost."""
        state = response.get("agent_state")
        if (type(state) is not dict or not self._job_id(state.get("job_id"))
                or not self._job_sequence(state.get("job_sequence", 0))):
            return
        with self.lock:
            identifier = state["job_id"]
            sequence = state.get("job_sequence", 0)
            if self.build and self.build.get("awaiting_response"):
                return
            if sequence < self.job_sequence or (sequence == self.job_sequence
                    and self.latest_job_id is not None and identifier != self.latest_job_id):
                return
            if identifier in self.finished_jobs:
                return
            self.job_sequence, self.latest_job_id = sequence, identifier
            if state.get("running") is True or state.get("status") == "running":
                self.build = {"job_id": identifier, "job_sequence": sequence,
                              "phase": str(state.get("phase", "planning"))[:30],
                              "title": str(state.get("title", "Building"))[:40],
                              "role": state.get("role"), "tool": state.get("tool"), "awaiting_response": False}
                self.encoder_pending = 0
            elif state.get("running") is False and state.get("status") in {"completed", "failed", "cancelled"}:
                was_busy = self.build is not None
                self.finished_jobs.append(identifier)
                self.build = None
                if was_busy and state["status"] != "completed":
                    if state["status"] == "failed" and type(response.get("clarification")) is dict:
                        self.feedback = None  # The actionable question takes precedence.
                    else:
                        title = "Request cancelled" if state["status"] == "cancelled" else "Request failed"
                        self._feedback(title, "See Studio for details")
                elif was_busy:
                    self.feedback = None

    def _network_step(self):
        try:
            try:
                cancel_job = self.cancellations.get_nowait()
            except queue.Empty:
                cancel_job = None
            if cancel_job:
                result = self.companion.post("cancel", {"job_id": cancel_job})
                if not result.get("cancelled"):
                    with self.lock:
                        self._feedback("Already finished", "No new build was cancelled")
            # Rendering owns the runtime lock before present() takes ours.
            # Read its camera revision before taking ours to keep that order.
            camera_fresh = self._live_camera_image() is not None
            with self.lock:
                self.sequence += 1
                delta = self.encoder_pending if not self._busy() and self.encoder_revision == self.state.get("revision") else 0
                sample = {**self.sample, "encoder_delta": max(-100, min(100, delta))}
                self.encoder_pending = 0  # Never replay uncertain physical actions after a timeout.
                packet = {"session": self.session, "sequence": self.sequence, "name": "Modulate Pi 5",
                          "revision": self.state.get("revision"), "ack": self.state.get("ack"),
                          "capabilities": self.controls.capabilities(), "input": sample,
                          "commands": self.commands if self.state.get("kind") == "game" else [],
                          "telemetry": {"fps": round(self.fps, 1), "voice": self.voice_state,
                                        "camera": {"frames_received": self.camera_frames_received,
                                                   "frame_fresh": camera_fresh},
                                        "voice_history": list(self.voice_history),
                                        "speaker": dict(self.speaker_state),
                                        "computer_audio": self.computer_audio.snapshot() if hasattr(self, "computer_audio") else {},
                                        "processing": {"busy": bool(self._busy()),
                                                       **{key: (self.build or {}).get(key) for key in
                                                          ("job_id", "job_sequence", "phase", "title")}},
                                        "display": dict(self.display_state),
                                        "runtime": "physical", "error": self.state.get("error")}}
                if self.state.get("failure"):
                    packet["failure"] = self.state["failure"]
                if self.speech_ack is not None:
                    packet["speech_ack"] = self.speech_ack
                if getattr(self, "audio_blocked", None):
                    packet["audio_stopped"] = self.audio_blocked
                if self.pairing.get("token"):
                    packet["volume_token"] = self.pairing["token"]
            response = self.companion.post("heartbeat", packet)
            # Every heartbeat carries the current transaction phase and retained
            # failure acknowledgment. Prefer fresh state to a backlog of stages.
            while True:
                try:
                    self.responses.put_nowait(response)
                    break
                except queue.Full:
                    try:
                        self.responses.get_nowait()
                    except queue.Empty:
                        pass
            with self.lock:
                self.last_response = time.monotonic()
                self.link_state = "Connected to Mac"
            try:
                text = self.requests.get_nowait()
            except queue.Empty:
                text = None
            if text:
                with self.lock:
                    self.request_in_flight = True
                try:
                    if type(text) is dict:
                        route = "unclear" if text.get("unclear") else "request"
                        payload = ({"reason": text["unclear"]} if route == "unclear" else {"text": text["text"]})
                        payload["followup_id"] = text.get("followup_id")
                    else:
                        route, payload = "request", {"text": text}
                    accepted = self.companion.post(route, payload)
                    if (accepted.get("accepted") is not True or not self._job_id(accepted.get("job_id"))
                            or not self._job_sequence(accepted.get("job_sequence", 0))):
                        raise TransportError("Companion did not confirm this request")
                    with self.lock:
                        self.job_sequence = accepted.get("job_sequence", 0)
                        self.latest_job_id = accepted["job_id"]
                        self.build = {"job_id": accepted["job_id"], "job_sequence": self.job_sequence,
                                      "phase": "queued", "title": "Request queued",
                                      "role": None, "tool": None, "awaiting_response": False}
                        self.host["agent_running"] = True
                        if self.cancel_when_accepted:
                            self.cancel_when_accepted = False
                            try:
                                self.cancellations.put_nowait(accepted["job_id"])
                            except queue.Full:
                                pass
                except (TransportError, OSError, ValueError) as error:
                    with self.lock:
                        self.build = None
                        self.cancel_when_accepted = False
                        self._feedback("Request not confirmed", "Check Studio before retrying\n" + str(error)[:65])
                    raise
                finally:
                    with self.lock:
                        self.request_in_flight = False
            try:
                action = self.actions.get_nowait()
            except queue.Empty:
                action = None
            if action:
                try:
                    result = self.companion.post("pair", {"code": action, "name": "Modulate Pi 5"})
                    self._validate_pairing(result)
                    save_private(self.pairing_path, result)
                finally:
                    with self.lock:
                        self.pairing_in_flight = False
        except (TransportError, OSError, ValueError) as error:
            with self.lock:
                # Also discard turns accumulated while an uncertain request was
                # in flight. They must not be applied as a delayed burst later.
                self.encoder_pending = 0
                self.link_state = str(error)[:100] if isinstance(error, TransportError) else "Could not save local pairing state"

    def network(self):
        while not self.stop.is_set():
            started = time.monotonic()
            self._network_step()
            self.stop.wait(max(0.01, 0.25 - (time.monotonic() - started)))

    def _offer(self):
        offer = self.host.get("pairing")
        if (type(offer) is dict and type(offer.get("code")) is str
                and offer["code"] != self.dismissed_pairing
                and type(offer.get("expires_at")) in (int, float)
                and time.time() < offer["expires_at"]):
            return offer
        return None

    def _tft_buttons(self):
        try:
            a, b = self.screen.buttons[0].value, self.screen.buttons[1].value
            if type(a) is not bool or type(b) is not bool:
                raise ValueError("Invalid TFT button read")
            return not a, not b, True
        except (IndexError, AttributeError, OSError, RuntimeError, ValueError):
            return False, False, False

    def _handle_buttons(self, sample, started):
        sample = dict(sample)
        a, b, valid = self._tft_buttons()
        if valid and b and not a:
            self._stop_computer_audio()
        if valid and not b:
            self.speech_button_held = False
        if valid and b and self._speaker_active() and not self.speech_button_held:
            self._stop_speech()
            self.speech_button_held = True
        if self.speech_button_held:
            sample["button_b"] = False
        offer = self._offer()
        if offer:
            identity = (offer["code"], offer["expires_at"])
            if identity != self.pair_offer:
                self.pair_offer = identity
                self.pair_buttons_released = False
            if not valid:
                self.pair_buttons_released = False
            elif not a and not b:
                self.pair_buttons_released = True
            elif self.pair_buttons_released and b:
                self.dismissed_pairing = offer["code"]
            elif self.pair_buttons_released and a and not self.pairing_in_flight:
                try:
                    self.actions.put_nowait(offer["code"])
                    self.pairing_in_flight = True
                    self.pair_buttons_released = False
                except queue.Full:
                    pass
            self.chord_start, self.chord_fired = None, False
            sample.update(button_a=False, button_b=False)
            return sample
        self.pair_offer, self.pair_buttons_released = None, False
        if valid and a and b:
            if self.chord_start is None:
                self.chord_start = started
            if not self.chord_fired and started - self.chord_start >= 0.75:
                with self.lock:
                    busy = self._busy()
                    if busy:
                        self._feedback("Working", "Please wait for this build")
                if busy:
                    self.chord_fired = True
                elif not self._speech_guard():
                    self.chord_fired = self.voice.request_ptt() is not False
            sample.update(button_a=False, button_b=False)
        else:
            self.chord_start, self.chord_fired = None, False
        return sample

    def _apply_responses(self):
        while True:
            try:
                response = self.responses.get_nowait()
            except queue.Empty:
                return
            with self.lock:
                self.host = response
            self.runtime.acknowledge_failure(response.get("failure_ack"))
            self.runtime.process(response.get("activation"))
            self._update_camera(response.get("camera_frame"))
            self._update_build(response)
            self._update_speech(response)
            self._sync_voice()
            if response.get("activation"):
                self.status_key = None  # Commit/rollback may have presented a frame.

    def _live_camera_image(self):
        if (getattr(self, "camera_identity", None)
                and self.camera_identity[0] != self.runtime.snapshot().get("revision")):
            self.camera_image = self.camera_identity = None
        if (getattr(self, "camera_image", None) is None
                or time.monotonic() - self.camera_received_at >= 2
                or not self.camera_identity
                or self.camera_identity[0] != self.runtime.snapshot().get("revision")):
            return None
        return self.camera_image

    def _update_camera(self, packet):
        if packet is None:
            self.camera_image = self.camera_identity = None
            return
        try:
            active = self.runtime.snapshot()
            if (type(packet) is not dict or set(packet) != {"revision", "session", "sequence", "jpeg"}
                    or active.get("kind") != "game" or not active.get("revision")
                    or packet["revision"] != active["revision"]
                    or not self._job_id(packet["session"])
                    or type(packet["sequence"]) is not int or not 1 <= packet["sequence"] < 2**53
                    or type(packet["jpeg"]) is not str or len(packet["jpeg"]) > 86_000):
                raise ValueError
            identity = (packet["revision"], packet["session"], packet["sequence"])
            watermarks = getattr(self, "camera_watermarks", {})
            last_session = getattr(self, "camera_session", None)
            if (identity[1] in watermarks and (last_session != identity[1]
                    or identity[2] <= watermarks[identity[1]])):
                return
            raw = base64.b64decode(packet["jpeg"], validate=True)
            if not 2 <= len(raw) <= 64_000:
                raise ValueError
            with Image.open(BytesIO(raw)) as image:
                if image.format != "JPEG" or image.size != (240, 135):
                    raise ValueError
                decoded = image.convert("RGB")
            self.camera_image, self.camera_identity = decoded, identity
            watermarks[identity[1]] = identity[2]
            if len(watermarks) > 64:
                del watermarks[next(iter(watermarks))]
            self.camera_watermarks, self.camera_session = watermarks, identity[1]
            self.camera_received_at = time.monotonic()
            self.camera_frames_received = getattr(self, "camera_frames_received", 0) + 1
        except (ValueError, TypeError, KeyError, OSError):
            self.camera_image = self.camera_identity = None

    def _publish(self, sample, frame, current, input_revision):
        with self.lock:
            revision = current.get("revision")
            if revision != self.encoder_revision:
                self.encoder_pending = 0
                self.encoder_revision = revision
            self.sample = dict(sample)
            if input_revision != revision:
                self.sample["encoder_delta"] = 0
            self.encoder_pending = max(-100, min(100, self.encoder_pending + self.sample["encoder_delta"]))
            if revision != self.state.get("revision") or current.get("kind") != "game":
                self.commands = []
            self.state = current
            if frame:
                self.commands = frame["commands"]

    def status(self, title, detail):
        key = title, detail
        if key != self.status_key:
            self.screen.status(title, detail)
            self._displayed("status", title)
            self.status_key = key

    def draw_volume(self):
        volume = self.host.get("volume") or {}
        brightness = "brightness" in volume
        value = volume.get("brightness" if brightness else "volume", 0)
        image = Image.new("RGB", (240, 135), "#101820")
        draw = ImageDraw.Draw(image)
        draw.text((10, 8), "MODULATE / THIS MAC", font=font(12), fill="#64E3B5")
        draw.text((10, 30), f"{value}%", font=font(44), fill="white")
        draw.text((125, 50), "BRIGHTNESS" if brightness else "MUTED" if volume.get("muted") else "VOLUME", font=font(11), fill="#D6DFE7")
        draw.rectangle((10, 92, 230, 100), fill="#273943")
        draw.rectangle((10, 92, 10 + max(0, min(100, value)) * 2.2, 100), fill="#64E3B5")
        linked = self.host.get("paired") and time.monotonic() - self.last_response < 4
        draw.text((10, 112), "Turn knob / Hey Meta..." if linked else "Pair the Mac in Studio", font=font(11), fill="#D6DFE7")
        self.present(image)
        self._displayed("control", "Brightness" if brightness else "Volume")

    def draw_processing(self):
        with self.lock:
            job = dict(self.build) if self.build else None
            connected = time.monotonic() - self.last_response < 4
        if job is None:
            return
        step = int(time.monotonic() * 5) % 4 if connected else -1
        title = job["title"] if connected else "Connection lost"
        role = str(job.get("role") or "Meta").replace("_", " ").capitalize()
        tool = str(job.get("tool") or "").replace("_", " ")
        detail = (role + (" / " + tool if tool else "")) if connected else "Build status unknown"
        footer = '"Hey Meta, cancel rebuild"' if connected else "Checking the Mac connection"
        key = ("processing", job.get("job_id"), title, detail, step)
        if key == self.status_key:
            return
        image = Image.new("RGB", (240, 135), "#101820")
        draw = ImageDraw.Draw(image)
        draw.text((10, 9), "MODULATE / META", font=font(12), fill="#64E3B5")
        for index in range(4):
            x = 194 + index * 9
            draw.ellipse((x, 13, x + 4, 17), fill="#64E3B5" if index == step else "#35434B")
        draw.text((10, 39), title[:23], font=font(17), fill="white")
        draw.text((10, 77), detail[:32], font=font(11), fill="#D6DFE7")
        draw.line((10, 101, 230, 101), fill="#273943")
        draw.text((10, 112), footer[:32], font=font(11), fill="#D6DFE7")
        self.present(image)
        self._displayed("processing", title)
        self.status_key = key

    def run(self):
        self.speaker.start()
        self.computer_audio.start()
        self.voice.start()
        worker = threading.Thread(target=self.network, name="modulate-link", daemon=True)
        worker.start()
        previous = time.monotonic()
        frames = 0
        measure_start = previous
        try:
            while not self.stop.is_set():
                started = time.monotonic()
                dt = max(0.001, min(0.1, started - previous))
                previous = started
                self.reload_pairing()
                self._apply_responses()
                self._sync_voice()
                input_revision = self.runtime.snapshot().get("revision")
                sample = self._handle_buttons(self.controls.poll(), started)
                voice = self.voice_state.get("state")
                voice_message = self.voice_state.get("message", "")
                voice_overlay = voice == "transcribing" or (voice == "listening" and
                                voice_message.startswith(("Push-to-talk", "Wake phrase heard", "Listening for your answer")))
                busy = self.build is not None
                speaking = self._speaker_active()
                streaming = self.computer_audio.snapshot().get("enabled")
                clarification = self.host.get("clarification")
                question = clarification.get("question") if type(clarification) is dict else None
                feedback = self._feedback_card()
                overlay = streaming or speaking or busy or feedback is not None or self._offer() is not None or voice_overlay or bool(question)
                if overlay:
                    sample["encoder_delta"] = 0
                # A modal pairing/voice card temporarily pauses the game rather
                # than writing a game frame and an overlay to SPI every loop.
                frame = None if overlay else self.runtime.tick(sample, dt)
                current = self.runtime.snapshot()
                if frame:
                    self._displayed("game", current.get("title", "Game"))
                self._publish(sample, frame, current, input_revision)
                if frame:
                    self.status_key = None
                offer = self._offer()
                if speaking:
                    self.status("Replying aloud", "B: stop speaking\nBoth screen buttons: talk")
                    self._displayed("speaker", "Replying aloud")
                elif busy:
                    self.draw_processing()
                elif feedback:
                    self.status(feedback["title"], feedback["detail"])
                elif offer:
                    self.status("Link this Mac?", f"Code: {offer['code']}\nA: allow Mac control\nB: decline")
                elif voice_overlay:
                    if voice_message.startswith("Listening for your answer"):
                        self.status("Your answer", "Answer the question\nNo Hey Meta needed")
                    else:
                        self.status("Listening" if voice == "listening" else "Understanding",
                                    "Speak your request" if voice == "listening" else "Local speech recognition")
                elif question:
                    speech = self.host.get("speech")
                    waiting = self.host.get("speech_pending") or (type(speech) is dict
                              and self._job_id(speech.get("id")) and speech["id"] not in self.speech_seen)
                    footer = ("Say Hey Meta to answer" if voice == "wake_listening" and not waiting
                              else "Reply after I finish speaking")
                    self.status("Quick question", "\n".join(textwrap.wrap(question, 31)[:3]) + "\n" + footer)
                elif streaming:
                    audio = self.computer_audio.snapshot()
                    detail = audio.get("error") or ("Playing computer audio" if audio.get("playing") else "Waiting for computer audio")
                    self.status("Mac speaker", detail + "\nB: stop · Both buttons: talk")
                    self._displayed("computer_audio", "Mac speaker")
                elif self.host.get("agent_running") and not current.get("kind"):
                    self.status("Reinventing...", "Meta is building and testing\nFollow progress in Studio")
                elif current.get("kind") == "control":
                    self.draw_volume()
                    self.status_key = None
                elif current.get("kind") == "game":
                    self.status_key = None  # tick() already presented the real game.
                else:
                    connected = time.monotonic() - self.last_response < 4
                    self.status("Ready to become" if connected else "Connecting to Mac",
                                'Say "Hey Meta..."\nHold both screen buttons\nfor push-to-talk' if connected else self.link_state)
                frames += int(frame is not None)
                if started - measure_start >= 1:
                    self.fps = frames / (started - measure_start)
                    frames, measure_start = 0, started
                self.stop.wait(max(0, 0.05 - (time.monotonic() - started)))
        finally:
            self.stop.set()
            self.computer_audio.stop()
            self.speaker.stop()
            self.voice.stop()
            worker.join(timeout=4)
            self.runtime.close()
            self.controls.close()
            self.screen.close()


def main():
    parser = argparse.ArgumentParser(description="Physical Modulate controller")
    parser.add_argument("--state-dir", default="/home/pi/modulate-product/state")
    parser.add_argument("--enrollment", required=True)
    parser.add_argument("--microphone", type=int)
    parser.add_argument("--pair-code", help="Pair with the one-time code shown by the Mac studio, then exit")
    args = parser.parse_args()
    os.umask(0o077)
    directory = Path(args.state_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.pair_code:
        result = Companion(args.enrollment).post("pair", {"code": args.pair_code, "name": "Modulate Pi 5"})
        save_private(directory / "pairing.json", result)
        print("Paired to the Mac volume bridge; the running controller will pick up this grant.")
        return
    lock = (directory / "device.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    controller = Controller(directory, args.enrollment, microphone=args.microphone)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: controller.stop.set())
    controller.run()


if __name__ == "__main__":
    main()
