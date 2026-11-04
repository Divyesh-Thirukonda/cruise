"""Read-only demo checks. No model calls, repairs, pairing, or settings changes.

Run on the Pi: .venv/bin/python -m modulate.demo_preflight --mac
Or inspect an authenticated tunnel state saved privately: --state-file PATH
The results describe telemetry, not physical audibility or display verification.
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path


def assess(state, *, mac=False, now=None, minutes=20):
    now = time.time() if now is None else now
    checks = []
    def add(name, status, detail):
        checks.append({"check": name, "status": status, "detail": detail})
    device = state.get("device") or {}
    telemetry = device.get("telemetry") or {}
    add("device", "pass" if device.get("connected") else "fail",
        "Pi heartbeat is current" if device.get("connected") else "Pi heartbeat is missing")
    app = telemetry.get("app") or {}
    unhealthy = telemetry.get("error") or app.get("suspended")
    add("runtime", "fail" if unhealthy else "pass",
        "Runtime is suspended or reports an error" if unhealthy else "No runtime fault reported")
    agent = state.get("agent") or {}
    add("agent", "warn" if agent.get("running") else "pass",
        "A request is still running; finish or cancel it before the demo" if agent.get("running") else "Agent is idle")
    budget = state.get("budget") or {}
    remaining = budget.get("limit_dollars", 0) - budget.get("charged_or_reserved_dollars", 0)
    add("model_budget", "fail" if budget.get("halted") or remaining <= 0 else "warn" if remaining < 1 else "pass",
        f"${max(0, remaining):.2f} remains under the existing spending ceiling, including unknown-cost holds")
    speech = state.get("speech") or {}
    speaker = telemetry.get("speaker_volume") or {}
    if speech.get("error") or speaker.get("error") or not speaker.get("available"):
        add("speech", "fail", "Speech or speaker telemetry is unavailable or reports an error")
    elif speaker.get("muted") or not isinstance(speaker.get("volume"), (int, float)) or speaker["volume"] <= 0:
        add("speech", "warn", "The Pi speaker is muted or at zero volume; spoken replies will not be audible")
    else:
        add("speech", "pass", f"{speech.get('provider', 'Unknown provider')}; speaker volume {speaker['volume']}%; audibility still needs a human check")
    voice = telemetry.get("voice") or {}
    add("wake", "pass" if state.get("wake") and voice.get("state") == "wake_listening" else "warn",
        "Wake listening is ready" if state.get("wake") and voice.get("state") == "wake_listening" else "Wake listening is off, busy, or not ready; check before a voice demo")
    setup = state.get("setup_status") or {}
    if mac:
        computer = state.get("computer") or {}
        permissions = computer.get("permissions") or {}
        ready = state.get("paired") and computer.get("enabled") and not computer.get("paused")
        add("mac", "pass" if ready else "fail", "Paired Mac helper is available" if ready else "Optional Mac controls are not currently ready")
        add("native_permissions", "pass" if all(permissions.get(k) for k in ("screen_recording", "accessibility")) else "fail",
            "Screen Recording and Accessibility are granted" if all(permissions.get(k) for k in ("screen_recording", "accessibility")) else "Check macOS Screen Recording and Accessibility permissions")
        expiry = setup.get("pairing_expires_at")
        left = (expiry - now) / 60 if isinstance(expiry, (int, float)) else 0
        add("mac_session", "fail" if left <= 0 else "warn" if left < minutes else "pass",
            f"Mac pairing has {max(0, int(left))} minutes left; fresh pairing needs physical confirmation")
    remote = state.get("remote") or {}
    if remote.get("connected"):
        expiry = remote.get("expires_at")
        left = (expiry - now) / 60 if isinstance(expiry, (int, float)) else 0
        add("browser_session", "fail" if left <= 0 else "warn" if left < minutes else "pass",
            f"This browser session has {max(0, int(left))} minutes left")
    return {"status": "fail" if any(c["status"] == "fail" for c in checks) else
            "warn" if any(c["status"] == "warn" for c in checks) else "pass", "checks": checks,
            "limits": "Read-only telemetry. Internet/provider health needs a live request; sound, buttons and motion need a physical check."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--mac", action="store_true", help="Also require the optional Mac session and native permissions")
    args = parser.parse_args()
    try:
        if args.state_file:
            state = json.loads(args.state_file.read_text())
        else:
            with urllib.request.urlopen("http://127.0.0.1:8787/api/state", timeout=5) as response:
                state = json.load(response)
        result = assess(state, mac=args.mac)
    except (OSError, ValueError, TypeError, AttributeError):
        result = {"status": "fail", "checks": [{"check": "state", "status": "fail", "detail": "Could not read valid agent state"}]}
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
