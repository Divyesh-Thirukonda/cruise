"""Registration backoff and status consistency, without contacting Cloudflare."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from modulate.connect_tunnel import publish


class ConnectTunnelTests(unittest.TestCase):
    def test_early_failures_recover_promptly_and_success_switches_to_hourly_refresh(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "tunnel.json"
            stopped = Mock()
            stopped.is_set.side_effect = [False] * 3 + [True]
            process = Mock(); process.poll.return_value = None
            states = []
            stopped.wait.side_effect = lambda _: states.append(json.loads(path.read_text()))
            with patch('modulate.connect_tunnel.register', side_effect=[OSError(), OSError(), None]) as register:
                publish('https://test.trycloudflare.com', 'private-test-secret', path, process, stopped)
            self.assertEqual([c.args[0] for c in stopped.wait.call_args_list], [2, 4, 3600])
            self.assertEqual([s['registered'] for s in states], [False, False, True])
            self.assertEqual(register.call_count, 3)
            self.assertNotIn('private-test-secret', path.read_text())

    def test_failed_refresh_clears_old_success_and_backoff_is_capped(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "tunnel.json"
            stopped = Mock(); stopped.is_set.side_effect = [False] * 7 + [True]
            process = Mock(); process.poll.return_value = None
            with patch('modulate.connect_tunnel.register', side_effect=[None] + [OSError()] * 6):
                publish('https://test.trycloudflare.com', 'secret', path, process, stopped)
            self.assertFalse(json.loads(path.read_text())['registered'])
            self.assertEqual([c.args[0] for c in stopped.wait.call_args_list], [3600, 2, 4, 8, 15, 30, 30])
