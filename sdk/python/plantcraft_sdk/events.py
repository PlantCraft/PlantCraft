"""The events an app writes, declared once in its ``app.toml`` (``docs/app-standard.md``, section 6).

An event is something that happened, reported by the app that saw it; Alarms is the one app
that judges events and decides what reaches a person. Every app declares the events it writes
in ``[[publishes.events]]``, even when it writes none yet, so the suite has one catalog::

    [[publishes.events]]
    name = "collector.stopped"            # sent as <app id>.collector.stopped
    title = "Collector stopped"
    description = "The collector read nothing from any source for two scan cycles."
    severity = "critical"                 # info | ok | warning | critical (the default)
    category = "system"                   # process | equipment | data | run | system | user
    phase = "interval"                    # instant, or interval: sent as start ... end with a key
    payload = { source = "Source id", since = "Last value read (UTC)" }
    rule = { when = "open", minutes = 5, priority = "critical", notify = "admins", enabled = true }

The app's code writes them through ``EventCatalog``, which knows the names, so a typo fails in
the app's own tests (``FakePlantCraft`` refuses an event the catalog does not declare)::

    catalog = EventCatalog.from_manifest(manifest, app="histcraft")
    client.post_events([catalog.event("collector.stopped", "app:histcraft", phase="start",
                                      key="collector", summary="No values for 2 minutes")])

PlantCraft keeps each app's catalog (``PUT /api/v1/events/catalog``, sent by the SDK when the
app starts) and answers all of them at ``GET /api/v1/events/catalog``; Alarms' rule editor reads
that. ``event_fields`` is the one rule that fills an event's severity, phase and category.

An app without an app key (the Historian answers the suite, it never calls it) cannot post. It
names the conditions it has open now instead (``plantcraft_sdk.server.ops.report_conditions``,
one ``Condition`` each): its ``GET /api/ops/metrics`` carries them with its catalog, and
PlantCraft's monitor, which reads the metrics every minute, writes each one in the app's name, a
``start`` when it appears and an ``end`` when it is gone.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from plantcraft_sdk.i18n import t
from plantcraft_sdk.links import EVENT_SEVERITIES, EventIn, LinkError

# ``<noun>.<verb>`` (up to four parts) after the app id.
EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39}){1,3}$")
PAYLOAD_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_CATALOG = 100
MAX_PAYLOAD_FIELDS = 30
# Conditions one app reports at once (``report_conditions``); past it the first ones are kept.
# Each is said once when it starts and once when it ends, so a large plant may name many.
MAX_CONDITIONS = 2000

Severity = Literal["info", "ok", "warning", "critical"]
Category = Literal["process", "equipment", "data", "run", "system", "user"]
Priority = Literal["critical", "high", "medium", "low"]


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EventRule(_Spec):
    """The rule Alarms suggests for an event.

    ``when``: ``event`` (each event), ``open`` (a condition still open after ``minutes``), or
    ``repeated`` (``count`` events about one subject within ``minutes``). ``enabled`` rules are
    switched on in a new installation; only ``system`` events may ask for it, so a new plant
    never starts with process alarms nobody chose.
    """

    when: Literal["event", "open", "repeated"] = "event"
    minutes: int = Field(0, ge=0, le=10080)
    count: int = Field(1, ge=1, le=1000)
    priority: Priority = "medium"
    creates: Literal["alarm", "notice"] = "alarm"
    notify: Literal["owner", "admins"] = "owner"
    enabled: bool = False


class EventSpec(_Spec):
    """One event of an app's catalog, as ``[[publishes.events]]`` declares it."""

    name: Annotated[str, StringConstraints(pattern=EVENT_NAME.pattern)]
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(max_length=600)] = ""
    severity: Severity = "info"
    category: Category = "system"
    phase: Literal["instant", "interval"] = "instant"
    payload: dict[str, Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=dict
    )
    rule: EventRule | None = None

    @field_validator("payload")
    @classmethod
    def _fields(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_PAYLOAD_FIELDS:
            raise ValueError(f"payload describes at most {MAX_PAYLOAD_FIELDS} fields")
        for name in value:
            if not PAYLOAD_FIELD.match(name):
                raise ValueError(f"payload field {name!r} is lower case, like schedule_id")
        return value

    @model_validator(mode="after")
    def _rule(self) -> EventSpec:
        if self.rule is None:
            return self
        if self.rule.enabled and self.category != "system":
            raise ValueError("only a system event's rule is enabled in a new installation")
        if self.rule.when == "open" and self.phase != "interval":
            raise ValueError('a rule "when = open" needs an event with phase = "interval"')
        if self.rule.when in ("open", "repeated") and self.rule.minutes < 1:
            raise ValueError(f'a rule "when = {self.rule.when}" gives minutes (1 or more)')
        return self


class CatalogIn(BaseModel):
    """The body of ``PUT /api/v1/events/catalog``: the app's whole catalog, replaced."""

    model_config = ConfigDict(extra="ignore")

    events: list[EventSpec] = Field(default_factory=list, max_length=MAX_CATALOG)
    app: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None = None

    @model_validator(mode="after")
    def _once(self) -> CatalogIn:
        names = [spec.name for spec in self.events]
        twice = sorted({name for name in names if names.count(name) > 1})
        if twice:
            raise ValueError(f"declared more than once: {', '.join(twice)}")
        return self


class Condition(_Spec):
    """A condition an app has open now (``report_conditions``): the declared ``interval`` event
    ``name`` (without the app id), named by ``key`` (one key, one condition)."""

    name: Annotated[str, StringConstraints(pattern=EVENT_NAME.pattern)]
    key: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    summary: Annotated[str, StringConstraints(max_length=500)] = ""
    # A reference (``source:opc-1``); empty: the app itself (``app:<id>``).
    subject: Annotated[str, StringConstraints(max_length=200)] = ""
    severity: Severity | None = None
    refs: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list, max_length=20
    )
    payload: dict[str, Any] = Field(default_factory=dict)


def parse_specs(items: Iterable[Any]) -> list[EventSpec]:
    """The specs of ``[publishes] events``: tables, or bare names (``finding.opened``) that
    declare an event with its name as the title. Raises ``ValueError``."""

    specs = []
    for item in items:
        if isinstance(item, str):
            item = {"name": item, "title": item}
        try:
            specs.append(item if isinstance(item, EventSpec) else EventSpec.model_validate(item))
        except ValidationError as exc:
            first = exc.errors(include_url=False)[0]
            where = ".".join(str(part) for part in first.get("loc", ()))
            message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
            name = item.get("name") if isinstance(item, Mapping) else item
            raise ValueError(f"event {name!r}: {where + ': ' if where else ''}{message}") from None
    return specs


def event_fields(item: EventIn, spec: EventSpec | None) -> dict[str, str]:
    """The event's ``severity``, ``key``, ``phase`` and ``category``, filled from its spec.

    Severity: the event's own, else ``payload.severity`` (how apps wrote it before SDK 0.26),
    else the spec's, else ``info``. A declared ``interval`` event says ``start`` or ``end``; a
    declared ``instant`` one says neither. Raises ``LinkError`` (422) otherwise.
    """

    severity = item.severity
    if severity is None:
        given = str((item.payload or {}).get("severity") or "").strip().lower()
        severity = given if given in EVENT_SEVERITIES else (spec.severity if spec else "info")
    phase = item.phase or "instant"
    if spec is not None:
        if spec.phase == "interval" and phase == "instant":
            raise LinkError(
                422,
                t(
                    "{kind} opens and closes a condition: send phase start or end, with a key.",
                    kind=item.kind,
                ),
            )
        if spec.phase == "instant" and phase != "instant":
            raise LinkError(
                422,
                t(
                    "{kind} is declared as an instant event: it has no start or end.",
                    kind=item.kind,
                ),
            )
    return {
        "severity": severity,
        "key": item.key or "",
        "phase": phase,
        "category": item.category or (spec.category if spec else ""),
    }


class EventCatalog:
    """An app's declared events, to write them by name (``event``) and to send the catalog."""

    def __init__(self, app: str, specs: Iterable[EventSpec]):
        self.app = app
        self.specs = {spec.name: spec for spec in specs}

    @classmethod
    def from_manifest(cls, manifest: Any, app: str | None = None) -> EventCatalog:
        """From a parsed ``AppManifest``, or ``app.toml`` read as a dict."""

        if isinstance(manifest, Mapping):
            app = app or str(manifest.get("app", {}).get("id") or "")
            items = (manifest.get("publishes") or {}).get("events") or []
        else:
            app = app or manifest.app.id
            items = manifest.publishes.events
        return cls(app, parse_specs(items))

    def spec(self, kind: str) -> EventSpec | None:
        """The spec of ``kind`` (``<app id>.<name>`` or the bare name), None if undeclared."""

        name = kind[len(self.app) + 1 :] if kind.startswith(f"{self.app}.") else kind
        return self.specs.get(name)

    def event(
        self,
        name: str,
        subject: str,
        *,
        summary: str = "",
        refs: Iterable[str] = (),
        payload: Mapping[str, Any] | None = None,
        severity: str | None = None,
        key: str | None = None,
        phase: str | None = None,
    ) -> dict[str, Any]:
        """One item for ``client.post_events``; ``KeyError`` for a name the catalog lacks."""

        if name not in self.specs:
            raise KeyError(f"{self.app} does not declare the event {name!r} in app.toml")
        item: dict[str, Any] = {
            "kind": f"{self.app}.{name}",
            "subject": subject,
            "summary": summary,
            "refs": list(refs),
            "payload": dict(payload or {}),
        }
        for field, value in (("severity", severity), ("key", key), ("phase", phase)):
            if value is not None:
                item[field] = value
        return item

    def to_json(self) -> list[dict[str, Any]]:
        """The body's ``events`` of ``PUT /api/v1/events/catalog``."""

        return [spec.model_dump(mode="json", exclude_none=True) for spec in self.specs.values()]


__all__ = [
    "CatalogIn",
    "Condition",
    "EventCatalog",
    "EventRule",
    "EventSpec",
    "MAX_CATALOG",
    "MAX_CONDITIONS",
    "event_fields",
    "parse_specs",
]
