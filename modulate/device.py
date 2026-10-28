"""Physical Modulate controller: trusted IO, local games, voice and companion link."""
from __future__ import annotations

import argparse
from collections import deque
import fcntl
import json
import os
from pathlib import Path
import queue
import signal
import threading
import time
import uuid

from PIL import Image, ImageDraw

from .controls import Controls, neutral_input
from .device_activation import DeviceActivation
from .device_transport import Companion, TransportError, save_private
from .hardware import Screen
from .rendering import font
from .voice import VoiceListener


class Controller:
    def __init__(self, directory, enrollment, *, microphone=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.companion = Companion(enrollment)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.responses = queue.Queue(maxsize=8)
        self.requests = queue.Queue(maxsize=1)
        self.actions = queue.Queue(maxsize=1)
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.screen = Screen(self.directory / "screen.png")
        self.screen.status("Connecting", "Starting physical controls")
        self.controls = Controls(self.screen)
        self.sample = neutral_input()
        self.encoder_pending = 0
        self.encoder_revision = None
        self.request_in_flight = False
        self.commands = []
        self.state = {"revision": None, "ack": None}
        self.voice_state = {"state": "idle", "message": "Starting voice"}
        self.voice_history = deque(maxlen=12)
        self.link_state = "Connecting to Mac"
        self.host = {}
        self.last_response = 0
        self.fps = 0
        self.pairing = {}
        self.pairing_path = self.directory / "pairing.json"
        self.pairing_mtime = None
        self.reload_pairing()
        self.runtime = DeviceActivation(self.directory / "runtime", self.present,
                                        lambda: self.controls.capabilities()["controls"],
                                        lambda: self.pairing.get("session_id"))
        # The first heartbeat must advertise the restored durable revision,
        # before the render loop runs, so the host does not stage a false recovery.
        self.state = self.runtime.snapshot()
        self.encoder_revision = self.state.get("revision")
        self.voice = VoiceListener(self.request, self.voice_status, device=microphone)
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

    def voice_status(self, status):
        with self.lock:
            self.voice_state = status
            self.voice_history.append({"at": time.time(), **status})

    def request(self, text):
        with self.lock:
            if self.request_in_flight or self.host.get("agent_running") or time.monotonic() - self.last_response > 4:
                return False
        try:
            self.requests.put_nowait(text)
            return True
        except queue.Full:
            return False

    def _network_step(self):
        try:
            with self.lock:
                self.sequence += 1
                delta = self.encoder_pending if self.encoder_revision == self.state.get("revision") else 0
                sample = {**self.sample, "encoder_delta": max(-100, min(100, delta))}
                self.encoder_pending = 0  # Never replay uncertain physical actions after a timeout.
                packet = {"session": self.session, "sequence": self.sequence, "name": "Modulate Pi 5",
                          "revision": self.state.get("revision"), "ack": self.state.get("ack"),
                          "capabilities": self.controls.capabilities(), "input": sample,
                          "commands": self.commands if self.state.get("kind") == "game" else [],
                          "telemetry": {"fps": round(self.fps, 1), "voice": self.voice_state,
                                        "voice_history": list(self.voice_history),
                                        "runtime": "physical", "error": self.state.get("error")}}
                if self.state.get("failure"):
                    packet["failure"] = self.state["failure"]
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
                    self.companion.post("request", {"text": text})
                    with self.lock:
                        self.host["agent_running"] = True
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
                self.voice.request_ptt()
                self.chord_fired = True
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
            self.voice.set_enabled(bool(response.get("wake")) and not response.get("agent_running", False))
            self.runtime.acknowledge_failure(response.get("failure_ack"))
            self.runtime.process(response.get("activation"))
            if response.get("activation"):
                self.status_key = None  # Commit/rollback may have presented a frame.

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
            self.status_key = key

    def draw_volume(self):
        volume = self.host.get("volume") or {}
        value = volume.get("volume", 0)
        image = Image.new("RGB", (240, 135), "#101820")
        draw = ImageDraw.Draw(image)
        draw.text((10, 8), "MODULATE / THIS MAC", font=font(12), fill="#64E3B5")
        draw.text((10, 30), f"{value}%", font=font(44), fill="white")
        draw.text((125, 50), "MUTED" if volume.get("muted") else "VOLUME", font=font(13), fill="#D6DFE7")
        draw.rectangle((10, 92, 230, 100), fill="#273943")
        draw.rectangle((10, 92, 10 + max(0, min(100, value)) * 2.2, 100), fill="#64E3B5")
        linked = self.host.get("paired") and time.monotonic() - self.last_response < 4
        draw.text((10, 112), "Turn knob / Hey Meta..." if linked else "Pair the Mac in Studio", font=font(11), fill="#D6DFE7")
        self.present(image)

    def run(self):
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
                input_revision = self.runtime.snapshot().get("revision")
                sample = self._handle_buttons(self.controls.poll(), started)
                voice = self.voice_state.get("state")
                voice_message = self.voice_state.get("message", "")
                voice_overlay = voice == "transcribing" or (voice == "listening" and
                                voice_message.startswith(("Push-to-talk", "Wake phrase heard")))
                overlay = self._offer() is not None or voice_overlay
                if overlay:
                    sample["encoder_delta"] = 0
                # A modal pairing/voice card temporarily pauses the game rather
                # than writing a game frame and an overlay to SPI every loop.
                frame = None if overlay else self.runtime.tick(sample, dt)
                current = self.runtime.snapshot()
                self._publish(sample, frame, current, input_revision)
                if frame:
                    self.status_key = None
                offer = self._offer()
                if offer:
                    self.status("Link this Mac?", f"Code: {offer['code']}\nA: allow volume control\nB: decline")
                elif voice_overlay:
                    self.status("Listening" if voice == "listening" else "Understanding",
                                "Speak your request" if voice == "listening" else "Local speech recognition")
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
