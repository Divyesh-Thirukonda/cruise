"""Loopback-only comparison screen; it cannot authorize physical pairing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import json
import secrets
import threading
import time

PAGE = b'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Connect this Mac to Modulate</title>
<style>body{font:18px system-ui;background:#f6f5f0;color:#252622;max-width:600px;margin:12vh auto;padding:30px}h1{font-size:42px}#code{font-size:52px;letter-spacing:8px;font-weight:700}p{line-height:1.6}a{color:inherit}</style>
<h1>Connect this Mac.</h1><p id="message">Checking your connection...</p><div id="code"></div><p id="expiry"></p><p>Modulate's apps and AI keep working without this Mac. Mac access lasts up to eight hours and can be revoked in the website's Device page.</p><a href="https://modulate-connect.vercel.app/connect">Return to Modulate Connect</a>
<script>async function refresh(){try{const r=await fetch('/status');const s=await r.json();document.getElementById('message').textContent=s.paired?'Mac connected. You can now ask Modulate to control it.':s.code?'Compare these eight digits with Modulate, then press the small A button on the device. You do not type this comparison code into the website.':'No active pairing. Ask your setup agent to reconnect this helper.';document.getElementById('code').textContent=s.code||'';document.getElementById('expiry').textContent=s.expires_at?'Session ends '+new Date(s.expires_at*1000).toLocaleTimeString():''}catch{document.getElementById('message').textContent='Mac helper is reconnecting...'}}refresh();setInterval(refresh,1000)</script></html>'''


def start(native, pairing):
    cookie = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if self.headers.get("Host") != "127.0.0.1:8787":
                self.send_error(403)
                return
            if self.path == "/setup":
                body, kind = PAGE, "text/html; charset=utf-8"
            elif self.path == "/status" and SimpleCookie(self.headers.get("Cookie", "")).get("modulate_mac") and SimpleCookie(self.headers.get("Cookie", ""))["modulate_mac"].value == cookie:
                paired = bool(native.session and native.lease > time.monotonic())
                body = json.dumps({"paired": paired, "code": pairing.get("code") if not paired and pairing.get("expires_at", 0) > time.time() else None,
                                   "expires_at": native.expires_at if paired else None}).encode()
                kind = "application/json"
            else:
                self.send_error(403)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            if self.path == "/setup": self.send_header("Set-Cookie", "modulate_mac=" + cookie + "; HttpOnly; SameSite=Strict; Path=/")
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 8787), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
