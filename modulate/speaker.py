"""Bounded local speech output; content exists only in memory and process pipes.

eSpeak NG synthesizes WAV on stdout; paplay/aplay receives that pipe. A successful
exit establishes software playback delivery, not that a physical speaker was
audible. This module never changes volume or chooses an ALSA fallback silently.

CLI references:
https://github.com/espeak-ng/espeak-ng/blob/master/docs/guide.md
https://manpages.debian.org/bookworm/pulseaudio-utils/paplay.1.en.html
"""

import os
import re
import shutil
import signal
import subprocess
import threading
import time


MAX_TEXT_CHARACTERS = 1200
MAX_TEXT_BYTES = 4800
MAX_PLAYBACK_SECONDS = 90
RECOVERY_SECONDS = 5
_OUTPUT = re.compile(r"[A-Za-z0-9_.,:=+/-]{1,240}\Z")
_ERRORS = {
    "synthesis_failed": "Local speech synthesis failed",
    "playback_failed": "Configured audio output rejected playback",
    "timeout": "Speech playback exceeded its time limit",
    "unavailable": "Local speech output is unavailable",
}


class SpeakerError(Exception):
    def __init__(self, category="unavailable"):
        self.category = category if category in _ERRORS else "unavailable"
        super().__init__(_ERRORS[self.category])


def _validate_text(text):
    if (type(text) is not str or not text.strip() or len(text) > MAX_TEXT_CHARACTERS
            or len(text.encode("utf-8")) > MAX_TEXT_BYTES
            or any(ord(char) < 32 and char not in "\n\t\r" for char in text)):
        raise ValueError("Speech must contain 1 to 1200 characters and no unsupported control characters")
    return text.strip()


class LocalSpeechBackend:
    """Pin a detected Pulse sink or an explicitly configured ALSA PCM.

    The worker may rediscover a missing audio session. Once an output is known,
    recovery requires that same output; errors never redirect speech elsewhere.
    """

    def __init__(self, *, pulse_sink=None, alsa_device=None):
        if pulse_sink is None and alsa_device is None:
            pulse_sink = os.environ.get("MODULATE_SPEAKER_SINK") or None
        if pulse_sink is not None and alsa_device is not None:
            raise ValueError("Configure one speech output")
        for value in (pulse_sink, alsa_device):
            if value is not None and (type(value) is not str or not _OUTPUT.fullmatch(value)):
                raise ValueError("Invalid speech output identifier")
        self.mode = "alsa" if alsa_device else "pulse"
        self.output = alsa_device or pulse_sink
        self.selection = "configured" if self.output else None
        self.refresh()

    def refresh(self):
        """Bounded discovery; call on the speech worker, never each frame."""
        self.synth = shutil.which("espeak-ng")
        self.player = shutil.which("aplay" if self.mode == "alsa" else "paplay")
        self.error = None
        if not self.synth:
            self.error = "Local espeak-ng synthesis is not installed"
        elif not self.player:
            self.error = "The selected local audio player is not installed"
        elif self.mode == "pulse":
            pactl = shutil.which("pactl")
            try:
                if not pactl:
                    raise SpeakerError()
                result = subprocess.run([pactl, "list", "short", "sinks"], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        timeout=2, check=True)
                if len(result.stdout) > 32_768:
                    raise SpeakerError()
                sinks = [line.split()[1] for line in result.stdout.decode("utf-8").splitlines()
                         if len(line.split()) >= 2]
                if any(not _OUTPUT.fullmatch(sink) for sink in sinks):
                    raise SpeakerError()
                if self.output is not None:
                    if self.output not in sinks:
                        raise SpeakerError()
                elif len(sinks) == 1:
                    self.output, self.selection = sinks[0], "detected_single_sink"
                else:
                    raise SpeakerError()
            except (OSError, ValueError, subprocess.SubprocessError, SpeakerError):
                self.error = "Configured output is absent or multiple outputs need an explicit selection"
        return self.info()

    def info(self):
        return {"available": self.error is None and self.output is not None,
                "backend": "espeak-ng/" + ("aplay" if self.mode == "alsa" else "paplay"),
                "output": self.output, "output_selection": self.selection, "error": self.error}

    @staticmethod
    def _close(processes):
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for process in processes:
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=0.5)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def play(self, text, cancel):
        """True means both subprocesses completed; False means cancelled."""
        payload = _validate_text(text).encode("utf-8")
        if not self.info()["available"]:
            raise SpeakerError()
        if cancel.is_set():
            return False
        processes = []
        try:
            synth = subprocess.Popen([self.synth, "--stdin", "--stdout", "-v", "en-us", "-s", "170"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     close_fds=True, start_new_session=True)
            processes.append(synth)
            arguments = ([self.player, "-q", "-D", self.output] if self.mode == "alsa" else
                         [self.player, "--playback", "--device=" + self.output,
                          "--client-name=Modulate", "--stream-name=Speech"])
            player = subprocess.Popen(arguments, stdin=synth.stdout, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            processes.append(player)
            synth.stdout.close()  # Only the player owns the read end of the WAV pipe.
            os.set_blocking(synth.stdin.fileno(), False)
            position = 0
            deadline = time.monotonic() + MAX_PLAYBACK_SECONDS
            while True:
                if cancel.is_set():
                    return False
                if time.monotonic() >= deadline:
                    raise SpeakerError("timeout")
                synthesis, playback = synth.poll(), player.poll()
                if synthesis not in (None, 0):
                    raise SpeakerError("synthesis_failed")
                if playback not in (None, 0):
                    raise SpeakerError("playback_failed")
                if synthesis == 0 and playback == 0:
                    if position != len(payload):
                        raise SpeakerError("synthesis_failed")
                    return True
                if position < len(payload):
                    try:
                        position += os.write(synth.stdin.fileno(), payload[position:position + 1024])
                    except BlockingIOError:
                        pass
                    if position == len(payload):
                        synth.stdin.close()
                cancel.wait(0.025)
        except SpeakerError as error:
            if error.category == "playback_failed":
                self.error = _ERRORS["playback_failed"]
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            self.error = _ERRORS["playback_failed"]
            raise SpeakerError("playback_failed") from None
        finally:
            self._close(processes)


class Speaker:
    """One active utterance plus one latest pending utterance, with no history.

    Backend contract: info()->generic metadata; play(text,cancel_event)->bool.
    Backends must honor cancellation and bound their work. Status callbacks are
    content-free and must return promptly. start() precedes speak().
    """

    def __init__(self, on_status=None, backend=None):
        self.backend = backend if backend is not None else LocalSpeechBackend()
        self.on_status = on_status
        self._changed = threading.Condition(threading.RLock())
        self._thread = None
        self._stopped = True
        self._pending = None
        self._active_cancel = None
        self._sequence = 0
        self._info = dict(self.backend.info())
        self._state = "stopped" if self._info.get("available") else "unavailable"
        self._error = self._info.get("error")
        self._last_delivery = None

    def snapshot(self):
        with self._changed:
            return {**self._info, "state": self._state, "error": self._error,
                    "request_id": self._sequence or None, "last_delivery": self._last_delivery}

    def _notify(self):
        if self.on_status:
            try:
                self.on_status(self.snapshot())
            except Exception:
                pass

    def start(self):
        with self._changed:
            if self._thread and self._thread.is_alive():
                return not self._stopped
            self._stopped = False
            available = bool(self._info.get("available"))
            self._state = "idle" if available else "unavailable"
            self._error = self._info.get("error")
            self._thread = threading.Thread(target=self._run, name="modulate-speaker", daemon=True)
            self._thread.start()
        self._notify()
        return available

    def speak(self, text):
        text = _validate_text(text)
        with self._changed:
            if self._stopped or not self._info.get("available"):
                return False
            self._sequence += 1
            self._pending = (self._sequence, text)
            if self._active_cancel:
                self._active_cancel.set()
            self._state, self._error, self._last_delivery = "queued", None, None
            self._changed.notify_all()
        self._notify()
        return True

    def cancel(self):
        with self._changed:
            self._sequence += 1
            self._pending = None
            if self._active_cancel:
                self._active_cancel.set()
            if not self._stopped:
                self._state = ("stopping" if self._active_cancel else
                               "idle" if self._info.get("available") else "unavailable")
            self._last_delivery = "cancelled"
            self._changed.notify_all()
        self._notify()

    def stop(self):
        with self._changed:
            self._stopped = True
            self._pending = None
            self._sequence += 1
            if self._active_cancel:
                self._active_cancel.set()
            self._state = "stopping" if self._active_cancel else "stopped"
            self._changed.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._notify()
        return thread is None or not thread.is_alive()

    def _run(self):
        retry_at = 0
        while True:
            with self._changed:
                if self._stopped:
                    self._state = "stopped"
                    return
                refresh = not self._info.get("available") and time.monotonic() >= retry_at
                if self._pending is None and not refresh:
                    self._changed.wait(timeout=RECOVERY_SECONDS)
                    continue
            if refresh:
                try:
                    refresh_backend = getattr(self.backend, "refresh", self.backend.info)
                    info = dict(refresh_backend())
                except Exception:
                    info = {**self._info, "available": False, "error": _ERRORS["unavailable"]}
                with self._changed:
                    self._info = info
                    self._error = info.get("error")
                    self._state = "stopped" if self._stopped else "idle" if info.get("available") else "unavailable"
                retry_at = time.monotonic() + RECOVERY_SECONDS
                self._notify()
                continue
            with self._changed:
                if self._stopped or self._pending is None:
                    continue
                identifier, text = self._pending
                self._pending = None
                cancel = self._active_cancel = threading.Event()
                self._state = "speaking"
            self._notify()
            error = None
            delivered = False
            try:
                delivered = self.backend.play(text, cancel)
            except Exception as failure:
                error = str(failure) if isinstance(failure, SpeakerError) else _ERRORS["playback_failed"]
            finally:
                text = None
            with self._changed:
                self._active_cancel = None
                self._info = dict(self.backend.info())
                if self._stopped:
                    self._state = "stopped"
                elif identifier == self._sequence:
                    self._error = error
                    self._state = "error" if error else "idle"
                    self._last_delivery = ("failed" if error else
                                           "delivered" if delivered and not cancel.is_set() else "cancelled")
                elif self._pending is None:
                    self._state = "idle"
            self._notify()
