"""Synthetic speech lifecycle and loopback HTTP tests; no cloud or audio output."""

import base64
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from modulate.agent import AgentError
from modulate.product import Product
from modulate.studio import handler_for
from modulate.tts import ElevenLabsTTS, TTSError
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend


PCM = b"\x01\x00\xff\xff" * 24


class SyntheticSpeech:
    """A controlled provider fixture, deliberately able to return after cancel."""

    def __init__(self, *, block_first=False, error=None, audio=PCM):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block_first = block_first
        self.error = error
        self.audio = audio
        self.calls = []
        self.active = 0
        self.max_active = 0

    def synthesize(self, text, cancel):
        self.calls.append((text, cancel))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            self.entered.set()
            if self.block_first and len(self.calls) == 1:
                if not self.release.wait(2):
                    raise AssertionError("Synthetic test provider was not released")
            if self.error:
                raise self.error
            return self.audio
        finally:
            self.active -= 1


class SpeechDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"MODULATE_TTS_PROVIDER": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.provider = SyntheticProvider([])
        self.product = Product(self.directory, self.provider, backend=FakeBackend(), computer=FakeComputer())
        self.sequence = 0
        self.synthesis = SyntheticSpeech()
        self.product.tts = self.synthesis
        self.product.tts_provider = "elevenlabs"
        self.addCleanup(self.stop_worker)

    def stop_worker(self):
        self.product.cancel()
        self.synthesis.release.set()
        worker = self.product.speech_worker
        if worker:
            worker.join(2)

    def publish(self, text="Synthetic spoken answer", job_id="a" * 32):
        with self.product.lock:
            self.product._publish_response(text, job_id)

    def heartbeat(self, **changes):
        self.sequence += 1
        return self.product.heartbeat({"session": "b" * 32, "sequence": self.sequence,
                                      "name": "Synthetic controller", "revision": None,
                                      "capabilities": {"controls": [], "devices": [], "warnings": []},
                                      "input": {}, **changes})

    def finish(self):
        worker = self.product.speech_worker
        if worker:
            worker.join(2)
            self.assertFalse(worker.is_alive(), "Speech worker did not finish")

    def test_synthesis_does_not_hold_product_lock_or_block_heartbeat(self):
        self.synthesis.block_first = True
        self.publish()
        self.assertTrue(self.synthesis.entered.wait(1))
        acquired = self.product.lock.acquire(timeout=.1)
        self.assertTrue(acquired)
        if acquired:
            self.product.lock.release()
        heartbeat = self.heartbeat()
        self.assertTrue(heartbeat["speech_pending"])
        self.assertIsNone(heartbeat["speech"])
        self.assertTrue(self.product.state()["speech"]["pending"])
        self.synthesis.release.set()
        self.finish()
        message = self.heartbeat()["speech"]
        self.assertEqual(message["audio"]["format"], "pcm_s16le_24000_mono")
        self.assertEqual(message["audio"]["bytes"], len(PCM))
        self.assertEqual(self.product.get_speech_audio(message["id"]), PCM)

    def test_replacement_discards_late_audio_and_keeps_only_latest_pending(self):
        self.synthesis.block_first = True
        self.publish("Old synthetic reply")
        self.assertTrue(self.synthesis.entered.wait(1))
        worker = self.product.speech_worker
        self.publish("Skipped synthetic reply", "c" * 32)
        self.publish("Newest synthetic reply", "d" * 32)
        self.assertIs(self.product.speech_worker, worker)
        self.assertTrue(self.synthesis.calls[0][1].is_set())
        self.assertIsNone(self.product.speech_audio)
        self.synthesis.release.set()
        self.finish()
        self.assertEqual([text for text, _ in self.synthesis.calls],
                         ["Old synthetic reply", "Newest synthetic reply"])
        self.assertEqual(self.synthesis.max_active, 1)
        self.assertEqual(self.product.speech_message["job_id"], "d" * 32)
        self.assertEqual(self.product.speech_message["text"], "Newest synthetic reply")

    def test_cancel_discards_late_result_and_clears_private_response(self):
        self.synthesis.block_first = True
        self.publish()
        self.assertTrue(self.synthesis.entered.wait(1))
        old_stop = self.product.speech_stop_id
        self.product.cancel()
        self.assertTrue(self.synthesis.calls[0][1].is_set())
        self.assertGreater(self.product.speech_stop_id, old_stop)
        self.synthesis.release.set()
        self.finish()
        self.assertIsNone(self.product.response)
        self.assertIsNone(self.product.speech_message)
        self.assertIsNone(self.product.speech_audio)
        self.assertIsNone(self.product.speech_pending)
        self.assertIsNone(self.product.speech_error)

    def test_cancelled_socket_worker_does_not_drop_newest_reply_as_busy(self):
        busy = threading.Event()
        old_socket_done = threading.Event()
        calls = []

        def synthesize(text, cancel):
            calls.append(text)
            if text == "Old reply":
                self.synthesis.entered.set()
                if not cancel.wait(1):
                    raise AssertionError("Old synthetic request was not cancelled")
                raise TTSError("cancelled")
            if not old_socket_done.is_set():
                busy.set()
                raise TTSError("busy")
            return PCM

        self.synthesis.synthesize = synthesize
        self.publish("Old reply")
        self.assertTrue(self.synthesis.entered.wait(1))
        self.publish("New reply", "c" * 32)
        self.assertTrue(busy.wait(1))
        with self.product.lock:
            self.assertEqual(self.product.speech_pending["text"], "New reply")
            self.assertIsNone(self.product.speech_error)
        old_socket_done.set()
        self.finish()
        self.assertEqual(self.product.speech_message["text"], "New reply")
        self.assertEqual(calls.count("Old reply"), 1)

    def test_stop_cancels_waiting_busy_replacement_without_audio_or_fallback(self):
        self.synthesis.error = TTSError("busy")
        self.publish()
        self.assertTrue(self.synthesis.entered.wait(1))
        self.product.speaker_action("stop")
        self.finish()
        self.assertIsNone(self.product.speech_pending)
        self.assertIsNone(self.product.speech_message)
        self.assertIsNone(self.product.speech_audio)

    def test_expired_pending_reply_never_starts_provider_work(self):
        self.synthesis.block_first = True
        with patch("modulate.assistant_io.time.time", return_value=1000):
            self.publish("Old reply")
            self.assertTrue(self.synthesis.entered.wait(1))
            self.publish("Expiring replacement")
        with patch("modulate.assistant_io.time.time", return_value=1121):
            self.synthesis.release.set()
            self.finish()
        self.assertEqual([text for text, _ in self.synthesis.calls], ["Old reply"])
        self.assertIsNone(self.product.speech_pending)
        self.assertIsNone(self.product.speech_message)
        self.assertIsNone(self.product.speech_audio)

    def test_expired_inflight_audio_is_never_published(self):
        self.synthesis.block_first = True
        with patch("modulate.assistant_io.time.time", return_value=1000):
            self.publish()
            self.assertTrue(self.synthesis.entered.wait(1))
        with patch("modulate.assistant_io.time.time", return_value=1121):
            self.synthesis.release.set()
            self.finish()
        self.assertIsNone(self.product.speech_message)
        self.assertIsNone(self.product.speech_audio)

    def test_exact_ack_clears_delivery_metadata_but_keeps_fetchable_audio(self):
        self.publish()
        self.finish()
        message = self.heartbeat()["speech"]
        self.assertEqual(self.heartbeat(speech_ack="c" * 32)["speech"]["id"], message["id"])
        self.assertIsNone(self.heartbeat(speech_ack=message["id"])["speech"])
        self.assertEqual(self.product.get_speech_audio(message["id"]), PCM)
        self.assertIsNone(self.heartbeat()["speech"])
        self.product.speaker_action("stop")
        with self.assertRaises(AgentError):
            self.product.get_speech_audio(message["id"])

    def test_old_ack_or_fetch_cannot_remove_or_read_new_reply(self):
        self.publish("Old reply")
        self.finish()
        old_id = self.product.speech_message["id"]
        self.publish("New reply")
        self.finish()
        current_id = self.product.speech_message["id"]
        self.assertNotEqual(current_id, old_id)
        self.assertEqual(self.heartbeat(speech_ack=old_id)["speech"]["id"], current_id)
        with self.assertRaises(AgentError):
            self.product.get_speech_audio(old_id)
        self.assertEqual(self.product.get_speech_audio(current_id), PCM)

    def test_expired_audio_is_removed_and_identifiers_are_bounded(self):
        with patch("modulate.assistant_io.time.time", return_value=1000):
            self.publish()
            self.finish()
        identifier = self.product.speech_message["id"]
        with patch("modulate.assistant_io.time.time", return_value=1001):
            for bad in (None, {}, 1, "", "../audio", identifier.upper(), identifier + "a"):
                with self.subTest(identifier=bad), self.assertRaises(AgentError):
                    self.product.get_speech_audio(bad)
        with patch("modulate.assistant_io.time.time", return_value=1121):
            with self.assertRaises(AgentError):
                self.product.get_speech_audio(identifier)
            self.assertIsNone(self.product.speech_audio)
            self.assertIsNone(self.heartbeat()["speech"])

    def test_provider_failure_exposes_generic_error_without_local_fallback(self):
        self.synthesis.error = RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_PAYLOAD")
        self.publish("Synthetic text remains readable")
        self.finish()
        result = self.heartbeat()
        self.assertIsNone(result["speech"])
        self.assertIsNone(self.product.speech_audio)
        self.assertIn("ElevenLabs", result["speech_error"])
        self.assertNotIn("SYNTHETIC_PRIVATE_PROVIDER_PAYLOAD", json.dumps(result))
        self.assertEqual(self.product.response["text"], "Synthetic text remains readable")
        self.assertEqual(len(self.synthesis.calls), 1)
        self.assertEqual(self.product.speech_status()["provider"], "elevenlabs")

    def test_unconfigured_elevenlabs_does_not_send_text_for_local_synthesis(self):
        self.product.tts = ElevenLabsTTS(self.directory, api_key="", voice_id="")
        self.publish()
        self.finish()
        self.assertIsNone(self.heartbeat()["speech"])
        self.assertIsNone(self.product.speech_audio)
        self.assertIsNotNone(self.product.speech_error)
        self.assertFalse((self.directory / "tts-character-ledger.json").exists())

    def test_bad_provider_audio_is_never_delivered(self):
        for bad in (b"", b"a", "synthetic", b"\x00" * 4_320_002):
            with self.subTest(size=len(bad)):
                self.synthesis.audio = bad
                self.publish()
                self.finish()
                self.assertIsNone(self.product.speech_message)
                self.assertIsNone(self.product.speech_audio)
                self.assertIsNotNone(self.product.speech_error)

    def test_text_and_audio_are_transient_even_when_character_ledger_is_saved(self):
        private_text = "SYNTHETIC_PRIVATE_SPOKEN_ANSWER"
        audio = b"SYNTHETIC_PRIVATE_PCM_SAMPLE!" * 2

        class Response(io.BytesIO):
            status = 200
            headers = {"Content-Type": "audio/pcm"}

            def getcode(self):
                return 200

            def geturl(self):
                return "https://api.elevenlabs.io/v1/text-to-speech/test-voice/stream?output_format=pcm_24000"

        class Opener:
            def open(self, request, timeout):
                return Response(audio)

        self.product.tts = ElevenLabsTTS(self.directory, api_key="synthetic-test-only",
                                        voice_id="test-voice", opener=Opener())
        self.publish(private_text)
        self.finish()
        self.assertEqual(self.product.get_speech_audio(self.product.speech_message["id"]), audio)
        self.product.progress.update(job_id="a" * 32, job_sequence=1)
        self.product._save_job()
        self.assertTrue((self.directory / "tts-character-ledger.json").exists())
        for path in self.directory.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                for marker in (private_text.encode(), audio, base64.b64encode(audio), b"synthetic-test-only"):
                    self.assertNotIn(marker, data, str(path))
        self.assertNotIn(private_text, json.dumps(list(self.product.events)))
        reopened = Product(self.directory, self.provider, backend=FakeBackend(), computer=FakeComputer())
        self.assertIsNone(reopened.response)
        self.assertIsNone(reopened.speech_message)
        self.assertIsNone(reopened.speech_audio)


class SpeechEndpointTests(unittest.TestCase):
    """HTTP auth/routing only; no claim about a real pinned TLS connection."""

    def start(self, **options):
        class SpeechProduct:
            def __init__(self):
                self.calls = []

            def get_speech_audio(self, identifier):
                self.calls.append(identifier)
                if identifier != "a" * 32:
                    raise AgentError("That spoken reply is no longer available")
                return PCM

        product = SpeechProduct()
        server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        server.daemon_threads = True
        port = server.server_address[1]
        server.RequestHandlerClass = handler_for(product, port=port, **options)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(1)

        self.addCleanup(stop)
        return product, port

    def request(self, port, *, method="POST", headers=None, body=None):
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request(method, "/device/speech", body=body if body is not None else json.dumps({"id": "a" * 32}),
                               headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_binary_speech_requires_exact_device_key_and_peer(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        good = {"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"}
        for authorization in (None, "Bearer wrong", "synthetic-device"):
            headers = {"Content-Type": "application/json"}
            if authorization:
                headers["Authorization"] = authorization
            self.assertEqual(self.request(port, headers=headers)[0], 403)
        self.assertEqual(product.calls, [])
        status, headers, data = self.request(port, headers=good)
        self.assertEqual((status, data), (200, PCM))
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(int(headers["Content-Length"]), len(PCM))
        self.assertEqual(self.request(port, method="GET", headers=good)[0], 403)
        other, wrong_peer_port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.2")
        self.assertEqual(self.request(wrong_peer_port, headers=good)[0], 403)
        self.assertEqual(other.calls, [])
        empty, empty_port = self.start(device=True, peer="127.0.0.1")
        self.assertEqual(self.request(empty_port, headers=good)[0], 403)
        self.assertEqual(empty.calls, [])

    def test_browser_session_cannot_fetch_audio_even_with_device_bearer(self):
        product, port = self.start(cookie="synthetic-session", csrf="synthetic-csrf")
        headers = {"Authorization": "Bearer synthetic-device", "Content-Type": "application/json",
                   "Origin": f"http://127.0.0.1:{port}", "Cookie": "modulate=synthetic-session",
                   "X-CSRF-Token": "synthetic-csrf"}
        self.assertEqual(self.request(port, headers=headers)[0], 404)
        self.assertEqual(self.request(port, method="GET", headers=headers)[0], 404)
        self.assertEqual(product.calls, [])

    def test_unavailable_id_and_invalid_body_do_not_return_audio(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        headers = {"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"}
        for body in ("{}", '{"id":"stale"}', '[]', '{"id":"a","id":"b"}'):
            with self.subTest(body=body):
                status, _, data = self.request(port, headers=headers, body=body)
                self.assertEqual(status, 400)
                self.assertNotIn(PCM, data)
        self.assertEqual(self.request(port, headers={**headers, "Content-Type": "text/plain"})[0], 413)


if __name__ == "__main__":
    unittest.main()
