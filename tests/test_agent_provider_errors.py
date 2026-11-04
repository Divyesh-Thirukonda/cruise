"""Received-response billing metadata using mocked HTTP only; no model calls."""
import copy
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, Mock

from modulate.agent_provider import AgentProvider, AgentProviderError
from tests.test_agent_provider import MESSAGES, TOOLS, cloud_response


class ProviderFailureMetadataTests(unittest.TestCase):
    def provider(self, response=None, *, kind="meta"):
        adapter = AgentProvider({"provider": kind, "model": "muse-spark-1.3"})
        adapter._headers = Mock(return_value={"Content-Type": "application/json"})
        adapter._opener = MagicMock()
        if response is not None:
            adapter._opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
        return adapter

    def failure(self, adapter):
        with self.assertRaises(AgentProviderError) as caught:
            adapter.complete(MESSAGES, TOOLS)
        adapter._opener.open.assert_called_once()
        return caught.exception

    def test_unavailable_tools_and_malformed_arguments_retain_validated_billing(self):
        for response, expected in (
            (cloud_response(name="synthetic_unadvertised_tool"), "unavailable tool"),
            (cloud_response(name="computer.computer"), "Invalid function name"),
            (cloud_response(arguments='{"private_marker":'), "Invalid JSON"),
            (cloud_response(arguments="[]"), "JSON object"),
        ):
            with self.subTest(expected=expected):
                error = self.failure(self.provider(response))
                self.assertIn(expected, str(error))
                # 20 input + 10 output tokens, rounded up at current Spark rates.
                self.assertEqual(error.billed_cost_microdollars, 68)
                self.assertIs(error.repairable, True)
                self.assertNotIn("private_marker", str(error))
                self.assertNotIn("private_marker", repr(error.__dict__))

    def test_invalid_usage_cannot_settle_or_mark_a_tool_error_repairable(self):
        for usage in (None, {}, {"prompt_tokens": 20},
                      {"prompt_tokens": "20", "completion_tokens": 10},
                      {"prompt_tokens": 20, "completion_tokens": -1},
                      {"prompt_tokens": 20, "completion_tokens": True},
                      {"prompt_tokens": 20, "completion_tokens": 10, "completion_tokens_details": []}):
            with self.subTest(usage=usage):
                response = cloud_response(name="unknown_tool")
                response["usage"] = usage
                error = self.failure(self.provider(response))
                self.assertIsNone(error.billed_cost_microdollars)
                self.assertIs(error.repairable, False)

    def test_missing_unknown_or_invalid_response_model_keeps_billing_unknown(self):
        for model in (None, "unpriced-model", "invalid model", ["muse-spark-1.3"]):
            with self.subTest(model=model):
                response = cloud_response(arguments="broken")
                if model is None:
                    response.pop("model")
                else:
                    response["model"] = model
                error = self.failure(self.provider(response))
                self.assertIsNone(error.billed_cost_microdollars)
                self.assertIs(error.repairable, False)

    def test_received_truncation_and_malformed_envelope_are_billed_but_not_repairable(self):
        invalid_choices = cloud_response()
        invalid_choices["choices"] = []
        for response in (cloud_response(finish="length"), cloud_response(finish="content_filter"),
                         cloud_response(finish=None), cloud_response(finish=[]), invalid_choices):
            with self.subTest(response=response):
                error = self.failure(self.provider(response))
                self.assertEqual(error.billed_cost_microdollars, 68)
                self.assertIs(error.repairable, False)

    def test_complete_assistant_shape_errors_can_be_repaired_without_returning_output(self):
        missing_message = cloud_response()
        missing_message["choices"][0]["message"] = None
        duplicate_calls = cloud_response()
        duplicate_calls["choices"][0]["message"]["tool_calls"] *= 2
        empty = cloud_response(content="", finish="stop")
        empty["choices"][0]["message"].pop("tool_calls")
        for response in (missing_message, duplicate_calls, empty):
            with self.subTest(response=response):
                error = self.failure(self.provider(response))
                self.assertEqual(error.billed_cost_microdollars, 68)
                self.assertIs(error.repairable, True)

    def test_explicit_refusal_is_not_a_repairable_empty_turn(self):
        response = cloud_response(content=None, finish="stop")
        response["choices"][0]["message"] = {"role": "assistant", "content": None,
                                                 "refusal": "Synthetic private refusal details"}
        error = self.failure(self.provider(response))
        self.assertEqual(error.billed_cost_microdollars, 68)
        self.assertFalse(error.repairable)
        self.assertNotIn("private", str(error))

    def test_transport_http_and_unreadable_response_remain_unknown_without_retry(self):
        for failure in (urllib.error.URLError("Synthetic private transport details"), TimeoutError()):
            adapter = self.provider()
            adapter._opener.open.side_effect = failure
            error = self.failure(adapter)
            self.assertIsNone(error.billed_cost_microdollars)
            self.assertFalse(error.repairable)
        adapter = self.provider()
        adapter._opener.open.side_effect = urllib.error.HTTPError("https://api.meta.ai/v1/chat/completions", 503, "private", {}, None)
        error = self.failure(adapter)
        self.assertIsNone(error.billed_cost_microdollars)
        self.assertFalse(error.repairable)
        adapter = self.provider()
        adapter._opener.open.return_value.__enter__.return_value.read.return_value = b'{"usage":'
        error = self.failure(adapter)
        self.assertIsNone(error.billed_cost_microdollars)
        self.assertFalse(error.repairable)

    def test_non_meta_failures_do_not_claim_meta_billing_or_repair_support(self):
        response = copy.deepcopy(cloud_response(name="unknown_tool"))
        error = self.failure(self.provider(response, kind="fireworks"))
        self.assertIsNone(error.billed_cost_microdollars)
        self.assertFalse(error.repairable)

    def test_preflight_failure_has_no_billing_and_does_not_send(self):
        adapter = self.provider()
        with self.assertRaises(AgentProviderError) as caught:
            adapter.complete([{"role": "tool", "tool_call_id": "missing", "content": "Synthetic"}], TOOLS)
        self.assertIsNone(caught.exception.billed_cost_microdollars)
        self.assertFalse(caught.exception.repairable)
        adapter._opener.open.assert_not_called()

    def test_only_transient_http_categories_allow_an_orchestrator_retry(self):
        for status in (400, 401, 403, 404, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                adapter = self.provider()
                adapter._opener.open.side_effect = urllib.error.HTTPError(
                    "https://api.meta.ai/v1/chat/completions", status, "private", {}, None)
                error = self.failure(adapter)
                self.assertEqual(error.transient, status in {429, 502, 503, 504})
                self.assertIsNone(error.billed_cost_microdollars)


if __name__ == "__main__":
    unittest.main()
