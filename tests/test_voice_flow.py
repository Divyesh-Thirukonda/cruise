"""Host-side draft, clarification and cancellation effects; no cloud or hardware."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from modulate.agent import AgentError
from modulate.agent_provider import AgentProvider
from modulate.product import Product
from tests.test_product import FakeBackend


class VoiceFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.product = Product(Path(self.tmp.name), AgentProvider({'provider':'ollama','model':'llama3.2:3b'}), backend=FakeBackend())
        self.addCleanup(self.product.cancel)
        self.product.last_seen = time.monotonic()

    def queued(self, text='Make a blue game', source='microphone'):
        with patch('modulate.product.threading.Thread') as thread:
            result = self.product.request(text, source=source)
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

if __name__ == '__main__':
    unittest.main()
