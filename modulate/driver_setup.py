"""Trusted, hash-pinned pure-Python driver packs; never model-supplied code.

Wheels and licenses: Adafruit LSM6DS 4.6.3 and Register 1.13.0 (MIT),
verified against their versioned PyPI metadata on 2026-10-30. The first supported
pack is the owned LSM6DS3TR-C. Blinka/BusDevice/I2C remain base prerequisites.
"""
from contextlib import contextmanager
import hashlib
import importlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import time
import urllib.request
import zipfile

from .imu import motion_sample, open_imu

DRIVER_ID = "lsm6ds3trc"
WHEELS = (
    ("https://files.pythonhosted.org/packages/26/1b/1c385b5dfefe8a95e51c85de0b888bc8ed4175fd1e7c20e10a069fe384ff/adafruit_circuitpython_lsm6ds-4.6.3-py3-none-any.whl",
     "079351c8ef3ce9a375ad617664a59aad276a16c3891844d7ee30f9583147d6b2",
     ("adafruit_lsm6ds", "adafruit_circuitpython_lsm6ds-4.6.3.dist-info")),
    ("https://files.pythonhosted.org/packages/d1/a0/9cf4fcfbe0ab7b62bf010f0f005f626df5b35dc98f8d6871e2ad15f50c87/adafruit_circuitpython_register-1.13.0-py3-none-any.whl",
     "fba55bf5d2cde3af77b7a8f9d7d97a6dc08697cff0d5977edadf83b90745066d",
     ("adafruit_register", "adafruit_circuitpython_register-1.13.0.dist-info")),
)
PACK = hashlib.sha256(json.dumps(WHEELS).encode()).hexdigest()
PREFIXES = ("adafruit_lsm6ds", "adafruit_register")


class DriverSetupError(ValueError):
    pass


def _check(allowed):
    if not allowed():
        raise DriverSetupError("Driver setup cancelled, disconnected or expired")


def _fetch(url, allowed):
    data = bytearray()
    with urllib.request.urlopen(url, timeout=5) as response:
        if not response.geturl().startswith("https://files.pythonhosted.org/"):
            raise DriverSetupError("Driver download source changed")
        while True:
            _check(allowed)
            chunk = response.read(16384)
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            if len(data) > 1_000_000:
                raise DriverSetupError("Driver download exceeded size limit")


def _unpack(data, expected, roots, destination):
    if hashlib.sha256(data).hexdigest() != expected:
        raise DriverSetupError("Driver download checksum did not match")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        items = archive.infolist()
        if len(items) > 256 or sum(i.file_size for i in items) > 4_000_000:
            raise DriverSetupError("Driver archive exceeded size limit")
        for item in items:
            name = PurePosixPath(item.filename)
            if (name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] not in roots
                    or '\\' in item.filename or stat.S_ISLNK(item.external_attr >> 16)
                    or name.suffix in {'.pth', '.so', '.dll', '.dylib'}):
                raise DriverSetupError("Unsupported driver archive layout")
            if item.is_dir():
                continue
            path = destination.joinpath(*name.parts)
            if path.exists():
                raise DriverSetupError("Duplicate driver archive member")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(item))


def _files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
            and p.name != 'verified.json'}


def _private_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.driver-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _imports(root):
    """Swap only this pack's modules; callers serialize physical driver access."""
    selected = lambda name: any(name == p or name.startswith(p + '.') for p in PREFIXES)
    old_modules = {k: v for k, v in sys.modules.copy().items() if selected(k)}
    old_path = list(sys.path)
    for name in old_modules:
        del sys.modules[name]
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield
    except BaseException:
        for name in list(sys.modules):
            if selected(name):
                del sys.modules[name]
        sys.modules.update(old_modules)
        sys.path[:] = old_path
        importlib.invalidate_caches()
        raise


class DriverSetup:
    def __init__(self, directory, *, fetch=_fetch):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'active.json'
        self.root = self.directory / PACK
        self.fetch = fetch
        self.error = None
        self.last_result = None
        self.active = False

    def _verified(self):
        if self.root.is_symlink() or not self.root.is_dir():
            return False
        try:
            manifest = json.loads((self.root / 'verified.json').read_text())
            return (not any(p.is_symlink() for p in self.root.rglob('*')) and
                    manifest['pack'] == PACK and manifest['files'] == _files(self.root)
                    and bool(manifest['files']))
        except (OSError, ValueError, KeyError):
            return False

    def restore(self):
        """Load only a committed verified pack. Partial downloads are inert."""
        if not self.path.exists():
            return
        try:
            if json.loads(self.path.read_text()) != {'driver': DRIVER_ID, 'pack': PACK} or not self._verified():
                raise DriverSetupError("Saved driver pack failed integrity verification")
            sys.path.insert(0, str(self.root))
            self.active = True
        except (OSError, ValueError):
            self.error = "Saved driver pack is unavailable; base drivers retained"

    def inspect(self, controls):
        try:
            with controls.bus_lock:
                identity = controls.hardware_backend().imu_identity()
        except Exception:
            identity = None
        ready = 'imu' in controls.capabilities()['controls']
        return {'catalog': [{'id': DRIVER_ID, 'model': 'LSM6DS3TR-C',
                            'packages': ['adafruit-circuitpython-lsm6ds==4.6.3', 'adafruit-circuitpython-register==1.13.0'],
                            'identity': identity, 'input_ready': ready,
                            'managed': self.active,
                            'installable': identity is not None}],
                'last_result': self.last_result, 'error': self.error}

    def install(self, driver, controls, allowed, commit_guard):
        if driver != DRIVER_ID:
            raise DriverSetupError("Driver is not in the supported catalog")
        _check(allowed)
        with controls.bus_lock:
            identity = controls.hardware_backend().imu_identity()
        if identity is None:
            raise DriverSetupError("LSM6DS3TR-C identity was not verified; no driver installed")
        if self.active and self._verified() and 'imu' in controls.capabilities()['controls']:
            self.last_result = {'driver': driver, 'status': 'already_ready', 'verified': True}
            return self.last_result
        staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=self.directory))
        try:
            if not self._verified():
                for url, digest, roots in WHEELS:
                    _check(allowed)
                    _unpack(self.fetch(url, allowed), digest, roots, staging)
                _private_json(staging / 'verified.json', {'pack': PACK, 'files': _files(staging)})
                _check(allowed)
                if self.root.exists():
                    # Keep a corrupt pack for diagnosis; never execute it.
                    self.root.rename(self.directory / ('.rejected-' + str(time.time_ns())))
                staging.rename(self.root)
            # Network/download work never owns the physical input lock.
            with controls.bus_lock:
                _check(allowed)
                if controls.hardware_backend().imu_identity() != identity:
                    raise DriverSetupError("Sensor changed during driver setup")
                old = (controls._imu, controls._bus, controls._imu_address, controls._status['imu'])
                bus = None
                try:
                    with _imports(self.root):
                        sensor, bus, address = open_imu(controls._bus)
                        for _ in range(3):
                            _check(allowed)
                            sample = motion_sample(sensor.acceleration, sensor.gyro)
                            if sum(sample[k] ** 2 for k in ('imu_ax','imu_ay','imu_az')) < 4:
                                raise DriverSetupError("Motion sensor did not provide a usable gravity sample")
                            time.sleep(.02)
                        # Same lock as cancellation: publication has a precise boundary.
                        with commit_guard():
                            _check(allowed)
                            _private_json(self.path, {'driver': driver, 'pack': PACK})
                            controls._imu, controls._bus, controls._imu_address = sensor, bus, address
                            controls._status['imu'] = 'ready'
                            self.active = True
                            self.error = None
                            self.last_result = {'driver': driver, 'status': 'installed', 'verified': True,
                                                'identity': identity, 'readings': sample}
                except BaseException:
                    if bus is not None and old[1] is None:
                        bus.deinit()
                    controls._imu, controls._bus, controls._imu_address, controls._status['imu'] = old
                    raise
            return self.last_result
        except Exception as error:
            self.last_result = {'driver': driver, 'status': 'failed', 'verified': False}
            self.error = str(error) if isinstance(error, DriverSetupError) else 'Driver setup failed; previous drivers retained'
            raise DriverSetupError(self.error) from None
        finally:
            if staging.exists():
                shutil.rmtree(staging)
