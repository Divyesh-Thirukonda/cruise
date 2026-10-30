"""Synthetic driver packs and bus. No registry/network or physical I2C access."""
from contextlib import nullcontext
import hashlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from modulate.driver_setup import DriverSetup, DriverSetupError, DRIVER_ID, PREFIXES, PACK, _unpack
from modulate.controls import ButtonDiagnostics


def wheel(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        for name, value in files.items():z.writestr(name, value)
    return stream.getvalue()


class DriverSetupTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.blob = wheel({'adafruit_lsm6ds/__init__.py': 'VALUE = "verified fixture"\n'})
        self.wheels = [('https://files.pythonhosted.org/synthetic.whl', hashlib.sha256(self.blob).hexdigest(), ('adafruit_lsm6ds',))]
        self.addCleanup(patch.stopall)
        patch('modulate.driver_setup.WHEELS', self.wheels).start()
        self.identity = {'address': 106, 'who_am_i': 106}
        self.backend = SimpleNamespace(imu_identity=lambda:self.identity)
        self.old = object();self.bus = Mock()
        self.controls = SimpleNamespace(bus_lock=threading.RLock(), hardware_backend=lambda:self.backend,
            capabilities=lambda:{'controls':['imu'] if self.controls._status['imu']=='ready' else []},
            _imu=self.old, _bus=self.bus, _imu_address=106, _status={'imu':'read_error'})
        self.fetch = Mock(return_value=self.blob)
        self.store = DriverSetup(self.root, fetch=self.fetch)
        self.sensor = SimpleNamespace(acceleration=(0,0,9.8),gyro=(0,0,0))
        self.open = patch('modulate.driver_setup.open_imu', return_value=(self.sensor,self.bus,106)).start()
        self.old_path = list(sys.path)
        self.modules = {k:v for k,v in sys.modules.copy().items() if k.split('.')[0] in PREFIXES}
        self.addCleanup(self.restore_imports)

    def restore_imports(self):
        sys.path[:] = self.old_path
        for key in list(sys.modules):
            if key.split('.')[0] in PREFIXES:del sys.modules[key]
        sys.modules.update(self.modules)

    def install(self, allowed=lambda:True):
        return self.store.install(DRIVER_ID,self.controls,allowed,nullcontext)

    def test_install_checks_real_readings_before_commit_and_survives_restart(self):
        def opening(bus):
            import adafruit_lsm6ds
            self.assertEqual(adafruit_lsm6ds.VALUE,'verified fixture')
            self.assertFalse(self.store.path.exists())
            return self.sensor,bus,106
        self.open.side_effect=opening
        result=self.install()
        self.assertTrue(result['verified']);self.assertEqual(result['readings']['imu_az'],9.8)
        self.assertIs(self.controls._imu,self.sensor)
        self.assertEqual(json.loads(self.store.path.read_text()),{'driver':DRIVER_ID,'pack':PACK})
        self.assertEqual(self.store.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.install()['status'],'already_ready')
        self.fetch.assert_called_once()
        self.restore_imports()
        restored=DriverSetup(self.root);restored.restore()
        self.assertTrue(restored.active);self.assertEqual(sys.path[0],str(restored.root))

    def test_wrong_chip_and_unknown_driver_never_download(self):
        for target,identity in [(DRIVER_ID,None),('shell',self.identity)]:
            self.identity=identity
            with self.assertRaises(DriverSetupError):self.store.install(target,self.controls,lambda:True,nullcontext)
        self.fetch.assert_not_called();self.assertIs(self.controls._imu,self.old)
        self.assertFalse(self.store.path.exists())

    def test_bad_checksum_and_partial_download_leave_previous_driver_untouched(self):
        for result in [b'corrupt',OSError('PRIVATE transport message')]:
            self.fetch.side_effect=result if isinstance(result,Exception) else None
            self.fetch.return_value=result
            with self.assertRaises(DriverSetupError) as e:self.install()
            self.assertNotIn('PRIVATE',str(e.exception))
            self.assertIs(self.controls._imu,self.old);self.assertFalse(self.store.path.exists())
            self.assertEqual(list(self.root.glob('.staging-*')),[])
        self.open.assert_not_called()

    def test_invalid_sensor_sample_rolls_back_imports_and_handle(self):
        oldmodule=SimpleNamespace(VALUE='old fixture');sys.modules['adafruit_lsm6ds']=oldmodule
        self.sensor.gyro=(float('nan'),0,0)
        with self.assertRaises(DriverSetupError):self.install()
        self.assertIs(sys.modules['adafruit_lsm6ds'],oldmodule)
        self.assertIs(self.controls._imu,self.old);self.assertEqual(sys.path,self.old_path)
        self.assertFalse(self.store.path.exists());self.bus.deinit.assert_not_called()

    def test_cancel_after_download_never_publishes(self):
        cancelled=False
        def fetch(url,allowed):
            nonlocal cancelled
            cancelled=True;return self.blob
        self.store.fetch=fetch
        with self.assertRaises(DriverSetupError):self.install(lambda:not cancelled)
        self.assertFalse(self.store.path.exists());self.open.assert_not_called()

    def test_cancel_at_commit_boundary_restores_previous_imports(self):
        @__import__('contextlib').contextmanager
        def guard():
            self.allowed=False;yield
        self.allowed=True
        with self.assertRaises(DriverSetupError):
            self.store.install(DRIVER_ID,self.controls,lambda:self.allowed,guard)
        self.assertIs(self.controls._imu,self.old);self.assertFalse(self.store.path.exists())
        self.assertEqual(sys.path,self.old_path)

    def test_device_change_during_download_rejected_without_opening_driver(self):
        def fetch(url,allowed):self.identity=None;return self.blob
        self.store.fetch=fetch
        with self.assertRaises(DriverSetupError):self.install()
        self.open.assert_not_called();self.assertFalse(self.store.path.exists())

    def test_pointer_write_failure_rolls_back_live_handle(self):
        from modulate.driver_setup import _private_json
        def saving(path,value):
            if path==self.store.path:raise OSError('disk full')
            return _private_json(path,value)
        with patch('modulate.driver_setup._private_json',side_effect=saving),self.assertRaises(DriverSetupError):self.install()
        self.assertIs(self.controls._imu,self.old);self.assertFalse(self.store.path.exists())
        self.assertEqual(sys.path,self.old_path)

    def test_restart_ignores_uncommitted_or_tampered_pack(self):
        self.sensor.acceleration=(0,0,0)
        with self.assertRaises(DriverSetupError):self.install()
        restored=DriverSetup(self.root);restored.restore();self.assertFalse(restored.active)
        self.sensor.acceleration=(0,0,9.8);self.install();self.restore_imports()
        (self.store.root/'adafruit_lsm6ds/__init__.py').write_text('tampered')
        restored=DriverSetup(self.root);restored.restore()
        self.assertFalse(restored.active);self.assertIsNotNone(restored.error)
        self.assertEqual(sys.path,self.old_path)

    def test_download_does_not_hold_input_bus_lock(self):
        def fetch(url,allowed):
            result=[]
            def other():
                success=self.controls.bus_lock.acquire(timeout=.1);result.append(success)
                if success:self.controls.bus_lock.release()
            t=threading.Thread(target=other);t.start();t.join(1)
            self.assertEqual(result,[True]);return self.blob
        self.store.fetch=fetch;self.install()

    def test_archive_cannot_write_outside_pack_or_add_startup_code(self):
        for path in ('../escape.py','/escape.py','unrelated/file.py','adafruit_lsm6ds/run.pth'):
            data=wheel({path:'bad'})
            with self.subTest(path=path),self.assertRaises(DriverSetupError):
                _unpack(data,hashlib.sha256(data).hexdigest(),('adafruit_lsm6ds',),self.root)

    def test_identity_checks_documented_register_and_not_just_address_ack(self):
        driver=Mock();driver.readByte.side_effect=[0x00,0x6A]
        identity=ButtonDiagnostics(driver).imu_identity()
        self.assertEqual(identity,{'address':0x6B,'who_am_i':0x6A})
        self.assertEqual([c.args for c in driver.readByte.call_args_list],[(0x6A,0x0F),(0x6B,0x0F)])
        driver.writeByte.assert_not_called()
