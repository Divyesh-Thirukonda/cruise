"""Synthetic Pi camera-frame validation; no capture, GPIO, network or files."""
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from modulate.device import Controller


def encoded_image(*, size=(240, 135), color="red", format="JPEG"):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=format)
    return base64.b64encode(output.getvalue()).decode("ascii")


class DeviceCameraTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.current = {"revision": "a" * 64, "kind": "game"}
        self.controller = Controller.__new__(Controller)
        self.controller.runtime = SimpleNamespace(snapshot=lambda: dict(self.current))
        self.controller.camera_image = None
        self.controller.camera_identity = None
        self.controller.camera_received_at = 0.0
        self.controller.camera_frames_received = 0
        self.jpeg = encoded_image()
        clock = patch("modulate.device.time.monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def packet(self, **changes):
        value = {"revision": self.current["revision"], "session": "b" * 32,
                 "sequence": 1, "jpeg": self.jpeg}
        value.update(changes)
        return value

    def test_valid_frame_decodes_to_exact_rgb_size_with_identity_and_receive_time(self):
        packet = self.packet()
        self.controller._update_camera(packet)
        image = self.controller._live_camera_image()
        self.assertIsNotNone(image)
        self.assertEqual(image.size, (240, 135))
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(self.controller.camera_identity, ("a" * 64, "b" * 32, 1))
        self.assertEqual(self.controller.camera_received_at, 100)
        self.assertEqual(self.controller.camera_frames_received, 1)

    def test_invalid_packet_types_identity_fields_and_bounds_clear_visible_frame(self):
        bad = [[], "invalid", {}, self.packet(extra="unsupported"),
               self.packet(revision="c" * 64), self.packet(session="not-a-session"),
               self.packet(session="B" * 32), self.packet(sequence=True),
               self.packet(sequence=0), self.packet(sequence=2**53), self.packet(sequence=1.5),
               self.packet(jpeg=b"not text"), self.packet(jpeg="A" * 86_001)]
        for value in bad:
            with self.subTest(packet_type=type(value).__name__):
                self.controller._update_camera(self.packet(sequence=self.controller.camera_frames_received + 1))
                self.assertIsNotNone(self.controller._live_camera_image())
                before = self.controller.camera_frames_received
                self.controller._update_camera(value)
                self.assertIsNone(self.controller._live_camera_image())
                self.assertIsNone(self.controller.camera_image)
                self.assertEqual(self.controller.camera_frames_received, before)

    def test_invalid_base64_oversized_bytes_wrong_dimensions_and_non_jpeg_reject(self):
        bad = ["@@@invalid@@@", base64.b64encode(b"x" * 64_002).decode(),
               base64.b64encode(b"not an image").decode(), encoded_image(size=(241, 135)),
               encoded_image(size=(240, 134)), encoded_image(format="PNG")]
        for encoded in bad:
            with self.subTest(length=len(encoded)):
                self.controller._update_camera(self.packet(jpeg=encoded))
                self.assertIsNone(self.controller._live_camera_image())
                self.assertEqual(self.controller.camera_frames_received, 0)

    def test_duplicate_or_lower_sequence_never_replaces_or_refreshes_existing_frame(self):
        self.controller._update_camera(self.packet(sequence=4))
        original = self.controller.camera_image
        self.now = 101.9
        for sequence in (4, 3, 1):
            self.controller._update_camera(self.packet(sequence=sequence, jpeg=encoded_image(color="blue")))
            self.assertIs(self.controller._live_camera_image(), original)
            self.assertEqual(self.controller.camera_received_at, 100)
        self.assertEqual(self.controller.camera_frames_received, 1)
        self.now = 102
        self.assertIsNone(self.controller._live_camera_image())
        self.controller._update_camera(self.packet(sequence=4))
        self.assertIsNone(self.controller._live_camera_image(), "A repeated heartbeat cannot revive an expired frame")
        self.controller._update_camera(self.packet(sequence=5))
        self.assertIsNotNone(self.controller._live_camera_image())
        self.assertEqual(self.controller.camera_received_at, 102)

    def test_revocation_clears_image_but_retains_replay_watermark(self):
        old = self.packet(sequence=7)
        self.controller._update_camera(old)
        self.controller._update_camera(None)
        self.assertIsNone(self.controller.camera_image)
        self.assertIsNone(self.controller._live_camera_image())
        self.now += 1
        self.controller._update_camera(old)
        self.assertIsNone(self.controller._live_camera_image(), "Revocation must not reset the accepted sequence")
        self.assertEqual(self.controller.camera_frames_received, 1)
        self.controller._update_camera(self.packet(sequence=8))
        self.assertIsNotNone(self.controller._live_camera_image())

    def test_malformed_packet_cannot_erase_watermark_and_replay_old_frame(self):
        old = self.packet(sequence=7)
        self.controller._update_camera(old)
        self.controller._update_camera({"invalid": True})
        self.now += 1
        self.controller._update_camera(old)
        self.assertIsNone(self.controller._live_camera_image())
        self.assertEqual(self.controller.camera_frames_received, 1)

    def test_revision_change_clears_frame_so_quick_rollback_cannot_revive_it(self):
        old = self.packet(sequence=7)
        self.controller._update_camera(old)
        self.current["revision"] = "c" * 64
        self.assertIsNone(self.controller._live_camera_image())
        self.current["revision"] = "a" * 64
        self.assertIsNone(self.controller._live_camera_image(), "Returning to a revision must not restore old camera pixels")
        self.controller._update_camera(old)
        self.assertIsNone(self.controller._live_camera_image())
        self.controller._update_camera(self.packet(sequence=8))
        self.assertIsNotNone(self.controller._live_camera_image())

    def test_new_host_session_accepts_sequence_reset_but_old_session_cannot_return(self):
        self.controller._update_camera(self.packet(sequence=100))
        self.now += .3
        fresh = self.packet(session="c" * 32, sequence=1, jpeg=encoded_image(color="blue"))
        self.controller._update_camera(fresh)
        image = self.controller._live_camera_image()
        self.assertIsNotNone(image)
        self.assertGreater(image.getpixel((0, 0))[2], 240)
        self.now += .3
        self.controller._update_camera(self.packet(sequence=101))
        image = self.controller._live_camera_image()
        self.assertTrue(image is None or image.getpixel((0, 0))[2] > 240,
                        "A retired host camera session must not replace its successor")

    def test_no_active_revision_cannot_authorize_a_camera_frame(self):
        self.current["revision"] = None
        self.controller._update_camera(self.packet())
        self.assertIsNone(self.controller._live_camera_image())
        self.assertEqual(self.controller.camera_frames_received, 0)

    def test_camera_telemetry_and_present_cannot_invert_runtime_controller_locks(self):
        controller = self.controller
        controller.lock = threading.RLock()
        runtime_lock = threading.RLock()
        rendering, snapshot_requested = threading.Event(), threading.Event()
        snapshots_under_controller_lock = []

        def snapshot():
            snapshots_under_controller_lock.append(controller.lock._is_owned())
            snapshot_requested.set()
            with runtime_lock:
                return dict(self.current)

        controller.runtime = SimpleNamespace(snapshot=snapshot, _lock=runtime_lock)
        controller.screen = SimpleNamespace(display=Mock())
        controller.camera_image = Image.new("RGB", (240, 135), "red")
        controller.camera_identity = (self.current["revision"], "b" * 32, 1)
        controller.camera_received_at = self.now
        controller.camera_frames_received = 1
        for name in ("cancellations", "requests", "actions", "responses", "setup_actions", "library_actions"):
            setattr(controller, name, queue.Queue())
        from modulate.library_screen import LibraryScreen
        controller.library_screen = LibraryScreen()
        controller.session = "c" * 32
        controller.sequence = controller.encoder_pending = 0
        controller.encoder_revision = self.current["revision"]
        controller.state = dict(self.current)
        controller.sample = {"encoder_delta": 0}
        controller.commands = []
        controller.fps = 20
        controller.voice_state = controller.speaker_state = {}
        controller.voice_history = []
        controller.build = None
        controller.request_in_flight = False
        controller.host = controller.pairing = {}
        controller.display_state = {}
        controller.speech_ack = None
        controller.controls = SimpleNamespace(capabilities=lambda: {"controls": [], "devices": [], "warnings": []})
        controller.companion = SimpleNamespace(post=Mock(return_value={}))

        def draw_frame():
            # DeviceActivation.tick holds its runtime lock while present() takes
            # the controller lock. Force telemetry to request a snapshot exactly
            # then. A bounded acquire makes the old deadlock a test failure,
            # never a hanging test worker.
            with runtime_lock:
                rendering.set()
                self.assertTrue(snapshot_requested.wait(1))
                acquired = controller.lock.acquire(timeout=0.5)
                self.assertTrue(acquired, "Telemetry held the controller lock while waiting for the runtime")
                try:
                    controller.present(controller.camera_image)
                finally:
                    controller.lock.release()

        with ThreadPoolExecutor(max_workers=2) as pool:
            draw = pool.submit(draw_frame)
            self.assertTrue(rendering.wait(1))
            heartbeat = pool.submit(controller._network_step)
            draw.result(timeout=2)
            heartbeat.result(timeout=2)
        self.assertTrue(snapshots_under_controller_lock)
        self.assertFalse(any(snapshots_under_controller_lock))
        controller.screen.display.image.assert_called_once()
        endpoint, packet = controller.companion.post.call_args.args
        self.assertEqual(endpoint, "heartbeat")
        self.assertEqual(packet["telemetry"]["camera"], {"frames_received": 1, "frame_fresh": True})


if __name__ == "__main__":
    unittest.main()
