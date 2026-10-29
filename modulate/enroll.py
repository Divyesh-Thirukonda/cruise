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
import subprocess
import threading
import time
from urllib.parse import urlsplit


class EnrollmentError(ValueError):
    def __init__(self, message, code="setup_error", next_action="check_studio", **details):
        super().__init__(message)
        self.code = code
        self.next_action = next_action
        self.details = details

    def result(self):
        return {"status": "error", "stage": "device_link", "error_code": self.code,
                "message": str(self), "next_action": self.next_action, **self.details}


# Device responses are untrusted. Never display their free-form error strings.
DEVICE_ERRORS = {
    "setup_closed": ("Setup is closed on the gadget. Press small A to open a new setup window.", "new_setup_code"),
    "setup_expired": ("The device setup code expired. Press small A for a fresh code, then enter it here.", "new_setup_code"),
    "wrong_code": ("The device did not accept that code. Check its current eight digits and setup window on the gadget.", "check_code"),
    "attempts_exhausted": ("Too many incorrect attempts closed setup. Press small A for a fresh code.", "new_setup_code"),
    "request_pending": ("A link request is already waiting on the gadget. Check that screen before starting another request.", "check_device"),
    "already_enrolled": ("This gadget already has a saved device link. Open connection setup to check the existing connection.", "check_studio"),
    "invalid_enrollment": ("The gadget rejected this Mac’s connection configuration. Ask your agent to check Studio’s address and certificate.", "check_studio"),
    "source_mismatch": ("Studio’s address does not match the Mac reaching the gadget. Ask your agent to check the current network route.", "check_studio"),
    "receipt_not_found": ("The gadget no longer has this request. Check its screen; this helper has not confirmed a link.", "check_device"),
    "setup_window_unavailable": ("The gadget’s setup window is closed or expired. Press small A for a fresh setup code.", "new_setup_code"),
    "save_failed": ("The gadget could not save the device link. No completed link was confirmed. Check the gadget before retrying; if this repeats, it needs device support.", "check_device"),
}
LEGACY_DEVICE_ERRORS = {
    "Open setup on the device first": "setup_window_unavailable",
    "Setup code not accepted": "wrong_code",
    "A setup request is already waiting on the device": "request_pending",
    "Setup window changed; try the current code": "setup_window_unavailable",
    "Companion address must match the connecting Mac": "source_mismatch",
    "Setup receipt not found": "receipt_not_found",
    "Only companion enrollment is accepted": "invalid_enrollment",
    "Invalid companion origin": "invalid_enrollment",
    "Use the Mac's HTTPS device endpoint on port 8788": "invalid_enrollment",
    "Invalid companion credential": "invalid_enrollment",
    "Use one public companion certificate": "invalid_enrollment",
    "Companion certificate does not match its address": "invalid_enrollment",
}


def device_error(result):
    reason = result.get("reason")
    if reason is None:
        legacy = result.get("error")
        reason = LEGACY_DEVICE_ERRORS.get(legacy) if type(legacy) is str else None
    if type(reason) is str and reason in DEVICE_ERRORS:
        message, action = DEVICE_ERRORS[reason]
        return EnrollmentError(message, reason, action)
    return EnrollmentError("The gadget declined setup without a recognized reason. Check its screen; no completed link was confirmed.",
                           "setup_declined", "check_device")


def device_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise EnrollmentError("Use the network address shown on your Modulate.") from None
    if (address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local
            or getattr(address, "scope_id", None) is not None or getattr(address, "ipv4_mapped", None) is not None):
        raise EnrollmentError("Use the reachable IPv4 or IPv6 address shown on your Modulate, without a zone suffix.")
    return str(address)


def mac_address(device):
    """Ask the OS for the route's source address; sends no network payload."""
    target = device_address(device)
    family = socket.AF_INET6 if ipaddress.ip_address(target).version == 6 else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as route:
        route.connect((target, 8790))
        return device_address(route.getsockname()[0])


def load_enrollment(directory, device):
    directory = Path(directory).resolve()
    path = directory / "device-enrollment.json"
    if not path.is_file() or path.stat().st_mode & 0o077 or path.stat().st_size > 16384:
        raise EnrollmentError("Start Modulate Studio first, using this installation’s existing private state directory.")
    try:
        config = json.loads(path.read_text())
        host = urlsplit(config["host_url"])
        expected = mac_address(device)
        if (host.scheme != "https" or device_address(host.hostname) != expected or host.port != 8788
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
        identity_check = subprocess.run(["openssl", "x509", "-in", str(certificate), "-noout", "-checkip", expected],
                                        capture_output=True, text=True, timeout=3)
        # Some OpenSSL versions return zero even when the address does not match.
        # Require the exact positive result as well as success before exporting it.
        if identity_check.returncode != 0 or identity_check.stdout.strip() != f"IP {expected} does match certificate":
            raise EnrollmentError("Studio’s device certificate does not match this Mac’s current address. Repair its certificate and enrollment first.")
    except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as error:
        if isinstance(error, EnrollmentError):
            raise
        raise EnrollmentError("Studio’s device enrollment is invalid; preserve its state and repair the configuration.") from None
    return {"host_url": config["host_url"], "device_key": key, "ca_pem": pem}


def pinned_post(device, fingerprint, path, body, *, port=8790):
    device = device_address(device)
    pin = re.sub(r"[\s:-]", "", fingerprint).lower()
    if re.fullmatch(r"[0-9a-f]{20}", pin) is None:
        raise EnrollmentError("Enter both groups of the 20-character identity shown on the gadget.", "invalid_identity", "check_identity")
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
            positions = [{"group": index // 10 + 1, "character": index % 10 + 1}
                         for index in range(20) if actual[index] != pin[index]]
            if len(positions) <= 4:
                where = "; ".join(f"group {item['group']}, character {item['character']}" for item in positions)
                message = f"Identity mismatch at {where}. Recheck those characters on the gadget. Nothing was sent."
            else:
                message = "The gadget identity differs in several characters. Recheck both groups on the physical screen. Nothing was sent."
            # Positions help locate transcription errors without providing or
            # automatically trusting the certificate identity from the network.
            raise EnrollmentError(message, "identity_mismatch", "check_identity", mismatch_positions=positions)
        connection.request("POST", path, raw_body, {"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(16385)
        if len(raw) > 16384:
            raise EnrollmentError("The gadget returned an invalid setup response.", "invalid_response", "check_device")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise EnrollmentError("The gadget returned an unreadable setup response.", "invalid_response", "check_device") from None
        if not isinstance(result, dict):
            raise EnrollmentError("The gadget returned an invalid setup response.", "invalid_response", "check_device")
        if response.status != 200:
            raise device_error(result)
        return result
    except (OSError, http.client.HTTPException):
        raise EnrollmentError("Cannot reach the gadget’s setup service. Check both devices’ network and the gadget’s setup screen.",
                              "device_unreachable", "check_network") from None
    finally:
        connection.close()


class EnrollmentJob:
    def __init__(self, device, directory):
        self.device, self.directory = device_address(device), Path(directory)
        self.lock = threading.Lock()
        self.result = {"status": "ready", "stage": "device_link", "next_action": "enter_details", "updated_at": time.monotonic()}
        self.cancelled = threading.Event()

    def snapshot(self):
        with self.lock:
            return dict(self.result)

    def update(self, **result):
        with self.lock:
            self.result = {**result, "updated_at": time.monotonic()}

    def start(self, fingerprint, code):
        if type(fingerprint) is not str or type(code) is not str or re.fullmatch(r"[0-9]{8}", code) is None:
            raise EnrollmentError("Enter the eight-digit device setup code, keeping any leading zeroes.", "invalid_code", "check_code")
        with self.lock:
            if self.result["status"] in {"connecting", "awaiting_confirmation", "complete"}:
                raise EnrollmentError("A device setup is already in progress or complete. Check the current step before submitting again.", "setup_in_progress", "check_device")
            self.result = {"status": "connecting", "stage": "device_link", "next_action": "wait", "updated_at": time.monotonic()}
        self.cancelled.clear()
        threading.Thread(target=self.run, args=(fingerprint, code), daemon=True).start()

    def run(self, fingerprint, code):
        try:
            enrollment = load_enrollment(self.directory, self.device)
            proposal = pinned_post(self.device, fingerprint, "/enroll", {"code": code, "enrollment": enrollment})
            identifier = proposal.get("id")
            if proposal.get("status") != "awaiting_confirmation" or type(identifier) is not str or re.fullmatch(r"[0-9a-f]{32}", identifier) is None:
                raise EnrollmentError("The gadget did not acknowledge a pending setup. Nothing is confirmed.", "invalid_response", "check_device")
            staged_mac = str(ipaddress.ip_address(urlsplit(enrollment["host_url"]).hostname))
            self.update(status="awaiting_confirmation", stage="device_confirmation", next_action="confirm_on_device",
                        request_suffix=identifier[-8:].upper(), mac_address=staged_mac,
                        message=f"Compare Mac {staged_mac} and request {identifier[-8:].upper()} with the gadget. Only if both match, release and press small A to link this device. Small B declines.")
            deadline = time.monotonic() + 300
            while not self.cancelled.wait(1) and time.monotonic() < deadline:
                reply = pinned_post(self.device, fingerprint, "/status", {"id": identifier, "code": code})
                if reply.get("id") != identifier:
                    raise EnrollmentError("The gadget acknowledged a different setup request. This link is not confirmed.", "request_mismatch", "check_device")
                status = reply.get("status")
                if status == "complete":
                    self.update(status="complete", stage="mac_access", next_action="open_setup",
                                setup_url="http://127.0.0.1:8787/setup",
                                message="Device linked. Opening connection setup to compare Mac access, then continue to the Modulate website.")
                    return
                if status == "expired":
                    raise EnrollmentError("The pending link expired before confirmation. Press small A for a fresh setup code.",
                                          "setup_expired", "new_setup_code")
                if status == "rejected":
                    reason = reply.get("reason")
                    if type(reason) is str and reason in DEVICE_ERRORS:
                        raise device_error({"reason": reason})
                    # Legacy devices use this receipt for both physical decline
                    # and a failed save. It cannot establish which happened.
                    raise EnrollmentError("The gadget did not complete this link request and did not report a specific reason. Check its screen before retrying; this helper has not confirmed a link.",
                                          "setup_rejected", "check_device")
                if status != "awaiting_confirmation":
                    raise EnrollmentError("The gadget returned an unknown setup state. Check the device screen.", "invalid_response", "check_device")
            stopped = getattr(self.cancelled, "is_set", lambda: False)()
            raise EnrollmentError("Setup was stopped. Press B on the gadget to cancel any pending link." if stopped
                                  else "The helper timed out waiting for confirmation. Check the gadget before starting another request.",
                                  "setup_stopped" if stopped else "setup_timeout", "check_device")
        except EnrollmentError as error:
            self.update(**error.result())
        except Exception:
            self.update(**EnrollmentError("Setup could not finish. Keep the existing state and check Studio.").result())


PAGE = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Link your Modulate</title>
<style>
body{background:#151719;color:#eef0f4;font:16px system-ui;margin:48px auto;padding:24px;max-width:560px}
p{color:#b9c1cb;line-height:1.6}h1{letter-spacing:-.04em}label{display:block;margin:24px 0 8px}
input,button,.primary{box-sizing:border-box;width:100%;font:inherit;padding:14px;border-radius:10px;border:1px solid #454b55;background:#20242a;color:inherit}
input{font-family:ui-monospace,monospace;letter-spacing:.08em}button,.primary{margin-top:24px;background:#459eff;color:#102036;font-weight:650;cursor:pointer}
button:disabled{opacity:.55;cursor:wait}small{display:block;margin:8px 0;color:#9aa7b8;line-height:1.5}
#status{white-space:pre-line;padding:16px;background:#20242a;border-radius:10px}#status:empty{display:none}
a{color:#69b1ff}.primary{display:block;text-align:center;text-decoration:none}ol{display:flex;gap:16px;padding:0;list-style:none;color:#8b99aa;font-size:12px}li[aria-current=step]{color:#69b1ff}#complete{border-top:1px solid #454b55;margin-top:24px;padding-top:8px}[hidden]{display:none!important}
</style>
<ol aria-label="Setup progress"><li id="step-link" aria-current="step">1 · Device link</li><li id="step-confirm">2 · Confirm on gadget</li><li id="step-mac">3 · Mac access</li></ol>
<h1>Link your Modulate.</h1>
<p id="intro">Press small A on your gadget to open setup. Use its two identity groups and eight-digit device setup code below. This sends a request; a separate press on the gadget approves it.</p>
<form id="form">
<label for="identity">Gadget identity</label><input id="identity" autocomplete="off" spellcheck="false" autocapitalize="characters" maxlength="40" required placeholder="0123456789 ABCDEF0123">
<small>Two groups of ten characters. Use the physical screen, not an identity reported by the network.</small>
<label for="code">Device setup code</label><input id="code" type="password" inputmode="numeric" autocomplete="off" pattern="[0-9]{8}" maxlength="8" required placeholder="8 digits">
<small>Expires after five minutes. This is not a Mac-access or website connection code.</small>
<button id="submit">Send link request</button>
</form>
<p id="status" role="status" aria-live="polite"></p>
<section id="complete" hidden><h2>Your device link is saved.</h2><p>Opening connection setup. Compare the Mac access code on both screens before approving, then finish on the Modulate website.</p><a class="primary" href="http://127.0.0.1:8787/setup">Continue setup</a></section>
<p id="studio-link"><a href="http://127.0.0.1:8787/setup">Open connection setup</a></p>
<small>Local setup: this form sends connection details to your gadget, not a cloud service.</small>
<script>
const csrf=__CSRF__;
const form=document.getElementById('form'), status=document.getElementById('status'), submit=document.getElementById('submit');
let newest=-1, submitting=false, polling=false, complete=false, timer;
function render(d){
  if(complete || !d || typeof d.status!=='string')return;
  if(typeof d.updated_at==='number'){if(d.updated_at<newest)return;newest=d.updated_at;}
  status.textContent=d.message||(d.status==='connecting'?'Checking the gadget identity and sending your request…':'');
  const pending=d.status==='awaiting_confirmation';
  complete=d.status==='complete';
  form.hidden=pending||complete;
  submit.disabled=submitting||['connecting','awaiting_confirmation'].includes(d.status);
  if(pending||complete)document.getElementById('code').value='';
  document.getElementById('complete').hidden=!complete;
  document.getElementById('intro').hidden=pending||complete;
  document.getElementById('studio-link').hidden=complete;
  for(const [id,current] of [['step-link',!pending&&!complete],['step-confirm',pending],['step-mac',complete]]){
    const el=document.getElementById(id);if(current)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');
  }
  if(complete){clearInterval(timer); if(typeof window!=='undefined')window.location.replace('http://127.0.0.1:8787/setup');}
}
form.onsubmit=async e=>{
  e.preventDefault();if(submitting||complete)return;submitting=true;submit.disabled=true;
  try{
    const r=await fetch('/enroll',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({fingerprint:document.getElementById('identity').value,code:document.getElementById('code').value})});
    const d=await r.json();submitting=false;
    if(!r.ok){status.textContent=d.error||'Setup could not start. Refresh this page and check the current gadget screen.';submit.disabled=false;return;}
    render(d);
  }catch{status.textContent='The setup helper could not be reached. Ask your agent to check it before retrying.';submit.disabled=false;}
  finally{submitting=false;}
};
async function poll(){
  if(polling||submitting||complete)return;polling=true;
  try{const r=await fetch('/status');if(!r.ok)throw Error();const d=await r.json();if(!submitting)render(d);}
  catch{if(!complete&&!submitting)status.textContent='The setup helper stopped responding. Ask your agent to check it.';}
  finally{polling=false;}
}
timer=setInterval(poll,1000);poll();
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
                self.send(202, {"started": True, **job.snapshot()})
            except EnrollmentError as error:
                self.send(400, {"error": str(error), **error.result()})
            except (ValueError, TypeError):
                self.send(400, {"error": "Check the gadget identity and eight-digit setup code, then try again.", "error_code": "invalid_input"})

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"Modulate device setup: {origin}", flush=True)
    print("Use the local setup page for the gadget identity and code. Avoid sharing codes in chat; agent-assisted entry follows the user’s preference.", flush=True)
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
