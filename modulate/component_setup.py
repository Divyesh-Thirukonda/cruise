"""Read-backed component inventory and one bounded setup attempt per observation.

An address is presence evidence, never an identity or a new generated-code input.
No model calls or bus I/O occur here. The normal agent/driver tools do the work.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile


class ComponentSetup:
    def __init__(self, directory):
        self.path = Path(directory) / 'component-setup-attempts.json'
        self.attempts = []
        self.error = None
        self.observation = self.since = None
        try:
            if self.path.exists():
                if self.path.stat().st_size > 16384:
                    raise ValueError()
                self.attempts = json.loads(self.path.read_text())
                if (type(self.attempts) is not list or len(self.attempts) > 128 or
                    any(type(k) is not str or len(k) != 64 or any(c not in '0123456789abcdef' for c in k) for k in self.attempts)):
                    raise ValueError()
        except (OSError, ValueError):
            self.error = 'Component setup history is unavailable; automatic setup paused'

    def inventory(self, hardware, devices):
        report = hardware.get('report') or {}
        online = hardware.get('connected') is True and report.get('bus_available') is True
        addresses = set(report.get('addresses', [])) if online else set()
        known = set()
        items = []
        catalog = (report.get('driver_setup') or {}).get('catalog', [])
        for device in devices:
            identifier = device.get('id')
            values = []
            for token in str(device.get('address') or '').split('/'):
                try: values.append(int(token.strip(), 16))
                except ValueError: pass
            # A missing driver may not yet know the address; verified catalog
            # identity associates the physical IMU without guessing from address.
            driver = next((c for c in catalog if type(c) is dict and c.get('id') == 'lsm6ds3trc'), None) if identifier == 'imu' else None
            if driver and type(driver.get('identity')) is dict:
                values.append(driver['identity'].get('address'))
            present = sorted(a for a in values if type(a) is int and a in addresses)
            known.update(present)
            ready = hardware.get('connected') is True and device.get('status') == 'ready'
            if not present and not ready:
                continue
            items.append({'id': identifier, 'model': device.get('model'),
                          'addresses': [hex(a) for a in present], 'ready': ready,
                          'status': 'ready' if ready else 'needs_setup',
                          'signals': device.get('inputs', {}),
                          'driver': driver.get('id') if driver else None,
                          'installable': bool(driver and driver.get('installable') and present)})
        for address in sorted(addresses - known):
            items.append({'id': 'i2c:' + hex(address), 'addresses': [hex(address)],
                          'ready': False, 'status': 'needs_identification',
                          'reason': 'Address observed; manufacturer/model and a supported input adapter are still needed'})
        return items

    def consider(self, hardware, devices, *, eligible, now):
        items = self.inventory(hardware, devices)
        pending = [i for i in items if not i['ready'] and
                   (i.get('installable') or i['status'] == 'needs_identification')]
        if (self.error or not eligible or not hardware.get('connected') or hardware.get('pending')
                or not pending or len(self.attempts) >= 128):
            self.observation = self.since = None
            return False
        key = hashlib.sha256(json.dumps(pending, sort_keys=True).encode()).hexdigest()
        if key in self.attempts:
            return False
        if key != self.observation:
            self.observation, self.since = key, now
            return False
        if now - self.since < 5:
            return False
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, delete=False) as f:
                temporary = f.name
                os.chmod(temporary, 0o600)
                json.dump(self.attempts + [key], f)
                f.flush(); os.fsync(f.fileno())
            os.replace(temporary, self.path)
            self.attempts.append(key)
        except OSError:
            self.error = 'Could not record component setup; automatic setup paused'
            return False
        finally:
            if temporary and os.path.exists(temporary): os.unlink(temporary)
        return True


SETUP_REQUEST = """New or unready components were observed. Load component-setup
and inspect current component/driver evidence. Install an identity-verified missing
catalog driver when supported, verify live readings and refresh capabilities.
For an unknown board, ask for identifying model/markings; never guess its identity
from an I2C address. Preserve the current app and existing mappings. Do not change
addresses, run computer actions, generate packages or start a physical repair.
Stop at a concrete human step or one unchanged failed attempt. State only verified
readiness. The next user app request chooses how to use ready signals."""
