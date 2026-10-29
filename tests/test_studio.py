"""Loopback HTTP handler tests using synthetic credentials and a fake product.

These exercise authorization and routing, not a real TLS device connection.
"""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from modulate.studio import handler_for


class FakeProduct:
    def __init__(self):
        self.calls = []
        self.wake = True
        self.preview_bytes = b"live-test-image"
        self.candidate_preview_bytes = b"candidate-test-image"

    def state(self):
        return {"synthetic": True}

    def request(self, text, source="website"):
        self.calls.append(("request", text, source))
        return {"accepted": True, "source": source, "job_id": "a" * 32}

    def cancel(self):
        self.calls.append(("cancel",))
        return {"cancelled": True}

    def heartbeat(self, data):
        self.calls.append(("heartbeat", data))
        return {"accepted": True}

    def create_pairing(self):
        self.calls.append(("create_pairing",))
        return {"code": "12345678", "expires_at": 12345}

    def pair(self, code, name):
        self.calls.append(("pair", code, name))
        return {"paired": True}

    def revoke(self):
        self.calls.append(("revoke",))
        return {"revoked": True}

    def rollback(self):
        self.calls.append(("rollback",))
        return {"accepted": True}


class StudioTests(unittest.TestCase):
    def start(self, **options):
        product = FakeProduct()
        server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        server.daemon_threads = True
        port = server.server_address[1]
        server.RequestHandlerClass = handler_for(product, port=port, **options)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        self.addCleanup(stop)
        return product, port

    def request(self, port, path, *, method="GET", body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def headers(self, port, **changes):
        headers = {"Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": "synthetic-csrf",
                   "Cookie": "modulate=synthetic-session", "Content-Type": "application/json"}
        headers.update(changes)
        return headers

    def test_browser_mutations_require_origin_cookie_and_csrf_together(self):
        product, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        good = self.headers(port)
        for missing in ("Origin", "X-CSRF-Token", "Cookie"):
            headers = {key: value for key, value in good.items() if key != missing}
            status, _, _ = self.request(port, "/api/cancel", method="POST", body="{}", headers=headers)
            self.assertEqual(status, 403)
        for changes in ({"Origin": "https://other.example"}, {"X-CSRF-Token": "wrong"},
                        {"Cookie": "modulate=wrong"}, {"Host": "other.example"}):
            status, _, _ = self.request(port, "/api/cancel", method="POST", body="{}", headers={**good, **changes})
            self.assertEqual(status, 403)
        self.assertEqual(product.calls, [])
        status, _, _ = self.request(port, "/api/cancel", method="POST", body="{}", headers=good)
        self.assertEqual(status, 200)
        self.assertEqual(product.calls, [("cancel",)])

    def test_empty_auth_configuration_does_not_authorize_mutations(self):
        product, port = self.start()
        headers = {"Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": "", "Cookie": "modulate=", "Content-Type": "application/json"}
        self.assertEqual(self.request(port, "/api/cancel", method="POST", body="{}", headers=headers)[0], 403)
        self.assertEqual(product.calls, [])
        _, device_port = self.start(device=True, peer="127.0.0.1")
        self.assertEqual(self.request(device_port, "/device/heartbeat", method="POST", body="{}",
                                     headers={"Authorization": "Bearer ", "Content-Type": "application/json"})[0], 403)

    def test_sensitive_gets_reject_bad_host_and_cross_origin(self):
        _, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        for path in ("/api/state", "/api/csrf", "/api/preview.png", "/api/candidate-preview.png"):
            self.assertEqual(self.request(port, path, headers={"Host": "attacker.example"})[0], 403)
            self.assertEqual(self.request(port, path, headers={"Origin": "https://attacker.example"})[0], 403)
        status, headers, body = self.request(port, "/api/csrf")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"token": "synthetic-csrf"})
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_device_requires_bearer_and_exact_peer_and_cannot_use_browser_routes(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        good = {"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"}
        for headers in ({"Content-Type": "application/json"}, {**good, "Authorization": "Bearer wrong"}):
            self.assertEqual(self.request(port, "/device/heartbeat", method="POST", body="{}", headers=headers)[0], 403)
        self.assertEqual(self.request(port, "/api/state", headers=good)[0], 403)
        self.assertEqual(self.request(port, "/api/pairing", method="POST", body="{}", headers=good)[0], 404)
        self.assertEqual(self.request(port, "/device/heartbeat", method="POST", body='{"sequence":1}', headers=good)[0], 200)
        self.assertEqual(product.calls, [("heartbeat", {"sequence": 1})])
        _, wrong_port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.2")
        self.assertEqual(self.request(wrong_port, "/device/heartbeat", method="POST", body="{}", headers=good)[0], 403)

    def test_invalid_json_and_lengths_never_dispatch(self):
        product, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        for body in ("[]", "null", '{"text":NaN}', '{"text":"a","text":"b"}', "not-json"):
            status, _, _ = self.request(port, "/api/request", method="POST", body=body, headers=self.headers(port))
            self.assertEqual(status, 400)
        for changes in ({"Content-Type": "text/plain"}, {"Content-Length": "300000"}, {"Transfer-Encoding": "chunked"}):
            self.assertEqual(self.request(port, "/api/request", method="POST", body="{}", headers=self.headers(port, **changes))[0], 413)
        self.assertEqual(product.calls, [])

    def test_unexpected_internal_exception_is_not_echoed(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")

        def fail(data):
            raise RuntimeError("synthetic private backend details")

        product.heartbeat = fail
        status, _, body = self.request(port, "/device/heartbeat", method="POST", body="{}",
                                       headers={"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"})
        self.assertEqual(status, 500)
        self.assertNotIn(b"private", body)

    def test_pairing_creation_uses_product_delivery_state(self):
        product, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session", host_url="https://test.invalid:8788")
        status, _, body = self.request(port, "/api/pairing", method="POST", body="{}", headers=self.headers(port))
        self.assertEqual(status, 200)
        self.assertEqual(product.calls, [("create_pairing",)])
        self.assertEqual(json.loads(body)["host_url"], "https://test.invalid:8788")

    def test_candidate_and_live_preview_routes_are_separate(self):
        product, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        self.assertEqual(self.request(port, "/api/preview.png")[2], b"live-test-image")
        self.assertEqual(self.request(port, "/api/candidate-preview.png")[2], b"candidate-test-image")
        product.preview_bytes = b""
        self.assertEqual(self.request(port, "/api/preview.png")[0], 404)
        self.assertEqual(self.request(port, "/api/candidate-preview.png")[0], 200)

    def test_both_request_endpoints_return_immediate_job_identity(self):
        _, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        status, _, body = self.request(port, "/api/request", method="POST", body='{"text":"Synthetic request"}', headers=self.headers(port))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["job_id"], "a" * 32)
        _, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        status, _, body = self.request(port, "/device/request", method="POST", body='{"text":"Synthetic voice request"}',
                                       headers={"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["job_id"], "a" * 32)
        self.assertEqual(json.loads(body)["source"], "microphone")


if __name__ == "__main__":
    unittest.main()
