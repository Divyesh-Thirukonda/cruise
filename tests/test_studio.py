"""Loopback HTTP handler tests using synthetic credentials and a fake product.

These exercise authorization and routing, not a real TLS device connection.
"""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
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

    def request(self, text, source="website", followup_id=None):
        self.calls.append(("request", text, source, followup_id))
        return {"accepted": True, "source": source, "job_id": "a" * 32}

    def unclear(self, reason, followup_id=None):
        self.calls.append(("unclear", reason, followup_id))
        return {"accepted": True, "job_id": "a" * 32}

    def cancel(self, job_id=None):
        self.calls.append(("cancel", job_id) if job_id is not None else ("cancel",))
        return {"cancelled": True}

    def draft(self, job_id, action, text):
        self.calls.append(("draft", job_id, action, text))
        return {"accepted": True}

    def computer_session(self, action, minutes=15):
        self.calls.append(("computer_session", action, minutes))
        return {"enabled": action == "enable"}

    def approve_computer_action(self, identifier, approved):
        self.calls.append(("computer_approval", identifier, approved))
        return {"accepted": True}

    def dismiss_response(self, identifier):
        self.calls.append(("dismiss_response", identifier))
        return {"dismissed": True}

    def speaker_action(self, action):
        self.calls.append(("speaker_action", action))
        return {"accepted": True}

    def heartbeat(self, data):
        self.calls.append(("heartbeat", data))
        return {"accepted": True}

    def create_pairing(self):
        self.calls.append(("create_pairing",))
        return {"code": "12345678", "expires_at": 12345}

    def pair(self, code, name):
        self.calls.append(("pair", code, name))
        return {"paired": True}

    def connection_setup(self, action):
        self.calls.append(("connection_setup", action))
        return {"display_requested": True}

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

    def test_voice_cancel_is_authenticated_and_bound_to_a_job(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        good = {"Authorization":"Bearer synthetic-device", "Content-Type":"application/json"}
        self.assertEqual(self.request(port,'/device/cancel',method='POST',body='{}',headers=good)[0],400)
        self.assertEqual(self.request(port,'/device/cancel',method='POST',body=json.dumps({'job_id':'a'*32}),headers=good)[0],200)
        self.assertEqual(product.calls, [('cancel','a'*32)])

    def test_edit_voice_draft_uses_browser_auth_and_exact_action(self):
        product, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        payload=json.dumps({'job_id':'b'*32,'action':'send','text':'Make it blue'})
        self.assertEqual(self.request(port,'/api/draft',method='POST',body=payload,headers=self.headers(port))[0],200)
        self.assertEqual(product.calls,[('draft','b'*32,'send','Make it blue')])

    def test_assistant_routes_require_complete_same_origin_browser_auth(self):
        product, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        good = self.headers(port)
        invalid = [{key: value for key, value in good.items() if key != missing}
                   for missing in ("Origin", "Cookie", "X-CSRF-Token")]
        invalid += [{**good, key: value} for key, value in (
            ("Origin", "https://other.example"), ("Cookie", "modulate=wrong"),
            ("X-CSRF-Token", "wrong"), ("Host", "other.example"))]
        for path in ("/api/computer", "/api/computer/approval", "/api/response/dismiss", "/api/speaker"):
            for headers in invalid:
                with self.subTest(path=path, headers=headers):
                    payload = {"action": "enable", "minutes": 120} if path == "/api/computer" else {}
                    self.assertEqual(self.request(port, path, method="POST", body=json.dumps(payload), headers=headers)[0], 403)
        self.assertEqual(product.calls, [], "Rejected requests must not reach computer or speaker actions")

    def test_assistant_routes_forward_exact_actions_ids_and_approval_decisions(self):
        product, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        cases = [
            ("/api/computer", {"action": "enable"}, ("computer_session", "enable", 15), {"enabled": True}),
            ("/api/computer", {"action": "revoke"}, ("computer_session", "revoke", 15), {"enabled": False}),
            ("/api/computer/approval", {"id": "a" * 32, "approved": True}, ("computer_approval", "a" * 32, True), {"accepted": True}),
            ("/api/computer/approval", {"id": "b" * 32, "approved": False}, ("computer_approval", "b" * 32, False), {"accepted": True}),
            ("/api/response/dismiss", {"id": "c" * 32}, ("dismiss_response", "c" * 32), {"dismissed": True}),
            ("/api/speaker", {"action": "test"}, ("speaker_action", "test"), {"accepted": True}),
            ("/api/speaker", {"action": "stop"}, ("speaker_action", "stop"), {"accepted": True}),
            ("/api/computer", {"action": "enable", "minutes": 120}, ("computer_session", "enable", 120), {"enabled": True}),
        ]
        for path, payload, expected_call, expected_result in cases:
            with self.subTest(path=path, payload=payload):
                status, headers, body = self.request(port, path, method="POST", body=json.dumps(payload), headers=self.headers(port))
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body), expected_result)
                self.assertEqual(product.calls[-1], expected_call)
                self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(product.calls, [case[2] for case in cases])
        self.assertIs(product.calls[2][2], True)
        self.assertIs(product.calls[3][2], False)

    def test_device_credentials_cannot_grant_computer_control_or_acknowledge_ui_actions(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        headers = {"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"}
        for path in ("/api/computer", "/api/computer/approval", "/api/response/dismiss", "/api/speaker"):
            with self.subTest(path=path):
                self.assertEqual(self.request(port, path, method="POST", body="{}", headers=headers)[0], 404)
        self.assertEqual(product.calls, [])

    def test_device_setup_requires_enrollment_and_only_accepts_fixed_actions(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        headers = {"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"}
        self.assertEqual(self.request(port, "/device/setup", method="POST", body='{"action":"show"}',
                                      headers={"Content-Type": "application/json"})[0], 403)
        for data in ({}, {"action": []}, {"action": "shell"}, {"action": "show", "approved": True}):
            with self.subTest(data=data):
                self.assertEqual(self.request(port, "/device/setup", method="POST", body=json.dumps(data), headers=headers)[0], 400)
        self.assertEqual(product.calls, [])
        for action in ("status", "show", "start_pairing", "create_browser_code"):
            status, _, body = self.request(port, "/device/setup", method="POST", body=json.dumps({"action": action}), headers=headers)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"display_requested": True})
            self.assertEqual(product.calls[-1], ("connection_setup", action))

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

    def test_interaction_lab_resources_are_external_and_permitted_by_unchanged_csp(self):
        _, port = self.start(csrf="synthetic-csrf", cookie="synthetic-session")
        status, headers, body = self.request(port, "/lab")
        self.assertEqual(status, 200)
        csp = headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertIn("style-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        tags = []

        class Tags(HTMLParser):
            def handle_starttag(self, tag, attrs):
                tags.append((tag, dict(attrs)))

        Tags().feed(body.decode())
        scripts = [attrs for tag, attrs in tags if tag == "script"]
        self.assertEqual(scripts, [{"src": "/lab.js", "defer": None}])
        self.assertIn(("link", {"rel": "stylesheet", "href": "/lab.css"}), tags)
        self.assertFalse(any(tag == "style" or "style" in attrs or any(key.startswith("on") for key in attrs)
                             for tag, attrs in tags))
        for path, mime in (("/lab.js", "text/javascript"), ("/lab.css", "text/css")):
            status, headers, content = self.request(port, path)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith(mime))
            self.assertEqual(headers["Content-Security-Policy"], csp)
            self.assertTrue(content)

    def test_interaction_lab_assets_keep_host_origin_and_device_listener_guards(self):
        _, port = self.start()
        _, device_port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        for path in ("/lab", "/lab.js", "/lab.css"):
            with self.subTest(path=path):
                self.assertEqual(self.request(port, path, headers={"Host": "attacker.example"})[0], 403)
                self.assertEqual(self.request(port, path, headers={"Origin": "https://attacker.example"})[0], 403)
                self.assertEqual(self.request(device_port, path, headers={"Authorization": "Bearer synthetic-device"})[0], 403)

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

    def test_followup_and_unclear_routes_preserve_exact_scope_and_authentication(self):
        product, port = self.start(device=True, device_key="synthetic-device", peer="127.0.0.1")
        headers = {"Authorization": "Bearer synthetic-device", "Content-Type": "application/json"}
        identifier = "c" * 32
        body = json.dumps({"text": "yes", "followup_id": identifier})
        self.assertEqual(self.request(port, "/device/request", method="POST", body=body, headers=headers)[0], 200)
        body = json.dumps({"reason": "empty", "followup_id": identifier})
        self.assertEqual(self.request(port, "/device/unclear", method="POST", body=body,
                                      headers={"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.request(port, "/device/unclear", method="POST", body=body, headers=headers)[0], 200)
        self.assertEqual(product.calls, [("request", "yes", "microphone", identifier), ("unclear", "empty", identifier)])


if __name__ == "__main__":
    unittest.main()
