import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from modulate.device_transport import Companion, NoRedirect, TransportError, save_private


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
        response.read.return_value = b"x" * (256 * 1024 + 1)
        with self.assertRaises(TransportError):
            client.post("heartbeat", {})

    def test_network_error_does_not_echo_credential(self):
        client = self.client()
        client.opener.open.side_effect = urllib.error.URLError("Bearer " + self.config["device_key"])
        with self.assertRaisesRegex(TransportError, "Companion unavailable") as captured:
            client.post("heartbeat", {})
        self.assertNotIn(self.config["device_key"], str(captured.exception))


if __name__ == "__main__":
    unittest.main()
