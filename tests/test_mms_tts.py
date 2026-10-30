"""Process-boundary tests with synthetic PCM; no real model or audio playback."""
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

from modulate.mms_tts import MMSTTS, MMSError
from modulate.mms_worker import normalize


class MMSTests(unittest.TestCase):
    def tts(self, script, timeout=1):
        value = MMSTTS(command=[sys.executable, "-u", "-c", script], timeout=timeout)
        self.addCleanup(value.close)
        return value

    def test_reuses_worker_without_provider_or_ledger(self):
        value = self.tts("import sys,struct\nfor line in sys.stdin:\n sys.stdout.buffer.write(struct.pack('!I',4)+b'\\0'*4);sys.stdout.buffer.flush()")
        self.assertEqual(value.synthesize("Test", threading.Event()), b"\0"*4)
        pid = value.process.pid
        self.assertEqual(value.synthesize("Next", threading.Event()), b"\0"*4)
        self.assertEqual(value.process.pid, pid)
        self.assertTrue(value.status()["local"])

    def test_invalid_lengths_and_truncated_audio_fail_closed(self):
        for size, pcm in ((0, b""), (3, b"abc"), (4_320_002, b""), (4, b"a")):
            with self.subTest(size=size, pcm=pcm):
                value = self.tts("import sys\nsys.stdin.readline()\nsys.stdout.buffer.write(" + repr(struct.pack('!I', size)+pcm) + ")")
                with self.assertRaises(MMSError): value.synthesize("Test", threading.Event())
                self.assertIsNone(value.process)

    def test_timeout_partial_header_kills_worker(self):
        value = self.tts("import sys,time\nsys.stdin.readline()\nsys.stdout.buffer.write(b'\\0');sys.stdout.flush();time.sleep(5)", timeout=.15)
        with self.assertRaisesRegex(MMSError, "timed out"): value.synthesize("Test", threading.Event())
        self.assertIsNone(value.process)

    def test_cancel_kills_worker_and_prevents_late_audio(self):
        value = self.tts("import sys,time\nsys.stdin.readline()\ntime.sleep(5)")
        cancel = threading.Event()
        timer = threading.Timer(.1, cancel.set); timer.start()
        started = time.monotonic()
        with self.assertRaisesRegex(MMSError, "cancelled"): value.synthesize("Test", cancel)
        timer.join()
        self.assertLess(time.monotonic()-started, .8)
        self.assertIsNone(value.process)

    def test_invalid_text_does_not_launch_worker(self):
        value = self.tts("raise RuntimeError('must not run')")
        for text in (None, "", "a"*1201, "bad\0text"):
            with self.assertRaises(MMSError): value.synthesize(text, threading.Event())
            self.assertIsNone(value.process)

    def test_local_worker_does_not_inherit_provider_credentials(self):
        value = self.tts("import os,sys,struct\nsys.stdin.readline()\nb=b'safe' if 'MODEL_API_KEY' not in os.environ else b'leak'\nsys.stdout.buffer.write(struct.pack('!I',4)+b)")
        with patch.dict("os.environ", {"MODEL_API_KEY": "synthetic-secret"}):
            self.assertEqual(value.synthesize("Test", threading.Event()), b"safe")

    def test_numbers_are_not_silently_removed_by_english_vocabulary(self):
        self.assertEqual(normalize("Brightness 47%, cost 11.44"), "Brightness forty seven percent, cost eleven point four four")
