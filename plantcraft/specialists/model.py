"""A language model answering for a specialist, over plain HTTP(S) (no SDK, no other library).

Two wire formats: Anthropic's Messages API (``anthropic``; ``endpoint`` points at a
gateway or proxy in front of it) and OpenAI's (``openai``). OpenAI's own service is spoken
to through its Responses API, the one its reasoning models take tools in; any other address
through chat completions, which most company and local models speak (vLLM, Ollama, LM Studio,
Azure OpenAI, LiteLLM): ``endpoint`` is the base address, with its ``/v1``. The model may call
the specialist's read-only tools; the conversation is kept in Anthropic's form and turned
into the other one on the way out.
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from plantcraft.egress import proxy_for
from plantcraft.i18n import t
from plantcraft.specialists.profiles import DEFAULT_MODEL, PROVIDERS, REASONING

LOGGER = logging.getLogger(__name__)

ANTHROPIC_ENDPOINT = "https://api.anthropic.com"
OPENAI_ENDPOINT = "https://api.openai.com/v1"
TOOL_ROUNDS = 4
MAX_TOKENS = 4000
# OpenAI's newer models take max_completion_tokens (and refuse max_tokens); it also counts
# their reasoning, hence the larger allowance. Servers that speak the older form (vLLM, Ollama,
# LM Studio, older Azure deployments) take max_tokens. Each client starts from the form its
# address suggests and switches once when the service names the other one.
COMPLETION_TOKENS = 16000
TOKEN_PARAMS = ("max_completion_tokens", "max_tokens")
# Anthropic's mark for the start of a request it may keep for the next ones (5 minutes).
CACHED = {"type": "ephemeral"}

Tool = Callable[[str, dict[str, Any]], Any]

# Seconds one call to the model may take: small reasoning models with a page of tool results
# took over 60 s per call (gpt-5-nano, 2026-10-26).
CALL_TIMEOUT = 180


class ChatModel:
    def __init__(
        self,
        api_key: str,
        *,
        provider: str = "anthropic",
        model: str = "",
        endpoint: str = "",
        timeout: float = CALL_TIMEOUT,
        reasoning: str = "",
    ):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider {provider}")
        self.provider = provider
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        # How many rounds of tool calls before an answer is asked for with what was read.
        self.rounds = TOOL_ROUNDS
        self.reasoning = reasoning if reasoning in REASONING else ""
        # Set by the chat: the answer's text so far, as the model writes it (streamed; each
        # call starts again from ""). Left None, each call waits for the whole answer.
        self.on_text: Callable[[str], None] | None = None
        # The tokens of the latest ``answer``, all its calls together (``usage_of``): what the
        # chat keeps with each answer, to know what an answer costs.
        self.usage: dict[str, int] = empty_usage()
        if provider == "openai":
            if not model:
                raise ValueError("Name the model to use.")
            base = (endpoint or OPENAI_ENDPOINT).rstrip("/")
            openai = urllib.parse.urlsplit(base).hostname == "api.openai.com"
            # OpenAI's reasoning models refuse tools in chat completions ("Function tools with
            # reasoning_effort are not supported"): its own service gets the Responses API.
            self.responses = openai
            self.url = f"{base}/responses" if openai else f"{base}/chat/completions"
            self.label = f"{self.model}"
            self.token_param = TOKEN_PARAMS[0] if openai else TOKEN_PARAMS[1]
        else:
            self.responses = False
            self.url = f"{(endpoint or ANTHROPIC_ENDPOINT).rstrip('/')}/v1/messages"
            self.label = f"Claude · {self.model}"

    def answer(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tool: Tool | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        conversation = list(messages)
        self.usage = empty_usage()
        for _ in range(self.rounds + 1):
            payload = self._call(system, conversation, tools if tool else None)
            content = payload.get("content") or []
            if payload.get("stop_reason") == "refusal":
                raise RuntimeError("The model refused to answer.")
            calls = [block for block in content if block.get("type") == "tool_use"]
            text = _text(content)
            if payload.get("stop_reason") != "tool_use" or not calls or tool is None:
                if not text:
                    raise RuntimeError("Empty answer from the model.")
                return text
            conversation.append({"role": "assistant", "content": content})
            results = []
            for call in calls:
                try:
                    value = tool(call.get("name", ""), call.get("input") or {})
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": json.dumps(value, ensure_ascii=False, default=str)[:12000],
                        }
                    )
                except Exception as exc:  # a tool error goes back to the model, not to the person
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": str(exc)[:300],
                            "is_error": True,
                        }
                    )
            conversation.append({"role": "user", "content": results})
        # Out of tool rounds: an answer with what it has.
        text = _text(self._call(system, conversation, None).get("content") or [])
        if not text:
            raise RuntimeError("Empty answer from the model.")
        return text

    def _call(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        if self.provider == "openai" and self.responses:
            return _from_responses(
                self._post(
                    _to_responses(self.model, system, messages, tools, self.reasoning),
                    {},
                    _ResponsesStream,
                )
            )
        if self.provider == "openai":
            body = _to_openai(self.model, system, messages, tools)
            if self.reasoning:
                body["reasoning_effort"] = self.reasoning
            try:
                return _from_openai(
                    self._post(_with_tokens(body, self.token_param), {}, _CompletionStream)
                )
            except _OtherTokenParam:
                # The service names the other form: use it from now on.
                self.token_param = _other(self.token_param)
                try:
                    return _from_openai(
                        self._post(_with_tokens(body, self.token_param), {}, _CompletionStream)
                    )
                except _OtherTokenParam as exc:
                    raise RuntimeError(_http_problem(400, str(exc))) from exc
        # Anthropic reuses a request's start only where ``cache_control`` marks it: the tools
        # (the same for every question) and the instructions (the same in each round of one
        # answer). Below the model's minimum length nothing is cached, and nothing fails.
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": MAX_TOKENS,
            "system": [{"type": "text", "text": system, "cache_control": CACHED}],
            "messages": messages,
        }
        if tools:
            body["tools"] = [*tools[:-1], {**tools[-1], "cache_control": CACHED}]
        return self._post(
            body,
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            _MessagesStream,
        )

    def _post(
        self, body: dict[str, Any], headers: dict[str, str], stream: type[_Stream] | None = None
    ) -> dict[str, Any]:
        """One call to the service; with ``on_text`` set and a ``stream`` reader for the format,
        the answer comes as server-sent events, read into the same answer as a whole one."""

        streaming = stream is not None and self.on_text is not None
        if streaming:
            body = {**body, "stream": True}
        if self.provider == "openai" and self.api_key:
            headers = {**headers, "authorization": f"Bearer {self.api_key}"}
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={**headers, "content-type": "application/json"},
            method="POST",
        )
        # A model on the internet is reached through the suite's one way out (llm-egress); a
        # model on the plant's network directly. Never the environment's proxy settings.
        proxy = proxy_for(self.url)
        try:
            with _open(request, self.timeout, proxy) as response:
                kind = (getattr(response, "headers", None) or {}).get("content-type") or ""
                if streaming and stream is not None and "event-stream" in kind:
                    found = stream(self.on_text or (lambda _text: None)).read(response)
                else:
                    # A server that does not stream answers the whole answer at once.
                    found = json.loads(response.read().decode("utf-8"))
                add_usage(self.usage, usage_of(found))
                return found
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 400 and self.provider == "openai" and _names_token_param(detail, body):
                raise _OtherTokenParam(detail) from exc
            problem = _http_problem(exc.code, detail)
            if exc.code == 400 and "reasoning" in detail.lower():
                problem += " " + t(
                    "Change the provider's reasoning effort in Settings › Language models."
                )
            raise ModelServiceError(problem, exc.code) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(_reach_problem(self.url, exc.reason, bool(proxy))) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError(t("The model service did not answer in time.")) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(t("The model service did not answer in JSON.")) from exc


class _Stream:
    """Server-sent events of one call, read into the answer the whole call would have given;
    ``shown`` sees the text written so far."""

    def __init__(self, shown: Callable[[str], None]):
        self.shown = shown
        self.text = ""
        self.shown("")

    def read(self, response: Any) -> dict[str, Any]:
        for raw in response:
            line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                self.event(event)
        return self.result()

    def write(self, delta: Any) -> None:
        if isinstance(delta, str) and delta:
            self.text += delta
            self.shown(self.text)

    def event(self, event: dict[str, Any]) -> None:
        raise NotImplementedError

    def result(self) -> dict[str, Any]:
        raise NotImplementedError


class _ResponsesStream(_Stream):
    """OpenAI's Responses API: text deltas, then the whole response in its last event."""

    final: dict[str, Any] | None = None

    def event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "response.output_text.delta":
            self.write(event.get("delta"))
        elif kind in ("response.completed", "response.incomplete"):
            self.final = event.get("response") or {}
        elif kind in ("response.failed", "error"):
            problem = (event.get("response") or {}).get("error") or event.get("error") or event
            message = problem.get("message") if isinstance(problem, dict) else problem
            raise RuntimeError(t("The model service answered: {detail}", detail=str(message)[:300]))

    def result(self) -> dict[str, Any]:
        if self.final is None:
            raise RuntimeError(t("The model service stopped before the answer was complete."))
        return self.final


class _CompletionStream(_Stream):
    """Chat completions: content and tool call deltas, put together as one completion."""

    def __init__(self, shown: Callable[[str], None]):
        super().__init__(shown)
        self.calls: dict[int, dict[str, Any]] = {}
        self.reason: str | None = None
        self.usage: dict[str, Any] | None = None

    def event(self, event: dict[str, Any]) -> None:
        if isinstance(event.get("usage"), dict):
            self.usage = event["usage"]
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            self.write(delta.get("content"))
            for call in delta.get("tool_calls") or []:
                slot = self.calls.setdefault(
                    int(call.get("index") or 0), {"id": "", "name": "", "arguments": ""}
                )
                function = call.get("function") or {}
                slot["id"] = call.get("id") or slot["id"]
                slot["name"] += function.get("name") or ""
                slot["arguments"] += function.get("arguments") or ""
            self.reason = choice.get("finish_reason") or self.reason

    def result(self) -> dict[str, Any]:
        calls = [
            {
                "id": slot["id"] or slot["name"],
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
            }
            for _, slot in sorted(self.calls.items())
        ]
        message: dict[str, Any] = {"content": self.text or None}
        if calls:
            message["tool_calls"] = calls
        found: dict[str, Any] = {"choices": [{"message": message, "finish_reason": self.reason}]}
        if self.usage:
            found["usage"] = self.usage
        return found


class _MessagesStream(_Stream):
    """Anthropic's Messages API: content blocks built from their deltas."""

    def __init__(self, shown: Callable[[str], None]):
        super().__init__(shown)
        self.blocks: dict[int, dict[str, Any]] = {}
        self.reason: str | None = None
        self.usage: dict[str, Any] = {}

    def event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        index = int(event.get("index") or 0)
        if kind == "message_start":
            self.usage.update(((event.get("message") or {}).get("usage")) or {})
        if kind == "message_delta" and isinstance(event.get("usage"), dict):
            self.usage.update(event["usage"])
        if kind == "content_block_start":
            block = dict(event.get("content_block") or {})
            if block.get("type") == "tool_use":
                block["partial"] = ""
            self.blocks[index] = block
        elif kind == "content_block_delta":
            delta = event.get("delta") or {}
            block = self.blocks.setdefault(index, {"type": "text", "text": ""})
            if delta.get("type") == "text_delta":
                block["text"] = block.get("text", "") + (delta.get("text") or "")
                self.write(delta.get("text"))
            elif delta.get("type") == "input_json_delta":
                block["partial"] = block.get("partial", "") + (delta.get("partial_json") or "")
        elif kind == "message_delta":
            self.reason = (event.get("delta") or {}).get("stop_reason") or self.reason
        elif kind == "error":
            problem = event.get("error") or {}
            raise RuntimeError(
                t("The model service answered: {detail}", detail=str(problem.get("message"))[:300])
            )

    def result(self) -> dict[str, Any]:
        content = []
        for _, block in sorted(self.blocks.items()):
            if block.get("type") == "tool_use":
                try:
                    arguments = json.loads(block.pop("partial", "") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                block["input"] = arguments if isinstance(arguments, dict) else {}
            content.append(block)
        return {"content": content, "stop_reason": self.reason, "usage": self.usage}


def empty_usage() -> dict[str, int]:
    return {"calls": 0, "input": 0, "cached": 0, "output": 0, "reasoning": 0}


def _count(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def usage_of(payload: Any) -> dict[str, int]:
    """One call's tokens, whichever service answered: OpenAI's Responses API
    (``input_tokens``, ``output_tokens`` and their details), chat completions (``prompt_tokens``,
    ``completion_tokens``) or Anthropic's Messages API (``input_tokens``,
    ``cache_read_input_tokens``). ``input`` counts the cached tokens too."""

    found = empty_usage()
    found["calls"] = 1
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return found
    details_in = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
    details_out = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    cache_read = _count(usage.get("cache_read_input_tokens"))
    found["input"] = (
        _count(usage.get("input_tokens") or usage.get("prompt_tokens"))
        + cache_read
        + _count(usage.get("cache_creation_input_tokens"))
    )
    found["cached"] = cache_read or _count(
        details_in.get("cached_tokens") if isinstance(details_in, dict) else 0
    )
    found["output"] = _count(usage.get("output_tokens") or usage.get("completion_tokens"))
    found["reasoning"] = _count(
        details_out.get("reasoning_tokens") if isinstance(details_out, dict) else 0
    )
    return found


def add_usage(total: dict[str, int], more: dict[str, int]) -> None:
    for key, value in more.items():
        total[key] = total.get(key, 0) + value


class _OtherTokenParam(RuntimeError):
    """The service refused the answer-length parameter sent and names the other form."""


def _other(param: str) -> str:
    return TOKEN_PARAMS[1] if param == TOKEN_PARAMS[0] else TOKEN_PARAMS[0]


def _with_tokens(body: dict[str, Any], param: str) -> dict[str, Any]:
    clean = {key: value for key, value in body.items() if key not in TOKEN_PARAMS}
    clean[param] = COMPLETION_TOKENS if param == TOKEN_PARAMS[0] else MAX_TOKENS
    return clean


def _names_token_param(detail: str, body: dict[str, Any]) -> bool:
    """A 400 that refuses the length parameter sent ("Unsupported parameter: 'max_tokens'... Use
    'max_completion_tokens' instead", or an older server that does not know the new one)."""

    sent = next((key for key in TOKEN_PARAMS if key in body), "")
    lowered = detail.lower()
    return (
        bool(sent)
        and sent in lowered
        and any(
            word in lowered
            for word in ("unsupported", "not supported", "unrecognized", "unknown", "extra")
        )
    )


def _open(request: urllib.request.Request, timeout: float, proxy: str = "") -> Any:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy} if proxy else {})
    )
    return opener.open(request, timeout=timeout)


class ModelServiceError(RuntimeError):
    """The model service answered with an error (``code``: its HTTP status)."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def _http_problem(code: int, detail: str) -> str:
    """What an error answer of the model service means, in words an administrator can act on."""

    if code == 401:
        return t(
            "The model service refused the key (401). Check the provider's key in Settings › Language models."
        )
    if code == 403:
        return t("The model service refused this key or this model (403): {detail}", detail=detail)
    if code == 404:
        return t(
            "The model service does not know this model or address (404). Check the model's name and the address."
        )
    if code == 429:
        return t(
            "The model service is limiting this key (429): too many calls, or no credit left on the account."
        )
    return t("The model service answered {code}: {detail}", code=code, detail=detail)


def _reach_problem(url: str, reason: object, proxied: bool) -> str:
    """Why the model service could not be reached: a name not found, the suite's gate, the network."""

    host = urllib.parse.urlsplit(url).hostname or url
    text = str(reason)
    if proxied and "403" in text:
        return t(
            "The suite's way out refused {host}: only the providers added in Settings › Language models can be reached.",
            host=host,
        )
    if (
        isinstance(reason, socket.gaierror)
        or "Name or service not known" in text
        or "name resolution" in text
    ):
        return t(
            "Couldn't find {host}: this installation resolves no names outside the plant. "
            "A model in the cloud is reached through llm-egress (docs/security-guide.md).",
            host=host,
        )
    if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in text:
        return t("The model service did not answer in time.")
    return t("The model service could not be reached: {reason}", reason=text)


def _data_url(block: dict[str, Any]) -> str:
    """An Anthropic image block as the data URL OpenAI reads."""

    source = block.get("source") or {}
    return f"data:{source.get('media_type', 'image/png')};base64,{source.get('data', '')}"


def _to_openai(
    model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """An Anthropic-form conversation as an OpenAI chat completions request."""

    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            out.append({"role": message["role"], "content": content})
            continue
        blocks = content or []
        if message["role"] == "assistant":
            calls = [
                {
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                }
                for block in blocks
                if block.get("type") == "tool_use"
            ]
            entry: dict[str, Any] = {"role": "assistant", "content": _text(blocks) or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        pictures = [_data_url(block) for block in blocks if block.get("type") == "image"]
        if pictures:
            parts: list[dict[str, Any]] = [
                {"type": "text", "text": block.get("text", "")}
                for block in blocks
                if block.get("type") == "text"
            ]
            parts += [{"type": "image_url", "image_url": {"url": url}} for url in pictures]
            out.append({"role": "user", "content": parts})
            continue
        for block in blocks:
            if block.get("type") == "tool_result":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": str(block.get("content", "")),
                    }
                )
            elif block.get("type") == "text":
                out.append({"role": "user", "content": block.get("text", "")})
    body: dict[str, Any] = {"model": model, "messages": out}
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "parameters": item.get("input_schema") or {"type": "object"},
                },
            }
            for item in tools
        ]
    return body


def _to_responses(
    model: str,
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    reasoning: str = "",
) -> dict[str, Any]:
    """An Anthropic-form conversation as an OpenAI Responses request. Nothing is kept on
    OpenAI's side (``store`` false): each call carries the whole conversation."""

    items: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            items.append({"role": message["role"], "content": content})
            continue
        pictures = [_data_url(b) for b in content or [] if b.get("type") == "image"]
        if pictures:
            parts: list[dict[str, Any]] = [
                {"type": "input_text", "text": b.get("text", "")}
                for b in content or []
                if b.get("type") == "text"
            ]
            parts += [{"type": "input_image", "image_url": url} for url in pictures]
            items.append({"role": message["role"], "content": parts})
            continue
        for block in content or []:
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                items.append({"role": message["role"], "content": block["text"]})
            elif kind == "tool_use":
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block["id"],
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    }
                )
            elif kind == "tool_result":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": block["tool_use_id"],
                        "output": str(block.get("content", "")),
                    }
                )
    body: dict[str, Any] = {
        "model": model,
        "instructions": system,
        "input": items,
        "max_output_tokens": COMPLETION_TOKENS,
        "store": False,
    }
    if tools:
        # Requests with the same tools go to the same cache: OpenAI then reuses their start
        # (the tools and the instructions' fixed rules) at the cached price.
        names = ",".join(sorted(item["name"] for item in tools))
        body["prompt_cache_key"] = "plantcraft-" + hashlib.sha256(names.encode()).hexdigest()[:16]
    if reasoning:
        body["reasoning"] = {"effort": reasoning}
    if tools:
        # strict is on by default there, and asks every property be required: the tools'
        # schemas have optional ones.
        body["tools"] = [
            {
                "type": "function",
                "name": item["name"],
                "description": item.get("description", ""),
                "parameters": item.get("input_schema") or {"type": "object"},
                "strict": False,
            }
            for item in tools
        ]
    return body


def _from_responses(payload: dict[str, Any]) -> dict[str, Any]:
    """An OpenAI Responses answer as the Anthropic answer ``answer`` reads."""

    content: list[dict[str, Any]] = []
    refused = False
    for item in payload.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and part.get("text"):
                    content.append({"type": "text", "text": str(part["text"])})
                elif part.get("type") == "refusal":
                    refused = True
        elif item.get("type") == "function_call":
            try:
                arguments = json.loads(item.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            content.append(
                {
                    "type": "tool_use",
                    "id": item.get("call_id") or item.get("id") or item.get("name", "call"),
                    "name": item.get("name", ""),
                    "input": arguments if isinstance(arguments, dict) else {},
                }
            )
    if not content and refused:
        return {"content": [], "stop_reason": "refusal"}
    if not content and payload.get("status") == "incomplete":
        reason = (payload.get("incomplete_details") or {}).get("reason") or "incomplete"
        raise RuntimeError(t("The model stopped before answering ({reason}).", reason=str(reason)))
    calls = any(block["type"] == "tool_use" for block in content)
    return {"content": content, "stop_reason": "tool_use" if calls else "end_turn"}


def _from_openai(payload: dict[str, Any]) -> dict[str, Any]:
    """An OpenAI chat completion as the Anthropic answer ``answer`` reads."""

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("Empty answer from the model.")
    message = choices[0].get("message") or {}
    content: list[dict[str, Any]] = []
    if message.get("content"):
        content.append({"type": "text", "text": str(message["content"])})
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            arguments = {}
        content.append(
            {
                "type": "tool_use",
                "id": call.get("id") or function.get("name", "call"),
                "name": function.get("name", ""),
                "input": arguments if isinstance(arguments, dict) else {},
            }
        )
    reason = choices[0].get("finish_reason")
    calls = any(block["type"] == "tool_use" for block in content)
    return {
        "content": content,
        "stop_reason": "tool_use" if calls or reason == "tool_calls" else "end_turn",
    }


def _text(content: list[dict[str, Any]]) -> str:
    return "".join(
        block.get("text", "") for block in content if block.get("type") == "text"
    ).strip()
