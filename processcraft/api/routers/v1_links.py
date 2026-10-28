"""API v1: results, events, runs and schedules, how the apps of the suite link.

``docs/app-standard.md`` (section 6) says what they are for; ``docs/api-v1.md``
("Results, events, runs and schedules") is the contract and
``tests/contract/test_api_v1_links.py`` holds it. The shapes and rules are
``plantcraft_sdk.links``, shared with the client and ``FakePlantCraft``.

Writes come from an app: a service token writes for its own app; a person's
token names the app in each item (or ``?app=`` for schedules) and needs
``editor`` access to it. Reads follow the rule of the plant data (viewers and
up). Nothing here touches a data source.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, Response
from pydantic import BaseModel, Field

from plantcraft_sdk.contract import MAX_PAGE, NEXT_CURSOR, ContractError
from plantcraft_sdk.contributes import FEATURES, ContributionsIn
from plantcraft_sdk.events import CatalogIn, EventCatalog, event_fields
from plantcraft_sdk.links import (
    MAX_READ,
    MAX_SUBJECTS,
    RUN_STATUSES,
    KnowledgeIn,
    LinkError,
    ResultIn,
    RunIn,
    ScheduleIn,
    check_url,
    cutoff_text,
    event_kind,
    item_error,
    now_text,
    own_app_subject,
    parse_body,
    parse_events,
    result_kind,
    split_subject,
    stale_view,
    subjects_param,
    utc_text,
)
from plantcraft_sdk.server.paging import decode_cursor, encode_cursor
from processcraft.api.deps import Runtime
from processcraft.api.identity import Caller, V1Caller, V1Reader, V1Scope
from processcraft.api.routers.v1 import _catalog
from processcraft.auth.suite import suite_apps
from processcraft.db import utc_text as db_utc_text
from processcraft.events.catalog import FLOOD_KIND, PLATFORM_APP, platform_catalog
from processcraft.i18n import t
from processcraft.platform.datalayer import DataLayerError
from processcraft.refs import parse_ref as parse_platform_ref

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)

Short = Annotated[str | None, Query(max_length=100)]
DEFAULT_HOURLY_LIMIT = 1000


def utc_text_now(*, minutes: int = 0) -> str:
    """Now (plus ``minutes``) as the events' ``at`` is written."""

    now = datetime.fromisoformat(db_utc_text().replace("Z", "+00:00"))
    return db_utc_text(now + timedelta(minutes=minutes))


def _http(error: LinkError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail)


def _parse(model: Any, body: Any, *, many: bool = True) -> list[Any]:
    try:
        return parse_body(model, body, many=many)
    except ContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _app_for(caller: Caller, given: str | None) -> str:
    """The app a write belongs to: the service token's own, or one the person edits."""

    if caller.app_id:
        if given and given.strip().lower() != caller.app_id:
            raise LinkError(403, t("A service token writes only for its own app."))
        return caller.app_id
    if not given:
        raise LinkError(422, t("app is required with a person's token."))
    app = given.strip().lower()
    if caller.apps.get(app) != "editor":
        raise LinkError(403, t("You need editor access to {app} to write for it.", app=app))
    return app


def _prefix(app: str) -> str | None:
    return next((item.url for item in suite_apps() if item.id == app), None)


class _Subjects:
    """Checks that subjects exist (the signal catalog is read once per request, if needed).

    A signal subject is stored by its id, ``signal:<source id>:<tag>``; a bare tag
    one source has (``signal:<tag>``, deprecated) is stored under that id.
    """

    def __init__(self, rt: Any):
        self.rt = rt
        self._catalog: Any = None

    def _signals(self) -> Any:
        if self._catalog is None:
            layer = self.rt.datalayer
            # With HistCraft as the data layer, signals are its own: asked one by one.
            self._catalog = _catalog(self.rt) if not layer.manages_sources else _Remote(layer)
        return self._catalog

    def check(self, subject: str) -> str:
        """The subject as stored; raises ``LinkError`` (404) for one PlantCraft does not know."""

        kind, item = split_subject(subject)
        if kind == "asset":
            if self.rt.workspace.assets.get(item) is None:
                raise LinkError(404, f"{t('Asset not found.')} ({subject})")
            return subject
        found, reason = self._signals().lookup(item)
        if found is None:
            raise LinkError(404, f"{reason} ({subject})")
        return f"signal:{found}"

    def named(self, ref: str) -> str:
        """A ``signal:`` reference by its signal's id when it names a known one, else as given."""

        if not ref.startswith("signal:"):
            return ref
        try:
            found = self._signals().find(ref[len("signal:") :])
        except LookupError:
            return ref
        return f"signal:{found}" if found else ref


class _Remote:
    """``SignalCatalog.lookup`` and ``find`` answered by the data layer (HistCraft), memoized."""

    def __init__(self, layer: Any):
        self.layer = layer
        self._seen: dict[str, tuple[str | None, str]] = {}

    def lookup(self, given: str) -> tuple[str | None, str]:
        if given not in self._seen:
            try:
                self._seen[given] = self.layer.lookup(given)
            except DataLayerError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
        return self._seen[given]

    def find(self, given: str) -> str | None:
        return self.lookup(given)[0]


# Results -----------------------------------------------------------------------


@router.put("/results")
def put_results(
    caller: V1Caller,
    rt: Runtime,
    body: Any = Body(None),
) -> dict[str, Any]:
    """Write up to 500 results; each failing item is in ``errors``, the rest are saved."""

    payload = _parse(ResultIn, body)
    subjects = _Subjects(rt)
    now = now_text()
    saved, errors = [], []
    for index, item in enumerate(payload):
        try:
            app = _app_for(caller, item.app)
            subject = subjects.check(item.subject)
            kind = result_kind(item.kind, app)
        except LinkError as error:
            errors.append(item_error(index, item.subject, error.status, error.detail))
            continue
        saved.append(
            {
                **item.model_dump(exclude={"app", "kind"}),
                "subject": subject,
                "app": app,
                "kind": kind,
                "at": item.at or now,
            }
        )
    count = rt.workspace.results.put_results(saved, now=now, cutoff=cutoff_text())
    return {"saved": count, "errors": errors}


def _kind_filter(app: str | None, kind: str | None) -> tuple[str | None, str | None]:
    """``kind=linkcraft.signal_quality`` means app ``linkcraft``, kind ``signal_quality``."""

    if kind and "." in kind:
        owner, _, name = kind.partition(".")
        if app and app != owner:
            return app, "\0"  # matches nothing
        return owner, name
    return app, kind


@router.get("/results")
def results(
    caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    response: Response,
    subject: Annotated[list[str] | None, Query()] = None,
    app: Short = None,
    kind: Short = None,
    under: Annotated[str | None, Query(max_length=400)] = None,
    group: Short = None,
    limit: Annotated[int | None, Query(ge=1, le=MAX_PAGE)] = None,
    cursor: Annotated[str | None, Query(max_length=1200)] = None,
) -> list[dict[str, Any]]:
    """The latest results; ``under`` keeps the results about an asset and the assets under
    it, ``group`` (an asset type, e.g. ``unit``) adds the ancestor of that type to each.

    In pages of at most ``limit`` (``MAX_PAGE``) results by subject, app and kind: when more
    are left the answer has an ``X-Next-Cursor`` header, and ``?cursor=`` reads on. Before
    pages, a list cut at 5,000 said nothing: 1,000 bench loops filled it and the assistant
    never saw the plant's signals (2026-10-27)."""

    wanted = subjects_param(subject)
    if len(wanted) > MAX_SUBJECTS or any(len(item) > 400 for item in wanted):
        raise HTTPException(
            status_code=422,
            detail=t("Ask for at most {count} subjects at once.", count=MAX_SUBJECTS),
        )
    app, kind = _kind_filter(app, kind)
    if wanted:
        named = _Subjects(rt).named
        wanted = list(dict.fromkeys(named(item) for item in wanted))
    size = limit or MAX_PAGE
    apps = _readable(rt, caller)
    rows = rt.workspace.results.results(
        subjects=wanted or None,
        app=app,
        kind=kind,
        limit=size + 1,
        after=_after(cursor),
        apps=apps,
    )
    if len(rows) > size:
        rows = rows[:size]
        last = rows[-1]
        response.headers[NEXT_CURSOR] = encode_cursor(
            json.dumps([last["subject"], last["app"], last["kind"]])
        )
    if not rows and not cursor and len(wanted) == 1 and "," in wanted[0]:
        # Clients before plantcraft-sdk 0.6 joined subjects with commas; read that
        # form only when no subject has the whole text (deprecated, dropped at the freeze).
        parts = subjects_param([part for part in wanted[0].split(",") if part.strip()])
        if 1 < len(parts) <= MAX_SUBJECTS:
            named = _Subjects(rt).named
            parts = list(dict.fromkeys(named(item) for item in parts))
            rows = rt.workspace.results.results(subjects=parts, app=app, kind=kind, apps=apps)
    now = now_text()
    # About assets out of the caller's asset scope: left out (docs/asset-scope.md). A page may
    # then be shorter than ``limit``; the cursor still reads on from where it stopped.
    answer = [stale_view(row, now) for row in rows if scope.subject(row["subject"])]
    if under or group:
        answer = _placed(rt.workspace.assets, answer, under=under, group=group, scope=scope)
    return answer


def _readable(rt: Any, caller: Any) -> set[str] | None:
    """The apps whose results, events, runs, schedules and texts ``caller`` reads: an app
    reads every app's (its token's scopes decide what it may do), a person those of the apps
    they may open (``rt.apps_for``)."""

    return None if caller.app_id is not None else rt.apps_for(caller.username)


def _after(cursor: str | None) -> tuple[str, str, str] | None:
    """The ``(subject, app, kind)`` a results cursor names (``X-Next-Cursor``)."""

    if not cursor:
        return None
    try:
        found = json.loads(decode_cursor(cursor))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=t("Invalid cursor.")) from exc
    if not (isinstance(found, list) and len(found) == 3 and all(isinstance(x, str) for x in found)):
        raise HTTPException(status_code=422, detail=t("Invalid cursor."))
    return (found[0], found[1], found[2])


def _placed(
    assets: Any,
    rows: list[dict[str, Any]],
    *,
    under: str | None,
    group: str | None,
    scope: Any = None,
) -> list[dict[str, Any]]:
    """Results about assets placed in the tree: those under ``under``, each with its ancestor
    of type ``group`` (``None`` when it has none). "Which unit has most loops with problems"
    needs this; per-loop results alone gave the wrong unit (2026-10-26)."""

    if under and (assets.get(under) is None or (scope is not None and not scope.asset(under))):
        raise HTTPException(status_code=404, detail=f"{t('Asset not found.')} ({under})")
    if group and not assets.is_kind(group):
        raise HTTPException(status_code=422, detail=f"{t('Unknown asset type.')} ({group})")
    by_id = {item["asset_id"]: item for item in assets.list()}
    inside = assets.descendants(under) if under else None
    kinds = assets.types.subtypes(group) if group else set()

    def ancestor(asset_id: str) -> dict[str, str] | None:
        seen: set[str] = set()
        found = by_id.get(asset_id)
        while found is not None and found["asset_id"] not in seen:
            if found["kind"] in kinds:
                if scope is not None and not scope.asset(found["asset_id"]):
                    return None  # above the caller's roots: not theirs to name
                return {"id": found["asset_id"], "name": found["name"]}
            seen.add(found["asset_id"])
            found = by_id.get(found["parent_id"]) if found["parent_id"] else None
        return None

    placed = []
    for row in rows:
        kind, item = split_subject(row["subject"])
        if inside is not None and (kind != "asset" or item not in inside):
            continue
        if group:
            row = {**row, "group": ancestor(item) if kind == "asset" else None}
        placed.append(row)
    return placed


@router.get("/results/history")
def result_history(
    caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    subject: Annotated[str, Query(min_length=1, max_length=400)],
    app: Short = None,
    kind: Short = None,
    after: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_READ)] = 100,
) -> list[dict[str, Any]]:
    """Status changes about ``subject`` (last 90 days), oldest first, after ``after``."""

    try:
        after_at = utc_text(after, "after")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    app, kind = _kind_filter(app, kind)
    subject = _Subjects(rt).named(subject)
    if not scope.subject(subject):
        raise HTTPException(status_code=404, detail=t("Not found."))
    return rt.workspace.results.history(
        subject, app=app, kind=kind, after=after_at, limit=limit, apps=_readable(rt, caller)
    )


# Events ------------------------------------------------------------------------


def _event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["event_id"],
        "at": item["at"],
        "app": item["source"],
        "kind": item["kind"],
        "subject": item["subject"],
        "actor": item["actor"],
        "summary": item["summary"],
        "refs": item["refs"],
        "payload": item["payload"],
        "severity": item.get("severity") or "info",
        "key": item.get("key") or "",
        "phase": item.get("phase") or "instant",
        "category": item.get("category") or "",
    }


class _Catalogs:
    """Each app's declared events, read once per request; an undeclared kind is logged once
    and listed in the catalog's ``undeclared`` (a 422 in a later version, docs/api-v1.md)."""

    def __init__(self, rt: Any):
        self.rt = rt
        self._read: dict[str, EventCatalog | None] = {}

    def spec(self, app: str, kind: str) -> Any:
        if app not in self._read:
            declared = self.rt.workspace.events.catalog(app)
            self._read[app] = (
                None if declared is None else EventCatalog(app, CatalogIn(events=declared).events)
            )
        catalog = self._read[app]
        if catalog is None:
            return None
        spec = catalog.spec(kind)
        if spec is None and self.rt.workspace.events.note_undeclared(app, kind):
            logger.warning("%s wrote the event %s, which its app.toml does not declare", app, kind)
        return spec


@router.post("/events", status_code=201)
def post_event(caller: V1Caller, rt: Runtime, body: Any = Body(None)) -> dict[str, Any]:
    """Record what happened, about an asset or a signal: one event, or a list of up to 1,000.

    One object answers the event (an item error is the request's status); a list
    answers ``{"saved", "ids", "errors"}``, the failing items in ``errors``.
    """

    payload, many = _parse_events(body)
    subjects = _Subjects(rt)
    catalogs = _Catalogs(rt)
    items, ids, errors = [], [], []
    for index, item in enumerate(payload):
        try:
            app = _app_for(caller, item.app)
            kind = event_kind(item.kind, app)
            if own_app_subject(item.subject, app):
                subject = item.subject
            else:
                subject = subjects.check(item.subject)
            parse_platform_ref(subject)
            fields = event_fields(item, catalogs.spec(app, kind))
        except LinkError as error:
            if not many:
                raise _http(error) from error
            errors.append(item_error(index, item.subject, error.status, error.detail))
            ids.append(None)
            continue
        except ValueError as exc:
            # A subject the platform's events cannot store; ids follow refs.check_id.
            detail = t("This subject cannot be named in an event yet.")
            if not many:
                raise HTTPException(status_code=422, detail=detail) from exc
            errors.append(item_error(index, item.subject, 422, detail))
            ids.append(None)
            continue
        ids.append(len(items))
        items.append(
            {
                "kind": kind,
                "subject": subject,
                "source": app,
                "actor": caller.username,
                "summary": item.summary,
                "payload": item.payload,
                "refs": [subjects.named(ref) for ref in item.refs],
                **fields,
            }
        )
    items, ids, errors = _within_budget(rt, items, ids, errors, many)
    events = rt.workspace.events.publish_many(items) if items else []
    if not many:
        return _event_or_repeated(events[0], items[0])
    created = [None if place is None else events[place].get("event_id") for place in ids]
    repeated = sum(1 for event in events if event.get("repeated"))
    return {
        "saved": len(events) - repeated,
        "ids": created,
        "errors": errors,
        "repeated": repeated,
    }


def _event_or_repeated(event: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """The event written, or the one already saying it (``repeated``); an ``end`` of a
    condition never opened answers what was sent, with no ``id``."""

    if not event.get("repeated"):
        return _event(event)
    if event.get("event_id"):
        return {**_event(event), "repeated": True}
    return {
        "id": None,
        "at": now_text(),
        "app": item["source"],
        "kind": item["kind"],
        "subject": item["subject"],
        "actor": item["actor"],
        "summary": item["summary"],
        "refs": [item["subject"]],
        "payload": item["payload"] or {},
        "severity": item.get("severity") or "info",
        "key": item.get("key") or "",
        "phase": item.get("phase") or "instant",
        "category": item.get("category") or "",
        "repeated": True,
    }


def hourly_limit() -> int:
    """Events an app may write in an hour (``PLANTCRAFT_EVENT_HOURLY_LIMIT``, default 1,000;
    ``0``: no limit). Ends of conditions always pass."""

    raw = os.environ.get("PLANTCRAFT_EVENT_HOURLY_LIMIT", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_HOURLY_LIMIT
    except ValueError:
        return DEFAULT_HOURLY_LIMIT


def _within_budget(
    rt: Any,
    items: list[dict[str, Any]],
    ids: list[int | None],
    errors: list[dict[str, Any]],
    many: bool,
) -> tuple[list[dict[str, Any]], list[int | None], list[dict[str, Any]]]:
    """The items an app may still write this hour; the others become 429 errors, and the
    first refusal of the hour is told once as ``processcraft.events.flood``."""

    limit = hourly_limit()
    if not limit or not items:
        return items, ids, errors
    app = items[0]["source"]
    start = utc_text_now(minutes=-60)
    used = rt.workspace.events.count_since(app, start)
    kept: list[dict[str, Any]] = []
    places: dict[int, int] = {}
    refused = 0
    for place, item in enumerate(items):
        if item.get("phase") == "end" or used < limit:
            if item.get("phase") != "end":
                used += 1
            places[place] = len(kept)
            kept.append(item)
        else:
            refused += 1
    if not refused:
        return items, ids, errors
    detail = t(
        "{app} wrote over {limit} events in the last hour: publish when something changes,"
        " not to repeat that it is still the same.",
        app=app,
        limit=limit,
    )
    if not many:
        _tell_flood(rt, app, limit)
        raise HTTPException(status_code=429, detail=detail)
    new_ids: list[int | None] = []
    for index, place in enumerate(ids):
        if place is None:
            new_ids.append(None)
        elif place in places:
            new_ids.append(places[place])
        else:
            new_ids.append(None)
            errors.append(item_error(index, items[place]["subject"], 429, detail))
    _tell_flood(rt, app, limit)
    return kept, new_ids, errors


def _tell_flood(rt: Any, app: str, limit: int) -> None:
    """``processcraft.events.flood`` about the app, at most once an hour (its own budget is
    PlantCraft's, never the app's)."""

    events = rt.workspace.events
    start = utc_text_now(minutes=-60)
    recent = events.listing(ref=f"app:{app}", kind=FLOOD_KIND, limit=1)
    if recent and recent[-1]["at"] >= start:
        return
    events.publish(
        FLOOD_KIND,
        f"app:{app}",
        source=PLATFORM_APP,
        actor="system",
        summary=t(
            "{app} wrote over {limit} events in an hour; the rest were refused.",
            app=app,
            limit=limit,
        ),
        payload={"app": app, "limit": limit},
        severity="warning",
        category="system",
    )


def _parse_events(body: Any) -> tuple[list[Any], bool]:
    try:
        return parse_events(body)
    except ContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/events")
def events(
    caller: V1Reader,
    rt: Runtime,
    ref: Annotated[str | None, Query(max_length=400)] = None,
    kind: Annotated[str | None, Query(max_length=120)] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_READ)] = 100,
    key: Annotated[str | None, Query(max_length=200)] = None,
) -> list[dict[str, Any]]:
    """Events oldest first: after the event id ``after``, else the latest ``limit``; ``key``
    keeps one condition's."""

    if ref is not None:
        ref = _Subjects(rt).named(ref)
    found = rt.workspace.events.listing(
        ref=ref,
        kind=kind,
        after_id=after,
        limit=limit,
        key=key,
        hidden=rt.hidden_sources(caller.username) if caller.app_id is None else (),
    )
    if caller.app_id is None:
        # A person (and their assistant) reads only the events of what they may see.
        found = rt.events_for(caller.username, found)
    return [_event(item) for item in found]


@router.put("/events/catalog")
def put_event_catalog(caller: V1Caller, rt: Runtime, body: Any = Body(None)) -> dict[str, Any]:
    """The events an app declares (its ``[[publishes.events]]``), replaced; sent by the SDK
    when the app starts."""

    try:
        catalog = CatalogIn.model_validate(body if isinstance(body, dict) else {"events": body})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_first_error(exc)) from exc
    try:
        app = _app_for(caller, catalog.app)
    except LinkError as error:
        raise _http(error) from error
    if app == PLATFORM_APP:
        raise HTTPException(status_code=403, detail=t("PlantCraft's own events are not sent."))
    events = [spec.model_dump(mode="json", exclude_none=True) for spec in catalog.events]
    rt.workspace.events.put_catalog(app, events)
    return {"app": app, "events": len(events)}


@router.get("/events/catalog")
def event_catalog(_caller: V1Reader, rt: Runtime) -> list[dict[str, Any]]:
    """Every declared event, PlantCraft's first: ``[{"app", "name", "events", "undeclared"}]``,
    each event with its full ``kind``."""

    names = {item.id: item.name for item in suite_apps()}
    out = [
        {
            "app": PLATFORM_APP,
            "name": "PlantCraft",
            "events": platform_catalog(),
            "undeclared": [],
            "updated_at": None,
        }
    ]
    for app, catalog in rt.workspace.events.catalogs().items():
        out.append(
            {
                "app": app,
                "name": names.get(app, app),
                "events": [{"kind": f"{app}.{spec['name']}", **spec} for spec in catalog["events"]],
                "undeclared": catalog["undeclared"],
                "updated_at": catalog["updated_at"],
            }
        )
    return out


# What each app adds to PlantCraft (docs/app-standard.md, section 4b) ---------------------


@router.put("/contributions")
def put_contributions(caller: V1Caller, rt: Runtime, body: Any = Body(None)) -> dict[str, Any]:
    """What an app adds (its ``[contributes]``, ``[[publishes.series]]`` and events), replaced
    whole; sent by the SDK when the app starts. The events go to the catalog as
    ``PUT /events/catalog`` would put them."""

    try:
        given = ContributionsIn.model_validate(body if isinstance(body, dict) else {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=_first_error(exc)) from exc
    try:
        app = _app_for(caller, given.app)
    except LinkError as error:
        raise _http(error) from error
    if app == PLATFORM_APP:
        raise HTTPException(status_code=403, detail=t("PlantCraft declares nothing to itself."))
    stored = rt.contributions.put(app, given)
    events = [spec.model_dump(mode="json", exclude_none=True) for spec in given.events]
    rt.workspace.events.put_catalog(app, events)
    return {"app": app, "events": len(events), "unknown": stored.get("unknown", [])}


@router.get("/contributions")
def contributions(_caller: V1Reader, rt: Runtime) -> dict[str, Any]:
    """What every installed app adds, in the suite's order: ``{"features", "apps": [{"app",
    "name", "version", "contributes", "series", "unknown", "updated_at"}]}``."""

    installed = rt.suite_apps()
    names = {item.id: item.name for item in installed}
    items = rt.contributions.listing([item.id for item in installed])
    return {
        "features": list(FEATURES),
        "apps": [{**item, "name": names.get(item["app"], item["app"])} for item in items],
    }


@router.get("/contributions/settings")
def contribution_settings(caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """The calling app's installation settings (``[[contributes.settings]]``), as the
    administrator set them in Settings › Apps, else their defaults, secrets included: an app's
    service token only. ``{"app", "values": {key: value}}``."""

    if not caller.app_id:
        raise HTTPException(status_code=403, detail=t("Only an app reads its settings."))
    row = rt.contributions.get(caller.app_id) or {}
    specs = (row.get("contributes") or {}).get("settings", [])
    return {"app": caller.app_id, "values": rt.app_settings.values(caller.app_id, specs)}


def _first_error(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        first = errors(include_url=False)[0]
        where = ".".join(str(part) for part in first.get("loc", ()))
        message = str(first.get("msg", "invalid")).removeprefix("Value error, ")
        return f"{where}: {message}" if where else message
    return str(exc)


# Runs and schedules ------------------------------------------------------------


@router.put("/runs")
def put_runs(
    caller: V1Caller,
    rt: Runtime,
    body: Any = Body(None),
) -> dict[str, Any]:
    """Write up to 500 runs (one per app and run id); failing items are in ``errors``."""

    payload = _parse(RunIn, body)
    subjects = _Subjects(rt)
    saved, errors = [], []
    for index, item in enumerate(payload):
        try:
            app = _app_for(caller, item.app)
            url = check_url(item.url, _prefix(app))
            cancel = check_url(item.cancel, _prefix(app))
            if cancel and not cancel.startswith("/"):
                raise LinkError(422, t("cancel is a path under the app's prefix."))
            named = list(dict.fromkeys(subjects.check(subject) for subject in item.subjects))
        except LinkError as error:
            errors.append(item_error(index, item.id, error.status, error.detail))
            continue
        row = item.model_dump(exclude={"app"})
        saved.append({**row, "app": app, "url": url, "cancel": cancel, "subjects": named})
    ended = _ended_runs(rt, saved)
    count = rt.workspace.results.put_runs(saved, now=now_text(), cutoff=cutoff_text())
    for run in ended:
        _tell_starter(rt, run)
    return {"saved": count, "errors": errors}


# A run someone started that ends faster than this only turns the Queue button green.
RUN_NOTICE_SECONDS = 60


def _ended_runs(rt: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The runs a person started that this write finishes (failed, or done after a minute):
    the platform tells that person, so apps never have to (docs/quick-access.md)."""

    ended = []
    for item in items:
        if not item.get("by") or item["status"] not in ("done", "failed"):
            continue
        before = rt.workspace.results.run(item["app"], item["id"])
        if before and before["status"] in ("done", "failed", "cancelled"):
            continue
        if item["status"] == "done":
            try:
                start = datetime.fromisoformat(str(item["started_at"]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(item["finished_at"]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if (end - start).total_seconds() < RUN_NOTICE_SECONDS:
                continue
        ended.append(item)
    return ended


def _tell_starter(rt: Any, run: dict[str, Any]) -> None:
    name = run["name"] or run["id"]
    failed = run["status"] == "failed"
    try:
        rt.notifications.notify(
            run["app"],
            rt.app_names().get(run["app"], run["app"]),
            recipients=[f"user:{run['by']}"],
            title=(t("Failed: {name}", name=name) if failed else t("Done: {name}", name=name))[
                :200
            ],
            text=run.get("summary") or "",
            priority="high" if failed else "low",
            url=run["url"] if (run.get("url") or "").startswith("/") else None,
            key=f"run:{run['id']}",
            category="run",
        )
    except (PermissionError, ValueError):
        logger.warning("could not tell %s about run %s/%s", run["by"], run["app"], run["id"])


@router.get("/runs")
def runs(
    caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    app: Short = None,
    status: Annotated[str | None, Query(max_length=20)] = None,
    subject: Annotated[str | None, Query(max_length=400)] = None,
    by: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_READ)] = 100,
) -> list[dict[str, Any]]:
    if status is not None and status not in RUN_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=t("Invalid status: use one of {statuses}.", statuses=", ".join(RUN_STATUSES)),
        )
    if subject is not None:
        subject = _Subjects(rt).named(subject)
    found = rt.workspace.results.runs(
        app=app, status=status, subject=subject, by=by, limit=limit, apps=_readable(rt, caller)
    )
    return [run for run in found if scope.subject(str(run.get("subject") or ""))]


# The suite's Queue (docs/quick-access.md) ------------------------------------------

QUEUE_MINE = 20
QUEUE_RUNNING = 30
QUEUE_KEEP_HOURS = 24


@router.get("/queue")
def queue(caller: V1Reader, rt: Runtime, scope: V1Scope) -> dict[str, Any]:
    """What the Queue panel lists for this person, from the runs apps write: ``mine`` (what
    they started, waiting or running, and what ended in the last 24 hours) and ``running``
    (everything waiting or running in the apps they may open), newest first.
    ``{"me", "mine", "running"}``; each run as ``GET /api/v1/runs`` gives it, with ``app_name``."""

    if caller.app_id is not None:
        raise HTTPException(status_code=403, detail=t("The queue panel belongs to a person."))
    names = rt.app_names()
    allowed = set(caller.apps)

    def shown(run: dict[str, Any]) -> dict[str, Any]:
        return {**run, "app_name": names.get(run["app"], run["app"])}

    active = [
        run
        for status in ("running", "queued")
        for run in rt.workspace.results.runs(status=status, limit=MAX_READ)
        if run["app"] in allowed and scope.subject(str(run.get("subject") or ""))
    ]
    since = utc_text_now(minutes=-QUEUE_KEEP_HOURS * 60)
    mine = [
        run
        for run in rt.workspace.results.runs(by=caller.username, limit=100)
        if run["app"] in allowed
        and (run["status"] in ("running", "queued") or str(run["updated_at"]) >= since)
    ]
    return {
        "me": caller.username,
        "mine": [shown(run) for run in mine[:QUEUE_MINE]],
        "running": [shown(run) for run in active[:QUEUE_RUNNING]],
    }


# Knowledge ---------------------------------------------------------------------


class KnowledgeDelete(BaseModel):
    refs: list[Annotated[str, Field(max_length=400)]] = Field(min_length=1, max_length=500)
    app: Annotated[str | None, Field(max_length=40)] = None


@router.put("/knowledge")
def put_knowledge(
    caller: V1Caller,
    rt: Runtime,
    body: Any = Body(None),
) -> dict[str, Any]:
    """Write up to 500 texts (one per app and ref) that specialists read as context."""

    payload = _parse(KnowledgeIn, body)
    saved, errors = [], []
    for index, item in enumerate(payload):
        try:
            app = _app_for(caller, item.app)
            url = check_url(item.url, _prefix(app))
            parse_platform_ref(item.ref)
            for subject in item.subjects:
                parse_platform_ref(subject)
        except LinkError as error:
            errors.append(item_error(index, item.ref, error.status, error.detail))
            continue
        except ValueError as exc:
            errors.append(item_error(index, item.ref, 422, str(exc)))
            continue
        saved.append({**item.model_dump(exclude={"app"}), "app": app, "url": url})
    count = rt.workspace.knowledge.put(saved, now=now_text(), cutoff=cutoff_text())
    return {"saved": count, "errors": errors}


@router.post("/knowledge/delete")
def delete_knowledge(payload: KnowledgeDelete, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """Remove the app's texts about these refs (a protocol deleted in the app)."""

    try:
        app = _app_for(caller, payload.app)
    except LinkError as error:
        raise _http(error) from error
    return {"deleted": rt.workspace.knowledge.delete(app, payload.refs)}


@router.get("/knowledge")
def knowledge(
    caller: V1Reader,
    rt: Runtime,
    ref: Annotated[str | None, Query(max_length=400)] = None,
    q: Annotated[str, Query(max_length=200)] = "",
    app: Short = None,
    limit: Annotated[int, Query(ge=1, le=MAX_READ)] = 50,
) -> list[dict[str, Any]]:
    """Texts about ``ref`` (written for it or naming it), else those matching ``q``."""

    apps = _readable(rt, caller)
    if ref is not None:
        rows = rt.workspace.knowledge.about(ref, apps=apps)
        return [item for item in rows if app is None or item["app"] == app][:limit]
    return rt.workspace.knowledge.search(q, apps=apps, app=app, limit=limit)


@router.put("/schedules")
def put_schedules(
    caller: V1Caller,
    rt: Runtime,
    app: Annotated[str | None, Query(max_length=40)] = None,
    body: Any = Body(None),
) -> dict[str, Any]:
    """Replace the app's schedules; items that fail are in ``errors`` and left out."""

    payload = _parse(ScheduleIn, body)
    try:
        owner = _app_for(caller, app)
    except LinkError as error:
        raise _http(error) from error
    ids = [item.id for item in payload]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail=t("Each schedule id appears once."))
    prefix = _prefix(owner)
    kept, errors = [], []
    for index, item in enumerate(payload):
        try:
            url = check_url(item.url, prefix)
            for subject in item.subjects:
                split_subject(subject)
        except LinkError as error:
            errors.append(item_error(index, item.id, error.status, error.detail))
            continue
        subjects = list(dict.fromkeys(item.subjects))
        kept.append({**item.model_dump(), "url": url, "subjects": subjects})
    count = rt.workspace.results.replace_schedules(owner, kept, now=now_text())
    return {"saved": count, "errors": errors}


@router.get("/schedules")
def schedules(caller: V1Reader, rt: Runtime, app: Short = None) -> list[dict[str, Any]]:
    return rt.workspace.results.schedules(app=app, apps=_readable(rt, caller))
