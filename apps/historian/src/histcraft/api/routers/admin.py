"""The routes behind HistCraft's pages: overview, sources, signals and settings.

Browsing a server and testing a connection are answered by the collector, which
holds the plant connections: the route files a request and the page polls
``GET /api/requests/{id}`` for its answer (docs/boundary.md). Signals are named
by their signal id, ``<source id>:<tag>``.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from plantcraft_sdk.contract import ContractError, series_range
from plantcraft_sdk.files import write_atomic
from pydantic import BaseModel, Field

from histcraft.api.deps import (
    AdminUser,
    CurrentUser,
    EditorUser,
    RuntimeDep,
    Scope,
    in_scope,
    time_limited,
)
from histcraft.api.routers.data import run_reads
from histcraft.api.runtime import Runtime, point_ref
from histcraft.archive.forecast import forecast, free_bytes
from histcraft.archive.query import SourceUnavailable, iso_ms
from histcraft.catalog import points_csv
from histcraft.catalog.models import (
    RETIRED_DAYS,
    SOURCE_SETTINGS,
    WRITTEN_KINDS,
    CatalogError,
    PointIn,
    PointPatch,
    SourceIn,
)
from histcraft.clock import now_ms
from histcraft.collector.backfill import MAX_HOURS
from histcraft.i18n import t
from histcraft.kinds import RUNS, outward_one
from histcraft.sources import certificates

router = APIRouter(prefix="/api", tags=["historian"])
# The collector is "running" while its heartbeat is younger than this.
HEARTBEAT_MS = 60_000
MAX_POINTS_PER_CALL = 5000


def _fail(exc: CatalogError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


def _collector(runtime: Runtime) -> dict[str, Any]:
    state = (runtime.archive.state().get("collector")) or {}
    heartbeat = state.get("heartbeat")
    running = bool(heartbeat) and now_ms() - int(heartbeat) < HEARTBEAT_MS
    return {
        "running": running,
        "mode": runtime.settings.collector,
        "heartbeat": heartbeat,
        "started": state.get("started"),
        "reads_per_second": state.get("reads_per_second", 0) if running else 0,
        "sources": state.get("sources") or {},
    }


@router.get("/overview")
def overview(runtime: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    points = runtime.catalog.points()
    stats = runtime.archive.point_stats()
    snaps = runtime.archive.snapshots()
    reads = sum(int(row.get("reads") or 0) for row in snaps.values())
    archived = sum(int(row.get("archived") or 0) for row in snaps.values())
    stored = sum(item["values"] for item in stats.values())
    stored_bytes = sum(item["bytes"] for item in stats.values())
    statuses: dict[str, int] = {}
    for point in points:
        if not point["enabled"]:
            status = "disabled"
        else:
            status = (snaps.get(point["id"]) or {}).get("status", "waiting")
        statuses[status] = statuses.get(status, 0) + 1
    firsts = [item["first"] for item in stats.values() if item["first"] is not None]
    return {
        "points": len(points),
        "sources": len(runtime.catalog.sources()),
        "statuses": statuses,
        "collector": _collector(runtime),
        "archive": {
            "values": stored,
            "day": sum(item["day"] for item in stats.values()),
            "bytes": stored_bytes,
            "file_bytes": runtime.archive.file_bytes(),
            "bytes_per_value": round(stored_bytes / stored, 2) if stored else None,
            "oldest": min(firsts) if firsts else None,
            # How fast it grows and when the disk fills (D4), from the counts above.
            "forecast": forecast(
                points,
                stats,
                free_bytes(
                    runtime.archive.path.parent
                    if runtime.archive.path
                    else runtime.settings.data_dir
                ),
                now_ms(),
            ),
        },
        # Since the collector started: values read per value archived.
        "compression": {
            "reads": reads,
            "archived": archived,
            "ratio": round(reads / archived, 1) if archived else None,
        },
        "settings": runtime.catalog.settings(),
    }


# Sources ---------------------------------------------------------------------------


@router.get("/sources")
def sources(runtime: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    status = _collector(runtime)["sources"]
    return [{**item, "state": status.get(item["id"])} for item in runtime.catalog.sources()]


def _plant(body: SourceIn) -> None:
    if body.kind in WRITTEN_KINDS:
        raise HTTPException(422, t("A derived source appears when its app first writes."))


def _secret(runtime: Runtime, body: SourceIn) -> str | None:
    """The typed password, encrypted; ``None`` keeps the stored one."""

    if body.password is None:
        return None
    return runtime.vault.encrypt(body.password)


@router.post("/sources", status_code=201)
def add_source(body: SourceIn, runtime: RuntimeDep, user: AdminUser) -> dict[str, Any]:
    _plant(body)
    try:
        source = runtime.catalog.save_source(body, create=True, secret=_secret(runtime, body))
    except CatalogError as exc:
        raise _fail(exc) from exc
    runtime.audit(user, "source.add", body.id, {"kind": body.kind, "endpoint": body.endpoint})
    return source


@router.put("/sources/{source_id}")
def update_source(
    source_id: str, body: SourceIn, runtime: RuntimeDep, user: AdminUser
) -> dict[str, Any]:
    if body.id != source_id:
        raise HTTPException(422, t("The id of a source cannot change."))
    _plant(body)
    try:
        source = runtime.catalog.save_source(body, create=False, secret=_secret(runtime, body))
    except CatalogError as exc:
        raise _fail(exc) from exc
    runtime.audit(
        user,
        "source.update",
        source_id,
        {
            "endpoint": body.endpoint,
            "mode": body.mode,
            "password": body.password is not None,
            **{key: getattr(body, key) for key in SOURCE_SETTINGS if key in body.model_fields_set},
        },
    )
    return source


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str, runtime: RuntimeDep, user: AdminUser, with_points: bool = False
) -> None:
    """Remove a source; ``with_points=true`` removes its points and their archive too."""

    try:
        removed = runtime.catalog.delete_source(source_id, with_points=with_points)
    except CatalogError as exc:
        raise _fail(exc) from exc
    runtime.audit(user, "source.delete", source_id, {"points": removed} if removed else None)


class TrustIn(BaseModel):
    thumbprint: str = Field(max_length=200)


@router.post("/sources/{source_id}/trust")
def trust_server(
    source_id: str, body: TrustIn, runtime: RuntimeDep, user: AdminUser
) -> dict[str, Any]:
    """Trust an OPC UA server's certificate by its SHA-256 (G2); empty forgets it."""

    try:
        source = runtime.catalog.trust_server(source_id, body.thumbprint)
    except CatalogError as exc:
        raise _fail(exc) from exc
    runtime.audit(user, "source.trust", source_id, {"thumbprint": body.thumbprint})
    return source


@router.get("/opcua/certificate")
def client_certificate(runtime: RuntimeDep, _user: EditorUser) -> Response:
    """Historian's OPC UA client certificate (DER), for the server's trusted list."""

    cert, _key = certificates.identity(runtime.settings.data_dir)
    return Response(
        cert.read_bytes(),
        media_type="application/pkix-cert",
        headers={"Content-Disposition": 'attachment; filename="plantcraft-historian.der"'},
    )


# A CSV file sent from the page: kept in the data folder, where the collector reads it.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
FILES_DIR = "files"


@router.post("/sources/files", status_code=201)
async def upload_csv(
    request: Request,
    runtime: RuntimeDep,
    user: AdminUser,
    name: Annotated[str, Query(min_length=1, max_length=120)],
) -> dict[str, Any]:
    """Keep a wide CSV (first column the time, one column per tag) in the data folder and answer
    the path a CSV source reads; the same name replaces the file (a newer export)."""

    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.rsplit("/", 1)[-1]).strip("-.") or "data"
    stem = stem[:-4] if stem.lower().endswith(".csv") else stem
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, t("A file sent here holds at most 200 MB."))
        chunks.append(chunk)
    data = b"".join(chunks)
    try:
        head = pd.read_csv(io.BytesIO(data), index_col=0, nrows=200)
        times = pd.to_datetime(head.index, errors="coerce", format="mixed", utc=True)
    except Exception as exc:  # any unreadable file is the sender's to fix
        raise HTTPException(422, t("Not a CSV file the Historian reads: {error}", error=exc))
    if head.empty or not len(head.columns) or times.isna().all():
        raise HTTPException(
            422, t("The first column must be the time and the next ones one column per tag.")
        )
    folder = runtime.settings.data_dir / FILES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{stem}.csv"
    write_atomic(target, data)  # the collector reads the folder: never half a file
    rows = data.count(b"\n") - 1
    runtime.audit(user, "source.file", target.name, {"bytes": size, "columns": len(head.columns)})
    return {"path": str(target.resolve()), "columns": len(head.columns), "rows": max(rows, 0)}


class BrowseIn(BaseModel):
    root: str | None = Field(default=None, max_length=500)


def _request(runtime: Runtime, kind: str, source_id: str, user: Any, detail: Any = None) -> dict:
    try:
        runtime.catalog.source(source_id)
    except CatalogError as exc:
        raise _fail(exc) from exc
    request_id = runtime.catalog.add_request(kind, source_id, user.username, detail)
    return {"request": request_id, "collector": _collector(runtime)["running"]}


@router.post("/sources/{source_id}/test", status_code=202)
def test_source(source_id: str, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    return _request(runtime, "test", source_id, user)


@router.post("/sources/{source_id}/browse", status_code=202)
def browse_source(
    source_id: str, runtime: RuntimeDep, user: EditorUser, body: BrowseIn | None = None
) -> dict[str, Any]:
    return _request(runtime, "browse", source_id, user, {"root": (body or BrowseIn()).root})


class BackfillIn(BaseModel):
    hours: float = Field(default=24, gt=0, le=MAX_HOURS)


@router.post("/sources/{source_id}/backfill", status_code=202)
def backfill_source(
    source_id: str, runtime: RuntimeDep, user: AdminUser, body: BackfillIn | None = None
) -> dict[str, Any]:
    """Copy the source's history of its archived signals into the archive, from ``hours`` ago
    up to where archiving began; the collector does it in the background (``/requests/{id}``)."""

    hours = (body or BackfillIn()).hours
    answer = _request(runtime, "backfill", source_id, user, {"hours": hours})
    runtime.audit(user, "source.backfill", source_id, {"hours": hours})
    return answer


@router.get("/requests/{request_id}")
def request_status(
    request_id: Annotated[int, Path(ge=1, le=2**62)], runtime: RuntimeDep, _user: CurrentUser
) -> dict[str, Any]:
    request = runtime.catalog.request(request_id)
    if request is None:
        raise HTTPException(404, t("Request not found."))
    answer = runtime.archive.request_result(request_id)
    if answer is None:
        return {"id": request_id, "kind": request["kind"], "status": "pending"}
    return {"id": request_id, "kind": request["kind"], **answer}


# Points -----------------------------------------------------------------------------


@router.get("/points")
def points(
    runtime: RuntimeDep, scope: Scope, q: str = "", source: str | None = None
) -> list[dict[str, Any]]:
    found = runtime.catalog.points(q=q.strip()[:200], source_id=source)
    return _with_state(runtime, [item for item in found if scope.signal(item["signal"])])


def _with_state(runtime: Runtime, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Points with their collection state and what the archive holds of them."""

    snaps = runtime.archive.snapshots([item["id"] for item in items])
    stats = runtime.archive.point_stats()
    out = []
    for item in items:
        snap = snaps.get(item["id"]) or {}
        stat = stats.get(item["id"]) or {}
        out.append(
            {
                **item,
                "status": "disabled" if not item["enabled"] else snap.get("status", "waiting"),
                "detail": snap.get("detail", ""),
                "value": outward_one(item["kind"], snap.get("value")),
                "at": snap.get("ts"),
                "reads": snap.get("reads", 0),
                "archived": snap.get("archived", 0),
                "stored_values": stat.get("values", 0),
                "stored_day": stat.get("day", 0),
                "stored_bytes": stat.get("bytes", 0),
                "first": stat.get("first"),
            }
        )
    return out


class PointsIn(BaseModel):
    points: list[PointIn] = Field(min_length=1, max_length=MAX_POINTS_PER_CALL)


@router.post("/points", status_code=201)
def add_points(body: PointsIn, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    result = runtime.catalog.add_points(body.points)
    if result["added"]:
        runtime.audit(user, "points.add", f"{len(result['added'])} points", result["added"][:50])
    return result


@router.get("/points/export")
def export_points(runtime: RuntimeDep, scope: Scope, source_id: str | None = None) -> Response:
    """The point list as CSV (``catalog.points_csv``): edit it, import it back."""

    found = runtime.catalog.points(source_id=source_id)
    text = points_csv.to_csv([item for item in found if scope.signal(item["signal"])])
    # Only safe characters in the file name: it goes into a header (latin-1, no quotes).
    label = "".join(c for c in (source_id or "all") if c.isascii() and (c.isalnum() or c in "-_."))
    name = f"historian-points-{label or 'source'}.csv"
    return Response(
        text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


MAX_IMPORT_BYTES = 10 * 1024 * 1024


@router.post("/points/import")
async def import_points(
    request: Request, runtime: RuntimeDep, user: EditorUser, apply: bool = False
) -> dict[str, Any]:
    """A point list in CSV: what it would add and change (``apply=false``), or do it."""

    raw = await request.body()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(413, t("The file is larger than 10 MB."))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    planned = points_csv.plan(runtime.catalog, text)
    preview = {key: value for key, value in planned.items() if key != "changes"}
    if not apply:
        return preview
    try:
        done = points_csv.apply(runtime.catalog, planned)
    except CatalogError as exc:
        raise _fail(exc) from exc
    runtime.audit(
        user,
        "points.import",
        f"{len(done['added'])} added, {len(done['updated'])} updated",
        {"added": done["added"][:50], "updated": done["updated"][:50]},
    )
    return {**preview, **done}


@router.get("/points/retired")
def retired_points(runtime: RuntimeDep, _user: AdminUser) -> dict[str, Any]:
    """Points retired, kept with their archive until they are deleted for good."""

    return {"points": runtime.catalog.retired(), "days": RETIRED_DAYS}


@router.get("/points/{signal_id:path}/series")
@time_limited
def point_series(
    signal_id: str,
    runtime: RuntimeDep,
    scope: Scope,
    start: str | None = None,
    end: str | None = None,
    step: float | None = None,
    extremes: bool = False,
    run: str | None = None,
    runs: int | None = None,
) -> dict[str, Any]:
    """A signal's trend for the pages, from wherever its mode says; on a grid, ``extremes``
    adds each cell's lowest and highest value (``low``, ``high``; up to a week). A runs point
    answers its runs instead (``run``, ``runs``: as API v1)."""

    in_scope(scope, signal_id)
    try:
        point = runtime.catalog.point(signal_id)
        if point["kind"] == RUNS:
            return {"signal": signal_id, "kind": RUNS, "runs": run_reads(runtime, point, run, runs)}
        begin, finish, step = series_range(start, end, step, default_end=datetime.now(timezone.utc))
        stamps, values = runtime.reader.series(point_ref(point), begin, finish, step)
        bounds = (
            runtime.reader.extremes(point_ref(point), begin, finish, step)
            if extremes and step
            else None
        )
    except CatalogError as exc:
        raise _fail(exc) from exc
    except ContractError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    # Where the quality was not good (G5): uncertain, substituted or bad, from t to the next.
    begin_ms, finish_ms = int(begin.timestamp() * 1000), int(finish.timestamp() * 1000)
    changes = runtime.archive.qualities(int(point["id"]), begin_ms, finish_ms)
    quality = [{"t": iso_ms(np.asarray([at]))[0], "quality": code} for at, code in changes]
    return {
        "signal": signal_id,
        "kind": point["kind"],
        "t": stamps,
        "v": values,
        "quality": quality,
        **({"low": bounds[0], "high": bounds[1]} if bounds else {}),
    }


@router.get("/points/{signal_id:path}/runs")
def point_runs(
    signal_id: str, runtime: RuntimeDep, scope: Scope, limit: int = 50
) -> dict[str, Any]:
    """A runs point's executions for the run picker, newest first."""

    in_scope(scope, signal_id)
    try:
        point = runtime.catalog.point(signal_id)
    except CatalogError as exc:
        raise _fail(exc) from exc
    found = runtime.reader.run_list(point_ref(point), max(1, min(limit, 1000)))
    return {"signal": signal_id, "runs": found if point["kind"] == RUNS else []}


@router.get("/points/{signal_id:path}")
def point(signal_id: str, runtime: RuntimeDep, scope: Scope) -> dict[str, Any]:
    """One point: its settings in effect (``retention_days``, ``scan_seconds``, ``deviation``,
    ``max_seconds``), its ``own`` values (null where it inherits), the ``origins`` of each
    (``point``, ``source`` or ``general``) and its collection state."""

    in_scope(scope, signal_id)
    try:
        found = runtime.catalog.point(signal_id)
    except CatalogError as exc:
        raise _fail(exc) from exc
    return _with_state(runtime, [found])[0]


@router.patch("/points/{signal_id:path}")
def update_point(
    signal_id: str, body: PointPatch, runtime: RuntimeDep, user: EditorUser, scope: Scope
) -> dict[str, Any]:
    in_scope(scope, signal_id)
    try:
        point = runtime.catalog.update_point(signal_id, body)
    except CatalogError as exc:
        raise _fail(exc) from exc
    runtime.audit(user, "point.update", signal_id, body.model_dump(exclude_unset=True))
    return point


class DeleteIn(BaseModel):
    signals: list[str] = Field(min_length=1, max_length=MAX_POINTS_PER_CALL)


@router.post("/points/delete")
def delete_points(body: DeleteIn, runtime: RuntimeDep, user: AdminUser) -> dict[str, Any]:
    """Retire points (admins only): no longer collected nor listed, archive kept, restorable.

    The archive goes for good after ``RETIRED_DAYS`` days, or earlier with ``/points/purge``.
    """

    retired = runtime.catalog.retire_points(body.signals, by=user.username)
    runtime.audit(user, "points.retire", f"{len(retired)} points", body.signals[:50])
    return {"removed": len(retired), "retired": len(retired), "days": RETIRED_DAYS}


class RetiredIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_POINTS_PER_CALL)


class PurgeIn(RetiredIn):
    # The count typed by the person, as on the page: deleting history needs a deliberate act.
    confirm: str = Field(max_length=20)


@router.post("/points/restore")
def restore_points(body: RetiredIn, runtime: RuntimeDep, user: AdminUser) -> dict[str, Any]:
    """Put retired points back with their archive (the collector reads them again)."""

    result = runtime.catalog.restore_points(body.ids)
    runtime.audit(
        user, "points.restore", f"{len(result['restored'])} points", result["restored"][:50]
    )
    return result


@router.post("/points/purge")
def purge_points(body: PurgeIn, runtime: RuntimeDep, user: AdminUser) -> dict[str, Any]:
    """Delete retired points and their archive for good, now (the typed count must match)."""

    if body.confirm.strip() != str(len(body.ids)):
        raise HTTPException(
            422, t("Type {count} to delete these signals for good.", count=len(body.ids))
        )
    signals = {item["id"]: item["signal"] for item in runtime.catalog.retired()}
    purged = runtime.catalog.purge_retired(body.ids)
    names = [signals.get(item, str(item)) for item in purged]
    runtime.audit(user, "points.purge", f"{len(purged)} points", names[:50])
    return {"purged": len(purged)}


# Settings --------------------------------------------------------------------------


@router.get("/settings")
def settings(runtime: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    return runtime.catalog.settings()


@router.put("/settings")
def update_settings(body: dict[str, Any], runtime: RuntimeDep, user: AdminUser) -> dict[str, Any]:
    try:
        result = runtime.catalog.update_settings(body)
    except CatalogError as exc:
        raise _fail(exc) from exc
    runtime.audit(user, "settings.update", "settings", body)
    return result
