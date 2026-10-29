"""Synthetic camera tests. No camera, permission prompt, file or network use."""
from io import BytesIO
import queue
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from modulate.camera import Camera, CameraError, AVFoundationBackend, _sample_image, _jpeg


def wait_until(condition):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(.005)
    raise AssertionError("Synthetic camera worker did not finish")


class FakeBackend:
    def __init__(self):
        self.started = threading.Event()
        self.items = queue.Queue()
        self.receivers = []
        self.starts = self.refreshes = self.stops = 0

    def info(self):
        return {"supported": True, "permission": "authorized", "backend": "synthetic", "error": None}

    def refresh_access(self):
        self.refreshes += 1
        return self.info()

    def run(self, receive, cancel, fps):
        self.starts += 1
        self.receivers.append(receive)
        self.started.set()
        try:
            while not cancel.is_set():
                try:
                    item = self.items.get(timeout=.01)
                except queue.Empty:
                    continue
                if isinstance(item, Exception):
                    raise item
                receive(item)
        finally:
            self.stops += 1


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.backend = FakeBackend()
        self.camera = Camera(self.backend, clock=lambda: self.now, wall_clock=lambda: 1000)
        self.addCleanup(self.camera.stop)

    def start(self):
        self.camera.start()
        self.assertTrue(self.backend.started.wait(1))

    def emit(self, color="red"):
        previous = self.camera.status()["sequence"]
        self.backend.items.put(Image.new("RGB", (640, 480), color))
        wait_until(lambda: self.camera.status()["sequence"] > previous)
        return self.camera.frame()

    def test_construct_status_and_permission_refresh_never_start_capture(self):
        self.assertEqual(self.camera.status()["state"], "stopped")
        self.assertIsNone(self.camera.frame())
        self.assertFalse(self.camera.refresh_access()["running"])
        self.assertEqual(self.backend.refreshes, 1)
        self.assertEqual(self.backend.starts, 0)
        with patch.object(AVFoundationBackend, "_load") as load:
            Camera().status()
        load.assert_not_called()

    def test_start_is_nonblocking_and_idempotent_and_keeps_only_small_latest_jpeg(self):
        self.start()
        self.camera.start()
        first = self.emit()
        self.assertEqual(self.backend.starts, 1)
        self.assertEqual((first["width"], first["height"]), (240, 135))
        self.assertEqual(first["captured_at"], 1000)
        self.assertLessEqual(len(first["jpeg"]), 64_000)
        self.assertEqual(Image.open(BytesIO(first["jpeg"])).size, (240, 135))
        self.now += .21
        second = self.emit("blue")
        self.assertNotEqual(first["jpeg"], second["jpeg"])
        self.assertEqual(second["sequence"], first["sequence"] + 1)
        second["sequence"] = -10
        self.assertGreater(self.camera.frame()["sequence"], 0)
        status = self.camera.status()
        self.assertNotIn("jpeg", status)
        self.assertNotIn("image", status)

    def test_rate_cap_drops_excess_frames_and_stale_frames_are_not_returned(self):
        self.start()
        first = self.emit()
        self.now += .1
        self.backend.receivers[0](Image.new("RGB", (640, 480), "blue"))
        self.assertEqual(self.camera.frame()["sequence"], first["sequence"])
        self.now = 102
        self.assertIsNone(self.camera.frame())
        self.assertEqual(self.camera.status()["frame_age_seconds"], 2)

    def test_stop_clears_frame_and_late_old_callback_cannot_repopulate_it(self):
        self.start()
        self.emit()
        old_receive = self.backend.receivers[0]
        self.assertFalse(self.camera.stop()["running"])
        self.assertIsNone(self.camera.frame())
        old_receive(Image.new("RGB", (640, 480), "blue"))
        self.assertIsNone(self.camera.frame())
        self.backend.started.clear()
        self.start()
        self.now += .3
        fresh = self.emit("green")
        self.now += .3
        old_receive(Image.new("RGB", (640, 480), "blue"))
        self.assertEqual(self.camera.frame(), fresh)

    def test_native_failure_discards_frame_and_never_reports_raw_diagnostics(self):
        self.start()
        self.emit()
        self.backend.items.put(RuntimeError("PRIVATE_NATIVE_CAMERA_DETAIL"))
        wait_until(lambda: self.camera.status()["state"] == "error")
        self.assertIsNone(self.camera.frame())
        self.assertNotIn("PRIVATE", repr(self.camera.status()))
        self.assertIn("capture stopped", self.camera.status()["error"])

    def test_invalid_frame_fails_and_clears_previous_frame(self):
        self.start()
        self.emit()
        self.now += .3
        self.backend.items.put(Image.new("RGB", (1921, 1)))
        wait_until(lambda: self.camera.status()["state"] == "error")
        self.assertIsNone(self.camera.frame())
        self.assertIn("invalid frame", self.camera.status()["error"])

    def test_fps_is_bounded_and_noise_jpeg_stays_bounded(self):
        for fps in (True, 0, 11, float("nan"), "5"):
            with self.assertRaises(ValueError):
                Camera(self.backend, fps=fps)
        encoded = _jpeg(Image.effect_noise((1920, 1080), 100).convert("RGB"))
        self.assertLessEqual(len(encoded), 64_000)
        self.assertEqual(Image.open(BytesIO(encoded)).size, (240, 135))


class NativeCameraTests(unittest.TestCase):
    def modules(self, permission):
        device = SimpleNamespace(authorizationStatusForMediaType_=Mock(return_value=permission),
                                 requestAccessForMediaType_completionHandler_=Mock())
        av = SimpleNamespace(AVCaptureDevice=device, AVMediaTypeVideo="video",
                             AVAuthorizationStatusNotDetermined=0, AVAuthorizationStatusRestricted=1,
                             AVAuthorizationStatusDenied=2, AVAuthorizationStatusAuthorized=3)
        return SimpleNamespace(av=av)

    def test_refresh_permission_is_read_only_and_does_not_prompt(self):
        backend = AVFoundationBackend()
        modules = self.modules(0)
        with patch.object(backend, "_load", return_value=modules):
            self.assertEqual(backend.refresh_access()["permission"], "not_determined")
        modules.av.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_not_called()

    def test_denied_or_cancelled_start_does_not_construct_native_session(self):
        backend = AVFoundationBackend()
        modules = self.modules(2)
        with patch.object(backend, "_load", return_value=modules):
            with self.assertRaisesRegex(CameraError, "permission is denied"):
                backend.run(Mock(), threading.Event(), 5)
        cancel = threading.Event()
        cancel.set()
        with patch.object(backend, "_load") as load:
            backend.run(Mock(), cancel, 5)
        load.assert_not_called()
        modules.av.AVCaptureDevice.requestAccessForMediaType_completionHandler_.assert_not_called()

    def test_permission_wait_can_be_cancelled_without_starting_capture(self):
        backend = AVFoundationBackend()
        modules = self.modules(0)
        cancel = threading.Event()
        modules.av.AVCaptureDevice.requestAccessForMediaType_completionHandler_.side_effect = lambda media, callback: cancel.set()
        with patch.object(backend, "_load", return_value=modules):
            backend.run(Mock(), cancel, 5)
        self.assertTrue(cancel.is_set())

    def test_bgra_copy_respects_stride_and_unlocks_without_retaining_native_buffer(self):
        buffer = object()
        pixels = b"\x00\x00\xff\xff" * 2 + bytes(8)
        quartz = SimpleNamespace(
            kCVPixelFormatType_32BGRA=1, CVPixelBufferGetPixelFormatType=lambda value: 1,
            CVPixelBufferGetWidth=lambda value: 2, CVPixelBufferGetHeight=lambda value: 1,
            CVPixelBufferGetBytesPerRow=lambda value: 16, CVPixelBufferLockBaseAddress=Mock(return_value=0),
            CVPixelBufferGetBaseAddress=lambda value: SimpleNamespace(as_buffer=lambda count: pixels[:count]),
            CVPixelBufferUnlockBaseAddress=Mock())
        media = SimpleNamespace(CMSampleBufferGetImageBuffer=lambda sample: buffer)
        image = _sample_image(object(), media, quartz)
        self.assertEqual(image.size, (2, 1))
        self.assertEqual([image.getpixel((x, 0)) for x in range(2)], [(255, 0, 0), (255, 0, 0)])
        quartz.CVPixelBufferUnlockBaseAddress.assert_called_once_with(buffer, 0)
        quartz.CVPixelBufferGetBytesPerRow = lambda value: 7
        with self.assertRaises(CameraError):
            _sample_image(object(), media, quartz)
        self.assertEqual(quartz.CVPixelBufferLockBaseAddress.call_count, 1)


if __name__ == "__main__":
    unittest.main()
