"""Provider protocol and failure-boundary tests; no network or credentials."""

import base64
import io
import json
import os
import unittest
import urllib.error
from unittest.mock import Mock, patch

from modulate import provider


CODE = 'value = randint(1, 20)\nshow(value, label="Roll", foreground="#FFFFFF", background="#000000")'
WAV = b"RIFF\x04\x00\x00\x00WAVE"


def google_output(text, *, status="completed"):
    return {"status": status, "steps": [
        {"type": "thought", "content": [{"type": "text", "text": "not output"}]},
        {"type": "model_output", "content": [{"type": "text", "text": text}]},
    ]}


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

    def google(self, payload):
        # Headers are mocked rather than using a secret-shaped fixture.
        self.reply(payload)
        return patch.object(provider, "_google_headers", return_value={})

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

    def test_google_uses_typed_steps_and_json_schema(self):
        with self.google(google_output(json.dumps({"code": CODE}))):
            result = provider.generate("roll a die", provider="google", model=" gemini-3.8-flash ")
        self.assertEqual(result["code"], CODE)
        self.assertEqual(result["model"], "gemini-3.8-flash")
        request, body = self.request()
        self.assertEqual(request.full_url, provider.GOOGLE_URL)
        self.assertEqual(body["response_format"]["mime_type"], "application/json")
        self.assertFalse(body["store"])
        self.assertEqual(body["generation_config"]["max_output_tokens"], 1024)
        self.assertEqual(self.open.call_args.kwargs["timeout"], 45)

    def test_refinement_is_data_and_does_not_replace_contract(self):
        self.reply({"done": True, "response": json.dumps({"code": CODE})})
        provider.generate("make the text blue", previous_code=CODE, feedback="A color is invalid.")
        _, body = self.request()
        context = json.loads(body["prompt"])
        self.assertEqual(context["previous_code"], CODE)
        self.assertEqual(context["verification_feedback"], "A color is invalid.")
        self.assertEqual(body["system"], provider._CONTRACT)

    def test_transcription_sends_wav_and_strips_response(self):
        with self.google(google_output("  choose a number  \n")):
            result = provider.transcribe(WAV)
        self.assertEqual(result, "choose a number")
        _, body = self.request()
        audio = body["input"][1]
        self.assertEqual(audio["mime_type"], "audio/wav")
        self.assertEqual(base64.b64decode(audio["data"]), WAV)

    def test_silence_is_empty_transcript(self):
        with self.google(google_output("  ")):
            self.assertEqual(provider.transcribe(WAV), "")

    def test_google_missing_key_fails_before_network(self):
        with self.assertRaisesRegex(provider.ProviderError, "GEMINI_API_KEY"):
            provider.generate("choose a number", provider="google", model="gemini-3.8-flash")
        self.open.assert_not_called()

    def test_input_limits_and_invalid_models_do_not_reach_network(self):
        cases = [
            lambda: provider.generate("x" * 8001),
            lambda: provider.generate(""),
            lambda: provider.generate("go", previous_code="x" * 6001),
            lambda: provider.generate("go", feedback="x" * 2001),
            lambda: provider.generate("go", model="x" * 129),
            lambda: provider.generate("go", model="bad\nmodel"),
            lambda: provider.generate("go", provider="automatic"),
            lambda: provider.transcribe(b"not wave audio"),
            lambda: provider.transcribe(WAV + b"x" * provider.MAX_AUDIO_BYTES),
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

    def test_google_rejects_incomplete_missing_and_oversized_text(self):
        cases = [google_output("x", status="failed"), {"status": "completed", "steps": []},
                 google_output("x" * 2001),
                 {"status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": 5}]}]}]
        for response in cases:
            with self.subTest(response=response.get("status")), self.google(response):
                with self.assertRaises(provider.ProviderError):
                    provider.transcribe(WAV)

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
