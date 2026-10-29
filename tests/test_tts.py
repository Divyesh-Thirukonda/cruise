"""Network-free checks; all text, voices and credentials here are test placeholders."""

import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

from modulate.tts import ElevenLabsTTS, TTSError, _NoRedirect


class Response:
    def __init__(self, data=b"\0\0" * 12, *, headers=None, status=200, url=None, read_hook=None):
        self.data = io.BytesIO(data)
        self.headers = {"Content-Type": "audio/pcm", **(headers or {})}
        self.status = status
        self.url = url
        self.read_hook = read_hook
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        self.data.close()

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def read(self, count):
        if self.read_hook:
            self.read_hook()
        return self.data.read(count)


class Opener:
    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        if self.response.url is None:
            self.response.url = request.full_url
        return self.response


class TTSTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cancel = threading.Event()

    def tts(self, opener=None, **kwargs):
        return ElevenLabsTTS(self.directory.name, api_key="unit-test-only",
                             voice_id="test-voice", opener=opener or Opener(), **kwargs)

    def ledger(self):
        return json.loads((Path(self.directory.name) / "tts-character-ledger.json").read_text())

    def error(self, category, function):
        with self.assertRaises(TTSError) as caught:
            function()
        self.assertEqual(caught.exception.category, category)
        return caught.exception

    def test_pcm_request_and_minimal_status(self):
        opener = Opener()
        tts = self.tts(opener)
        self.assertEqual(tts.synthesize("A test sentence.", self.cancel), b"\0\0" * 12)
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url,
            "https://api.elevenlabs.io/v1/text-to-speech/test-voice/stream?output_format=pcm_24000")
        self.assertEqual(json.loads(request.data), {"text": "A test sentence.", "model_id": "eleven_flash_v2_5"})
        self.assertEqual(request.get_header("Xi-api-key"), "unit-test-only")
        self.assertEqual(timeout, 10)
        self.assertEqual(tts.status(), {"provider": "elevenlabs", "model": "eleven_flash_v2_5",
                                       "voice": "test-voice", "configured": True})
        self.assertEqual(self.ledger(), {"version": 1, "reserved_characters": 16,
                                        "settled_characters": 16, "requests": 1, "uncertain_requests": 0})
        saved = (Path(self.directory.name) / "tts-character-ledger.json").read_text()
        self.assertNotIn("sentence", saved)
        self.assertNotIn("unit-test-only", saved)
        self.assertEqual((Path(self.directory.name) / "tts-character-ledger.json").stat().st_mode & 0o777, 0o600)
        self.assertTrue(opener.response.closed)

    def test_environment_configuration_without_sdk(self):
        with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "unit-test-only",
                        "ELEVENLABS_VOICE_ID": "env-test-voice", "ELEVENLABS_MODEL_ID": "eleven_multilingual_v2"}):
            tts = ElevenLabsTTS(self.directory.name, opener=Opener())
        self.assertEqual(tts.status(), {"provider": "elevenlabs", "model": "eleven_multilingual_v2",
                                       "voice": "env-test-voice", "configured": True})

    def test_unconfigured_does_not_create_ledger_or_call(self):
        opener = Opener()
        tts = ElevenLabsTTS(self.directory.name, api_key="", voice_id="", opener=opener)
        self.assertFalse(tts.status()["configured"])
        self.error("configuration", lambda: tts.synthesize("Test", self.cancel))
        self.assertFalse(opener.calls)
        self.assertFalse((Path(self.directory.name) / "tts-character-ledger.json").exists())

    def test_configuration_cannot_change_url_or_inject_header(self):
        for args in ({"voice_id": "../other"}, {"voice_id": "https://example.test"},
                     {"model_id": "bad\nmodel"}, {"api_key": "bad\nheader"}):
            with self.subTest(args=list(args)):
                self.error("configuration", lambda: ElevenLabsTTS(self.directory.name, **args))

    def test_invalid_text_and_pre_cancel_do_not_reserve(self):
        opener = Opener()
        tts = self.tts(opener)
        for text in (None, "", "   ", "a" * 1201, "test\0", "test\x7f", "\ud800"):
            with self.subTest(kind=type(text).__name__):
                self.error("text", lambda: tts.synthesize(text, self.cancel))
        self.cancel.set()
        self.error("cancelled", lambda: tts.synthesize("Test", self.cancel))
        self.assertFalse(opener.calls)
        self.assertFalse((Path(self.directory.name) / "tts-character-ledger.json").exists())

    def test_budget_survives_new_instance_and_never_resets(self):
        self.tts(max_chars=5).synthesize("hello", self.cancel)
        opener = Opener()
        self.error("budget", lambda: self.tts(opener, max_chars=5).synthesize("x", self.cancel))
        self.assertFalse(opener.calls)
        self.tts(max_chars=6).synthesize("x", self.cancel)
        self.assertEqual(self.ledger()["reserved_characters"], 6)

    def test_uncertain_http_failure_retains_charge_without_body(self):
        body = io.BytesIO(b"untrusted response detail")
        error = urllib.error.HTTPError("https://api.elevenlabs.io/", 429, "private provider detail", {}, body)
        opener = Opener(error=error)
        found = self.error("http", lambda: self.tts(opener, max_chars=5).synthesize("hello", self.cancel))
        self.assertEqual(found.status, 429)
        self.assertNotIn("private", str(found))
        self.assertNotIn("untrusted", str(found))
        self.assertTrue(body.closed)
        self.assertEqual(self.ledger()["reserved_characters"], 5)
        self.assertEqual(self.ledger()["settled_characters"], 0)
        self.error("budget", lambda: self.tts(max_chars=5).synthesize("x", self.cancel))

    def test_corrupt_ledger_fails_closed(self):
        path = Path(self.directory.name) / "tts-character-ledger.json"
        for content in ("not json", "{}", '{"version":1,"version":1}', json.dumps({"version": 1, "reserved_characters": 2,
                            "settled_characters": 3, "requests": 1, "uncertain_requests": 0})):
            path.write_text(content)
            opener = Opener()
            self.error("ledger", lambda: self.tts(opener).synthesize("Test", self.cancel))
            self.assertFalse(opener.calls)
            self.assertEqual(path.read_text(), content)

    def test_reservation_write_failure_prevents_dispatch(self):
        opener = Opener()
        with patch("modulate.tts.os.replace", side_effect=OSError("test-only failure")):
            self.error("ledger", lambda: self.tts(opener).synthesize("Test", self.cancel))
        self.assertFalse(opener.calls)

    def test_redirects_are_rejected_without_forwarding(self):
        self.error("redirect", lambda: _NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.test"))
        opener = Opener(Response(url="https://example.test/audio"))
        self.error("redirect", lambda: self.tts(opener).synthesize("Test", self.cancel))
        self.assertEqual(len(opener.calls), 1)

    def test_bad_audio_never_settles_as_success(self):
        cases = [(b"", {}), (b"x", {}), (b"\0\0", {"Content-Type": "application/json"}),
                 (b"\0\0", {"Content-Length": "4"}), (b"\0\0", {"Content-Length": "unknown"}),
                 (b"\0\0", {"Content-Length": "3"})]
        for data, headers in cases:
            opener = Opener(Response(data, headers=headers))
            self.error("audio", lambda: self.tts(opener).synthesize("Test", self.cancel))
            self.assertTrue(opener.response.closed)
        self.assertEqual(self.ledger()["settled_characters"], 0)
        self.assertEqual(self.ledger()["uncertain_requests"], len(cases))

    def test_byte_cap_with_and_without_content_length(self):
        with patch("modulate.tts.MAX_AUDIO_BYTES", 8):
            for headers in ({}, {"Content-Length": "10"}):
                opener = Opener(Response(b"\0" * 10, headers=headers))
                self.error("audio", lambda: self.tts(opener).synthesize("Test", self.cancel))
        self.assertEqual(self.ledger()["settled_characters"], 0)

    def test_network_error_is_generic_and_does_not_fallback(self):
        opener = Opener(error=urllib.error.URLError("untrusted transport diagnostics"))
        found = self.error("network", lambda: self.tts(opener).synthesize("Test", self.cancel))
        self.assertNotIn("diagnostics", str(found))
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(self.ledger()["uncertain_requests"], 1)

    def test_two_instances_share_reservations_before_dispatch(self):
        entered, release = threading.Event(), threading.Event()
        def wait_read():
            entered.set()
            release.wait(2)
        first = self.tts(Opener(Response(read_hook=wait_read)), max_chars=5)
        results = []
        caller = threading.Thread(target=lambda: results.append(first.synthesize("hello", self.cancel)))
        caller.start()
        try:
            self.assertTrue(entered.wait(1))
            opener = Opener()
            self.error("budget", lambda: self.tts(opener, max_chars=5).synthesize("x", threading.Event()))
            self.assertFalse(opener.calls)
        finally:
            release.set()
            caller.join(2)
        self.assertEqual(results, [b"\0\0" * 12])
        self.assertEqual(self.ledger()["reserved_characters"], 5)

    def test_failed_success_accounting_does_not_return_audio(self):
        tts = self.tts()
        with patch.object(tts._ledger, "settle", side_effect=TTSError("ledger")):
            self.error("ledger", lambda: tts.synthesize("Test", self.cancel))
        self.assertEqual(self.ledger()["settled_characters"], 0)
        self.assertEqual(self.ledger()["uncertain_requests"], 1)

    def test_cancellation_during_read_returns_promptly_and_blocks_overlap(self):
        entered, release = threading.Event(), threading.Event()
        def wait_read():
            entered.set()
            release.wait(2)
        tts = self.tts(Opener(Response(read_hook=wait_read)))
        errors = []
        def synthesize():
            try:
                tts.synthesize("Test", self.cancel)
            except TTSError as error:
                errors.append(error.category)
        caller = threading.Thread(target=synthesize)
        caller.start()
        try:
            self.assertTrue(entered.wait(1))
            self.cancel.set()
            caller.join(0.5)
            self.assertFalse(caller.is_alive())
            self.assertEqual(errors, ["cancelled"])
            self.error("busy", lambda: tts.synthesize("Later", threading.Event()))
        finally:
            release.set()
            caller.join(2)
        deadline = time.monotonic() + 1
        while tts._active.locked() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(tts._active.locked())
        self.assertEqual(self.ledger()["settled_characters"], 0)
        self.assertEqual(self.ledger()["uncertain_requests"], 1)

    def test_total_deadline_keeps_reservation_and_discards_late_audio(self):
        release = threading.Event()
        tts = self.tts(Opener(Response(read_hook=lambda: release.wait(1))), total_timeout=0.04)
        try:
            self.error("timeout", lambda: tts.synthesize("Test", self.cancel))
        finally:
            release.set()
        deadline = time.monotonic() + 1
        while tts._active.locked() and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(self.ledger()["settled_characters"], 0)
        self.assertEqual(self.ledger()["reserved_characters"], 4)


if __name__ == "__main__":
    unittest.main()
