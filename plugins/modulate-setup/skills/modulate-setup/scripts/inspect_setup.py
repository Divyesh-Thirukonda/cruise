#!/usr/bin/env python3
"""Read-only setup probe. Does not read private file contents or call a provider."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import socket
import sys


def reachable(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def inspect(repo):
    repo = repo.expanduser().resolve()
    required = ("modulate/studio.py", "modulate/device.py", "requirements-product-host.txt", "context/connect.md")
    return {
        "os": platform.system(),
        "mac_native_bridge_supported": platform.system() == "Darwin",
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 11),
        "commands_available": {name: shutil.which(name) is not None for name in ("git", "openssl", "cloudflared")},
        "checkout_files_present": {name: (repo / name).is_file() for name in required},
        "venv_present": (repo / ".venv" / "bin" / "python").is_file(),
        "private_files_present": {name: (repo / "context" / "private" / name).is_file() for name in ("meta.env", "connect.env")},
        "default_state_directory_present": (repo / "context" / "private" / "product").is_dir(),
        "loopback_ports_listening": {str(port): reachable(port) for port in (8787, 8788, 8789)},
        "notes": [
            "Ports do not identify a process or prove that the Pi is connected.",
            "An existing service may use another state directory or virtual environment.",
            "No credentials, private file contents, model requests, or settings were read or changed.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    print(json.dumps(inspect(parser.parse_args().repo), indent=2))
