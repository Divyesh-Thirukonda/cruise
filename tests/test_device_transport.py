import json
import hashlib
import http.client
import io
from email.message import Message
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from modulate.device_transport import (Companion, NoRedirect, TransportError, save_private,
                                       SPEECH_FORMAT, MAX_SPEECH_BYTES)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "enrollment.json"
        self.config = {"host_url": "https://127.0.0.1:8788", "device_key": "x" * 40, "ca_file": "cert.pem"}
        save_private(self.path, self.config)

    def tearDown(self):
        self.directory.cleanup()

    def client(self):
        with patch("modulate.device_transport.ssl.SSLContext"), patch("modulate.device_transport.urllib.request.build_opener"):
            return Companion(self.path)

    def audio_response(self, payload=b"\x01\x00" * 100, descriptor=None):
        client = self.client()
        descriptor = descriptor or {"id": "a" * 32, "format": SPEECH_FORMAT, "bytes": len(payload),
                                    "sha256": hashlib.sha256(payload).hexdigest()}
        response = client.opener.open.return_value.__enter__.return_value
        response.geturl.return_value = client.origin + "/device/speech"
        response.headers = Message()
        response.headers["Content-Type"] = "application/octet-stream"
        response.headers["Content-Length"] = str(descriptor["bytes"])
        response.headers["X-Modulate-Audio-Format"] = SPEECH_FORMAT
        response.read.side_effect = io.BytesIO(payload).read
        return client, descriptor, response

    def test_private_configuration_required(self):
        self.path.chmod(0o644)
        with self.assertRaises(TransportError):
            Companion(self.path)

    def test_only_enrolled_https_origin(self):
        for url in ("http://127.0.0.1", "https://host/?key=x", "https://user:pass@host", "https://host/other", "https://host/#x"):
            save_private(self.path, {**self.config, "host_url": url})
            with self.subTest(url=url), self.assertRaises(TransportError):
                self.client()

    def test_no_redirect_can_forward_authorization(self):
        with self.assertRaises(TransportError):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid")

    def test_certificate_verification_not_disabled_and_proxies_not_used(self):
        with patch("modulate.device_transport.ssl.SSLContext") as tls, patch("modulate.device_transport.urllib.request.build_opener"), patch("modulate.device_transport.urllib.request.ProxyHandler") as proxy:
            Companion(self.path)
            tls.return_value.load_verify_locations.assert_called_once_with(cafile=str(self.path.resolve().parent / "cert.pem"))
            proxy.assert_called_once_with({})
            self.assertNotIn("verify_mode", tls.return_value.__dict__)

    def test_action_allowlist_and_payload_limit(self):
        client = self.client()
        with self.assertRaises(TransportError):
            client.post("../admin", {})
        with self.assertRaises(TransportError):
            client.post("request", {"text": "x" * 300_000})
        client.opener.open.assert_not_called()

    def test_bounded_response_and_authenticated_origin(self):
        client = self.client()
        response = client.opener.open.return_value.__enter__.return_value
        response.read.return_value = b'{"accepted":true}'
        self.assertTrue(client.post("request", {"text": "build a game"})["accepted"])
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://127.0.0.1:8788/device/request")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + "x" * 40)
        response.read.return_value = b"x" * (1024 * 1024 + 1)
        with self.assertRaises(TransportError):
            client.post("heartbeat", {})

    def test_network_error_does_not_echo_credential(self):
        client = self.client()
        client.opener.open.side_effect = urllib.error.URLError("Bearer " + self.config["device_key"])
        with self.assertRaisesRegex(TransportError, "Companion unavailable") as captured:
            client.post("heartbeat", {})
        self.assertNotIn(self.config["device_key"], str(captured.exception))

    def test_speech_audio_uses_only_enrolled_authenticated_post_and_verifies_bytes(self):
        payload = b"\x01\x00" * 80_000
        client, descriptor, response = self.audio_response(payload)
        self.assertEqual(client.speech_audio(descriptor, threading.Event()), payload)
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, client.origin + "/device/speech")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"id": descriptor["id"]})
        self.assertEqual(request.get_header("Authorization"), "Bearer " + self.config["device_key"])
        self.assertEqual(client.opener.open.call_args.kwargs, {"timeout": 3})
        self.assertTrue(all(0 < call.args[0] <= 65_536 for call in response.read.call_args_list))

    def test_invalid_speech_descriptor_never_opens_network(self):
        client, valid, _ = self.audio_response()
        changes = [{"id": "../other"}, {"format": "mp3"}, {"bytes": True}, {"bytes": 0},
                   {"bytes": 3}, {"bytes": MAX_SPEECH_BYTES + 2}, {"sha256": "wrong"},
                   {"url": "https://elsewhere.invalid/private"}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(TransportError):
                client.speech_audio({**valid, **change}, threading.Event())
        client.opener.open.assert_not_called()

    def test_audio_rejects_hash_length_format_and_redirect_mismatches(self):
        for change in ("hash", "short", "long", "header_length", "content_type", "format", "redirect"):
            with self.subTest(change=change):
                client, descriptor, response = self.audio_response()
                if change == "hash":
                    response.read.side_effect = io.BytesIO(b"\x02\x00" * 100).read
                elif change == "short":
                    response.read.side_effect = io.BytesIO(b"\x01\x00" * 99).read
                elif change == "long":
                    response.read.side_effect = io.BytesIO(b"\x01\x00" * 101).read
                elif change == "header_length":
                    response.headers.replace_header("Content-Length", "999")
                elif change == "content_type":
                    response.headers.replace_header("Content-Type", "audio/mpeg")
                elif change == "format":
                    response.headers.replace_header("X-Modulate-Audio-Format", "pcm_s16be_48000_stereo")
                else:
                    response.geturl.return_value = "https://elsewhere.invalid/speech"
                with self.assertRaises(TransportError):
                    client.speech_audio(descriptor, threading.Event())

    def test_audio_auth_and_expiry_errors_do_not_read_private_error_bodies(self):
        for code in (401, 403, 404, 410):
            with self.subTest(code=code):
                client, descriptor, _ = self.audio_response()
                private = io.BytesIO(b"PRIVATE_PROVIDER_RESPONSE_AND_CREDENTIAL")
                private.read = MagicMock(wraps=private.read)
                client.opener.open.side_effect = urllib.error.HTTPError(client.origin, code, "private", {}, private)
                with self.assertRaisesRegex(TransportError, str(code)) as raised:
                    client.speech_audio(descriptor, threading.Event())
                self.assertNotIn("PRIVATE", str(raised.exception))
                private.read.assert_not_called()
                self.assertTrue(private.closed)

    def test_audio_cancellation_before_request_and_between_bounded_reads(self):
        cancel = threading.Event()
        client, descriptor, response = self.audio_response(b"\x01\x00" * 80_000)
        cancel.set()
        with self.assertRaisesRegex(TransportError, "cancelled"):
            client.speech_audio(descriptor, cancel)
        client.opener.open.assert_not_called()
        cancel.clear()
        read = response.read.side_effect
        def interrupted(size):
            cancel.set()
            return read(size)
        response.read.side_effect = interrupted
        with self.assertRaisesRegex(TransportError, "cancelled"):
            client.speech_audio(descriptor, cancel)
        self.assertEqual(response.read.call_count, 1)
        client.opener.open.return_value.__exit__.assert_called_once()

    def test_audio_deadline_and_network_errors_are_bounded_and_generic(self):
        client, descriptor, _ = self.audio_response()
        with patch("modulate.device_transport.time.monotonic", side_effect=[0, 91]):
            with self.assertRaisesRegex(TransportError, "timed out"):
                client.speech_audio(descriptor, threading.Event())
        client.opener.open.side_effect = urllib.error.URLError(self.config["device_key"])
        with self.assertRaises(TransportError) as raised:
            client.speech_audio(descriptor, threading.Event())
        self.assertNotIn(self.config["device_key"], str(raised.exception))

    def test_truncated_http_audio_does_not_expose_partial_private_bytes(self):
        client, descriptor, response = self.audio_response()
        response.read.side_effect = http.client.IncompleteRead(b"PRIVATE_AUDIO_PAYLOAD", 200)
        with self.assertRaises(TransportError) as raised:
            client.speech_audio(descriptor, threading.Event())
        self.assertNotIn("PRIVATE", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
