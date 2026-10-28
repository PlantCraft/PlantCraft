"""The kinds of value a point holds, and how each is written, stored and read.

- ``number``: a float (NaN marks a gap). Reads rebuild lines between values.
- ``integer``, ``boolean`` and ``instant`` are stored as numbers too (an instant as UTC
  milliseconds), recorded on change and rebuilt as steps. Reads give an int, a bool or an
  ISO 8601 time.
- ``text`` and ``structured`` are labels: a string, or a JSON object or array. They are
  recorded on change and read as the value in effect.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

import pandas as pd

from .i18n import t

KINDS = ("number", "integer", "boolean", "text", "instant", "structured")
# One whole series per execution of an app (H2): ``archive.store`` ``run_series``, not chunks.
RUNS = "runs"
# Stored as labels (codec TEXT); every other kind is stored as float64.
LABELS = ("text", "structured")
# Hourly rollups (averages) mean something for these only.
ROLLED = ("number", "integer", "boolean")
TEXT_CHARS = 1000
STRUCTURED_BYTES = 64_000


def labelled(kind: str) -> bool:
    """Whether values of ``kind`` are stored as labels (text or JSON), not numbers."""

    return kind in LABELS


def on_change(kind: str) -> bool:
    """Whether ``kind`` is recorded on change and rebuilt as steps (all but ``number`` and
    ``runs``, whose runs are drawn as they were computed)."""

    return kind not in ("number", RUNS)


def change_kind(kind: str) -> str:
    """The kind ``plantcraft_sdk.contract.recorded_on_change`` knows for ``kind``."""

    return "number" if kind == "number" else "text"


def coerce(kind: str, raw: Any) -> Any:
    """A written value as stored for ``kind`` (NaN or None for a gap); ``ValueError`` if
    ``raw`` is not one."""

    if kind == "text":
        if raw is not None and not isinstance(raw, str):
            raise ValueError(t("A text series takes text or null."))
        # Longer texts are cut, as they always were (a label, not a document).
        return None if raw is None else raw[:TEXT_CHARS].replace("\x00", "")
    if kind == "structured":
        if raw is not None and not isinstance(raw, dict | list):
            raise ValueError(t("A structured series takes JSON objects, arrays or null."))
        if raw is not None and len(json.dumps(raw, ensure_ascii=False)) > STRUCTURED_BYTES:
            raise ValueError(
                t("Structured values have at most {count} bytes of JSON.", count=STRUCTURED_BYTES)
            )
        return raw
    if raw is None:
        return math.nan
    if kind == "boolean":
        if not isinstance(raw, bool):
            raise ValueError(t("A boolean series takes true, false or null."))
        return float(raw)
    if kind == "instant":
        if not isinstance(raw, str):
            raise ValueError(t("An instant series takes ISO 8601 times or null."))
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(t("{value} is not an ISO 8601 time.", value=raw[:40])) from exc
        if moment.tzinfo is None:
            raise ValueError(t("Times need an offset (Z or +hh:mm)."))
        return float(round(moment.timestamp() * 1000))
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(t("A number series takes numbers or null."))
    if not math.isfinite(float(raw)):
        return math.nan
    if kind == "integer":
        if float(raw) != int(raw):
            raise ValueError(t("An integer series takes whole numbers or null."))
        return float(int(raw))
    return float(raw)


def outward(kind: str, values: list[Any]) -> list[Any]:
    """Values read (floats or None, or labels) as the API answers them for ``kind``."""

    if kind in ("number", "text"):
        return values
    if kind == "structured":
        return [_structured(v) for v in values]
    if kind == "integer":
        return [None if v is None else round(v) for v in values]
    if kind == "boolean":
        return [None if v is None else v >= 0.5 for v in values]
    if kind == "instant":
        return [None if v is None else _iso(v) for v in values]
    return values


def outward_one(kind: str, value: Any) -> Any:
    return outward(kind, [value])[0]


def _structured(value: Any) -> Any:
    # SQLite keeps a structured snapshot as its JSON text.
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _iso(ms: float) -> str:
    return pd.Timestamp(int(ms), unit="ms", tz="UTC").isoformat()
