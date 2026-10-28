import io
import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, Mock, patch

from modulate.agent_provider import (
    AgentProvider, AgentProviderError, ProviderConfig, ENDPOINTS,
    MAX_RESPONSE_BYTES, _NoRedirect,
    cost_microdollars,
)


TOOLS = [{"type": "function", "function": {
    "name": "inspect_device", "description": "Read current capabilities.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}}]
MESSAGES = [{"role": "user", "content": "Build a device game."}]


def cloud_response(*, arguments="{}", content=None, finish="tool_calls", name="inspect_device"):
    return {"model": "muse-spark-1.3", "choices": [{"finish_reason": finish, "message": {
        "role": "assistant", "content": content,
        "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}],
    }}], "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}}


class AgentProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def make(self, kind="meta", **kwargs):
        adapter = AgentProvider({"provider": kind, "model": "llama3.2:3b" if kind == "ollama" else "muse-spark-1.3", **kwargs})
        adapter._opener = MagicMock()
        adapter._headers = Mock(return_value={"Content-Type": "application/json"})
        return adapter

    def reply(self, adapter, value):
        response = Mock()
        response.read.return_value = json.dumps(value).encode()
        adapter._opener.open.return_value.__enter__.return_value = response
        return response

    def sent(self, adapter):
        request = adapter._opener.open.call_args.args[0]
        return request, json.loads(request.data)

    def test_meta_tool_call_is_normalized_with_usage(self):
        adapter = self.make()
        self.reply(adapter, cloud_response(arguments='{"component":"screen"}'))
        result = adapter.complete(MESSAGES, TOOLS)
        self.assertEqual(result["tool_calls"], [{"id": "call_1", "name": "inspect_device", "arguments": {"component": "screen"}}])
        self.assertEqual(result["usage"]["total_tokens"], 30)
        request, body = self.sent(adapter)
        self.assertEqual(request.full_url, ENDPOINTS["meta"])
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(body["max_completion_tokens"], 4096)
        self.assertNotIn("temperature", body)
        self.assertFalse(body["stream"])

    def test_fireworks_uses_verified_endpoint_and_parameters(self):
        adapter = self.make("fireworks", reasoning_effort="low", temperature=0.4)
        self.reply(adapter, cloud_response())
        adapter.complete(MESSAGES, TOOLS)
        request, body = self.sent(adapter)
        self.assertEqual(request.full_url, ENDPOINTS["fireworks"])
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertEqual(body["temperature"], 0.4)

    def test_content_only_turn_does_not_force_tools(self):
        adapter = self.make()
        value = cloud_response(content="The task is complete.", finish="stop")
        value["choices"][0]["message"].pop("tool_calls")
        self.reply(adapter, value)
        result = adapter.complete(MESSAGES, [])
        self.assertEqual(result["content"], "The task is complete.")
        self.assertEqual(result["tool_calls"], [])
        self.assertNotIn("tool_choice", self.sent(adapter)[1])

    def test_local_calls_get_ids_and_replay_as_native_ollama_history(self):
        adapter = self.make("ollama")
        self.reply(adapter, {"done": True, "model": "llama3.2:3b", "prompt_eval_count": 8, "eval_count": 3,
            "message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "inspect_device", "arguments": {}}}
            ]}})
        result = adapter.complete(MESSAGES, TOOLS)
        call = result["tool_calls"][0]
        self.assertTrue(call["id"].startswith("ollama_"))
        self.assertEqual(result["usage"], {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11})
        history = MESSAGES + [{"role": "assistant", **result}, {"role": "tool", "tool_call_id": call["id"], "content": "screen available"}]
        self.reply(adapter, {"done": True, "message": {"role": "assistant", "content": "Ready."}})
        adapter.complete(history, TOOLS)
        _, body = self.sent(adapter)
        self.assertEqual(body["messages"][-1], {"role": "tool", "tool_name": "inspect_device", "content": "screen available"})
        self.assertEqual(body["messages"][-2]["tool_calls"][0]["function"]["arguments"], {})
        self.assertNotIn("tool_choice", body)

    def test_cloud_replay_retains_call_ids_and_json_arguments(self):
        adapter = self.make()
        self.reply(adapter, cloud_response())
        history = MESSAGES + [{"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_old", "name": "inspect_device", "arguments": {"component": "screen"}}
        ]}, {"role": "tool", "tool_call_id": "call_old", "content": "available"}]
        adapter.complete(history, TOOLS)
        wire = self.sent(adapter)[1]["messages"]
        self.assertEqual(wire[-1]["tool_call_id"], "call_old")
        self.assertEqual(json.loads(wire[-2]["tool_calls"][0]["function"]["arguments"]), {"component": "screen"})

    def test_private_reasoning_is_replay_metadata_separate_from_content(self):
        adapter = self.make()
        value = cloud_response()
        value["choices"][0]["message"]["reasoning_content"] = "private model metadata"
        self.reply(adapter, value)
        result = adapter.complete(MESSAGES, TOOLS)
        self.assertEqual(result["content"], "")
        self.assertEqual(result["reasoning_content"], "private model metadata")

    def test_invalid_argument_json_is_rejected(self):
        for arguments in ("broken", "[]", "null", '{"x":NaN}', '{"x":1,"x":2}'):
            with self.subTest(arguments=arguments):
                adapter = self.make()
                self.reply(adapter, cloud_response(arguments=arguments))
                with self.assertRaises(AgentProviderError):
                    adapter.complete(MESSAGES, TOOLS)

    def test_unknown_tools_and_duplicate_ids_are_rejected(self):
        for value in (cloud_response(name="run_shell"), cloud_response()):
            if value["choices"][0]["message"]["tool_calls"][0]["function"]["name"] != "run_shell":
                value["choices"][0]["message"]["tool_calls"] *= 2
            adapter = self.make()
            self.reply(adapter, value)
            with self.assertRaises(AgentProviderError):
                adapter.complete(MESSAGES, TOOLS)

    def test_truncated_or_empty_responses_cannot_be_executed(self):
        values = [cloud_response(finish="length"), {"choices": []}, cloud_response(finish=None)]
        empty = cloud_response(content="", finish="stop")
        empty["choices"][0]["message"].pop("tool_calls")
        values.append(empty)
        for value in values:
            adapter = self.make()
            self.reply(adapter, value)
            with self.assertRaises(AgentProviderError):
                adapter.complete(MESSAGES, TOOLS)

    def test_unmatched_missing_and_misnamed_tool_results_fail_before_network(self):
        assistant = {"role": "assistant", "content": "", "tool_calls": [{"id": "call_1", "name": "inspect_device", "arguments": {}}]}
        histories = [
            MESSAGES + [{"role": "tool", "tool_call_id": "unknown", "content": "x"}],
            MESSAGES + [assistant],
            MESSAGES + [assistant, {"role": "tool", "tool_call_id": "call_1", "name": "different", "content": "x"}],
        ]
        for history in histories:
            adapter = self.make()
            with self.assertRaises(AgentProviderError):
                adapter.complete(history, TOOLS)
            adapter._opener.open.assert_not_called()

    def test_request_size_and_non_json_inputs_are_bounded(self):
        for message in ({"role": "user", "content": "x" * (128 * 1024 + 1)}, {"role": "user", "content": object()}):
            adapter = self.make()
            with self.assertRaises(AgentProviderError):
                adapter.complete([message], TOOLS)
            adapter._opener.open.assert_not_called()

    def test_endpoint_and_config_cannot_redirect_credentials(self):
        invalid = [
            {"endpoint": "https://example.com/chat/completions"},
            {"endpoint": ENDPOINTS["meta"] + "?key=anything"},
            {"timeout": float("nan")}, {"max_tokens": 999999},
            {"temperature": float("inf")}, {"api_key_env": "NOT A NAME"},
            {"provider": []}, {"endpoint": ["not a URL"]}, {"api_key_env": ["not a name"]},
            {"endpoint": []}, {"endpoint": ""}, {"api_key_env": ""},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(AgentProviderError):
                AgentProvider({"provider": "meta", "model": "muse-spark-1.3", **changes})
        self.assertIsNone(_NoRedirect().redirect_request(Mock(), None, 307, "redirect", {}, "https://elsewhere.example"))

    def test_missing_credentials_fail_without_network(self):
        adapter = AgentProvider(ProviderConfig("meta", "muse-spark-1.3"))
        adapter._opener = Mock()
        with self.assertRaisesRegex(AgentProviderError, "credential is missing"):
            adapter.complete(MESSAGES, TOOLS)
        adapter._opener.open.assert_not_called()

    def test_http_and_network_errors_do_not_expose_details_or_retry(self):
        for error, expected in [
            (urllib.error.HTTPError(ENDPOINTS["meta"], 401, "PRIVATE REASON", {}, io.BytesIO(b"PRIVATE BODY")), "Provider request failed (HTTP 401)."),
            (urllib.error.URLError("PRIVATE DETAILS"), "Provider request failed or timed out."),
        ]:
            adapter = self.make()
            adapter._opener.open.side_effect = error
            with self.assertRaises(AgentProviderError) as caught:
                adapter.complete(MESSAGES, TOOLS)
            self.assertEqual(str(caught.exception), expected)
            self.assertTrue(caught.exception.__suppress_context__)
            adapter._opener.open.assert_called_once()

    def test_invalid_and_oversized_response_bytes_are_rejected(self):
        for data in (b"not-json", b"\xff", b"[]", b"x" * (MAX_RESPONSE_BYTES + 1)):
            adapter = self.make()
            response = self.reply(adapter, {})
            response.read.return_value = data
            with self.assertRaises(AgentProviderError):
                adapter.complete(MESSAGES, TOOLS)
            response.read.assert_called_with(MAX_RESPONSE_BYTES + 1)

    def test_budget_reserves_context_and_output_without_network(self):
        adapter = self.make(max_tokens=8192, reasoning_effort="low")
        budget = adapter.request_budget(MESSAGES, TOOLS)
        self.assertEqual(budget["reserved_input_tokens"], 1048576)
        self.assertEqual(budget["max_completion_tokens"], 8192)
        self.assertEqual(budget["reserved_cost_microdollars"], 1345536)
        self.assertGreater(budget["request_bytes"], len(MESSAGES[0]["content"].encode()))
        adapter._headers.assert_not_called()
        adapter._opener.open.assert_not_called()

    def test_usage_cost_is_conservative_and_unknown_never_becomes_zero(self):
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 100}
        self.assertEqual(cost_microdollars("meta", "muse-spark-1.3", usage), 210)
        self.assertEqual(cost_microdollars("meta", "muse-wonder-1.0", usage), 800)
        self.assertIsNone(cost_microdollars("meta", "unknown", usage))
        self.assertIsNone(cost_microdollars("meta", "muse-spark-1.3", {}))
        self.assertIsNone(cost_microdollars("fireworks", "accounts/fireworks/models/muse-spark-open", usage))

    def test_usage_preserves_cache_and_reasoning_counts(self):
        adapter = self.make()
        response = cloud_response()
        response["usage"]["prompt_tokens_details"] = {"cached_tokens": 5}
        response["usage"]["completion_tokens_details"] = {"reasoning_tokens": 7}
        self.reply(adapter, response)
        usage = adapter.complete(MESSAGES, TOOLS)["usage"]
        self.assertEqual(usage["cached_tokens"], 5)
        self.assertEqual(usage["reasoning_tokens"], 7)
        self.assertEqual(usage["completion_tokens"], 10)

    def test_missing_usage_is_unknown_not_zero_cost(self):
        adapter = self.make()
        response = cloud_response()
        response["usage"] = None
        self.reply(adapter, response)
        usage = adapter.complete(MESSAGES, TOOLS)["usage"]
        self.assertEqual(usage, {})
        self.assertIsNone(cost_microdollars("meta", "muse-spark-1.3", usage))


if __name__ == "__main__":
    unittest.main()
