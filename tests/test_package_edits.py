"""Synthetic exact-edit safety checks; no live model or physical evidence."""
import copy
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from modulate.agent import AgentError, Ledger, Orchestrator
from tests.test_agent import FakeService, ScriptedProvider, control_package, game_package, reply, result_for


class PackageEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = FakeService()
        self.service.package = control_package()
        self.provider = ScriptedProvider([reply(content='Ready')])
        self.agent = Orchestrator(self.provider, self.service, Path(self.temp.name)/'agent',
                                  Ledger(Path(self.temp.name)/'ledger.json', 0))
        self.agent.run('Synthetic initialization')

    def edit(self, changes, revision=None):
        return self.agent.dispatch('edit_package', {'base_revision': revision or self.service.revision,
                                                   'changes': changes}, 'orchestrator')

    def test_checked_small_binding_edit_preserves_active_until_ack(self):
        before = copy.deepcopy(self.service.package)
        result = self.edit([{'path':['bindings',0,'scale'], 'old':2, 'new':-2}])
        self.assertTrue(result['verified'])
        self.assertEqual(self.service.package, before)
        self.assertEqual(self.service.checked, 1)
        self.assertEqual(self.service.activations, [])
        self.agent.dispatch('activate_package', {'candidate_id':result['candidate_id']}, 'orchestrator')
        self.assertEqual(self.service.package['bindings'][0]['scale'], -2)
        self.assertEqual(self.service.package['target'], before['target'])

    def test_stale_edit_and_external_revision_change_rejected(self):
        change = [{'path':['title'], 'old':self.service.package['title'], 'new':'Changed'}]
        with self.assertRaises(AgentError): self.edit(change, 'stale')
        self.service.revision = 'external-revision'
        with self.assertRaises(AgentError): self.edit(change)
        self.assertEqual(self.agent.candidates, {})

    def test_failed_late_change_is_atomic(self):
        before = copy.deepcopy(self.service.package)
        with self.assertRaises(AgentError):
            self.edit([{'path':['bindings',0,'scale'], 'old':2, 'new':-2},
                       {'path':['title'], 'old':'wrong', 'new':'Other'}])
        self.assertEqual(self.service.package, before)
        self.assertEqual(self.agent.candidates, {})
        self.assertEqual(self.service.candidates, [])

    def test_substring_edit_requires_exact_count_and_preserves_unrelated_code(self):
        self.service.package = game_package()
        code = self.service.package['code']
        change = {'op':'replace_text','path':['code'],'old':'return s','new':'return s /* edit */'}
        result = self.edit([change])
        candidate = self.agent.candidates[result['candidate_id']]['package']
        self.assertEqual(candidate['code'], code.replace('return s','return s /* edit */'))
        self.assertEqual(candidate['assets'], self.service.package['assets'])
        with self.assertRaises(AgentError): self.edit([{**change,'old':'return','count':1}])
        with self.assertRaises(AgentError): self.edit([{**change,'old':''}])

    def test_invalid_paths_and_operations_do_not_create_candidates(self):
        for path in [[], ['missing'], ['bindings',-1,'scale'], ['bindings',True,'scale'], ['title','x']]:
            with self.subTest(path=path), self.assertRaises(AgentError):
                self.edit([{'path':path,'old':2,'new':1}])
        with self.assertRaises(AgentError):
            self.edit([{'path':['title'],'old':'x','new':'y','op':'shell'}])
        self.assertEqual(self.agent.candidates, {})

    def test_changed_controls_and_target_still_validated(self):
        with self.assertRaises(AgentError): self.edit([{'path':['target'],'old':'test-session','new':'unpaired'}])
        self.service.package = game_package()
        with self.assertRaises(AgentError): self.edit([{'path':['controls',0],'old':'button_a','new':'joystick'}])
        self.assertEqual(self.service.activations, [])

    def test_failing_check_never_authorizes_activation(self):
        self.service.check_passes = False
        result = self.edit([{'path':['bindings',0,'scale'],'old':2,'new':1}])
        self.assertFalse(result['verified'])
        with self.assertRaises(AgentError):
            self.agent.dispatch('activate_package', {'candidate_id':result['candidate_id']}, 'orchestrator')
        self.assertEqual(self.service.activations, [])

    def test_private_and_automatic_setup_cannot_edit(self):
        change = [{'path':['bindings',0,'scale'],'old':2,'new':1}]
        self.agent.private_request = True
        with self.assertRaises(AgentError): self.edit(change)
        self.agent.private_request = False
        self.agent.setting_up_components = True
        with self.assertRaises(AgentError): self.edit(change)

    def test_checked_write_returns_real_report_without_activation(self):
        result = self.agent.dispatch('write_package', {'package':control_package(), 'verify':True}, 'orchestrator')
        self.assertTrue(result['verified'])
        self.assertEqual(result['report']['candidate_id'], result['candidate_id'])
        self.assertEqual(self.service.checked, 1)
        self.assertEqual(self.service.activations, [])

    def test_live_loop_can_review_combined_report_before_activation(self):
        def activate(messages, tools):
            result = result_for(messages,'edit_package')
            self.assertTrue(result['report']['passed'])
            return reply(('activate_package',{'candidate_id':result['candidate_id']}))
        self.provider.script = [reply(('edit_package',{'base_revision':self.service.revision,
            'changes':[{'path':['bindings',0,'scale'],'old':2,'new':-2}]})), activate, reply(content='Updated')]
        self.agent.run('Synthetic edit')
        self.assertEqual(len(self.service.activations), 1)
        self.assertEqual(self.agent.calls, 3)
