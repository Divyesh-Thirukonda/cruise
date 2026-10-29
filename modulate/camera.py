"""Local Mac camera frames for the enrolled display, never for a model.

Only explicit start() opens a camera or requests permission. AVFoundation runs
on a capture worker with a serial sample delegate and late-frame dropping.
One 240x135 JPEG is retained in memory; stop and failures discard it. No frame,
camera identifier or native diagnostic is written to a file or log.

Apple API references:
https://developer.apple.com/documentation/avfoundation/avcapturevideodataoutput
https://developer.apple.com/documentation/avfoundation/avcapturedevice/authorizationstatus(for:)
https://developer.apple.com/documentation/avfoundation/avcapturevideodataoutput/setsamplebufferdelegate(_:queue:)
PyObjC dispatch bindings: https://pyobjc.readthedocs.io/en/latest/apinotes/libdispatch.html
"""
from __future__ import annotations

from io import BytesIO
import math
import sys
import threading
import time
from types import SimpleNamespace

from PIL import Image, ImageOps


WIDTH, HEIGHT = 240, 135
MAX_JPEG_BYTES = 64_000
MAX_FRAME_AGE = 2
_ERRORS = {
    "unsupported": "Camera capture is available on macOS only",
    "unavailable": "Camera capture dependencies are unavailable",
    "permission_denied": "Camera permission is denied; allow camera access in System Settings",
    "permission_pending": "Camera permission is still waiting; allow access and start again",
    "camera_missing": "The selected Mac camera is unavailable",
    "capture_failed": "Camera capture stopped; start the camera again",
    "invalid_frame": "Camera returned an invalid frame",
    "no_frames": "Camera did not produce a recent frame",
}


class CameraError(Exception):
    def __init__(self, category="capture_failed"):
        self.category = category if category in _ERRORS else "capture_failed"
        super().__init__(_ERRORS[self.category])


def _jpeg(image):
    if (not isinstance(image, Image.Image) or not 1 <= image.width <= 1920
            or not 1 <= image.height <= 1080):
        raise CameraError("invalid_frame")
    small = ImageOps.fit(image.convert("RGB"), (WIDTH, HEIGHT), method=Image.Resampling.BILINEAR)
    for quality in (75, 55, 35):
        stream = BytesIO()
        small.save(stream, format="JPEG", quality=quality)
        value = stream.getvalue()
        if len(value) <= MAX_JPEG_BYTES:
            return value
    raise CameraError("invalid_frame")


def _sample_image(sample, media, quartz):
    """Copy a bounded BGRA pixel buffer while it is locked, then release it."""
    buffer = media.CMSampleBufferGetImageBuffer(sample)
    if buffer is None or quartz.CVPixelBufferGetPixelFormatType(buffer) != quartz.kCVPixelFormatType_32BGRA:
        raise CameraError("invalid_frame")
    width, height = int(quartz.CVPixelBufferGetWidth(buffer)), int(quartz.CVPixelBufferGetHeight(buffer))
    stride = int(quartz.CVPixelBufferGetBytesPerRow(buffer))
    if (not 1 <= width <= 1920 or not 1 <= height <= 1080
            or stride < width * 4 or stride * height > 10 * 1024 * 1024):
        raise CameraError("invalid_frame")
    if quartz.CVPixelBufferLockBaseAddress(buffer, 0):
        raise CameraError("invalid_frame")
    try:
        base = quartz.CVPixelBufferGetBaseAddress(buffer)
        if base is None:
            raise CameraError("invalid_frame")
        pixels = bytes(base.as_buffer(stride * height))
        return Image.frombytes("RGB", (width, height), pixels, "raw", "BGRX", stride, 1)
    finally:
        quartz.CVPixelBufferUnlockBaseAddress(buffer, 0)


_delegate_type = None
_delegate_lock = threading.Lock()


def _delegate(modules):
    global _delegate_type
    with _delegate_lock:
        if _delegate_type is None:
            class ModulateCameraFrameDelegate(modules.foundation.NSObject,
                    protocols=[modules.objc.protocolNamed("AVCaptureVideoDataOutputSampleBufferDelegate")]):
                def captureOutput_didOutputSampleBuffer_fromConnection_(self, output, sample, connection):
                    receiver = getattr(self, "receiver", None)
                    if receiver is not None:
                        receiver(sample)
            _delegate_type = ModulateCameraFrameDelegate
        return _delegate_type.alloc().init()


class AVFoundationBackend:
    """Native video only. The first selected camera remains pinned across starts."""
    def __init__(self):
        self.permission = "unknown" if sys.platform == "darwin" else "unsupported"
        self.error = None
        self._device_id = None

    def info(self):
        return {"supported": sys.platform == "darwin", "permission": self.permission,
                "backend": "avfoundation", "source": "Mac camera", "error": self.error}

    @staticmethod
    def _load():
        if sys.platform != "darwin":
            raise CameraError("unsupported")
        try:
            import AVFoundation
            import CoreMedia
            import Quartz
            import dispatch
            import objc
            import Foundation
            return SimpleNamespace(av=AVFoundation, media=CoreMedia, quartz=Quartz,
                                   dispatch=dispatch, objc=objc, foundation=Foundation)
        except ImportError:
            raise CameraError("unavailable") from None

    def _authorization(self, av):
        value = av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeVideo)
        self.permission = {av.AVAuthorizationStatusNotDetermined: "not_determined",
                           av.AVAuthorizationStatusAuthorized: "authorized",
                           av.AVAuthorizationStatusDenied: "denied",
                           av.AVAuthorizationStatusRestricted: "restricted"}.get(value, "unavailable")
        return self.permission

    def refresh_access(self):
        """Read authorization without requesting it or creating a capture session."""
        try:
            self._authorization(self._load().av)
            self.error = None
        except Exception as failure:
            self.permission = "unsupported" if sys.platform != "darwin" else "unavailable"
            self.error = str(failure) if isinstance(failure, CameraError) else _ERRORS["unavailable"]
        return self.info()

    def run(self, on_frame, cancel, fps):
        if cancel.is_set():
            return
        modules = self._load()
        av = modules.av
        permission = self._authorization(av)
        if permission == "not_determined":
            answered = threading.Event()
            av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(av.AVMediaTypeVideo,
                                                                            lambda allowed: answered.set())
            deadline = time.monotonic() + 30
            while not answered.wait(.05):
                if cancel.is_set():
                    return
                if time.monotonic() >= deadline:
                    raise CameraError("permission_pending")
            permission = self._authorization(av)
        if cancel.is_set():
            return
        if permission != "authorized":
            raise CameraError("permission_denied")
        device = (av.AVCaptureDevice.deviceWithUniqueID_(self._device_id) if self._device_id
                  else av.AVCaptureDevice.defaultDeviceWithMediaType_(av.AVMediaTypeVideo))
        if device is None:
            raise CameraError("camera_missing")
        self._device_id = str(device.uniqueID())
        input_device, error = av.AVCaptureDeviceInput.deviceInputWithDevice_error_(device, None)
        if input_device is None or error is not None:
            raise CameraError("camera_missing")
        session = av.AVCaptureSession.alloc().init()
        output = av.AVCaptureVideoDataOutput.alloc().init()
        delegate = _delegate(modules)
        serial = modules.dispatch.dispatch_queue_create(b"modulate.camera.frames", None)
        state = {"next": 0.0, "last": time.monotonic(), "failure": None}

        def receive(sample):
            if cancel.is_set() or state["failure"] is not None:
                return
            now = time.monotonic()
            if now < state["next"]:
                return
            state["next"] = now + 1 / fps
            try:
                image = _sample_image(sample, modules.media, modules.quartz)
                on_frame(image)
                state["last"] = now
            except Exception as failure:
                state["failure"] = failure.category if isinstance(failure, CameraError) else "capture_failed"

        delegate.receiver = receive
        try:
            session.beginConfiguration()
            try:
                preset = next((candidate for candidate in (av.AVCaptureSessionPreset640x480, av.AVCaptureSessionPresetLow)
                               if session.canSetSessionPreset_(candidate)), None)
                if preset is None or not session.canAddInput_(input_device):
                    raise CameraError("capture_failed")
                session.setSessionPreset_(preset)
                session.addInput_(input_device)
                output.setVideoSettings_({modules.quartz.kCVPixelBufferPixelFormatTypeKey:
                                          modules.quartz.kCVPixelFormatType_32BGRA})
                output.setAlwaysDiscardsLateVideoFrames_(True)
                output.setSampleBufferDelegate_queue_(delegate, serial)
                if not session.canAddOutput_(output):
                    raise CameraError("capture_failed")
                session.addOutput_(output)
            finally:
                session.commitConfiguration()
            if cancel.is_set():
                return
            session.startRunning()  # Synchronous native work stays off the caller thread.
            checked = time.monotonic()
            while not cancel.wait(.05):
                if state["failure"] is not None:
                    raise CameraError(state["failure"])
                if not session.isRunning():
                    raise CameraError("capture_failed")
                now = time.monotonic()
                if now - state["last"] > 5:
                    raise CameraError("no_frames")
                if now - checked >= 2:
                    if self._authorization(av) != "authorized":
                        raise CameraError("permission_denied")
                    checked = now
        finally:
            output.setSampleBufferDelegate_queue_(None, None)
            session.stopRunning()
            delegate.receiver = None


class Camera:
    """Asynchronous camera owner with one bounded, expiring in-memory JPEG.

    Injected backend: info(), refresh_access(), run(on_frame,cancel_event,fps).
    start is nonblocking; stop joins for at most two seconds and reports a
    truthful stopping state if native cleanup is still running.
    """
    def __init__(self, backend=None, fps=5, *, clock=time.monotonic, wall_clock=time.time):
        if type(fps) not in (int, float) or not math.isfinite(fps) or not 1 <= fps <= 10:
            raise ValueError("Camera frame rate must be between 1 and 10")
        self.backend = backend if backend is not None else AVFoundationBackend()
        self.fps, self.clock, self.wall_clock = fps, clock, wall_clock
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._generation = self._sequence = 0
        self._latest = None
        self._captured = None
        self._state, self._error = "stopped", None

    def refresh_access(self):
        self.backend.refresh_access()
        return self.status()

    def status(self):
        with self._lock:
            info = dict(self.backend.info())
            age = None if self._captured is None else max(0, self.clock() - self._captured)
            return {**info, "state": self._state, "running": bool(self._thread and self._thread.is_alive()),
                    "error": self._error or info.get("error"), "sequence": self._sequence,
                    "frame_age_seconds": None if age is None else round(age, 3), "fps_limit": self.fps}

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._generation += 1
            generation = self._generation
            self._cancel = threading.Event()
            self._latest = self._captured = None
            self._state, self._error = "starting", None
            self._thread = threading.Thread(target=self._run, args=(generation, self._cancel),
                                            name="modulate-camera", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self):
        with self._lock:
            self._cancel.set()
            self._generation += 1
            self._latest = self._captured = None
            thread = self._thread
            self._state = "stopping" if thread and thread.is_alive() else "stopped"
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        with self._lock:
            if not thread or not thread.is_alive():
                self._state = "stopped"
        return self.status()

    def frame(self):
        with self._lock:
            if (self._latest is None or self._cancel.is_set() or self._state != "running"
                    or self.clock() - self._captured >= MAX_FRAME_AGE):
                return None
            return dict(self._latest)

    def _receive(self, generation, cancel, image):
        with self._lock:
            if generation != self._generation or cancel.is_set():
                return
            if self._captured is not None and self.clock() - self._captured < 1 / self.fps:
                return
        encoded = _jpeg(image)
        with self._lock:
            if generation != self._generation or cancel.is_set():
                return
            self._sequence += 1
            self._captured = self.clock()
            self._latest = {"sequence": self._sequence, "captured_at": self.wall_clock(),
                            "width": WIDTH, "height": HEIGHT, "jpeg": encoded}
            self._state = "running"

    def _run(self, generation, cancel):
        error = None
        try:
            self.backend.run(lambda image: self._receive(generation, cancel, image), cancel, self.fps)
            if not cancel.is_set():
                raise CameraError("capture_failed")
        except Exception as failure:
            error = str(failure) if isinstance(failure, CameraError) else _ERRORS["capture_failed"]
        finally:
            with self._lock:
                if generation == self._generation:
                    self._latest = self._captured = None
                    self._error = error
                    self._state = "error" if error and not cancel.is_set() else "stopped"
                elif cancel.is_set() and self._state == "stopping":
                    self._state = "stopped"
