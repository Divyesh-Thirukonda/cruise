"""Synthetic device packets and volume backend only; no hardware or cloud calls."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modulate.agent import AgentError, digest
from modulate.agent_provider import AgentProvider
from modulate.host_bridge import BridgeError
from modulate.product import Product
import modulate.product as product_module


class FakeBackend:
    def __init__(self):
        self.volume = 40
        self.supported = True
        self.fail_get = False
        self.actions = []
        self.get_calls = 0

    def capabilities(self):
        return {"supported": self.supported, "platform": "synthetic-test"}

    def get(self):
        self.get_calls += 1
        if self.fail_get:
            raise BridgeError("Synthetic read failure")
        return {"volume": self.volume, "muted": False}

    def set_volume(self, value):
        self.actions.append(value)
        self.volume = value


def game(title="Synthetic game fixture"):
    return {"kind": "game", "title": title, "controls": ["button_a"],
            "code": "function init(){return {}};function update(s,i,d){return s};function draw(s){return []}",
            "assets": {"sprites": {"test_pixel": {"width": 1, "height": 1, "palette": ["#FFFFFF"], "pixels": [[0]]}}}}


def checks(package):
    # Test gate fixture only: these tests do not claim real runtime verification.
    return {"passed": True, "candidate_id": digest(package), "checks": [{"name": "synthetic gate", "passed": True}]}


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.backend = FakeBackend()
        self.provider = AgentProvider({"provider": "ollama", "model": "llama3.2:3b"})
        self.product = Product(self.directory, self.provider, backend=self.backend)
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.addCleanup(self.pool.shutdown, wait=True)
        self.addCleanup(self.product.cancel)
        self.session = "a" * 32
        self.sequence = 0

    def packet(self, **changes):
        self.sequence += 1
        value = {"session": self.session, "sequence": self.sequence, "name": "Synthetic controller",
                 "capabilities": {"controls": ["encoder", "button_a"], "devices": [], "warnings": []},
                 "input": {}, "revision": self.product.revision}
        value.update(changes)
        return value

    def heartbeat(self, **changes):
        return self.product.heartbeat(self.packet(**changes))

    def begin(self, package=None):
        package = package or game()
        future = self.pool.submit(self.product.activate, package, checks(package), base_revision=self.product.revision, timeout=2)
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(
                lambda: self.product.pending is not None and self.product.pending["phase"] == "stage", timeout=1))
            pending = copy.deepcopy(self.product.pending)
        return future, pending

    def finish(self, future, pending):
        ready = self.heartbeat(revision=pending["base_revision"], ack={"id": pending["id"], "revision": pending["revision"], "phase": "ready"})
        self.assertEqual(ready["activation"]["phase"], "commit")
        activated = self.heartbeat(revision=pending["revision"], ack={"id": pending["id"], "revision": pending["revision"], "phase": "activated"})
        self.assertEqual(activated["activation"]["phase"], "confirmed")
        self.assertTrue(future.result(timeout=1)["device_acknowledged"])

    def activate(self, package):
        future, pending = self.begin(package)
        self.finish(future, pending)

    def pair(self):
        code = self.product.bridge.create_pairing()["code"]
        return self.product.pair(code, "Synthetic controller")

    def control(self, target):
        return {"kind": "control", "title": "Synthetic volume fixture", "target": target,
                "bindings": [{"control": "encoder", "action": "volume.delta", "scale": 2}]}

    def test_disconnected_and_unverified_activation_cannot_stage(self):
        package = game()
        with self.assertRaisesRegex(AgentError, "disconnected"):
            self.product.activate(package, checks(package), base_revision=None)
        self.heartbeat()
        for report in ({}, {"passed": "yes", "candidate_id": digest(package)}, {"passed": True, "candidate_id": "wrong"}):
            with self.assertRaisesRegex(AgentError, "exact package"):
                self.product.activate(package, report, base_revision=None)
        self.assertIsNone(self.product.pending)

    def test_matching_stage_commit_ack_persists_exact_package(self):
        self.heartbeat()
        package = game()
        future, pending = self.begin(package)
        package["title"] = "Caller mutated its input after staging"
        self.assertIsNone(self.product.active)
        self.finish(future, pending)
        self.assertEqual(self.product.current_package()["title"], "Synthetic game fixture")
        reopened = Product(self.directory, self.provider, backend=self.backend)
        self.assertEqual(reopened.revision, pending["revision"])
        self.assertFalse(reopened.connected())

    def test_wrong_and_out_of_order_acknowledgements_do_not_commit(self):
        self.heartbeat()
        future, pending = self.begin()
        for ack in (
            {"id": "b" * 32, "revision": pending["revision"], "phase": "ready"},
            {"id": pending["id"], "revision": "c" * 64, "phase": "ready"},
            {"id": pending["id"], "revision": pending["revision"], "phase": "activated"},
        ):
            self.heartbeat(ack=ack)
            self.assertEqual(self.product.pending["phase"], "stage")
            self.assertIsNone(self.product.active)
        self.finish(future, pending)

    def test_wrong_device_revision_cannot_acknowledge_ready_or_activated(self):
        self.heartbeat()
        future, pending = self.begin()
        with self.assertRaisesRegex(AgentError, "Unknown controller revision"):
            self.heartbeat(revision="c" * 64, ack={"id": pending["id"], "revision": pending["revision"], "phase": "ready"})
        self.assertEqual(self.product.pending["phase"], "stage")
        self.heartbeat(revision=None, ack={"id": pending["id"], "revision": pending["revision"], "phase": "ready"})
        self.heartbeat(revision=None, ack={"id": pending["id"], "revision": pending["revision"], "phase": "activated"})
        self.assertEqual(self.product.pending["phase"], "commit")
        self.assertIsNone(self.product.active)
        self.heartbeat(revision=pending["revision"], ack={"id": pending["id"], "revision": pending["revision"], "phase": "activated"})
        self.assertTrue(future.result(timeout=1)["activated"])

    def test_cancellation_after_ready_rejects_late_activation_ack(self):
        self.heartbeat()
        future, pending = self.begin()
        self.heartbeat(ack={"id": pending["id"], "revision": pending["revision"], "phase": "ready"})
        self.product.cancel()
        response = self.heartbeat(revision=pending["revision"], ack={"id": pending["id"], "revision": pending["revision"], "phase": "activated"})
        self.assertEqual(response["activation"]["phase"], "abort")
        self.assertIsNone(self.product.active)
        with self.assertRaisesRegex(AgentError, "Cancelled"):
            future.result(timeout=1)

    def test_session_or_capability_change_aborts_staged_activation(self):
        for change in ("session", "capability"):
            with self.subTest(change=change):
                self.product.agent.cancelled.clear()
                self.heartbeat()
                future, pending = self.begin()
                if change == "session":
                    self.session = "b" * 32
                    self.heartbeat()
                else:
                    self.heartbeat(capabilities={"controls": [], "devices": [], "warnings": []})
                self.assertEqual(self.product.pending["phase"], "abort")
                with self.assertRaises(AgentError):
                    future.result(timeout=1)
        self.assertIsNone(self.product.active)

    def test_old_session_and_duplicate_packets_stay_rejected_after_restart(self):
        original = self.packet()
        self.product.heartbeat(original)
        with self.assertRaisesRegex(AgentError, "Stale"):
            self.product.heartbeat(original)
        self.session = "b" * 32
        newest = self.packet()
        self.product.heartbeat(newest)
        reopened = Product(self.directory, self.provider, backend=self.backend)
        for stale in (original, {**original, "sequence": 10000}, newest):
            with self.assertRaisesRegex(AgentError, "Stale"):
                reopened.heartbeat(stale)
        self.assertFalse(reopened.connected())
        reopened.heartbeat({**newest, "sequence": newest["sequence"] + 1})
        self.assertTrue(reopened.connected())

    def test_invalid_packet_does_not_change_sequence_session_or_connection(self):
        invalid = self.packet(input={"encoder_delta": "bad"})
        with self.assertRaises(ValueError):
            self.product.heartbeat(invalid)
        self.assertEqual(self.product.last_packet, -1)
        self.assertIsNone(self.product.source_session)
        self.assertFalse(self.product.connected())
        self.product.heartbeat({**invalid, "input": {}})
        last_seen = self.product.last_seen
        malformed = self.packet(capabilities={"controls": [["encoder"]]})
        with self.assertRaises(AgentError):
            self.product.heartbeat(malformed)
        self.assertEqual(self.product.last_seen, last_seen)
        self.assertEqual(self.product.last_packet, invalid["sequence"])

    def test_native_pairing_read_failure_revokes_new_grant(self):
        self.heartbeat()
        code = self.product.bridge.create_pairing()["code"]
        self.backend.fail_get = True
        with self.assertRaises(BridgeError):
            self.product.pair(code, "Synthetic controller")
        self.assertIsNone(self.product.volume_token)
        state = json.loads(self.product.bridge.path.read_text())
        self.assertEqual(state["sessions"], [])

    def test_volume_delta_requires_matching_active_revision_grant_and_encoder(self):
        self.heartbeat()
        paired = self.pair()
        package = self.control(paired["session_id"])
        self.activate(package)
        self.heartbeat(volume_token=paired["token"], input={"encoder_delta": 3})
        self.assertEqual(self.backend.actions, [46])
        self.heartbeat(revision=None, volume_token=paired["token"], input={"encoder_delta": 3})
        self.assertEqual(self.backend.actions, [46])
        response = self.heartbeat(volume_token=paired["token"], input={"encoder_delta": 3},
                                  capabilities={"controls": [], "devices": [], "warnings": []})
        self.assertEqual(self.backend.actions, [46])
        self.assertFalse(response["paired"])
        self.assertIsNone(self.product.volume_token)

    def test_revoked_or_unsupported_volume_capability_fails_closed(self):
        self.heartbeat()
        paired = self.pair()
        self.activate(self.control(paired["session_id"]))
        self.backend.supported = False
        response = self.heartbeat(volume_token=paired["token"], input={"encoder_delta": 2})
        self.assertFalse(response["paired"])
        self.assertEqual(self.backend.actions, [])
        self.backend.supported = True
        self.product.revoke()
        response = self.heartbeat(volume_token=paired["token"], input={"encoder_delta": 2})
        self.assertFalse(response["paired"])
        self.assertEqual(self.backend.actions, [])

    def test_failed_host_commit_aborts_and_preserves_old_active_record(self):
        self.heartbeat()
        self.activate(game("First synthetic game"))
        previous = self.product.revision
        future, pending = self.begin(game("Second synthetic game"))
        self.heartbeat(ack={"id": pending["id"], "revision": pending["revision"], "phase": "ready"})
        with patch.object(self.product, "_commit", side_effect=OSError("Synthetic disk failure")):
            response = self.heartbeat(revision=pending["revision"], ack={"id": pending["id"], "revision": pending["revision"], "phase": "activated"})
        self.assertEqual(response["activation"]["phase"], "abort")
        self.assertEqual(self.product.revision, previous)
        with self.assertRaisesRegex(AgentError, "Host could not commit"):
            future.result(timeout=1)

    def test_explicit_rollback_after_cancel_can_activate_previous_program(self):
        self.heartbeat()
        self.activate(game("First synthetic game"))
        first = self.product.revision
        self.activate(game("Second synthetic game"))
        self.product.cancel()
        future = self.pool.submit(self.product.rollback)
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: self.product.pending["phase"] == "stage", timeout=1))
            pending = copy.deepcopy(self.product.pending)
        self.finish(future, pending)
        self.assertEqual(self.product.revision, first)

    def test_runtime_failure_restores_only_known_predecessor_and_is_idempotent(self):
        self.heartbeat()
        self.activate(game("First synthetic game"))
        first = self.product.revision
        self.activate(game("Second synthetic game"))
        failed = self.product.revision
        failure = {"revision": failed, "restored_revision": first, "error": "Synthetic runtime deadline"}
        response = self.heartbeat(revision=first, failure=failure)
        self.assertEqual(self.product.revision, first)
        self.assertEqual(response["activation"]["phase"], "abort")
        self.assertEqual(response["failure_ack"], {"revision": failed, "restored_revision": first})
        reopened = Product(self.directory, self.provider, backend=self.backend)
        response = reopened.heartbeat(self.packet(revision=first, failure=failure))
        self.assertEqual(response["failure_ack"]["revision"], failed)
        self.assertEqual(reopened.revision, first)
        self.assertEqual([item["type"] for item in self.product.events].count("device_runtime_failed"), 1)

    def test_runtime_failure_without_predecessor_restores_idle(self):
        self.heartbeat()
        self.activate(game())
        failed = self.product.revision
        self.heartbeat(revision=None, failure={"revision": failed, "restored_revision": None, "error": "Synthetic failure"})
        self.assertIsNone(self.product.active)
        self.assertIsNone(Product(self.directory, self.provider, backend=self.backend).active)

    def test_unknown_failure_cannot_rewrite_host_active_or_consume_packet(self):
        self.heartbeat()
        self.activate(game())
        active = self.product.revision
        sequence = self.product.last_packet
        with self.assertRaisesRegex(AgentError, "resynchronization"):
            self.heartbeat(revision=None, failure={"revision": "f" * 64, "restored_revision": None, "error": "Synthetic false failure"})
        self.assertEqual(self.product.revision, active)
        self.assertEqual(self.product.last_packet, sequence)

    def test_failure_before_host_commit_is_acknowledged_even_after_restart(self):
        self.heartbeat()
        future, pending = self.begin()
        self.product.cancel()
        with self.assertRaises(AgentError):
            future.result(timeout=1)
        reopened = Product(self.directory, self.provider, backend=self.backend)
        failure = {"revision": pending["revision"], "restored_revision": None, "error": "Synthetic commit timeout"}
        response = reopened.heartbeat(self.packet(revision=None, failure=failure))
        self.assertEqual(response["failure_ack"]["revision"], pending["revision"])
        self.assertIsNone(reopened.active)

    def test_host_recovery_restages_confirmed_program_without_rewriting_predecessor(self):
        self.heartbeat()
        self.activate(game("First synthetic game"))
        first = self.product.revision
        self.activate(game("Second synthetic game"))
        second = self.product.revision
        reopened = Product(self.directory, self.provider, backend=self.backend)
        response = reopened.heartbeat(self.packet(revision=first))
        activation = response["activation"]
        self.assertEqual((activation["phase"], activation["revision"], activation["base_revision"]), ("stage", second, first))
        ready = reopened.heartbeat(self.packet(revision=first, ack={"id": activation["id"], "revision": second, "phase": "ready"}))
        self.assertEqual(ready["activation"]["phase"], "commit")
        final = reopened.heartbeat(self.packet(revision=second, ack={"id": activation["id"], "revision": second, "phase": "activated"}))
        self.assertEqual(final["activation"]["phase"], "confirmed")
        self.assertEqual(reopened.active["previous"]["revision"], first)

    def test_pairing_code_is_delivered_only_until_expiry_pairing_or_revoke(self):
        pairing = self.product.create_pairing()
        response = self.heartbeat()
        self.assertEqual(response["pairing"], pairing)
        with patch("modulate.product.time.time", return_value=pairing["expires_at"]):
            self.assertIsNone(self.heartbeat()["pairing"])
        paired = self.product.pair(pairing["code"], "Synthetic controller")
        self.assertIsNone(self.heartbeat(volume_token=paired["token"])["pairing"])
        self.product.revoke()
        self.assertIsNone(self.product.pairing)
        self.assertIsNone(self.heartbeat()["pairing"])

    def test_candidate_preview_never_replaces_live_frame_and_control_commit_clears_it(self):
        self.heartbeat()
        self.activate(game())
        commands = [{"op": "clear", "color": "#123456"}]
        self.heartbeat(commands=commands)
        live = self.product.preview_bytes
        self.assertTrue(live.startswith(b"\x89PNG"))
        self.product.preview(b"synthetic candidate preview")
        self.assertEqual(self.product.preview_bytes, live)
        self.assertEqual(self.product.candidate_preview_bytes, b"synthetic candidate preview")
        paired = self.pair()
        self.activate(self.control(paired["session_id"]))
        self.assertEqual(self.product.preview_bytes, b"")

    def test_error_after_atomic_host_replace_reconciles_the_new_pointer(self):
        self.heartbeat()
        future, pending = self.begin()
        self.heartbeat(ack={"id": pending["id"], "revision": pending["revision"], "phase": "ready"})
        original_save = product_module._save_json

        def interrupted_save(path, value):
            original_save(path, value)
            if path == self.product.active_path:
                raise OSError("Synthetic interruption after atomic replacement")

        with patch("modulate.product._save_json", side_effect=interrupted_save):
            response = self.heartbeat(revision=pending["revision"], ack={"id": pending["id"], "revision": pending["revision"], "phase": "activated"})
        self.assertEqual(response["activation"]["phase"], "confirmed")
        self.assertTrue(future.result(timeout=1)["activated"])
        self.assertEqual(self.product.revision, pending["revision"])

    def test_new_cancel_aborts_an_explicit_rollback(self):
        self.heartbeat()
        self.activate(game("First synthetic game"))
        self.activate(game("Second synthetic game"))
        second = self.product.revision
        future = self.pool.submit(self.product.rollback)
        with self.product.changed:
            self.assertTrue(self.product.changed.wait_for(lambda: self.product.pending["phase"] == "stage", timeout=1))
        self.product.cancel()
        with self.assertRaisesRegex(AgentError, "Cancelled"):
            future.result(timeout=1)
        self.assertEqual(self.product.revision, second)

    def test_failed_resynchronization_does_not_repeat_every_heartbeat(self):
        self.heartbeat()
        self.activate(game("First synthetic game"))
        first = self.product.revision
        self.activate(game("Second synthetic game"))
        reopened = Product(self.directory, self.provider, backend=self.backend)
        activation = reopened.heartbeat(self.packet(revision=first))["activation"]
        failed = reopened.heartbeat(self.packet(revision=first, ack={"id": activation["id"],
            "revision": activation["revision"], "phase": "failed", "error": "Synthetic runtime verification failure"}))
        self.assertEqual(failed["activation"]["phase"], "abort")
        again = reopened.heartbeat(self.packet(revision=first))
        self.assertEqual(again["activation"]["id"], activation["id"])
        self.assertEqual(again["activation"]["phase"], "abort")

    def test_button_source_metadata_is_bounded_and_preserved(self):
        capabilities = {"controls": ["button_a", "button_b"], "devices": [], "warnings": [],
                        "button_sources": {"button_a": "PiTFT A or green Qwiic 0x6e", "button_b": "PiTFT B or red Qwiic 0x6f"}}
        self.heartbeat(capabilities=capabilities)
        self.assertEqual(self.product.capabilities()["button_sources"], capabilities["button_sources"])
        sequence = self.product.last_packet
        capabilities["button_sources"]["button_a"] = "x" * 161
        with self.assertRaisesRegex(AgentError, "button source"):
            self.heartbeat(capabilities=capabilities)
        self.assertEqual(self.product.last_packet, sequence)

    def test_control_reconnect_without_knob_movement_reads_real_zero_volume(self):
        self.heartbeat()
        paired = self.pair()
        self.activate(self.control(paired["session_id"]))
        reopened = Product(self.directory, self.provider, backend=self.backend)
        self.backend.volume = 0
        reads = self.backend.get_calls
        response = reopened.heartbeat(self.packet(session="b" * 32, volume_token=paired["token"]))
        self.assertEqual(response["volume"]["volume"], 0)
        self.assertTrue(response["paired"])
        self.assertEqual(self.backend.get_calls, reads + 1)
        self.assertEqual(self.backend.actions, [])

    def test_idle_control_polls_once_per_second_and_reflects_external_os_changes(self):
        self.heartbeat()
        paired = self.pair()
        self.activate(self.control(paired["session_id"]))
        self.product.volume_read_at = 100.0
        reads = self.backend.get_calls
        self.backend.volume = 67
        for now in (100.1, 100.5, 100.99):
            with patch("modulate.product.time.monotonic", return_value=now):
                response = self.heartbeat(volume_token=paired["token"])
            self.assertEqual(response["volume"]["volume"], 40)
        self.assertEqual(self.backend.get_calls, reads)
        with patch("modulate.product.time.monotonic", return_value=101.0):
            response = self.heartbeat(volume_token=paired["token"])
        self.assertEqual(response["volume"]["volume"], 67)
        self.assertEqual(self.backend.get_calls, reads + 1)
        self.backend.volume = 81
        with patch("modulate.product.time.monotonic", return_value=101.8):
            self.heartbeat(volume_token=paired["token"])
        self.assertEqual(self.backend.get_calls, reads + 1)
        with patch("modulate.product.time.monotonic", return_value=102.0):
            response = self.heartbeat(volume_token=paired["token"])
        self.assertEqual(response["volume"]["volume"], 81)
        self.assertEqual(self.backend.get_calls, reads + 2)

    def test_knob_delta_is_immediate_and_delays_next_idle_poll(self):
        self.heartbeat()
        paired = self.pair()
        self.activate(self.control(paired["session_id"]))
        self.product.volume_read_at = 100.0
        reads = self.backend.get_calls
        with patch("modulate.product.time.monotonic", return_value=100.1):
            response = self.heartbeat(volume_token=paired["token"], input={"encoder_delta": 2})
        self.assertEqual(response["volume"]["volume"], 44)
        self.assertEqual(self.backend.actions, [44])
        self.assertEqual(self.backend.get_calls, reads + 2)
        with patch("modulate.product.time.monotonic", return_value=101.0):
            self.heartbeat(volume_token=paired["token"])
        self.assertEqual(self.backend.get_calls, reads + 2)
        with patch("modulate.product.time.monotonic", return_value=101.2):
            self.heartbeat(volume_token=paired["token"])
        self.assertEqual(self.backend.get_calls, reads + 3)

    def test_failed_volume_polls_clear_cache_and_remain_rate_limited(self):
        self.heartbeat()
        paired = self.pair()
        self.activate(self.control(paired["session_id"]))
        self.product.volume_read_at = None
        self.backend.fail_get = True
        reads = self.backend.get_calls
        with patch("modulate.product.time.monotonic", return_value=100.0):
            response = self.heartbeat(volume_token=paired["token"])
        self.assertIsNone(response["volume"])
        self.assertIsNone(self.product.volume_token)
        with patch("modulate.product.time.monotonic", return_value=100.2):
            self.heartbeat(volume_token=paired["token"])
        self.assertEqual(self.backend.get_calls, reads + 1)
        with patch("modulate.product.time.monotonic", return_value=101.0):
            self.heartbeat(volume_token=paired["token"])
        self.assertEqual(self.backend.get_calls, reads + 2)
        self.product.revoke()
        self.assertIsNone(self.product.volume)
        self.assertIsNone(self.product.volume_read_at)
        with patch("modulate.product.time.monotonic", return_value=102.0):
            self.heartbeat(volume_token=paired["token"])
        self.assertEqual(self.backend.get_calls, reads + 2)

    def test_events_default_to_current_timestamp_without_replacing_supplied_time(self):
        with patch("modulate.product.time.time", return_value=1234.5):
            self.product.event({"type": "synthetic_default_time"})
            self.product.event({"type": "synthetic_supplied_time", "at": "2026-10-28T12:34:56Z"})
        self.assertEqual(self.product.events[-2]["at"], 1234.5)
        self.assertEqual(self.product.events[-1]["at"], "2026-10-28T12:34:56Z")

    def deferred_request(self, source="website"):
        self.heartbeat()
        with patch("modulate.product.threading.Thread") as thread:
            accepted = self.product.request("Synthetic progress test", source=source)
            work = thread.call_args.kwargs["target"]
        return accepted, work

    def test_job_identity_exists_before_worker_and_ignores_previous_request_events(self):
        self.product.agent.request_id = "e" * 32
        accepted, work = self.deferred_request()
        self.product.event({"type": "request_finished", "request_id": "e" * 32})
        state = self.heartbeat()["agent_state"]
        self.assertEqual(state["job_id"], accepted["job_id"])
        self.assertIsNone(state["request_id"])
        self.assertEqual((state["phase"], state["status"], state["running"]), ("queued", "running", True))
        self.assertEqual(self.product.state()["agent"], state)
        with patch.object(self.product.agent, "run", return_value="Synthetic completion"):
            work()
        self.assertEqual(self.heartbeat()["agent_state"]["status"], "completed")

    def test_current_job_events_report_actual_stages_with_fixed_titles(self):
        accepted, work = self.deferred_request()

        def run(text):
            self.product.event({"type": "request_started", "request_id": "b" * 32, "role": "orchestrator"})
            for tool, phase in (("write_package", "coding"), ("test_package", "checking"),
                                ("preview_package", "previewing"), ("activate_package", "activating")):
                self.product.event({"type": "tool_started", "request_id": "b" * 32,
                                    "role": "orchestrator", "tool": tool, "title": "Untrusted generated label"})
                state = self.product.agent_state()
                self.assertEqual((state["job_id"], state["request_id"], state["phase"], state["tool"]),
                                 (accepted["job_id"], "b" * 32, phase, tool))
                self.assertNotEqual(state["title"], "Untrusted generated label")
            self.product.event({"type": "tool_finished", "request_id": "b" * 32,
                                "tool": "test_package", "status": "failed", "role": "orchestrator"})
            self.assertEqual(self.product.agent_state()["status"], "running")
            self.assertEqual(self.product.agent_state()["title"], "Adjusting the app")
            self.product.event({"type": "request_finished", "request_id": "b" * 32, "role": "orchestrator"})
            return "Synthetic completion"

        with patch.object(self.product.agent, "run", side_effect=run):
            work()
        state = self.product.agent_state()
        self.assertEqual((state["running"], state["phase"], state["status"]), (False, "ready", "completed"))
        self.assertEqual(Product(self.directory, self.provider, backend=self.backend).agent_state()["job_id"], accepted["job_id"])

    def test_cancelled_inflight_job_stays_busy_until_worker_returns(self):
        accepted, work = self.deferred_request()

        def run(text):
            self.product.event({"type": "request_started", "request_id": "b" * 32, "role": "orchestrator"})
            self.product.cancel()
            self.product.event({"type": "model_call", "request_id": "b" * 32, "role": "orchestrator"})
            state = self.product.agent_state()
            self.assertEqual((state["running"], state["status"], state["phase"]), (True, "running", "cancelled"))
            raise AgentError("Synthetic cancellation")

        with patch.object(self.product.agent, "run", side_effect=run):
            work()
        state = self.heartbeat()["agent_state"]
        self.assertEqual(state["job_id"], accepted["job_id"])
        self.assertEqual((state["running"], state["status"]), (False, "cancelled"))

    def test_queued_cancel_never_starts_the_agent(self):
        accepted, work = self.deferred_request()
        self.product.cancel()
        with patch.object(self.product.agent, "run") as run:
            work()
        run.assert_not_called()
        self.assertEqual(self.product.agent_state()["status"], "cancelled")

    def test_host_restart_returns_matching_interrupted_job_identity(self):
        accepted, _ = self.deferred_request()
        reopened = Product(self.directory, self.provider, backend=self.backend)
        state = reopened.agent_state()
        self.assertEqual(state["job_id"], accepted["job_id"])
        self.assertEqual((state["running"], state["status"], state["phase"], state["title"]),
                         (False, "failed", "error", "Request interrupted"))

    def test_failed_job_and_late_old_job_event_cannot_clear_new_queued_job(self):
        first, work = self.deferred_request()
        with patch.object(self.product.agent, "run", side_effect=AgentError("Synthetic provider failure")):
            work()
        self.assertEqual(self.product.agent_state()["status"], "failed")
        second, second_work = self.deferred_request()
        self.product.job_context.job_id = first["job_id"]
        self.product.event({"type": "request_failed", "request_id": "b" * 32, "role": "orchestrator"})
        del self.product.job_context.job_id
        state = self.product.agent_state()
        self.assertEqual((state["job_id"], state["phase"], state["running"]), (second["job_id"], "queued", True))
        with patch.object(self.product.agent, "run", return_value="Done"):
            second_work()

    def test_job_sequence_is_monotonic_and_persists_before_worker_and_across_restart(self):
        first, work = self.deferred_request()
        self.assertEqual(first["job_sequence"], 1)
        self.assertEqual(self.heartbeat()["agent_state"]["job_sequence"], 1)
        self.assertEqual(json.loads(self.product.job_path.read_text())["job_sequence"], 1)
        with patch.object(self.product.agent, "run", return_value="Done"):
            work()
        self.product = Product(self.directory, self.provider, backend=self.backend)
        self.assertEqual(self.product.agent_state()["job_sequence"], 1)
        second, second_work = self.deferred_request()
        self.assertEqual(second["job_sequence"], 2)
        self.assertNotEqual(first["job_id"], second["job_id"])
        with patch.object(self.product.agent, "run", return_value="Done"):
            second_work()

    def test_legacy_saved_job_gets_sequence_zero_then_next_job_increments(self):
        first, work = self.deferred_request()
        with patch.object(self.product.agent, "run", return_value="Done"):
            work()
        saved = json.loads(self.product.job_path.read_text())
        saved.pop("job_sequence")
        self.product.job_path.write_text(json.dumps(saved))
        self.product = Product(self.directory, self.provider, backend=self.backend)
        self.assertEqual(self.product.agent_state()["job_id"], first["job_id"])
        self.assertEqual(self.product.agent_state()["job_sequence"], 0)
        accepted, work = self.deferred_request()
        self.assertEqual(accepted["job_sequence"], 1)
        with patch.object(self.product.agent, "run", return_value="Done"):
            work()


if __name__ == "__main__":
    unittest.main()
