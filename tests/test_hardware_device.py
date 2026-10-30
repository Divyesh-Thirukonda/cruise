"""Synthetic hardware repair tests. No test opens a physical I2C adapter."""
from copy import deepcopy
import errno
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

from modulate.controls import ButtonDiagnostics, BUTTON_TARGETS, Controls
from modulate.hardware_device import HardwareDevice


def button(address=0x6F, firmware=259):
    return {"address": address, "id": 93, "firmware": firmware,
            "configured_address": address}


class Bus:
    def __init__(self):
        self.devices = {0x6F: button()}
        self.writes = []
        self.fail_write = False
        self.revert = False
        self.scan_error = False
        self.on_read = None
        self.on_write = None

    def scan(self):
        if self.scan_error:
            raise OSError("private diagnostic text must not escape")
        return sorted(self.devices)

    def button(self, address):
        if self.on_read:
            self.on_read()
        return deepcopy(self.devices[address])

    def readdress_factory_button(self, target):
        if self.on_write:
            self.on_write()
        self.writes.append(target)
        if not self.revert:
            self.devices.pop(0x6F)
            self.devices[target] = button(target)
        if self.fail_write:
            raise OSError("Write completed but transport lost acknowledgement")


class HardwareTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bus = Bus()
        self.now = 1000.0
        self.session, self.boot = uuid.uuid4().hex, str(uuid.uuid4())
        self.factories = [patch("modulate.controls." + name, side_effect=OSError("missing"))
                          for name in ("_open_encoder", "_open_joystick", "_open_external_buttons", "open_imu")]
        self.mocks = [p.start() for p in self.factories]
        for p in self.factories:
            self.addCleanup(p.stop)
        self.controls = Controls(SimpleNamespace(buttons=[]), diagnostic_backend=self.bus)
        self.worker = self.make_worker()

    def test_background_discovery_publishes_new_address_without_readdressing(self):
        self.worker._scan(uuid.uuid4().hex)
        self.bus.devices[0x39] = {}
        previous = self.worker._last_discovery
        with patch('modulate.hardware_device.time.monotonic', return_value=previous + 16):
            self.worker.refresh_inventory()
        self.assertIn(0x39, self.worker.snapshot()['report']['addresses'])
        self.assertEqual(self.bus.writes, [])
        self.assertNotIn('0x39', str(self.controls.capabilities()['controls']))

    def make_worker(self):
        worker = HardwareDevice(self.controls, self.directory.name, self.session,
                                boot_id=self.boot, clock=lambda: self.now)
        self.addCleanup(worker.close)
        return worker

    def command(self, action="readdress_button", target=0x6E):
        return {"id": uuid.uuid4().hex, "session": self.session, "boot_id": self.boot,
                "expires_at": self.now + 30, "action": action,
                "target": target if action == "readdress_button" else None}

    def wait_for(self, predicate):
        end = time.monotonic() + 2
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(0.005)
        self.fail("Worker did not finish within two seconds")

    def run_command(self, command=None):
        command = command or self.command()
        self.worker.start()
        self.assertTrue(self.worker.offer(command))
        return self.wait_for(lambda: (ack if (ack := self.worker.snapshot()["ack"])
                                      and ack["id"] == command["id"] else None))

    def test_startup_only_scans_and_reports_actual_boot_session_without_ack(self):
        self.worker.start()
        self.wait_for(lambda: self.worker.snapshot()["report"])
        snapshot = self.worker.snapshot()
        self.assertEqual((snapshot["boot_id"], snapshot["session"]), (self.boot, self.session))
        self.assertTrue(snapshot["supported"])
        self.assertIsNone(snapshot["ack"])
        self.assertEqual(snapshot["report"]["buttons"], [button()])
        self.assertEqual(self.bus.writes, [])
        snapshot["report"]["addresses"].clear()
        self.assertEqual(self.worker.snapshot()["report"]["addresses"], [0x6F])

    def test_driver_install_is_session_bound_and_duplicate_command_is_not_reexecuted(self):
        setup=Mock()
        setup.inspect.return_value={'catalog':[], 'last_result':{'verified':True}}
        self.worker.driver_setup=setup
        command={**self.command('scan'),'action':'install_driver','target':'lsm6ds3trc'}
        self.assertFalse(self.worker.offer({**command,'session':'b'*32}))
        self.assertFalse(self.worker.offer({**command,'target':'shell'}))
        ack=self.run_command(command)
        self.assertEqual(ack['status'],'done')
        self.assertEqual(ack['result']['scan_id'],command['id'])
        self.worker.offer(command)
        setup.install.assert_called_once()
        self.assertEqual(self.bus.writes,[])

    def test_driver_install_withdrawal_reaches_installer_before_commit(self):
        from modulate.driver_setup import DriverSetupError
        setup=Mock();setup.inspect.return_value={'catalog':[]}
        def install(driver,controls,allowed,guard):
            self.assertTrue(allowed())
            self.worker.offer(None)
            with guard():self.assertFalse(allowed())
            raise DriverSetupError('Driver setup cancelled, disconnected or expired')
        setup.install.side_effect=install;self.worker.driver_setup=setup
        command={**self.command('scan'),'action':'install_driver','target':'lsm6ds3trc'}
        ack=self.run_command(command)
        self.assertEqual(ack['status'],'failed');self.assertIn('cancelled',ack['error'])
        self.assertEqual(self.bus.writes,[])

    def test_scan_and_reinitialize_never_write_address_or_reset_encoder(self):
        for action in ("scan", "reinitialize"):
            command = self.command(action)
            ack = self.run_command(command)
            self.assertEqual(ack["status"], "done")
            self.assertEqual(ack["result"]["scan_id"], command["id"])
        self.assertEqual(self.bus.writes, [])
        self.assertGreater(self.mocks[0].call_count, 1)  # Missing driver was retried.

    def test_only_factory_button_can_be_moved_and_consumed_before_write(self):
        command = self.command(target=0x6D)
        def inspect_journal():
            path = Path(self.directory.name) / "hardware-repairs.json"
            self.assertEqual(json.loads(path.read_text())["consumed"][command["id"]],
                             {"target": 0x6D, "status": "consumed"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.bus.on_write = inspect_journal
        ack = self.run_command(command)
        self.assertEqual(ack["status"], "done")
        self.assertEqual(ack["result"]["addresses"], [0x6D])
        self.assertEqual(ack["result"]["buttons"], [button(0x6D)])
        self.assertTrue(any("diagnostic-only" in w for w in ack["result"]["warnings"]))
        self.worker.offer(command)
        self.assertEqual(self.bus.writes, [0x6D])

    def test_collision_preconditions_target_occupied_or_any_other_responder_reject(self):
        for address in (0x6E, 0x20, 0x36, 0x39, 0x6A):
            with self.subTest(address=address):
                self.bus.devices = {0x6F: button(), address: button(address)}
                self.assertEqual(self.run_command()["status"], "failed")
        self.assertEqual(self.bus.writes, [])

    def test_wrong_identity_firmware_or_address_readback_reject(self):
        for bad in ({**button(), "id": 92}, button(firmware=258),
                    {**button(), "configured_address": 0x6D}):
            with self.subTest(bad=bad):
                self.bus.devices = {0x6F: bad}
                self.assertEqual(self.run_command()["status"], "failed")
        self.assertEqual(self.bus.writes, [])

    def test_stale_session_boot_expiry_malformed_and_unsupported_target_reject(self):
        changes = [{"session": uuid.uuid4().hex}, {"boot_id": str(uuid.uuid4())},
                   {"expires_at": self.now}, {"expires_at": float("nan")},
                   {"expires_at": self.now + 61}, {"action": []}, {"target": 0x6A},
                   {"target": 0x6F}, {"target": True}, {"source": 0x6F}]
        for changed in changes:
            self.assertFalse(self.worker.offer({**self.command(), **changed}))
        self.assertEqual(self.bus.writes, [])

    def test_withdrawal_while_preflight_is_blocked_prevents_write(self):
        self.worker.start()
        self.wait_for(lambda: self.worker.snapshot()["report"])
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.bus.on_read = lambda: (entered.set(), release.wait(1))
        command = self.command()
        self.worker.offer(command)
        self.assertTrue(entered.wait(1))
        self.worker.offer(None)
        self.worker.offer(None)
        release.set()
        ack = self.wait_for(lambda: self.worker.snapshot()["ack"])
        self.assertEqual(ack["status"], "failed")
        self.assertEqual(self.bus.writes, [])

    def test_withdrawal_during_durable_consumption_prevents_write(self):
        original = self.worker._save
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def blocked_save():
            original()
            entered.set()
            release.wait(1)
        with patch.object(self.worker, "_save", side_effect=blocked_save):
            self.worker.start()
            self.worker.offer(self.command())
            self.assertTrue(entered.wait(1))
            self.worker.offer(None)
            release.set()
            self.wait_for(lambda: self.worker.snapshot()["ack"])
        self.assertEqual(self.bus.writes, [])

    def test_expiry_during_preflight_prevents_write(self):
        self.worker.start()
        self.wait_for(lambda: self.worker.snapshot()["report"])
        self.bus.on_read = lambda: setattr(self, "now", self.now + 31)
        self.assertEqual(self.run_command()["status"], "failed")
        self.assertEqual(self.bus.writes, [])

    def test_poll_and_repair_share_one_lock(self):
        self.worker.start()
        self.wait_for(lambda: self.worker.snapshot()["report"])
        entered, release, polled = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.bus.on_read = lambda: (entered.set(), release.wait(1))
        command = self.command("scan")
        self.worker.offer(command)
        self.assertTrue(entered.wait(1))
        thread = threading.Thread(target=lambda: (self.controls.poll(), polled.set()))
        thread.start()
        try:
            self.assertFalse(polled.wait(0.02))
        finally:
            release.set()
            thread.join(1)
        self.assertTrue(polled.is_set())

    def test_uncertain_write_is_not_replayed_even_after_worker_restart(self):
        command = self.command()
        self.bus.fail_write = True
        ack = self.run_command(command)
        self.assertEqual(ack["status"], "uncertain")
        self.assertNotIn("transport", ack["error"])
        self.worker.close()
        # Even if the isolated board is later factory-addressed again, the
        # consumed request cannot become permission to mutate it a second time.
        self.bus.devices = {0x6F: button()}
        self.worker = self.make_worker()
        self.assertEqual(self.run_command(command)["status"], "uncertain")
        self.assertEqual(self.bus.writes, [0x6E])

    def test_interrupted_consumed_journal_never_replays_on_startup_or_offer(self):
        command = self.command()
        path = Path(self.directory.name) / "hardware-repairs.json"
        path.write_text(json.dumps({"version": 1, "consumed": {
            command["id"]: {"target": 0x6E, "status": "consumed"}}}))
        self.worker = self.make_worker()
        self.assertEqual(self.run_command(command)["status"], "uncertain")
        self.assertEqual(self.bus.writes, [])

    def test_failed_readback_is_uncertain_without_automatic_retry(self):
        self.bus.revert = True
        command = self.command()
        self.assertEqual(self.run_command(command)["status"], "uncertain")
        self.worker.offer(command)
        self.assertEqual(self.bus.writes, [0x6E])

    def test_disk_failure_and_corrupt_journal_block_writes_but_allow_scan(self):
        with patch.object(self.worker, "_save", side_effect=OSError("disk full")):
            self.assertEqual(self.run_command()["status"], "failed")
        self.assertEqual(self.bus.writes, [])
        self.worker.close()
        (Path(self.directory.name) / "hardware-repairs.json").write_text("{broken")
        self.worker = self.make_worker()
        ack = self.run_command(self.command("scan"))
        self.assertEqual(ack["status"], "done")
        self.assertTrue(any("history" in w for w in ack["result"]["warnings"]))
        self.assertEqual(self.run_command()["status"], "failed")
        self.assertEqual(self.bus.writes, [])

    def test_scan_failure_does_not_claim_empty_available_bus(self):
        self.bus.scan_error = True
        ack = self.run_command(self.command("scan"))
        self.assertEqual(ack["status"], "failed")
        self.assertFalse(ack["result"]["bus_available"])
        self.assertEqual(ack["result"]["addresses"], [])
        self.assertNotIn("private diagnostic", json.dumps(self.worker.snapshot()))

    def test_unknown_responders_reported_without_register_identity_reads(self):
        self.bus.devices = {0x20: None, 0x36: None, 0x6A: None}
        self.bus.button = Mock(side_effect=AssertionError("Unknown register read"))
        ack = self.run_command(self.command("scan"))
        self.assertEqual(ack["status"], "done")
        self.assertEqual(ack["result"]["buttons"], [])
        self.bus.button.assert_not_called()


class NativeBackendTests(unittest.TestCase):
    def test_fixed_identity_reads_and_exact_single_write(self):
        driver = Mock()
        registers = {0x00: 93, 0x01: 3, 0x02: 1, 0x1F: 0x6F}
        driver.readByte.side_effect = lambda address, register: registers[register]
        backend = ButtonDiagnostics(driver)
        self.assertEqual(backend.button(0x6F), button())
        driver.writeByte.assert_not_called()
        backend.readdress_factory_button(0x6E)
        driver.writeByte.assert_called_once_with(0x6F, 0x1F, 0x6E)
        for invalid in (0x6F, 0x6A, 0x20, True):
            with self.assertRaises(ValueError):
                backend.readdress_factory_button(invalid)
        self.assertEqual(driver.writeByte.call_count, 1)

    def test_scan_distinguishes_normal_nack_from_adapter_failure(self):
        driver = Mock()
        def probe(address):
            if address != 0x6F:
                raise OSError(errno.ENXIO, "NACK")
        driver.i2cbus.write_quick.side_effect = probe
        driver.i2cbus.read_byte.side_effect = probe
        backend = ButtonDiagnostics(driver)
        self.assertEqual(backend.scan(), [0x6F])
        driver.i2cbus.write_quick.side_effect = OSError(errno.EIO, "Adapter failure")
        with self.assertRaises(OSError):
            backend.scan()
        driver.writeByte.assert_not_called()

    def test_scan_uses_receive_byte_for_sensitive_ranges_and_quick_elsewhere(self):
        driver = Mock()
        def receive(address):
            if address != 0x36:
                raise OSError(errno.ENXIO, "NACK")
            return 0
        driver.i2cbus.read_byte.side_effect = receive
        driver.i2cbus.write_quick.side_effect = OSError(errno.ENXIO, "NACK")
        self.assertEqual(ButtonDiagnostics(driver).scan(), [0x36])
        read_addresses = {call.args[0] for call in driver.i2cbus.read_byte.call_args_list}
        quick_addresses = {call.args[0] for call in driver.i2cbus.write_quick.call_args_list}
        self.assertEqual(read_addresses, set(range(0x30, 0x38)) | set(range(0x50, 0x60)))
        self.assertFalse(read_addresses & quick_addresses)
        self.assertEqual(read_addresses | quick_addresses, set(range(0x08, 0x78)))
        driver.writeByte.assert_not_called()


if __name__ == "__main__":
    unittest.main()
