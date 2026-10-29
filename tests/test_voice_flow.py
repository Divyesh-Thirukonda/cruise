"""Host-side draft, clarification and cancellation effects; no cloud or hardware."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from modulate.agent import AgentError
from modulate.agent_provider import AgentProvider, AgentProviderError
from modulate.product import Product
from tests.test_product import FakeBackend


class VoiceFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.product = Product(Path(self.tmp.name), AgentProvider({'provider':'ollama','model':'llama3.2:3b'}), backend=FakeBackend())
        self.addCleanup(self.product.cancel)
        self.product.last_seen = time.monotonic()

    def queued(self, text='Make a blue game', source='microphone', **options):
        with patch('modulate.product.threading.Thread') as thread:
            result = self.product.request(text, source=source, **options)
        return result['job_id'], thread.call_args.kwargs['target']

    def test_edit_holds_draft_and_only_edited_text_reaches_agent(self):
        job, work = self.queued()
        self.product.draft(job, 'pause')
        called = threading.Event()
        with patch.object(self.product.agent, 'run', side_effect=lambda text: called.set() or 'Done') as run:
            with ThreadPoolExecutor(1) as pool:
                result = pool.submit(work)
                self.assertFalse(called.wait(.04))
                self.assertIsNone(self.product.state()['voice_draft']['send_at'])
                self.product.draft(job, 'send', 'Make a green game')
                result.result(timeout=1)
            run.assert_called_once_with('Make a green game')
        self.assertIsNone(self.product.voice_draft)

    def test_auto_submit_waits_for_review_deadline(self):
        job, work = self.queued()
        self.assertGreater(self.product.draft_deadline - time.monotonic(), 2.8)
        # Advance the controlled deadline, then exercise the real worker dispatch.
        self.product.draft_deadline = time.monotonic() - .01
        with patch.object(self.product.agent, 'run', return_value='Done') as run:
            work()
        run.assert_called_once_with('Make a blue game')

    def test_discard_before_dispatch_makes_no_model_call(self):
        job, work = self.queued()
        self.assertTrue(self.product.draft(job, 'discard')['cancelled'])
        with patch.object(self.product.agent, 'run') as run:
            work()
        run.assert_not_called()
        self.assertEqual(self.product.agent_state()['status'], 'cancelled')
        self.assertIsNone(self.product.voice_draft)

    def test_stale_cancel_cannot_stop_a_new_job(self):
        old, work = self.queued(source='website')
        with patch.object(self.product.agent, 'run', return_value='Done'):
            work()
        new, _ = self.queued(source='website')
        self.assertNotEqual(old, new)
        self.assertFalse(self.product.cancel(old)['cancelled'])
        self.assertTrue(self.product.running)
        self.assertFalse(self.product.agent.cancelled.is_set())

    def test_stale_draft_and_invalid_edit_cannot_change_request(self):
        job, _ = self.queued()
        for identifier, action, text in [('x'*32,'send','wrong'),(job,'send',''),(job,'unknown','wrong')]:
            with self.assertRaises(AgentError): self.product.draft(identifier,action,text)
        self.assertEqual(self.product.voice_draft['text'],'Make a blue game')

    def test_question_keeps_program_and_next_reply_includes_context(self):
        _, work = self.queued('Make it faster', source='website')
        def ask(text):
            self.product.progress['request_id']='b'*32
            self.product.request_clarification('Do you mean movement speed or falling speed?')
            return 'Do you mean movement speed or falling speed?'
        with patch.object(self.product.agent, 'run', side_effect=ask): work()
        self.assertIsNone(self.product.active)
        self.assertIn('falling speed',self.product.state()['clarification']['question'])
        _, answer = self.queued('Falling speed', source='website')
        with patch.object(self.product.agent, 'run', return_value='Done') as run: answer()
        self.assertIn('Make it faster',run.call_args.args[0])
        self.assertIn("User's reply",run.call_args.args[0])
        self.assertIsNone(self.product.clarification)

    def test_unowned_clarification_callback_is_rejected(self):
        with self.assertRaises(AgentError): self.product.request_clarification('What should change?')

    def test_second_clarification_retains_original_goal(self):
        _, first = self.queued('Make the falling meteors faster', source='website')
        def ask(text):
            self.product.request_clarification('How much faster?')
            return 'How much faster?'
        with patch.object(self.product.agent, 'run', side_effect=ask): first()
        _, second = self.queued('A little', source='website')
        with patch.object(self.product.agent, 'run', side_effect=ask): second()
        _, third = self.queued('Twenty percent', source='website')
        with patch.object(self.product.agent, 'run', return_value='Done') as run: third()
        self.assertIn('Make the falling meteors faster', run.call_args.args[0])

    def test_exact_question_can_be_dismissed_without_cancelling_future_jobs(self):
        job, work = self.queued('Make it better',source='website')
        def ask(text):
            self.product.request_clarification('What should change?')
            return 'What should change?'
        with patch.object(self.product.agent,'run',side_effect=ask):work()
        self.assertFalse(self.product.cancel('c'*32)['cancelled'])
        self.assertIsNotNone(self.product.clarification)
        self.assertTrue(self.product.cancel(job)['dismissed_question'])
        self.assertIsNone(self.product.clarification)
        new, _ = self.queued(source='website')
        self.assertFalse(self.product.cancel(job)['cancelled'])
        self.assertTrue(self.product.running)

    def ask(self, question='Should the meteors fall faster?'):
        _, work = self.queued('Make the falling meteors faster', source='website')
        def ask(text):
            self.product.request_clarification(question)
            return question
        with patch.object(self.product.agent, 'run', side_effect=ask): work()
        return self.product.state()['clarification']

    def test_scoped_yes_preserves_goal_and_consumes_scope_without_granting_computer_approval(self):
        question = self.ask()
        self.product.computer_approved_action = {'action': 'synthetic old receipt'}
        _, work = self.queued('yes', source='website', followup_id=question['id'])
        self.assertIsNone(self.product.computer_approved_action)
        with patch.object(self.product.agent, 'run', return_value='Done') as run: work()
        self.assertIn('Make the falling meteors faster', run.call_args.args[0])
        self.assertIn("User's reply (may replace the request): yes", run.call_args.args[0])
        self.assertIsNone(self.product.conversation)
        with self.assertRaisesRegex(AgentError, 'conversation has ended'):
            self.product.request('yes', followup_id=question['id'])

    def test_expired_or_cancelled_scope_never_becomes_a_fresh_request(self):
        question = self.ask()
        self.product.clarification['expires_at'] = time.time() - 1
        with self.assertRaises(AgentError): self.product.request('yes', followup_id=question['id'])
        self.assertIsNone(self.product.state()['clarification'])
        self.assertIsNone(self.product.conversation)
        question = self.ask()
        self.product.cancel(question['job_id'])
        with self.assertRaises(AgentError): self.product.request('yes', followup_id=question['id'])
        self.assertFalse(self.product.running)

    def test_missing_speech_asks_without_model_or_activation_and_limits_reprompts(self):
        with patch.object(self.product.agent, 'run') as run:
            result = self.product.unclear('empty')
            for _ in range(4):
                question = self.product.state()['clarification']
                self.assertIsNotNone(question)
                old = question['id']
                self.product.unclear('empty', followup_id=old)
                current = self.product.state()['clarification']
                if current: self.assertNotEqual(current['id'], old)
            run.assert_not_called()
        self.assertIsNone(self.product.state()['clarification'])
        self.assertIsNone(self.product.active)
        self.assertIn('type it in Studio', self.product.response['text'])
        with self.assertRaises(AgentError): self.product.unclear([])

    def test_provider_failure_requires_human_reply_and_only_one_recovery(self):
        _, first = self.queued('Original synthetic goal', source='website')
        failure = AgentProviderError('Provider request failed or timed out.')
        with patch.object(self.product.agent, 'run', side_effect=failure) as run:
            first()
            self.assertEqual(run.call_count, 1)
        question = self.product.state()['clarification']
        self.assertEqual(question['kind'], 'recovery')
        self.assertIn('Check the connection', self.product.response['text'])
        _, retry = self.queued('yes', source='website', followup_id=question['id'])
        with patch.object(self.product.agent, 'run', side_effect=failure) as run:
            retry()
            self.assertIn('Original synthetic goal', run.call_args.args[0])
        self.assertIsNone(self.product.state()['clarification'])
        self.assertIn("stopped retrying", self.product.response['text'])
        self.assertIsNone(self.product.active)

    def test_missed_retry_answer_preserves_single_recovery_limit(self):
        _, work = self.queued('Original synthetic goal', source='website')
        failure = AgentProviderError('Provider request failed or timed out.')
        with patch.object(self.product.agent, 'run', side_effect=failure): work()
        first = self.product.state()['clarification']
        self.product.unclear('empty', followup_id=first['id'])
        repeated = self.product.state()['clarification']
        self.assertNotEqual(repeated['id'], first['id'])
        self.assertEqual(repeated['kind'], 'recovery')
        _, retry = self.queued('yes', source='website', followup_id=repeated['id'])
        with patch.object(self.product.agent, 'run', side_effect=failure): retry()
        self.assertIsNone(self.product.state()['clarification'])
        self.assertIn('stopped retrying', self.product.response['text'])

    def test_unclear_then_real_goal_then_yes_keeps_original_intent(self):
        self.product.unclear('empty')
        first = self.product.state()['clarification']
        _, work = self.queued('Make a game about catching falling stars', source='website', followup_id=first['id'])
        def ask(text):
            self.product.request_clarification('Should the stars get faster over time?')
            return 'Should the stars get faster over time?'
        with patch.object(self.product.agent, 'run', side_effect=ask): work()
        second = self.product.state()['clarification']
        _, answer = self.queued('yes', source='website', followup_id=second['id'])
        with patch.object(self.product.agent, 'run', return_value='Done') as run: answer()
        self.assertIn('Previous request: Make a game about catching falling stars', run.call_args.args[0])
        self.assertIn('stars get faster over time', run.call_args.args[0])
        self.assertIn("User's reply (may replace the request): yes", run.call_args.args[0])

    def test_long_goal_and_reply_are_not_silently_truncated(self):
        goal = 'a' * 3980 + 'KEEP_GOAL_END'
        _, work = self.queued(goal, source='website')
        def ask(text):
            self.product.request_clarification('Which behavior should change?')
            return 'Which behavior should change?'
        with patch.object(self.product.agent, 'run', side_effect=ask): work()
        question = self.product.state()['clarification']
        answer = 'b' * 3980 + 'KEEP_REPLY_END'
        _, work = self.queued(answer, source='website', followup_id=question['id'])
        with patch.object(self.product.agent, 'run', return_value='Done') as run: work()
        prompt = run.call_args.args[0]
        self.assertIn('KEEP_GOAL_END', prompt)
        self.assertIn('KEEP_REPLY_END', prompt)
        self.assertLessEqual(len(prompt), 24000)

    def test_budget_and_unexpected_failures_stop_without_raw_payload_or_retry_scope(self):
        for error in (AgentError('The approved model budget cannot cover another reserved call'),
                      RuntimeError('SECRET_PATH_OR_SCREEN_PAYLOAD')):
            _, work = self.queued(source='website')
            with patch.object(self.product.agent, 'run', side_effect=error): work()
            self.assertIsNone(self.product.state()['clarification'])
            self.assertNotIn('SECRET_PATH', self.product.response['text'])
        self.assertFalse(self.product.running)

if __name__ == '__main__':
    unittest.main()
