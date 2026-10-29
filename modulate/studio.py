"""Local companion website and a separate pinned-TLS controller endpoint."""
from __future__ import annotations

import argparse
import fcntl
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import ssl
import subprocess
import threading
from urllib.parse import urlparse

from .agent_provider import AgentProvider
from .agent import AgentError
from .host_bridge import BridgeError
from .product import Product


def atomic_json(path, value):
    tmp = path.with_suffix(".pending")
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False))
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def tls_material(directory, address):
    """Create our own endpoint certificate; device trusts this exact certificate."""
    address = str(ipaddress.ip_address(address))
    cert, key = directory / "device-cert.pem", directory / "device-key.pem"
    if not cert.exists() or not key.exists():
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "30",
                        "-subj", "/CN=Modulate local companion", "-addext", f"subjectAltName=IP:{address}"],
                       check=True, capture_output=True, timeout=15)
        key.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context, cert


def load_credentials(path):
    if not path:
        return
    path = Path(path).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("Credential file must have mode600")
    allowed = {"MODEL_API_KEY", "FIREWORKS_API_KEY", "ELEVENLABS_API_KEY",
               "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID", "MODULATE_TTS_PROVIDER"}
    for line in path.read_text().splitlines():
        name, separator, value = line.partition("=")
        if separator and name in allowed:
            os.environ.setdefault(name, value.strip())


class IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6
    daemon_threads = True


def handler_for(product, *, device=False, device_key="", csrf="", cookie="", port=8787,
                host_url="", peer=None):
    origin = f"http://127.0.0.1:{port}"
    web = Path(__file__).with_name("web")

    class Handler(BaseHTTPRequestHandler):
        server_version = "Modulate"

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # Never log bearer tokens, request text or private device addresses.

        def send(self, status, data, content_type="application/json", *, session=False):
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            if session:
                self.send_header("Set-Cookie", f"modulate={cookie}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self, *, mutation=False):
            if device:
                try:
                    if not device_key or not isinstance(device_key, str):
                        return False
                    remote = ipaddress.ip_address(self.client_address[0])
                    expected = ipaddress.ip_address(peer)
                    if remote != expected:
                        return False
                    return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + device_key)
                except (ValueError, TypeError):
                    return False
            if self.headers.get("Host", "") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return False
            request_origin = self.headers.get("Origin")
            if request_origin is not None and request_origin not in {origin, f"http://localhost:{port}"}:
                return False
            if mutation:
                if not csrf or not cookie:
                    return False
                if self.headers.get("Origin") not in {origin, f"http://localhost:{port}"}:
                    return False
                jar = SimpleCookie()
                try:
                    if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                        return False
                    jar.load(self.headers.get("Cookie", ""))
                    return "modulate" in jar and secrets.compare_digest(jar["modulate"].value, cookie)
                except Exception:
                    return False
            return True

        def do_GET(self):
            if device or not self.authorized():
                return self.send(403, {"error": "Forbidden"})
            path = urlparse(self.path).path
            if path == "/api/state":
                return self.send(200, product.state())
            if path == "/api/csrf":
                return self.send(200, {"token": csrf}, session=True)
            if path == "/api/preview.png":
                return self.send(200, product.preview_bytes, "image/png") if product.preview_bytes else self.send(404, {"error": "No live frame yet"})
            if path == "/api/candidate-preview.png":
                return self.send(200, product.candidate_preview_bytes, "image/png") if product.candidate_preview_bytes else self.send(404, {"error": "No candidate preview yet"})
            names = {"/": ("index.html", "text/html; charset=utf-8"), "/lab": ("lab.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/lab.js": ("lab.js", "text/javascript; charset=utf-8"),
                     "/lab.css": ("lab.css", "text/css; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path not in names:
                return self.send(404, {"error": "Not found"})
            filename, mime = names[path]
            return self.send(200, (web / filename).read_bytes(), mime, session=True)

        def do_POST(self):
            if not self.authorized(mutation=True):
                return self.send(403, {"error": "Forbidden"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1
                        or not 0 < length <= 256 * 1024
                        or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json"):
                    return self.send(413, {"error": "Expected bounded JSON body"})
                def unique_fields(pairs):
                    result = {}
                    for name, value in pairs:
                        if name in result:
                            raise ValueError("Duplicate JSON field")
                        result[name] = value
                    return result

                def invalid_number(value):
                    raise ValueError("Non-finite JSON number")

                data = json.loads(self.rfile.read(length), object_pairs_hook=unique_fields, parse_constant=invalid_number)
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                path = urlparse(self.path).path
                if device:
                    if path == "/device/speech":
                        return self.send(200, product.get_speech_audio(data.get("id")), "application/octet-stream")
                    elif path == "/device/audio":
                        result = product.audio_packet(data.get("session"), data.get("after"))
                    elif path == "/device/audio/stop":
                        if not isinstance(data.get("session"), str):
                            raise ValueError("Identify the stream to stop")
                        result = product.stop_computer_audio(data["session"])
                    elif path == "/device/heartbeat":
                        result = product.heartbeat(data)
                    elif path == "/device/request":
                        result = product.request(data.get("text"), source="microphone", followup_id=data.get("followup_id"))
                    elif path == "/device/unclear":
                        result = product.unclear(data.get("reason"), followup_id=data.get("followup_id"))
                    elif path == "/device/cancel":
                        job_id = data.get("job_id")
                        if not isinstance(job_id, str) or len(job_id) != 32:
                            raise ValueError("Cancellation must identify the heard request")
                        result = product.cancel(job_id)
                    elif path == "/device/pair":
                        result = product.pair(data.get("code"), str(data.get("name", "Modulate Pi"))[:80])
                    elif path == "/device/rollback":
                        result = product.rollback()
                    else:
                        return self.send(404, {"error": "Unknown device action"})
                elif path == "/api/request":
                    result = product.request(data.get("text"), followup_id=data.get("followup_id"))
                elif path == "/api/context/clear":
                    result = product.clear_context()
                elif path == "/api/cancel":
                    result = product.cancel()
                elif path == "/api/draft":
                    result = product.draft(data.get("job_id"), data.get("action"), data.get("text"))
                elif path == "/api/computer":
                    result = product.computer_session(data.get("action"), minutes=data.get("minutes", 15))
                elif path == "/api/audio/stop":
                    result = product.stop_computer_audio()
                elif path == "/api/camera/stop":
                    result = product.stop_camera()
                elif path == "/api/computer/approval":
                    result = product.approve_computer_action(data.get("id"), data.get("approved"))
                elif path == "/api/response/dismiss":
                    result = product.dismiss_response(data.get("id"))
                elif path == "/api/speaker":
                    result = product.speaker_action(data.get("action"))
                elif path == "/api/pairing":
                    result = {**product.create_pairing(), "host_url": host_url}
                elif path == "/api/revoke":
                    result = product.revoke()
                elif path == "/api/rollback":
                    result = product.rollback()
                elif path == "/api/wake":
                    if type(data.get("enabled")) is not bool:
                        raise ValueError("enabled must be boolean")
                    product.wake = data["enabled"]
                    result = {"enabled": product.wake}
                else:
                    return self.send(404, {"error": "Unknown action"})
                self.send(200, result)
            except (AgentError, BridgeError, ValueError) as error:
                self.send(400, {"error": str(error)[:500]})
            except Exception:
                self.send(500, {"error": "The local service could not complete this action"})

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Modulate companion studio")
    parser.add_argument("--state-dir", default="context/private/product")
    parser.add_argument("--provider", choices=["meta", "ollama", "fireworks"], default="meta")
    parser.add_argument("--model", default="muse-spark-1.3")
    parser.add_argument("--env-file")
    parser.add_argument("--budget", type=float, default=0, help="Explicit approved dollar ceiling; defaults to no cloud calls")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--device-port", type=int, default=8788)
    parser.add_argument("--host-address", required=True, help="This computer's LAN IPv4/IPv6 address")
    parser.add_argument("--device-address", required=True, help="Only this peer may access the TLS device endpoint")
    args = parser.parse_args()
    os.umask(0o077)
    load_credentials(args.env_file)
    directory = Path(args.state_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (directory / "studio.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    provider = AgentProvider({"provider": args.provider, "model": args.model, "max_tokens": 8192,
                              "reasoning_effort": "low" if args.provider == "meta" else None})
    product = Product(directory, provider, budget=args.budget)
    address = ipaddress.ip_address(args.host_address)
    host_url = f"https://[{address}]:{args.device_port}" if address.version == 6 else f"https://{address}:{args.device_port}"
    enrollment = directory / "device-enrollment.json"
    key = json.loads(enrollment.read_text())["device_key"] if enrollment.exists() else secrets.token_urlsafe(32)
    tls, certificate = tls_material(directory, str(address))
    atomic_json(enrollment, {"host_url": host_url, "device_key": key, "ca_file": "device-cert.pem"})
    server_type = IPv6Server if address.version == 6 else ThreadingHTTPServer
    device_server = server_type((str(address), args.device_port), handler_for(product, device=True, device_key=key, peer=args.device_address))
    device_server.socket = tls.wrap_socket(device_server.socket, server_side=True)
    studio = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(product, csrf=secrets.token_urlsafe(32),
                               cookie=secrets.token_urlsafe(32), port=args.port, host_url=host_url))
    for server in (device_server, studio):
        server.daemon_threads = True
    threading.Thread(target=device_server.serve_forever, daemon=True).start()
    print(f"Modulate Studio: http://127.0.0.1:{args.port}", flush=True)
    print("Device endpoint uses pinned TLS, bearer authentication and an exact peer allowlist.", flush=True)
    try:
        studio.serve_forever()
    except KeyboardInterrupt:
        product.cancel()
    finally:
        product.stop_computer_audio()
        if product.camera:
            product.camera.stop()
        studio.server_close()
        device_server.shutdown()
        device_server.server_close()
        lock.close()


if __name__ == "__main__":
    main()
