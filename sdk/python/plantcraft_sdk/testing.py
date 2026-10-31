"""``FakePlantCraft``: API v1 in-process, so an app tests without the real PlantCraft.

::

    from plantcraft_sdk.testing import FakePlantCraft

    fake = FakePlantCraft()
    client = fake.client("engineer")            # PlantCraftClient acting as that user
    verifier = fake.verifier("linkcraft")        # TokenVerifier reading the fake's keys
    token = fake.token("operator")              # a signed user token (aud "processcraft")
    expired = fake.token("operator", ttl=-60)   # ...or one that is no longer valid

The fake signs real Ed25519 tokens, serves the same routes and shapes as
``docs/api-v1.md`` and fills series with a deterministic synthetic signal per
id, or with the ``pandas.Series`` given in ``series={id: values}`` (labels make
a text signal). Signal ids are ``<source id>:<tag>`` as in PlantCraft (the
default signals are ``fake:FIC-101.PV``...); like PlantCraft until API v1 is
frozen, a bare tag that exactly one signal has names that signal, and
``series`` and ``broken`` may be keyed by id or by bare tag. Given series are a recorded file: ``end`` and value windows
default to their last sample, as PlantCraft does for a recorded file. Writes
land in ``fake.audit_log``; ids in ``fake.broken`` fail as a dead source (502).
Assets carry ``type_path`` and ``relations`` like PlantCraft's; their types come from
``asset_types=`` (definitions as an admin writes them, default the starter types of
``plantcraft_sdk.assets``), served resolved by ``GET /api/v1/asset-types``.
The browser renewal (``POST /api/v1/auth/token``) takes the user name from the
``processcraft_session`` cookie. Derived series an app writes with ``PUT /api/v1/series``
become signals of ``app-<app id>`` (with ``app``, ``subject`` and ``result``, and the
``?app&subject&result`` filters), read back like the others; ``fake.derived`` holds them.

Two ways in, one implementation (``fake.handle``):

- ``fake.http_client()`` (default): an ``httpx.Client`` on an
  ``httpx.MockTransport``. In-process, no event loop, no sockets: fast.
- ``fake.app``: a real ASGI app (Starlette, from the ``server`` extra) to serve
  with uvicorn or ``fake.http_client(transport="asgi")`` (Starlette's TestClient).
"""

import copy
import hmac
import json
import math
import re
import time
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import cached_property
from typing import Any
from urllib.parse import parse_qsl, unquote

import httpx
import numpy as np
import pandas as pd
from pydantic import ValidationError

from plantcraft_sdk import contributes as _contributes
from plantcraft_sdk import derived as _derived
from plantcraft_sdk import desk as _desk
from plantcraft_sdk import events as _events
from plantcraft_sdk import explore as _explore
from plantcraft_sdk import jwt
from plantcraft_sdk import links as _links
from plantcraft_sdk import llm as _llm
from plantcraft_sdk import scopes as _scopes
from plantcraft_sdk.assets import (
    MAX_RESULT_ASSETS,
    RESULT_TYPE,
    STARTER_TYPES,
    parse_result_assets,
    resolve_types,
    type_path,
)
from plantcraft_sdk.contract import (
    AGGREGATIONS,
    CENTRAL_AUDIENCE,
    ISSUER,
    MAX_BATCH_POINTS,
    MAX_BATCH_SIGNALS,
    MAX_POINTS,
    SERVICE_TOKEN_SECONDS,
    TOKEN_COOKIE,
    USER_TOKEN_SECONDS,
    BatchBuilder,
    ContractError,
    aggregate,
    iso,
    iso_many,
    kind_of,
    parse_times,
    parse_window,
    series_range,
    shape_values,
    subject_digest,
    unique_signals,
)
from plantcraft_sdk.people import check_notification, check_resolution
from plantcraft_sdk.refs import split_signal_id

BASE_URL = "http://processcraft.test"
SESSION_COOKIE = "processcraft_session"

DEFAULT_APPS: list[dict[str, Any]] = [
    {"id": "linkcraft", "name": "PlantCraft Analytics", "url": "/link/", "version": "0.1.0"},
]
DEFAULT_USERS: dict[str, dict[str, Any]] = {
    "admin": {"name": "Administrator", "level": "admin", "apps": {"linkcraft": "editor"}},
    "engineer": {"name": "Process Engineer", "level": "editor", "apps": {"linkcraft": "editor"}},
    "operator": {"name": "Operator", "level": "viewer", "apps": {"linkcraft": "viewer"}},
    "outsider": {"name": "No Apps", "level": "viewer", "apps": {}},
}
DEFAULT_APP_KEYS = {"linkcraft": "test-app-key"}
DEFAULT_GROUPS: list[dict[str, Any]] = [
    {"id": "operations", "name": "Operations", "kind": "team", "members": ["operator"]},
    {
        "id": "process-engineering",
        "name": "Process engineering",
        "kind": "discipline",
        "coordinator": "engineer",
        "members": ["engineer", "admin"],
    },
]
DEFAULT_ASSETS: list[dict[str, Any]] = [
    {"id": "plant", "name": "Plant", "kind": "site", "parent_id": None, "attributes": {}},
    {"id": "unit-100", "name": "Unit 100", "kind": "unit", "parent_id": "plant", "attributes": {}},
    {
        "id": "fv-101",
        "name": "FV-101",
        "kind": "control_valve",
        "parent_id": "unit-100",
        "attributes": {"description": "Feed valve", "characteristic": "equal percentage"},
    },
    {
        "id": "fic-101",
        "name": "FIC-101",
        "kind": "loop",
        "parent_id": "unit-100",
        "attributes": {
            "description": "Feed flow control",
            "loop_type": "flow",
            "criticality": "high",
            "action": "reverse",
            "controller": "DCS",
        },
        "relations": [{"type": "controls", "to": "fv-101"}],
        "signals": {
            "pv": "fake:FIC-101.PV",
            "sp": "fake:FIC-101.SP",
            "op": "fake:FIC-101.OP",
            "mode": "fake:FIC-101.MODE",
        },
    },
    {
        "id": "lic-102",
        "name": "LIC-102",
        "kind": "loop",
        "parent_id": "unit-100",
        "attributes": {"description": "Drum level control", "loop_type": "level"},
        "signals": {"pv": "fake:LIC-102.PV", "sp": "fake:LIC-102.SP", "op": "fake:LIC-102.OP"},
    },
]


# The source id of the fake's own signals.
FAKE_SOURCE = "fake"


def _signal(tag: str, name: str, unit: str, low: float | None, high: float | None) -> dict:
    # No "kind": the fake answers it from the given series (labels are text), else "number".
    return {
        "id": f"{FAKE_SOURCE}:{tag}",
        "name": name,
        "source": FAKE_SOURCE,
        "unit": unit,
        "description": name,
        "low": low,
        "high": high,
        # The fake's signals read like an OPC UA source's (no laboratory sampling).
        "source_kind": "opcua",
    }


DEFAULT_SIGNALS: list[dict[str, Any]] = [
    _signal("FIC-101.PV", "Feed flow", "m3/h", 0.0, 100.0),
    _signal("FIC-101.SP", "Feed flow setpoint", "m3/h", 0.0, 100.0),
    _signal("FIC-101.OP", "Feed valve output", "%", 0.0, 100.0),
    _signal("FIC-101.MODE", "Feed flow mode (1 auto)", "", None, None),
    _signal("LIC-102.PV", "Drum level", "%", 0.0, 100.0),
    _signal("LIC-102.SP", "Drum level setpoint", "%", 0.0, 100.0),
    _signal("LIC-102.OP", "Drum outlet valve", "%", 0.0, 100.0),
]


def synthetic(signal_id: str, times: pd.DatetimeIndex) -> np.ndarray:
    """A deterministic process-like signal: a level, a slow wave and repeatable noise.

    Seeded by the tag, so ``fake:FIC-101.PV`` and ``FIC-101.PV`` draw the same values.
    """

    signal_id = split_signal_id(signal_id)[1]
    seed = zlib.crc32(signal_id.encode()) % 1000
    seconds = times.as_unit("ns").asi8 / 1e9 if len(times) else np.array([])
    suffix = signal_id.rsplit(".", 1)[-1].upper()
    if suffix == "MODE":
        return np.ones(len(times))
    if suffix == "SP":
        return 50.0 + 5.0 * (np.floor(seconds / 3600.0) % 2)
    level = 40.0 if suffix == "OP" else 50.0
    wave = 3.0 * np.sin(2 * math.pi * seconds / (600.0 + seed))
    noise = (np.sin(seconds * 12.9898 + seed) * 43758.5453) % 1.0 - 0.5
    return level + wave + noise


def synthetic_text(signal_id: str, times: pd.DatetimeIndex) -> list[str]:
    """A text signal with no given series: a controller left in automatic."""

    return ["AUTO"] * len(times)


class _Abort(Exception):
    def __init__(self, status: int, detail: Any, headers: dict[str, str] | None = None):
        super().__init__(str(detail))
        self.status = status
        self.detail = detail
        self.headers = headers or {}


@dataclass
class FakeResponse:
    """What ``FakePlantCraft.handle`` answers: a status, a JSON body, headers, cookies."""

    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)
    # (name, value, max_age) set on the caller, as PlantCraft's Set-Cookie does.
    cookies: list[tuple[str, str, int]] = field(default_factory=list)

    def content(self) -> bytes:
        return json.dumps(self.body, separators=(",", ":"), allow_nan=False).encode()

    def set_cookie_headers(self) -> list[str]:
        return [
            f"{name}={value}; Max-Age={max_age}; Path=/; HttpOnly; SameSite=lax"
            for name, value, max_age in self.cookies
        ]


# Derived kinds kept as written and read back as recorded values (no grid; only agg=last).
_TYPED_KINDS = ("integer", "boolean", "instant", "structured")

_ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("GET", re.compile(r"^/api/v1/auth/keys$"), "keys"),
    ("GET", re.compile(r"^/api/v1/auth/revoked$"), "revoked"),
    ("POST", re.compile(r"^/api/v1/auth/token$"), "renew"),
    ("POST", re.compile(r"^/api/v1/auth/service-token$"), "service_token"),
    ("GET", re.compile(r"^/api/v1/me$"), "me"),
    ("GET", re.compile(r"^/api/v1/apps$"), "apps"),
    ("GET", re.compile(r"^/api/v1/installation$"), "installation"),
    ("GET", re.compile(r"^/api/v1/assets$"), "assets"),
    ("GET", re.compile(r"^/api/v1/explore$"), "explore"),
    ("PUT", re.compile(r"^/api/v1/assets/results$"), "put_result_assets"),
    ("POST", re.compile(r"^/api/v1/assets/results/remove$"), "remove_result_assets"),
    ("GET", re.compile(r"^/api/v1/assets/(?P<id>.+)$"), "asset"),
    ("GET", re.compile(r"^/api/v1/asset-types$"), "asset_types"),
    ("GET", re.compile(r"^/api/v1/signals$"), "signals"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)/series$"), "series"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)/value$"), "value"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)/runs$"), "run_list"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)$"), "signal"),
    ("POST", re.compile(r"^/api/v1/series$"), "series_batch"),
    ("PUT", re.compile(r"^/api/v1/series$"), "put_series"),
    ("POST", re.compile(r"^/api/v1/series/retire$"), "retire_series"),
    ("PUT", re.compile(r"^/api/v1/series/runs$"), "put_series_runs"),
    ("POST", re.compile(r"^/api/v1/audit$"), "audit"),
    ("GET", re.compile(r"^/api/v1/people$"), "people"),
    ("GET", re.compile(r"^/api/v1/groups$"), "groups"),
    ("GET", re.compile(r"^/api/v1/notifications$"), "notification_settings"),
    ("POST", re.compile(r"^/api/v1/notifications$"), "notify"),
    ("POST", re.compile(r"^/api/v1/notifications/resolve$"), "resolve_notification"),
]


# Results, events, runs and schedules (plantcraft_sdk.links) ------------------------
#
# The fake keeps them in memory, in ``fake.links``; the rules are the shared ones of
# ``plantcraft_sdk.links``, so a body the fake accepts PlantCraft accepts too.

_ROUTES.extend(
    [
        ("PUT", re.compile(r"^/api/v1/results$"), "put_results"),
        ("GET", re.compile(r"^/api/v1/results$"), "results"),
        ("GET", re.compile(r"^/api/v1/results/history$"), "result_history"),
        ("POST", re.compile(r"^/api/v1/events$"), "post_event"),
        ("GET", re.compile(r"^/api/v1/events$"), "events"),
        ("PUT", re.compile(r"^/api/v1/events/catalog$"), "put_event_catalog"),
        ("GET", re.compile(r"^/api/v1/events/catalog$"), "event_catalog"),
        ("PUT", re.compile(r"^/api/v1/contributions$"), "put_contributions"),
        ("GET", re.compile(r"^/api/v1/contributions$"), "contributions"),
        ("POST", re.compile(r"^/api/v1/llm/(?P<use>[^/]+)$"), "llm"),
        ("GET", re.compile(r"^/api/v1/contributions/settings$"), "contribution_settings"),
        ("PUT", re.compile(r"^/api/v1/calendar/(?P<feed>[^/]+)$"), "put_calendar"),
        ("POST", re.compile(r"^/api/v1/todos$"), "put_todo"),
        ("GET", re.compile(r"^/api/v1/todos$"), "todos"),
        ("POST", re.compile(r"^/api/v1/todos/close$"), "close_todos"),
        ("PUT", re.compile(r"^/api/v1/runs$"), "put_runs"),
        ("GET", re.compile(r"^/api/v1/runs$"), "runs"),
        ("PUT", re.compile(r"^/api/v1/knowledge$"), "put_knowledge"),
        ("POST", re.compile(r"^/api/v1/knowledge/delete$"), "delete_knowledge"),
        ("GET", re.compile(r"^/api/v1/knowledge$"), "knowledge"),
        ("PUT", re.compile(r"^/api/v1/schedules$"), "put_schedules"),
        ("GET", re.compile(r"^/api/v1/schedules$"), "schedules"),
    ]
)
# Rows a read answers when it gives no ``limit`` (as PlantCraft).
_SHORT = 100

# Each route's path as API v1 names it, for the permission it needs (plantcraft_sdk.scopes).
_TEMPLATES: dict[str, str] = {
    "asset": "/api/v1/assets/{asset_id}",
    "signal": "/api/v1/signals/{signal_id}",
    "series": "/api/v1/signals/{signal_id}/series",
    "value": "/api/v1/signals/{signal_id}/value",
    "run_list": "/api/v1/signals/{signal_id}/runs",
    "llm": "/api/v1/llm/{use}",
    "put_calendar": "/api/v1/calendar/{feed}",
}
# The permissions each app's own token used in every fake of this test run, by app id
# (``apptest.permission_problems`` holds them to the app's ``app.toml``).
PERMISSIONS_USED: dict[str, set[str]] = {}


def _template(name: str, pattern: re.Pattern[str]) -> str:
    return _TEMPLATES.get(name) or pattern.pattern.strip("^$").replace("\\", "")


@dataclass
class FakeLinks:
    """What apps published to the fake: inspect it in tests (``fake.links.results``...)."""

    # (app, subject, kind) -> stored result
    results: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    # (app, run id) -> run
    runs: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # app -> its schedules, in order
    schedules: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # (app, ref) -> text
    knowledge: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # app -> its declared events (PUT /api/v1/events/catalog, or ``fake.declare_events``).
    # An app with a catalog here may post only the events it declares: the fake answers 422
    # where PlantCraft only logs a warning, so a typo fails in the app's own tests.
    catalogs: dict[str, _events.EventCatalog] = field(default_factory=dict)
    # app -> what it adds to PlantCraft (PUT /api/v1/contributions), as PlantCraft stores it.
    contributions: dict[str, dict[str, Any]] = field(default_factory=dict)
    # What POST /api/v1/llm/{use} received: {"app", "use", "system", "messages"}.
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    # The model's answer: a text, or a function of the call; None answers as if the use had
    # no model (409), as PlantCraft does until an administrator sets one up.
    llm_answer: Any = "A model's answer."
    # (app, feed) -> its items (PUT /api/v1/calendar/<feed>)
    calendar: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    # (app, key) -> to-do (POST /api/v1/todos); tick one in a test with ``fake.tick_todo``.
    todos: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    # app -> {key: value} an administrator chose in Setup › Apps; set them in a test.
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)


class _LinksRoutes:
    """The fake's routes for results, events, runs and schedules (mixed into the fake)."""

    @cached_property
    def links(self) -> FakeLinks:
        return FakeLinks()

    def _links_now(self) -> str:
        return self.now.astimezone(timezone.utc).isoformat(timespec="seconds")  # type: ignore[attr-defined]

    def _links_app(self, claims: dict[str, Any], given: Any) -> str:
        subject = str(claims.get("sub") or "")
        if subject.startswith("app:"):
            own = subject[4:]
            if given and str(given).strip().lower() != own:
                raise _links.LinkError(403, "A service token writes only for its own app.")
            return own
        if not given:
            raise _links.LinkError(422, "app is required with a person's token.")
        app = str(given).strip().lower()
        if (claims.get("apps") or {}).get(app) != "editor":
            raise _links.LinkError(403, f"You need editor access to {app} to write for it.")
        return app

    def _links_prefix(self, app: str) -> str | None:
        installed = self.apps_installed  # type: ignore[attr-defined]
        return next((item["url"] for item in installed if item["id"] == app), None)

    def _links_subject(self, subject: str) -> str:
        """The subject as stored (a bare signal tag by its signal's id); 404 when unknown."""

        kind, item = _links.split_subject(subject)
        if kind == "asset":
            if not any(asset["id"] == item for asset in self.assets):  # type: ignore[attr-defined]
                raise _links.LinkError(404, f"Asset not found. ({subject})")
            return subject
        try:
            found = self._known(item)  # type: ignore[attr-defined]
        except _Abort as abort:
            raise _links.LinkError(404, f"{abort.detail} ({subject})") from abort
        if found is None:
            raise _links.LinkError(404, f"Signal not found. ({subject})")
        return f"signal:{found['id']}"

    def _links_named(self, ref: str | None) -> str | None:
        """A ``signal:`` reference by its signal's id when it names a known one."""

        if ref is None or not ref.startswith("signal:"):
            return ref
        try:
            found = self._known(ref[len("signal:") :])  # type: ignore[attr-defined]
        except _Abort:
            return ref
        return f"signal:{found['id']}" if found else ref

    @staticmethod
    def _links_limit(query: dict[str, str], default: int = _SHORT) -> int:
        raw = query.get("limit")
        try:
            limit = default if raw in (None, "") else int(raw)
        except ValueError as exc:
            raise ContractError("limit is a whole number from 1 to 500.") from exc
        if not 1 <= limit <= _links.MAX_READ:
            raise ContractError("limit is a whole number from 1 to 500.")
        return limit

    @staticmethod
    def _links_kind(app: str | None, kind: str | None) -> tuple[str | None, str | None]:
        if kind and "." in kind:
            owner, _, name = kind.partition(".")
            return (app, "\0") if app and app != owner else (owner, name)
        return app, kind

    def _route_put_results(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        items = _links.parse_body(_links.ResultIn, request.json(), many=True)
        now = self._links_now()
        errors = []
        saved = 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                subject = self._links_subject(item.subject)
                kind = _links.result_kind(item.kind, app)
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.subject, error.status, error.detail))
                continue
            row = {
                **item.model_dump(exclude={"app", "kind"}),
                "subject": subject,
                "app": app,
                "kind": kind,
                "at": item.at or now,
                "updated_at": now,
            }
            key = (app, subject, kind)
            previous = self.links.results.get(key)
            if previous is None or previous["status"] != row["status"]:
                change = {name: row[name] for name in _CHANGE_FIELDS}
                self.links.history.append({**change, "recorded_at": now})
            self.links.results[key] = row
            saved += 1
        cutoff = _links.cutoff_text(self.now)  # type: ignore[attr-defined]
        self.links.history = [row for row in self.links.history if row["recorded_at"] >= cutoff]
        return {"saved": saved, "errors": errors}

    def _route_results(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        wanted = _links.subjects_param(request.lists.get("subject"))
        if len(wanted) > _links.MAX_SUBJECTS:
            raise ContractError(f"Ask for at most {_links.MAX_SUBJECTS} subjects at once.")
        wanted = [str(self._links_named(item)) for item in wanted]
        app, kind = self._links_kind(request.query.get("app"), request.query.get("kind"))
        now = self._links_now()
        rows = sorted(
            self.links.results.values(), key=lambda r: (r["subject"], r["app"], r["kind"])
        )
        return [
            _links.stale_view(row, now)
            for row in rows
            if (not wanted or row["subject"] in wanted)
            and (app is None or row["app"] == app)
            and (kind is None or row["kind"] == kind)
        ]

    def _route_result_history(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        subject = request.query.get("subject")
        if not subject:
            raise ContractError("subject is required.")
        subject = self._links_named(subject)
        app, kind = self._links_kind(request.query.get("app"), request.query.get("kind"))
        after = _links.utc_text(request.query.get("after"), "after")
        rows = [
            {name: row[name] for name in _CHANGE_FIELDS}
            for row in sorted(self.links.history, key=lambda r: r["at"])
            if row["subject"] == subject
            and (app is None or row["app"] == app)
            and (kind is None or row["kind"] == kind)
            and (after is None or row["at"] > after)
        ]
        return rows[: self._links_limit(request.query)]

    def _route_post_event(self, request: "_Request") -> "FakeResponse":
        claims = self._caller(request)  # type: ignore[attr-defined]
        items, many = _links.parse_events(request.json())
        ids: list[int | None] = []
        errors = []
        repeated = 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                kind = _links.event_kind(item.kind, app)
                if _links.own_app_subject(item.subject, app):
                    subject = item.subject
                else:
                    subject = self._links_subject(item.subject)
                catalog = self.links.catalogs.get(app)
                spec = catalog.spec(kind) if catalog is not None else None
                if catalog is not None and spec is None:
                    raise _links.LinkError(
                        422, f"{kind} is not in the event catalog of {app} (app.toml)."
                    )
                fields = _events.event_fields(item, spec)
            except _links.LinkError as error:
                if not many:
                    raise _Abort(error.status, error.detail) from error
                errors.append(_links.item_error(index, item.subject, error.status, error.detail))
                ids.append(None)
                continue
            refs = [subject]
            for ref in item.refs:
                ref = str(self._links_named(ref))
                if ref not in refs:
                    refs.append(ref)
            same = self._links_repeated(app, fields)
            if same is not None:
                echo = {**(same or {}), "repeated": True}
                if not many:
                    return FakeResponse(
                        201, echo if same else {"id": None, **fields, "repeated": True}
                    )
                ids.append(same["id"] if same else None)
                repeated += 1
                continue
            event = {
                "id": len(self.links.events) + 1,
                "at": self._links_now(),
                "app": app,
                "kind": kind,
                "subject": subject,
                "actor": str(claims.get("sub") or ""),
                "summary": item.summary,
                "refs": refs,
                "payload": item.payload,
                **fields,
            }
            self.links.events.append(event)
            if not many:
                return FakeResponse(201, event)
            ids.append(event["id"])
        saved = sum(1 for item in ids if item is not None) - repeated
        return FakeResponse(
            201, {"saved": saved, "ids": ids, "errors": errors, "repeated": repeated}
        )

    def _links_repeated(self, app: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        """PlantCraft keeps only changes: the event already saying this start (same severity)
        or end, ``{}`` for an end of a condition never opened, None for a change."""

        key, phase = fields.get("key"), fields.get("phase")
        if not key or phase not in ("start", "end"):
            return None
        before = next(
            (
                event
                for event in reversed(self.links.events)
                if event["app"] == app
                and event.get("key") == key
                and event.get("phase") in ("start", "end")
            ),
            None,
        )
        if phase == "end":
            if before is None:
                return {}
            return before if before["phase"] == "end" else None
        if before and before["phase"] == "start" and before["severity"] == fields["severity"]:
            return before
        return None

    def _route_events(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        query = request.query
        ref, kind, key = self._links_named(query.get("ref")), query.get("kind"), query.get("key")
        try:
            after = None if query.get("after") in (None, "") else int(query["after"])
        except ValueError as exc:
            raise ContractError("after is the id of an event.") from exc
        limit = self._links_limit(query)
        found = [
            event
            for event in self.links.events
            if (ref is None or ref in event["refs"])
            and (kind is None or event["kind"] == kind)
            and (key is None or event.get("key") == key)
        ]
        if after is not None:
            return [event for event in found if event["id"] > after][:limit]
        return found[-limit:]

    def declare_events(self, manifest: Any, app: str | None = None) -> _events.EventCatalog:
        """Hold the app to the events its manifest declares (``app.toml`` dict or AppManifest)."""

        catalog = _events.EventCatalog.from_manifest(manifest, app=app)
        self.links.catalogs[catalog.app] = catalog
        return catalog

    def _route_put_event_catalog(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            body = _events.CatalogIn.model_validate(request.json())
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        try:
            app = self._links_app(claims, body.app)
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error
        self.links.catalogs[app] = _events.EventCatalog(app, body.events)
        return {"app": app, "events": len(body.events)}

    def _route_put_contributions(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            body = _contributes.ContributionsIn.model_validate(request.json() or {})
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        try:
            app = self._links_app(claims, body.app)
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error
        self.links.contributions[app] = {
            "app": app,
            **body.model_dump(mode="json", exclude_none=True, exclude={"app", "events"}),
            "updated_at": self._links_now(),
        }
        self.links.catalogs[app] = _events.EventCatalog(app, body.events)
        return {"app": app, "events": len(body.events), "unknown": body.unknown}

    def _route_contributions(self, request: "_Request") -> dict[str, Any]:
        self._reader(request)  # type: ignore[attr-defined]
        return {
            "features": list(_contributes.FEATURES),
            "apps": [
                {**item, "name": app} for app, item in sorted(self.links.contributions.items())
            ],
        }

    def _route_llm(self, request: "_Request", use: str) -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app writes with its own uses of a model.")
        app = subject[4:]
        try:
            name = _llm.split_use(app, unquote(use))
        except ValueError as exc:
            raise _Abort(403, str(exc)) from exc
        declared = (self.links.contributions.get(app) or {}).get("contributes", {}).get("llm", [])
        if name not in {item["id"] for item in declared}:
            raise _Abort(404, f"{app} declares no use {name!r} in [[contributes.llm]].")
        body = request.json() or {}
        try:
            sent = _llm.messages_body(body.get("messages") or [], system=body.get("system") or "")
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        call = {"app": app, "use": name, **sent}
        self.links.llm_calls.append(call)
        answer = (
            self.links.llm_answer(call)
            if callable(self.links.llm_answer)
            else self.links.llm_answer
        )
        if answer is None:
            raise _Abort(409, "This use has no language model now.")
        return {"use": f"{app}:{name}", "model": "fake", "text": str(answer)}

    def _route_contribution_settings(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        app = str(claims.get("sub", ""))
        if not app.startswith("app:"):
            raise _Abort(403, "Only an app reads its settings.")
        app = app[4:]
        row = self.links.contributions.get(app) or {}
        specs = (row.get("contributes") or {}).get("settings", [])
        chosen = self.links.settings.get(app, {})
        for key, value in chosen.items():
            spec = next((item for item in specs if item["key"] == key), None)
            if spec is None:
                raise ContractError(f"{app} declares no setting {key}.")
            _contributes.setting_value(spec, value)
        return {
            "app": app,
            "values": {spec["key"]: chosen.get(spec["key"], spec.get("default")) for spec in specs},
        }

    # Desk: calendar feeds and to-dos (plantcraft_sdk.desk) ------------------------------

    def _declared(self, app: str, table: str) -> set[str]:
        row = self.links.contributions.get(app) or {}
        return {item["id"] for item in (row.get("contributes") or {}).get(table, [])}

    def _desk_app(self, request: "_Request") -> str:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            return self._links_app(claims, request.query.get("app"))
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error

    def _route_put_calendar(self, request: "_Request", feed: str) -> dict[str, Any]:
        app = self._desk_app(request)
        feed = unquote(feed)
        if feed not in self._declared(app, "calendar"):
            raise _Abort(
                422, f"{app} has no calendar feed {feed}: declare it in [[contributes.calendar]]."
            )
        body = request.json()
        try:
            given = _desk.FeedIn.model_validate({"items": body if isinstance(body, list) else None})
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        self.links.calendar[(app, feed)] = [item.model_dump(mode="json") for item in given.items]
        return {"app": app, "feed": feed, "items": len(given.items)}

    def _route_put_todo(self, request: "_Request") -> dict[str, Any]:
        app = self._desk_app(request)
        try:
            given = _desk.TodoIn.model_validate(request.json() or {})
        except ValidationError as exc:
            raise ContractError(str(exc.errors(include_url=False)[0].get("msg"))) from exc
        if given.kind not in self._declared(app, "todo"):
            raise _Abort(
                422, f"{app} has no to-do kind {given.kind}: declare it in [[contributes.todo]]."
            )
        known = self.links.todos.get((app, given.key))
        if known is None:
            open_ = sum(
                1
                for (owner, _), item in self.links.todos.items()
                if owner == app and item["for"] == given.for_ and not item["done"]
            )
            if open_ >= _desk.MAX_OPEN_TODOS:
                raise _Abort(429, f"{given.for_} already has {_desk.MAX_OPEN_TODOS} open to-dos.")
        now = self._links_now()
        item = {
            "app": app,
            "detail": "",
            **given.as_body(),
            "done": bool(known and known["done"]),
            "done_at": known["done_at"] if known else None,
            "done_by": known["done_by"] if known else None,
            "created_at": known["created_at"] if known else now,
            "updated_at": now,
        }
        self.links.todos[(app, given.key)] = item
        return item

    def tick_todo(self, app: str, key: str, by: str, done: bool = True) -> dict[str, Any]:
        """A person ticks (or unticks) the app's to-do in Desk."""

        item = self.links.todos[(app, key)]
        item.update(
            done=done, done_at=self._links_now() if done else None, done_by=by if done else None
        )
        return item

    def _route_todos(self, request: "_Request") -> list[dict[str, Any]]:
        app = self._desk_app(request)
        state = request.query.get("state", "all")
        items = [item for (owner, _), item in self.links.todos.items() if owner == app]
        if state != "all":
            items = [item for item in items if item["done"] == (state == "done")]
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)

    def _route_close_todos(self, request: "_Request") -> dict[str, Any]:
        app = self._desk_app(request)
        keys = (request.json() or {}).get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 500:
            raise ContractError("keys is a list of 1 to 500 keys.")
        closed = sum(1 for key in dict.fromkeys(keys) if self.links.todos.pop((app, key), None))
        return {"app": app, "closed": closed}

    def _route_event_catalog(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        return [
            {
                "app": app,
                "name": app,
                "updated_at": None,
                "events": [{"kind": f"{app}.{spec['name']}", **spec} for spec in catalog.to_json()],
                "undeclared": [],
            }
            for app, catalog in sorted(self.links.catalogs.items())
        ]

    def _route_put_runs(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        items = _links.parse_body(_links.RunIn, request.json(), many=True)
        now = self._links_now()
        errors, saved = [], 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                url = _links.check_url(item.url, self._links_prefix(app))
                cancel = _links.check_url(item.cancel, self._links_prefix(app))
                if cancel and not cancel.startswith("/"):
                    raise _links.LinkError(422, "cancel is a path under the app's prefix.")
                subjects = list(
                    dict.fromkeys(self._links_subject(subject) for subject in item.subjects)
                )
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.id, error.status, error.detail))
                continue
            row = item.model_dump(exclude={"app"})
            self.links.runs[(app, item.id)] = {
                **row,
                "app": app,
                "url": url,
                "cancel": cancel,
                "subjects": subjects,
                "updated_at": now,
            }
            saved += 1
        cutoff = _links.cutoff_text(self.now)  # type: ignore[attr-defined]
        self.links.runs = {
            key: run for key, run in self.links.runs.items() if run["updated_at"] >= cutoff
        }
        return {"saved": saved, "errors": errors}

    def _route_runs(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        query = request.query
        status, app, by = query.get("status"), query.get("app"), query.get("by")
        subject = self._links_named(query.get("subject"))
        if status is not None and status not in _links.RUN_STATUSES:
            raise ContractError(f"Invalid status: use one of {', '.join(_links.RUN_STATUSES)}.")
        rows = sorted(
            self.links.runs.values(),
            key=lambda run: run["started_at"] or run["updated_at"],
            reverse=True,
        )
        return [
            run
            for run in rows
            if (app is None or run["app"] == app)
            and (status is None or run["status"] == status)
            and (subject is None or subject in run["subjects"])
            and (by is None or run.get("by") == by)
        ][: self._links_limit(query)]

    def _route_put_knowledge(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        items = _links.parse_body(_links.KnowledgeIn, request.json(), many=True)
        now = self._links_now()
        errors, saved = [], 0
        for index, item in enumerate(items):
            try:
                app = self._links_app(claims, item.app)
                url = _links.check_url(item.url, self._links_prefix(app))
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.ref, error.status, error.detail))
                continue
            row = item.model_dump(exclude={"app"})
            self.links.knowledge[(app, item.ref)] = {
                **row,
                "app": app,
                "url": url,
                "updated_at": now,
            }
            saved += 1
        return {"saved": saved, "errors": errors}

    def _route_delete_knowledge(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            app = self._links_app(claims, request.query.get("app"))
        except _links.LinkError as error:
            raise ContractError(error.detail) from error
        refs = set((request.json() or {}).get("refs") or [])
        before = len(self.links.knowledge)
        self.links.knowledge = {
            key: item
            for key, item in self.links.knowledge.items()
            if not (key[0] == app and key[1] in refs)
        }
        return {"deleted": before - len(self.links.knowledge)}

    def _route_knowledge(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        query = request.query
        ref, app, words = query.get("ref"), query.get("app"), (query.get("q") or "").lower()
        rows = sorted(self.links.knowledge.values(), key=lambda item: item["updated_at"])
        return [
            item
            for item in reversed(rows)
            if (ref is None or item["ref"] == ref or ref in item["subjects"])
            and (app is None or item["app"] == app)
            and all(word in f"{item['title']} {item['text']}".lower() for word in words.split())
        ][: self._links_limit(query)]

    def _route_put_schedules(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)  # type: ignore[attr-defined]
        try:
            app = self._links_app(claims, request.query.get("app"))
        except _links.LinkError as error:
            raise _Abort(error.status, error.detail) from error
        items = _links.parse_body(_links.ScheduleIn, request.json(), many=True)
        ids = [item.id for item in items]
        if len(set(ids)) != len(ids):
            raise ContractError("Each schedule id appears once.")
        now, prefix = self._links_now(), self._links_prefix(app)
        kept, errors = [], []
        for index, item in enumerate(items):
            try:
                url = _links.check_url(item.url, prefix)
                for subject in item.subjects:
                    _links.split_subject(subject)
            except _links.LinkError as error:
                errors.append(_links.item_error(index, item.id, error.status, error.detail))
                continue
            subjects = list(dict.fromkeys(item.subjects))
            kept.append(
                {
                    **item.model_dump(),
                    "app": app,
                    "url": url,
                    "subjects": subjects,
                    "updated_at": now,
                }
            )
        self.links.schedules[app] = kept
        return {"saved": len(kept), "errors": errors}

    def _route_schedules(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)  # type: ignore[attr-defined]
        app = request.query.get("app")
        return [
            schedule
            for owner in sorted(self.links.schedules)
            if app is None or owner == app
            for schedule in self.links.schedules[owner]
        ]


_CHANGE_FIELDS = ("app", "subject", "kind", "status", "score", "usable", "value", "summary", "at")


class FakePlantCraft(_LinksRoutes):
    """An in-process PlantCraft API v1 with its own key pair, users, assets and signals."""

    def __init__(
        self,
        *,
        users: dict[str, dict[str, Any]] | None = None,
        apps: list[dict[str, Any]] | None = None,
        app_keys: dict[str, str] | None = None,
        assets: list[dict[str, Any]] | None = None,
        asset_types: list[dict[str, Any]] | None = None,
        signals: list[dict[str, Any]] | None = None,
        series: dict[str, pd.Series] | None = None,
        sample_seconds: float = 10.0,
        now: datetime | None = None,
        recorded: bool | None = None,
        groups: list[dict[str, Any]] | None = None,
        time_zone: str = "UTC",
    ):
        self.users = copy.deepcopy(DEFAULT_USERS if users is None else users)
        # The installation's zone, as ``GET /api/v1/installation`` answers it ("local").
        self.time_zone = time_zone
        # Groups as GET /api/v1/groups answers them ({"id", "name", "kind", "members", ...}).
        self.groups = [
            {
                "description": "",
                "asset_id": None,
                "coordinator": None,
                "members": [],
                "parent_id": None,
                **item,
            }
            for item in copy.deepcopy(DEFAULT_GROUPS if groups is None else groups)
        ]
        # What apps sent with POST /api/v1/notifications: the body, the app and who received it.
        self.notifications: list[dict[str, Any]] = []
        # What apps settled with POST /api/v1/notifications/resolve: {(app, key): note}.
        self.resolved_notifications: dict[tuple[str, str], str] = {}
        # Whether the platform's email server is set up (GET /api/v1/notifications).
        self.email_ready = False
        self.apps_installed = copy.deepcopy(DEFAULT_APPS if apps is None else apps)
        self.app_keys = dict(DEFAULT_APP_KEYS if app_keys is None else app_keys)
        # Type definitions as an admin writes them (own attributes and roles only);
        # ``GET /api/v1/asset-types`` answers them resolved, as PlantCraft does.
        self.asset_types = copy.deepcopy(STARTER_TYPES if asset_types is None else asset_types)
        definitions = {item["id"]: item for item in self.asset_types}
        self.assets = [
            {
                "signals": {},
                "attributes": {},
                "relations": [],
                "type_path": type_path(definitions, item["kind"]),
                **item,
            }
            for item in copy.deepcopy(DEFAULT_ASSETS if assets is None else assets)
        ]
        self.signals = copy.deepcopy(DEFAULT_SIGNALS if signals is None else signals)
        self.series_data = dict(series or {})
        self.sample_seconds = sample_seconds
        self._now = now
        # Given series are a recorded file unless told otherwise.
        self.recorded = bool(self.series_data) if recorded is None else recorded
        # Signal ids whose reads fail as a dead data source would (502).
        self.broken: dict[str, str] = {}
        # Points one POST /api/v1/series answers before it postpones the rest (413).
        self.batch_points = MAX_BATCH_POINTS
        self.audit_log: list[dict[str, Any]] = []
        # Derived signal id -> {instant (UTC ISO): value}, as apps wrote them.
        self.derived: dict[str, dict[str, Any]] = {}
        # Runs points: signal id -> {run_at (UTC ISO): {"t", "v"}}, as apps wrote them.
        self.derived_runs: dict[str, dict[str, dict[str, list[Any]]]] = {}
        self.requests = 0
        # Tokens ended early (``revoke``), as ``GET /api/v1/auth/revoked`` lists them.
        self.revoked_users: dict[str, int] = {}
        self.revoked_keys: set[str] = set()
        # Sessions signed out (``end_session``): the ``sid`` claim of their tokens.
        self.ended_sessions: set[str] = set()
        self.private_key = jwt.generate_private_key()
        self.kid = jwt.key_id(self.private_key)
        self._public = [jwt.public_key_to_jwk(self.private_key, self.kid)]

    # Keys and tokens --------------------------------------------------------

    @property
    def now(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    @property
    def data_end(self) -> datetime:
        """Now; for a recorded file (given series), its last sample, as PlantCraft answers."""

        if self.recorded:
            ends = [
                pd.Timestamp(values.index.max())
                for values in self.series_data.values()
                if len(values) and not pd.isna(values.index.max())
            ]
            if ends:
                last = max(
                    stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
                    for stamp in ends
                )
                return last.to_pydatetime()
        return self.now

    @property
    def jwks(self) -> dict[str, Any]:
        return {"keys": list(self._public)}

    def revoke(self, username: str, *, at: int | None = None) -> None:
        """End the tokens ``username`` holds now (disabled, new password or access)."""

        self.revoked_users[username] = int(time.time()) + 1 if at is None else at

    def end_session(self, sid: str) -> None:
        """Sign out the browser session whose tokens carry ``sid`` (the session's digest)."""

        self.ended_sessions.add(sid)

    def rotate_key(self) -> str:
        """Sign with a new key from now on; the old public key stays listed."""

        self.private_key = jwt.generate_private_key()
        self.kid = jwt.key_id(self.private_key)
        self._public.append(jwt.public_key_to_jwk(self.private_key, self.kid))
        return self.kid

    def token(
        self,
        username: str = "admin",
        *,
        aud: str = CENTRAL_AUDIENCE,
        ttl: float = USER_TOKEN_SECONDS,
        **claims: Any,
    ) -> str:
        """A signed user token; ``claims`` override any claim (``apps={...}``, ``level=...``)."""

        user = self.users.get(username, {"name": username, "level": "viewer", "apps": {}})
        # Never older than the user's last revocation, as PlantCraft issues them.
        issued = max(int(time.time()), self.revoked_users.get(username, 0))
        body = {
            "iss": ISSUER,
            "sub": username,
            "name": user.get("name", username),
            "level": user.get("level", "viewer"),
            "apps": dict(user.get("apps") or {}),
            "aud": aud,
            "iat": issued,
            "exp": issued + int(ttl),
        }
        body.update(claims)
        return jwt.encode(body, self.private_key, self.kid)

    def _grant(self, token: str) -> dict[str, str]:
        claims = jwt.decode(token, self.jwks, None, issuer=None)
        return {"token": token, "expires_at": iso(pd.Timestamp(claims["exp"], unit="s"))}

    # Clients ----------------------------------------------------------------

    def http_client(self, transport: str = "mock") -> httpx.Client:
        """An ``httpx.Client`` wired to the fake.

        ``"mock"`` (default): an ``httpx.MockTransport`` calling ``handle`` in
        process. ``"asgi"``: Starlette's ``TestClient`` on ``fake.app``, to run
        the requests through a real ASGI stack.
        """

        if transport == "asgi":
            from starlette.testclient import TestClient

            return TestClient(self.app, base_url=BASE_URL)
        if transport != "mock":
            raise ValueError("transport is 'mock' or 'asgi'.")
        return httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(self._httpx))

    def client(
        self, username: str | None = "admin", *, transport: str = "mock", **options: Any
    ) -> Any:
        """A ``PlantCraftClient`` acting as ``username``, or as an app when given ``app`` and ``key``."""

        from plantcraft_sdk.client import PlantCraftClient

        token = self.token(username) if username and "key" not in options else None
        return PlantCraftClient(BASE_URL, token, http_client=self.http_client(transport), **options)

    def verifier(
        self, app_id: str = "linkcraft", *, transport: str = "mock", **options: Any
    ) -> Any:
        """A ``TokenVerifier`` for ``app_id`` that reads this fake's keys."""

        from plantcraft_sdk.auth import TokenVerifier

        return TokenVerifier(BASE_URL, app_id, http_client=self.http_client(transport), **options)

    # Data -------------------------------------------------------------------

    def _given(self, values: dict[str, Any], signal_id: str) -> Any:
        """What ``series`` or ``broken`` holds for a signal: by its id, else by its bare tag."""

        if signal_id in values:
            return values[signal_id]
        return values.get(split_signal_id(signal_id)[1])

    def kind(self, signal_id: str) -> str:
        """``"text"`` or ``"number"``: as the signal says, else from its given series."""

        found = next((item for item in self.signals if item["id"] == signal_id), None)
        if found is not None and found.get("kind") in _derived.POINT_KINDS:
            return str(found["kind"])
        if found is not None and found.get("kind"):
            return kind_of(found["kind"])
        given = self._given(self.series_data, signal_id)
        if given is not None and not pd.api.types.is_numeric_dtype(given.dtype):
            numbers = pd.to_numeric(given.dropna(), errors="coerce")
            if numbers.isna().any():
                return "text"
        return "number"

    def _signal_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "kind": self.kind(item["id"])}

    def _values(
        self, signal_id: str, start: datetime, end: datetime, step: float | None
    ) -> tuple[list[str], list[Any]]:
        broken = self._given(self.broken, signal_id)
        if broken is not None:
            raise _Abort(502, f"Failed to read history: {broken}")
        kind = self.kind(signal_id)
        if kind in _TYPED_KINDS:
            # Kept as written, read back as recorded values (no grid), as PlantCraft answers.
            low, high = iso(start), iso(end)
            kept = sorted(
                (stamp, value)
                for stamp, value in self.derived.get(signal_id, {}).items()
                if low <= stamp <= high
            )
            return [stamp for stamp, _ in kept], [value for _, value in kept]
        given = self._given(self.series_data, signal_id)
        if given is not None:
            return shape_values(given, start, end, step, kind, now=self.now, signal_id=signal_id)
        period = step or self.sample_seconds
        first = math.ceil(start.timestamp() / period) * period
        count = int(max(0, math.floor((end.timestamp() - first) / period) + 1))
        if step is None and count > MAX_POINTS:
            raise ContractError(
                f"Too many recorded values: at most {MAX_POINTS} per request. Give a step."
            )
        if step is not None:
            times = pd.date_range(start, end, freq=pd.Timedelta(seconds=step), inclusive="left")
        else:
            times = pd.DatetimeIndex(
                pd.to_datetime(first + period * np.arange(count), unit="s", utc=True)
            )
        if kind == "text":
            return iso_many(times), synthetic_text(signal_id, times)
        return iso_many(times), synthetic(signal_id, times).tolist()

    # Requests ---------------------------------------------------------------

    def handle(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str | list[str]] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> FakeResponse:
        """Answer one API v1 request (``path`` decoded, ``headers`` with lowercase names).

        A repeated query parameter is given as a list (``{"subject": ["a", "b"]}``).
        """

        self.requests += 1
        lists = {
            key: [value] if isinstance(value, str) else [str(item) for item in value]
            for key, value in (query or {}).items()
        }
        single = {key: values[-1] for key, values in lists.items() if values}
        request = _Request(
            method.upper(), path, single, dict(headers or {}), dict(cookies or {}), body, lists
        )
        allowed = False
        for route_method, pattern, name in _ROUTES:
            match = pattern.match(path)
            if match is None:
                continue
            allowed = True
            if route_method != request.method:
                continue
            refused = self._app_refusal(request, route_method, _template(name, pattern))
            if refused is not None:
                return FakeResponse(403, {"detail": refused})
            try:
                answer = getattr(self, f"_route_{name}")(request, **match.groupdict())
            except _Abort as abort:
                return FakeResponse(abort.status, {"detail": abort.detail}, abort.headers)
            except ContractError as exc:
                return FakeResponse(422, {"detail": str(exc)})
            if isinstance(answer, FakeResponse):
                return answer
            status = 201 if name == "audit" else 200
            return FakeResponse(status, answer)
        if allowed:
            return FakeResponse(405, {"detail": "Method Not Allowed"})
        return FakeResponse(404, {"detail": "Not Found"})

    def _app_refusal(self, request: "_Request", method: str, route: str) -> str | None:
        """As PlantCraft: an app's own token is held to the ``[permissions]`` it declared in its
        contributions (none declared: not held); every permission used is recorded."""

        try:
            claims = self._caller(request)
        except _Abort:
            return None  # the route answers 401 itself
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            return None
        app = subject.removeprefix("app:")
        known, scope = _scopes.required(method, route)
        if not known:
            return f"{method} {route} is not open to an app's token"
        if scope is None:
            return None
        PERMISSIONS_USED.setdefault(app, set()).add(scope)
        declared = (self.links.contributions.get(app) or {}).get("permissions")
        if declared is not None and scope not in declared:
            return f"{app} did not ask for {scope} in its app.toml [permissions]"
        return None

    def _httpx(self, request: httpx.Request) -> httpx.Response:
        cookies: dict[str, str] = {}
        for part in (request.headers.get("cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name:
                cookies[name] = value
        answer = self.handle(
            request.method,
            request.url.path,
            query=_multi(parse_qsl(request.url.query.decode(), keep_blank_values=True)),
            headers={key.lower(): value for key, value in request.headers.items()},
            cookies=cookies,
            body=request.read(),
        )
        headers = [("content-type", "application/json"), *answer.headers.items()]
        headers += [("set-cookie", value) for value in answer.set_cookie_headers()]
        return httpx.Response(answer.status, headers=headers, content=answer.content())

    @cached_property
    def app(self) -> Any:
        """The fake as an ASGI app (Starlette), to serve over HTTP."""

        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Route

        fake = self

        async def endpoint(request: Any) -> Response:
            answer = fake.handle(
                request.method,
                request.scope["path"],
                query=_multi(request.query_params.multi_items()),
                headers={key.lower(): value for key, value in request.headers.items()},
                cookies=dict(request.cookies),
                body=await request.body(),
            )
            response = Response(
                answer.content(),
                status_code=answer.status,
                media_type="application/json",
                headers=answer.headers,
            )
            for name, value, max_age in answer.cookies:
                response.set_cookie(
                    name, value, max_age=max_age, path="/", httponly=True, samesite="lax"
                )
            return response

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        return Starlette(routes=[Route("/{path:path}", endpoint, methods=methods)])

    # Access -----------------------------------------------------------------

    def _caller(self, request: "_Request") -> dict[str, Any]:
        header = request.headers.get("authorization") or ""
        scheme, _, value = header.partition(" ")
        token = value.strip() if scheme.lower() == "bearer" else ""
        token = token or request.cookies.get(TOKEN_COOKIE) or ""
        challenge = {"WWW-Authenticate": "Bearer"}
        if not token:
            raise _Abort(401, "Sign in to continue.", challenge)
        try:
            return jwt.decode(token, self.jwks, CENTRAL_AUDIENCE)
        except jwt.TokenError as exc:
            raise _Abort(401, f"The token was not accepted: {exc}", challenge) from exc

    def _reader(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        if claims.get("level") not in ("viewer", "editor", "admin"):
            raise _Abort(403, "Your access is limited to dashboards.")
        return claims

    def _known(self, signal_id: str) -> dict[str, Any] | None:
        """The signal of an id, or of a bare tag one signal has (deprecated, as in PlantCraft).

        A bare tag that two sources have is a 404 naming both ids.
        """

        found = next((item for item in self.signals if item["id"] == signal_id), None)
        if found is not None:
            return found
        same = [item for item in self.signals if split_signal_id(item["id"])[1] == signal_id]
        if len(same) > 1:
            ids = ", ".join(sorted(item["id"] for item in same))
            raise _Abort(
                404, f"Signal not found: {signal_id} is in more than one source; use {ids}."
            )
        return same[0] if same else None

    def _signal_or_404(self, signal_id: str) -> dict[str, Any]:
        found = self._known(signal_id)
        if found is None:
            raise _Abort(404, "Signal not found.")
        return found

    # Routes -----------------------------------------------------------------

    def _route_keys(self, request: "_Request") -> dict[str, Any]:
        return self.jwks

    def _route_revoked(self, request: "_Request") -> dict[str, Any]:
        return {
            "users": [
                {"sub_sha256": subject_digest(name), "not_before": stamp}
                for name, stamp in self.revoked_users.items()
            ],
            "keys": [{"key_id": key_id, "revoked_at": 0} for key_id in sorted(self.revoked_keys)],
            "sessions": [{"sid_sha256": sid, "ended_at": 0} for sid in sorted(self.ended_sessions)],
        }

    def _route_renew(self, request: "_Request") -> FakeResponse:
        username = request.cookies.get(SESSION_COOKIE)
        if not username or username not in self.users:
            raise _Abort(401, "Session expired. Sign in again.")
        grant = self._grant(self.token(username))
        return FakeResponse(
            200, grant, cookies=[(TOKEN_COOKIE, grant["token"], USER_TOKEN_SECONDS)]
        )

    def _route_service_token(self, request: "_Request") -> dict[str, str]:
        payload = request.json()
        if not isinstance(payload, dict):
            raise _Abort(422, "Send a JSON object with app and key.")
        app_id, key = str(payload.get("app") or ""), str(payload.get("key") or "")
        expected = self.app_keys.get(app_id)
        if not expected or not hmac.compare_digest(expected, key):
            raise _Abort(401, "Unknown app or key.")
        token = self.token(
            f"app:{app_id}",
            ttl=SERVICE_TOKEN_SECONDS,
            name=app_id,
            level="viewer",
            apps={app_id: "viewer"},
        )
        return self._grant(token)

    def _route_me(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        return {
            "username": claims.get("sub"),
            "name": claims.get("name"),
            "level": claims.get("level"),
            "apps": claims.get("apps") or {},
            "notebooks_url": None,  # Notebooks: off in the fake
        }

    def _route_installation(self, request: "_Request") -> dict[str, Any]:
        self._caller(request)
        return {"time_zone": self.time_zone, "features": list(_contributes.FEATURES)}

    def _route_apps(self, request: "_Request") -> list[dict[str, Any]]:
        allowed = self._caller(request).get("apps") or {}
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "url": item["url"],
                "access": allowed[item["id"]],
                "version": item.get("version"),
            }
            for item in self.apps_installed
            if item["id"] in allowed
        ]

    def _scope(self, claims: dict[str, Any]) -> tuple[set[str], set[str]] | None:
        """The assets and signals a token's ``assets`` claim lets it read, as PlantCraft
        applies it (docs/asset-scope.md); None for the whole plant."""

        from plantcraft_sdk.asset_scope import roots_of

        roots = roots_of(claims)
        if roots is None:
            return None
        children: dict[str | None, list[str]] = {}
        for item in self.assets:
            children.setdefault(item.get("parent_id"), []).append(item["id"])
        assets: set[str] = set()
        pending = [root for root in roots if any(item["id"] == root for item in self.assets)]
        while pending:
            current = pending.pop()
            if current not in assets:
                assets.add(current)
                pending.extend(children.get(current, []))
        signals = {
            str(signal)
            for item in self.assets
            if item["id"] in assets
            for signal in (item.get("signals") or {}).values()
        }
        for item in self.signals:
            subject = str(item.get("subject") or "")
            if subject.startswith("asset:") and subject[6:] in assets:
                signals.add(item["id"])
            if subject.startswith("signal:") and subject[7:] in signals:
                signals.add(item["id"])
        return assets, signals

    def _signal_in_scope(self, request: "_Request", signal_id: str) -> None:
        scope = self._scope(self._caller(request))
        if scope is None:
            return
        found = self._known(signal_id)
        if found is None or found["id"] not in scope[1]:
            raise _Abort(404, "Signal not found.")

    def _route_assets(self, request: "_Request") -> list[dict[str, Any]]:
        scope = self._scope(self._reader(request))
        kind, parent_id = request.query.get("kind"), request.query.get("parent_id")
        wanted = request.query.get("type")
        results = request.query.get("results") == "true" or RESULT_TYPE in (kind, wanted)
        return [
            item
            for item in self.assets
            if (results or not isinstance(item, dict) or item.get("kind") != RESULT_TYPE)
            and (kind is None or item["kind"] == kind)
            and (wanted is None or wanted in item["type_path"])
            and (parent_id is None or item["parent_id"] == parent_id)
            and (scope is None or item["id"] in scope[0])
        ]

    def _app_caller(self, request: "_Request", detail: str) -> str:
        subject = str(self._caller(request).get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, detail)
        return subject[4:]

    def _route_put_result_assets(self, request: "_Request") -> dict[str, int]:
        app = self._app_caller(request, "Only an app's service token writes result assets.")
        origin = f"app:{app}"
        try:
            items = parse_result_assets(app, request.json())
        except ValueError as error:
            raise _Abort(422, str(error)) from error
        by_id = {item["id"]: item for item in self.assets}
        for index, item in enumerate(items):
            parent = by_id.get(item["parent_id"])
            if parent is None:
                raise _Abort(422, f"[{index}] parent_id {item['parent_id']} is not an asset.")
            if parent["kind"] == RESULT_TYPE:
                raise _Abort(
                    422,
                    f"[{index}] a result hangs under the asset it is about, not under another result.",
                )
            mine = by_id.get(item["id"])
            if mine is not None and mine["attributes"].get("origin") != origin:
                raise _Abort(422, f"[{index}] {item['id']} is an asset the app does not own.")
        listed = {item["id"] for item in items}
        ended = 0
        for asset in self.assets:
            stale = asset["kind"] == RESULT_TYPE and asset["id"] not in listed
            if stale and asset["attributes"].get("origin") == origin:
                ended += asset["attributes"].get("state") != "ended"
                asset["attributes"]["state"] = "ended"
        for item in items:
            row = {
                "id": item["id"],
                "name": item["name"],
                "kind": RESULT_TYPE,
                "type_path": [RESULT_TYPE],
                "parent_id": item["parent_id"],
                "attributes": {
                    "app": app,
                    "made_by": item["made_by"],
                    "state": "active",
                    "description": item["description"],
                    "kind_label": "Result",
                    "origin": origin,
                },
                "signals": {point["role"]: point["signal"] for point in item["points"]},
                "relations": [],
            }
            if item["id"] in by_id:
                by_id[item["id"]].clear()
                by_id[item["id"]].update(row)
            else:
                self.assets.append(row)
        return {"saved": len(items), "ended": ended}

    def _route_remove_result_assets(self, request: "_Request") -> dict[str, int]:
        app = self._app_caller(request, "Only an app's service token removes result assets.")
        body = request.json() or {}
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_RESULT_ASSETS:
            raise ContractError(f"Send 1 to {MAX_RESULT_ASSETS} ids to remove.")
        wanted = {str(item) for item in ids}
        kept = [
            item
            for item in self.assets
            if not (
                item["id"] in wanted
                and item["kind"] == RESULT_TYPE
                and item["attributes"].get("origin") == f"app:{app}"
            )
        ]
        removed = len(self.assets) - len(kept)
        self.assets[:] = kept
        return {"removed": removed}

    def _route_asset_types(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)
        return resolve_types(self.asset_types)

    def _route_explore(self, request: "_Request") -> dict[str, Any]:
        """The Explorer (``plantcraft_sdk.explore``), over the fake's assets, signals and the
        events written to it."""

        self._reader(request)
        assets = [
            item
            for item in self.assets
            if isinstance(item, dict) and item.get("kind") != RESULT_TYPE
        ]
        signals = [self._signal_payload(item) for item in self.signals]
        query, asset_id = request.query.get("q") or "", request.query.get("asset")
        if query.strip():
            return {"hits": _explore.search(assets, signals, query)}
        if not asset_id:
            return _explore.top(assets)
        found = next((item for item in assets if item["id"] == asset_id), None)
        if found is None:
            raise _Abort(404, "Asset not found.")
        ref = f"asset:{asset_id}"
        kinds: dict[str, dict[str, Any]] = {}
        last: dict[tuple[str, str], tuple[str, str]] = {}
        for event in self.links.events:
            if ref not in event["refs"]:
                continue
            item = kinds.setdefault(
                event["kind"],
                {"kind": event["kind"], "app": event["app"], "count": 0, "last_at": "",
                 "open": 0, "severity": "", "title": event["kind"]},
            )  # fmt: skip
            item.update(count=item["count"] + 1, last_at=event["at"], severity=event["severity"])
            if event.get("key") and event.get("phase") in ("start", "end"):
                last[(event["app"], event["key"])] = (event["phase"], event["kind"])
        for phase, kind in last.values():
            kinds[kind]["open"] += int(phase == "start")
        return _explore.asset_contents(found, assets, signals, events=list(kinds.values()))

    def _route_asset(self, request: "_Request", id: str) -> dict[str, Any]:
        scope = self._scope(self._reader(request))
        found = next((item for item in self.assets if item["id"] == id), None)
        if found is None or (scope is not None and id not in scope[0]):
            raise _Abort(404, "Asset not found.")
        return found

    def _route_signals(self, request: "_Request") -> list[dict[str, Any]]:
        scope = self._scope(self._reader(request))
        needle = (request.query.get("q") or "").strip().lower()
        filters = {key: request.query.get(key) for key in _derived.DERIVED_FIELDS}
        return [
            self._signal_payload(item)
            for item in self.signals
            if (
                not needle or needle in f"{item['id']} {item['name']} {item['description']}".lower()
            )
            and _derived.matches(item, filters)
            and (scope is None or item["id"] in scope[1])
        ]

    def _route_signal(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        self._signal_in_scope(request, id)
        return self._signal_payload(self._signal_or_404(id))

    def _range(self, start: Any, end: Any, step: Any) -> tuple[datetime, datetime, float | None]:
        if isinstance(step, bool) or not (step is None or isinstance(step, int | float | str)):
            raise ContractError("step must be a positive number of seconds.")
        if isinstance(start, bool) or isinstance(end, bool):
            raise ContractError("start and end are ISO 8601 times.")
        if not (start is None or isinstance(start, str)) or not (
            end is None or isinstance(end, str)
        ):
            raise ContractError("start and end are ISO 8601 times.")
        try:
            seconds = None if step in (None, "") else float(step)
        except ValueError as exc:
            raise ContractError("step must be a positive number of seconds.") from exc
        return series_range(start, end, seconds, default_end=self.data_end)

    def _route_series(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        self._signal_in_scope(request, id)
        found = self._signal_or_404(id)["id"]
        query = request.query
        if self.kind(found) == _derived.RUNS_KIND:
            return {"signal": id, "kind": "runs", "runs": self._runs(found, query)}
        start_at, end_at, step = self._range(
            query.get("start"), query.get("end"), query.get("step")
        )
        stamps, values = self._values(found, start_at, end_at, step)
        return {"signal": id, "kind": self.kind(found), "t": stamps, "v": values}

    def _route_series_batch(self, request: "_Request") -> dict[str, Any]:
        self._reader(request)
        payload = request.json()
        if not isinstance(payload, dict):
            raise _Abort(422, "Send a JSON object with signals, start, end and step.")
        signals = payload.get("signals")
        if (
            not isinstance(signals, list)
            or not 1 <= len(signals) <= MAX_BATCH_SIGNALS
            or not all(isinstance(item, str) and 0 < len(item) <= 300 for item in signals)
        ):
            raise _Abort(422, f"signals is a list of 1 to {MAX_BATCH_SIGNALS} signal ids (text).")
        start_at, end_at, step = self._range(
            payload.get("start"), payload.get("end"), payload.get("step")
        )
        batch = BatchBuilder(self.batch_points)
        for signal_id in unique_signals(signals):
            try:
                known = self._known(signal_id)
            except _Abort as abort:
                batch.fail(signal_id, abort.status, str(abort.detail))
                continue
            if known is None:
                batch.fail(signal_id, 404, "Signal not found.")
                continue
            if batch.full:
                batch.postpone(signal_id)
                continue
            found = known["id"]
            if self.kind(found) == _derived.RUNS_KIND:
                latest = self._runs(found, {})
                run = latest[0] if latest else {"run_at": None, "t": [], "v": []}
                batch.add(signal_id, "runs", run["t"], run["v"])
                if batch.series and batch.series[-1]["signal"] == signal_id:
                    batch.series[-1]["run_at"] = run["run_at"]
                continue
            try:
                stamps, values = self._values(found, start_at, end_at, step)
            except ContractError as exc:
                batch.fail(signal_id, 422, str(exc))
                continue
            except _Abort as abort:
                batch.fail(signal_id, abort.status, str(abort.detail))
                continue
            batch.add(signal_id, self.kind(found), stamps, values)
            if payload.get("extremes") is True and step and self.kind(found) == "number":
                band = self._extremes(found, start_at, end_at, step, len(stamps))
                if band is not None and batch.series and batch.series[-1]["signal"] == signal_id:
                    batch.series[-1]["low"], batch.series[-1]["high"] = band
        return batch.payload()

    def _extremes(
        self, signal_id: str, start: datetime, end: datetime, step: float, cells: int
    ) -> tuple[list[Any], list[Any]] | None:
        """Each ``step`` cell's lowest and highest recorded value, as the Historian's
        ``extremes`` (None when the raw values do not fit one read)."""

        try:
            stamps, values = self._values(signal_id, start, end, None)
        except (ContractError, _Abort):
            return None
        numbers = pd.to_numeric(pd.Series(values, dtype=object), errors="coerce").to_numpy(float)
        at = pd.DatetimeIndex(pd.to_datetime(list(stamps), utc=True)).as_unit("ns").asi8 / 1e9
        index = np.floor((at - start.timestamp()) / step).astype(np.int64)
        keep = (index >= 0) & (index < cells) & ~np.isnan(numbers)
        low, high = np.full(cells, np.nan), np.full(cells, np.nan)
        np.fmin.at(low, index[keep], numbers[keep])
        np.fmax.at(high, index[keep], numbers[keep])

        def listed(found: np.ndarray) -> list[Any]:
            return [None if np.isnan(value) else float(value) for value in found]

        return listed(low), listed(high)

    def _route_put_series(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token writes derived series.")
        app = subject[4:]
        items = _derived.parse_derived(request.json())
        for item in items:
            try:
                _derived.check_owner(app, item.signal)
            except _derived.DerivedError as error:
                raise _Abort(error.status, error.detail) from error
        written, errors = 0, []
        for index, item in enumerate(items):
            known = next((s for s in self.signals if s["id"] == item.signal), None)
            if known is not None and known.get("kind") not in (None, item.kind):
                detail = f"{item.signal} holds {known['kind']} values; write {known['kind']} values to it."
                errors.append(
                    {"index": index, "signal": item.signal, "status": 422, "detail": detail}
                )
                continue
            points = self.derived.setdefault(item.signal, {})
            points.update(zip(item.t, item.v, strict=True))
            row = _derived.derived_signal(
                item.signal,
                app=app,
                name=item.name if item.name is not None else (known or {}).get("name"),
                unit=item.unit if item.unit is not None else (known or {}).get("unit"),
                kind=item.kind or "number",
                subject=item.subject or (known or {}).get("subject"),
                result=item.result or (known or {}).get("result"),
                description=(
                    item.description
                    if item.description is not None
                    else (known or {}).get("description")
                ),
                managed_by=(
                    item.managed_by
                    if item.managed_by is not None
                    else (known or {}).get("managed_by", "")
                ),
                retention_days=(
                    item.retention_days
                    if item.retention_days is not None
                    else (known or {}).get("retention_days")
                ),
            )
            if known is None:
                self.signals.append(row)
            else:
                known.update(row)
            written += 1
            if item.kind in _TYPED_KINDS:
                continue
            ordered = sorted(points.items())
            self.series_data[item.signal] = pd.Series(
                [value for _, value in ordered],
                index=parse_times([stamp for stamp, _ in ordered]),
                dtype=object if item.kind == "text" else float,
            )
        return {"written": written, "errors": errors}

    def _runs(self, signal_id: str, query: Mapping[str, Any]) -> list[dict[str, Any]]:
        kept = self.derived_runs.get(signal_id, {})
        newest = sorted(kept, reverse=True)
        run = query.get("run")
        if run not in (None, "", "latest"):
            try:
                at = iso(parse_times([str(run)])[0])
            except (ValueError, TypeError) as error:
                raise ContractError("run is latest or an ISO 8601 run time.") from error
            newest = [stamp for stamp in newest if stamp == at]
        else:
            last = int(query.get("runs") or 1)
            if not 1 <= last <= 50:
                raise ContractError("runs is 1 to 50.")
            newest = newest[:last]
        return [{"run_at": stamp, **copy.deepcopy(kept[stamp])} for stamp in newest]

    def _route_run_list(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        found = self._signal_or_404(id)["id"]
        if self.kind(found) != _derived.RUNS_KIND:
            raise ContractError(f"{id} is not a runs point.")
        limit = int(request.query.get("limit") or 50)
        if not 1 <= limit <= 200:
            raise ContractError("limit is 1 to 200.")
        kept = self.derived_runs.get(found, {})
        runs = [{"run_at": stamp, **kept[stamp]} for stamp in sorted(kept, reverse=True)[:limit]]
        return {
            "signal": id,
            "runs": [
                {
                    "run_at": run["run_at"],
                    "start": run["t"][0] if run["t"] else None,
                    "end": run["t"][-1] if run["t"] else None,
                    "n": len(run["t"]),
                }
                for run in runs
            ],
        }

    def _route_put_series_runs(self, request: "_Request") -> dict[str, Any]:
        app = self._app_caller(request, "Only an app's service token writes derived series.")
        items = _derived.parse_runs(request.json())
        for item in items:
            try:
                _derived.check_owner(app, item.signal)
            except _derived.DerivedError as error:
                raise _Abort(error.status, error.detail) from error
        written, errors = 0, []
        for index, item in enumerate(items):
            known = next((s for s in self.signals if s["id"] == item.signal), None)
            if known is not None and known.get("kind") != _derived.RUNS_KIND:
                detail = f"{item.signal} holds {known.get('kind')} values; write {known.get('kind')} values to it."
                errors.append(
                    {"index": index, "signal": item.signal, "status": 409, "detail": detail}
                )
                continue
            row = _derived.derived_signal(
                item.signal,
                app=app,
                name=item.name if item.name is not None else (known or {}).get("name"),
                unit=item.unit if item.unit is not None else (known or {}).get("unit"),
                kind=_derived.RUNS_KIND,
                subject=item.subject or (known or {}).get("subject"),
                result=item.result or (known or {}).get("result"),
                description=(
                    item.description
                    if item.description is not None
                    else (known or {}).get("description")
                ),
                managed_by=(
                    item.managed_by
                    if item.managed_by is not None
                    else (known or {}).get("managed_by", "")
                ),
            )
            if known is None:
                self.signals.append(row)
            else:
                known.update(row)
            kept = self.derived_runs.setdefault(item.signal, {})
            kept[item.run_at] = {"t": list(item.t), "v": list(item.v)}
            oldest = iso(self.now - timedelta(days=item.keep_days)) if item.keep_days else None
            for stamp in sorted(kept, reverse=True)[item.keep_runs :]:
                kept.pop(stamp)
            for stamp in [stamp for stamp in kept if oldest is not None and stamp < oldest]:
                kept.pop(stamp)
            written += 1
        return {"written": written, "errors": errors}

    def _route_retire_series(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token retires derived series.")
        app = subject[4:]
        body = request.json() or {}
        signals = body.get("signals") if isinstance(body, dict) else None
        if not isinstance(signals, list) or not 1 <= len(signals) <= 500:
            raise ContractError("Send 1 to 500 signals to retire.")
        for signal in signals:
            try:
                _derived.check_owner(app, str(signal))
            except _derived.DerivedError as error:
                raise _Abort(error.status, error.detail) from error
        retired = []
        for signal in dict.fromkeys(str(item) for item in signals):
            known = next((s for s in self.signals if s["id"] == signal), None)
            if known is None:
                continue
            self.signals.remove(known)
            self.derived.pop(signal, None)
            self.derived_runs.pop(signal, None)
            self.series_data.pop(signal, None)
            retired.append(signal)
        return {"retired": retired, "errors": []}

    def _route_value(self, request: "_Request", id: str) -> dict[str, Any]:
        self._reader(request)
        found = self._signal_or_404(id)["id"]
        agg = request.query.get("agg", "last")
        window = request.query.get("window", "1h")
        span = parse_window(window)
        if agg not in AGGREGATIONS:
            raise ContractError(f"Invalid agg: use one of {', '.join(AGGREGATIONS)}.")
        kind = self.kind(found)
        if kind == _derived.RUNS_KIND:
            raise ContractError("A runs point has no value: read its runs.")
        if kind == "text" and agg != "last":
            raise ContractError("A text signal has only agg=last.")
        if kind in _TYPED_KINDS:
            if agg != "last":
                raise ContractError(f"A {kind} point has only agg=last.")
            stamps, typed = self._values(found, self.data_end - span, self.data_end, None)
            return {
                "signal": id,
                "agg": agg,
                "window": window,
                "value": typed[-1] if typed else None,
                "at": stamps[-1] if stamps else iso(self.data_end),
            }
        end_at = self.data_end
        # Long windows are summarized on a coarser grid, as a historian would.
        seconds = span.total_seconds()
        step = None if seconds / self.sample_seconds <= MAX_POINTS else seconds / 10_000
        given = self._given(self.series_data, found)
        if given is not None and len(given) <= MAX_POINTS:
            # A recorded series is read as recorded: the window's own samples, its last included.
            step = None
        stamps, values = self._values(found, end_at - span, end_at, step)
        frame = pd.Series(
            values,
            # Stamps with and without fractional seconds: one fixed format cannot read them.
            index=parse_times(stamps),
            dtype=object if kind == "text" else float,
        )
        result, at = aggregate(frame, agg, kind)
        return {
            "signal": id,
            "agg": agg,
            "window": window,
            "value": result,
            "at": iso(at if at is not None else end_at),
        }

    def _route_audit(self, request: "_Request") -> dict[str, int]:
        claims = self._caller(request)
        payload = request.json()
        if not isinstance(payload, dict):
            raise _Abort(422, "Send a JSON object with action, subject and detail.")
        action = payload.get("action")
        if not isinstance(action, str) or not action.strip():
            raise _Abort(422, "action is required.")
        subject = str(claims.get("sub") or "")
        # A service token always records its own app, as PlantCraft does.
        app_id = subject[4:] if subject.startswith("app:") else payload.get("app")
        entry = {
            "id": len(self.audit_log) + 1,
            "username": subject,
            "app": app_id,
            "action": action,
            "subject": str(payload.get("subject") or ""),
            "detail": payload.get("detail"),
            "at": iso(pd.Timestamp.now(tz="UTC")),
        }
        self.audit_log.append(entry)
        return {"id": entry["id"]}

    # People, groups and notifications (plantcraft_sdk.people) --------------

    def _route_people(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)
        return [
            {
                "username": username,
                "name": user.get("name") or username,
                "role": user.get("role") or "",
                "job_title": user.get("job_title") or "",
                "unit": user.get("unit") or "",
                "groups": [group["id"] for group in self.groups if username in group["members"]],
            }
            for username, user in self.users.items()
        ]

    def _route_groups(self, request: "_Request") -> list[dict[str, Any]]:
        self._reader(request)
        return copy.deepcopy(self.groups)

    def _route_notification_settings(self, request: "_Request") -> dict[str, bool]:
        self._reader(request)
        return {"email": bool(self.email_ready)}

    def _route_notify(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token sends notifications.")
        try:
            body = check_notification(request.json())
        except ContractError as exc:
            raise _Abort(422, str(exc)) from exc
        delivered: list[str] = []
        unknown: list[str] = []
        for ref in body["recipients"]:
            kind, _, name = ref.partition(":")
            group = next((item for item in self.groups if item["id"] == name), None)
            if kind == "user" and name in self.users:
                delivered.append(name)
            elif kind == "group" and group is not None:
                delivered.extend(group["members"])
            else:
                unknown.append(ref)
        delivered = list(dict.fromkeys(delivered))
        self.notifications.append({**body, "app": subject[4:], "delivered": delivered})
        return {"delivered": delivered, "email_queued": 0, "unknown": unknown}

    def _route_resolve_notification(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            raise _Abort(403, "Only an app's service token resolves notifications.")
        try:
            body = check_resolution(request.json())
        except ContractError as exc:
            raise _Abort(422, str(exc)) from exc
        self.resolved_notifications[(subject[4:], body["key"])] = body["note"]
        return {**body, "resolved_at": _links.now_text()}


def _multi(pairs: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """Query pairs by name, repeated names kept in order."""

    found: dict[str, list[str]] = {}
    for key, value in pairs:
        found.setdefault(key, []).append(value)
    return found


@dataclass
class _Request:
    method: str
    path: str
    # Each parameter's last value; ``lists`` keeps every value of a repeated one.
    query: dict[str, str]
    headers: dict[str, str]
    cookies: dict[str, str]
    body: bytes
    lists: dict[str, list[str]] = field(default_factory=dict)

    def json(self) -> Any:
        try:
            return json.loads(self.body or b"null")
        except ValueError as exc:
            raise _Abort(422, "The body is not JSON.") from exc


__all__ = [
    "BASE_URL",
    "DEFAULT_ASSETS",
    "DEFAULT_GROUPS",
    "DEFAULT_SIGNALS",
    "DEFAULT_USERS",
    "FakeLinks",
    "FakePlantCraft",
    "FakeResponse",
    "synthetic",
    "synthetic_text",
]
