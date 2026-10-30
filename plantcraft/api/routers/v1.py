"""HTTP routes: API v1, the contract between PlantCraft and the apps of the suite.

``docs/api-v1.md`` is the contract; ``tests/contract/test_api_v1.py`` holds it.
Callers authenticate with a signed token (``Authorization: Bearer`` or the
``processcraft_token`` cookie), not the session: this router is mounted
without the session guard. Plant data is read only: no route here writes to a
data source. Signals and series come from the data layer
(``plantcraft.platform.datalayer``): PlantCraft's sources, or HistCraft; the
only write, ``PUT /api/v1/series``, stores an app's derived series there.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StringConstraints

from plantcraft.api.deps import Runtime, action_visibility, claims_marks_owner
from plantcraft.api.feed import inbox_notices, marked_unread_chats, visit_reads
from plantcraft.api.identity import (
    READ_LEVELS,
    V1Caller,
    V1Reader,
    V1Scope,
    issue_service_token,
    refresh_browser_token,
)
from plantcraft.auth.public_demo import public_demo
from plantcraft.config import plant_timezone
from plantcraft.i18n import t
from plantcraft.platform.datalayer import DataLayerError
from plantcraft.platform.signals import SignalCatalog
from plantcraft.platform.signals import signal_id as make_signal_id
from plantcraft_sdk.assets import MAX_RESULT_ASSETS, RESULT_TYPE, parse_result_assets
from plantcraft_sdk.contract import (
    MAX_BATCH_SIGNALS,
    SERVICE_TOKEN_SECONDS,
    USER_TOKEN_SECONDS,
    ContractError,
    subject_digest,
)
from plantcraft_sdk.contributes import FEATURES
from plantcraft_sdk.derived import DerivedError, check_owner, parse_derived, parse_runs
from plantcraft_sdk.server.paging import MAX_PAGE, list_response

router = APIRouter(prefix="/api/v1")
JSON = "application/json"


class ServiceTokenRequest(BaseModel):
    app: str = Field(min_length=1, max_length=40)
    key: str = Field(min_length=1, max_length=200)


class AuditEntry(BaseModel):
    action: str = Field(min_length=1, max_length=120)
    subject: str = Field(default="", max_length=300)
    detail: Any = None
    # Which app recorded it; service tokens name their app themselves.
    app: str | None = Field(default=None, max_length=40)


SignalId = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class SeriesBatchRequest(BaseModel):
    signals: list[SignalId] = Field(min_length=1, max_length=MAX_BATCH_SIGNALS)
    start: str | None = Field(default=None, max_length=64)
    end: str | None = Field(default=None, max_length=64)
    step: float | None = None


def _unprocessable(error: ContractError) -> HTTPException:
    return HTTPException(status_code=422, detail=str(error))


# Identity ------------------------------------------------------------------------


@router.get("/auth/keys")
def keys(rt: Runtime) -> dict[str, Any]:
    return rt.tokens.jwks()


@router.get("/auth/revoked")
def revoked(rt: Runtime) -> dict[str, Any]:
    """Tokens ended before they expire, for apps that verify offline (``REVOKED_PATH``).

    Public like the keys: people appear only as the SHA-256 of their username, and an entry is
    listed only while a token from before it could still be alive.
    """

    now = time.time()
    return {
        "users": [
            {"sub_sha256": subject_digest(username), "not_before": stamp}
            for username, stamp in rt.workspace.users.revoked_since(now - USER_TOKEN_SECONDS)
        ],
        "keys": [
            {"key_id": key_id, "revoked_at": stamp}
            for key_id, stamp in rt.workspace.app_keys.revoked_since(now - SERVICE_TOKEN_SECONDS)
        ],
    }


@router.post("/auth/token")
def renew_token(request: Request, response: Response, rt: Runtime) -> dict[str, str]:
    """A fresh user token for the browser's session (also set as the ``processcraft_token`` cookie)."""

    grant = refresh_browser_token(request, response, rt)
    if grant is None:
        raise HTTPException(status_code=401, detail=t("Session expired. Sign in again."))
    return grant


@router.post("/auth/service-token")
def service_token(payload: ServiceTokenRequest, rt: Runtime) -> dict[str, str]:
    app_id = payload.app.strip().lower()
    record = rt.workspace.app_keys.verify(app_id, payload.key)
    if record is None:
        raise HTTPException(status_code=401, detail=t("Unknown app or key."))
    return issue_service_token(rt, app_id, record["key_id"])


@router.get("/me")
def me(caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    # Where this person opens data in a notebook, or None (off, or no read access).
    notebooks = rt.workspace.notebooks.enabled() and caller.level in READ_LEVELS
    return {
        "username": caller.username,
        "name": caller.name,
        "level": caller.level,
        "apps": caller.apps,
        "notebooks_url": "/notebooks" if notebooks and not caller.app_id else None,
    }


@router.get("/installation")
def installation(_caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """The installation's id (which plant or site this is, stable for good), its time zone
    (the "local" every app's schedules and screens mean) and what this PlantCraft draws for
    apps (``features``: the tables of ``[contributes]``)."""

    return {
        "id": rt.workspace.installation.installation_id(),
        "time_zone": plant_timezone().key,
        "features": list(FEATURES),
    }


@router.get("/apps")
def apps(caller: V1Caller, rt: Runtime) -> list[dict[str, Any]]:
    """``PLANTCRAFT_APPS`` and the apps installed from the Apps page (docs/app-package.md)."""

    return [
        {
            "id": app.id,
            "name": app.name,
            "url": app.url,
            "access": caller.apps[app.id],
            "version": app.version,
        }
        for app in rt.suite_apps()
        if app.id in caller.apps
    ]


@router.get("/inbox")
def inbox(caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """A person's unread chat messages, unread notifications and open actions: the badge of the
    suite's messages button (chats and notifications together)."""

    if caller.app_id is not None:
        raise HTTPException(status_code=403, detail=t("The inbox belongs to a person."))
    if caller.level not in READ_LEVELS:
        raise HTTPException(status_code=403, detail=t("Your access is limited to dashboards."))
    owner = claims_marks_owner(caller.username, caller.claims)
    unread, urgent = inbox_notices(rt, caller.username, owner)
    return {
        # Chats only: apps' notifications are counted apart, with their own read marks.
        "unread_messages": rt.workspace.messages.unread_total(
            caller.username, chats_only=True, read_upto=visit_reads(rt, owner)
        )
        + marked_unread_chats(rt, caller.username, owner),
        "unread_notifications": unread,
        # The newest unread critical or high notification of the last hour, for the pop-up.
        "urgent_notification": urgent,
        "open_actions": rt.workspace.actions.open_count(caller.username),
        "messages_url": "/messages",
        "actions_url": "/actions",
    }


ACTION_FIELDS = (
    "action_id",
    "title",
    "status",
    "status_label",
    "priority",
    "priority_label",
    "owner",
    "owner_name",
    "group_id",
    "group_name",
    "due_at",
    "overdue",
    "refs",
    "created_at",
    "updated_at",
    "completed_at",
)


@router.get("/actions")
def actions(
    caller: V1Reader,
    rt: Runtime,
    ref: Annotated[str | None, Query(max_length=400)] = None,
    status: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """Follow-up actions, those about ``ref`` (``asset:<id>``) when given: an app shows what was
    decided about the asset it is showing (docs/collaboration.md). Read only. A person's token
    reads the actions that person sees; an app's service token reads them all."""

    visible = None if caller.app_id is not None else action_visibility(rt, caller.username)
    items = rt.workspace.actions.list(
        statuses=status or None, ref=ref, limit=limit, visible=visible
    )
    return {
        "items": [{key: item.get(key) for key in ACTION_FIELDS} for item in items],
        "actions_url": "/actions",
    }


# Assets ---------------------------------------------------------------------------


def _assets(rt: Any) -> list[dict[str, Any]]:
    """Every asset with its type path, record, relations and signals by role.

    A handful of queries for the whole tree, whatever its size.
    """

    store = rt.workspace.assets
    sources = store.binding_sources()
    roles: dict[str, dict[str, str]] = {}
    for tag, uses in store.signal_assets().items():
        # The id names the source the binding records (filled by the platform at start).
        found = make_signal_id(sources.get(tag) or rt.platform.sources.source_of(tag), tag)
        for use in uses:
            if use["role"]:
                roles.setdefault(use["asset_id"], {}).setdefault(use["role"], found)
    values = store.all_attributes()
    relations = store.outgoing()
    paths: dict[str, list[str]] = {}
    found = []
    for item in store.list():
        kind = item["kind"]
        if kind not in paths:
            paths[kind] = store.types.path(kind)
        found.append(
            {
                "id": item["asset_id"],
                "name": item["name"],
                "kind": kind,
                "type_path": paths[kind],
                "parent_id": item["parent_id"],
                "attributes": {
                    **values.get(item["asset_id"], {}),
                    "description": item.get("description") or "",
                    "kind_label": item.get("kind_label") or kind,
                    "origin": item.get("origin") or "",
                },
                "signals": roles.get(item["asset_id"], {}),
                "relations": relations.get(item["asset_id"], []),
            }
        )
    return found


Limit = Annotated[int | None, Query(ge=1, le=MAX_PAGE)]
Cursor = Annotated[str | None, Query(max_length=400)]


@router.get("/assets", response_model=list[dict[str, Any]])
def assets(
    request: Request,
    _caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    kind: str | None = Query(default=None, max_length=60),
    type: str | None = Query(default=None, max_length=64),
    parent_id: str | None = Query(default=None, max_length=200),
    results: bool = False,
    limit: Limit = None,
    cursor: Cursor = None,
) -> Response:
    """``kind`` is the exact type; ``type`` also takes its subtypes. Result assets (what apps
    record about assets) come only with ``results=true`` or when asked by type. ``limit`` and
    ``cursor`` answer it in pages by id; an ``ETag`` answers a list that did not change with
    304 (``plantcraft_sdk.server.paging``)."""

    return list_response(
        request,
        _scoped(
            scope,
            _filtered_assets(rt, kind=kind, type=type, parent_id=parent_id, results=results),
        ),
        limit=limit,
        cursor=cursor,
    )


def _scoped(scope: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The assets in the caller's asset scope: a root's parent reads as none, relations to
    assets out of it are left out (docs/asset-scope.md)."""

    if scope.everything:
        return items
    return [
        {
            **item,
            "parent_id": item["parent_id"] if scope.asset(item["parent_id"]) else None,
            "relations": [
                relation for relation in item["relations"] if scope.asset(relation.get("to"))
            ],
        }
        for item in items
        if scope.asset(item["id"])
    ]


def _filtered_assets(
    rt: Any, *, kind: str | None, type: str | None, parent_id: str | None, results: bool
) -> list[dict[str, Any]]:
    wanted = rt.workspace.assets.types.subtypes(type) if type is not None else None
    results = results or RESULT_TYPE in (kind, type)
    return [
        item
        for item in _assets(rt)
        if (results or item["kind"] != RESULT_TYPE)
        and (kind is None or item["kind"] == kind)
        and (wanted is None or item["kind"] in wanted)
        and (parent_id is None or item["parent_id"] == parent_id)
    ]


@router.put("/assets/results")
def put_result_assets(caller: V1Caller, rt: Runtime, body: Any = Body(None)) -> dict[str, int]:
    """An app's whole set of result assets (``{"assets": [...]}``, see ``parse_result_assets``).

    Only a service token, for its own app (403 otherwise); a broken item makes the request a
    422 and nothing is written. Results no longer listed are ended, not removed.
    ``{"saved", "ended"}``.
    """

    app_id = caller.app_id
    if app_id is None:
        raise HTTPException(
            status_code=403, detail=t("Only an app's service token writes result assets.")
        )
    try:
        items = parse_result_assets(app_id, body)
        return rt.workspace.assets.sync_results(app_id, items, actor=f"app:{app_id}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ResultRemove(BaseModel):
    ids: list[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=MAX_RESULT_ASSETS
    )


@router.post("/assets/results/remove")
def remove_result_assets(payload: ResultRemove, caller: V1Caller, rt: Runtime) -> dict[str, int]:
    """An app removes result assets of its own (``{"ids": [...]}``); others' ids are skipped.
    Their points stay in the Historian until their retention ends. ``{"removed"}``."""

    app_id = caller.app_id
    if app_id is None:
        raise HTTPException(
            status_code=403, detail=t("Only an app's service token removes result assets.")
        )
    ids = list(dict.fromkeys(payload.ids))
    return {"removed": rt.workspace.assets.remove_results(app_id, ids)}


@router.get("/assets/{asset_id:path}")
def asset(asset_id: str, _caller: V1Reader, rt: Runtime, scope: V1Scope) -> dict[str, Any]:
    found = next((item for item in _scoped(scope, _assets(rt)) if item["id"] == asset_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    return found


@router.get("/asset-types")
def asset_types(_caller: V1Reader, rt: Runtime) -> list[dict[str, Any]]:
    """The type catalog with inherited attributes and roles resolved."""

    return rt.workspace.assets.types.all_resolved()


# Signals -------------------------------------------------------------------------
#
# The caller is checked here; the data layer answers (``plantcraft.platform.datalayer``):
# PlantCraft's own sources, or HistCraft when ``HISTCRAFT_URL`` is set.


def _catalog(rt: Any) -> SignalCatalog:
    """The signals PlantCraft knows, by API v1 id (``<source id>:<tag>``)."""

    return rt.platform.signal_catalog()


def _require_signal(scope: Any, signal_id: str) -> None:
    """A signal out of the caller's asset scope is not there for them (docs/asset-scope.md)."""

    if not scope.signal(signal_id):
        raise HTTPException(status_code=404, detail=t("Signal not found."))


def _answer(call: Any, *args: Any, **kwargs: Any) -> Any:
    """The data layer's answer; its failures as the HTTP status they carry."""

    try:
        return call(*args, **kwargs)
    except DataLayerError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


@router.get("/signals")
def signals(
    request: Request,
    _caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    q: str = Query(default="", max_length=200),
    app: str | None = Query(default=None, max_length=40),
    subject: str | None = Query(default=None, max_length=300),
    result: str | None = Query(default=None, max_length=60),
    limit: Limit = None,
    cursor: Cursor = None,
) -> Any:
    """Every signal; ``app``, ``subject`` and ``result`` keep the derived signals that have them.
    ``limit`` and ``cursor`` answer it in pages by id; an ``ETag`` answers a list that did not
    change with 304."""

    found = _answer(rt.datalayer.signals, q, app=app, subject=subject, result=result)
    if not scope.everything:
        found = [item for item in found if scope.signal_item(item)]
    return list_response(request, found, limit=limit, cursor=cursor)


@router.get("/signals/{signal_id:path}/series")
def series(
    signal_id: str,
    _caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    start: str | None = Query(default=None, max_length=64),
    end: str | None = Query(default=None, max_length=64),
    step: float | None = Query(default=None),
    run: str | None = Query(default=None, max_length=64),
    runs: int | None = Query(default=None, ge=1, le=50),
) -> Any:
    """Recorded values, or one mean (text: the last label) per ``step`` seconds; at most
    200,000 points. ``signal`` in the answer is the id as asked. A runs point answers
    ``{"signal", "kind": "runs", "runs": [{"run_at", "t", "v"}]}``, newest first: the run at
    ``run`` (``latest`` by default, or its ISO time) or the ``runs`` newest."""

    _require_signal(scope, signal_id)
    options = {"run": run, "runs": runs}
    raw = getattr(rt.datalayer, "series_raw", None)
    if raw is not None:
        # The Historian's JSON as it came: never parsed and written again here.
        return Response(_answer(raw, signal_id, start, end, step, **options), media_type=JSON)
    # Written straight to JSON: long lists skip FastAPI's per-item encoder.
    return JSONResponse(_answer(rt.datalayer.series, signal_id, start, end, step, **options))


@router.get("/signals/{signal_id:path}/runs")
def run_list(
    signal_id: str,
    _caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """The executions a runs point keeps: ``{"signal", "runs": [{"run_at", "start", "end",
    "n"}]}``, newest first; 422 for another kind."""

    _require_signal(scope, signal_id)
    return _answer(rt.datalayer.run_list, signal_id, limit)


@router.post("/series")
def series_batch(
    payload: SeriesBatchRequest, _caller: V1Reader, rt: Runtime, scope: V1Scope
) -> Any:
    """Many signals' series in one request and one source read; each failure is listed
    in ``errors`` (404, 422, 502, or 413 when the request ran out of points)."""

    hidden = [item for item in payload.signals if not scope.signal(item)]
    if hidden:
        # Signals out of the caller's asset scope answer 404, as unknown ones do.
        allowed = [item for item in payload.signals if scope.signal(item)]
        answer: dict[str, Any] = {"series": [], "errors": []}
        if allowed:
            answer = _answer(
                rt.datalayer.series_batch, allowed, payload.start, payload.end, payload.step
            )
        missing = [
            {"signal": item, "status": 404, "detail": t("Signal not found.")}
            for item in dict.fromkeys(hidden)
        ]
        return JSONResponse({**answer, "errors": [*answer.get("errors", []), *missing]})
    args = (payload.signals, payload.start, payload.end, payload.step)
    raw = getattr(rt.datalayer, "series_batch_raw", None)
    if raw is not None:
        return Response(_answer(raw, *args), media_type=JSON)
    return JSONResponse(_answer(rt.datalayer.series_batch, *args))


@router.put("/series")
def put_series(caller: V1Caller, rt: Runtime, body: Any = Body(None)) -> dict[str, Any]:
    """Derived series: an app's service token writes computed series to ``app-<app id>``.

    The whole body is checked first (422); an item naming another app's source makes the
    request a 403 and nothing is written. ``{"written", "errors"}``.
    """

    app_id = caller.app_id
    if app_id is None:
        raise HTTPException(
            status_code=403, detail=t("Only an app's service token writes derived series.")
        )
    try:
        items = parse_derived(body)
        for item in items:
            check_owner(app_id, item.signal)
    except ContractError as exc:
        raise _unprocessable(exc) from exc
    except DerivedError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return _answer(rt.datalayer.put_derived, app_id, items)


@router.put("/series/runs")
def put_series_runs(caller: V1Caller, rt: Runtime, body: Any = Body(None)) -> dict[str, Any]:
    """Runs points: an app's service token writes one whole series per execution
    (``[{"signal", "run_at", "t", "v", "keep_runs", "keep_days", ...}]``) to ``app-<app id>``.

    Checked as ``PUT /api/v1/series`` is (422, then 403 for another app's source, nothing
    written). A run at the same ``run_at`` replaces it. ``{"written", "errors"}``.
    """

    app_id = caller.app_id
    if app_id is None:
        raise HTTPException(
            status_code=403, detail=t("Only an app's service token writes derived series.")
        )
    try:
        items = parse_runs(body)
        for item in items:
            check_owner(app_id, item.signal)
    except ContractError as exc:
        raise _unprocessable(exc) from exc
    except DerivedError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return _answer(rt.datalayer.put_runs, app_id, items)


class SeriesRetire(BaseModel):
    signals: list[Annotated[str, StringConstraints(min_length=1, max_length=340)]] = Field(
        min_length=1, max_length=500
    )


@router.post("/series/retire")
def retire_series(payload: SeriesRetire, caller: V1Caller, rt: Runtime) -> dict[str, Any]:
    """An app retires derived series it no longer writes (``{"signals": [...]}``).

    Only its own source (403 otherwise, nothing retired). A retired series is no longer listed
    nor read; the Historian keeps its archive for its retired days. ``{"retired", "errors"}``.
    """

    app_id = caller.app_id
    if app_id is None:
        raise HTTPException(
            status_code=403, detail=t("Only an app's service token retires derived series.")
        )
    try:
        for signal in payload.signals:
            check_owner(app_id, signal)
    except DerivedError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc
    return _answer(rt.datalayer.retire_derived, app_id, list(dict.fromkeys(payload.signals)))


@router.get("/signals/{signal_id:path}/value")
def value(
    signal_id: str,
    _caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    agg: str = Query(default="last", max_length=10),
    window: str = Query(default="1h", max_length=20),
) -> dict[str, Any]:
    """One aggregate (``last, mean, min, max, std``) over the ``window`` that ends now.

    A text signal has only ``last``, its newest label.
    """

    _require_signal(scope, signal_id)
    return _answer(rt.datalayer.value, signal_id, agg, window)


@router.get("/signals/{signal_id:path}")
def signal(signal_id: str, _caller: V1Reader, rt: Runtime, scope: V1Scope) -> dict[str, Any]:
    """One signal by id; a bare tag one source has answers that signal (deprecated)."""

    found = _answer(rt.datalayer.signal, signal_id)
    if not scope.signal_item(found) and not scope.signal(signal_id):
        raise HTTPException(status_code=404, detail=t("Signal not found."))
    return found


# Audit ---------------------------------------------------------------------------


@router.post("/audit", status_code=201)
def audit(payload: AuditEntry, caller: V1Caller, rt: Runtime) -> dict[str, int]:
    """Record a change an app's user made; the user comes from the token."""

    if caller.app_id is None and caller.level not in {"editor", "admin"} and public_demo():
        # A public demo's visitors change nothing, so they have nothing to record either.
        raise HTTPException(
            status_code=403,
            detail=t("This is a public demo: you can try everything, but nothing is saved."),
        )
    app_id = caller.app_id or (payload.app.strip().lower() if payload.app else None)
    audit_id = rt.workspace.audit.record(
        caller.username,
        payload.action.strip(),
        payload.subject,
        payload.detail,
        app_id=app_id,
    )
    return {"id": audit_id}
