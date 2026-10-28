"""Derived series: computed signals apps publish with ``PUT /api/v1/series``.

An app writes series it computed (a loop health score, a filtered flow, a mass balance) to its
own source, ``app-<app id>``; they become signals like any other (``app-linkcraft:health.fic-101``),
read back through the v1 series, batch and value routes and listed by ``GET /api/v1/signals``
with ``app``, ``subject`` and ``result``. Only a service token writes, and only to its own
app's source. ``docs/api-v1.md`` ("Derived series") is the contract; PlantCraft, the client
and ``FakePlantCraft`` share these rules.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from plantcraft_sdk.contract import ContractError, iso, text_label
from plantcraft_sdk.refs import KINDS, RefError, parse_ref

# Items per request, and values across all of them.
MAX_DERIVED_ITEMS = 500
MAX_DERIVED_VALUES = 100_000
SOURCE_PREFIX = "app-"
# The unit of a score from 0 to 100 (100 = best), as results score.
SCORE_UNIT = "/100"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
RESULT_KIND = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
MAX_NAME = 200
# A derived series' description (HistCraft keeps 500 characters).
MAX_DESCRIPTION = 500
# Fields a derived signal adds to the signal shape of ``GET /api/v1/signals``.
DERIVED_FIELDS = ("app", "subject", "result")
# What a derived point holds (contract with the Historian, round 8): one value per instant of
# these kinds, or ``runs``, a whole series per execution (``PUT /api/v1/series/runs``).
VALUE_KINDS = ("number", "integer", "boolean", "text", "instant", "structured")
RUNS_KIND = "runs"
POINT_KINDS = (*VALUE_KINDS, RUNS_KIND)
# A text value's characters (the Historian cuts longer ones) and a structured value's JSON bytes.
MAX_TEXT = 1000
MAX_STRUCTURED_BYTES = 64 * 1024
# Retention a writing app sets (0 keeps the values forever; None leaves it as it is).
MAX_RETENTION_DAYS = 36_500
MAX_MANAGED_BY = 100
# Runs: executions kept per point, values per run, runs per request.
DEFAULT_KEEP_RUNS = 10
MAX_KEEP_RUNS = 1000
MAX_RUN_VALUES = 20_000
MAX_RUN_ITEMS = 500


class DerivedError(ValueError):
    """A rule that depends on the caller is broken (403: another app's source)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def source_of(app: str) -> str:
    """The source id an app's derived signals live in: ``app-<app id>``."""

    return f"{SOURCE_PREFIX}{app}"


def split_derived(signal: str) -> tuple[str, str] | None:
    """``(app id, name)`` of a derived signal id (``app-<app id>:<name>``), else None."""

    source, sep, name = signal.partition(":")
    if not sep or not name or not source.startswith(SOURCE_PREFIX):
        return None
    app = source[len(SOURCE_PREFIX) :]
    return (app, name) if app else None


def check_owner(app: str, signal: str) -> tuple[str, str]:
    """``(source id, name)`` when ``signal`` is in ``app``'s own source; else ``DerivedError(403)``."""

    found = split_derived(signal)
    if found is None or found[0] != app:
        raise DerivedError(
            403,
            f"An app writes only its own derived signals: {source_of(app)}:<name>.",
        )
    return source_of(app), found[1]


def _utc(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("times are ISO 8601 text")
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("times are ISO 8601, like 2026-10-19T08:00:00Z") from exc
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return iso(stamp)


def typed_value(kind: str, item: Any) -> Any:
    """One value checked for a point of ``kind`` (``VALUE_KINDS``); ``ValueError`` otherwise.

    number: finite float; integer: whole number (2.0 is 2); boolean: true or false; text: up to
    1,000 characters; instant: ISO 8601, given back in UTC; structured: object or list, 64 kB
    of JSON at most. ``None`` is a gap in every kind.
    """

    if item is None:
        return None
    if kind == "text":
        if isinstance(item, (dict, list)):
            raise ValueError("text values are strings, numbers or null")
        label = text_label(item)
        return label[:MAX_TEXT] if label is not None else None
    if kind == "boolean":
        if not isinstance(item, bool):
            raise ValueError("boolean values are true, false or null")
        return item
    if kind == "instant":
        return _utc(item)
    if kind == "structured":
        if not isinstance(item, (dict, list)):
            raise ValueError("structured values are JSON objects, lists or null")
        try:
            size = len(json.dumps(item, allow_nan=False, separators=(",", ":")).encode())
        except (TypeError, ValueError) as exc:
            raise ValueError("structured values are plain JSON (no NaN)") from exc
        if size > MAX_STRUCTURED_BYTES:
            raise ValueError("a structured value is 64 kB of JSON at most")
        return item
    if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
        raise ValueError(f"{kind} values are finite numbers or null")
    if kind == "integer":
        if isinstance(item, float) and not item.is_integer():
            raise ValueError("integer values are whole numbers or null")
        return int(item)
    return float(item)


class _PointIn(BaseModel):
    """What every write to a derived point names: the point and what it means."""

    model_config = ConfigDict(extra="ignore")

    signal: str = Field(min_length=3, max_length=300)
    name: str | None = Field(default=None, max_length=MAX_NAME)
    unit: str | None = Field(default=None, max_length=40)
    # What the series means, for people and the suite's assistants (shown with the signal).
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    subject: str | None = Field(default=None, max_length=300)
    result: str | None = Field(default=None, max_length=60)
    # Who sets the point's retention ("link:<schedule id>"): people cannot change it then;
    # "" clears the lock, None leaves it as it is.
    managed_by: str | None = Field(default=None, max_length=MAX_MANAGED_BY)

    @field_validator("signal")
    @classmethod
    def _signal(cls, value: str) -> str:
        found = split_derived(value)
        if found is None:
            raise ValueError("a derived signal id is app-<app id>:<name>")
        name = found[1]
        if _CONTROL.search(value) or name != name.strip() or len(name) > MAX_NAME:
            raise ValueError("the name has no control characters or outer spaces (200 at most)")
        return value

    @field_validator("name", "unit", "managed_by")
    @classmethod
    def _text(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL.search(value):
            raise ValueError("no control characters")
        return value

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _CONTROL.search(value.replace("\n", " ")):
            raise ValueError("no control characters but line breaks")
        return value.strip()

    @field_validator("subject")
    @classmethod
    def _subject(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        try:
            ref = parse_ref(value)
        except RefError as exc:
            raise ValueError(f"a reference of the suite ({', '.join(KINDS)})") from exc
        if ref.kind not in ("asset", "signal"):
            raise ValueError("subject is asset:<id> or signal:<id>")
        return value

    @field_validator("result")
    @classmethod
    def _result(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not RESULT_KIND.match(value):
            raise ValueError("a result kind: lower case, digits and _ (loop_health)")
        return value


class DerivedIn(_PointIn):
    """One item of ``PUT /api/v1/series``; ``t`` comes out as UTC ISO text, ``kind`` resolved."""

    t: list[Any] = Field(max_length=MAX_DERIVED_VALUES)
    v: list[Any] = Field(max_length=MAX_DERIVED_VALUES)
    kind: Literal["number", "integer", "boolean", "text", "instant", "structured"] | None = None
    # Days the Historian keeps the values (0: forever); None leaves the point's as it is.
    retention_days: int | None = Field(default=None, ge=0, le=MAX_RETENTION_DAYS)

    @field_validator("t")
    @classmethod
    def _times(cls, value: list[Any]) -> list[str]:
        return [_utc(item) for item in value]

    @model_validator(mode="after")
    def _values(self) -> DerivedIn:
        if len(self.t) != len(self.v):
            raise ValueError("t and v have the same length")
        texts = any(isinstance(item, str) for item in self.v)
        kind = self.kind or ("text" if texts else "number")
        self.kind = kind
        self.v = [typed_value(kind, item) for item in self.v]
        return self

    def payload(self, app: str | None = None) -> dict[str, Any]:
        """The item as forwarded (with ``app`` when given) or stored."""

        body = self.model_dump()
        if app is not None:
            body["app"] = app
        return body


def parse_derived(body: Any) -> list[DerivedIn]:
    """The validated items of a ``PUT /api/v1/series`` body; ``ContractError`` (422) otherwise.

    A list of 1 to 500 items with 100,000 values at most across them. The input is never
    echoed back.
    """

    if not isinstance(body, list) or not body:
        raise ContractError(
            f"Send a JSON list of 1 to {MAX_DERIVED_ITEMS} series: "
            '[{"signal", "t": [...], "v": [...]}].'
        )
    if len(body) > MAX_DERIVED_ITEMS:
        raise ContractError(f"At most {MAX_DERIVED_ITEMS} series per request.")
    total = sum(len(item.get("v") or []) for item in body if isinstance(item, dict))
    if total > MAX_DERIVED_VALUES:
        raise ContractError(f"At most {MAX_DERIVED_VALUES} values per request.")
    found = []
    for index, item in enumerate(body):
        try:
            found.append(DerivedIn.model_validate(item))
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_url=False)[0]
            where = ".".join(str(part) for part in first.get("loc", ())) or "item"
            message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
            raise ContractError(f"[{index}] {where}: {message}") from None
    return found


class RunIn(_PointIn):
    """One execution's series for a ``runs`` point (``PUT /api/v1/series/runs``).

    The point keeps the last ``keep_runs`` executions (and none older than ``keep_days`` when
    given); a run sent again at the same ``run_at`` replaces it.
    """

    run_at: Any
    t: list[Any] = Field(max_length=MAX_RUN_VALUES)
    v: list[Any] = Field(max_length=MAX_RUN_VALUES)
    keep_runs: int = Field(default=DEFAULT_KEEP_RUNS, ge=1, le=MAX_KEEP_RUNS)
    keep_days: int | None = Field(default=None, ge=1, le=MAX_RETENTION_DAYS)

    @field_validator("run_at")
    @classmethod
    def _run_at(cls, value: Any) -> str:
        return _utc(value)

    @field_validator("t")
    @classmethod
    def _times(cls, value: list[Any]) -> list[str]:
        return [_utc(item) for item in value]

    @model_validator(mode="after")
    def _values(self) -> RunIn:
        if len(self.t) != len(self.v):
            raise ValueError("t and v have the same length")
        self.v = [typed_value("number", item) for item in self.v]
        return self

    def payload(self) -> dict[str, Any]:
        return self.model_dump()


def parse_runs(body: Any) -> list[RunIn]:
    """The validated items of a ``PUT /api/v1/series/runs`` body; ``ContractError`` (422) otherwise.

    A list of 1 to 500 runs, each of 20,000 values at most. The input is never echoed back.
    """

    if not isinstance(body, list) or not body:
        raise ContractError(
            f"Send a JSON list of 1 to {MAX_RUN_ITEMS} runs: "
            '[{"signal", "run_at", "t": [...], "v": [...]}].'
        )
    if len(body) > MAX_RUN_ITEMS:
        raise ContractError(f"At most {MAX_RUN_ITEMS} runs per request.")
    found = []
    for index, item in enumerate(body):
        try:
            found.append(RunIn.model_validate(item))
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_url=False)[0]
            where = ".".join(str(part) for part in first.get("loc", ())) or "item"
            message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
            raise ContractError(f"[{index}] {where}: {message}") from None
    return found


def derived_signal(
    signal: str,
    *,
    app: str,
    name: str | None = None,
    unit: str | None = None,
    kind: str = "number",
    subject: str | None = None,
    result: str | None = None,
    description: str | None = None,
    managed_by: str = "",
    retention_days: int | None = None,
) -> dict[str, Any]:
    """The signal shape of a derived signal (``GET /api/v1/signals``): the plant shape plus
    ``app``, ``subject``, ``result``, ``managed_by`` (who sets its retention, "" for people)
    and ``retention_days`` (0 keeps it forever, None the general default)."""

    found = split_derived(signal)
    tag = found[1] if found else signal
    return {
        "id": signal,
        "name": name or tag,
        "source": source_of(app),
        "unit": unit or "",
        "description": description or "",
        "low": None,
        "high": None,
        "kind": kind,
        "source_kind": "derived",
        "app": app,
        "subject": subject,
        "result": result,
        "managed_by": managed_by or "",
        "retention_days": retention_days,
    }


def matches(signal: dict[str, Any], filters: dict[str, str | None]) -> bool:
    """True when the signal has every given ``app``, ``subject`` and ``result``."""

    return all(value in (None, "") or signal.get(key) == value for key, value in filters.items())


class DerivedItemError(TypedDict):
    index: int
    signal: str
    status: int
    detail: str


class DerivedReceipt(TypedDict):
    written: int
    errors: list[DerivedItemError]


__all__ = [
    "DEFAULT_KEEP_RUNS",
    "DERIVED_FIELDS",
    "MAX_KEEP_RUNS",
    "MAX_RUN_ITEMS",
    "MAX_RUN_VALUES",
    "POINT_KINDS",
    "RUNS_KIND",
    "RunIn",
    "VALUE_KINDS",
    "parse_runs",
    "typed_value",
    "MAX_DERIVED_ITEMS",
    "MAX_DERIVED_VALUES",
    "SCORE_UNIT",
    "SOURCE_PREFIX",
    "DerivedError",
    "DerivedIn",
    "DerivedItemError",
    "DerivedReceipt",
    "check_owner",
    "derived_signal",
    "matches",
    "parse_derived",
    "source_of",
    "split_derived",
]
