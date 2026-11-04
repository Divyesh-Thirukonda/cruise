"""Provider protocol and failure-boundary tests; no network or credentials."""

import io
import json
import os
import unittest
import urllib.error
from unittest.mock import Mock, patch

from modulate import provider


CODE = 'value = randint(1, 20)\nshow(value, label="Roll", foreground="#FFFFFF", background="#000000")'


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.open_patch = patch.object(provider._OPENER, "open")
        self.open = self.open_patch.start()
        self.addCleanup(self.open_patch.stop)
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def reply(self, payload):
        response = Mock()
        response.read.return_value = json.dumps(payload).encode()
        self.open.return_value.__enter__.return_value = response
        return response

    def request(self):
        request = self.open.call_args.args[0]
        return request, json.loads(request.data)


    def test_local_generation_preserves_source_and_provenance(self):
        self.reply({"done": True, "response": json.dumps({"code": CODE})})
        result = provider.generate("roll a twenty-sided die")
        self.assertEqual(result, {"code": CODE, "transcript": "", "provider": "ollama", "model": "llama3.2:1b"})
        request, body = self.request()
        self.assertEqual(request.full_url, provider.OLLAMA_URL)
        self.assertFalse(body["stream"])
        self.assertEqual(body["format"]["required"], ["code"])
        self.assertEqual(body["options"], {"num_predict": 300, "num_ctx": 2048, "temperature": 0.4})
        self.assertEqual(self.open.call_args.kwargs["timeout"], 90)


    def test_refinement_is_data_and_does_not_replace_contract(self):
        self.reply({"done": True, "response": json.dumps({"code": CODE})})
        provider.generate("make the text blue", previous_code=CODE, feedback="A color is invalid.")
        _, body = self.request()
        context = json.loads(body["prompt"])
        self.assertEqual(context["previous_code"], CODE)
        self.assertEqual(context["verification_feedback"], "A color is invalid.")
        self.assertEqual(body["system"], provider._CONTRACT)


    def test_input_limits_and_invalid_models_do_not_reach_network(self):
        cases = [
            lambda: provider.generate("x" * 8001),
            lambda: provider.generate(""),
            lambda: provider.generate("go", previous_code="x" * 6001),
            lambda: provider.generate("go", feedback="x" * 2001),
            lambda: provider.generate("go", model="x" * 129),
            lambda: provider.generate("go", model="bad\nmodel"),
            lambda: provider.generate("go", provider="automatic"),
            lambda: provider.generate("go", model="qwen:7b"),
            lambda: provider.generate("go", provider="google"),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(provider.ProviderError):
                case()
        self.open.assert_not_called()

    def test_invalid_code_objects_are_rejected_without_execution(self):
        for text in ("not json", "[]", '{"code":4}', '{"code":""}',
                     json.dumps({"code": CODE, "extra": 1}),
                     json.dumps({"code": "x" * 6001})):
            with self.subTest(text=text[:30]):
                self.reply({"done": True, "response": text})
                with self.assertRaises(provider.ProviderError):
                    provider.generate("go")

    def test_untrusted_code_is_returned_for_runtime_check_not_executed(self):
        source = 'raise RuntimeError("must never run here")'
        self.reply({"done": True, "response": json.dumps({"code": source})})
        self.assertEqual(provider.generate("go")["code"], source)

    def test_incomplete_or_truncated_local_response_is_rejected(self):
        for result in ({"done": False}, {"done": True, "done_reason": "length", "response": '{"code":"x"}'}):
            with self.subTest(result=result):
                self.reply(result)
                with self.assertRaisesRegex(provider.ProviderError, "did not complete"):
                    provider.generate("go")


    def test_http_error_does_not_expose_response_body_or_reason(self):
        self.open.side_effect = urllib.error.HTTPError(
            provider.OLLAMA_URL, 429, "PRIVATE REASON", {}, io.BytesIO(b"PRIVATE BODY")
        )
        with self.assertRaises(provider.ProviderError) as caught:
            provider.generate("go")
        self.assertEqual(str(caught.exception), "Ollama request failed (HTTP 429).")
        self.assertIsNone(caught.exception.__cause__)
        self.assertTrue(caught.exception.__suppress_context__)
        self.open.assert_called_once()

    def test_network_error_is_sanitized_and_not_retried(self):
        self.open.side_effect = urllib.error.URLError("PRIVATE NETWORK DETAIL")
        with self.assertRaises(provider.ProviderError) as caught:
            provider.generate("go")
        self.assertEqual(str(caught.exception), "Ollama request failed or timed out.")
        self.open.assert_called_once()

    def test_invalid_or_oversized_wire_response_is_rejected(self):
        for data in (b"invalid-json", b"[]", b"\xff", b"x" * (provider.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(size=len(data)):
                response = self.reply({})
                response.read.return_value = data
                with self.assertRaises(provider.ProviderError):
                    provider.generate("go")
                response.read.assert_called_with(provider.MAX_RESPONSE_BYTES + 1)

    def test_redirects_do_not_forward_requests(self):
        self.assertIsNone(provider._NoRedirect().redirect_request(
            Mock(), None, 302, "redirect", {}, "https://another.example/"
        ))


if __name__ == "__main__":
    unittest.main()
