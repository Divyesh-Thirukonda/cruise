"""Synthetic system audio tests. No native capture, speaker, network or files."""
from array import array
import struct
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import patch

from modulate.system_audio import (BLOCK_BYTES, MAX_CHUNK_BYTES, ScreenCaptureBackend,
                                   SystemAudio, SystemAudioError, _pcm)


def block(number):
    return struct.pack("<hh", number, -number) * (BLOCK_BYTES // 4)


class Backend:
    def __init__(self):
        self.ready = threading.Event()
        self.fail = threading.Event()
        self.callback = None
        self.starts = self.refreshes = 0

    def info(self):
        return {"supported": True, "permission": "authorized", "backend": "synthetic", "error": None}

    def refresh_access(self):
        self.refreshes += 1
        return self.info()

    def run(self, callback, cancel):
        self.starts += 1
        self.callback = callback
        self.ready.set()
        while not cancel.wait(.005):
            if self.fail.is_set():
                raise RuntimeError("private native process and audio details")


class SystemAudioTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.backend = Backend()
        self.audio = SystemAudio(self.backend, clock=lambda: self.now)
        self.addCleanup(self.audio.stop)

    def start(self):
        self.audio.start()
        self.assertTrue(self.backend.ready.wait(1))
        return self.audio.status()["session"]

    def test_construct_status_and_permission_refresh_do_not_capture(self):
        self.assertEqual(self.audio.status()["state"], "stopped")
        self.assertIsNone(self.audio.chunk(timeout=0))
        self.audio.refresh_access()
        self.assertEqual(self.backend.refreshes, 1)
        self.assertEqual(self.backend.starts, 0)

    def test_start_is_idempotent_and_partial_native_chunks_are_contiguous(self):
        session = self.start()
        self.audio.start()
        self.assertEqual(self.backend.starts, 1)
        self.assertEqual(self.audio.status()["session"], session)
        pcm = block(123)
        self.backend.callback(pcm[:4000])
        self.assertIsNone(self.audio.chunk(0, session, 0))
        self.backend.callback(pcm[4000:])
        packet = self.audio.chunk(0, session, 0)
        self.assertEqual(packet, {"session": session, "sequence": 1, "pcm": pcm, "reset": False})
        self.assertEqual(self.audio.chunk(0, session, 0), packet, "Unadvanced cursor is idempotent")
        self.assertIsNone(self.audio.chunk(1, session, 0))

    def test_aggregate_contiguous_blocks_and_jump_to_live_edge_when_lagged(self):
        session = self.start()
        for i in range(1, 8):
            self.backend.callback(block(i))
        self.assertEqual(self.audio.status()["buffered_ms"], 500)
        self.assertEqual(self.audio.chunk(3, session, 0),
                         {"session": session, "sequence": 5, "pcm": block(4) + block(5), "reset": False})
        self.assertEqual(self.audio.chunk(5, session, 0)["pcm"], block(6) + block(7))
        for after, provided_session in [(1, session), (None, session), (7, "a" * 32), (0, None)]:
            with self.subTest(after=after, session=provided_session):
                result = self.audio.chunk(after, provided_session, 0)
                self.assertEqual(result["pcm"], block(6) + block(7))
                self.assertEqual(result["sequence"], 7)
                self.assertTrue(result["reset"])
                self.assertLessEqual(len(result["pcm"]), MAX_CHUNK_BYTES)

    def test_expired_audio_cannot_reappear_and_partial_audio_recovers_after_gap(self):
        session = self.start()
        self.backend.callback(block(1))
        self.now += 1
        self.assertIsNone(self.audio.chunk(0, session, 0))
        self.assertEqual(self.audio.status()["buffered_ms"], 0)
        self.backend.callback(block(2)[:9600])
        self.backend.callback(block(2)[9600:])
        self.assertEqual(self.audio.chunk(1, session, 0)["pcm"], block(2))
        self.backend.callback(block(3)[:12000])
        self.now += 1
        self.backend.callback(block(4)[:12000])
        self.assertIsNone(self.audio.chunk(2, session, 0))
        self.backend.callback(block(4)[12000:])
        self.assertEqual(self.audio.chunk(2, session, 0)["pcm"], block(4))

    def test_stop_clears_audio_wakes_waiter_and_old_callback_cannot_revive(self):
        session = self.start()
        old = self.backend.callback
        old(block(1))
        result, waiting = [], threading.Event()

        def fetch():
            waiting.set()
            result.append(self.audio.chunk(1, session, .5))

        waiter = threading.Thread(target=fetch)
        waiter.start()
        self.assertTrue(waiting.wait(1))
        self.audio.stop()
        waiter.join(1)
        self.assertEqual(result, [None])
        self.assertIsNone(self.audio.status()["session"])
        self.assertEqual(self.audio.status()["buffered_ms"], 0)
        old(block(99))
        self.assertIsNone(self.audio.chunk(timeout=0))
        self.backend.ready.clear()
        next_session = self.start()
        self.assertNotEqual(session, next_session)
        old(block(98))
        self.assertIsNone(self.audio.chunk(timeout=0))
        self.backend.callback(block(2))
        self.assertEqual(self.audio.chunk(None, next_session, 0)["pcm"], block(2))

    def test_waiting_chunk_wakes_on_audio_without_polling_main_loop(self):
        session = self.start()
        result = []
        waiter = threading.Thread(target=lambda: result.append(self.audio.chunk(0, session, .5)))
        waiter.start()
        self.backend.callback(block(7))
        waiter.join(1)
        self.assertEqual(result[0]["pcm"], block(7))

    def test_backend_failure_clears_buffer_and_redacts_native_details(self):
        self.start()
        old = self.backend.callback
        old(block(1))
        self.backend.fail.set()
        self.audio._thread.join(1)
        status = self.audio.status()
        self.assertEqual(status["state"], "error")
        self.assertNotIn("private", str(status))
        self.assertEqual(status["buffered_ms"], 0)
        old(block(2))
        self.assertIsNone(self.audio.chunk(timeout=0))

    def test_invalid_cursors_and_native_bytes_reject(self):
        self.start()
        for value in (True, -1, 2**53, 1.2, "0"):
            with self.subTest(after=value), self.assertRaises(ValueError):
                self.audio.chunk(value, timeout=0)
        for value in ("wrong", "A" * 32, 1):
            with self.subTest(session=value), self.assertRaises(ValueError):
                self.audio.chunk(session=value, timeout=0)
        for value in (True, -.1, .501, float("nan")):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                self.audio.chunk(timeout=value)
        for value in (b"", b"123", bytearray(4), bytes(MAX_CHUNK_BYTES + 4)):
            with self.subTest(length=len(value)), self.assertRaises(SystemAudioError):
                self.backend.callback(value)
        self.assertEqual(self.audio.status()["sequence"], 0)


class ConversionTests(unittest.TestCase):
    def convert(self, planes, frames, **changes):
        args = dict(rate=48000, channels=2, bits=32, flags=1 | 8 | 32, format_id=0x6C70636D)
        args.update(changes)
        return _pcm(planes, frames, **args)

    def test_planar_float_interleaves_clips_and_preserves_channel_order(self):
        left = struct.pack("<4f", -2, -.5, 0, .5)
        right = struct.pack("<4f", 2, .25, -.25, 0)
        pcm = self.convert([left, right], 4)
        self.assertEqual(struct.unpack("<8h", pcm), (-32768, 32767, -16384, 8192, 0, -8192, 16384, 0))

    def test_interleaved_float_and_big_endian_integer(self):
        self.assertEqual(self.convert([struct.pack("<2f", .5, -.5)], 1, flags=1 | 8),
                         struct.pack("<2h", 16384, -16384))
        self.assertEqual(self.convert([struct.pack(">4h", 1, -2, 3, -4)], 2, bits=16, flags=2 | 4 | 8),
                         struct.pack("<4h", 1, -2, 3, -4))
        self.assertEqual(self.convert([struct.pack("<2h", 1, 2), struct.pack("<2h", 3, 4)],
                                     2, bits=16, flags=4 | 8 | 32), struct.pack("<4h", 1, 3, 2, 4))

    def test_rejects_wrong_rate_channels_size_flags_and_nonfinite_samples(self):
        planes = [struct.pack("<f", 0), struct.pack("<f", 0)]
        for changes in ({"rate": 44100}, {"channels": 1}, {"bits": 64}, {"flags": 1 | 32},
                        {"flags": 1 | 8 | 32 | 64}, {"format_id": 0}, {"flags": 1 | 4 | 8 | 32}):
            with self.subTest(changes=changes), self.assertRaises(SystemAudioError):
                self.convert(planes, 1, **changes)
        for frames in (0, 9601, True):
            with self.subTest(frames=frames), self.assertRaises(SystemAudioError):
                self.convert(planes, frames)
        for bad in ([planes[0]], [planes[0] + b"1234", planes[1]],
                    [struct.pack("<f", float("nan")), planes[1]]):
            with self.assertRaises(SystemAudioError):
                self.convert(bad, 1)


class NativeConfigurationTests(unittest.TestCase):
    def test_audio_only_stream_excludes_own_process_and_never_captures_mic_or_video(self):
        cancel = threading.Event()
        settings, types, stopped, received = {}, [], [], []
        delegate = SimpleNamespace(receiver=None, stopped=None)

        class Configuration:
            def __getattr__(self, name):
                return lambda value: settings.__setitem__(name, value)

        class Stream:
            def addStreamOutput_type_sampleHandlerQueue_error_(self, output, kind, queue, error):
                types.append(kind)
                return True, None

            def startCaptureWithCompletionHandler_(self, callback):
                callback(None)
                delegate.receiver("ignored video", 0)
                delegate.receiver("synthetic sample", 1)

            def stopCaptureWithCompletionHandler_(self, callback):
                stopped.append(True)
                callback(None)

            def removeStreamOutput_type_error_(self, *args):
                return True, None

        display = SimpleNamespace(displayID=lambda: 123)
        content = SimpleNamespace(displays=lambda: [display])
        config, stream = Configuration(), Stream()
        sc = SimpleNamespace(
            SCStreamOutputTypeAudio=1,
            SCShareableContent=SimpleNamespace(
                getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_=
                lambda desktop, onscreen, callback: callback(content, None)),
            SCContentFilter=SimpleNamespace(alloc=lambda: SimpleNamespace(
                initWithDisplay_excludingWindows_=lambda display, windows: "filter")),
            SCStreamConfiguration=SimpleNamespace(alloc=lambda: SimpleNamespace(init=lambda: config)),
            SCStream=SimpleNamespace(alloc=lambda: SimpleNamespace(
                initWithFilter_configuration_delegate_=lambda *args: stream)))
        modules = SimpleNamespace(sc=sc, quartz=SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: True,
                                                             CGMainDisplayID=lambda: 123),
                                  media=SimpleNamespace(CMTimeMake=lambda *args: args),
                                  dispatch=SimpleNamespace(dispatch_queue_create=lambda *args: "queue"))

        def on_pcm(pcm):
            received.append(pcm)
            cancel.set()

        backend = ScreenCaptureBackend()
        with patch.object(backend, "_load", return_value=modules), \
                patch("modulate.system_audio._delegate", return_value=delegate), \
                patch("modulate.system_audio._sample_pcm", return_value=block(1)) as convert:
            backend.run(on_pcm, cancel)
        self.assertEqual(types, [1])
        self.assertEqual(received, [block(1)])
        self.assertEqual(convert.call_count, 1)
        self.assertEqual(settings["setSampleRate_"], 48000)
        self.assertEqual(settings["setChannelCount_"], 2)
        self.assertIs(settings["setCapturesAudio_"], True)
        self.assertIs(settings["setExcludesCurrentProcessAudio_"], True)
        self.assertIs(settings["setCaptureMicrophone_"], False)
        self.assertEqual(stopped, [True])
        self.assertIsNone(delegate.receiver)

    def test_denied_permission_and_precancelled_start_do_not_create_stream(self):
        backend = ScreenCaptureBackend()
        modules = SimpleNamespace(quartz=SimpleNamespace(CGPreflightScreenCaptureAccess=lambda: False), sc=None)
        with patch.object(backend, "_load", return_value=modules) as load:
            self.assertEqual(backend.refresh_access()["permission"], "denied")
            with self.assertRaisesRegex(SystemAudioError, "Allow Screen"):
                backend.run(lambda _: self.fail("Must not capture"), threading.Event())
            cancel = threading.Event()
            cancel.set()
            before = load.call_count
            backend.run(lambda _: self.fail("Must not capture"), cancel)
            self.assertEqual(load.call_count, before)


if __name__ == "__main__":
    unittest.main()
