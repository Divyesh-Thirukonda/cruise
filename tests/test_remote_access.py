"""Public dashboard boundary tests; only synthetic devices and local HTTP."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from modulate.agent import AgentError, digest
from modulate.product import Product
from modulate.remote_access import RemoteAccess, RemoteAccessError, PERMISSIONS, CONNECTOR_SECONDS, handler_for
from tests.test_assistant_io import SyntheticProvider, FakeComputer
from tests.test_mac_access import FakeCamera
from tests.test_product import FakeBackend


class RemoteAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.backend = FakeBackend()
        self.product = Product(self.directory, SyntheticProvider([]), backend=self.backend, computer=FakeComputer())
        self.product.last_seen = time.monotonic()
        self.now = 1000
        self.remote = RemoteAccess(self.product, self.directory, clock=lambda: self.now)
        self.product.remote_access = self.remote
        self.addCleanup(self.product.cancel)

    def claim(self, **kwargs):
        code = self.remote.create_pairing()["code"]
        return self.remote.claim(code, **kwargs)["token"]

    def pair_mac(self):
        self.product.last_seen = time.monotonic()
        self.product.pair(self.product.create_pairing()["code"], "Synthetic Pi")

    def start_http(self):
        self.secret = "synthetic-server-secret-" + "x" * 32
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.remote, self.secret))
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()
        self.port = server.server_address[1]
        def stop():
            server.shutdown()
            server.server_close()
            worker.join(1)
        self.addCleanup(stop)

    def http(self, path, method="GET", data=None, token=None, secret=True, raw=None):
        headers = {"Authorization": "Bearer " + self.secret} if secret else {}
        if token:
            headers["X-Modulate-Session"] = token
        body = json.dumps(data) if data is not None else raw
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            payload = response.read()
            if response.getheader("Content-Type") == "application/json":
                payload = json.loads(payload)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            return response.status, payload
        finally:
            connection.close()

    def test_speaker_connector_requires_live_browser_and_speaker_access(self):
        token = self.claim()
        self.start_http()
        with patch.object(self.product.speaker_volume, "control") as control:
            self.assertEqual(self.http("/speaker-control", "POST", {"action": "get"})[0], 401)
            self.remote.set_permissions({"speaker": False})
            self.assertNotEqual(self.http("/speaker-control", "POST", {"action": "get"}, token)[0], 200)
            control.assert_not_called()
            self.remote.set_permissions({"speaker": True})
            self.remote.revoke(token)
            self.assertEqual(self.http("/speaker-control", "POST", {"action": "get"}, token)[0], 401)
            control.assert_not_called()

    def test_speaker_connector_is_bounded_independent_of_mac_and_rechecks_revocation(self):
        token = self.claim()
        self.assertFalse(self.product.state()["paired"])
        self.product.agent.cancelled.set()
        def apply(action, value, *, allowed):
            self.assertTrue(allowed())
            # Heartbeats must be able to acquire Product.lock during readback.
            acquired = []
            def probe():
                with self.product.lock:
                    acquired.append(True)
            thread = threading.Thread(target=probe)
            thread.start(); thread.join(.5)
            self.assertEqual(acquired, [True])
            self.remote.revoke(token)
            self.assertFalse(allowed())
            return {"verified": True, "after": {"volume": 80, "muted": False}, "private": "hidden"}
        with patch.object(self.product.speaker_volume, "control", side_effect=apply):
            self.assertEqual(self.remote.speaker_command(token, {"action": "set", "value": 80}),
                             {"verified": True, "volume": 80, "muted": False})
        token = self.claim()
        for data in ({"action": "mute", "value": True}, {"action": "set", "value": True},
                     {"action": "set", "value": 101}, {"action": "get", "value": 0},
                     {"action": "set", "value": 80, "path": "/api/request"}):
            with self.subTest(data=data), patch.object(self.product.speaker_volume, "control") as control:
                with self.assertRaises(RemoteAccessError):
                    self.remote.speaker_command(token, data)
                control.assert_not_called()

    def test_connector_reservation_storage_failure_blocks_model_dispatch(self):
        token = self.claim()
        with patch.object(self.remote.connector_requests, "save", side_effect=OSError("disk full")), patch.object(self.remote, "request") as request:
            with self.assertRaises(OSError):
                self.remote.connector_request(token, {"request_id": "a"*32, "text": "Make a game"})
            request.assert_not_called()
            self.assertEqual(self.remote.connector_requests.records, {})

    def test_connector_corrupt_history_fails_closed_instead_of_resetting_identities(self):
        (self.directory / "connector-requests.json").write_text('{"bad": "corrupt"}')
        with self.assertRaisesRegex(ValueError, "refusing to replay"):
            RemoteAccess(self.product, self.directory, clock=lambda: self.now)

    def test_connector_request_replay_and_restart_do_not_duplicate_dispatch(self):
        token = self.claim()
        payload = {"request_id": "a"*32, "text": "Make a game"}
        def dispatch(*args):
            self.product.progress.update(job_id="b"*32, phase="queued")
            self.product.running = True
            return {"job_id": "b"*32, "accepted": True}
        with patch.object(self.remote, "request", side_effect=dispatch) as request:
            first = self.remote.connector_request(token, payload)
            self.assertEqual(first["job_id"], "b"*32)
            self.assertEqual(self.remote.connector_request(token, payload), first)
            request.assert_called_once()
        self.product.running = False
        reloaded = RemoteAccess(self.product, self.directory, clock=lambda: self.now)
        with patch.object(reloaded, "request") as request:
            self.assertEqual(reloaded.connector_request(token, payload)["job_id"], "b"*32)
            request.assert_not_called()
        with self.assertRaisesRegex(ValueError, "different text"):
            reloaded.connector_request(token, {**payload, "text": "Do a different task"})
        journal = (self.directory / "connector-requests.json").read_text()
        self.assertNotIn(token, journal)
        self.assertNotIn("Make a game", journal)
        self.assertEqual((self.directory / "connector-requests.json").stat().st_mode & 0o777, 0o600)

    def test_connector_unknown_dispatch_is_retained_instead_of_replayed(self):
        token = self.claim()
        payload = {"request_id": "a"*32, "text": "Make a game"}
        with patch.object(self.remote, "request", side_effect=RuntimeError("uncertain dispatch")) as request:
            with self.assertRaises(RuntimeError):
                self.remote.connector_request(token, payload)
            self.assertEqual(self.remote.connector_request(token, payload)["status"], "unknown")
            request.assert_called_once()

    def test_connector_status_and_cancel_are_owned_and_never_expose_other_jobs(self):
        token, other = self.claim(), self.claim()
        self.remote.connector_requests.reserve(hashlib.sha256(token.encode()).hexdigest(), "a"*32,
            {"text": "A request"}, self.now+100, self.now)[0]["job_id"] = "b"*32
        self.product.progress.update(job_id="b"*32, phase="ready")
        self.product.summary = "Done"
        self.product.response = {"id": "c"*32, "text": "This job result", "expires_at": time.time()+100}
        result = self.remote.connector_status(token, "a"*32)
        self.assertEqual(result["response"], "This job result")
        self.assertNotIn("events", result)
        with self.assertRaises(RemoteAccessError):
            self.remote.connector_status(other, "a"*32)
        with patch.object(self.product, "cancel", return_value={"cancelled": True}) as cancel:
            self.assertTrue(self.remote.connector_cancel(token, "a"*32)["cancelled"])
            cancel.assert_called_once_with("b"*32)
        self.product.progress["job_id"] = "d"*32
        self.product.response["text"] = "Other session private result"
        result = self.remote.connector_status(token, "a"*32)
        self.assertEqual(result["status"], "superseded")
        self.assertNotIn("private", json.dumps(result))
        with patch.object(self.product, "cancel") as cancel:
            with self.assertRaises(RemoteAccessError):
                self.remote.connector_cancel(token, "a"*32)
            cancel.assert_not_called()
        self.remote.revoke(token)
        with self.assertRaises(RemoteAccessError):
            self.remote.connector_status(token, "a"*32)

    def test_connector_http_only_accepts_typed_requests_and_owns_status(self):
        token = self.claim()
        self.start_http()
        for payload in ({"text": "Hi"}, {"request_id": "a"*32, "text": "Hi", "shell": "bad"},
                        {"request_id": "a"*32, "text": "Hi", "followup_id": "bad"}):
            self.assertEqual(self.http("/connector-request", "POST", payload, token)[0], 400)
        self.assertEqual(self.http("/connector-request?request_id="+"a"*32, token=token)[0], 404)
        self.assertEqual(self.http("/connector-request?request_id="+"a"*32+"&request_id="+"b"*32, token=token)[0], 400)
        self.assertEqual(self.http("/connector-request?request_id="+"a"*32)[0], 401)

    def test_week_connector_survives_browser_expiry_revocation_and_reload(self):
        browser = self.claim()
        connection = self.remote.create_connector(browser, {})
        token = connection["token"]
        self.assertEqual(connection["expires_at"], self.now + CONNECTOR_SECONDS)
        self.assertNotIn(token, self.remote.path.read_text())
        self.assertEqual(self.remote.session(browser)["connectors"][0]["id"], connection["id"])
        self.remote.revoke(browser)
        self.now += 6 * 24 * 60 * 60
        reloaded = RemoteAccess(self.product, self.directory, clock=lambda: self.now)
        self.assertEqual(reloaded.authenticate(token)["kind"], "connector")
        self.assertFalse(reloaded.session(browser)["connected"])
        self.assertFalse(reloaded.session(token)["connected"], "A tool credential is never browser authentication")
        self.assertEqual(reloaded.local_status()["browsers"], [])
        self.assertEqual(len(reloaded.local_status()["connectors"]), 1)
        reloaded.job_owner = connection["id"]
        reloaded.job_id = self.product.progress["job_id"] = "a"*32
        reloaded.require_job()
        self.assertFalse(self.product.state()["paired"], "Week access must not pair a Mac")
        self.now = connection["expires_at"]
        with self.assertRaises(RemoteAccessError):
            reloaded.authenticate(token)
        with self.assertRaises(AgentError):
            reloaded.require_job()

    def test_connector_expiry_does_not_extend_ordinary_browser_authentication(self):
        browser = self.claim()
        connection = self.remote.create_connector(browser, {})
        self.now += 8 * 60 * 60 + 1
        self.assertFalse(self.remote.session(browser)["connected"])
        self.assertEqual(self.remote.authenticate(connection["token"])["kind"], "connector")

    def test_week_connector_cannot_create_grants_or_use_dashboard_admin_routes(self):
        browser = self.claim()
        connection = self.remote.create_connector(browser, {})
        token = connection["token"]
        self.start_http()
        self.assertFalse(self.http("/session", token=token)[1]["connected"])
        for path, method, data in [("/state", "GET", None), ("/preview", "GET", None),
                ("/permissions", "POST", {"permissions": {"speaker": True}}),
                ("/command", "POST", {"path": "/api/wake", "payload": {"enabled": False}}),
                ("/connector-session", "POST", {})]:
            with self.subTest(path=path):
                self.assertEqual(self.http(path, method, data, token)[0], 403)
        with patch.object(self.product.speaker_volume, "control", return_value={"verified": True, "volume": 80, "muted": False}):
            self.assertEqual(self.http("/speaker-control", "POST", {"action": "get"}, token)[0], 200)
            self.remote.set_permissions({"speaker": False})
            self.assertNotEqual(self.http("/speaker-control", "POST", {"action": "get"}, token)[0], 200)
        self.assertTrue(self.product.wake)

    def test_browser_can_revoke_only_connector_ids_and_cancels_its_running_job(self):
        browser = self.claim()
        connection = self.remote.create_connector(browser, {})
        with self.assertRaises(RemoteAccessError):
            self.remote.revoke_connector(connection["token"], connection["id"])
        with self.assertRaises(RemoteAccessError):
            self.remote.revoke_connector(browser, hashlib.sha256(browser.encode()).hexdigest())
        self.remote.job_owner = connection["id"]
        self.remote.job_id = self.product.progress["job_id"] = "a"*32
        with patch.object(self.product, "cancel") as cancel:
            result = self.remote.revoke_connector(browser, connection["id"])
            self.assertTrue(result["revoked"])
            cancel.assert_called_once_with("a"*32)
        self.assertTrue(self.remote.session(browser)["connected"])
        with self.assertRaises(RemoteAccessError):
            RemoteAccess(self.product, self.directory, clock=lambda: self.now).authenticate(connection["token"])

    def test_connector_creation_and_revocation_fail_without_false_success_on_storage_failure(self):
        browser = self.claim()
        before = dict(self.remote.state["sessions"])
        with patch.object(self.remote, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.remote.create_connector(browser, {})
        self.assertEqual(self.remote.state["sessions"], before)
        connection = self.remote.create_connector(browser, {})
        with patch.object(self.remote, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.remote.revoke_connector(browser, connection["id"])
        self.assertEqual(self.remote.authenticate(connection["token"])["kind"], "connector")

    def test_pair_code_one_use_and_only_token_hash_is_saved(self):
        result = self.remote.create_pairing()
        token = self.remote.claim(result["code"], "My phone")["token"]
        self.assertEqual(len(token), 43)
        self.assertEqual(self.remote.session(token)["name"], "My phone")
        self.assertNotIn(token, self.remote.path.read_text())
        self.assertNotIn(result["code"], self.remote.path.read_text())
        self.assertEqual(self.remote.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(RemoteAccessError):
            self.remote.claim(result["code"])
        reloaded = RemoteAccess(self.product, self.directory, clock=lambda: self.now)
        self.assertTrue(reloaded.session(token)["connected"])

    def test_website_comparison_requires_claimed_browser_and_cannot_pair_mac(self):
        token = self.claim()
        code = self.product.create_pairing()["code"]
        self.start_http()
        for path in ("/state", "/session"):
            self.assertNotIn(code, json.dumps(self.http(path)[1]))
        status, state = self.http("/state", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(state["mac_pairing"]["code"], code)
        self.assertFalse(self.product.state()["paired"])
        self.assertNotIn("mac_pairing", self.product.state())
        self.product.pairing["expires_at"] = time.time()-1
        self.assertIsNone(self.http("/state", token=token)[1]["mac_pairing"])
        self.remote.revoke(token)
        self.assertEqual(self.http("/state", token=token)[0], 401)

    def test_wrong_code_locks_after_six_attempts_and_expires(self):
        code = self.remote.create_pairing()["code"]
        for _ in range(6):
            with self.assertRaises(RemoteAccessError):
                self.remote.claim("wrong")
        with self.assertRaises(RemoteAccessError):
            self.remote.claim(code)
        code = self.remote.create_pairing()["code"]
        self.now += 301
        with self.assertRaises(RemoteAccessError):
            self.remote.claim(code)

    def test_claim_without_permissions_preserves_current_device_grants(self):
        self.remote.set_permissions({"computer": False, "system": False, "speaker": False,
                                     "remote_preview": True})
        expected = self.remote.local_status()["permissions"]
        code = self.remote.create_pairing()["code"]
        with patch.object(self.remote, "set_permissions", wraps=self.remote.set_permissions) as update:
            result = self.remote.claim(code, "Second browser")
        update.assert_not_called()
        self.assertEqual(result["permissions"], expected)
        reloaded = RemoteAccess(self.product, self.directory, clock=lambda: self.now)
        self.assertEqual(reloaded.session(result["token"])["permissions"], expected)

    def test_claim_without_permissions_does_not_restore_grants_from_code_creation(self):
        code = self.remote.create_pairing()["code"]
        self.remote.set_permissions({"camera": False, "audio": False, "hardware": False})
        expected = self.remote.local_status()["permissions"]
        result = self.remote.claim(code)
        self.assertEqual(result["permissions"], expected)
        self.assertFalse(self.product.permission_allowed("camera"))
        self.assertFalse(self.product.permission_allowed("audio"))
        self.assertFalse(self.product.permission_allowed("hardware"))

    def test_claim_with_explicit_permissions_keeps_existing_default_merge_semantics(self):
        self.remote.set_permissions({key: False for key in PERMISSIONS})
        token = self.claim(permissions={"camera": False, "remote_preview": True})
        self.assertEqual(self.remote.session(token)["permissions"], {
            **PERMISSIONS, "camera": False, "remote_preview": True,
        })

    def test_expiry_and_revocation_invalidate_private_reads_and_tools(self):
        token = self.claim()
        self.remote.job_owner = hashlib.sha256(token.encode()).hexdigest()
        self.product.progress["job_id"] = self.remote.job_id = "a" * 32
        self.now += 8 * 60 * 60 + 1
        self.assertFalse(self.remote.session(token)["connected"])
        with self.assertRaises(RemoteAccessError):
            self.remote.authenticate(token)
        with self.assertRaises(AgentError):
            self.product.check_request_access()
        token = self.claim()
        with patch.object(self.product, "cancel") as cancel:
            self.remote.job_owner = hashlib.sha256(token.encode()).hexdigest()
            self.remote.revoke(token)
            cancel.assert_called_once()
        self.assertFalse(self.remote.session(token)["connected"])

    def test_followup_starting_routes_record_browser_job_ownership(self):
        token = self.claim()
        with patch.object(self.product, "hardware_confirm", return_value={"job_id": "b" * 32, "accepted": True}):
            self.remote.command(token, "/api/hardware/confirm", {"id": "step", "step": "isolated"})
        self.assertEqual(self.remote.job_id, "b" * 32)
        self.product.progress["job_id"] = "b" * 32
        with patch.object(self.product, "cancel") as cancel:
            self.remote.revoke(token)
            cancel.assert_called_once()

    def test_native_action_rechecks_browser_revocation_before_cursor_use(self):
        self.pair_mac()
        token = self.claim()
        self.remote.job_owner = hashlib.sha256(token.encode()).hexdigest()
        self.remote.job_id = self.product.progress["job_id"] = "e" * 32
        self.product.running = True
        self.now += 8 * 60 * 60 + 1
        with self.assertRaisesRegex(AgentError, "browser"):
            self.product.computer_act("observation", {"type": "click", "x": 0, "y": 0}, False, "Synthetic click")
        self.assertEqual(self.product.computer.actions, [])
        self.product.running = False

    def test_permissions_survive_restart_and_block_trusted_actions(self):
        self.pair_mac()
        self.product.camera = FakeCamera()
        self.remote.set_permissions({key: False for key in PERMISSIONS})
        operations = [lambda: self.product.system_control("volume.set", 80),
                      self.product.computer_observe,
                      lambda: self.product.camera_control("start"),
                      lambda: self.product.computer_audio("start"),
                      lambda: self.product.speaker_control("set", 80),
                      lambda: self.product.hardware_debug("scan"),
                      lambda: self.product.request("Do something", source="microphone"),
                      lambda: self.product.computer_session("enable")]
        for operation in operations:
            with self.assertRaisesRegex(AgentError, "access is off"):
                operation()
        self.assertEqual(self.backend.actions, [])
        self.assertEqual(self.product.computer.observations, 0)
        self.assertEqual(self.product.camera.starts, 0)
        self.assertEqual(self.product.capabilities()["paired_host"]["actions"], [])
        self.assertFalse(self.product.state()["wake"])
        self.assertTrue(self.product.state()["paired"])
        reloaded = RemoteAccess(self.product, self.directory, clock=lambda: self.now)
        self.assertFalse(reloaded.allowed("camera"))
        self.assertFalse(self.product._camera_wanted())

    def test_removing_permission_cancels_current_request_and_streams(self):
        self.product.running = True
        with patch.object(self.product, "cancel") as cancel, patch.object(self.product, "stop_computer_audio") as stop_audio, patch.object(self.product, "stop_camera") as stop_camera, patch.object(self.product, "_stop_speech") as stop_speech:
            self.remote.set_permissions({"camera": False, "speaker": False})
            cancel.assert_called_once()
            stop_audio.assert_called_once()
            stop_camera.assert_called_once()
            stop_speech.assert_called_once()
        self.product.running = False

    def test_disabled_system_permission_stops_existing_knob_binding_without_unpairing(self):
        self.product.heartbeat({"session": "a" * 32, "sequence": 1, "name": "Synthetic Pi",
                                "capabilities": {"controls": ["encoder"], "devices": [], "warnings": []},
                                "input": {}, "revision": None})
        self.pair_mac()
        target = self.product.capabilities()["paired_host"]["session_id"]
        package = {"kind": "control", "title": "Synthetic volume", "target": target,
                   "bindings": [{"control": "encoder", "action": "volume.delta", "scale": 2}]}
        revision = digest(package)
        self.product.active = {"revision": revision, "package": package}
        self.remote.set_permissions({"system": False})
        response = self.product.heartbeat({"session": "a" * 32, "sequence": 2, "name": "Synthetic Pi",
                  "capabilities": {"controls": ["encoder"], "devices": [], "warnings": []},
                  "input": {"encoder_delta": 3}, "revision": revision})
        self.assertEqual(self.backend.actions, [])
        self.assertTrue(response["paired"])
        self.assertEqual(self.product.revision, revision)
        self.remote.set_permissions({"system": True})
        self.product.heartbeat({"session": "a" * 32, "sequence": 3, "name": "Synthetic Pi",
                  "capabilities": {"controls": ["encoder"], "devices": [], "warnings": []},
                  "input": {"encoder_delta": 1}, "revision": revision})
        self.assertEqual(self.backend.actions, [42])

    def test_bad_permission_shape_and_corrupt_disk_fail_closed(self):
        for value in ({"system": "true"}, {"shell": True}, [], None):
            with self.assertRaises(RemoteAccessError):
                self.remote.set_permissions(value)
        self.remote.path.write_text('{"version":1,"permissions":{},"sessions":{}}')
        with self.assertRaises(RemoteAccessError):
            RemoteAccess(self.product, self.directory)

    def test_restarting_without_gateway_configuration_keeps_permission_denials(self):
        self.remote.set_permissions({"system": False, "computer": False})
        restarted = Product(self.directory, SyntheticProvider([]), backend=FakeBackend(), computer=FakeComputer())
        self.assertFalse(restarted.permission_allowed("system"))
        self.assertFalse(restarted.permission_allowed("computer"))
        self.assertFalse(restarted.remote_access.local_status()["enabled"])
        with self.assertRaises(RemoteAccessError):
            restarted.remote_access.create_pairing()
        with self.assertRaisesRegex(AgentError, "access is off"):
            restarted.system_control("volume.set", 80)

    def test_failed_permission_save_does_not_grant_new_authority(self):
        self.remote.set_permissions({"system": False})
        with patch.object(self.remote, "_save", side_effect=OSError("Synthetic disk fault")):
            with self.assertRaises(OSError):
                self.remote.set_permissions({"system": True})
        self.assertFalse(self.product.permission_allowed("system"))

    def test_http_requires_both_gateway_and_browser_authority(self):
        self.start_http()
        token = self.claim()
        for path in ("/session", "/state", "/preview"):
            self.assertEqual(self.http(path, token=token, secret=False)[0], 401)
        self.assertEqual(self.http("/session")[1]["connected"], False)
        self.assertEqual(self.http("/state")[0], 401)
        self.assertEqual(self.http("/state", token=token)[0], 200)
        self.remote.revoke(token)
        self.assertEqual(self.http("/state", token=token)[0], 401)

    def test_state_queued_behind_revocation_cannot_return_private_snapshot(self):
        self.start_http()
        token = self.claim()
        authenticated = threading.Event()
        authenticate = self.remote.authenticate

        def observed_authenticate(value):
            session = authenticate(value)
            authenticated.set()
            return session

        result = {}

        def read_state():
            result["response"] = self.http("/state", token=token)

        with patch.object(self.remote, "authenticate", side_effect=observed_authenticate):
            with self.product.lock:
                worker = threading.Thread(target=read_state, daemon=True)
                worker.start()
                self.assertTrue(authenticated.wait(1))
                self.remote.revoke(token)
            worker.join(3)
        self.assertFalse(worker.is_alive())
        status, body = result["response"]
        self.assertEqual(status, 401)
        self.assertNotIn("device", body)

    def test_wake_rechecks_revocation_before_enabling_or_disabling(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                token = self.claim()
                self.product.wake = not enabled
                authenticated = threading.Event()
                release = threading.Event()
                authenticate = self.remote.authenticate

                def delayed_authenticate(value):
                    session = authenticate(value)
                    authenticated.set()
                    if not release.wait(2):
                        raise RuntimeError("Timed out waiting for synthetic revocation")
                    return session

                result = {}

                def change_wake():
                    try:
                        result["response"] = self.remote.command(token, "/api/wake", {"enabled": enabled})
                    except RemoteAccessError as error:
                        result["error"] = error

                with patch.object(self.remote, "authenticate", side_effect=delayed_authenticate):
                    worker = threading.Thread(target=change_wake, daemon=True)
                    worker.start()
                    try:
                        self.assertTrue(authenticated.wait(1))
                        self.remote.revoke(token)
                    finally:
                        release.set()
                    worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertNotIn("response", result)
                self.assertEqual(result["error"].status, 401)
                self.assertEqual(self.product.wake, not enabled)

    def test_http_exact_commands_and_bounded_json_only(self):
        self.start_http()
        token = self.claim()
        with patch.object(self.product, "cancel", return_value={"cancelled": True}) as cancel:
            self.assertEqual(self.http("/command", "POST", {"path": "/api/cancel", "payload": {}}, token)[0], 200)
            cancel.assert_called_once()
        self.assertEqual(self.http("/command", "POST", {"path": "http://localhost:8787/api/cancel"}, token)[0], 404)
        self.assertEqual(self.http("/command", "POST", {"path": "/api/remote/pairing"}, token)[0], 404)
        self.assertEqual(self.http("/command", "POST", token=token, raw='{"path":"/api/cancel","path":"/api/revoke"}')[0], 400)
        self.assertEqual(self.http("/command", "POST", token=token, raw='{"number":NaN}')[0], 400)
        self.assertEqual(self.http("/command", "POST", token=token, raw="x" * (256*1024 + 1))[0], 413)

    def test_camera_preview_requires_explicit_cloud_sharing_toggle(self):
        self.start_http()
        token = self.claim()
        self.product.active = {"package": {"kind": "game", "camera": {"target": "synthetic"}}}
        self.product.preview_bytes = b"synthetic-camera-image"
        self.product.candidate_preview_bytes = b"synthetic-candidate-image"
        self.assertEqual(self.http("/preview", token=token)[0], 403)
        self.assertEqual(self.http("/preview?candidate=1", token=token)[1], b"synthetic-candidate-image")
        self.remote.set_permissions({"remote_preview": True})
        self.assertEqual(self.http("/preview", token=token)[1], b"synthetic-camera-image")
        self.remote.set_permissions({"remote_preview": False})
        self.assertEqual(self.http("/preview", token=token)[0], 403)


if __name__ == "__main__":
    unittest.main()
