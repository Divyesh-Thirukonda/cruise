"""One model turn with normalized function calls, without a prescribed workflow.

Provider documentation verified October 28, 2026:
https://dev.meta.ai/docs/protocols/chat-completions
https://dev.meta.ai/docs/tool-calling
https://dev.meta.ai/docs/muse-spark-open/deploy
https://docs.fireworks.ai/api-reference/post-chatcompletions
https://docs.ollama.com/capabilities/tool-calling
https://dev.meta.ai/docs/pricing-rate-limits
https://dev.meta.ai/docs/cookbook/vision-input

History uses text messages and bounded inline user screenshots for Meta.
Assistant tool_calls may use normalized
{id, name, arguments: object} entries or OpenAI function entries. Tool replies
carry tool_call_id and text content; their name is resolved from history.
This module neither executes tools nor selects replacement providers/models.
"""

from dataclasses import dataclass, replace
import json
import base64
import io
import math
import os
import re
import urllib.error
import urllib.request
import uuid

from .cloud_provider import CloudConfigurationError, CloudProvider


ENDPOINTS = {
    "meta": "https://api.meta.ai/v1/chat/completions",
    "fireworks": "https://api.fireworks.ai/inference/v1/chat/completions",
    "ollama": "http://localhost:11434/api/chat",
}
_ALLOWED_ENDPOINTS = {
    "meta": {ENDPOINTS["meta"]},
    "fireworks": {ENDPOINTS["fireworks"]},
    "ollama": {ENDPOINTS["ollama"], "http://127.0.0.1:11434/api/chat", "http://[::1]:11434/api/chat"},
}
_KEY_ENVS = {"meta": "MODEL_API_KEY", "fireworks": "FIREWORKS_API_KEY"}
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_CONTENT_CHARS = 128 * 1024
MAX_ARGUMENT_BYTES = 256 * 1024
MAX_MESSAGES = 128
MAX_TOOLS = 32
MAX_CALLS = 32
MAX_IMAGE_BYTES = 350_000
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z", re.ASCII)
_CALL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z", re.ASCII)
# Rates are integer nanodollars per token; no cache discount is assumed.
# These are reporting estimates, not a balance or a substitute for a shared ledger.
_META_RATES = {
    "muse-spark-1.1": (1250, 4250),
    "muse-spark-1.2": (1250, 4250),
    "muse-spark-1.3": (1250, 4250),
    "muse-wonder-1.0": (4000, 20000),
}
_META_CONTEXT_TOKENS = 1_048_576


class AgentProviderError(RuntimeError):
    """Sanitized failure; optional billing describes a received Meta reply.

    None means usage is unknown and the reservation must remain held. Repairable
    marks a completed, billed reply with invalid assistant/tool output; it never
    authorizes executing that output or automatically retrying a request.
    """

    def __init__(self, message, *, billed_cost_microdollars=None, repairable=False):
        super().__init__(message)
        self.billed_cost_microdollars = billed_cost_microdollars
        self.repairable = repairable


ProviderError = AgentProviderError


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    endpoint: str | None = None
    api_key_env: str | None = None
    timeout: float = 90
    max_tokens: int = 4096
    temperature: float | None = None
    num_ctx: int = 8192
    reasoning_effort: str | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _string(value, label, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value):
        raise AgentProviderError(f"Invalid or oversized {label}.")
    return value


def _name(value):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise AgentProviderError("Invalid function name.")
    return value


def _identifier(value, label="model identifier"):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise AgentProviderError(f"Invalid {label}.")
    return value


def _call_id(value):
    if not isinstance(value, str) or not _CALL_ID.fullmatch(value):
        raise AgentProviderError("Invalid tool-call ID.")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-finite JSON number")


def _loads(text, label):
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise AgentProviderError(f"Invalid JSON in {label}.") from None


def _encode(value, limit, label):
    try:
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    except (ValueError, TypeError, RecursionError):
        raise AgentProviderError(f"Invalid JSON in {label}.") from None
    if len(encoded) > limit:
        raise AgentProviderError(f"{label} exceeds the size limit.")
    return encoded


def _arguments(value):
    if isinstance(value, str):
        if len(value) > MAX_ARGUMENT_BYTES:
            raise AgentProviderError("Tool arguments exceed the size limit.")
        value = _loads(value, "tool arguments")
    if not isinstance(value, dict):
        raise AgentProviderError("Tool arguments must be a JSON object.")
    # Round-trip to detach caller objects and reject non-JSON numbers/types.
    return _loads(_encode(value, MAX_ARGUMENT_BYTES, "Tool arguments"), "tool arguments")


def _calls(value, *, allowed=None, generate_ids=False):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_CALLS:
        raise AgentProviderError("Invalid or excessive tool calls.")
    result, seen = [], set()
    for raw in value:
        if not isinstance(raw, dict):
            raise AgentProviderError("Invalid tool call.")
        function = raw.get("function", raw)
        if not isinstance(function, dict) or raw.get("type", "function") != "function":
            raise AgentProviderError("Only function tool calls are supported.")
        name = _name(function.get("name"))
        if allowed is not None and name not in allowed:
            raise AgentProviderError("Model requested an unavailable tool.")
        identifier = raw.get("id")
        if identifier is None and generate_ids:
            identifier = "ollama_" + uuid.uuid4().hex
        identifier = _call_id(identifier)
        if identifier in seen:
            raise AgentProviderError("Duplicate tool-call ID.")
        seen.add(identifier)
        result.append({"id": identifier, "name": name, "arguments": _arguments(function.get("arguments"))})
    return result


def _wire_calls(calls, local):
    result = []
    for call in calls:
        arguments = call["arguments"] if local else _encode(
            call["arguments"], MAX_ARGUMENT_BYTES, "Tool arguments"
        ).decode("ascii")
        item = {"type": "function", "function": {"name": call["name"], "arguments": arguments}}
        if not local:
            item["id"] = call["id"]
        result.append(item)
    return result


def _image_parts(content):
    """Only bounded inline screenshots; never fetch a model-supplied URL.

    Meta contract: https://dev.meta.ai/docs/cookbook/vision-input
    """
    from PIL import Image
    if not 1 <= len(content) <= 2:
        raise AgentProviderError("Expected one screenshot and optional text.")
    parts, images = [], 0
    for part in content:
        if not isinstance(part, dict):
            raise AgentProviderError("Invalid image content part.")
        if part.get("type") == "text" and set(part) == {"type", "text"}:
            parts.append({"type": "text", "text": _string(part["text"], "image caption", 8000, empty=True)})
            continue
        if part.get("type") != "image_url" or set(part) != {"type", "image_url"}:
            raise AgentProviderError("Invalid image content part.")
        ref = part["image_url"]
        if not isinstance(ref, dict) or set(ref) != {"url"} or not isinstance(ref["url"], str):
            raise AgentProviderError("Invalid inline screenshot.")
        url = ref["url"]
        prefix = next((p for p in ("data:image/jpeg;base64,", "data:image/png;base64,") if url.startswith(p)), None)
        if prefix is None or len(url) > MAX_IMAGE_BYTES * 4 // 3 + 100:
            raise AgentProviderError("Screenshot must be a bounded inline PNG or JPEG.")
        try:
            raw = base64.b64decode(url[len(prefix):], validate=True)
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"PNG", "JPEG"} or max(image.size) > 1280 or min(image.size) < 1:
                    raise ValueError
                image.verify()
        except Exception:
            raise AgentProviderError("Invalid screenshot image.") from None
        images += 1
        parts.append({"type": "image_url", "image_url": {"url": url}})
    if images != 1:
        raise AgentProviderError("Expected exactly one screenshot.")
    return parts


def _messages(messages, local):
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise AgentProviderError("Messages must be a non-empty bounded list.")
    result, pending, seen = [], {}, set()
    for message in messages:
        if not isinstance(message, dict):
            raise AgentProviderError("Invalid message.")
        role = message.get("role")
        if not isinstance(role, str) or role not in {"system", "developer", "user", "assistant", "tool"}:
            raise AgentProviderError("Unsupported message role.")
        content = message.get("content")
        if content is None and role == "assistant":
            content = ""
        if isinstance(content, list):
            if role != "user" or local:
                raise AgentProviderError("Screenshots require a Meta user message.")
            content = _image_parts(content)
        else:
            content = _string(content, "message content", MAX_CONTENT_CHARS, empty=True)
        item = {"role": "system" if local and role == "developer" else role, "content": content}
        if role == "assistant":
            if pending:
                raise AgentProviderError("Tool results are missing before the next assistant turn.")
            calls = _calls(message.get("tool_calls"))
            for call in calls:
                if call["id"] in seen:
                    raise AgentProviderError("Duplicate tool-call ID in history.")
                seen.add(call["id"])
                pending[call["id"]] = call["name"]
            if calls:
                item["tool_calls"] = _wire_calls(calls, local)
            # Preserve provider reasoning privately when the caller replays it.
            reasoning = message.get("reasoning_content")
            if reasoning is not None and not local:
                item["reasoning_content"] = _string(reasoning, "reasoning content", MAX_CONTENT_CHARS, empty=True)
            thinking = message.get("thinking")
            if thinking is not None and local:
                item["thinking"] = _string(thinking, "thinking content", MAX_CONTENT_CHARS, empty=True)
        elif message.get("tool_calls"):
            raise AgentProviderError("Tool calls must belong to assistant messages.")
        if role == "tool":
            identifier = _call_id(message.get("tool_call_id"))
            if identifier not in pending:
                raise AgentProviderError("Tool result does not match a pending call.")
            name = pending.pop(identifier)
            if message.get("name", message.get("tool_name", name)) != name:
                raise AgentProviderError("Tool result name does not match its call.")
            if local:
                item["tool_name"] = name
            else:
                item["tool_call_id"] = identifier
        result.append(item)
    if pending:
        raise AgentProviderError("Tool results are missing from history.")
    return result


def _tools(tools):
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise AgentProviderError("Tools must be a bounded list.")
    result, names = [], set()
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            raise AgentProviderError("Only function tools are supported.")
        function = tool.get("function")
        if not isinstance(function, dict):
            raise AgentProviderError("Invalid function tool.")
        name = _name(function.get("name"))
        if name in names:
            raise AgentProviderError("Duplicate function tool.")
        names.add(name)
        parameters = function.get("parameters")
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise AgentProviderError("Tool parameters must use an object schema.")
        clean = {"name": name, "parameters": parameters}
        if "description" in function:
            clean["description"] = _string(function["description"], "tool description", 8000, empty=True)
        if "strict" in function:
            if type(function["strict"]) is not bool:
                raise AgentProviderError("Tool strict must be boolean.")
            clean["strict"] = function["strict"]
        result.append({"type": "function", "function": clean})
    return result, names


def _usage(result, local):
    source = result if local else result.get("usage", {})
    if source is None:
        return {}
    if not isinstance(source, dict):
        raise AgentProviderError("Invalid usage metadata.")
    mapping = {"prompt_eval_count": "prompt_tokens", "eval_count": "completion_tokens"} if local else {
        "prompt_tokens": "prompt_tokens", "completion_tokens": "completion_tokens", "total_tokens": "total_tokens"
    }
    usage = {}
    for source_name, target in mapping.items():
        if source_name in source:
            value = source[source_name]
            if type(value) is not int or not 0 <= value <= 10**12:
                raise AgentProviderError("Invalid usage metadata.")
            usage[target] = value
    if "total_tokens" not in usage and "prompt_tokens" in usage and "completion_tokens" in usage:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    if not local:
        for detail, name in (("prompt_tokens_details", "cached_tokens"), ("completion_tokens_details", "reasoning_tokens")):
            details = source.get(detail, {})
            if details is None:
                continue
            if not isinstance(details, dict):
                raise AgentProviderError("Invalid usage metadata.")
            if name in details:
                value = details[name]
                if type(value) is not int or not 0 <= value <= 10**12:
                    raise AgentProviderError("Invalid usage metadata.")
                usage[name] = value
    return usage


def cost_microdollars(provider, model, usage):
    """Round up a standard-rate usage estimate; None means unknown, never free.

    Deliberately ignores cache discounts, so the reported estimate can be higher
    than the invoice. A caller must retain its reservation whenever usage is
    unknown. A rejected assistant/tool payload may still
    carry validated billing. Reasoning tokens are included in completion_tokens.
    """
    if provider == "ollama":
        return 0
    rates = _META_RATES.get(model) if provider == "meta" else None
    if rates is None or not isinstance(usage, dict):
        return None
    values = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
    if any(type(value) is not int or value < 0 for value in values):
        return None
    return (sum(value * rate for value, rate in zip(values, rates)) + 999) // 1000


class AgentProvider:
    """A stateless, explicit provider/model binding for one assistant turn.

    complete() returns content, normalized tool_calls, usage, model and provider.
    Optional reasoning_content/thinking is replay metadata, not user-facing prose.
    Validate each tool's argument schema and permissions in the tool dispatcher;
    this adapter validates JSON shape and rejects unadvertised tool names only.
    """

    def __init__(self, config):
        if isinstance(config, dict):
            try:
                config = ProviderConfig(**config)
            except TypeError:
                raise AgentProviderError("Invalid provider configuration.") from None
        if not isinstance(config, ProviderConfig) or not isinstance(config.provider, str) or config.provider not in ENDPOINTS:
            raise AgentProviderError("Select meta, fireworks, or ollama explicitly.")
        model = _identifier(config.model.strip() if isinstance(config.model, str) else config.model)
        endpoint = ENDPOINTS[config.provider] if config.endpoint is None else config.endpoint
        if not isinstance(endpoint, str) or endpoint not in _ALLOWED_ENDPOINTS[config.provider]:
            raise AgentProviderError("Provider endpoint is not allowlisted.")
        if type(config.timeout) not in (int, float) or not math.isfinite(config.timeout) or not 1 <= config.timeout <= 180:
            raise AgentProviderError("Timeout must be between 1 and 180 seconds.")
        if type(config.max_tokens) is not int or not 1 <= config.max_tokens <= 32768:
            raise AgentProviderError("max_tokens must be between 1 and 32768.")
        if type(config.num_ctx) is not int or not 512 <= config.num_ctx <= 32768:
            raise AgentProviderError("num_ctx must be between 512 and 32768.")
        if config.temperature is not None and (
            type(config.temperature) not in (int, float) or not math.isfinite(config.temperature)
            or not 0 <= config.temperature <= 2
        ):
            raise AgentProviderError("Temperature must be between 0 and 2.")
        if config.reasoning_effort not in (None, "minimal", "low", "medium", "high", "xhigh", "max"):
            raise AgentProviderError("Unsupported reasoning effort.")
        if config.provider == "ollama" and config.reasoning_effort is not None:
            raise AgentProviderError("Ollama reasoning options require model-specific configuration.")
        if config.provider == "fireworks" and config.reasoning_effort not in (None, "low", "medium", "high", "xhigh"):
            raise AgentProviderError("Unsupported Fireworks reasoning effort.")
        key_env = _KEY_ENVS.get(config.provider) if config.api_key_env is None else config.api_key_env
        if key_env is not None and (not isinstance(key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key_env)):
            raise AgentProviderError("Invalid credential environment variable name.")
        self.config = replace(config, model=model, endpoint=endpoint, api_key_env=key_env)
        self._opener = urllib.request.build_opener(_NoRedirect())
        try:
            self._cloud = CloudProvider() if config.provider == "meta" else None
        except CloudConfigurationError:
            raise AgentProviderError("Modulate cloud provider configuration is incomplete or invalid.") from None

    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._cloud and self._cloud.enabled:
            return self._cloud.request("meta", {})[1]
        if self.config.provider != "ollama":
            key = os.environ.get(self.config.api_key_env, "").strip()
            if not key:
                raise AgentProviderError("Provider credential is missing from the configured environment variable.")
            if not key.isascii() or any(char.isspace() for char in key):
                raise AgentProviderError("Provider credential must be a single ASCII token.")
            headers["Authorization"] = "Bearer " + key
        return headers

    def _request(self, payload):
        data = _encode(payload, MAX_REQUEST_BYTES, "Request")
        headers = self._headers()
        endpoint = (self._cloud.request("meta", payload)[0]
                    if self._cloud and self._cloud.enabled else self.config.endpoint)
        try:
            request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            with self._opener.open(request, timeout=self.config.timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = error.code if type(error.code) is int else "unknown"
            error.close()
            raise AgentProviderError(f"Provider request failed (HTTP {status}).") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise AgentProviderError("Provider request failed or timed out.") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise AgentProviderError("Provider response exceeds the size limit.")
        result = _loads(body, "provider response")
        if not isinstance(result, dict) or "error" in result:
            raise AgentProviderError("Provider returned an invalid response.")
        return result

    def _payload(self, messages, tools):
        if self.config.provider != "meta" and any(isinstance(m.get("content"), list) for m in messages if isinstance(m, dict)):
            raise AgentProviderError("Computer vision is verified only for the Meta adapter.")
        local = self.config.provider == "ollama"
        definitions, names = _tools(tools)
        payload = {"model": self.config.model, "messages": _messages(messages, local), "stream": False}
        if definitions:
            payload["tools"] = definitions
            if not local:
                payload["tool_choice"] = "auto"
        if local:
            payload["options"] = {"num_predict": self.config.max_tokens, "num_ctx": self.config.num_ctx}
            if self.config.temperature is not None:
                payload["options"]["temperature"] = self.config.temperature
        else:
            token_field = "max_completion_tokens" if self.config.provider == "meta" else "max_tokens"
            payload[token_field] = self.config.max_tokens
            if self.config.temperature is not None:
                payload["temperature"] = self.config.temperature
            if self.config.reasoning_effort is not None:
                payload["reasoning_effort"] = self.config.reasoning_effort
        return payload, names

    def request_budget(self, messages, tools):
        """Pure preflight metadata, without credentials or a network request.

        Byte count is an estimate, not a guaranteed tokenizer bound. For known
        Meta text models, reserve the entire documented context plus the output
        cap at uncached rates. The deliberately larger reservation avoids relying
        on an approximate tokenizer; the shared caller ledger owns enforcement.
        """
        payload, _ = self._payload(messages, tools)
        size = len(_encode(payload, MAX_REQUEST_BYTES, "Request"))
        known_meta = self.config.provider == "meta" and self.config.model in _META_RATES
        reserved_input = _META_CONTEXT_TOKENS if known_meta else None
        usage = {"prompt_tokens": reserved_input, "completion_tokens": self.config.max_tokens}
        return {
            "request_bytes": size,
            "estimated_input_tokens": size,
            "reserved_input_tokens": reserved_input,
            "max_completion_tokens": self.config.max_tokens,
            "reserved_cost_microdollars": cost_microdollars(self.config.provider, self.config.model, usage),
        }

    def complete(self, messages, tools):
        local = self.config.provider == "ollama"
        payload, names = self._payload(messages, tools)
        # Transport/JSON failures have no trustworthy billing metadata. Do not
        # catch them as repairable model output or release their reservation.
        result = self._request(payload)
        # Validate billing independently, before assistant/tool action parsing.
        # Missing model or usage cannot establish a charge on a rejected reply.
        usage = _usage(result, local)
        model = _identifier(result.get("model", self.config.model))
        billed = (cost_microdollars("meta", model, usage)
                  if self.config.provider == "meta" and "model" in result else None)
        repairable = False
        try:
            if local:
                if result.get("done") is not True or result.get("done_reason") == "length":
                    raise AgentProviderError("Provider did not finish the assistant turn.")
                message = result.get("message")
            else:
                choices = result.get("choices")
                if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                    raise AgentProviderError("Provider returned invalid choices.")
                finish = choices[0].get("finish_reason")
                if not isinstance(finish, str) or finish not in {"stop", "tool_calls"}:
                    raise AgentProviderError("Provider did not finish the assistant turn.")
                message = choices[0].get("message")
                if isinstance(message, dict) and message.get("refusal"):
                    raise AgentProviderError("Provider refused the request.")
            # Only a completed Meta turn with known billing can invite a bounded
            # repair. Tool allowlisting and JSON validation remain unchanged.
            repairable = billed is not None
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise AgentProviderError("Provider returned an invalid assistant message.")
            content = message.get("content")
            content = "" if content is None else _string(content, "assistant content", MAX_CONTENT_CHARS, empty=True)
            calls = _calls(message.get("tool_calls"), allowed=names, generate_ids=local)
            if not content and not calls:
                raise AgentProviderError("Provider returned an empty assistant turn.")
            normalized = {"content": content, "tool_calls": calls, "usage": usage,
                          "model": model, "provider": self.config.provider}
            # Only replay these fields to the model; do not display private reasoning.
            reasoning_field = "thinking" if local else "reasoning_content"
            if message.get(reasoning_field) is not None:
                normalized[reasoning_field] = _string(message[reasoning_field], "reasoning metadata", MAX_CONTENT_CHARS, empty=True)
            return normalized
        except AgentProviderError as error:
            error.billed_cost_microdollars = billed
            error.repairable = repairable
            raise
