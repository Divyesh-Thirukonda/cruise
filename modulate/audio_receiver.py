"""Transient paired-Mac PCM playback on the Pi's already-selected Pulse sink.

The trusted fetcher must return within three seconds and honor cancellation.
It supplies contiguous chunks, or reset=True when it skipped to the live edge.
There are no audio files, fallback outputs, or microphone changes here. Written
frames establish software delivery to paplay, not physical audibility.
"""

import base64
import binascii
import os
import re
import shutil
import subprocess
import threading
import time


FORMAT = "pcm_s16le_48000_stereo"
MAX_CHUNK_BYTES = 38_400
BYTES_PER_SECOND = 48_000 * 2 * 2
LINK_STALE_SECONDS = 3.0
_SESSION = re.compile(r"[0-9a-f]{32}\Z")
_SINK = re.compile(r"[A-Za-z0-9_.,:=+/-]{1,240}\Z")
_ERRORS = {
    "packet": "Computer audio packet was rejected",
    "transport": "Computer audio connection was interrupted",
    "stale": "Computer audio connection is stale",
    "unavailable": "The selected Pulse speaker is unavailable",
    "playback": "The selected speaker rejected computer audio",
    "overrun": "Computer audio fell behind; resuming at the live edge",
}


class AudioReceiverError(ValueError):
    def __init__(self, category):
        self.category = category if category in _ERRORS else "playback"
        super().__init__(_ERRORS[self.category])


def _packet(value, session):
    required = {"session", "sequence", "pcm"}
    if (type(value) is not dict or not required <= set(value)
            or set(value) - required - {"reset", "format"}
            or value["session"] != session
            or type(value["sequence"]) is not int or not 0 <= value["sequence"] < 2 ** 63
            or type(value.get("reset", False)) is not bool
            or value.get("format", FORMAT) != FORMAT
            or type(value["pcm"]) is not str
            or not 4 <= len(value["pcm"]) <= 4 * ((MAX_CHUNK_BYTES + 2) // 3)):
        raise AudioReceiverError("packet")
    try:
        pcm = base64.b64decode(value["pcm"], validate=True)
    except (ValueError, binascii.Error):
        raise AudioReceiverError("packet") from None
    if not 4 <= len(pcm) <= MAX_CHUNK_BYTES or len(pcm) % 4:
        raise AudioReceiverError("packet")
    return value["sequence"], pcm, value.get("reset", False)


class _PulsePlayer:
    """One continuous raw pipe; no shell or default-device fallback.

    paplay options: https://manpages.debian.org/bookworm/pulseaudio-utils/paplay.1.en.html
    """

    def __init__(self, sink):
        executable = shutil.which("paplay")
        if not executable or type(sink) is not str or not _SINK.fullmatch(sink):
            raise AudioReceiverError("unavailable")
        self.lock = threading.Lock()
        try:
            self.process = subprocess.Popen(
                [executable, "--playback", "--device=" + sink, "--raw", "--format=s16le",
                 "--rate=48000", "--channels=2", "--latency-msec=40",
                 "--client-name=Modulate", "--stream-name=Computer audio"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True, bufsize=0)
        except OSError:
            raise AudioReceiverError("unavailable") from None
        try:
            os.set_blocking(self.process.stdin.fileno(), False)
        except BaseException:
            self.close()
            raise

    def write(self, pcm, cancel):
        with self.lock:
            process = self.process
        if process is None or cancel.is_set():
            return False
        position, deadline = 0, time.monotonic() + 0.35
        try:
            while position < len(pcm):
                if cancel.is_set():
                    return False
                if process.poll() is not None:
                    raise AudioReceiverError("playback")
                if time.monotonic() >= deadline:
                    raise AudioReceiverError("overrun")
                try:
                    written = os.write(process.stdin.fileno(), pcm[position:position + 8192])
                    if written <= 0:
                        raise AudioReceiverError("playback")
                    position += written
                except BlockingIOError:
                    cancel.wait(0.005)
            return not cancel.is_set()
        except AudioReceiverError:
            raise
        except (OSError, ValueError):
            if cancel.is_set():
                return False
            raise AudioReceiverError("playback") from None

    def close(self):
        with self.lock:
            process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()  # Discard buffered PCM; never drain on stop.
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.2)
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass


class AudioReceiver:
    """One fetch/play worker, with no queued audio or persisted state.

    fetch(session, after_sequence, cancel_event) -> packet | None. after=None
    requests the live edge, including after a pause, reset or local overrun.
    sink is the already-selected Pulse sink name, never an ALSA device/default.
    on_status receives content-free snapshots on the worker and must be quick.
    Setters cancel in-flight work and promptly close the player; call them outside
    the controller's frame lock. Physical stop latching belongs to the owner.
    """

    def __init__(self, fetch, on_status=None, sink=None, *, player_factory=None, clock=time.monotonic):
        if not callable(fetch) or (sink is not None and (type(sink) is not str or not _SINK.fullmatch(sink))):
            raise ValueError("Configure a trusted audio fetcher and selected Pulse sink")
        self.fetch, self.on_status, self.sink = fetch, on_status, sink
        self._factory, self._clock = player_factory or _PulsePlayer, clock
        self._lock = threading.RLock()
        self._wake, self._stop = threading.Event(), threading.Event()
        self._cancel = threading.Event()
        self._thread = self._player = None
        self._enabled = self._ducked = False
        self._session = self._after = None
        self._last_sequence = -1
        self._epoch = 0
        self._until = 0.0
        self._state, self._error = "stopped", None
        self._chunks = self._received = self._written = self._dropped = 0

    def snapshot(self):
        with self._lock:
            playing = (self._state == "playing" and self._enabled and not self._ducked
                       and self._player is not None and self._clock() < self._until)
            return {"available": self.sink is not None, "enabled": self._enabled,
                    "ducked": self._ducked, "playing": playing,
                    "state": "waiting" if self._state == "playing" and not playing else self._state,
                    "session": self._session, "output": self.sink, "format": FORMAT,
                    "sequence": self._last_sequence if self._last_sequence >= 0 else None,
                    "chunks_received": self._chunks, "frames_received": self._received,
                    "frames_written": self._written, "chunks_dropped": self._dropped,
                    "error": self._error}

    def _emit(self):
        if self.on_status:
            try:
                self.on_status(self.snapshot())
            except Exception:
                pass  # UI callbacks cannot break transport or player cleanup.

    def _invalidate_locked(self):
        self._epoch += 1
        self._cancel.set()
        self._cancel = threading.Event()
        player, self._player = self._player, None
        self._after, self._until = None, 0.0
        self._wake.set()
        return player

    def set_enabled(self, enabled, session=None):
        if type(enabled) is not bool or (enabled and (type(session) is not str or not _SESSION.fullmatch(session))):
            raise ValueError("Enabled audio requires its exact stream session")
        with self._lock:
            if self._enabled == enabled and (not enabled or self._session == session):
                return
            player = self._invalidate_locked()
            if enabled and session != self._session:
                self._last_sequence = -1
            self._enabled = enabled
            self._session = session if enabled else self._session
            self._state = "connecting" if enabled else "off"
            self._error = None
        if player:
            player.close()

    def set_sink(self, sink):
        """Accept late discovery once; never redirect a known speaker output."""
        if type(sink) is not str or not _SINK.fullmatch(sink):
            raise ValueError("Configure a valid selected Pulse sink")
        with self._lock:
            if self.sink is not None:
                if self.sink != sink:
                    raise ValueError("Computer audio cannot switch its selected speaker")
                return False
            self.sink = sink
            self._error = None
            if self._enabled:
                self._state = "ducked" if self._ducked else "connecting"
            self._wake.set()
            return True

    def set_ducked(self, ducked):
        if type(ducked) is not bool:
            raise ValueError("Audio ducking must be boolean")
        with self._lock:
            if self._ducked == ducked:
                return
            player = self._invalidate_locked()
            self._ducked = ducked
            self._state = ("ducked" if ducked else "connecting") if self._enabled else "off"
        if player:
            player.close()

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._state = "connecting" if self._enabled else "off"
            self._thread = threading.Thread(target=self._run, name="modulate-computer-audio", daemon=True)
            self._thread.start()
        return True

    def stop(self):
        with self._lock:
            self._stop.set()
            player = self._invalidate_locked()
            self._cancel.set()
            self._enabled, self._state = False, "stopped"
            thread = self._thread
        if player:
            player.close()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=0.25)  # Fetcher bounds its own remaining network work.

    def _wait(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def _run(self):
        self._emit()
        try:
            while not self._stop.is_set():
                with self._lock:
                    enabled, ducked, sink = self._enabled, self._ducked, self.sink
                    epoch, session, after, cancel = self._epoch, self._session, self._after, self._cancel
                    lead = max(0, self._until - self._clock())
                if not enabled or sink is None:
                    with self._lock:
                        if enabled and sink is None:
                            self._state, self._error = "unavailable", _ERRORS["unavailable"]
                    self._emit()
                    self._wait(0.1)
                    continue
                if not ducked and lead > 0.2:
                    self._wait(min(lead - 0.2, 0.05))
                    continue
                try:
                    started = self._clock()
                    packet = self.fetch(session, after, cancel)
                    with self._lock:
                        if epoch != self._epoch or cancel.is_set() or self._stop.is_set():
                            continue
                    if self._clock() - started > LINK_STALE_SECONDS:
                        raise AudioReceiverError("stale")
                    if packet is None:
                        self._emit()
                        self._wait(0.01)
                        continue
                    sequence, pcm, reset = _packet(packet, session)
                    with self._lock:
                        if epoch != self._epoch:
                            continue
                        if sequence <= self._last_sequence:
                            self._dropped += 1
                            replay = True
                        else:
                            replay = False
                            self._last_sequence = self._after = sequence
                            self._chunks += 1
                            self._received += len(pcm) // 4
                        if self._ducked:
                            self._state, self._error = "ducked", None
                            if not replay:
                                self._dropped += 1
                            replay = True
                        player = self._player
                        if reset and player and not replay:
                            self._player, self._until = None, 0.0
                    if reset and player and not replay:
                        player.close()
                        player = None
                    if replay:
                        self._emit()
                        self._wait(0.01)
                        continue
                    if player is None:
                        player = self._factory(sink)
                        with self._lock:
                            accepted = epoch == self._epoch and not cancel.is_set() and not self._ducked
                            if accepted:
                                self._player = player
                        if not accepted:
                            player.close()
                            continue
                    if not player.write(pcm, cancel):
                        continue
                    with self._lock:
                        if epoch == self._epoch:
                            self._written += len(pcm) // 4
                            self._until = max(self._until, self._clock()) + len(pcm) / BYTES_PER_SECOND
                            self._state, self._error = "playing", None
                    self._emit()
                except Exception as error:
                    with self._lock:
                        if epoch != self._epoch or self._stop.is_set():
                            continue
                        player, self._player = self._player, None
                        self._after, self._until = None, 0.0
                        category = error.category if isinstance(error, AudioReceiverError) else "transport"
                        self._state, self._error = "error", _ERRORS[category]
                    if player:
                        player.close()
                    self._emit()
                    self._wait(0.5)
        finally:
            with self._lock:
                player, self._player = self._player, None
                self._until = 0.0
            if player:
                player.close()
            self._emit()
