"""Network-free cloud transport checks, with synthetic credentials only."""
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from modulate.agent_provider import AgentProvider, AgentProviderError
from modulate.cloud_provider import CloudProvider, CloudConfigurationError, GATEWAY_URL
from modulate.tts import ElevenLabsTTS, TTSError
from tests.test_tts import Opener


class CloudProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def configure(self):
        os.environ.update(MODULATE_CLOUD_URL=GATEWAY_URL, MODULATE_CLOUD_KEY="test_" + "x" * 50)

    def test_partial_or_untrusted_destination_fails_closed(self):
        self.assertFalse(CloudProvider().enabled)
        for url, key in ((GATEWAY_URL, ""), ("", "x" * 40),
                         ("http://divy.live/api/modulate-provider", "x" * 40),
                         ("https://attacker.example/api/modulate-provider", "x" * 40),
                         (GATEWAY_URL, "x" * 40 + "\nheader:value")):
            with self.subTest(url=url):
                os.environ.update(MODULATE_CLOUD_URL=url, MODULATE_CLOUD_KEY=key)
                with self.assertRaises(CloudConfigurationError):
                    CloudProvider()
                with self.assertRaises(AgentProviderError):
                    AgentProvider({"provider": "meta", "model": "muse-spark-1.3"})

    def test_meta_transport_uses_gateway_key_without_provider_key(self):
        self.configure()
        os.environ["MODEL_API_KEY"] = "must-not-be-forwarded"
        provider = AgentProvider({"provider": "meta", "model": "muse-spark-1.3"})
        provider._opener = MagicMock()
        result = {"model": "muse-spark-1.3", "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": "Ready."}}], "usage": {
                "prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}}
        provider._opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(result).encode()
        self.assertEqual(provider.complete([{"role": "user", "content": "Hello"}], [])["content"], "Ready.")
        request = provider._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, GATEWAY_URL + "?action=meta")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + os.environ["MODULATE_CLOUD_KEY"])
        self.assertNotIn("must-not-be-forwarded", str(request.headers) + str(request.data))
        self.assertEqual(provider.config.endpoint, "https://api.meta.ai/v1/chat/completions")
        self.assertGreater(provider.request_budget([{"role": "user", "content": "Hello"}], [])[
            "reserved_cost_microdollars"], 0)

    def test_speech_gateway_preserves_reservations_and_hides_provider_key(self):
        self.configure()
        with tempfile.TemporaryDirectory() as directory:
            opener = Opener()
            tts = ElevenLabsTTS(directory, api_key="do-not-forward", voice_id="test-voice", max_chars=5, opener=opener)
            tts.synthesize("hello", threading.Event())
            request = opener.calls[0][0]
            self.assertEqual(request.full_url, GATEWAY_URL + "?action=speech")
            self.assertGreater(opener.calls[0][1], 10)
            self.assertLessEqual(opener.calls[0][1], 45)
            self.assertIsNone(request.get_header("Xi-api-key"))
            self.assertEqual(json.loads(request.data), {"voice_id": "test-voice", "payload": {
                "text": "hello", "model_id": "eleven_flash_v2_5"}})
            second = ElevenLabsTTS(directory, api_key="", voice_id="test-voice", max_chars=5, opener=Opener())
            self.assertTrue(second.status()["configured"])
            with self.assertRaises(TTSError) as error:
                second.synthesize("x", threading.Event())
            self.assertEqual(error.exception.category, "budget")
            self.assertEqual(json.loads((Path(directory) / "tts-character-ledger.json").read_text())["reserved_characters"], 5)

    def test_gateway_error_does_not_retry_direct_or_release_speech_hold(self):
        self.configure()
        with tempfile.TemporaryDirectory() as directory:
            opener = Opener(error=urllib.error.HTTPError(GATEWAY_URL, 503, "Private failure", {}, io.BytesIO()))
            tts = ElevenLabsTTS(directory, api_key="local-must-not-fallback", voice_id="test-voice", opener=opener)
            with self.assertRaises(TTSError):
                tts.synthesize("hello", threading.Event())
            self.assertEqual(len(opener.calls), 1)
            ledger = json.loads((Path(directory) / "tts-character-ledger.json").read_text())
            self.assertEqual(ledger["reserved_characters"], 5)
            self.assertEqual(ledger["uncertain_requests"], 1)


if __name__ == "__main__":
    unittest.main()
