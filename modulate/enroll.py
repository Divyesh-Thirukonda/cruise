"""Mac-only enrollment of a preloaded Modulate. No SSH or Pi shell access."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
from pathlib import Path
import re
import secrets
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit


class EnrollmentError(ValueError):
    pass


def device_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise EnrollmentError("Use the network address shown on your Modulate.") from None
    if address.version != 4 or address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local:
        raise EnrollmentError("Use the IPv4 address shown on your Modulate, on the same network as this Mac.")
    return str(address)


def mac_address(device):
    """Ask the OS for the route's source address; sends no network payload."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect((device_address(device), 8790))
        return route.getsockname()[0]


def load_enrollment(directory, device):
    directory = Path(directory).resolve()
    path = directory / "device-enrollment.json"
    if not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_size > 16384:
        raise EnrollmentError("Start Modulate Studio first, using this installation’s existing private state directory.")
    try:
        config = json.loads(path.read_text())
        host = urlsplit(config["host_url"])
        expected = mac_address(device)
        if (host.scheme != "https" or host.hostname != expected or host.port != 8788
                or host.path not in ("", "/") or host.username or host.password or host.query or host.fragment):
            raise EnrollmentError("Studio’s device endpoint does not match this Mac’s route to Modulate. Repair its address and certificate first.")
        certificate = (directory / config["ca_file"]).resolve()
        if certificate.parent != directory or not certificate.is_file() or certificate.stat().st_size > 8192:
            raise EnrollmentError("Studio’s device certificate is missing or outside its private state directory.")
        pem = certificate.read_text()
        key = config["device_key"]
        if not isinstance(key, str) or not 32 <= len(key) <= 256 or not key.isascii() or any(c.isspace() for c in key):
            raise EnrollmentError("Studio’s device enrollment is invalid.")
        if re.fullmatch(r"\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*", pem) is None:
            raise EnrollmentError("Studio’s public device certificate is invalid.")
        certificate_check = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        certificate_check.load_verify_locations(cadata=pem)
    except (OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, EnrollmentError):
            raise
        raise EnrollmentError("Studio’s device enrollment is invalid; preserve its state and repair the configuration.") from None
    return {"host_url": config["host_url"], "device_key": key, "ca_pem": pem}


def pinned_post(device, fingerprint, path, body, *, port=8790):
    device = device_address(device)
    pin = re.sub(r"[\s:-]", "", fingerprint).lower()
    if re.fullmatch(r"[0-9a-f]{20}", pin) is None:
        raise EnrollmentError("Enter the complete 20-character identity shown on the gadget.")
    if path not in {"/enroll", "/status"}:
        raise EnrollmentError("Unsupported setup operation.")
    try:
        raw_body = json.dumps(body, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        raise EnrollmentError("The device setup request is invalid.") from None
    if len(raw_body) > 16384:
        raise EnrollmentError("The device setup request is too large.")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Physical certificate pin is checked BEFORE any HTTP bytes.
    connection = http.client.HTTPSConnection(device, port, context=context, timeout=5)
    try:
        connection.connect()
        actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()[:20]
        if not hmac.compare_digest(actual, pin):
            raise EnrollmentError("The gadget identity does not match. Nothing was sent. Check the device screen.")
        connection.request("POST", path, raw_body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(16385)
        if len(raw) > 16384:
            raise EnrollmentError("The gadget returned an invalid setup response.")
        result = json.loads(raw)
        if response.status != 200 or not isinstance(result, dict):
            raise EnrollmentError("The gadget declined setup. Check the code, expiry, and setup screen, then try again.")
        return result
    except (OSError, http.client.HTTPException, json.JSONDecodeError):
        raise EnrollmentError("Cannot reach the gadget’s setup service. Check both devices’ network and the gadget’s setup screen.") from None
    finally:
        connection.close()


class EnrollmentJob:
    def __init__(self, device, directory):
        self.device, self.directory = device_address(device), Path(directory)
        self.lock = threading.Lock()
        self.result = {"status": "ready"}
        self.cancelled = threading.Event()

    def snapshot(self):
        with self.lock:
            return dict(self.result)

    def update(self, **result):
        with self.lock:
            self.result = result

    def start(self, fingerprint, code):
        if type(fingerprint) is not str or type(code) is not str or re.fullmatch(r"[0-9]{8}", code) is None:
            raise EnrollmentError("Enter the eight-digit device setup code, keeping any leading zeroes.")
        with self.lock:
            if self.result["status"] in {"connecting", "awaiting_confirmation", "complete"}:
                raise EnrollmentError("A device setup is already in progress or complete.")
            self.result = {"status": "connecting"}
        self.cancelled.clear()
        threading.Thread(target=self.run, args=(fingerprint, code), daemon=True).start()

    def run(self, fingerprint, code):
        try:
            enrollment = load_enrollment(self.directory, self.device)
            proposal = pinned_post(self.device, fingerprint, "/enroll", {"code": code, "enrollment": enrollment})
            identifier = proposal.get("id")
            if proposal.get("status") != "awaiting_confirmation" or type(identifier) is not str or re.fullmatch(r"[0-9a-f]{32}", identifier) is None:
                raise EnrollmentError("The gadget did not acknowledge a pending setup. Nothing is confirmed.")
            self.update(status="awaiting_confirmation", message=f"On Modulate, check Mac {mac_address(self.device)} and request {identifier[-8:].upper()}. Press the small A button to accept, or B to cancel.")
            deadline = time.monotonic() + 300
            while not self.cancelled.wait(1) and time.monotonic() < deadline:
                reply = pinned_post(self.device, fingerprint, "/status", {"id": identifier, "code": code})
                if reply.get("id") != identifier:
                    raise EnrollmentError("The gadget acknowledged a different setup request. This link is not confirmed.")
                status = reply.get("status")
                if status == "complete":
                    self.update(status="complete", message="Device link saved. Open Studio to confirm Mac access on the gadget, then create your website connection code.")
                    return
                if status in {"expired", "rejected"}:
                    raise EnrollmentError("Device setup expired or was declined. Press A on the gadget to begin a new attempt.")
                if status != "awaiting_confirmation":
                    raise EnrollmentError("The gadget returned an unknown setup state. Check the device screen.")
            raise EnrollmentError("Setup was stopped or timed out. Press B on the gadget to cancel any pending link.")
        except EnrollmentError as error:
            self.update(status="error", message=str(error))
        except Exception:
            self.update(status="error", message="Setup could not finish. Keep the existing state and check Studio.")


PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Link your Modulate</title><style>body{background:#151719;color:#eef0f4;font:16px system-ui;margin:60px auto;padding:24px;max-width:560px}p{color:#b9c1cb;line-height:1.6}label{display:block;margin:24px 0 8px}input,button{box-sizing:border-box;width:100%;font:inherit;padding:14px;border-radius:10px;border:1px solid #454b55;background:#20242a;color:inherit}button{margin-top:24px;background:#459eff;color:#102036;font-weight:650;cursor:pointer}small{display:block;margin:8px 0;color:#9aa7b8}#status{white-space:pre-line}a{color:#69b1ff}</style><h1>Link your Modulate.</h1><p>Press the small A button on your gadget to open setup. Enter the identity and setup code shown on its screen. These stay between this Mac and your gadget.</p><form id="form"><label for="identity">Gadget identity</label><input id="identity" autocomplete="off" required placeholder="Two rows of 10 characters"><small>Copy both rows exactly. This checks that you are connecting to your own gadget.</small><label for="code">Device setup code</label><input id="code" inputmode="numeric" autocomplete="off" pattern="[0-9]{8}" maxlength="8" required placeholder="00000000"><small>This is the device setup code, not the later website connection code.</small><button id="submit">Link this Mac</button></form><p id="status" role="status"></p><p><a href="http://127.0.0.1:8787">Open local Studio</a></p><script>
const csrf=__CSRF__;
const form=document.getElementById('form'), status=document.getElementById('status'), submit=document.getElementById('submit');
form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{const r=await fetch('/enroll',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({fingerprint:document.getElementById('identity').value,code:document.getElementById('code').value})});const d=await r.json();if(!r.ok)throw Error(d.error||'Setup failed');document.getElementById('code').value='';status.textContent='Connecting to your gadget…';}catch(e){status.textContent=e.message;submit.disabled=false;}};
setInterval(async()=>{try{const r=await fetch('/status');const d=await r.json();if(d.message)status.textContent=d.message;if(d.status==='complete'){form.hidden=true;}else submit.disabled=['connecting','awaiting_confirmation'].includes(d.status);}catch{status.textContent='The setup helper stopped. Ask your agent to reopen it.'}},1000);
</script></html>"""


def serve(job, port=8791):
    csrf, session = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    origin = f"http://127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def send(self, status, value, html=False, cookie=False):
            raw = value.encode() if html else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if cookie:
                self.send_header("Set-Cookie", f"modulate_setup={session}; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            return self.headers.get("Host") == f"127.0.0.1:{port}"

        def do_GET(self):
            if not self.valid_host():
                return self.send(403, {"error": "Forbidden"})
            if self.path == "/":
                return self.send(200, PAGE.replace("__CSRF__", json.dumps(csrf)), html=True, cookie=True)
            if self.path == "/status":
                return self.send(200, job.snapshot())
            return self.send(404, {"error": "Not found"})

        def do_POST(self):
            try:
                jar = SimpleCookie(self.headers.get("Cookie", ""))
                if (not self.valid_host() or self.headers.get("Origin") != origin or self.path != "/enroll"
                        or not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf)
                        or "modulate_setup" not in jar or not hmac.compare_digest(jar["modulate_setup"].value, session)):
                    return self.send(403, {"error": "Refresh this setup page before continuing."})
                if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1 or self.headers.get("Content-Type") != "application/json":
                    raise EnrollmentError("Expected a bounded setup request.")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 1024:
                    raise EnrollmentError("Expected a bounded setup request.")
                value = json.loads(self.rfile.read(length))
                if type(value) is not dict or set(value) != {"fingerprint", "code"}:
                    raise EnrollmentError("Only the gadget identity and setup code are accepted.")
                job.start(value["fingerprint"], value["code"])
                self.send(202, {"started": True})
            except (ValueError, TypeError):
                self.send(400, {"error": "Check the gadget identity and eight-digit setup code, then try again."})

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Modulate device setup: {origin}", flush=True)
    print("Enter the identity and code directly in this local page; keep them out of chat and logs.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        job.cancelled.set()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-address", required=True, type=device_address)
    parser.add_argument("--state-dir", default="context/private/product")
    parser.add_argument("--print-host-address", action="store_true", help="Print the Mac route address without sending a network payload")
    args = parser.parse_args()
    if args.print_host_address:
        print(mac_address(args.device_address))
        return
    load_enrollment(args.state_dir, args.device_address)
    serve(EnrollmentJob(args.device_address, args.state_dir))


if __name__ == "__main__":
    main()
