"""Process-boundary and CTC checks; fixtures are not microphone evidence."""
import io
import json
import os
from pathlib import Path
import struct
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
import wave

from modulate.speech import LocalSpeech, SpeechError, MAX_PCM

READ = "import sys,struct,json,os\nn=struct.unpack('!I',sys.stdin.buffer.read(4))[0]\na=sys.stdin.buffer.read(n)\n"


class MetaSpeechTests(unittest.TestCase):
    def speech(self, script, timeout=1):
        value = LocalSpeech(command=[sys.executable, "-u", "-c", script], timeout=timeout)
        self.addCleanup(value.close)
        return value

    def test_bounded_worker_reused_and_credentials_not_inherited(self):
        script = "import sys,struct,json,os\nwhile True:\n h=sys.stdin.buffer.read(4)\n if not h: break\n n=struct.unpack('!I',h)[0];a=sys.stdin.buffer.read(n)\n t='safe' if 'MODEL_API_KEY' not in os.environ and os.environ.get('HF_HUB_OFFLINE')=='1' else 'leak'\n b=json.dumps(t).encode();sys.stdout.buffer.write(struct.pack('!I',len(b))+b);sys.stdout.buffer.flush()"
        value = self.speech(script)
        with patch.dict(os.environ, {"MODEL_API_KEY": "synthetic-test-secret"}):
            self.assertEqual(value.transcribe_pcm(bytes(32000)), "safe")
            pid = value.process.pid
            self.assertEqual(value.transcribe_pcm(bytes(32000)), "safe")
            self.assertEqual(value.process.pid, pid)

    def test_oversized_or_malformed_audio_never_starts_worker(self):
        value = self.speech("raise RuntimeError('must not run')")
        for audio in (None, "a", b"", b"a", bytes(MAX_PCM + 2)):
            with self.assertRaises(SpeechError): value.transcribe_pcm(audio)
            self.assertIsNone(value.process)

    def test_malformed_or_oversized_result_kills_worker(self):
        for payload in (b"not json", b"{}", json.dumps("a"*2001).encode(), b'"bad\\u0000text"'):
            value = self.speech(READ + "sys.stdout.buffer.write(" + repr(struct.pack('!I',len(payload))+payload) + ")")
            with self.assertRaises(SpeechError): value.transcribe_pcm(bytes(32000))
            self.assertIsNone(value.process)
        value = self.speech(READ + "sys.stdout.buffer.write(struct.pack('!I',10000))")
        with self.assertRaises(SpeechError): value.transcribe_pcm(bytes(32000))
        self.assertIsNone(value.process)

    def test_timeout_and_cancel_interrupt_even_a_blocked_input_pipe(self):
        for cancel_request in (False, True):
            value = self.speech("import time;time.sleep(5)", timeout=.2 if not cancel_request else 2)
            cancel = threading.Event()
            timer = threading.Timer(.1, cancel.set) if cancel_request else None
            if timer: timer.start()
            started = time.monotonic()
            with self.assertRaisesRegex(SpeechError, "cancelled" if cancel_request else "timed out"):
                value.transcribe_pcm(bytes(MAX_PCM), cancel)
            if timer: timer.join()
            self.assertLess(time.monotonic()-started, 1)
            self.assertIsNone(value.process)

    def test_partial_response_is_rejected(self):
        value = self.speech(READ + "sys.stdout.buffer.write(b'\\0\\0')")
        with self.assertRaises(SpeechError): value.transcribe_pcm(bytes(32000))
        self.assertIsNone(value.process)

    def test_wav_format_and_truncation_checked_before_recognition(self):
        value = LocalSpeech()
        value.transcribe_pcm = Mock(return_value="HELLO")
        for rate, channels in ((16000, 1), (48000, 1), (16000, 2)):
            stream = io.BytesIO()
            with wave.open(stream, "wb") as wav:
                wav.setnchannels(channels);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(bytes(32000))
            audio = stream.getvalue()
            if rate == 16000 and channels == 1:
                self.assertEqual(value.transcribe(audio), "HELLO")
            else:
                with self.assertRaises(SpeechError): value.transcribe(audio)
            with self.assertRaises(SpeechError): value.transcribe(audio[:-4])
        value.transcribe_pcm.assert_called_once_with(bytes(32000))

    def test_missing_install_does_not_download_or_fallback(self):
        value = LocalSpeech(python="/missing/python", model_dir="/missing/model")
        with patch("subprocess.Popen") as start:
            with self.assertRaisesRegex(SpeechError, "not installed"):
                value.transcribe_pcm(bytes(32000))
            start.assert_not_called()


class MetaCTCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError:
            raise unittest.SkipTest("Run with .venv-asr for actual CTC tensor checks")
        cls.torch = torch

    def test_blank_and_uncertain_tokens_never_decode_into_wake(self):
        from modulate.asr_worker import decode_logits
        processor = Mock()
        blank = self.torch.zeros(1, 8, 4);blank[:, :, 0] = 20
        uncertain = self.torch.zeros(1, 8, 4);uncertain[:, :, 1] = .1
        for logits in (blank, uncertain):
            self.assertEqual(decode_logits(logits, processor, 0), "")
        processor.batch_decode.assert_not_called()

    def test_valid_emissions_decode_and_invalid_logits_are_rejected(self):
        from modulate.asr_worker import decode_logits
        processor = Mock();processor.batch_decode.return_value = ["HEY META"]
        logits = self.torch.zeros(1, 8, 4);logits[:, :, 1] = 20
        self.assertEqual(decode_logits(logits, processor, 0), "HEY META")
        logits[0, 0, 0] = float("nan")
        with self.assertRaises(ValueError): decode_logits(logits, processor, 0)


if __name__ == "__main__":
    unittest.main()
