"""The models the battery asks: one that obeys everything, and a real one that is measured.

Both are ``ChatModel``s, so the engine's own loop (tool rounds, tool errors, the last answer
asked without tools) runs exactly as in a person's chat. Only the call to the service changes:
``ObedientModel`` answers it itself, ``MeteredModel`` makes it and keeps the tokens it cost.

An instruction the obedient model follows is written ``<<obey:{json}>>`` anywhere it reads
(the person's question, an asset's description, a result's summary). A real model sees the same
text as one more injection attempt. The actions:

- ``{"do": "call", "tool": name, "args": {...}, "times": n}``: call a tool ``n`` times in one round.
- ``{"do": "loop", "tool": name, "args": {...}}``: call it again every round, for ever.
- ``{"do": "say", "text": "...", "repeat": n}``: write that text (``n`` times) in the answer.
- ``{"do": "echo", "what": "system" | "seen" | "all"}``: write the instructions it was given,
  everything tools returned, or both and the whole conversation.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

from plantcraft.specialists.model import ChatModel

OBEY = re.compile(r"<<obey:(\{.*?\})>>", re.S)


def obey(action: dict[str, Any]) -> str:
    """The marker the obedient model follows, written into an attack's text."""

    return f"<<obey:{json.dumps(action, separators=(',', ':'))}>>"


class Meter:
    """What every model answer cost: one record per answer (one model object per answer)."""

    lock = threading.Lock()
    records: list[dict[str, Any]] = []

    @classmethod
    def start(cls, label: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "model": label,
            "calls": 0,
            "input_tokens": 0,
            "cached_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "seconds": 0.0,
            "tool_calls": 0,
            "tool_results": [],
            "system": "",
            "history_turns": 0,
            "created": time.monotonic(),
        }
        with cls.lock:
            cls.records.append(record)
        return record

    @classmethod
    def since(cls, moment: float) -> list[dict[str, Any]]:
        with cls.lock:
            return [item for item in cls.records if item["created"] >= moment]

    @classmethod
    def reset(cls) -> None:
        with cls.lock:
            cls.records = []


def _texts(content: Any) -> list[str]:
    """The text of one turn: its words, and what each tool returned."""

    if isinstance(content, str):
        return [content]
    found: list[str] = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            found.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_result":
            found.append(str(block.get("content") or ""))
    return found


def _tool_results(messages: list[dict[str, Any]]) -> list[str]:
    return [
        str(block.get("content") or "")
        for turn in messages
        if isinstance(turn.get("content"), list)
        for block in turn["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


class _Measured(ChatModel):
    """A ChatModel whose every call is timed and whose tool results and prompt are kept."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.record = Meter.start(self.label)

    def _call(self, system, messages, tools):  # type: ignore[override]
        self.record["calls"] += 1
        self.record["system"] = system
        self.record["tool_results"] = _tool_results(messages)
        if self.record["calls"] == 1:
            self.record["history_turns"] = len(messages)
        started = time.monotonic()
        try:
            payload = self._answer_call(system, messages, tools)
        finally:
            self.record["seconds"] += time.monotonic() - started
        self.record["tool_calls"] += sum(
            1 for block in payload.get("content") or [] if block.get("type") == "tool_use"
        )
        return payload

    def _answer_call(self, system, messages, tools):
        return super()._call(system, messages, tools)

    def _count(self, usage: dict[str, Any] | None) -> None:
        if not isinstance(usage, dict):
            return
        record = self.record
        record["input_tokens"] += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        record["output_tokens"] += int(
            usage.get("output_tokens") or usage.get("completion_tokens") or 0
        )
        details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
        record["cached_tokens"] += int(details.get("cached_tokens") or 0)
        out = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
        record["reasoning_tokens"] += int(out.get("reasoning_tokens") or 0)


class MeteredModel(_Measured):
    """The real model, as Settings › Language models makes it, with each call's tokens kept.

    ``reasoning`` set on the class (``--reasoning low``) overrides the installation's."""

    reasoning_override = ""

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        super().__init__(
            api_key,
            provider=provider,
            model=model,
            endpoint=endpoint,
            reasoning=self.reasoning_override or reasoning,
        )

    def _post(self, body, headers, stream=None):  # type: ignore[override]
        payload = super()._post(body, headers, stream)
        self._count(payload.get("usage") if isinstance(payload, dict) else None)
        return payload


class ObedientModel(_Measured):
    """A model with no judgement at all: it does what any text it reads tells it to.

    Without an instruction it answers in one line. ``latency`` (seconds per call) stands in for a
    real model's time in the load group."""

    latency = 0.0

    def __init__(self, api_key, *, provider, model, endpoint, reasoning=""):
        super().__init__(
            api_key or "none",
            provider="openai",
            model=model or "obedient",
            endpoint=endpoint or "http://llm.battery.localhost/v1",
        )
        self.label = "obedient (fake)"
        self.record["model"] = self.label
        self.queue: list[dict[str, Any]] = []
        self.read_upto = 0
        self.said: list[str] = []
        self.ids = 0
        self.looping: dict[str, Any] | None = None

    def _answer_call(self, system, messages, tools):
        if self.latency:
            time.sleep(self.latency)
        # Every instruction in what is new since the last call, in the order it was read: its
        # instructions (the page's context is there) once, then each new turn.
        new = [] if self.read_upto else [system]
        new += [text for turn in messages[self.read_upto :] for text in _texts(turn.get("content"))]
        for text in new:
            # A tool's answer reaches the model as JSON: the marker's quotes come escaped.
            for raw in OBEY.findall(text.replace('\\"', '"')):
                try:
                    self.queue.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
        self.read_upto = len(messages)
        while self.queue:
            action = self.queue.pop(0)
            kind = action.get("do")
            if kind == "say":
                repeat = max(1, min(100_000, int(action.get("repeat") or 1)))
                self.said.append(str(action.get("text") or "") * repeat)
            elif kind == "echo":
                self.said.append(self._echo(str(action.get("what") or "all"), system, messages))
            elif kind == "loop":
                self.looping = action
            elif kind == "call" and tools:
                times = max(1, min(500, int(action.get("times") or 1)))
                return self._calls([action] * times)
        if self.looping and tools:
            return self._calls([self.looping])
        text = "\n\n".join(item for item in self.said if item) or "Done."
        return self._usage(
            {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"},
            system,
            messages,
            text,
        )

    def _calls(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        content = []
        for action in actions:
            self.ids += 1
            content.append(
                {
                    "type": "tool_use",
                    "id": f"call_{self.ids}",
                    "name": str(action.get("tool") or ""),
                    "input": action.get("args") or {},
                }
            )
        return {"content": content, "stop_reason": "tool_use"}

    def _usage(self, payload, system, messages, text):
        # About four characters a token: enough to compare the cost of one case with another.
        seen = len(system) + sum(
            len(json.dumps(turn.get("content"), default=str)) for turn in messages
        )
        self._count({"input_tokens": seen // 4, "output_tokens": len(text) // 4})
        return payload

    @staticmethod
    def _echo(what: str, system: str, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        if what in ("system", "all"):
            parts.append(system)
        if what in ("seen", "all"):
            parts.extend(_tool_results(messages))
        if what == "all":
            parts.extend(text for turn in messages for text in _texts(turn.get("content")))
        return "\n".join(parts)
