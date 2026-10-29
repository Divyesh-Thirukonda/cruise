"""Synthetic screenshots and provider decisions only; no desktop or cloud use."""
import base64
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image
from modulate.agent import AgentError, Ledger, Orchestrator
from modulate.agent_provider import AgentProvider, AgentProviderError
from tests.test_agent import FakeService, ScriptedProvider, reply


def screenshot(color):
    stream = io.BytesIO()
    Image.new('RGB', (16, 16), color).save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


class VisionProviderTests(unittest.TestCase):
    def test_only_bounded_inline_user_images_are_accepted(self):
        provider = AgentProvider({'provider': 'meta', 'model': 'muse-spark-1.3'})
        image = {'type': 'image_url', 'image_url': {'url': screenshot('blue')}}
        good = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Current screen'}, image]}]
        self.assertGreater(provider.request_budget(good, [])['reserved_cost_microdollars'], 0)
        for bad in ([{'role': 'system', 'content': [image]}],
                    [{'role': 'user', 'content': [image, image]}],
                    [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'https://private.example/image'}}]}],
                    [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,bm90YW5pbWFnZQ=='}}]}]):
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(AgentProviderError):
                provider.request_budget(bad, [])

    def test_unverified_provider_rejects_screen_input(self):
        provider = AgentProvider({'provider': 'ollama', 'model': 'llama3.2:3b'})
        with self.assertRaises(AgentProviderError):
            provider.request_budget([{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': screenshot('red')}}]}], [])


class ComputerAgentTests(unittest.TestCase):
    def test_observe_act_verify_uses_latest_image_and_redacts_private_trace(self):
        first, second = screenshot('red'), screenshot('blue')
        service = FakeService()
        service.computer_authorized = lambda: None
        service.computer_observe = lambda: {'observation_id': 'one', 'width': 16, 'height': 16, 'image_url': first}
        service.computer_act = lambda **kw: {'observation_id': 'two', 'width': 16, 'height': 16,
                                           'image_url': second, 'private_result': 'PRIVATE_SCREEN_TEXT'}
        provider = ScriptedProvider([
            reply(('computer_observe', {})),
            reply(('computer_act', {'observation_id': 'one', 'action': {'type': 'click', 'x': 4, 'y': 4},
                                    'requires_confirmation': False, 'description': 'Open the visible message'})),
            reply(content='PRIVATE_EMAIL_ANSWER'),
        ])
        provider.real = AgentProvider({'provider': 'meta', 'model': 'muse-spark-1.3'})
        provider.config = provider.real.config
        with TemporaryDirectory() as directory:
            agent = Orchestrator(provider, service, directory, Ledger(Path(directory) / 'ledger.json', 5))
            result = agent.run('Read the visible email')
            self.assertEqual(result, 'PRIVATE_EMAIL_ANSWER')
            persisted = (Path(directory) / 'trace.jsonl').read_text()
            for value in (first, second, 'PRIVATE_SCREEN_TEXT', 'PRIVATE_EMAIL_ANSWER'):
                self.assertNotIn(value, persisted)
                self.assertNotIn(value, json.dumps(service.events))
            last_messages, tools = provider.requests[-1]
            images = [m for m in last_messages if isinstance(m.get('content'), list)]
            self.assertEqual(len(images), 1)
            self.assertEqual(images[0]['content'][1]['image_url']['url'], second)
            self.assertNotIn('write_package', [t['function']['name'] for t in tools])
            with self.assertRaises(AgentError):
                agent.dispatch('delegate_task', {'role': 'coder', 'task': 'Copy the inbox'}, 'orchestrator')

    def test_specialist_cannot_observe_computer(self):
        with TemporaryDirectory() as directory:
            agent = Orchestrator(ScriptedProvider([]), FakeService(), directory, Ledger(Path(directory) / 'ledger.json'))
            with self.assertRaises(AgentError):
                agent.dispatch('computer_observe', {}, 'coder')
