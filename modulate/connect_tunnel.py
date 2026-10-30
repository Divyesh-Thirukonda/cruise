"""Supervise the existing Quick Tunnel and register changes with our fixed site.

The device holds its existing scoped gateway secret, never a Vercel admin token.
No raw cloudflared output or credentials are written by this wrapper.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request

from .device_transport import NoRedirect
from .studio import load_credentials

DISCOVERY_URL = "https://modulate-connect.vercel.app/api/modulate-discovery"
ORIGIN = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com")


def register(origin, secret):
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}\n{origin}".encode(), hashlib.sha256).hexdigest()
    request = urllib.request.Request(DISCOVERY_URL,
        json.dumps({"origin": origin, "timestamp": timestamp}).encode(),
        {"Content-Type": "application/json", "X-Modulate-Signature": signature})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
        if json.loads(response.read(1024)).get("registered") is not True:
            raise ValueError("Registration was not acknowledged")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--cloudflared", required=True)
    args = parser.parse_args()
    load_credentials(args.env_file)
    secret = os.environ["MODULATE_REMOTE_SECRET"]
    process = subprocess.Popen([args.cloudflared, "tunnel", "--no-autoupdate", "--protocol", "http2",
                                "--url", "http://127.0.0.1:8789"],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    stopped = threading.Event()
    def stop(*_):
        stopped.set()
        process.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def publish(origin):
        while not stopped.is_set() and process.poll() is None:
            try:
                register(origin, secret)
                print("Website discovery registered the current device tunnel", flush=True)
                delay = 3600  # Writes happen only when the hostname changes.
            except Exception:
                print("Website discovery unavailable; retrying in 30 seconds", flush=True)
                delay = 30
            stopped.wait(delay)
    worker = None
    try:
        for line in process.stdout:
            match = ORIGIN.search(line)
            if match and worker is None:
                worker = threading.Thread(target=publish, args=(match.group(),), daemon=True)
                worker.start()
        result = process.wait()
        if result and not stopped.is_set():
            raise SystemExit(result)
    finally:
        stop()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
