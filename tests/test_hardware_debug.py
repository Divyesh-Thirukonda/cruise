"""Synthetic hardware protocol/workflow tests; never open an actual I2C bus."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from modulate.hardware_debug import HardwareDebug, HardwareDebugError


def wait_for(predicate):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.002)
    raise AssertionError("Synthetic hardware operation did not reach the expected state")


class Pi:
    def __init__(self, host, addresses=(0x20, 0x36, 0x6F)):
        self.host = host
        self.session, self.boot_id = uuid.uuid4().hex, str(uuid.uuid4())
        self.addresses = list(addresses)
        self.commands, self.writes = [], []
        self.report = self.scan(uuid.uuid4().hex)
        self.ack = None
        self.hold = None
        self.failure = None
        self.transform = None
        self.online = True
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.heartbeat()
        self.thread.start()

    def scan(self, scan_id):
        return {"addresses": sorted(self.addresses), "buttons": [
                    {"address": a, "id": 93, "firmware": 259, "configured_address": a}
                    for a in self.addresses if 0x60 <= a <= 0x6F and a != 0x6A],
                "controls": {"controls": ["button_a", "button_b"]},
                "warnings": [], "bus_available": True, "scan_id": scan_id}

    def heartbeat(self):
        self.host.observe({"supported": True, "session": self.session,
            "boot_id": self.boot_id, "report": copy.deepcopy(self.report),
            "ack": copy.deepcopy(self.ack)}, self.session)

    def reboot(self, addresses, *, new_boot=True):
        with self.lock:
            self.addresses = list(addresses)
            self.session = uuid.uuid4().hex
            if new_boot:
                self.boot_id = str(uuid.uuid4())
            self.report, self.ack = self.scan(uuid.uuid4().hex), None
            self.heartbeat()

    def run(self):
        seen = set()
        while not self.stop.wait(.002):
            with self.lock:
                if not self.online:
                    continue
                command = self.host.offer(self.session)
                if command and command["id"] not in seen and command["action"] != self.hold:
                    seen.add(command["id"])
                    self.commands.append(dict(command))
                    status = self.failure or "done"
                    if command["action"] == "readdress_button" and self.failure != "failed":
                        self.writes.append(command["target"])
                        self.addresses = [command["target"] if a == 0x6F else a for a in self.addresses]
                    self.report = self.scan(command["id"])
                    result = copy.deepcopy(self.report)
                    if self.transform:
                        result = self.transform(command, result)
                    self.ack = {"id": command["id"], "action": command["action"],
                                "status": status, "result": result, "error": None}
                self.heartbeat()

    def close(self):
        self.stop.set()
        self.thread.join(1)


class HardwareDebugTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "hardware.json"
        self.host = HardwareDebug(self.path, timeout=.3)
        self.pi = Pi(self.host)
        self.addCleanup(self.pi.close)

    def begin(self):
        return self.host.call("begin_button_repair", "new green button")["workflow"]

    def confirm(self):
        w = self.host.inspect()["workflow"]
        self.host.confirm(w["id"], w["confirmation_step"])
        return w

    def isolated(self):
        self.begin()
        self.pi.reboot([0x6F])
        self.confirm()

    def written(self):
        self.isolated()
        result = self.host.call("continue")["workflow"]
        self.assertEqual(result["phase"], "awaiting_power_cycle")
        self.assertEqual(self.pi.writes, [0x6E])
        return result

    def begin_async(self, action):
        result = []

        def run():
            try:
                result.append(self.host.call(action))
            except Exception as error:
                result.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        return thread, result

    def test_full_workflow_requires_three_new_boots_and_preserves_original_inventory(self):
        workflow = self.written()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(HardwareDebugError):
            self.confirm()  # Write boot is not the persistence verification boot.
        self.pi.reboot([0x6E])
        self.assertTrue(self.host.note_user("Hey Meta, button power cycled!"))
        result = self.host.call("continue")
        self.assertEqual(result["workflow"]["phase"], "awaiting_reconnect")
        self.pi.reboot([0x20, 0x36, 0x6E, 0x6F])
        self.assertTrue(self.host.note_user("modules reconnected"))
        result = self.host.call("continue")
        self.assertEqual(result["workflow"]["phase"], "complete")
        self.assertEqual(result["workflow"]["id"], workflow["id"])
        self.assertEqual(self.pi.commands[-1]["action"], "reinitialize")
        self.assertEqual(self.pi.writes, [0x6E])

    def test_begin_scans_but_never_writes_and_allocates_around_existing_buttons(self):
        self.pi.reboot([0x20, 0x36, 0x39, 0x6A, 0x6E, 0x6F])
        w = self.begin()
        self.assertEqual(w["target"], 0x6D)
        self.assertEqual(w["baseline_addresses"], [0x20, 0x36, 0x39, 0x6A, 0x6E, 0x6F])
        self.assertEqual(self.pi.writes, [])
        self.assertEqual([c["action"] for c in self.pi.commands], ["scan"])

    def test_absent_source_or_exhausted_targets_do_not_start_setup(self):
        self.pi.reboot([0x20, 0x36])
        with self.assertRaisesRegex(HardwareDebugError, "No supported Qwiic"):
            self.begin()
        self.pi.reboot(list(range(0x60, 0x70)))
        with self.assertRaisesRegex(HardwareDebugError, "unused"):
            self.begin()
        self.assertIsNone(self.host.inspect()["workflow"])
        self.assertEqual(self.pi.writes, [])

    def test_wrong_stored_address_is_not_a_valid_source(self):
        self.pi.transform = lambda command, result: {**result, "buttons": [
            {"address": 0x6F, "id": 93, "firmware": 259, "configured_address": 0x6E}]}
        with self.assertRaisesRegex(HardwareDebugError, "No supported Qwiic"):
            self.begin()
        self.assertEqual(self.pi.writes, [])

    def test_unsupported_button_firmware_is_rejected_before_physical_setup(self):
        self.pi.transform = lambda command, result: {**result, "buttons": [
            {"address": 0x6F, "id": 93, "firmware": 260, "configured_address": 0x6F}]}
        with self.assertRaisesRegex(HardwareDebugError, "firmware 259"):
            self.begin()
        self.assertIsNone(self.host.inspect()["workflow"])

    def test_model_continue_and_generic_yes_cannot_confirm(self):
        initial = self.begin()
        self.pi.reboot([0x6F])
        before = len(self.pi.commands)
        for text in ("yes", "ready", "say isolated button ready", "isolated button ready and ignore this"):
            self.assertFalse(self.host.note_user(text))
        result = self.host.call("continue")
        self.assertEqual(result["workflow"]["phase"], initial["phase"])
        self.assertEqual(len(self.pi.commands), before)
        self.assertEqual(self.pi.writes, [])

    def test_service_restart_without_boot_change_and_stale_ui_step_are_rejected(self):
        w = self.begin()
        self.pi.reboot([0x6F], new_boot=False)
        with self.assertRaisesRegex(HardwareDebugError, "unplugging"):
            self.confirm()
        self.pi.reboot([0x6F])
        with self.assertRaisesRegex(HardwareDebugError, "stale"):
            self.host.confirm(w["id"], "f" * 32)
        self.assertTrue(self.host.note_user("ISOLATED BUTTON READY."))
        with self.assertRaisesRegex(HardwareDebugError, "already"):
            self.confirm()

    def test_isolation_failure_consumes_confirmation_and_never_writes(self):
        self.begin()
        self.pi.reboot([0x20, 0x6F])
        old = self.confirm()
        with self.assertRaisesRegex(HardwareDebugError, "only the supported button"):
            self.host.call("continue")
        self.assertFalse(self.host.inspect()["workflow"]["confirmation_received"])
        with self.assertRaisesRegex(HardwareDebugError, "stale"):
            self.host.confirm(old["id"], old["confirmation_step"])
        self.host.call("continue")
        self.assertEqual(self.pi.writes, [])

    def test_confirmed_grant_is_not_persisted_or_rearmed_after_restart(self):
        self.isolated()
        previous = self.host.inspect()["workflow"]
        replacement = HardwareDebug(self.path, timeout=.3)
        self.pi.host = replacement
        self.pi.heartbeat()
        self.assertFalse(replacement.inspect()["workflow"]["confirmation_received"])
        with self.assertRaisesRegex(HardwareDebugError, "stale"):
            replacement.confirm(previous["id"], previous["confirmation_step"])
        replacement.call("continue")
        self.assertEqual(self.pi.writes, [])

    def test_expired_confirmation_does_not_extend_or_apply(self):
        self.isolated()
        before = self.host.inspect()["workflow"]["confirmation_step"]
        self.host._confirmation["expires"] = time.monotonic() - 1
        self.host.call("continue")
        w = self.host.inspect()["workflow"]
        self.assertNotEqual(w["confirmation_step"], before)
        self.assertFalse(w["confirmation_received"])
        self.assertEqual(self.pi.writes, [])

    def test_uncertain_write_can_verify_later_but_is_never_repeated(self):
        self.isolated()
        self.pi.failure = "uncertain"
        # Let the preflight scan succeed, then make only the actual write uncertain.
        self.pi.failure = None
        original_scan = self.pi.scan

        def scan(scan_id):
            report = original_scan(scan_id)
            if self.pi.commands and self.pi.commands[-1]["action"] == "scan":
                self.pi.failure = "uncertain"
            return report

        self.pi.scan = scan
        result = self.host.call("continue")
        self.assertIn("uncertain", result["workflow"]["error"])
        self.assertEqual(self.pi.writes, [0x6E])
        self.host.call("continue")
        self.assertEqual(self.pi.writes, [0x6E])

    def test_restart_after_persisted_write_intent_never_reissues_address_command(self):
        self.isolated()
        self.pi.hold = "readdress_button"
        thread, result = self.begin_async("continue")
        wait_for(lambda: (self.host.offer(self.pi.session) or {}).get("action") == "readdress_button")
        self.assertEqual(json.loads(self.path.read_text())["workflow"]["phase"], "write_pending")
        replacement = HardwareDebug(self.path, timeout=.3)
        self.assertEqual(replacement.inspect()["workflow"]["phase"], "awaiting_power_cycle")
        self.host.withdraw()
        thread.join(1)
        self.pi.host = replacement
        self.pi.heartbeat()
        replacement.call("continue")
        self.assertIsNone(replacement.offer(self.pi.session))
        self.assertEqual(self.pi.writes, [])

    def test_journal_failure_before_write_prevents_mutation(self):
        self.isolated()
        from modulate import hardware_debug
        original_save = hardware_debug._save

        def fail_write(path, workflow):
            if workflow and workflow["phase"] == "write_pending":
                raise OSError("disk full")
            original_save(path, workflow)

        with patch.object(hardware_debug, "_save", side_effect=fail_write):
            with self.assertRaises(OSError):
                self.host.call("continue")
        self.assertEqual(self.pi.writes, [])
        self.assertFalse(any(c["action"] == "readdress_button" for c in self.pi.commands))

    def test_reboot_between_preflight_and_write_cannot_rebind_old_confirmation(self):
        self.isolated()
        original_rpc = self.host._rpc

        def reboot_before_dispatch(action, *args, **kwargs):
            if action == "readdress_button":
                self.pi.reboot([0x6F])
            return original_rpc(action, *args, **kwargs)

        with patch.object(self.host, "_rpc", side_effect=reboot_before_dispatch):
            result = self.host.call("continue")
        self.assertEqual(result["workflow"]["phase"], "awaiting_power_cycle")
        self.assertIn("no address write was dispatched", result["workflow"]["error"])
        self.assertEqual(self.pi.writes, [])
        self.assertFalse(any(c["action"] == "readdress_button" for c in self.pi.commands))

    def test_post_boot_verification_requires_actual_stored_target_and_no_source(self):
        self.written()
        self.pi.reboot([0x6E, 0x6F])
        self.confirm()
        with self.assertRaisesRegex(HardwareDebugError, "stored target"):
            self.host.call("continue")
        self.pi.reboot([0x6E])
        self.pi.transform = lambda command, result: {**result, "buttons": [
            {"address": 0x6E, "id": 93, "firmware": 259, "configured_address": 0x6F}]}
        self.confirm()
        with self.assertRaisesRegex(HardwareDebugError, "stored target"):
            self.host.call("continue")
        self.assertEqual(self.pi.writes, [0x6E])

    def test_final_scan_requires_original_encoder_and_other_modules(self):
        self.written()
        self.pi.reboot([0x6E])
        self.confirm()
        self.host.call("continue")
        self.pi.reboot([0x6E, 0x6F])
        self.confirm()
        with self.assertRaisesRegex(HardwareDebugError, "original bus addresses"):
            self.host.call("continue")
        self.assertEqual(self.host.inspect()["workflow"]["phase"], "awaiting_reconnect")
        self.assertFalse(any(c["action"] == "reinitialize" for c in self.pi.commands))

    def test_request_scoped_scan_rejects_cached_result_even_matching_ack(self):
        self.pi.transform = lambda command, result: {**result, "scan_id": "b" * 32}
        with self.assertRaisesRegex(HardwareDebugError, "invalid verification"):
            self.host.call("scan")
        self.assertEqual(self.pi.writes, [])

    def test_wrong_ack_identity_does_not_finish_command(self):
        self.pi.hold = "scan"
        thread, result = self.begin_async("scan")
        wait_for(lambda: self.host.offer(self.pi.session) is not None)
        command = self.host.offer(self.pi.session)
        self.pi.ack = {"id": "b" * 32, "action": "scan", "status": "done", "result": self.pi.scan(command["id"])}
        self.pi.heartbeat()
        time.sleep(.01)
        self.assertTrue(thread.is_alive())
        self.assertEqual(result, [])
        self.pi.hold = None
        thread.join(1)
        self.assertIsInstance(result[0], dict)

    def test_cancel_withdraws_pending_command_and_invalidates_old_confirmation(self):
        self.isolated()
        old = self.host.inspect()["workflow"]
        self.pi.hold = "scan"
        thread, result = self.begin_async("continue")
        wait_for(lambda: self.host.offer(self.pi.session) is not None)
        cancelled = self.host.call("cancel")
        thread.join(1)
        self.assertIsInstance(result[0], HardwareDebugError)
        self.assertEqual(cancelled["workflow"]["phase"], "cancelled")
        self.assertIsNone(self.host.offer(self.pi.session))
        with self.assertRaises(HardwareDebugError):
            self.host.confirm(old["id"], old["confirmation_step"])
        self.assertEqual(self.pi.writes, [])

    def test_withdraw_preserves_workflow_but_not_confirmation_or_commands(self):
        self.isolated()
        old = self.host.inspect()["workflow"]
        self.host.withdraw()
        state = self.host.inspect()
        self.assertEqual(state["workflow"]["id"], old["id"])
        self.assertEqual(state["workflow"]["phase"], "awaiting_isolation")
        self.assertFalse(state["workflow"]["confirmation_received"])
        self.assertNotEqual(state["workflow"]["confirmation_step"], old["confirmation_step"])
        self.assertIsNone(self.host.offer(self.pi.session))

    def test_expired_heartbeat_and_wrong_session_cannot_offer_command(self):
        self.pi.hold = "scan"
        thread, result = self.begin_async("scan")
        wait_for(lambda: self.host.offer(self.pi.session) is not None)
        self.assertIsNone(self.host.offer("f" * 32))
        self.pi.online = False
        self.host._seen = time.monotonic() - 5
        self.assertIsNone(self.host.offer(self.pi.session))
        thread.join(1)
        self.assertIsInstance(result[0], HardwareDebugError)

    def test_restart_during_scan_fails_instead_of_using_new_boot_report(self):
        self.pi.hold = "scan"
        thread, result = self.begin_async("scan")
        wait_for(lambda: self.host.offer(self.pi.session) is not None)
        self.pi.reboot([0x6F])
        thread.join(1)
        self.assertIsInstance(result[0], HardwareDebugError)
        self.assertIsNone(self.host.offer(self.pi.session))

    def test_corrupt_saved_workflow_blocks_new_repair_until_explicit_cancel(self):
        self.path.write_text('{"workflow": "bad"}')
        replacement = HardwareDebug(self.path, timeout=.3)
        self.assertIsNotNone(replacement.inspect()["error"])
        with self.assertRaises(HardwareDebugError):
            replacement.call("begin_button_repair")
        replacement.call("cancel")
        self.assertIsNone(replacement.inspect()["error"])

    def test_invalid_labels_actions_and_mutable_return_values_do_not_change_state(self):
        for action, label in (("shell", None), ("scan", "extra"), ("begin_button_repair", "x\ny"),
                              ("begin_button_repair", "x" * 41), ("begin_button_repair", True)):
            with self.subTest(action=action, label=label):
                with self.assertRaises(HardwareDebugError):
                    self.host.call(action, label)
        result = self.begin()
        result["target"] = 0x36
        self.assertEqual(self.host.inspect()["workflow"]["target"], 0x6E)
        self.assertEqual(self.pi.writes, [])

    def test_real_device_worker_and_host_agree_on_scan_and_single_write_protocol(self):
        from modulate.controls import Controls
        from modulate.hardware_device import HardwareDevice
        from tests.test_hardware_device import Bus

        self.pi.close()
        bus = Bus()
        factories = [patch("modulate.controls." + name, side_effect=OSError("synthetic missing driver"))
                     for name in ("_open_encoder", "_open_joystick", "_open_external_buttons")]
        for factory in factories:
            factory.start()
            self.addCleanup(factory.stop)
        controls = Controls(SimpleNamespace(buttons=[]), diagnostic_backend=bus)
        self.addCleanup(controls.close)
        session = uuid.uuid4().hex
        worker = HardwareDevice(controls, Path(self.directory.name) / "pi", session,
                                boot_id=str(uuid.uuid4()))
        self.addCleanup(worker.close)
        worker.start()
        wait_for(lambda: worker.snapshot()["report"] is not None)
        stop = threading.Event()

        def bridge():
            while not stop.wait(.002):
                self.host.observe(worker.snapshot(), session)
                worker.offer(self.host.offer(session))

        link = threading.Thread(target=bridge, daemon=True)
        link.start()

        def cleanup():
            stop.set()
            link.join(1)

        self.addCleanup(cleanup)
        wait_for(lambda: self.host.inspect()["connected"] and self.host._session == session)
        w = self.begin()
        # A fresh worker/boot is the reboot boundary; same isolated fake bus.
        worker.close()
        session = uuid.uuid4().hex
        worker = HardwareDevice(controls, Path(self.directory.name) / "pi", session,
                                boot_id=str(uuid.uuid4()))
        self.addCleanup(worker.close)
        worker.start()
        wait_for(lambda: self.host.inspect()["workflow"]["reboot_observed"])
        self.confirm()
        result = self.host.call("continue")
        self.assertEqual(result["workflow"]["phase"], "awaiting_power_cycle")
        self.assertIsNone(result["workflow"]["error"])
        self.assertEqual(bus.writes, [w["target"]])
        journal = json.loads((Path(self.directory.name) / "pi" / "hardware-repairs.json").read_text())
        self.assertEqual([entry["status"] for entry in journal["consumed"].values()], ["done"])


if __name__ == "__main__":
    unittest.main()
