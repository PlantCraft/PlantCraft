"""An app writes with a language model through PlantCraft.

The app declares each use in ``[[contributes.llm]]`` of its ``app.toml``
(``plantcraft_sdk.contributes.LlmUse``); Setup › Language models lists it as
``<app id>:<id>``, where an administrator gives it the default model, another one or none.
The app then calls ``client.llm("algorithm-draft", messages)`` (``POST /api/v1/llm/{use}``):
PlantCraft picks the model, keeps the key and counts the calls. The app never sees a key or an
address.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ROLES = ("user", "assistant")


def messages_body(messages: list[Mapping[str, str]] | str, *, system: str = "") -> dict[str, Any]:
    """The body of ``POST /api/v1/llm/{use}``: a question, or the turns of a chat."""

    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    turns = []
    for item in messages:
        role = item.get("role", "user")
        if role not in ROLES:
            raise ValueError(f"a message's role is one of {', '.join(ROLES)}, not {role!r}")
        turns.append({"role": role, "content": str(item.get("content", ""))})
    if not turns or turns[-1]["role"] != "user":
        raise ValueError("the last message is the user's")
    return {"system": system, "messages": turns}


def split_use(app: str, use: str) -> str:
    """The use's own id from ``<id>`` or ``<app id>:<id>``; another app's use is refused."""

    owner, sep, name = use.partition(":")
    if not sep:
        return use
    if owner != app:
        raise ValueError(f"{app} calls only its own uses, not {use!r}")
    return name
