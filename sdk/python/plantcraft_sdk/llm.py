"""An app writes with a language model through PlantCraft.

The app declares each use in ``[[contributes.llm]]`` of its ``app.toml``
(``plantcraft_sdk.contributes.LlmUse``); Setup › Language models lists it as
``<app id>:<id>``, where an administrator gives it the default model, another one or none.
The app then calls ``client.llm("algorithm-draft", messages)`` (``POST /api/v1/llm/{use}``):
PlantCraft picks the model, keeps the key and counts the calls. The app never sees a key or an
address.

A user's turn may carry images (``"images": [image(png_bytes)]``, or ``images=`` on
``client.llm``) for a model that reads them: a scanned drawing, a photo of a gauge, a chart.
At most ``MAX_IMAGES`` a call, each at most ``MAX_IMAGE_BYTES``, PNG, JPEG, WebP or GIF.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Mapping
from typing import Any

ROLES = ("user", "assistant")
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def image(data: bytes, media_type: str = "image/png") -> dict[str, str]:
    """An image for a user's turn: ``{"media_type", "data"}`` with the bytes in base64."""

    return {"media_type": media_type, "data": base64.b64encode(data).decode("ascii")}


def _images(items: Iterable[Any]) -> list[dict[str, str]]:
    out = []
    for item in items:
        if isinstance(item, (bytes, bytearray)):
            item = image(bytes(item))
        if not isinstance(item, Mapping):
            raise ValueError("an image is {media_type, data} with the data in base64")
        media_type = str(item.get("media_type", ""))
        if media_type not in IMAGE_TYPES:
            raise ValueError(f"an image is one of {', '.join(IMAGE_TYPES)}, not {media_type!r}")
        data = str(item.get("data", ""))
        try:
            size = len(base64.b64decode(data, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise ValueError("an image's data is base64") from exc
        if not size:
            raise ValueError("an image is empty")
        if size > MAX_IMAGE_BYTES:
            raise ValueError(f"an image is at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
        out.append({"media_type": media_type, "data": data})
    return out


def messages_body(
    messages: list[Mapping[str, Any]] | str,
    *,
    system: str = "",
    images: Iterable[Any] = (),
) -> dict[str, Any]:
    """The body of ``POST /api/v1/llm/{use}``: a question, or the turns of a chat. ``images``
    (bytes of PNG, or :func:`image`) go with the last user turn."""

    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    turns = []
    count = 0
    for item in messages:
        role = item.get("role", "user")
        if role not in ROLES:
            raise ValueError(f"a message's role is one of {', '.join(ROLES)}, not {role!r}")
        turn: dict[str, Any] = {"role": role, "content": str(item.get("content", ""))}
        pictures = _images(item.get("images") or [])
        if pictures:
            if role != "user":
                raise ValueError("only a user's turn carries images")
            turn["images"] = pictures
            count += len(pictures)
        turns.append(turn)
    if not turns or turns[-1]["role"] != "user":
        raise ValueError("the last message is the user's")
    extra = _images(images)
    if extra:
        turns[-1]["images"] = turns[-1].get("images", []) + extra
        count += len(extra)
    if count > MAX_IMAGES:
        raise ValueError(f"at most {MAX_IMAGES} images a call")
    return {"system": system, "messages": turns}


def split_use(app: str, use: str) -> str:
    """The use's own id from ``<id>`` or ``<app id>:<id>``; another app's use is refused."""

    owner, sep, name = use.partition(":")
    if not sep:
        return use
    if owner != app:
        raise ValueError(f"{app} calls only its own uses, not {use!r}")
    return name
