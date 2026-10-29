"""Synthetic Mac enrollment checks; no Pi, provider, SSH or browser access."""
import hashlib
import io
import json
import socket
from email.message import Message
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from modulate import enroll


DEVICE = "192.168.40.23"
HOST = "192.168.40.24"
CERTIFICATE = b"synthetic peer certificate"
PIN = hashlib.sha256(CERTIFICATE).hexdigest()[:20]
IDENTIFIER = "1" * 32
CODE = "01234567"
DEVICE_V6 = "2001:db8:1234:5678:90ab:cdef:1234:5678"
HOST_V6 = "2001:db8:1234:5678:90ab:cdef:1234:5679"


class DeviceAddressTests(unittest.TestCase):
    def test_ipv4_and_canonical_unscoped_ipv6_are_supported(self):
        self.assertEqual(enroll.device_address(DEVICE), DEVICE)
        self.assertEqual(enroll.device_address(DEVICE_V6.upper()), DEVICE_V6)

    def test_loopback_link_local_multicast_unspecified_scoped_and_mapped_rejected(self):
        for value in ("::1", "::", "fe80::1", "ff02::1", DEVICE_V6 + "%en0", "::ffff:127.0.0.1", "127.0.0.1"):
            with self.subTest(value=value):
                with self.assertRaises(enroll.EnrollmentError):
                    enroll.device_address(value)

    def test_source_route_uses_the_correct_socket_family_without_payload(self):
        for device, host, family in ((DEVICE, HOST, socket.AF_INET), (DEVICE_V6, HOST_V6, socket.AF_INET6)):
            with self.subTest(device=device):
                route = Mock()
                route.getsockname.return_value = (host, 12345)
                context = Mock()
                context.__enter__ = Mock(return_value=route)
                context.__exit__ = Mock(return_value=None)
                with patch.object(enroll.socket, "socket", return_value=context) as factory:
                    self.assertEqual(enroll.mac_address(device), host)
                factory.assert_called_once_with(family, socket.SOCK_DGRAM)
                route.connect.assert_called_once_with((device, 8790))
                route.send.assert_not_called()
                route.sendto.assert_not_called()


class PeerConnection:
    def __init__(self, reply=None, status=200, raw=None):
        self.sock = Mock()
        self.sock.getpeercert.return_value = CERTIFICATE
        self.events = []
        self.reply = {"id": IDENTIFIER, "status": "awaiting_confirmation"} if reply is None else reply
        self.response = Mock(status=status)
        self.response.read.side_effect = lambda limit: (json.dumps(self.reply).encode() if raw is None else raw)[:limit]

    def connect(self):
        self.events.append("connect")

    def request(self, *args):
        self.events.append(("request", args))

    def getresponse(self):
        return self.response

    def close(self):
        self.events.append("close")


class PinnedEnrollmentTests(unittest.TestCase):
    def test_wrong_physical_identity_sends_no_http_or_credentials(self):
        connection = PeerConnection()
        body = {"code": CODE, "enrollment": {"device_key": "private-controller-key"}}
        with patch.object(enroll.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaisesRegex(enroll.EnrollmentError, "Nothing was sent"):
                enroll.pinned_post(DEVICE, "0" * 20, "/enroll", body)
        self.assertEqual(connection.events, ["connect", "close"])
        connection.response.read.assert_not_called()

    def test_matching_identity_sends_only_requested_json_after_handshake(self):
        connection = PeerConnection()
        body = {"id": IDENTIFIER, "code": CODE}
        with patch.object(enroll.http.client, "HTTPSConnection", return_value=connection):
            result = enroll.pinned_post(DEVICE, PIN.upper(), "/status", body)
        self.assertEqual(result, connection.reply)
        self.assertEqual(connection.events[0], "connect")
        method, path, raw, headers = connection.events[1][1]
        self.assertEqual((method, path), ("POST", "/status"))
        self.assertEqual(json.loads(raw), body)
        self.assertEqual(headers, {"Content-Type": "application/json"})
        self.assertEqual(connection.events[-1], "close")

    def test_ipv6_device_uses_the_same_pinned_transport(self):
        connection = PeerConnection()
        with patch.object(enroll.http.client, "HTTPSConnection", return_value=connection) as factory:
            result = enroll.pinned_post(DEVICE_V6.upper(), PIN, "/status", {"id": IDENTIFIER, "code": CODE})
        self.assertEqual(factory.call_args.args, (DEVICE_V6, 8790))
        self.assertEqual(result, connection.reply)
        self.assertEqual(connection.events[0], "connect")

    def test_invalid_address_identity_or_route_never_connects(self):
        with patch.object(enroll.http.client, "HTTPSConnection") as connect:
            for device, pin, path in (("127.0.0.1", PIN, "/enroll"),
                                      ("example.org", PIN, "/enroll"),
                                      (DEVICE, "short", "/enroll"),
                                      (DEVICE, PIN, "/shell")):
                with self.subTest(device=device, path=path, pin=pin):
                    with self.assertRaises(enroll.EnrollmentError):
                        enroll.pinned_post(device, pin, path, {})
            connect.assert_not_called()

    def test_oversized_or_nonfinite_payload_never_connects(self):
        with patch.object(enroll.http.client, "HTTPSConnection") as connect:
            for body in ({"data": "x" * 16385}, {"value": float("nan")}):
                with self.subTest(kind=next(iter(body))):
                    with self.assertRaises(enroll.EnrollmentError):
                        enroll.pinned_post(DEVICE, PIN, "/enroll", body)
            connect.assert_not_called()

    def test_invalid_and_oversized_device_responses_are_rejected(self):
        for raw, status in ((b"x" * 16385, 200), (b"not-json", 200), (b"[]", 200),
                            (b'{"status":"complete"}', 403)):
            with self.subTest(length=len(raw), status=status):
                connection = PeerConnection(raw=raw, status=status)
                with patch.object(enroll.http.client, "HTTPSConnection", return_value=connection):
                    with self.assertRaises(enroll.EnrollmentError):
                        enroll.pinned_post(DEVICE, PIN, "/status", {"id": IDENTIFIER, "code": CODE})
                self.assertEqual(connection.events[-1], "close")


class EnrollmentConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "private"
        self.directory.mkdir(mode=0o700)
        self.path = self.directory / "device-enrollment.json"
        self.certificate = self.directory / "device-cert.pem"
        self.certificate.write_text("-----BEGIN CERTIFICATE-----\nY2VydA==\n-----END CERTIFICATE-----\n")
        self.config = {"host_url": f"https://{HOST}:8788", "device_key": "K" * 43, "ca_file": self.certificate.name}
        self.write()
        self.route = patch.object(enroll, "mac_address", return_value=HOST)
        self.route.start()
        self.addCleanup(self.route.stop)

    def write(self):
        self.path.write_text(json.dumps(self.config))
        self.path.chmod(0o600)

    def make_certificate(self, address=HOST):
        key_path = self.directory / "host-private-key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt",
                        "ec_paramgen_curve:prime256v1", "-nodes", "-days", "1",
                        "-subj", "/CN=Synthetic enrollment test", "-addext", f"subjectAltName=IP:{address}",
                        "-keyout", str(key_path), "-out", str(self.certificate)],
                       check=True, capture_output=True, timeout=10)
        return key_path

    def test_wrong_mac_route_and_unreachable_loopback_origin_rejected(self):
        for url in ("https://192.168.40.99:8788", "http://192.168.40.24:8788",
                    f"https://{HOST}:8787", f"https://{HOST}:8788/other", "https://127.0.0.1:8788"):
            with self.subTest(url=url):
                self.config["host_url"] = url
                self.write()
                with self.assertRaises(enroll.EnrollmentError):
                    enroll.load_enrollment(self.directory, DEVICE)

    def test_certificate_traversal_and_symlink_escape_rejected(self):
        outside = self.directory.parent / "outside.pem"
        outside.write_text(self.certificate.read_text())
        (self.directory / "alias.pem").symlink_to(outside)
        for name in ("../outside.pem", str(outside), "alias.pem"):
            with self.subTest(name=name):
                self.config["ca_file"] = name
                self.write()
                with self.assertRaises(enroll.EnrollmentError):
                    enroll.load_enrollment(self.directory, DEVICE)

    def test_publicly_readable_enrollment_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaises(enroll.EnrollmentError):
            enroll.load_enrollment(self.directory, DEVICE)

    def test_missing_file_is_reported_without_creating_state(self):
        self.path.unlink()
        before = sorted(p.name for p in self.directory.iterdir())
        with self.assertRaises(enroll.EnrollmentError):
            enroll.load_enrollment(self.directory, DEVICE)
        self.assertEqual(sorted(p.name for p in self.directory.iterdir()), before)

    def test_private_key_material_is_not_exported_as_public_certificate(self):
        self.certificate.write_text("-----BEGIN PRIVATE KEY-----\nY2VydA==\n-----END PRIVATE KEY-----\n")
        with self.assertRaises(enroll.EnrollmentError):
            enroll.load_enrollment(self.directory, DEVICE)

    def test_only_controller_key_and_public_certificate_are_exported(self):
        key_path = self.make_certificate()
        self.config["MODEL_API_KEY"] = "synthetic-provider-secret"
        self.write()
        result = enroll.load_enrollment(self.directory, DEVICE)
        self.assertEqual(set(result), {"host_url", "device_key", "ca_pem"})
        self.assertEqual(result["ca_pem"], self.certificate.read_text())
        self.assertNotIn("synthetic-provider-secret", json.dumps(result))
        self.assertNotIn(key_path.read_text(), json.dumps(result))
        self.assertEqual(json.loads(self.path.read_text()), self.config)

    def test_stale_address_certificate_is_rejected_without_export(self):
        self.make_certificate("192.168.40.99")
        with self.assertRaisesRegex(enroll.EnrollmentError, "certificate does not match"):
            enroll.load_enrollment(self.directory, DEVICE)

    def test_zero_exit_with_mismatch_or_unknown_output_still_rejected(self):
        self.make_certificate()
        for output in (f"IP {HOST} does NOT match certificate\n", "", "unrecognized result\n"):
            with self.subTest(output=output):
                result = subprocess.CompletedProcess([], 0, output, "")
                with patch.object(enroll.subprocess, "run", return_value=result):
                    with self.assertRaises(enroll.EnrollmentError):
                        enroll.load_enrollment(self.directory, DEVICE)

    def test_ipv6_origin_and_certificate_match_route(self):
        self.make_certificate(HOST_V6)
        self.config["host_url"] = f"https://[{HOST_V6}]:8788"
        self.write()
        with patch.object(enroll, "mac_address", return_value=HOST_V6):
            result = enroll.load_enrollment(self.directory, DEVICE_V6)
        self.assertEqual(result["host_url"], f"https://[{HOST_V6}]:8788")

    def test_oversized_config_and_certificate_are_rejected(self):
        self.config["unused"] = "x" * 16384
        self.write()
        with self.assertRaises(enroll.EnrollmentError):
            enroll.load_enrollment(self.directory, DEVICE)
        self.config.pop("unused")
        self.write()
        self.certificate.write_text("x" * 8193)
        with self.assertRaises(enroll.EnrollmentError):
            enroll.load_enrollment(self.directory, DEVICE)


class NoWait:
    def __init__(self, count=4):
        self.remaining = count

    def wait(self, _):
        self.remaining -= 1
        return self.remaining < 0


class EnrollmentReceiptTests(unittest.TestCase):
    def run_job(self, replies):
        job = enroll.EnrollmentJob(DEVICE, "/unused")
        job.cancelled = NoWait()
        observed = []
        def post(device, pin, path, body):
            if path == "/enroll":
                return {"id": IDENTIFIER, "status": "awaiting_confirmation"}
            observed.append(job.snapshot())
            self.assertEqual(body, {"id": IDENTIFIER, "code": CODE})
            return replies.pop(0)
        with patch.object(enroll, "load_enrollment", return_value={"host_url": f"https://{HOST}:8788"}), \
             patch.object(enroll, "pinned_post", side_effect=post), \
             patch.object(enroll, "mac_address", return_value=HOST):
            job.run(PIN, CODE)
        return job, observed

    def test_staged_setup_remains_pending_until_exact_matching_completion(self):
        job, observed = self.run_job([
            {"id": IDENTIFIER, "status": "awaiting_confirmation"},
            {"id": IDENTIFIER, "status": "complete"},
        ])
        self.assertEqual([x["status"] for x in observed], ["awaiting_confirmation"] * 2)
        self.assertEqual(job.snapshot()["status"], "complete")
        self.assertNotIn(CODE, json.dumps(observed + [job.snapshot()]))

    def test_wrong_or_missing_receipt_id_cannot_claim_completion(self):
        for reply in ({"id": "2" * 32, "status": "complete"}, {"status": "complete"}):
            with self.subTest(reply=reply):
                job, _ = self.run_job([reply])
                self.assertEqual(job.snapshot()["status"], "error")

    def test_expired_or_rejected_link_is_not_reported_complete(self):
        for status in ("expired", "rejected"):
            with self.subTest(status=status):
                job, _ = self.run_job([{"id": IDENTIFIER, "status": status}])
                self.assertEqual(job.snapshot()["status"], "error")


class LocalEnrollmentPageTests(unittest.TestCase):
    def setUp(self):
        self.job = Mock()
        self.job.snapshot.return_value = {"status": "ready"}
        captured = {}
        def server(address, handler):
            self.assertEqual(address, ("127.0.0.1", 8791))
            captured["handler"] = handler
            instance = Mock()
            instance.serve_forever.side_effect = KeyboardInterrupt
            return instance
        with patch.object(enroll, "HTTPServer", side_effect=server), \
             patch.object(enroll.secrets, "token_urlsafe", side_effect=["csrf-value", "session-value"]), \
             patch("builtins.print"):
            enroll.serve(self.job)
        self.handler = captured["handler"]

    def post(self, *, headers=None, path="/enroll", body=None):
        raw = json.dumps({"fingerprint": PIN, "code": CODE}).encode() if body is None else body
        values = {"Host": "127.0.0.1:8791", "Origin": "http://127.0.0.1:8791",
                  "X-CSRF-Token": "csrf-value", "Cookie": "modulate_setup=session-value",
                  "Content-Type": "application/json", "Content-Length": str(len(raw))}
        values.update(headers or {})
        handler = object.__new__(self.handler)
        handler.headers = Message()
        for key, value in values.items():
            if value is not None:
                handler.headers[key] = value
        handler.path, handler.rfile = path, io.BytesIO(raw)
        handler.send = Mock()
        handler.do_POST()
        return handler.send.call_args.args

    def test_valid_same_origin_page_can_start_setup(self):
        status, _ = self.post()
        self.assertEqual(status, 202)
        self.job.start.assert_called_once_with(PIN, CODE)

    def test_host_origin_csrf_and_cookie_all_required(self):
        variants = ({"Host": "evil.example:8791"}, {"Origin": "https://evil.example"},
                    {"Origin": None}, {"X-CSRF-Token": "wrong"}, {"X-CSRF-Token": None},
                    {"Cookie": None}, {"Cookie": "modulate_setup=wrong"})
        for headers in variants:
            with self.subTest(headers=headers):
                self.assertEqual(self.post(headers=headers)[0], 403)
        self.job.start.assert_not_called()

    def test_local_page_rejects_arbitrary_routes_fields_and_large_requests(self):
        self.assertEqual(self.post(path="/shell")[0], 403)
        self.assertEqual(self.post(body=b'{"fingerprint":"x","code":"01234567","shell":"id"}')[0], 400)
        self.assertEqual(self.post(body=b"x" * 1024)[0], 400)
        self.assertEqual(self.post(headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.job.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
