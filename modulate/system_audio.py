"""Local Mac system-audio mirror, with no microphone, model or file output.

ScreenCaptureKit supplies PCM through one native audio-only callback. The trusted
service converts it to 48 kHz stereo S16LE and retains only half a second. This
module does not mute the Mac or change its output device: capture is a mirror.

API sources: Apple's ScreenCaptureKit capturesAudio, sampleRate, channelCount,
excludesCurrentProcessAudio and Capturing screen content in macOS documentation;
PyObjC ScreenCaptureKit/CoreMedia bindings. No third-party capture code is copied.
"""
from array import array
from collections import deque
import math
import re
import sys
import threading
import time
from types import SimpleNamespace
import uuid


FORMAT = "pcm_s16le_48000_stereo"
RATE, CHANNELS, SAMPLE_BYTES = 48_000, 2, 2
BLOCK_BYTES = 19_200  # 100 ms
MAX_CHUNK_BYTES = 38_400  # 200 ms
MAX_BUFFER_BYTES = 96_000  # 500 ms
MAX_AGE = 1.0
_ERRORS = {
    "unsupported": "System audio capture requires macOS 13 or later",
    "unavailable": "Install the optional Mac system-audio dependencies",
    "permission_denied": "Allow Screen and System Audio Recording in macOS System Settings",
    "no_display": "No Mac display is available for system audio capture",
    "start_timeout": "Mac system audio capture did not start in time",
    "capture_failed": "Mac system audio capture stopped; start it again",
    "invalid_audio": "Mac system audio returned an unsupported audio format",
}


class SystemAudioError(Exception):
    def __init__(self, category="capture_failed"):
        self.category = category if category in _ERRORS else "capture_failed"
        super().__init__(_ERRORS[self.category])


def _pcm(planes, frames, *, rate, channels, bits, flags, format_id):
    """Convert a bounded native linear PCM buffer, preserving stereo order.

    CoreAudio flag bits: float=1, big-endian=2, signed-int=4, packed=8,
    noninterleaved=32. Only the exact formats we can verify are accepted.
    """
    if (rate != RATE or channels != CHANNELS or format_id != 0x6C70636D
            or type(frames) is not int or not 1 <= frames <= RATE // 5
            or flags & ~(1 | 2 | 4 | 8 | 32)
            or not flags & 8):
        raise SystemAudioError("invalid_audio")
    floating = bool(flags & 1)
    planar = bool(flags & 32)
    if ((floating and (bits != 32 or flags & 4))
            or (not floating and (bits != 16 or not flags & 4))):
        raise SystemAudioError("invalid_audio")
    if len(planes) != (CHANNELS if planar else 1):
        raise SystemAudioError("invalid_audio")
    count = frames if planar else frames * CHANNELS
    values = []
    for data in planes:
        if type(data) is not bytes or len(data) != count * (bits // 8):
            raise SystemAudioError("invalid_audio")
        samples = array("f" if floating else "h")
        samples.frombytes(data)
        if bool(flags & 2) != (sys.byteorder == "big"):
            samples.byteswap()
        values.append(samples)
    output = array("h")
    for frame in range(frames):
        for channel in range(CHANNELS):
            value = values[channel][frame] if planar else values[0][frame * CHANNELS + channel]
            if floating:
                if not math.isfinite(value):
                    raise SystemAudioError("invalid_audio")
                value = max(-32768, min(32767, round(value * 32768)))
            output.append(value)
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


def _sample_pcm(sample, modules):
    media, audio = modules.media, modules.audio
    if not media.CMSampleBufferIsValid(sample) or not media.CMSampleBufferDataIsReady(sample):
        return None
    frames = int(media.CMSampleBufferGetNumSamples(sample))
    if frames == 0:
        return None
    description = media.CMAudioFormatDescriptionGetStreamBasicDescription(
        media.CMSampleBufferGetFormatDescription(sample))
    if description is None or not 1 <= frames <= RATE // 5:
        raise SystemAudioError("invalid_audio")
    # AudioBufferList is a PyObjC-owned fixed two-buffer allocation. On 64-bit
    # macOS the aligned header is eight bytes and each AudioBuffer is 16 bytes.
    buffers = audio.AudioBufferList(CHANNELS)
    status, required, retained = media.CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
        sample, None, buffers, 8 + 16 * CHANNELS, None, None, 0, None)
    if status != 0 or required > 8 + 16 * CHANNELS or len(buffers) not in (1, CHANNELS):
        raise SystemAudioError("invalid_audio")
    expected_channels = 1 if description.mFormatFlags & 32 else CHANNELS
    if any(b.mNumberChannels != expected_channels or not 0 < b.mDataByteSize <= MAX_CHUNK_BYTES * 2
           for b in buffers):
        raise SystemAudioError("invalid_audio")
    # Copy while `retained` still owns the native block; never retain pointers.
    planes = [bytes(b.mData) for b in buffers]
    return _pcm(planes, frames, rate=description.mSampleRate,
                channels=description.mChannelsPerFrame, bits=description.mBitsPerChannel,
                flags=description.mFormatFlags, format_id=description.mFormatID)


_delegate_type = None
_delegate_lock = threading.Lock()


def _delegate(modules):
    global _delegate_type
    with _delegate_lock:
        if _delegate_type is None:
            class ModulateSystemAudioDelegate(modules.foundation.NSObject,
                    protocols=[modules.objc.protocolNamed("SCStreamOutput"),
                               modules.objc.protocolNamed("SCStreamDelegate")]):
                def stream_didOutputSampleBuffer_ofType_(self, stream, sample, output_type):
                    receiver = getattr(self, "receiver", None)
                    if receiver is not None:
                        receiver(sample, output_type)

                def stream_didStopWithError_(self, stream, error):
                    stopped = getattr(self, "stopped", None)
                    if stopped is not None:
                        stopped()
            _delegate_type = ModulateSystemAudioDelegate
        return _delegate_type.alloc().init()


class ScreenCaptureBackend:
    def __init__(self):
        self.permission = "unknown" if sys.platform == "darwin" else "unsupported"
        self.error = None

    def info(self):
        return {"supported": sys.platform == "darwin", "permission": self.permission,
                "backend": "screencapturekit", "source": "Mac system audio",
                "excludes_current_process": True, "error": self.error}

    @staticmethod
    def _load():
        if sys.platform != "darwin":
            raise SystemAudioError("unsupported")
        try:
            import CoreAudio
            import CoreMedia
            import Foundation
            import Quartz
            import ScreenCaptureKit
            import dispatch
            import objc
            if not hasattr(ScreenCaptureKit.SCStreamConfiguration, "setCapturesAudio_"):
                raise SystemAudioError("unsupported")
            return SimpleNamespace(audio=CoreAudio, media=CoreMedia, foundation=Foundation,
                                   quartz=Quartz, sc=ScreenCaptureKit, dispatch=dispatch, objc=objc)
        except ImportError:
            raise SystemAudioError("unavailable") from None

    def refresh_access(self):
        """Read the existing macOS permission without prompting or starting."""
        try:
            self.permission = "authorized" if self._load().quartz.CGPreflightScreenCaptureAccess() else "denied"
            self.error = None
        except Exception as failure:
            self.permission = "unavailable" if sys.platform == "darwin" else "unsupported"
            self.error = str(failure) if isinstance(failure, SystemAudioError) else _ERRORS["unavailable"]
        return self.info()

    def run(self, on_pcm, cancel):
        if cancel.is_set():
            return
        modules = self._load()
        sc = modules.sc
        # No implicit permission prompt. A denied grant is surfaced to Studio.
        self.permission = "authorized" if modules.quartz.CGPreflightScreenCaptureAccess() else "denied"
        if self.permission != "authorized":
            raise SystemAudioError("permission_denied")
        result, answered = {}, threading.Event()

        def content_ready(content, error):
            result.update(content=content, failed=error is not None)
            answered.set()

        sc.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
            True, True, content_ready)
        deadline = time.monotonic() + 10
        while not answered.wait(.05):
            if cancel.is_set():
                return
            if time.monotonic() >= deadline:
                raise SystemAudioError("start_timeout")
        if cancel.is_set():
            return
        if result.get("failed") or result.get("content") is None:
            raise SystemAudioError("capture_failed")
        displays = result["content"].displays()
        main_id = modules.quartz.CGMainDisplayID()
        display = next((item for item in displays if item.displayID() == main_id), None)
        if display is None:
            raise SystemAudioError("no_display")
        content_filter = sc.SCContentFilter.alloc().initWithDisplay_excludingWindows_(display, [])
        config = sc.SCStreamConfiguration.alloc().init()
        config.setWidth_(2)
        config.setHeight_(2)
        config.setMinimumFrameInterval_(modules.media.CMTimeMake(1, 1))
        config.setQueueDepth_(3)
        config.setShowsCursor_(False)
        config.setCapturesAudio_(True)
        config.setSampleRate_(RATE)
        config.setChannelCount_(CHANNELS)
        config.setExcludesCurrentProcessAudio_(True)
        if hasattr(config, "setCaptureMicrophone_"):
            config.setCaptureMicrophone_(False)
        delegate = _delegate(modules)
        queue = modules.dispatch.dispatch_queue_create(b"modulate.system-audio", None)
        failure = []

        def receive(sample, output_type):
            if cancel.is_set() or failure or output_type != sc.SCStreamOutputTypeAudio:
                return
            try:
                pcm = _sample_pcm(sample, modules)
                if pcm:
                    on_pcm(pcm)
            except Exception as error:
                failure.append(error.category if isinstance(error, SystemAudioError) else "invalid_audio")

        delegate.receiver = receive
        delegate.stopped = lambda: failure.append("capture_failed") if not failure else None
        stream = sc.SCStream.alloc().initWithFilter_configuration_delegate_(content_filter, config, delegate)
        try:
            success, error = stream.addStreamOutput_type_sampleHandlerQueue_error_(
                delegate, sc.SCStreamOutputTypeAudio, queue, None)
            if not success or error is not None:
                raise SystemAudioError("capture_failed")
            started = threading.Event()
            start_result = []

            def start_done(error):
                start_result.append(error is not None)
                started.set()

            stream.startCaptureWithCompletionHandler_(start_done)
            deadline = time.monotonic() + 10
            while not started.wait(.05):
                if cancel.is_set():
                    return
                if time.monotonic() >= deadline:
                    raise SystemAudioError("start_timeout")
            if start_result[0]:
                raise SystemAudioError("capture_failed")
            while not cancel.wait(.05):
                if failure:
                    raise SystemAudioError(failure[0])
        finally:
            delegate.receiver = delegate.stopped = None
            stopped = threading.Event()
            stream.stopCaptureWithCompletionHandler_(lambda error: stopped.set())
            stopped.wait(1.5)
            stream.removeStreamOutput_type_error_(delegate, sc.SCStreamOutputTypeAudio, None)


class SystemAudio:
    """Asynchronous capture owner. Backend: info(), refresh_access(), run(callback,cancel).

    chunk returns contiguous blocks up to200ms. A new or lagging client gets the
    newest available200ms and reset=True. Repeated calls at the same cursor are
    intentionally idempotent; callers advance only after consuming the response.
    """
    def __init__(self, backend=None, *, clock=time.monotonic):
        self.backend = backend if backend is not None else ScreenCaptureBackend()
        self.clock = clock
        self._condition = threading.Condition(threading.RLock())
        self._cancel = threading.Event()
        self._thread = None
        self._generation = self._sequence = 0
        self._session = None
        self._blocks = deque()
        self._pending = bytearray()
        self._pending_at = None
        self._captured = None
        self._state, self._error = "stopped", None

    def refresh_access(self):
        self.backend.refresh_access()
        return self.status()

    def status(self):
        with self._condition:
            self._expire()
            info = dict(self.backend.info())
            return {**info, "state": self._state, "running": bool(self._thread and self._thread.is_alive()),
                    "error": self._error or info.get("error"), "session": self._session,
                    "sequence": self._sequence, "format": FORMAT, "mode": "mirror",
                    "sample_rate": RATE, "channels": CHANNELS,
                    "buffered_ms": len(self._blocks) * 100,
                    "audio_age_seconds": None if self._captured is None else round(max(0, self.clock() - self._captured), 3)}

    def start(self):
        with self._condition:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._generation += 1
            self._session, self._sequence = uuid.uuid4().hex, 0
            self._cancel = threading.Event()
            self._clear()
            self._state, self._error = "starting", None
            self._thread = threading.Thread(target=self._run, args=(self._generation, self._cancel),
                                            name="modulate-system-audio", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self):
        with self._condition:
            self._cancel.set()
            self._generation += 1
            self._clear()
            self._session = None
            thread = self._thread
            self._state = "stopping" if thread and thread.is_alive() else "stopped"
            self._condition.notify_all()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._condition:
            if not thread or not thread.is_alive():
                self._state = "stopped"
        return self.status()

    def _clear(self):
        self._blocks.clear()
        self._pending.clear()
        self._pending_at = None
        self._captured = None

    def _expire(self):
        now = self.clock()
        while self._blocks and now - self._blocks[0][1] >= MAX_AGE:
            self._blocks.popleft()
        if self._pending_at is not None and now - self._pending_at >= MAX_AGE:
            self._pending.clear()
            self._pending_at = None

    def chunk(self, after=0, session=None, timeout=.5):
        if ((after is not None and (type(after) is not int or not 0 <= after < 2**53))
                or (session is not None and (type(session) is not str or not re.fullmatch(r"[a-f0-9]{32}", session)))
                or type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 <= timeout <= .5):
            raise ValueError("Invalid system audio cursor or timeout")
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                self._expire()
                if self._cancel.is_set() or self._state in ("stopped", "stopping", "error"):
                    return None
                if self._blocks:
                    reset = after is None or session != self._session or after < self._blocks[0][0] - 1
                    blocks = list(self._blocks)[-2:] if reset else [b for b in self._blocks if b[0] > after][:2]
                    if blocks:
                        return {"session": self._session, "sequence": blocks[-1][0],
                                "pcm": b"".join(block[2] for block in blocks), "reset": reset}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def _receive(self, generation, cancel, pcm):
        with self._condition:
            if generation != self._generation or cancel.is_set():
                return
            if type(pcm) is not bytes or not 4 <= len(pcm) <= MAX_CHUNK_BYTES or len(pcm) % 4:
                raise SystemAudioError("invalid_audio")
            self._expire()
            self._pending.extend(pcm)
            self._pending_at = self.clock()
            while len(self._pending) >= BLOCK_BYTES:
                self._sequence += 1
                block = bytes(self._pending[:BLOCK_BYTES])
                del self._pending[:BLOCK_BYTES]
                self._captured = self.clock()
                self._blocks.append((self._sequence, self._captured, block))
                while len(self._blocks) > MAX_BUFFER_BYTES // BLOCK_BYTES:
                    self._blocks.popleft()
            self._state = "running"
            self._condition.notify_all()

    def _run(self, generation, cancel):
        error = None
        try:
            self.backend.run(lambda pcm: self._receive(generation, cancel, pcm), cancel)
            if not cancel.is_set():
                raise SystemAudioError("capture_failed")
        except Exception as failure:
            error = str(failure) if isinstance(failure, SystemAudioError) else _ERRORS["capture_failed"]
        finally:
            was_cancelled = cancel.is_set()
            cancel.set()  # A backend's late callback cannot revive failed capture.
            with self._condition:
                if generation == self._generation:
                    self._clear()
                    self._session = None
                    self._error = error
                    self._state = "error" if error and not was_cancelled else "stopped"
                elif cancel.is_set() and self._state == "stopping":
                    self._state = "stopped"
                self._condition.notify_all()
