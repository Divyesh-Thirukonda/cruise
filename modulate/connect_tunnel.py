"""Supervise the existing Quick Tunnel and register changes with our fixed site.

The device holds its existing scoped gateway secret, never a Vercel admin token.
No raw cloudflared output or credentials are written by this wrapper.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import urllib.request

from .device_transport import NoRedirect, save_private
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


def publish(origin, secret, status_path, process, stopped):
    save_private(status_path, {"origin": origin, "registered": False, "started_at": time.time()})
    failures = 0
    warmup_until = time.monotonic() + 90
    registered_once = False
    while not stopped.is_set() and process.poll() is None:
        try:
            register(origin, secret)
            save_private(status_path, {"origin": origin, "registered": True, "registered_at": time.time()})
            print("Website discovery registered the current device tunnel", flush=True)
            failures = 0
            registered_once = True
            delay = 3600  # Writes happen only when the hostname changes.
        except Exception:
            # New Quick Tunnel DNS/edge routing may not be ready at first. Do
            # not impose a 30-second penalty for each early registration miss.
            if not registered_once and time.monotonic() < warmup_until:
                delay = (2, 3, 5)[min(failures, 2)]
            else:
                delay = (2, 4, 8, 15, 30)[min(failures, 4)]
            failures += 1
            save_private(status_path, {"origin": origin, "registered": False, "retry_at": time.time() + delay})
            print(f"Website discovery unavailable; retrying in {delay} seconds", flush=True)
        stopped.wait(delay)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--cloudflared", required=True)
    args = parser.parse_args()
    load_credentials(args.env_file)
    status_path = Path(args.env_file).parent / "connect-tunnel.json"
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
    worker = None
    try:
        for line in process.stdout:
            match = ORIGIN.search(line)
            if match and worker is None:
                worker = threading.Thread(target=publish, args=(match.group(), secret, status_path, process, stopped), daemon=True)
                worker.start()
        result = process.wait()
        if result and not stopped.is_set():
            raise SystemExit(result)
    finally:
        stop()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
