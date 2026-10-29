"""Hardware-debugger integration using synthetic Pi evidence and loopback HTTP.

No physical bus, native Mac actions, cloud model calls or speaker output. These
exercise the real Product, hardware coordinator, agent dispatch and HTTP routes.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

from modulate.agent import AgentError, TOOLS
from modulate.controls import neutral_input
from modulate.device import Controller
from modulate.device_transport import TransportError
from modulate.hardware_debug import HardwareDebug, HardwareDebugError
from modulate.product import Product
from modulate.studio import handler_for
from tests.test_agent import reply
from tests.test_assistant_io import FakeComputer, SyntheticProvider
from tests.test_product import FakeBackend


class HardwareIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.provider = SyntheticProvider([])
        with patch.dict("os.environ", {"MODULATE_TTS_PROVIDER": "disabled-test"}):
            self.product = Product(self.directory, self.provider, backend=FakeBackend(), computer=FakeComputer())
        self.product.hardware.timeout = 1
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown, wait=True)
        self.addCleanup(self.product.cancel, shutdown=True)
        self.session, self.boot = uuid.uuid4().hex, str(uuid.uuid4())
        self.sequence = 0
        self.addresses = [0x20, 0x36, 0x6E, 0x6F]
        self.report = self.make_report(uuid.uuid4().hex)

    def make_report(self, identifier):
        return {"bus_available": True, "scan_id": identifier, "addresses": sorted(self.addresses),
                "buttons": [{"address": address, "id": 93, "firmware": 259, "configured_address": address}
                            for address in self.addresses if address in {0x6D, 0x6E, 0x6F}],
                "controls": {"controls": ["encoder", "button_a", "button_b"]}, "warnings": []}

    def packet(self, *, ack=None, nested_session=None):
        self.sequence += 1
        return {"session": self.session, "sequence": self.sequence, "name": "Synthetic test Pi",
                "capabilities": {"controls": ["encoder", "button_a", "button_b"], "devices": [], "warnings": []},
                "revision": self.product.revision, "input": {},
                "telemetry": {"hardware": {"supported": True, "session": nested_session or self.session,
                    "boot_id": self.boot, "report": copy.deepcopy(self.report), "ack": ack}}}

    def heartbeat(self, **kwargs):
        return self.product.heartbeat(self.packet(**kwargs))

    def command(self):
        deadline = time.monotonic() + .8
        while time.monotonic() < deadline:
            command = self.product.hardware.offer(self.session)
            if command:
                return command
            time.sleep(.002)
        self.fail("Synthetic hardware command was not offered")

    def ack(self, command):
        self.report = self.make_report(command["id"])
        return {"id": command["id"], "action": command["action"], "status": "done",
                "result": copy.deepcopy(self.report)}

    def begin(self):
        self.heartbeat()
        future = self.pool.submit(self.product.hardware_debug, "begin_button_repair", "Synthetic extra button")
        command = self.command()
        self.assertEqual(command["action"], "scan")
        self.heartbeat(ack=self.ack(command))
        workflow = future.result(timeout=1)["workflow"]
        self.assertEqual(workflow["target"], 0x6D)  # Preserve the existing 0x6e and 0x6f buttons.
        return workflow

    def isolate(self):
        workflow = self.begin()
        self.session, self.boot = uuid.uuid4().hex, str(uuid.uuid4())
        self.sequence, self.addresses = 0, [0x6F]
        self.report = self.make_report(uuid.uuid4().hex)
        self.heartbeat()
        return workflow

    def server(self, *, device=False):
        server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        server.daemon_threads = True
        port = server.server_address[1]
        server.RequestHandlerClass = handler_for(self.product, device=device, port=port,
            csrf="synthetic-csrf", cookie="synthetic-session", device_key="synthetic-device", peer="127.0.0.1")
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        worker.start()

        def close():
            server.shutdown()
            server.server_close()
            worker.join(1)

        self.addCleanup(close)
        return port

    def post(self, port, path, data, headers):
        client = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            client.request("POST", path, json.dumps(data), {"Content-Type": "application/json", **headers})
            response = client.getresponse()
            return response.status, json.loads(response.read())
        finally:
            client.close()

    def browser_headers(self, port):
        return {"Origin": f"http://127.0.0.1:{port}", "X-CSRF-Token": "synthetic-csrf",
                "Cookie": "modulate=synthetic-session"}

    def test_authenticated_heartbeat_delivers_and_acknowledges_session_bound_command(self):
        port = self.server(device=True)
        auth = {"Authorization": "Bearer synthetic-device"}
        self.assertEqual(self.post(port, "/device/heartbeat", self.packet(), {})[0], 403)
        self.assertIsNone(self.product.source_session)
        self.assertEqual(self.post(port, "/device/heartbeat", self.packet(), auth)[0], 200)
        future = self.pool.submit(self.product.hardware_debug, "scan")
        command = self.command()
        status, response = self.post(port, "/device/heartbeat", self.packet(), auth)
        self.assertEqual(status, 200)
        self.assertEqual(response["hardware_command"], command)
        self.assertEqual(command["session"], self.session)
        self.assertIsNone(self.product.hardware.offer(uuid.uuid4().hex))
        ack = self.ack(command)
        self.assertEqual(self.post(port, "/device/heartbeat", self.packet(ack=ack),
                                  {"Authorization": "Bearer wrong-synthetic-key"})[0], 403)
        self.assertFalse(future.done())
        wrong = {**ack, "id": uuid.uuid4().hex}
        self.assertEqual(self.post(port, "/device/heartbeat", self.packet(ack=wrong), auth)[0], 200)
        self.assertFalse(future.done())
        final_packet = self.packet(ack=ack)
        self.assertEqual(self.post(port, "/device/heartbeat", final_packet, auth)[0], 200)
        result = future.result(timeout=1)
        self.assertEqual(result["report"]["scan_id"], command["id"])
        self.assertEqual(self.post(port, "/device/heartbeat", final_packet, auth)[0], 400)

    def test_nested_hardware_session_mismatch_withdraws_pending_operation(self):
        self.heartbeat()
        future = self.pool.submit(self.product.hardware_debug, "scan")
        command = self.command()
        response = self.heartbeat(ack=self.ack(command), nested_session=uuid.uuid4().hex)
        self.assertIsNone(response["hardware_command"])
        self.assertFalse(self.product.hardware.inspect()["supported"])
        with self.assertRaises(HardwareDebugError):
            future.result(timeout=1)

    def test_waiting_hardware_rpc_does_not_hold_product_lock(self):
        self.heartbeat()
        future = self.pool.submit(self.product.hardware_debug, "reinitialize")
        command = self.command()
        acquired = self.product.lock.acquire(timeout=.1)
        try:
            self.assertTrue(acquired, "Heartbeat must be able to acquire Product.lock while RPC waits")
        finally:
            if acquired:
                self.product.lock.release()
        self.heartbeat(ack=self.ack(command))
        self.assertTrue(future.result(timeout=1)["device_health"]["connected"])

    def test_agent_cannot_supply_physical_confirmation_or_use_specialist_tool(self):
        self.isolate()
        agent = self.product.agent
        schema = next(item["function"]["parameters"] for item in TOOLS
                      if item["function"]["name"] == "hardware_debug")
        self.assertEqual(set(schema["properties"]), {"action", "label"})
        with self.assertRaises(AgentError):
            agent.dispatch("hardware_debug", {"action": "inspect"}, "hardware-specialist")
        for field in ("confirmation", "confirmed", "phrase", "target", "register"):
            with self.subTest(field=field), self.assertRaises(AgentError):
                agent.dispatch("hardware_debug", {"action": "continue", field: "isolated button ready"}, "orchestrator")
        with self.assertRaises(ValueError):
            agent.dispatch("hardware_debug", {"action": "continue", "label": "isolated button ready"}, "orchestrator")
        result = agent.dispatch("hardware_debug", {"action": "continue"}, "orchestrator")
        self.assertFalse(result["workflow"]["confirmation_received"])
        self.assertEqual(result["workflow"]["phase"], "awaiting_isolation")
        self.assertIsNone(self.product.hardware.offer(self.session))

    def test_specialist_model_tool_catalog_omits_hardware_debugger(self):
        self.provider.script = [reply(content="Synthetic specialist observation only")]
        agent = self.product.agent
        agent.manifest = self.product.capabilities()
        agent.loop("Inspect the synthetic plan", "reviewer", 1)
        names = {item["function"]["name"] for item in self.provider.requests[-1][1]}
        self.assertNotIn("hardware_debug", names)

    def test_request_uses_raw_human_reply_not_prior_context_for_confirmation(self):
        self.isolate()
        self.product.conversation = {"original": "isolated button ready", "history": [], "questions": 0, "recoveries": 0}
        self.product._question("Say isolated button ready after reconnecting.")
        identifier = self.product.clarification["id"]
        seen = []

        def inspect_at_agent_entry(text):
            seen.append((text, self.product.hardware.inspect()["workflow"]["confirmation_received"]))
            return "Synthetic response; no hardware action."

        with patch.object(self.product.agent, "run", side_effect=inspect_at_agent_entry), \
                patch.object(self.product, "_publish_response"):
            self.product.request("yes", followup_id=identifier)
            with self.product.changed:
                self.assertTrue(self.product.changed.wait_for(lambda: not self.product.running, timeout=1))
            self.assertIn("isolated button ready", seen[0][0])
            self.assertFalse(seen[0][1])
            self.product.request("isolated button ready")
            with self.product.changed:
                self.assertTrue(self.product.changed.wait_for(lambda: not self.product.running, timeout=1))
        self.assertTrue(seen[1][1])
        self.assertIsNone(self.product.hardware.offer(self.session))  # Confirmation alone never writes.

    def test_ui_confirmation_requires_browser_auth_current_workflow_and_step(self):
        workflow = self.isolate()
        port = self.server()
        headers = self.browser_headers(port)
        data = {"id": workflow["id"], "step": workflow["confirmation_step"]}
        with patch.object(self.product, "request", return_value={"accepted": True}) as request:
            for missing in ("Origin", "Cookie", "X-CSRF-Token"):
                partial = {key: value for key, value in headers.items() if key != missing}
                self.assertEqual(self.post(port, "/api/hardware/confirm", data, partial)[0], 403)
            for key in ("id", "step"):
                self.assertEqual(self.post(port, "/api/hardware/confirm", {**data, key: uuid.uuid4().hex}, headers)[0], 400)
            request.assert_not_called()
            self.assertFalse(self.product.hardware.inspect()["workflow"]["confirmation_received"])
            self.assertEqual(self.post(port, "/api/hardware/confirm", data, headers)[0], 200)
            request.assert_called_once_with("Continue the current hardware repair using my confirmed physical step.")
            self.assertEqual(self.post(port, "/api/hardware/confirm", data, headers)[0], 400)
            self.assertEqual(request.call_count, 1)
        device_port = self.server(device=True)
        self.assertEqual(self.post(device_port, "/api/hardware/confirm", data,
                                  {"Authorization": "Bearer synthetic-device"})[0], 404)

    def test_shutdown_withdraws_command_and_keeps_workflow_but_explicit_cancel_ends_it(self):
        workflow = self.isolate()
        self.product.hardware.confirm(workflow["id"], workflow["confirmation_step"])
        future = self.pool.submit(self.product.hardware_debug, "scan")
        self.command()
        self.product.cancel(shutdown=True)
        with self.assertRaises(HardwareDebugError):
            future.result(timeout=1)
        self.assertIsNone(self.product.hardware.offer(self.session))
        state = self.product.hardware.inspect()["workflow"]
        self.assertEqual(state["phase"], "awaiting_isolation")
        self.assertFalse(state["confirmation_received"])
        self.assertNotEqual(state["confirmation_step"], workflow["confirmation_step"])
        reopened = HardwareDebug(self.product.hardware.path)
        self.assertEqual(reopened.inspect()["workflow"]["id"], workflow["id"])
        self.assertEqual(reopened.inspect()["workflow"]["phase"], "awaiting_isolation")
        self.product.cancel()
        self.assertEqual(self.product.hardware.inspect()["workflow"]["phase"], "cancelled")
        self.assertEqual(HardwareDebug(self.product.hardware.path).inspect()["workflow"]["phase"], "cancelled")

    def test_late_cancel_of_completed_job_does_not_cancel_durable_hardware_setup(self):
        workflow = self.begin()
        completed_job = uuid.uuid4().hex
        self.product.progress.update(job_id=completed_job, phase="ready")
        self.product.running = False
        self.product.clarification = None
        before = self.product.hardware.path.read_bytes()
        for identifier in (completed_job, uuid.uuid4().hex):
            result = self.product.cancel(identifier)
            self.assertFalse(result["cancelled"])
            self.assertEqual(self.product.hardware.path.read_bytes(), before)
            self.assertEqual(self.product.hardware.inspect()["workflow"]["id"], workflow["id"])
            self.assertEqual(self.product.hardware.inspect()["workflow"]["phase"], "awaiting_isolation")


class HardwareControllerIntegrationTests(unittest.TestCase):
    """Real Controller coordination with all hardware/transport workers replaced."""
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        for name in ("Companion", "Screen", "Controls", "DeviceActivation", "VoiceListener", "Speaker",
                     "SpeakerVolumeDevice", "HardwareDevice", "AudioReceiver"):
            patcher = patch("modulate.device." + name)
            setattr(self, name, patcher.start().return_value)
            self.addCleanup(patcher.stop)
        self.Screen.buttons = [SimpleNamespace(value=True), SimpleNamespace(value=True)]
        self.Controls.capabilities.return_value = {"controls": ["encoder", "button_a", "button_b"],
                                                   "devices": [], "warnings": []}
        self.Controls.poll.return_value = neutral_input()
        self.Speaker.snapshot.return_value = {"available": False, "state": "stopped", "error": None}
        self.SpeakerVolumeDevice.snapshot.return_value = {}
        self.HardwareDevice.snapshot.return_value = {}
        self.AudioReceiver.snapshot.return_value = {"enabled": False, "playing": False}
        self.DeviceActivation.snapshot.return_value = {"revision": None, "kind": None, "ack": None}
        self.controller = Controller(self.directory, "synthetic-enrollment")
        self.controller.last_response = time.monotonic()

    def test_network_delivers_offer_and_withdrawal_before_render_consumes_responses(self):
        command = {"id": uuid.uuid4().hex, "action": "scan"}
        self.Companion.post.side_effect = [{"hardware_command": command}, {"hardware_command": None}]
        self.controller._network_step()
        self.HardwareDevice.offer.assert_called_once_with(command)
        self.DeviceActivation.process.assert_not_called()
        self.assertEqual(self.controller.responses.qsize(), 1)
        self.controller._network_step()
        self.assertEqual([call.args[0] for call in self.HardwareDevice.offer.call_args_list], [command, None])
        self.DeviceActivation.process.assert_not_called()
        self.assertEqual(self.controller.responses.qsize(), 2)

    def test_network_failure_withdraws_hardware_without_waiting_for_render(self):
        self.Companion.post.side_effect = TransportError("Synthetic disconnected transport")
        self.controller._network_step()
        self.HardwareDevice.offer.assert_called_once_with(None)
        self.assertTrue(self.controller.responses.empty())
        self.DeviceActivation.process.assert_not_called()

    def test_capabilities_and_hardware_snapshot_are_read_outside_controller_lock(self):
        calls = []

        def read(name, value):
            self.assertFalse(self.controller.lock._is_owned(), name + " must not wait for the bus under the UI lock")
            calls.append(name)
            return value

        self.Controls.capabilities.side_effect = lambda: read("controls", {"controls": [], "devices": [], "warnings": []})
        self.HardwareDevice.snapshot.side_effect = lambda: read("hardware", {"supported": False})
        self.Companion.post.return_value = {"hardware_command": None}
        self.controller._network_step()
        self.assertEqual(calls, ["controls", "hardware"])

    def test_expired_question_with_active_hardware_setup_queues_fresh_voice_cancel(self):
        self.controller.host = {
            "agent_state": {"running": False, "job_id": "a" * 32},
            "clarification": {"job_id": "a" * 32, "expires_at": time.time() - 1,
                              "question": "Confirm isolation"},
            "hardware_workflow": {"id": "b" * 32, "phase": "awaiting_isolation"},
        }
        self.assertTrue(self.controller.cancel_request())
        self.assertTrue(self.controller.cancellations.empty())
        self.assertEqual(self.controller.requests.get_nowait(), "Cancel the current hardware setup.")
        self.assertTrue(self.controller.build["awaiting_response"])

    def test_one_render_iteration_retries_suspended_app_despite_hardware_overlay(self):
        state = {"revision": "a" * 64, "kind": "game", "title": "Synthetic saved app",
                 "ack": None, "suspended": True, "error": "Required controls unavailable"}
        self.DeviceActivation.snapshot.side_effect = lambda: dict(state)
        self.controller.state = dict(state)
        self.controller.host = {"hardware_workflow": {"phase": "awaiting_reconnect"}}
        self.Controls.poll.return_value = {**neutral_input(), "encoder_delta": 5}

        def resume(sample, dt):
            self.assertTrue(state["suspended"])
            self.assertEqual(sample["encoder_delta"], 0)
            state.update(suspended=False, error=None)
            self.controller.stop.set()  # One synthetic render iteration only.
            return None

        self.DeviceActivation.tick.side_effect = resume
        with patch("modulate.device.threading.Thread") as network_thread:
            self.controller.run()
        self.DeviceActivation.tick.assert_called_once()
        self.assertFalse(self.controller.state["suspended"])
        self.assertEqual(self.controller.state["revision"], "a" * 64)
        self.DeviceActivation.close.assert_called_once()
        network_thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
