"""Debounced, restart-safe adaptation of local apps to observed controls.

This schedules one checked model edit per app/control combination, never input
events or privileged host actions. A failed/cancelled attempt is not retried.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile


class ControlAdaptation:
    def __init__(self, directory):
        self.path = Path(directory) / "control-adaptations.json"
        self.attempts = []
        self.observation = None
        self.since = None
        self.error = None
        try:
            if self.path.exists():
                if self.path.stat().st_size > 8192:
                    raise ValueError()
                self.attempts = json.loads(self.path.read_text())
                if (type(self.attempts) is not list or len(self.attempts) > 64
                        or any(type(x) is not str or len(x) != 64
                               or any(c not in "0123456789abcdef" for c in x) for x in self.attempts)):
                    raise ValueError()
        except (OSError, ValueError):
            self.error = "Automatic control adaptation history is unavailable"

    def consider(self, package, revision, available, *, suspended, eligible, now):
        if (self.error or not eligible or not suspended or not package
                or package.get("kind") != "game" or package.get("camera")
                or not set(package.get("controls", [])) - set(available)):
            self.observation = self.since = None
            return False
        key = hashlib.sha256(json.dumps([revision, sorted(available)]).encode()).hexdigest()
        if key in self.attempts:
            return False
        if key != self.observation:
            self.observation, self.since = key, now
            return False
        if now - self.since < 5:
            return False
        # Consume before dispatch so restart, cancellation and uncertain model
        # outcomes cannot repeat the same automatic paid request.
        attempts = (self.attempts + [key])[-64:]
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as stream:
                temporary = stream.name
                os.chmod(temporary, 0o600)
                json.dump(attempts, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            self.attempts = attempts
        except OSError:
            self.error = "Automatic control adaptation could not be recorded"
            return False
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
        return True


ADAPT_REQUEST = """The connected controls changed. Adapt the current local app to
the actual controls now available. Read its package and inspect capabilities.
Preserve its identity, artwork and gameplay; change only controls and their hints
as needed. Choose a usable mapping from each detected input's identity, signals,
units and the app's interaction. There is no fixed preference order among motion
sensors, joysticks, encoders or buttons. Missing peripherals and an unpaired Mac are not a
reason to block a local game. Declare only controls this version really needs.
If no physical inputs are available, make a clearly labeled automatic demo that
does not claim interactive play. Do not fix wiring, reconnect devices, start a
camera, or operate a computer. Check and activate the adapted package through the
normal tools. If a check fails, repair within this request; never claim success
without activation. Briefly explain the new controls after activation."""
