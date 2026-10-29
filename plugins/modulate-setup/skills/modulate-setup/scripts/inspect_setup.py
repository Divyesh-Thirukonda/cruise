#!/usr/bin/env python3
"""Read-only setup probe. Optional live reads emit only an allowlisted summary."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import socket
import sys
import urllib.request


MAX_RESPONSE = 256 * 1024
HELPER_STATES = {"ready", "connecting", "awaiting_confirmation", "complete", "error"}
HELPER_ERRORS = {
    "identity_mismatch", "setup_closed", "setup_expired", "wrong_code",
    "attempts_exhausted", "request_pending", "already_enrolled", "invalid_enrollment",
    "source_mismatch", "receipt_not_found", "setup_window_unavailable", "setup_declined",
    "device_unreachable", "invalid_response", "request_mismatch", "setup_rejected",
    "setup_timeout", "setup_stopped", "save_failed", "invalid_identity", "invalid_code",
    "setup_in_progress", "setup_error", "invalid_input",
}
HELPER_ACTIONS = {
    "enter_details", "wait", "confirm_on_device", "open_studio", "check_identity",
    "new_setup_code", "check_code", "check_device", "check_network", "check_studio",
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def local_json(port, path):
    """Fixed loopback destinations only; never use proxies or follow redirects."""
    if (port, path) not in {(8787, "/api/state"), (8791, "/status")}:
        raise ValueError("Unsupported local setup endpoint")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Local status response is too large")
    result = json.loads(raw)
    if type(result) is not dict:
        raise ValueError("Local status is not an object")
    return result


def live_status(read=local_json):
    result = {}
    try:
        state = read(8787, "/api/state")
        if type(state) is not dict:
            raise ValueError("Unrecognized Studio state")
        device = state.get("device")
        remote = state.get("remote")
        if (type(device) is not dict or type(device.get("connected")) is not bool
                or type(state.get("paired")) is not bool or type(remote) is not dict
                or type(remote.get("enabled")) is not bool):
            raise ValueError("Unrecognized Studio state")
        computer = state.get("computer") if type(state.get("computer")) is dict else {}
        permissions = computer.get("permissions") if type(computer.get("permissions")) is dict else {}
        enabled = computer.get("enabled") if type(computer.get("enabled")) is bool else None
        paused = computer.get("paused") if type(computer.get("paused")) is bool else None
        native_permissions = {name: permissions.get(name) if type(permissions.get(name)) is bool else None
                              for name in ("screen_recording", "accessibility")}
        if enabled is True and (not device["connected"] or not state["paired"] or paused is True
                                or False in native_permissions.values()):
            enabled = False
        result["studio"] = {
            "status": "available",
            "device_online": device["connected"],
            "pairing_saved": state["paired"],
            "native_pairing_active": device["connected"] and state["paired"],
            "local_connection_ready": device["connected"] and state["paired"],
            "remote_gateway_configured": remote["enabled"],
            "computer_control_enabled": enabled,
            "computer_paused": paused,
            "native_permissions": native_permissions,
        }
        telemetry = device.get("telemetry") if type(device.get("telemetry")) is dict else {}
        voice = telemetry.get("voice") if type(telemetry.get("voice")) is dict else {}
        voice_state = voice.get("state")
        if type(voice_state) is str and voice_state in {"error", "wake_listening", "wake_checking", "listening", "transcribing", "idle", "muted"}:
            result["studio"]["voice_state"] = voice_state
        capabilities = device.get("capabilities") if type(device.get("capabilities")) is dict else {}
        warnings = capabilities.get("warnings")
        if type(warnings) is list:
            result["studio"]["hardware_warning_count"] = len(warnings)
    except (OSError, ValueError, TypeError, RecursionError):
        result["studio"] = {"status": "unavailable_or_unrecognized"}
    try:
        helper = read(8791, "/status")
        if type(helper) is not dict:
            raise ValueError("Unrecognized helper state")
        status = helper.get("status")
        if type(status) is not str or status not in HELPER_STATES:
            raise ValueError("Unrecognized helper state")
        result["enrollment_helper"] = {"status": status}
        for name, allowed in (("error_code", HELPER_ERRORS), ("next_action", HELPER_ACTIONS)):
            value = helper.get(name)
            if type(value) is str and value in allowed:
                result["enrollment_helper"][name] = value
    except (OSError, ValueError, TypeError, RecursionError):
        result["enrollment_helper"] = {"status": "unavailable_or_unrecognized"}
    return result


def reachable(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def inspect(repo, live=False):
    repo = repo.expanduser().resolve()
    required = ("modulate/studio.py", "modulate/device.py", "requirements-product-host.txt", "context/connect.md")
    result = {
        "os": platform.system(),
        "mac_native_bridge_supported": platform.system() == "Darwin",
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 11),
        "commands_available": {name: shutil.which(name) is not None for name in ("git", "openssl", "cloudflared")},
        "checkout_files_present": {name: (repo / name).is_file() for name in required},
        "venv_present": (repo / ".venv" / "bin" / "python").is_file(),
        "private_files_present": {name: (repo / "context" / "private" / name).is_file() for name in ("meta.env", "connect.env")},
        "default_state_directory_present": (repo / "context" / "private" / "product").is_dir(),
        "loopback_ports_listening": {str(port): reachable(port) for port in (8787, 8789, 8791)},
        "notes": [
            "Ports do not identify a process or prove that the Pi is connected.",
            "An existing service may use another state directory or virtual environment.",
            "Pi TLS port 8788 is bound to the configured network address, not necessarily loopback.",
            "No private files, model requests or settings are read or changed. Live status output omits private response content.",
        ],
    }
    if live:
        result["live"] = live_status()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--live", action="store_true", help="Read fixed local Studio/helper status; print only safe connection fields")
    args = parser.parse_args()
    print(json.dumps(inspect(args.repo, live=args.live), indent=2))
