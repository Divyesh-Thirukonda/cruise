"""Optional native Mac helper. No AI provider, app generator or spending ledger."""
import argparse
import base64
import fcntl
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import ssl
import threading
import time

from .computer import ComputerController
from .device_transport import save_private
from .host_bridge import BridgeStore, BridgeError
from .enroll import device_address


def post(config, path, data, token=None):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Pin is checked before HTTP or credentials.
    connection = http.client.HTTPSConnection(config["device"], 8790, context=context, timeout=3)
    try:
        connection.connect()
        actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        pin = config["fingerprint"]
        if not hmac.compare_digest(actual[:len(pin)], pin):
            raise BridgeError("Pi identity changed; compare its current fingerprint before reconnecting")
        headers = {"Content-Type": "application/json"}
        if token: headers["Authorization"] = "Bearer " + token
        connection.request("POST", path, json.dumps(data, allow_nan=False), headers)
        response = connection.getresponse()
        raw = response.read(2 * 1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 2 * 1024 * 1024:
            raise BridgeError("Pi rejected the Mac connection; it may need pairing again")
        result = json.loads(raw)
        if type(result) is not dict: raise BridgeError("Invalid Pi response")
        return result
    finally:
        connection.close()


class NativeHelper:
    def __init__(self, directory):
        self.bridge = BridgeStore(Path(directory) / "native")
        self.computer = ComputerController()
        self.token = None
        self.session = None
        self.expires_at = 0
        self.lease = 0
        self.epoch = None
        self.camera = self.audio = self.route = None
        self.lock = threading.RLock()

    def stop(self):
        self.computer.revoke()
        if self.camera: self.camera.stop()
        if self.audio: self.audio.stop()
        if self.route: self.route.stop()
        self.session = self.token = None
        self.bridge.revoke_all()

    def sync(self, packet):
        if packet.get("authorized") is not True:
            return
        with self.lock:
            if packet["session_id"] != self.session:
                self.stop()
                code = self.bridge.create_pairing()["code"]
                self.token = self.bridge.pair(code, "Pi physical pairing")
                self.session = packet["session_id"]
                self.computer.sync_pairing(self.session)
            if self.epoch is not None and self.epoch != packet["epoch"]:
                self.computer.cancel()
            self.epoch = packet["epoch"]
            self.expires_at, self.lease = packet["expires_at"], time.monotonic() + 3

    def info(self):
        result = {**self.bridge.backend.capabilities(), "computer": self.computer.status()}
        from .camera import Camera
        from .system_audio import SystemAudio
        if self.camera is None: self.camera = Camera()
        if self.audio is None: self.audio = SystemAudio()
        result.update(camera=self.camera.status(), audio=self.audio.status())
        frame = self.camera.frame()
        if frame:
            result["camera_frame"] = {**frame, "jpeg": base64.b64encode(frame["jpeg"]).decode()}
        return result

    def execute(self, command):
        if (not self.session or time.monotonic() >= self.lease or time.time() >= self.expires_at
                or time.time() >= command["deadline"] or command["epoch"] != self.epoch):
            raise BridgeError("Mac action expired or was cancelled")
        operation, args = command["operation"], command["args"]
        if operation in self.bridge.capabilities()["actions"]:
            session = self.bridge.session(self.token)
            return self.bridge.execute(self.token, session["next_sequence"], operation, args.get("value"))
        if operation == "computer.begin":
            self.computer.begin_task()
            return {"started": True}
        if operation == "computer.focus": return self.computer.focus()
        if operation == "computer.observe": return self.computer.observe()
        if operation == "computer.act": return self.computer.act(args.get("observation_id"), args.get("action"))
        if operation == "camera.start": return self.camera.start()
        if operation == "camera.stop": return self.camera.stop()
        if operation == "camera.status": return self.camera.refresh_access()
        if operation == "audio.start": return self.audio.start()
        if operation == "audio.stop":
            if self.route: self.route.stop()
            return self.audio.stop()
        if operation == "audio.chunk":
            chunk = self.audio.chunk(after=args.get("after", 0), session=args.get("session"), timeout=.5)
            return {**chunk, "pcm": base64.b64encode(chunk["pcm"]).decode()} if chunk else None
        if operation == "audio.route_start":
            from .audio_route import MacAudioRoute
            if self.route is None: self.route = MacAudioRoute()
            return self.route.start()
        if operation == "audio.route_stop":
            return self.route.stop() if self.route else {"stopped": True}
        raise BridgeError("Unsupported native Mac operation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default=str(Path.home() / ".local/share/modulate-mac"))
    parser.add_argument("--device")
    parser.add_argument("--fingerprint")
    parser.add_argument("--pair", action="store_true")
    parser.add_argument("--pair-only", action="store_true", help="Prepare pairing, then let the native Modulate app reconnect")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    if args.pair_only and not args.pair: parser.error("--pair-only requires --pair")
    if os.sys.platform != "darwin": parser.error("Run this optional helper on macOS")
    os.umask(0o077)
    directory = Path(args.state_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (directory / "helper.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = directory / "connection.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    if path.exists() and path.stat().st_mode & 0o077: raise BridgeError("Mac connection must be owner-only")
    native = NativeHelper(directory)
    pairing = config.get("pending_pairing", {})
    if args.pair:
        pin = re.sub(r"[\s:-]", "", args.fingerprint or "").lower()
        if not re.fullmatch(r"(?:[0-9a-f]{20}|[0-9a-f]{64})", pin): parser.error("Use the fingerprint from Modulate's screen")
        config = {"device": device_address(args.device), "fingerprint": pin}
        result = post(config, "/mac/join", {"name": socket.gethostname()[:80], "info": native.info()})
        pairing = result
        config.update(token=result["token"], last_sequence=0,
                      pending_pairing={"code": result["code"], "expires_at": result["expires_at"]})
        save_private(path, config)
        if args.pair_only:
            print("Open Modulate.app and compare the code at https://modulate-connect.vercel.app/connect/setup", flush=True)
            return
    if not config: parser.error("Pair this helper first with --pair --device ADDRESS --fingerprint IDENTITY")
    if args.revoke:
        post(config, "/mac/revoke", {}, config["token"])
        native.stop()
        print("Mac access revoked", flush=True)
        return
    from .mac_pairing_page import start
    page = start(native, pairing)
    print("Mac pairing: https://modulate-connect.vercel.app/connect/setup (link this browser first)", flush=True)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    completion, worker, info_at, info = {}, None, 0, {}
    def work(command):
        try:
            value = native.execute(command)
            completion.update(id=command["id"], value=value)
        except Exception as error:
            completion.update(id=command["id"], error=str(error)[:200])
    def guard():
        while not stopped.wait(.25):
            if native.session and (time.monotonic() >= native.lease or time.time() >= native.expires_at):
                native.stop()
    threading.Thread(target=guard, daemon=True).start()
    announced = False
    try:
        while not stopped.is_set():
            try:
                if time.monotonic() - info_at >= .5 or worker and not worker.is_alive():
                    info, info_at = native.info(), time.monotonic()
                payload = {"info": info}
                if worker and not worker.is_alive(): payload["result"] = dict(completion)
                packet = post(config, "/mac/poll", payload, config["token"])
                native.sync(packet)
                if packet.get("authorized") and not announced:
                    config.pop("pending_pairing", None)
                    save_private(path, config)
                    print("Mac paired. Native controls are available until this eight-hour session expires or is revoked.", flush=True)
                    announced = True
                if packet.get("ack") == completion.get("id") and completion:
                    completion.clear()
                    worker = None
                command = packet.get("command")
                if command:
                    if (worker is not None or type(command.get("sequence")) is not int
                            or command["sequence"] <= config.get("last_sequence", 0)):
                        raise BridgeError("Repeated or concurrent native command rejected")
                    config["last_sequence"] = command["sequence"]
                    save_private(path, config)  # Consume before native work, even if it times out.
                    worker = threading.Thread(target=work, args=(command,), daemon=True)
                    worker.start()
                stopped.wait(.04 if worker else .15)
            except (OSError, ValueError, http.client.HTTPException, BridgeError):
                if native.session and time.monotonic() >= native.lease: native.stop()
                stopped.wait(1)
    finally:
        native.stop()
        page.shutdown()
        page.server_close()


if __name__ == "__main__":
    main()
