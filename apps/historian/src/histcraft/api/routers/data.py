"""The data API PlantCraft serves to every app (docs/data-layer.md).

HistCraft is the suite's data layer: PlantCraft's API v1 routes for signals,
series and values forward here, and its ``POST /api/v1/series/write`` sends the
series apps compute. Only PlantCraft calls these routes, with a token it signs
for itself (``sub: app:processcraft``); people use the pages' routes. Shapes,
limits and error codes are those of PlantCraft's ``docs/api-v1.md``
(``plantcraft_sdk.contract``); signal ids are ``<source id>:<tag>``.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from functools import partial
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from plantcraft_sdk.auth import User
from plantcraft_sdk.contract import (
    MAX_BATCH_SIGNALS,
    ContractError,
    parse_time,
    series_range,
    unique_signals,
)
from plantcraft_sdk.wire import MEDIA_TYPE as WIRE_MEDIA_TYPE
from pydantic import BaseModel, Field, ValidationError

from histcraft.api.deps import RuntimeDep, current_user, time_limited
from histcraft.api.read_budget import BinaryBatch, EncodedBatch, Ticket, json_bytes
from histcraft.api.runtime import Runtime, point_ref
from histcraft.archive.edit_marks import edit_marks
from histcraft.archive.query import Reader, SourceUnavailable, iso_ms, to_ms
from histcraft.catalog.models import (
    INTEGRATION_FIELDS,
    PLANT_KINDS,
    SOURCE_SETTINGS,
    SYSTEM_SOURCE,
    WRITTEN_KINDS,
    CatalogError,
    PointIn,
    PointPatch,
    SourceIn,
    derived_source,
    secret_follows,
    split_signal,
)
from histcraft.clock import now_ms
from histcraft.i18n import t
from histcraft.kinds import KINDS, RUNS, coerce
from histcraft.opc_status import described
from histcraft.sources.history import open_source

router = APIRouter(prefix="/api/v1/data", tags=["data"])
PROCESSCRAFT = "app:processcraft"
# Derived writes: series and values per call.
MAX_WRITE_SERIES = 500
MAX_WRITE_VALUES = 100_000
APP_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,35}$")


def processcraft(user: Annotated[User, Depends(current_user)]) -> User:
    if user.username != PROCESSCRAFT:
        raise HTTPException(403, t("Only PlantCraft reads and writes data here."))
    return user


PlantCraft = Annotated[User, Depends(processcraft)]


class ImportedSignal(BaseModel):
    tag: str = Field(min_length=1, max_length=300)
    address: str = Field(default="", max_length=500)
    mode: str = ""
    name: str = Field(default="", max_length=200)
    unit: str = Field(default="", max_length=40)
    description: str = Field(default="", max_length=500)
    low: float | None = None
    high: float | None = None
    kind: str = "number"
    step: bool = False
    # Collection (archive mode): scan period and compression deviation; None = the defaults.
    scan_seconds: float | None = None
    deviation: float | None = None


def signal_shape(point: dict[str, Any]) -> dict[str, Any]:
    # Other apps read low and high as the engineering limits, which judge the data (Analytics'
    # out-of-range and noise checks): a range only suggested from the first day is not that
    # until a person confirms it (``catalog.ranges``), so it stays inside the Historian.
    confirmed = point.get("range_origin") != "suggested"
    return {
        "id": point["signal"],
        "name": point["name"] or point["tag"],
        "source": point["source_id"],
        "unit": point["unit"],
        "description": point["description"],
        "low": point["low"] if confirmed else None,
        "high": point["high"] if confirmed else None,
        "kind": point["kind"],
        "mode": point["mode"],
        # Its source's kind: opcua, pi_web_api, csv (laboratory, manual entries), derived or
        # system (the suite's own health, written by PlantCraft).
        "source_kind": point["source_kind"],
        # Derived signals: the app that writes them, and what they are about.
        "app": point["source_id"][4:] if point["source_kind"] == "derived" else None,
        "subject": point["subject"] or None,
        "result": point["result"] or None,
        # The retention in effect (0: forever), and what sets it when not people (H1).
        "retention_days": point["retention_days"],
        "managed_by": point.get("managed_by") or None,
    }


def _point(runtime: Runtime, signal_id: str) -> dict[str, Any]:
    try:
        return runtime.catalog.point(signal_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _range(start: str | None, end: str | None, step: float | None):
    try:
        return series_range(start, end, step, default_end=datetime.now(timezone.utc))
    except ContractError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/sources")
def sources(runtime: RuntimeDep, _caller: PlantCraft) -> list[dict[str, Any]]:
    state = (runtime.archive.state().get("collector") or {}).get("sources") or {}
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "kind": item["kind"],
            "enabled": item["enabled"],
            "mode": item["mode"],
            "default_mode": item["default_mode"],
            "endpoint": item["endpoint"],
            "namespace_uri": item["namespace_uri"],
            "username": item["username"],
            "password_env": item["password_env"],
            "has_password": item["has_password"],
            "options": item["options"],
            # Overrides of the general settings for the source's signals (null: general).
            **{key: item[key] for key in SOURCE_SETTINGS},
            # The integration: who answers for it, the team's contact, the expected interval.
            **{key: item[key] for key in INTEGRATION_FIELDS},
            "status": state.get(item["id"]),
            "signals": item["points"],
        }
        for item in runtime.catalog.sources()
    ]


# Sources created from PlantCraft's Connections page ------------------------------------


class SourceCreate(SourceIn):
    """A plant source (``SourceIn``) and, optionally, its first signals."""

    signals: list[str | ImportedSignal] = Field(default_factory=list, max_length=200_000)


def _plant_source(body: SourceIn) -> None:
    if body.kind not in PLANT_KINDS:
        raise HTTPException(422, t("A derived source appears when its app first writes."))


def _add_signals(
    runtime: Runtime, source_id: str, signals: list[str | ImportedSignal]
) -> dict[str, Any]:
    points, skipped = [], []
    for entry in signals:
        item = entry if isinstance(entry, ImportedSignal) else ImportedSignal(tag=entry)
        try:
            points.append(
                PointIn(
                    tag=item.tag,
                    source_id=source_id,
                    address=item.address or item.tag,
                    name=item.name,
                    unit=item.unit,
                    description=item.description,
                    low=item.low,
                    high=item.high,
                    kind=item.kind if item.kind in ("number", "text") else "number",
                    step=item.step,
                    mode=item.mode,
                    scan_seconds=item.scan_seconds,
                    deviation=item.deviation,
                )
            )
        except ValidationError as exc:
            skipped.append({"tag": item.tag, "reason": str(exc.errors()[0]["msg"])[:200]})
    added: list[str] = []
    for offset in range(0, len(points), 5000):
        result = runtime.catalog.add_points(points[offset : offset + 5000])
        added += result["added"]
        skipped += result["skipped"]
    return {"added": added, "skipped": skipped}


def _source_answer(runtime: Runtime, source_id: str) -> dict[str, Any]:
    return next(item for item in sources(runtime, None) if item["id"] == source_id)


@router.post("/sources", status_code=201)
def create_source(body: SourceCreate, runtime: RuntimeDep, caller: PlantCraft) -> dict[str, Any]:
    _plant_source(body)
    secret = runtime.vault.encrypt(body.password) if body.password else None
    try:
        runtime.catalog.save_source(body, create=True, secret=secret)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    runtime.audit(caller, "source.add", body.id, {"kind": body.kind, "endpoint": body.endpoint})
    added = _add_signals(runtime, body.id, body.signals) if body.signals else None
    return {**_source_answer(runtime, body.id), "signals_added": added}


@router.put("/sources/{source_id}")
def update_source(
    source_id: str, body: SourceIn, runtime: RuntimeDep, caller: PlantCraft
) -> dict[str, Any]:
    if body.id != source_id:
        raise HTTPException(422, t("The id in the path and the body differ."))
    _plant_source(body)
    secret = runtime.vault.encrypt(body.password) if body.password is not None else None
    try:
        runtime.catalog.save_source(body, create=False, secret=secret)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    runtime.audit(caller, "source.update", source_id, {"endpoint": body.endpoint})
    return _source_answer(runtime, source_id)


@router.get("/sources/{source_id}/history")
def source_history(
    source_id: str, runtime: RuntimeDep, _caller: PlantCraft, limit: int = 100
) -> list[dict[str, Any]]:
    """When the collector found the source connected and disconnected, the newest first."""

    try:
        runtime.catalog.source(source_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return runtime.catalog.source_events(source_id, limit)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, runtime: RuntimeDep, caller: PlantCraft) -> None:
    try:
        runtime.catalog.delete_source(source_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    runtime.audit(caller, "source.delete", source_id)


def _plant_reader(runtime: Runtime, source_id: str) -> Any:
    try:
        source = runtime.catalog.source(source_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    if source["kind"] not in PLANT_KINDS:
        raise HTTPException(422, t("Derived signals appear when their app writes them."))
    try:
        return runtime.source_history(source_id)
    except (SourceUnavailable, ValueError, RuntimeError) as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/sources/test")
def test_settings(body: SourceIn, runtime: RuntimeDep, _caller: PlantCraft) -> dict[str, Any]:
    """Reach a source from settings not saved yet. Without ``password``, an existing source's
    stored one is used (editing)."""

    _plant_source(body)
    password = body.password
    if password is None and body.password_env:
        password = os.environ.get(body.password_env, "")
    if password is None:
        try:
            stored = runtime.catalog.secret(body.id)
            if stored:
                secret_follows(runtime.catalog.source(body.id), body)
            password = runtime.vault.decrypt(stored)
        except CatalogError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc
    row = {**body.model_dump(), "id": body.id}
    try:
        reader = open_source(row, password or "")
        return {"ok": True, "detail": reader.test()}
    except Exception as exc:  # noqa: BLE001 - the plant system's own words
        raise HTTPException(502, str(exc) or type(exc).__name__) from exc


@router.post("/sources/{source_id}/test")
def test_source(source_id: str, runtime: RuntimeDep, _caller: PlantCraft) -> dict[str, Any]:
    """Reach the source now; ``{"ok": true, "detail": {...}}`` or 502 with its own words."""

    reader = _plant_reader(runtime, source_id)
    try:
        return {"ok": True, "detail": reader.test()}
    except Exception as exc:  # noqa: BLE001 - the plant system's own words
        raise HTTPException(502, str(exc) or type(exc).__name__) from exc


class BrowseIn(BaseModel):
    root: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=5000, ge=1, le=20_000)


@router.post("/sources/{source_id}/browse")
def browse_source(
    source_id: str, runtime: RuntimeDep, _caller: PlantCraft, body: BrowseIn | None = None
) -> dict[str, Any]:
    """The source's variables: ``{"variables": [{"address", "tag", "name", "path", "kind",
    "step", "unit", "description", "low", "high"}], "truncated", "limit"}``."""

    body = body or BrowseIn()
    reader = _plant_reader(runtime, source_id)
    try:
        return reader.browse(body.root or None, body.limit)
    except Exception as exc:  # noqa: BLE001 - the plant system's own words
        raise HTTPException(502, str(exc) or type(exc).__name__) from exc


class SignalsIn(BaseModel):
    signals: list[str | ImportedSignal] = Field(default_factory=list, max_length=200_000)
    # Instead of a list: every variable the source shows (under ``root``), up to 20,000.
    all: bool = False
    root: str | None = Field(default=None, max_length=500)
    # Defaults for signals that do not set their own.
    mode: str = ""
    scan_seconds: float | None = Field(default=None, ge=0.1, le=86400)
    deviation: float | None = Field(default=None, ge=0)


def _describe(runtime: Runtime, source_id: str, items: list[ImportedSignal]) -> None:
    """Signals given by tag only take their kind, step, unit and name from the source's browse,
    so a text variable (an OPC UA MODE reading AUTO or MAN) is never archived as a number. The
    source being out of reach leaves the defaults."""

    if not items:
        return
    try:
        found = _plant_reader(runtime, source_id).browse(None, 20_000)
    except Exception:  # noqa: BLE001 - described later, when the source answers
        return
    by_tag = {item.get("tag"): item for item in found.get("variables", [])}
    for item in items:
        variable = by_tag.get(item.tag)
        if not variable:
            continue
        if variable.get("kind") in ("number", "text"):
            item.kind = variable["kind"]
        item.step = item.step or bool(variable.get("step"))
        item.unit = item.unit or str(variable.get("unit") or "")
        item.name = item.name or str(variable.get("name") or "")


@router.post("/sources/{source_id}/signals")
def add_signals(
    source_id: str, body: SignalsIn, runtime: RuntimeDep, caller: PlantCraft
) -> dict[str, Any]:
    try:
        source = runtime.catalog.source(source_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    if source["kind"] not in PLANT_KINDS:
        raise HTTPException(422, t("Derived signals appear when their app writes them."))
    wanted = [e if isinstance(e, ImportedSignal) else ImportedSignal(tag=e) for e in body.signals]
    if body.all:
        reader = _plant_reader(runtime, source_id)
        try:
            found = reader.browse(body.root or None, 20_000)
        except Exception as exc:  # noqa: BLE001 - the plant system's own words
            raise HTTPException(502, str(exc) or type(exc).__name__) from exc
        fields = set(ImportedSignal.model_fields)
        wanted += [
            ImportedSignal(**{k: v for k, v in item.items() if k in fields and v is not None})
            for item in found["variables"]
        ]
    if not wanted:
        raise HTTPException(422, t("Give signals, or all: true."))
    _describe(runtime, source_id, [item for item in wanted if "kind" not in item.model_fields_set])
    for item in wanted:
        item.mode = item.mode or body.mode
        item.scan_seconds = item.scan_seconds or body.scan_seconds
        if item.deviation is None and item.kind == "number" and not item.step:
            item.deviation = body.deviation
    result = _add_signals(runtime, source_id, wanted)
    runtime.audit(caller, "points.add", f"{len(result['added'])} points", result["added"][:50])
    return result


@router.get("/signals")
def signals(
    runtime: RuntimeDep,
    _caller: PlantCraft,
    q: str = "",
    source: str | None = None,
    app: str | None = None,
    subject: str | None = None,
    result: str | None = None,
) -> list[dict[str, Any]]:
    items = runtime.catalog.points(
        q=q.strip()[:200],
        source_id=source or None,
        app=app or None,
        subject=subject or None,
        result=result or None,
    )
    return [signal_shape(point) for point in items]


@router.get("/signals/{signal_id:path}/series")
@time_limited
def series(
    signal_id: str,
    runtime: RuntimeDep,
    _caller: PlantCraft,
    start: str | None = None,
    end: str | None = None,
    step: float | None = None,
    run: str | None = None,
    runs: int | None = None,
) -> dict[str, Any]:
    point = _point(runtime, signal_id)
    if point["kind"] == RUNS:
        return {"signal": signal_id, "kind": RUNS, "runs": run_reads(runtime, point, run, runs)}
    begin, finish, step = _range(start, end, step)
    with runtime.read_budget.hold() as ticket:
        try:
            ref = point_ref(point)
            samples = None
            if step is None or not Reader.rollups_help(ref, to_ms(begin), step):
                samples = runtime.reader.samples(ref, to_ms(begin), to_ms(finish))
            ticket.take(_values_of(samples, begin, finish, step))
            stamps, values = runtime.reader.series(ref, begin, finish, step, samples)
        except ContractError as exc:
            raise HTTPException(422, str(exc)) from exc
        except SourceUnavailable as exc:
            raise HTTPException(502, str(exc)) from exc
        # Written straight to JSON: long lists skip FastAPI's per-item encoder.
        return Response(
            json_bytes({"signal": signal_id, "kind": point["kind"], "t": stamps, "v": values}),
            media_type="application/json",
        )


def _values_of(samples: Any, begin: datetime, finish: datetime, step: float | None) -> int:
    """The values an answer will hold: the samples read, at most the grid's cells."""

    cells = None if step is None else int((finish - begin).total_seconds() // step) + 1
    found = None if samples is None else len(samples[0])
    if found is None:
        return cells or 0
    return found if cells is None else min(found, cells)


def run_reads(
    runtime: Runtime, point: dict[str, Any], run: str | None, runs: int | None
) -> list[dict[str, Any]]:
    """A runs point's runs: ``run`` = ``latest`` (the default) or a run's ISO time, or the
    newest ``runs`` (1 to 50); ``start``, ``end`` and ``step`` do not apply."""

    if runs is not None and not 1 <= runs <= 50:
        raise HTTPException(422, t("runs is 1 to 50."))
    run_at = None
    if run and run != "latest":
        try:
            run_at = _moment(run)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    return runtime.reader.runs(point_ref(point), run_at=run_at, count=runs or 1)


@router.get("/signals/{signal_id:path}/runs")
def run_list(
    signal_id: str, runtime: RuntimeDep, _caller: PlantCraft, limit: int = 50
) -> dict[str, Any]:
    """A runs point's executions, newest first; an empty list for any other point."""

    point = _point(runtime, signal_id)
    limit = max(1, min(int(limit), 1000))
    found = runtime.reader.run_list(point_ref(point), limit) if point["kind"] == RUNS else []
    return {"signal": signal_id, "runs": found}


@router.get("/signals/{signal_id:path}/value")
def value(
    signal_id: str,
    runtime: RuntimeDep,
    _caller: PlantCraft,
    agg: str = "last",
    window: str = "1h",
    end: str | None = None,
) -> dict[str, Any]:
    """One aggregate over the ``window`` that ends at ``end`` (ISO 8601; now when left out, and
    never later than now): a report of last week reads the week that closed on Monday."""

    point = _point(runtime, signal_id)
    try:
        now = datetime.now(timezone.utc)
        until = parse_time(end, "end")
        answer = runtime.reader.value(
            point_ref(point), agg, window, min(until, now) if until else None
        )
    except ContractError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    return {**answer, "signal": signal_id}


@router.patch("/signals/{signal_id:path}")
def update_signal(
    signal_id: str, body: PointPatch, runtime: RuntimeDep, _caller: PlantCraft
) -> dict[str, Any]:
    """Change a plant signal: ``{"enabled": false}`` stops using it and keeps its history."""

    point = _point(runtime, signal_id)
    if point["source_kind"] in WRITTEN_KINDS:
        raise HTTPException(422, t("Derived signals are changed by the app that writes them."))
    try:
        return signal_shape(runtime.catalog.update_point(point["signal"], body))
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.delete("/signals/{signal_id:path}", status_code=204)
def delete_signal(signal_id: str, runtime: RuntimeDep, _caller: PlantCraft) -> None:
    """Retire a signal: no longer collected, its archive kept for ``RETIRED_DAYS`` days."""

    point = _point(runtime, signal_id)
    runtime.catalog.retire_points([point["signal"]], by="plantcraft")


@router.get("/signals/{signal_id:path}")
def signal(signal_id: str, runtime: RuntimeDep, _caller: PlantCraft) -> dict[str, Any]:
    return signal_shape(_point(runtime, signal_id))


class BatchIn(BaseModel):
    signals: list[Any]
    start: str | None = None
    end: str | None = None
    step: float | None = None
    # Each series also says where its quality was not good: ``quality: [{t, quality}]`` (the
    # quality from ``t`` to the next change: uncertain, substituted, bad, or good again).
    quality: bool = False
    # With ``step``: each number series also holds every cell's lowest and highest value
    # (``low``, ``high``, beside the means), from the hourly rollups where whole hours allow.
    extremes: bool = False


@router.post("/series")
@time_limited
def series_batch(
    body: BatchIn, runtime: RuntimeDep, _caller: PlantCraft, request: Request
) -> Response:
    with runtime.read_budget.hold() as ticket:
        return read_batch(body, runtime, ticket, binary=wants_binary(request)).response()


def wants_binary(request: Request) -> bool:
    """The caller asked for the binary answer (``plantcraft_sdk.wire``) in ``Accept``."""

    return WIRE_MEDIA_TYPE in request.headers.get("accept", "")


def read_batch(
    body: BatchIn, runtime: Runtime, ticket: Ticket, *, binary: bool = False
) -> EncodedBatch | BinaryBatch:
    """The series of a batch, each JSON as soon as it is read (or kept as arrays for the
    binary answer), within the read budget: the caller answers ``.response()`` before
    ``ticket`` is given back."""

    if not 1 <= len(body.signals) <= MAX_BATCH_SIGNALS:
        raise HTTPException(
            422, t("Ask for 1 to {count} signals per request.", count=MAX_BATCH_SIGNALS)
        )
    if any(not isinstance(item, str) or not 1 <= len(item) <= 340 for item in body.signals):
        raise HTTPException(422, t("Signal ids are text of 1 to 340 characters."))
    begin, finish, step = _range(body.start, body.end, body.step)
    wanted = unique_signals(body.signals)
    points = runtime.catalog.find_many(wanted)
    begin_ms, finish_ms = to_ms(begin), to_ms(finish)
    # Signals read from their sources: one call per source for the whole batch.
    from_source = [p for p in points.values() if p is not None and p["mode"] == "source"]
    fetched = runtime.recorded(from_source, begin_ms, finish_ms) if from_source else {}
    # The archive of the whole batch in two queries. A grid of whole hours of an archive-only
    # signal is left to ``Reader.series``, which reads the hourly rollups.
    refs = [point_ref(p) for p in points.values() if p is not None and p["mode"] != "source"]
    stored = [
        ref for ref in refs if ref.mode == "both" or not Reader.rollups_help(ref, begin_ms, step)
    ]
    archived = runtime.reader.archived_many(stored, begin_ms, finish_ms) if stored else {}
    # Signals archived and read from their source before the archive began (``both``): the
    # source's part of the whole batch in one call per source too, never one per signal.
    gaps: dict[int, int] = {}
    for point in points.values():
        if point is None or point["mode"] != "both":
            continue
        upto = Reader.source_gap(archived[int(point["id"])][0], begin_ms, finish_ms)
        if upto is not None:
            gaps[int(point["id"])] = upto
    older = (
        runtime.recorded(
            [p for p in points.values() if p is not None and int(p["id"]) in gaps],
            begin_ms,
            max(gaps.values()),
        )
        if gaps
        else {}
    )
    # The answer's values, known now the samples are read: wait for room for them.
    ticket.take(
        sum(
            _values_of(found, begin, finish, step)
            for found in [*archived.values(), *fetched.values()]
            if not isinstance(found, str)
        )
        + (len(refs) - len(stored)) * _values_of(None, begin, finish, step)
    )
    quality: dict[int, list[tuple]] = {}
    edited: dict[int, list[dict[str, Any]]] = {}
    if body.quality:
        quality = runtime.archive.qualities_many(
            [int(p["id"]) for p in points.values() if p is not None and p["mode"] != "source"],
            begin_ms,
            finish_ms,
            with_status=True,
        )
        edited = runtime.archive.edits(
            [int(p["id"]) for p in points.values() if p is not None and p["mode"] != "source"],
            begin_ms,
            finish_ms,
        )
    builder: EncodedBatch | BinaryBatch = BinaryBatch() if binary else EncodedBatch()
    read = runtime.reader.series_arrays if binary else runtime.reader.series
    for signal_id in wanted:
        point = points[signal_id]
        if point is None:
            builder.fail(signal_id, 404, t("Signal {id} not found.", id=signal_id))
            continue
        if builder.full:
            builder.postpone(signal_id)
            continue
        samples = fetched.get(int(point["id"]))
        if isinstance(samples, str):
            builder.fail(signal_id, 502, samples)
            continue
        ref = point_ref(point)
        if point["kind"] == RUNS:
            # Its newest run, as a plain series with the run's time.
            latest = runtime.reader.runs(ref)
            if latest:
                run_at = {"run_at": latest[0]["run_at"]}
                builder.add(signal_id, RUNS, latest[0]["t"], latest[0]["v"], run_at)
            else:
                builder.add(signal_id, RUNS, [], [], {"run_at": None})
            continue
        try:
            if samples is not None:
                samples = runtime.reader.normalize(ref, *samples)
            elif int(point["id"]) in archived:
                samples = archived[int(point["id"])]
                found = older.get(int(point["id"]))
                # A source that cannot answer leaves the archive alone, as for one signal.
                if found is not None and not isinstance(found, str):
                    samples = Reader.with_older(ref, samples, runtime.reader.normalize(ref, *found))
            stamps, values = read(ref, begin, finish, step, samples)
        except ContractError as exc:
            builder.fail(signal_id, 422, str(exc))
            continue
        except SourceUnavailable as exc:
            builder.fail(signal_id, 502, str(exc))
            continue
        extra = None
        if body.quality:
            changes = quality.get(int(point["id"]), [])
            stamps_q = iso_ms(np.asarray([change[0] for change in changes], dtype=np.int64))
            extra = {
                "quality": [
                    {"t": at, "quality": code, **described(status, name)}
                    for at, (_, code, status, name) in zip(stamps_q, changes, strict=True)
                ]
            }
            marks = edit_marks(edited.get(int(point["id"]), []))
            if marks:
                extra["edits"] = marks
        if body.extremes and step:
            bounds = runtime.reader.extremes(ref, begin, finish, step)
            if bounds is not None and len(bounds[0]) == len(stamps):
                extra = {**(extra or {}), "low": bounds[0], "high": bounds[1]}
        builder.add(signal_id, point["kind"], stamps, values, extra)
    return builder


# Derived series -------------------------------------------------------------------------


class DerivedSeries(BaseModel):
    # The app writing it; PlantCraft fills it from the caller's token.
    app: str | None = Field(default=None, min_length=1, max_length=40)
    signal: str = Field(min_length=3, max_length=340)
    subject: str | None = Field(default=None, max_length=340)
    result: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    low: float | None = None
    high: float | None = None
    kind: str = "number"
    # Days the values are kept, sent on each write (0: forever; null: as it is).
    retention_days: int | None = Field(default=None, ge=0, le=36500)
    # What sets the point's retention and compression, e.g. ``link:<schedule>``: people then
    # cannot change them here (409). Empty clears it; null leaves it as it is.
    managed_by: str | None = Field(default=None, max_length=100)
    t: list[str]
    v: list[Any]


class DerivedIn(BaseModel):
    # Default app for items without their own ``app``.
    app: str | None = Field(default=None, min_length=1, max_length=40)
    series: list[DerivedSeries] = Field(min_length=1, max_length=MAX_WRITE_SERIES)


def _samples(item: DerivedSeries) -> list[tuple[int, Any]]:
    """The series as ``(ms, value)`` in time order; raises ``ValueError`` with the reason."""

    if len(item.t) != len(item.v):
        raise ValueError(t("t and v must have the same length."))
    if item.kind not in KINDS:
        raise ValueError(t("kind is one of {kinds}.", kinds=", ".join(KINDS)))
    samples: list[tuple[int, Any]] = []
    for stamp, raw in zip(item.t, item.v, strict=True):
        try:
            moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(t("{value} is not an ISO 8601 time.", value=str(stamp)[:40])) from exc
        if moment.tzinfo is None:
            raise ValueError(t("Times need an offset (Z or +hh:mm)."))
        samples.append((to_ms(moment), coerce(item.kind, raw)))
    times = [at for at, _ in samples]
    if any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise ValueError(t("Times must be in ascending order, without repeats."))
    if times and times[-1] > now_ms() + 86_400_000:
        raise ValueError(t("Values more than a day in the future are refused."))
    return samples


@router.post("/derived")
def write_derived(body: DerivedIn, runtime: RuntimeDep, _caller: PlantCraft) -> dict[str, Any]:
    """Apps' computed series, stored as their derived signals (``app-<app id>:<name>``)."""

    if sum(len(item.v) for item in body.series) > MAX_WRITE_VALUES:
        raise HTTPException(422, t("Send at most {count} values per call.", count=MAX_WRITE_VALUES))
    errors: list[dict[str, Any]] = []
    ready: dict[str, list[tuple[DerivedSeries, list[tuple[int, Any]]]]] = {}
    seen: set[str] = set()
    for item in body.series:
        app = _writer(item.app or body.app, item.signal, seen, errors)
        if app is None:
            continue
        try:
            ready.setdefault(app, []).append((item, _samples(item)))
        except ValueError as exc:
            errors.append({"signal": item.signal, "status": 422, "detail": str(exc)})
    written = 0
    for app, items in ready.items():
        written += _store(runtime, items, errors, partial(runtime.catalog.derived, app))
    return {"written": written, "errors": errors}


def _writer(
    app: str | None, signal: str, seen: set[str], errors: list[dict[str, Any]]
) -> str | None:
    """The app writing ``signal`` when it may (its own source, once per call); else None, with
    the reason in ``errors``."""

    if not app or not APP_ID.match(app):
        errors.append({"signal": signal, "status": 422, "detail": t("Invalid app.")})
        return None
    source_id, tag = split_signal(signal)
    if source_id != derived_source(app):
        errors.append(
            {
                "signal": signal,
                "status": 403,
                "detail": t(
                    "{app} writes only signals {source}:<name>.",
                    app=app,
                    source=derived_source(app),
                ),
            }
        )
        return None
    if signal in seen or any(ch in tag for ch in "\x00\n\r\t"):
        errors.append({"signal": signal, "status": 422, "detail": t("Invalid signal.")})
        return None
    seen.add(signal)
    return app


def _store(
    runtime: Runtime,
    items: list[tuple[DerivedSeries, list[tuple[int, Any]]]],
    errors: list[dict[str, Any]],
    points_of: Any,
) -> int:
    """Writes checked series to the points ``points_of(descriptions)`` creates; the values
    written. Failures join ``errors``."""

    try:
        points = points_of([item.model_dump(exclude={"t", "v", "app"}) for item, _ in items])
    except CatalogError as exc:
        errors.extend(
            {"signal": item.signal, "status": exc.status, "detail": str(exc)} for item, _ in items
        )
        return 0
    written = 0
    snapshots = []
    for item, samples in items:
        point = points[item.signal]
        if point["kind"] != item.kind:
            errors.append(
                {
                    "signal": item.signal,
                    "status": 409,
                    "detail": t("{id} is a {kind} signal.", id=item.signal, kind=point["kind"]),
                }
            )
            continue
        written += runtime.archive.replace(int(point["id"]), point["kind"], samples)
        if samples:
            at, last = samples[-1]
            if isinstance(last, float) and np.isnan(last):
                last = None
            snapshots.append({"point": int(point["id"]), "ts": at, "value": last, "status": "ok"})
    if snapshots:
        runtime.archive.put_snapshots(snapshots)
    return written


# Runs (H2) ---------------------------------------------------------------------------------

MAX_RUN_VALUES = 20_000


class DerivedRun(BaseModel):
    """One execution of an app's series output: a whole series of its own, kept with the
    newest ``keep_runs`` runs (``keep_days``: also dropped past that age; null: by count only)."""

    app: str | None = Field(default=None, min_length=1, max_length=40)
    signal: str = Field(min_length=3, max_length=340)
    subject: str | None = Field(default=None, max_length=340)
    result: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)
    managed_by: str | None = Field(default=None, max_length=100)
    keep_runs: int = Field(default=10, ge=1, le=1000)
    keep_days: int | None = Field(default=None, ge=1, le=36500)
    run_at: str
    t: list[str] = Field(max_length=MAX_RUN_VALUES)
    v: list[Any] = Field(max_length=MAX_RUN_VALUES)


class RunsIn(BaseModel):
    app: str | None = Field(default=None, min_length=1, max_length=40)
    series: list[DerivedRun] = Field(min_length=1, max_length=MAX_WRITE_SERIES)


def _moment(stamp: Any) -> int:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(t("{value} is not an ISO 8601 time.", value=str(stamp)[:40])) from exc
    if moment.tzinfo is None:
        raise ValueError(t("Times need an offset (Z or +hh:mm)."))
    return to_ms(moment)


@router.post("/derived/runs")
def write_runs(body: RunsIn, runtime: RuntimeDep, _caller: PlantCraft) -> dict[str, Any]:
    """Apps' series outputs, one run per execution, as derived signals of kind ``runs``."""

    if sum(len(item.v) for item in body.series) > MAX_WRITE_VALUES:
        raise HTTPException(422, t("Send at most {count} values per call.", count=MAX_WRITE_VALUES))
    errors: list[dict[str, Any]] = []
    ready: dict[str, list[tuple[DerivedRun, int, list[tuple[int, Any]]]]] = {}
    seen: set[str] = set()
    for item in body.series:
        app = _writer(item.app or body.app, item.signal, seen, errors)
        if app is None:
            continue
        try:
            run_at = _moment(item.run_at)
            samples = _samples(DerivedSeries(signal=item.signal, kind="number", t=item.t, v=item.v))
        except ValueError as exc:
            errors.append({"signal": item.signal, "status": 422, "detail": str(exc)})
            continue
        ready.setdefault(app, []).append((item, run_at, samples))
    written = 0
    for app, items in ready.items():
        descriptions = [
            {
                **item.model_dump(exclude={"t", "v", "app", "run_at", "keep_days"}),
                "kind": RUNS,
                # Kept by count; by age too when the app says so.
                "retention_days": item.keep_days or 0,
            }
            for item, _, _ in items
        ]
        try:
            points = runtime.catalog.derived(app, descriptions)
        except CatalogError as exc:
            errors.extend(
                {"signal": item.signal, "status": exc.status, "detail": str(exc)}
                for item, _, _ in items
            )
            continue
        snapshots = []
        for item, run_at, samples in items:
            point = points[item.signal]
            if point["kind"] != RUNS:
                errors.append(
                    {
                        "signal": item.signal,
                        "status": 409,
                        "detail": t("{id} is a {kind} signal.", id=item.signal, kind=point["kind"]),
                    }
                )
                continue
            if not samples:
                continue
            written += 1
            runtime.archive.put_run(int(point["id"]), run_at, samples, item.keep_runs)
            snapshots.append(
                {"point": int(point["id"]), "ts": run_at, "value": None, "status": "ok"}
            )
        if snapshots:
            runtime.archive.put_snapshots(snapshots)
    return {"written": written, "errors": errors}


class SystemIn(BaseModel):
    series: list[DerivedSeries] = Field(min_length=1, max_length=MAX_WRITE_SERIES)


@router.post("/system")
def write_system(body: SystemIn, runtime: RuntimeDep, _caller: PlantCraft) -> dict[str, Any]:
    """The suite's own health (``system:<name>``: each service up, latency, CPU, memory, errors;
    the disk; the backups), written by PlantCraft's monitor every minute (docs/data-layer.md)."""

    if sum(len(item.v) for item in body.series) > MAX_WRITE_VALUES:
        raise HTTPException(422, t("Send at most {count} values per call.", count=MAX_WRITE_VALUES))
    errors: list[dict[str, Any]] = []
    ready: list[tuple[DerivedSeries, list[tuple[int, Any]]]] = []
    seen: set[str] = set()
    for item in body.series:
        source_id, tag = split_signal(item.signal)
        if (
            source_id != SYSTEM_SOURCE
            or item.signal in seen
            or any(ch in tag for ch in "\x00\n\r\t")
        ):
            errors.append({"signal": item.signal, "status": 422, "detail": t("Invalid signal.")})
            continue
        seen.add(item.signal)
        try:
            ready.append((item, _samples(item)))
        except ValueError as exc:
            errors.append({"signal": item.signal, "status": 422, "detail": str(exc)})
    written = _store(runtime, ready, errors, runtime.catalog.system) if ready else 0
    return {"written": written, "errors": errors}


# Sources handed over by PlantCraft ----------------------------------------------------------


class ImportedSource(BaseModel):
    """A source as PlantCraft keeps it (``DataSourceConfig``, docs/data-layer.md)."""

    id: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=120)
    type: str
    base_url: str = ""
    server: str | None = None
    endpoint_url: str | None = None
    namespace_uri: str = ""
    path: str | None = None
    auth_type: str = "kerberos"
    username: str | None = None
    password: str | None = Field(default=None, max_length=500, repr=False)
    verify_ssl: bool = True
    ca_bundle: str | None = None
    read_mode: str = "recorded"
    max_workers: int = 4
    retries: int = 3
    page_size: int = 50000
    timezone: str = "UTC"
    timeout_seconds: float = 30.0
    history_boundary_minutes: int = 1440
    tags: list[str | ImportedSignal] = Field(default_factory=list, max_length=200_000)
    mapping: dict[str, str] = Field(default_factory=dict)


class ImportIn(BaseModel):
    sources: list[ImportedSource] = Field(min_length=1, max_length=100)


def _source_in(item: ImportedSource) -> SourceIn:
    common = {"id": item.id, "name": item.name or item.id, "enabled": True}
    if item.type == "pi_web_api":
        return SourceIn(
            **common,
            kind="pi_web_api",
            endpoint=item.base_url,
            username=item.username or "",
            options={
                "server": item.server or "",
                "auth_type": item.auth_type,
                "verify_ssl": item.verify_ssl,
                "ca_bundle": item.ca_bundle or "",
                "read_mode": item.read_mode,
                "max_workers": item.max_workers,
                "retries": item.retries,
                "page_size": item.page_size,
                "timeout_seconds": item.timeout_seconds,
                "timezone": item.timezone,
                "history_boundary_minutes": item.history_boundary_minutes,
            },
        )
    if item.type == "opcua":
        # PlantCraft read these servers' own history (Historical Access): keep doing so.
        return SourceIn(
            **common,
            kind="opcua",
            mode="source",
            endpoint=item.endpoint_url or "",
            namespace_uri=item.namespace_uri,
            username=(item.username or "") if item.auth_type == "basic" else "",
            options={
                "timeout_seconds": item.timeout_seconds,
                "timezone": item.timezone,
                "history_boundary_minutes": item.history_boundary_minutes,
            },
        )
    if item.type == "csv":
        return SourceIn(
            **common, kind="csv", endpoint=item.path or "", options={"timezone": item.timezone}
        )
    raise ValueError(t("Unknown source type {type}.", type=item.type))


@router.post("/sources/import")
def import_sources(body: ImportIn, runtime: RuntimeDep, _caller: PlantCraft) -> dict[str, Any]:
    """PlantCraft's sources, handed over once at the upgrade; again updates them."""

    imported, skipped = [], []
    for item in body.sources:
        try:
            source = _source_in(item)
        except (ValueError, ValidationError) as exc:
            skipped.append({"id": item.id, "reason": str(exc)[:300]})
            continue
        exists = any(s["id"] == source.id for s in runtime.catalog.sources())
        secret = runtime.vault.encrypt(item.password) if item.password else None
        try:
            runtime.catalog.save_source(source, create=not exists, secret=secret)
        except CatalogError as exc:
            skipped.append({"id": item.id, "reason": str(exc)})
            continue
        points = []
        for entry in item.tags:
            signal = entry if isinstance(entry, ImportedSignal) else ImportedSignal(tag=entry)
            address = item.mapping.get(signal.tag, signal.tag) if item.type == "csv" else signal.tag
            try:
                points.append(
                    PointIn(
                        tag=signal.tag,
                        source_id=source.id,
                        address=address,
                        name=signal.name,
                        unit=signal.unit,
                        description=signal.description,
                        low=signal.low,
                        high=signal.high,
                        kind=signal.kind if signal.kind in ("number", "text") else "number",
                    )
                )
            except ValidationError:
                continue
        for offset in range(0, len(points), 5000):
            runtime.catalog.add_points(points[offset : offset + 5000])
        imported.append(source.id)
    return {"imported": imported, "skipped": skipped}
