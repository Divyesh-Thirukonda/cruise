"""Synthetic hardware changes and model tools; no live device or provider calls."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from modulate.adaptation import ControlAdaptation
from modulate.agent import AgentError, Ledger, Orchestrator, digest
from modulate.product import Product
from tests.test_agent import FakeService, ScriptedProvider, reply, game_package, control_package
from tests.test_assistant_io import FakeComputer
from tests.test_product import FakeBackend


class AdaptationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.scheduler = ControlAdaptation(self.root)
        self.package = game_package('joystick')

    def observe(self, now, controls=None, **kwargs):
        options = dict(suspended=True, eligible=True, now=now)
        options.update(kwargs)
        return self.scheduler.consider(self.package, digest(self.package),
                                       controls if controls is not None else ['button_a'], **options)

    def test_stable_missing_control_dispatches_once_even_after_restart(self):
        self.assertFalse(self.observe(0))
        self.assertFalse(self.observe(4.99))
        self.assertTrue(self.observe(5))
        self.assertFalse(self.observe(100))
        self.scheduler = ControlAdaptation(self.root)
        self.assertFalse(self.observe(200))
        self.assertFalse(self.observe(206))
        self.assertEqual(self.scheduler.path.stat().st_mode & 0o777, 0o600)

    def test_transient_loss_or_busy_task_does_not_dispatch(self):
        self.assertFalse(self.observe(0))
        self.assertFalse(self.observe(2, ['joystick'], suspended=False))
        self.assertFalse(self.observe(8))
        self.assertFalse(self.observe(12, eligible=False))
        self.assertFalse(self.observe(20))
        self.assertTrue(self.observe(25))

    def test_new_hardware_set_restarts_debounce_and_empty_controls_can_adapt(self):
        self.assertFalse(self.observe(0))
        self.assertFalse(self.observe(4, []))
        self.assertFalse(self.observe(5, []))
        self.assertTrue(self.observe(9, []))

    def test_healthy_app_and_host_packages_do_not_adapt(self):
        for package in (game_package('button_a'), control_package(),
                        {**self.package, 'camera': {'target': 'a' * 32}}):
            self.package = package
            self.assertFalse(self.observe(0))
            self.assertFalse(self.observe(10))

    def test_corrupt_history_disables_automatic_calls_without_reset(self):
        self.scheduler.path.write_text('invalid history')
        self.scheduler = ControlAdaptation(self.root)
        self.assertFalse(self.observe(0))
        self.assertFalse(self.observe(10))
        self.assertEqual(self.scheduler.path.read_text(), 'invalid history')
        self.assertIsNotNone(self.scheduler.error)

    def test_failed_history_write_never_dispatches(self):
        self.observe(0)
        with patch('modulate.adaptation.os.replace', side_effect=OSError('test')):
            self.assertFalse(self.observe(10))
        self.assertFalse(self.observe(20))

    def test_authenticated_heartbeat_schedules_local_edit_without_a_mac(self):
        provider = ScriptedProvider([])
        with patch.dict('os.environ', {'MODULATE_TTS_PROVIDER': 'local'}):
            product = Product(self.root, provider, backend=FakeBackend(), computer=FakeComputer())
        self.addCleanup(product.cancel, shutdown=True)
        product.active = {'revision': digest(self.package), 'package': self.package}
        packet = {'session': 'a' * 32, 'sequence': 0, 'name': 'Synthetic Pi',
                  'revision': product.revision, 'input': {},
                  'capabilities': {'controls': ['encoder', 'button_a', 'button_b']},
                  'telemetry': {'app': {'suspended': True, 'missing_controls': ['joystick']}}}
        with patch.object(product, 'request') as request, patch('modulate.product.time.monotonic', return_value=100):
            product.heartbeat(packet)
            request.assert_not_called()
        with patch.object(product, 'request') as request, patch('modulate.product.time.monotonic', return_value=106):
            product.heartbeat({**packet, 'sequence': 1, 'telemetry': {
                **packet['telemetry'], 'voice': {'state': 'listening'}}})
            request.assert_not_called()
        with patch.object(product, 'request') as request, patch('modulate.product.time.monotonic', return_value=112):
            product.heartbeat({**packet, 'sequence': 2})
            request.assert_not_called()
        with patch.object(product, 'request') as request, patch('modulate.product.time.monotonic', return_value=118):
            product.heartbeat({**packet, 'sequence': 3})
            request.assert_called_once()
            self.assertTrue(request.call_args.kwargs['_adapt_controls'])
            self.assertIsNone(product.capabilities()['paired_host'])
            product.heartbeat({**packet, 'sequence': 4})
            request.assert_called_once()

    def test_model_cannot_expand_adaptation_into_host_or_hardware_actions(self):
        service = FakeService()
        provider = ScriptedProvider([reply(content='Synthetic observation')])
        agent = Orchestrator(provider, service, self.root / 'agent', Ledger(self.root / 'budget.json', 0))
        agent.run('Adapt this local app', adapt_controls=True)
        names = {tool['function']['name'] for tool in provider.requests[0][1]}
        self.assertNotIn('system_control', names)
        self.assertNotIn('hardware_debug', names)
        self.assertNotIn('computer_act', names)
        for name, arguments in [('system_control', {'action': 'brightness.get'}),
                                ('hardware_debug', {'action': 'inspect'}),
                                ('load_skill', {'name': 'computer-use'}),
                                ('write_package', {'package': control_package()}),
                                ('write_package', {'package': {**self.package, 'camera': {'target': 'a' * 32}}})]:
            with self.subTest(name=name), self.assertRaises(AgentError):
                agent.dispatch(name, arguments, 'orchestrator')
        result = agent.dispatch('write_package', {'package': game_package('button_a')}, 'orchestrator')
        self.assertIn('candidate_id', result)
        self.assertEqual(service.system_actions, [])
