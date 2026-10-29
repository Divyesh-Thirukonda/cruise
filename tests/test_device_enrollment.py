"""Offline enrollment state/security checks plus real local TLS ingress."""
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from modulate.device_enrollment import EnrollmentError, EnrollmentServer, MAX_ATTEMPTS, WINDOW_SECONDS


class DeviceEnrollmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cert_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.cert_dir.cleanup)
        root = Path(cls.cert_dir.name)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-days", "2", "-subj", "/CN=Modulate companion", "-addext",
                        "subjectAltName=IP:192.168.1.2,IP:127.0.0.1,IP:::1,IP:2001:db8::2", "-keyout", str(root / "key.pem"),
                        "-out", str(root / "cert.pem")], check=True, capture_output=True)
        cls.pem = (root / "cert.pem").read_text()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "device-enrollment.json"
        self.now = 100.0
        self.server = EnrollmentServer(self.root / "setup", self.path, port=0,
                                       clock=lambda: self.now, address="192.168.1.3")
        self.assertTrue(self.server.start())
        self.addCleanup(self.server.close)
        self.data = {"host_url": "https://192.168.1.2:8788", "device_key": "x" * 43, "ca_pem": self.pem}
        self.peer = "192.168.1.2"

    def open(self):
        return self.server.open_window()["code"]

    def propose(self, code=None, data=None, peer=None):
        return self.server.propose({"code": code or self.code, "enrollment": data or self.data}, peer or self.peer)

    def receipt(self, proposal, code=None):
        return {"id": proposal["id"], "code": code or self.code}

    def test_unarmed_cannot_accept_and_existing_invalid_enrollment_is_never_replaced(self):
        with self.assertRaises(EnrollmentError):
            self.propose(code="12345678")
        self.path.write_bytes(b"corrupt but preserve")
        self.assertFalse(self.server.snapshot()["available"])
        self.assertNotIn("code", self.server.open_window())
        with self.assertRaises(EnrollmentError):
            self.propose(code="12345678")
        self.assertEqual(self.path.read_bytes(), b"corrupt but preserve")
        another = EnrollmentServer(self.root / "other", self.path, port=0)
        self.assertFalse(another.start())
        self.assertFalse((self.root / "other").exists())

    def test_attempt_limit_is_global_and_only_physical_open_resets_it(self):
        self.code = self.open()
        bad = "00000000" if self.code != "00000000" else "00000001"
        for _ in range(MAX_ATTEMPTS):
            with self.assertRaises(EnrollmentError):
                self.propose(code=bad)
        self.assertNotIn("code", self.server.snapshot())
        with self.assertRaises(EnrollmentError):
            self.propose()
        self.code = self.open()
        self.assertEqual(self.propose()["status"], "awaiting_confirmation")

    def test_pending_requires_exact_fresh_confirmation_then_private_files_and_receipt(self):
        self.code = self.open()
        proposal = self.propose()
        self.assertFalse(self.path.exists())
        self.assertFalse(self.server.confirm("a" * 32))
        self.assertEqual(self.server.status(self.receipt(proposal), self.peer)["status"], "awaiting_confirmation")
        self.assertTrue(self.server.confirm(proposal["id"]))
        config = json.loads(self.path.read_text())
        self.assertEqual(config["host_url"], self.data["host_url"])
        self.assertEqual(config["device_key"], self.data["device_key"])
        cert = self.root / config["ca_file"]
        self.assertEqual(cert.read_text(), self.pem)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(cert.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.server.status(self.receipt(proposal), self.peer)["status"], "complete")
        self.assertFalse(self.server.snapshot()["available"])
        self.assertNotIn("code", self.server.snapshot())
        self.assertFalse(self.server.confirm(proposal["id"]))
        with self.assertRaises(EnrollmentError):
            self.propose()
        with self.assertRaises(EnrollmentError):
            self.server.status(self.receipt(proposal), "192.168.1.99")
        self.now += WINDOW_SECONDS
        with self.assertRaises(EnrollmentError):
            self.server.status(self.receipt(proposal), self.peer)

    def test_expiry_and_cancel_never_write_pending_credentials(self):
        self.code = self.open()
        proposal = self.propose()
        self.now += WINDOW_SECONDS
        self.assertFalse(self.server.confirm(proposal["id"]))
        self.assertEqual(self.server.status(self.receipt(proposal), self.peer)["status"], "expired")
        self.assertFalse(self.path.exists())
        self.code = self.open()
        proposal = self.propose()
        self.server.close_window()
        self.assertEqual(self.server.status(self.receipt(proposal), self.peer)["status"], "rejected")
        self.assertFalse(self.server.confirm(proposal["id"]))
        self.assertFalse(self.path.exists())

    def test_reopen_invalidates_old_pending_request_and_code(self):
        self.code = self.open()
        proposal = self.propose()
        old_code = self.code
        self.code = self.open()
        self.assertFalse(self.server.confirm(proposal["id"]))
        with self.assertRaises(EnrollmentError):
            self.server.status(self.receipt(proposal, old_code), self.peer)
        self.assertFalse(self.path.exists())

    def test_wrong_peer_invalid_origin_paths_or_provider_fields_are_rejected(self):
        invalid = [
            {**self.data, "host_url": "http://192.168.1.2:8788"},
            {**self.data, "host_url": "https://localhost:8788"},
            {**self.data, "host_url": "https://127.0.0.1:8788"},
            {**self.data, "host_url": "https://169.254.2.1:8788"},
            {**self.data, "host_url": "https://0.0.0.0:8788"},
            {**self.data, "host_url": "https://224.0.0.1:8788"},
            {**self.data, "host_url": "https://192.168.1.2:8787"},
            {**self.data, "host_url": "https://192.168.1.2:8788/device/heartbeat"},
            {**self.data, "host_url": "https://192.168.1.2:8788/?x=1"},
            {**self.data, "host_url": "https://user:pass@192.168.1.2:8788"},
            {**self.data, "device_key": "tiny"},
            {**self.data, "device_key": "x" * 200},
            {**self.data, "ca_file": "../../authorized_keys"},
            {**self.data, "MODEL_API_KEY": "should-not-be-here"},
            {**self.data, "command": "run me"},
        ]
        for data in invalid:
            with self.subTest(data=list(data)):
                self.code = self.open()
                with self.assertRaises(EnrollmentError):
                    self.propose(data=data)
                self.assertFalse(self.path.exists())
        self.code = self.open()
        with self.assertRaises(EnrollmentError):
            self.propose(peer="192.168.1.99")
        self.assertNotIn("pending", self.server.snapshot())

    def test_wrong_san_and_malformed_certificate_are_rejected_before_staging(self):
        for pem in ("not a cert", self.pem + self.pem, self.pem.replace("CERTIFICATE", "PRIVATE KEY")):
            self.code = self.open()
            with self.assertRaises(EnrollmentError):
                self.propose(data={**self.data, "ca_pem": pem})
        self.code = self.open()
        with self.assertRaises(EnrollmentError):
            self.propose(data={**self.data, "host_url": "https://192.168.1.99:8788"}, peer="192.168.1.99")
        self.assertNotIn("pending", self.server.snapshot())

    def test_zero_exit_mismatching_or_missing_openssl_result_never_authorizes(self):
        # Linux's deployed OpenSSL can return 0 for a negative -checkip result.
        # A successful process is not evidence that the certificate matched.
        outputs = (b"IP 192.168.1.99 does NOT match certificate\n", b"",
                   b"IP 192.168.1.2 does match certificate\n",
                   b"unexpected output\n")
        for output in outputs:
            with self.subTest(output=output):
                self.code = self.open()
                completed = subprocess.CompletedProcess(["openssl"], 0, stdout=output, stderr=b"")
                with patch("modulate.device_enrollment.subprocess.run", return_value=completed):
                    with self.assertRaises(EnrollmentError):
                        self.propose(data={**self.data, "host_url": "https://192.168.1.99:8788"},
                                     peer="192.168.1.99")
                self.assertFalse(self.path.exists())
                self.assertNotIn("pending", self.server.snapshot())

    def test_atomic_commit_refuses_concurrent_target_and_leaves_no_orphan_cert(self):
        self.code = self.open()
        proposal = self.propose()
        original_link = os.link
        def race(src, dst):
            self.path.write_bytes(b"keep concurrent enrollment")
            original_link(src, dst)
        with patch("modulate.device_enrollment.os.link", side_effect=race):
            self.assertFalse(self.server.confirm(proposal["id"]))
        self.assertEqual(self.path.read_bytes(), b"keep concurrent enrollment")
        self.assertEqual(list(self.root.glob("enrolled-cert-*.pem")), [])
        self.assertEqual(list(self.root.glob(".enrollment-*")), [])

    def test_disk_failure_preserves_other_files_and_does_not_claim_success(self):
        (self.root / "saved-app.json").write_bytes(b"keep")
        self.code = self.open()
        proposal = self.propose()
        with patch("modulate.device_enrollment.os.link", side_effect=OSError("disk full")):
            self.assertFalse(self.server.confirm(proposal["id"]))
        self.assertFalse(self.path.exists())
        self.assertEqual((self.root / "saved-app.json").read_bytes(), b"keep")
        self.assertEqual(self.server.status(self.receipt(proposal), self.peer)["status"], "rejected")

    def test_pending_request_cannot_be_swapped_by_a_second_proposal(self):
        self.code = self.open()
        proposal = self.propose()
        with self.assertRaises(EnrollmentError):
            self.propose(data={**self.data, "device_key": "y" * 43})
        self.assertTrue(self.server.confirm(proposal["id"]))
        self.assertEqual(json.loads(self.path.read_text())["device_key"], self.data["device_key"])

    def connection(self, address="127.0.0.1"):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(address, self.server.port, context=context, timeout=3)
        connection.connect()
        self.addCleanup(connection.close)
        fingerprint = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()[:20]
        self.assertEqual(fingerprint, self.server.snapshot()["fingerprint"])
        return connection

    def test_real_tls_rejects_unknown_action_and_malformed_duplicate_json(self):
        self.code = self.open()
        connection = self.connection()
        connection.request("POST", "/shell", b"{}", {"Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 404)
        self.assertNotIn(self.code.encode(), response.read())
        connection = self.connection()
        connection.request("POST", "/enroll", b'{"code":"one","code":"two"}', {"Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        self.assertNotIn(self.data["device_key"].encode(), response.read())
        self.assertEqual(self.server.attempts, 1)
        self.assertFalse(self.path.exists())

    def test_real_tls_code_auth_and_bounded_body(self):
        self.code = self.open()
        connection = self.connection()
        connection.request("POST", "/enroll", json.dumps({"code": "bad", "enrollment": self.data}),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection = self.connection()
        connection.request("POST", "/enroll", b"x" * 16385, {"Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        self.assertEqual(self.server.attempts, 2)

    def test_real_tls_end_to_end_requires_physical_confirmation(self):
        # Loopback is a transport fixture only; production rejects it separately.
        from modulate.device_enrollment import usable_address
        def fixture_address(value):
            return "127.0.0.1" if value == "127.0.0.1" else usable_address(value)
        self.code = self.open()
        with patch("modulate.device_enrollment.usable_address", side_effect=fixture_address):
            connection = self.connection()
            connection.request("POST", "/enroll", json.dumps({"code": self.code, "enrollment": {
                **self.data, "host_url": "https://127.0.0.1:8788"}}), {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            proposal = json.loads(response.read())
            self.assertEqual(proposal["status"], "awaiting_confirmation")
            self.assertFalse(self.path.exists())
            self.assertTrue(self.server.confirm(proposal["id"]))
            connection = self.connection()
            connection.request("POST", "/status", json.dumps(self.receipt(proposal)), {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {"id": proposal["id"], "status": "complete"})

    def test_ipv6_tls_round_trip_and_bracketed_companion_origin(self):
        if self.server.server.address_family != socket.AF_INET6:
            self.skipTest("Dual-stack IPv6 is unavailable")
        from modulate.device_enrollment import usable_address
        def fixture_address(value):
            return "::1" if value == "::1" else usable_address(value)
        self.code = self.open()
        with patch("modulate.device_enrollment.usable_address", side_effect=fixture_address):
            try:
                connection = self.connection("::1")
            except OSError:
                self.skipTest("IPv6 loopback is unavailable")
            connection.request("POST", "/enroll", json.dumps({"code": self.code, "enrollment": {
                **self.data, "host_url": "https://[::1]:8788"}}), {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            proposal = json.loads(response.read())
            self.assertEqual(proposal["status"], "awaiting_confirmation")
            self.assertTrue(self.server.confirm(proposal["id"]))
            connection = self.connection("::1")
            connection.request("POST", "/status", json.dumps(self.receipt(proposal)), {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {"id": proposal["id"], "status": "complete"})
        self.assertEqual(json.loads(self.path.read_text())["host_url"], "https://[::1]:8788")

    def test_mapped_ipv4_peers_match_but_mapped_loopback_is_still_rejected(self):
        from modulate.device_enrollment import usable_address
        self.assertEqual(usable_address("::ffff:192.168.1.2"), "192.168.1.2")
        for invalid in ("::ffff:127.0.0.1", "2001:db8::2%en0", "::ffff:192.168.1.2%en0"):
            with self.subTest(address=invalid), self.assertRaises(EnrollmentError):
                usable_address(invalid)
        self.code = self.open()
        proposal = self.propose(peer="::ffff:192.168.1.2")
        self.assertEqual(self.server.status(self.receipt(proposal), "::ffff:192.168.1.2")["status"],
                         "awaiting_confirmation")
        self.assertTrue(self.server.confirm(proposal["id"]))
        self.assertEqual(self.server.status(self.receipt(proposal), "::ffff:192.168.1.2")["status"], "complete")

    def test_network_discovery_prefers_global_ipv6_then_usable_ipv4(self):
        from modulate.device_enrollment import local_address
        with patch("modulate.device_enrollment.socket.getaddrinfo", return_value=[]):
            for addresses, expected in (
                ("100.64.0.2 2606:4700:4700::1111 ", "2606:4700:4700::1111"),
                ("fe80::1234 192.168.1.3 fd00::3", "192.168.1.3"),
                ("127.0.0.1 ::ffff:192.168.1.3", "192.168.1.3"),
                ("::1 fe80::3", None),
            ):
                result = subprocess.CompletedProcess(["hostname", "-I"], 0, stdout=addresses, stderr="")
                with self.subTest(addresses=addresses), patch("modulate.device_enrollment.subprocess.run", return_value=result):
                    self.assertEqual(local_address(), expected)
            result = subprocess.CompletedProcess(["hostname", "-I"], 0,
                        stdout="100.64.0.2 2606:4700:4700::1111", stderr="")
            with patch("modulate.device_enrollment.subprocess.run", return_value=result):
                self.assertEqual(local_address(socket.AF_INET), "100.64.0.2")

    def test_ipv4_listener_fallback_when_ipv6_is_not_supported(self):
        self.server.close()
        with patch("modulate.device_enrollment._IPv6Server", side_effect=OSError("No IPv6")):
            self.assertTrue(self.server.start())
        self.assertEqual(self.server.server.address_family, socket.AF_INET)
        connection = self.connection()
        connection.request("GET", "/")
        response = connection.getresponse()
        self.assertEqual(response.status, 404)
        response.read()

    def test_missing_network_recovers_on_physical_retry_without_restart(self):
        self.server.address_override = None
        with patch("modulate.device_enrollment.local_address", return_value=None):
            self.assertNotIn("code", self.server.open_window())
        with patch("modulate.device_enrollment.local_address", return_value="192.168.1.3"):
            snapshot = self.server.open_window()
        self.assertEqual(snapshot["address"], "192.168.1.3")
        self.assertIn("code", snapshot)

    def test_certificate_name_collision_never_deletes_preexisting_file(self):
        self.code = self.open()
        proposal = self.propose()
        existing = self.root / ("enrolled-cert-" + "a" * 32 + ".pem")
        existing.write_bytes(b"keep other certificate")
        with patch("modulate.device_enrollment.secrets.token_hex", return_value="a" * 32):
            self.assertFalse(self.server.confirm(proposal["id"]))
        self.assertEqual(existing.read_bytes(), b"keep other certificate")
        self.assertFalse(self.path.exists())

    def test_setup_identity_persists_but_codes_do_not_survive_restart(self):
        fingerprint = self.server.snapshot()["fingerprint"]
        self.open()
        port = self.server.port
        self.server.close()
        self.server = EnrollmentServer(self.root / "setup", self.path, port=port, address="192.168.1.3")
        self.addCleanup(self.server.close)
        self.assertTrue(self.server.start())
        self.assertEqual(self.server.snapshot()["fingerprint"], fingerprint)
        self.assertNotIn("code", self.server.snapshot())


if __name__ == "__main__":
    unittest.main()
