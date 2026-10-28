"""The language model behind the chat: any OpenAI-compatible server, or Anthropic's Messages API.

Called with the standard library (urllib), one request per answer, no streaming: answers are
short. The key comes from the environment or a file and is never logged or sent to the page.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com/v1"
# OpenAI's reasoning models spend max_completion_tokens on thinking before the answer: without
# room for it a normal question came back empty (site test, 2026-10-27). The prompt keeps the
# answer short; this is only headroom.
REASONING_ROOM = 4000


class ModelError(RuntimeError):
    """The model could not answer (network, quota, refusal): the visitor gets the contact form."""


class Model(Protocol):
    name: str

    def complete(self, system: str, messages: list[dict[str, str]], max_tokens: int) -> str: ...


@dataclass
class OpenAIModel:
    """Chat completions of OpenAI or any compatible server (vLLM, Ollama, LM Studio...)."""

    name: str
    api_key: str
    base_url: str = OPENAI_URL
    reasoning_effort: str = ""
    timeout: float = 45.0

    def complete(self, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        body: dict = {
            "model": self.name,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        # OpenAI's own API counts reasoning in max_completion_tokens; compatible servers read
        # max_tokens.
        if self.base_url.rstrip("/") == OPENAI_URL:
            body["max_completion_tokens"] = max_tokens + REASONING_ROOM
        else:
            body["max_tokens"] = max_tokens
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        data = _post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            body,
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout,
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("unexpected answer from the model") from exc
        if not text.strip():
            raise ModelError("empty answer from the model")
        return text


@dataclass
class AnthropicModel:
    """Anthropic's Messages API."""

    name: str
    api_key: str
    base_url: str = ANTHROPIC_URL
    timeout: float = 45.0

    def complete(self, system: str, messages: list[dict[str, str]], max_tokens: int) -> str:
        body = {
            "model": self.name,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        data = _post(
            f"{self.base_url.rstrip('/')}/messages",
            body,
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            self.timeout,
        )
        try:
            text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise ModelError("unexpected answer from the model") from exc
        if not text.strip():
            raise ModelError("empty answer from the model")
        return text


def _post(url: str, body: dict, headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # The status only: a provider's error body can echo parts of the request.
        raise ModelError(f"the model answered HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ModelError(f"the model could not be reached ({type(exc).__name__})") from None


DEFAULT_MODELS = {"openai": "gpt-5-mini", "anthropic": "claude-haiku-5-5"}


def make_model(provider: str, api_key: str, name: str = "", base_url: str = "", effort: str = ""):
    """The configured model, or None when the chat's model is off (no provider or no key)."""
    provider = provider.strip().lower()
    if provider in ("", "off") or not api_key:
        return None
    name = name or DEFAULT_MODELS.get(provider, "")
    if provider == "openai":
        # A site answer needs little thinking: low effort unless set, for reasoning models.
        if not effort and name.startswith(("gpt-5", "o3", "o4")):
            effort = "low"
        return OpenAIModel(name, api_key, base_url or OPENAI_URL, effort)
    if provider == "anthropic":
        return AnthropicModel(name, api_key, base_url or ANTHROPIC_URL)
    raise ValueError(f"unknown SITE_CHAT_PROVIDER {provider!r}: use openai, anthropic or off")
