"""Synthetic discovery changes; does not plug/unplug physical hardware."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from modulate.component_setup import ComponentSetup
from modulate.agent import AgentError
from tests.test_agent import reply


def hardware(addresses=(0x6A,), ready=False):
    return {'connected': True, 'report': {'bus_available': True, 'addresses': list(addresses),
        'driver_setup': {'catalog': [{'id': 'lsm6ds3trc', 'model': 'LSM6DS3TR-C',
            'identity': {'address': 0x6A, 'who_am_i': 0x6A}, 'installable': True, 'input_ready': ready}]}}}

DEVICES = [{'id': 'imu', 'address': None, 'status': 'unavailable', 'inputs': {'tilt_x': 'gravity tilt'}}]


class ComponentSetupTests(unittest.TestCase):
    def setUp(self):
        self.root = TemporaryDirectory(); self.addCleanup(self.root.cleanup)
        self.manager = ComponentSetup(self.root.name)

    def test_unknown_address_is_not_a_working_input(self):
        items = self.manager.inventory(hardware((0x39,)), DEVICES)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['status'], 'needs_identification')
        self.assertFalse(items[0]['ready'])
        self.assertNotIn('signals', items[0])

    def test_verified_identity_marks_installable_not_ready_until_live_reads(self):
        items = self.manager.inventory(hardware(), DEVICES)
        self.assertEqual(items[0]['driver'], 'lsm6ds3trc')
        self.assertTrue(items[0]['installable']); self.assertFalse(items[0]['ready'])
        ready = [{**DEVICES[0], 'status': 'ready', 'address': '0x6a'}]
        item = self.manager.inventory(hardware(ready=True), ready)[0]
        self.assertEqual(item['status'], 'ready')
        self.assertEqual(item['addresses'], ['0x6a'])
        offline = hardware(); offline['connected'] = False
        self.assertEqual(self.manager.inventory(offline, ready), [])

    def test_debounce_once_only_and_restart_does_not_repeat_model_work(self):
        for t in (0, 4):
            self.assertFalse(self.manager.consider(hardware(), DEVICES, eligible=True, now=t))
        self.assertTrue(self.manager.consider(hardware(), DEVICES, eligible=True, now=5))
        self.assertFalse(self.manager.consider(hardware(), DEVICES, eligible=True, now=50))
        restarted = ComponentSetup(self.root.name)
        self.assertFalse(restarted.consider(hardware(), DEVICES, eligible=True, now=100))

    def test_permission_busy_and_ready_devices_do_not_start_setup(self):
        self.assertFalse(self.manager.consider(hardware(), DEVICES, eligible=False, now=0))
        ready = [{**DEVICES[0], 'status': 'ready', 'address': '0x6a'}]
        self.assertFalse(self.manager.consider(hardware(ready=True), ready, eligible=True, now=10))
        busy = hardware(); busy['pending'] = True
        self.assertFalse(self.manager.consider(busy, DEVICES, eligible=True, now=20))
        self.assertFalse(self.manager.path.exists())

    def test_corrupt_or_failed_journal_cannot_allow_repeated_automatic_calls(self):
        self.manager.path.write_text('invalid')
        broken = ComponentSetup(self.root.name)
        self.assertFalse(broken.consider(hardware(), DEVICES, eligible=True, now=0))
        self.assertIsNotNone(broken.error)
        self.manager.consider(hardware(), DEVICES, eligible=True, now=0)
        with patch('modulate.component_setup.os.replace', side_effect=OSError()):
            self.assertFalse(self.manager.consider(hardware(), DEVICES, eligible=True, now=5))
        self.assertEqual(self.manager.attempts, [])

    def test_product_gate_honors_hardware_permission_before_dispatch(self):
        from modulate.product import Product
        from tests.test_agent import ScriptedProvider
        from tests.test_assistant_io import FakeComputer
        from tests.test_product import FakeBackend
        import time
        with patch.dict('os.environ', {'MODULATE_TTS_PROVIDER': 'local'}):
            product = Product(Path(self.root.name) / 'product', ScriptedProvider([]), backend=FakeBackend(), computer=FakeComputer())
        self.addCleanup(product.cancel, shutdown=True)
        product.last_seen = time.monotonic()
        product.device['devices'] = DEVICES
        with patch.object(product.hardware, 'inspect', return_value=hardware()), patch.object(product, 'permission_allowed', return_value=False), patch.object(product, 'request') as request:
            product._setup_new_components()
            request.assert_not_called()
            self.assertFalse(product.component_setup.path.exists())



class AutomaticSetupAgentTests(unittest.TestCase):
    def make(self, script):
        from tests.test_agent_reliability import AgentReliabilityTests
        return AgentReliabilityTests.make(self, script)
    def test_restricted_setup_cannot_operate_computer_or_change_packages_or_addresses(self):
        agent, _, service, _ = self.make([reply(content='No changes')])
        agent.run('Check new component', component_setup=True)
        for name,args in [('speaker_control', {'action':'set','value':50}),
                          ('hardware_debug', {'action':'begin_button_repair'}),
                          ('read_recent_context', {'include_private':True}),
                          ('write_package', {'package':{}})]:
            with self.subTest(tool=name), self.assertRaisesRegex(AgentError, 'Automatic component setup'):
                agent.dispatch(name, args, 'orchestrator')
        self.assertEqual(service.activations, [])
