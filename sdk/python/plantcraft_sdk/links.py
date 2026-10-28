"""How apps link through PlantCraft: results, events, runs and schedules (API v1).

``docs/app-standard.md`` (section 6) says what they are for and ``docs/api-v1.md``
("Results, events, runs and schedules") is the contract. This module holds the
shapes and rules code needs in more than one place, so PlantCraft, the client
and ``FakePlantCraft`` validate the same way:

- the request bodies as pydantic models (``ResultIn``, ``EventIn``, ``RunIn``,
  ``ScheduleIn``); a body outside them is a 422 for the whole request;
- the per-item rules that depend on the caller (``result_kind``, ``event_kind``,
  ``check_url``, ``split_subject``), reported per item in ``errors``.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, TypedDict
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from plantcraft_sdk.contract import ContractError, parse_time
from plantcraft_sdk.i18n import t
from plantcraft_sdk.refs import RefError, parse_ref
from plantcraft_sdk.utc import utc_iso

# Items one PUT may carry (results, runs, schedules), and rows one read returns at most.
MAX_ITEMS = 500
# Events one POST may carry when it sends a list.
MAX_EVENTS = 1000
MAX_READ = 500
# Status changes of results and runs are kept this long.
RETENTION = timedelta(days=90)
MAX_SUMMARY = 300
# ``detail`` of a result and ``payload`` of an event, as compact JSON.
MAX_DETAIL_BYTES = 16 * 1024
MAX_REFS = 50
MAX_SUBJECTS = 500
MAX_SCHEDULE_SUBJECTS = 2000

STATUSES = ("ok", "warning", "alarm", "unknown")
RUN_STATUSES = ("queued", "running", "done", "failed", "cancelled")
TRIGGERS = ("manual", "schedule", "api")
SUBJECT_KINDS = ("asset", "signal")
# The event's own fields (docs/api-v1.md, "Events"): how bad the app thinks it is, whether it
# opens or closes a condition (``key`` names the condition), and what it is about.
EVENT_SEVERITIES = ("info", "ok", "warning", "critical")
EVENT_PHASES = ("instant", "start", "end")
EVENT_CATEGORIES = ("process", "equipment", "data", "run", "system", "user")
MAX_EVENT_KEY = 200

# The machine id of an app as API v1 carries it (``auth.app_keys`` accepts the same).
APP_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
# A result kind as its producer writes it (``loop_health``); readers may qualify it
# with the app id (``linkcraft.loop_health``).
KIND_NAME = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
# An event kind after the app id: ``finding.opened``.
EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39}){0,3}$")
# Run and schedule ids: they go into ``run:<app>/<run id>`` references.
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class LinkError(ValueError):
    """One item breaks a rule that depends on the caller; reported in ``errors``."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# Values ------------------------------------------------------------------------


def utc_text(value: Any, name: str) -> str | None:
    """An ISO 8601 time as ``2026-10-23T14:05:09.123Z`` (``plantcraft_sdk.utc``, sortable as
    text); None stays None."""

    if value is None or value == "":
        return None
    if not isinstance(value, str | datetime):
        raise ValueError(f"{name} is an ISO 8601 time.")
    if isinstance(value, str) and len(value) > 64:
        raise ValueError(f"{name} is an ISO 8601 time.")
    try:
        return utc_iso(parse_time(value, name))
    except (ContractError, OverflowError, ValueError) as exc:
        raise ValueError(f"Invalid {name}: use ISO 8601, like 2026-10-19T08:00:00Z.") from exc


def now_text() -> str:
    return utc_iso()


def cutoff_text(now: datetime | None = None) -> str:
    """The oldest time still kept (``RETENTION`` ago)."""

    return utc_iso((now or datetime.now(timezone.utc)) - RETENTION)


def json_size(value: Any, name: str = "detail") -> int:
    """Bytes of ``value`` as compact JSON; NaN and infinities are refused (ValueError)."""

    try:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{name} is JSON with finite numbers only (no NaN or infinity).") from exc
    return len(text.encode())


def own_app_subject(subject: str, app: str) -> bool:
    """``app:<app id>``, an event about the app itself (its collector, its runs as a whole)."""

    return subject == f"app:{app}"


def split_subject(subject: str) -> tuple[str, str]:
    """``("asset" | "signal", id)`` of a subject; raises ``LinkError`` (422) otherwise."""

    kind, sep, item = subject.partition(":")
    if not sep or kind not in SUBJECT_KINDS or not item or item != item.strip():
        raise LinkError(422, t("A subject is asset:<asset id> or signal:<signal id>."))
    return kind, item


def result_kind(kind: str, app: str) -> str:
    """A result kind without its app prefix (``linkcraft.loop_health`` -> ``loop_health``)."""

    if kind.startswith(f"{app}."):
        kind = kind[len(app) + 1 :]
    if not KIND_NAME.match(kind):
        raise LinkError(
            422, t("A result kind is lower-case letters, digits and _ (for example loop_health).")
        )
    return kind


def event_kind(kind: str, app: str) -> str:
    """The event kind, which must be ``<app id>.<noun>.<verb>`` for the caller's app."""

    prefix = f"{app}."
    if not kind.startswith(prefix):
        raise LinkError(
            422,
            t(
                "An event kind of {app} starts with {prefix} (like {prefix}x.done).",
                app=app,
                prefix=prefix,
            ),
        )
    if not EVENT_NAME.match(kind[len(prefix) :]):
        raise LinkError(422, t("An event kind is <app id>.<noun>.<verb> in lower case."))
    return kind


def check_url(url: str | None, prefix: str | None) -> str | None:
    """A link into the app: a path under its ``prefix`` or an absolute http(s) URL."""

    if not url:
        return None
    if _CONTROL.search(url) or "\\" in url or " " in url:
        raise LinkError(422, t("The url has characters a link cannot have."))
    if url.startswith("/"):
        segments = urlsplit(url).path.split("/")
        if url.startswith("//") or ".." in segments:
            raise LinkError(422, t("The url is a path under the app's prefix or an http(s) URL."))
        if not prefix or not prefix.startswith("/"):
            raise LinkError(422, t("This app has no prefix here: give an http(s) URL."))
        base = prefix if prefix.endswith("/") else f"{prefix}/"
        if not (url.startswith(base) or url == base.rstrip("/")):
            raise LinkError(
                422, t("The url must start with the app's prefix {prefix}.", prefix=base)
            )
        return url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise LinkError(422, t("The url is a path under the app's prefix or an http(s) URL."))
    return url


# Request bodies ----------------------------------------------------------------

Text = Annotated[str, StringConstraints(max_length=300)]
Subject = Annotated[str, StringConstraints(min_length=1, max_length=400)]
AppField = Annotated[str, StringConstraints(min_length=1, max_length=40)] | None
UrlField = Annotated[str, StringConstraints(max_length=2000)] | None


def _finite(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} is a number or null.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number (no NaN or infinity).")
    return number


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ResultIn(_Body):
    """One item of ``PUT /api/v1/results``."""

    subject: Subject
    kind: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    status: Literal["ok", "warning", "alarm", "unknown"]
    score: Any = None
    usable: StrictBool | None = None
    value: Any = None
    summary: Annotated[str, StringConstraints(max_length=MAX_SUMMARY)] = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    at: Any = None
    expires_at: Any = None
    # With a user token: the app this result belongs to (a service token names its own).
    app: AppField = None

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: Any) -> float | None:
        number = _finite(value, "score")
        if number is not None and not 0 <= number <= 100:
            raise ValueError("score is between 0 and 100 (100 = best), or null.")
        return number

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: Any) -> float | None:
        return _finite(value, "value")

    @field_validator("detail", mode="before")
    @classmethod
    def _detail(cls, value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, dict) and json_size(value, "detail") > MAX_DETAIL_BYTES:
            raise ValueError(f"detail is at most {MAX_DETAIL_BYTES} bytes of JSON.")
        return value

    @field_validator("at", mode="before")
    @classmethod
    def _at(cls, value: Any) -> str | None:
        return utc_text(value, "at")

    @field_validator("expires_at", mode="before")
    @classmethod
    def _expires(cls, value: Any) -> str | None:
        return utc_text(value, "expires_at")


class EventIn(_Body):
    """One event of ``POST /api/v1/events`` (the body, or one item of a list)."""

    kind: Annotated[str, StringConstraints(min_length=3, max_length=120)]
    subject: Subject
    summary: Annotated[str, StringConstraints(max_length=MAX_SUMMARY)] = ""
    refs: list[Annotated[str, StringConstraints(min_length=1, max_length=400)]] = Field(
        default_factory=list, max_length=MAX_REFS
    )
    payload: dict[str, Any] = Field(default_factory=dict)
    app: AppField = None
    # None: the default of the app's catalog (plantcraft_sdk.events.event_fields).
    severity: Literal["info", "ok", "warning", "critical"] | None = None
    key: Annotated[str, StringConstraints(min_length=1, max_length=MAX_EVENT_KEY)] | None = None
    phase: Literal["instant", "start", "end"] | None = None
    category: Literal["process", "equipment", "data", "run", "system", "user"] | None = None

    @field_validator("refs")
    @classmethod
    def _refs(cls, value: list[str]) -> list[str]:
        for ref in value:
            try:
                parse_ref(ref)
            except RefError as exc:
                raise ValueError(str(exc)) from None
        return value

    @field_validator("payload", mode="before")
    @classmethod
    def _payload(cls, value: Any) -> Any:
        if value is None:
            return {}
        if isinstance(value, dict) and json_size(value, "payload") > MAX_DETAIL_BYTES:
            raise ValueError(f"payload is at most {MAX_DETAIL_BYTES} bytes of JSON.")
        return value

    @field_validator("key")
    @classmethod
    def _key(cls, value: str | None) -> str | None:
        if value is not None and _CONTROL.search(value):
            raise ValueError("key has no control characters.")
        return value

    @model_validator(mode="after")
    def _condition(self) -> EventIn:
        if self.phase in ("start", "end") and not self.key:
            raise ValueError("an event that starts or ends a condition names it in key.")
        return self


class RunIn(_Body):
    """One item of ``PUT /api/v1/runs``."""

    id: Annotated[str, StringConstraints(pattern=ITEM_ID.pattern)]
    name: Annotated[str, StringConstraints(max_length=200)] = ""
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    trigger: Literal["manual", "schedule", "api"]
    started_at: Any = None
    finished_at: Any = None
    subjects: list[Subject] = Field(default_factory=list, max_length=MAX_SUBJECTS)
    summary: Annotated[str, StringConstraints(max_length=MAX_SUMMARY)] = ""
    url: UrlField = None
    app: AppField = None
    # For the suite's Queue (docs/quick-access.md, plantcraft-sdk 0.53.0): who started it (a
    # username; the platform tells them when it fails or ends after a minute), how far it went
    # (0 to 1), what it does now ("Writing 120 of 900 tags") and the path of the app that cancels
    # it (POSTed as the person, under the app's prefix; only while it can still be cancelled).
    by: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None
    progress: Annotated[float, Field(ge=0, le=1)] | None = None
    step: Annotated[str, StringConstraints(max_length=200)] = ""
    cancel: UrlField = None

    @field_validator("started_at", mode="before")
    @classmethod
    def _started(cls, value: Any) -> str | None:
        return utc_text(value, "started_at")

    @field_validator("finished_at", mode="before")
    @classmethod
    def _finished(cls, value: Any) -> str | None:
        return utc_text(value, "finished_at")


MAX_KNOWLEDGE_TEXT = 20000
KNOWLEDGE_REF = re.compile(r"^[a-z][a-z_]{1,31}:\S.{0,298}$")


class KnowledgeIn(_Body):
    """One item of ``PUT /api/v1/knowledge``: an app's text about one of its objects."""

    ref: Annotated[str, StringConstraints(pattern=KNOWLEDGE_REF.pattern)]
    kind: Annotated[str, StringConstraints(min_length=1, max_length=40)] = "note"
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_KNOWLEDGE_TEXT)]
    subjects: list[Subject] = Field(default_factory=list, max_length=MAX_SUBJECTS)
    url: UrlField = None
    # A run's report: dropped 90 days after its last write.
    transient: StrictBool = False
    app: AppField = None


class ScheduleIn(_Body):
    """One item of ``PUT /api/v1/schedules`` (the app's whole list)."""

    id: Annotated[str, StringConstraints(pattern=ITEM_ID.pattern)]
    name: Annotated[str, StringConstraints(max_length=200)] = ""
    cadence: Annotated[str, StringConstraints(max_length=200)] = ""
    next_run: Any = None
    enabled: StrictBool = True
    url: UrlField = None
    # What each execution runs on (``asset:<id>``), so a rule can cover an execution's assets.
    subjects: list[Subject] = Field(default_factory=list, max_length=MAX_SCHEDULE_SUBJECTS)

    @field_validator("next_run", mode="before")
    @classmethod
    def _next(cls, value: Any) -> str | None:
        return utc_text(value, "next_run")


def parse_body(
    model: type[BaseModel], body: Any, *, many: bool, limit: int = MAX_ITEMS
) -> list[Any]:
    """The validated items of a request body (``many``: a list of at most ``limit``).

    Raises ``ContractError`` (422) naming the first problem; the input is never
    echoed back, so a NaN sent by the caller cannot break the answer.
    """

    if many:
        if not isinstance(body, list):
            raise ContractError(t("Send a JSON list of at most {count} items.", count=limit))
        if len(body) > limit:
            raise ContractError(t("At most {count} items per request.", count=limit))
        items = body
    else:
        if not isinstance(body, dict):
            raise ContractError(t("Send a JSON object."))
        items = [body]
    found = []
    for index, item in enumerate(items):
        try:
            found.append(model.model_validate(item))
        except ValidationError as exc:
            first = exc.errors(include_input=False, include_url=False)[0]
            where = ".".join(str(part) for part in first.get("loc", ())) or "item"
            message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
            prefix = f"[{index}] " if many else ""
            raise ContractError(f"{prefix}{where}: {message}") from None
    return found


def parse_events(body: Any) -> tuple[list[EventIn], bool]:
    """The events of a ``POST /api/v1/events`` body and whether it was a list.

    One JSON object is one event (answered with the event); a list holds 1 to
    ``MAX_EVENTS`` (answered with an ``EventsReceipt``). Raises ``ContractError``.
    """

    if isinstance(body, list):
        if not body:
            raise ContractError(t("Send a JSON list of at most {count} items.", count=MAX_EVENTS))
        return parse_body(EventIn, body, many=True, limit=MAX_EVENTS), True
    if not isinstance(body, dict):
        raise ContractError(
            t("Send a JSON object, or a list of at most {count} of them.", count=MAX_EVENTS)
        )
    return parse_body(EventIn, body, many=False), False


# Answers -----------------------------------------------------------------------


class ItemError(TypedDict):
    index: int
    id: str
    status: int
    detail: str


class PutReceipt(TypedDict):
    saved: int
    errors: list[ItemError]


class EventsReceipt(TypedDict):
    """The answer to a list of events: ``ids[i]`` is item ``i``'s new event id, None if in ``errors``."""

    saved: int
    ids: list[int | None]
    errors: list[ItemError]
    # Items PlantCraft did not write again: a start already open with the same severity, or
    # an end of a condition not open (``ids[i]`` is the event already saying it, or None).
    repeated: int


class Result(TypedDict):
    app: str
    subject: str
    kind: str
    status: str
    score: float | None
    usable: bool | None
    value: float | None
    summary: str
    detail: dict[str, Any]
    at: str
    expires_at: str | None
    updated_at: str
    stale: bool


class ResultChange(TypedDict):
    app: str
    subject: str
    kind: str
    status: str
    score: float | None
    usable: bool | None
    value: float | None
    summary: str
    at: str


class Event(TypedDict):
    id: int
    at: str
    app: str
    kind: str
    subject: str
    actor: str
    summary: str
    refs: list[str]
    payload: dict[str, Any]
    severity: str
    key: str
    phase: str
    category: str


class Run(TypedDict):
    app: str
    id: str
    name: str
    status: str
    trigger: str
    started_at: str | None
    finished_at: str | None
    subjects: list[str]
    summary: str
    url: str | None
    by: str | None
    progress: float | None
    step: str
    cancel: str | None
    updated_at: str


class Schedule(TypedDict):
    app: str
    id: str
    name: str
    cadence: str
    next_run: str | None
    enabled: bool
    url: str | None
    subjects: list[str]
    updated_at: str


def item_error(index: int, item_id: str, status: int, detail: str) -> ItemError:
    return {"index": index, "id": item_id, "status": int(status), "detail": str(detail)}


def stale_view(row: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    """A stored result as API v1 answers it: past ``expires_at`` it is ``unknown`` and stale."""

    expired = bool(row.get("expires_at")) and row["expires_at"] <= (now or now_text())
    answer = dict(row)
    answer["stale"] = expired
    if expired:
        answer["status"] = "unknown"
    return answer


def subjects_param(values: list[str] | str | None) -> list[str]:
    """``subject`` parameters as given, one subject each, in order, without repeats.

    A subject is never split: ids may hold commas and spaces (``refs.check_id``),
    so many subjects are sent as repeated parameters (``?subject=a&subject=b``).
    """

    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    found: list[str] = []
    for value in values:
        value = str(value).strip()
        if value and value not in found:
            found.append(value)
    return found


__all__ = [
    "APP_ID",
    "EVENT_CATEGORIES",
    "EVENT_PHASES",
    "EVENT_SEVERITIES",
    "Event",
    "EventIn",
    "EventsReceipt",
    "ItemError",
    "LinkError",
    "MAX_DETAIL_BYTES",
    "MAX_EVENTS",
    "MAX_ITEMS",
    "MAX_READ",
    "PutReceipt",
    "RETENTION",
    "RUN_STATUSES",
    "Result",
    "ResultChange",
    "ResultIn",
    "Run",
    "KnowledgeIn",
    "RunIn",
    "STATUSES",
    "Schedule",
    "ScheduleIn",
    "TRIGGERS",
    "check_url",
    "cutoff_text",
    "event_kind",
    "item_error",
    "now_text",
    "own_app_subject",
    "parse_body",
    "parse_events",
    "result_kind",
    "split_subject",
    "stale_view",
    "subjects_param",
    "utc_text",
]
