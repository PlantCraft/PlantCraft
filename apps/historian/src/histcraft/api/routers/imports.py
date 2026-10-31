"""CSV and Excel imports (Import & export): a file loaded, checked before anything is written.

A person sends the file (``POST /api/imports/check``) and gets a report: its shape, the period,
the tags, and the lines that keep it from being imported. Nothing is written then; the file
waits in ``<data>/imports/pending`` for a day. Confirming (``POST /api/imports``) creates the
import, a source of kind ``import`` (``import-<n>``) with one point per tag, and hands the file
to the collector, which writes the values as they are (the server never writes the archive,
docs/boundary.md) and deletes the file. Deleting an import (``DELETE /api/imports/{id}``) takes
its points and every value along.

An import keeps how its file was read (``options.read``: separator, columns, time format…,
``csv_table.ReadOptions``): a check answers what it detected, so the form starts filled in, and
the next file of the same kind (``into``: last month's lab results, then this month's) is read
the same way into the same import and points, values at a time already there replaced. Each
file is listed in ``options.runs``.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request, Response
from plantcraft_sdk.files import write_atomic, write_json
from plantcraft_sdk.server.queue import queue_answer
from pydantic import BaseModel, Field, ValidationError

from histcraft.api import queue
from histcraft.api.deps import CurrentUser, EditorUser, RuntimeDep
from histcraft.api.runtime import Runtime
from histcraft.catalog import imports as catalog_imports
from histcraft.catalog.models import (
    IMPORT_KIND,
    IMPORT_PREFIX,
    CatalogError,
    PointIn,
    SourceIn,
)
from histcraft.clock import now_ms
from histcraft.collector import imports as collector_imports
from histcraft.config import IMPORTS_DIR, csv_pattern_allowed, outside_csv_folders
from histcraft.i18n import t
from histcraft.sources.csv_table import ReadOptions, read_table

router = APIRouter(prefix="/api", tags=["historian"])

MAX_BYTES = 200 * 1024 * 1024
PENDING_HOURS = 24
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


def _folder(runtime: Runtime, *parts: str) -> Path:
    folder = Path(runtime.settings.data_dir) / IMPORTS_DIR
    for part in parts:
        folder = folder / part
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _zone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, t("Unknown time zone: {name}.", name=name)) from exc
    return name


def _clean_pending(folder: Path) -> None:
    """Files checked but never confirmed go after a day."""

    limit = time.time() - PENDING_HOURS * 3600
    for path in folder.iterdir():
        if path.stat().st_mtime < limit:
            path.unlink(missing_ok=True)


def _tag_problems(tags: list[str]) -> list[str]:
    bad = []
    for tag in tags:
        try:
            PointIn(tag=tag, source_id="import-0")
        except ValueError:
            bad.append(tag)
    return bad


@router.post("/imports/check")
async def check_import(
    request: Request,
    runtime: RuntimeDep,
    user: EditorUser,
    name: Annotated[str, Query(min_length=1, max_length=200)],
    timezone: Annotated[str, Query(max_length=60)] = "UTC",
    options: Annotated[str, Query(max_length=4000)] = "",
    into: Annotated[str, Query(max_length=40)] = "",
) -> dict[str, Any]:
    """Read a file and report what an import would hold; nothing is written. ``options``
    (JSON, ``ReadOptions``) set how it is read; ``into`` names the import it would join."""

    zone = _zone(timezone)
    read = _options(options)
    if into:
        _import(runtime, into)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, t("A file sent here holds at most 200 MB."))
        chunks.append(chunk)
    data = b"".join(chunks)
    file_name = name.rsplit("/", 1)[-1][:200]
    table = read_table(data, zone, options=read, file_name=file_name)
    report = table.report()
    bad = _tag_problems(list(table.series))
    if bad:
        report["errors"].append(
            {
                "message": t("Tags that are empty or longer than 300 characters"),
                "count": len(bad),
                "lines": [],
                "tags": bad[:20],
            }
        )
    digest = hashlib.sha256(data).hexdigest()
    same = [
        source["id"]
        for source in runtime.catalog.sources()
        if source["kind"] == IMPORT_KIND
        and digest
        in {source["options"].get("sha256")}
        | {run.get("sha256") for run in source["options"].get("runs") or []}
    ]
    if same:
        report["warnings"].append(
            {
                "message": t("This file was imported before ({ids})", ids=", ".join(same)),
                "count": len(same),
                "lines": [],
            }
        )
    token = ""
    if not report["errors"]:
        pending = _folder(runtime, "pending")
        _clean_pending(pending)
        token = secrets.token_hex(16)
        write_atomic(pending / f"{token}.csv", data)
        meta = {
            "file_name": file_name,
            "bytes": size,
            "sha256": digest,
            "timezone": zone,
            "user": user.username,
            "options": read.model_dump(),
        }
        write_json(pending / f"{token}.json", meta)
    return {
        "token": token,
        "file_name": file_name,
        "bytes": size,
        "timezone": zone,
        "ok": not report["errors"],
        "report": report,
    }


def _options(text: str) -> ReadOptions:
    try:
        return ReadOptions.model_validate_json(text) if text.strip() else ReadOptions()
    except ValidationError as exc:
        raise HTTPException(
            422, t("Invalid read options: {error}", error=exc.errors()[0]["msg"])
        ) from exc


def _import(runtime: Runtime, import_id: str) -> dict[str, Any]:
    source = next(
        (
            item
            for item in runtime.catalog.sources()
            if item["id"] == import_id and item["kind"] == IMPORT_KIND
        ),
        None,
    )
    if source is None:
        raise HTTPException(404, t("Import {id} not found.", id=import_id))
    return source


class ImportIn(BaseModel):
    token: str = Field(min_length=32, max_length=32)
    name: str = Field(default="", max_length=120)
    # An import to add this file to (read the same way, the same points); empty: a new one.
    into: str = Field(default="", max_length=40)


def _next_id(runtime: Runtime) -> str:
    numbers = [
        int(source["id"][len(IMPORT_PREFIX) :])
        for source in runtime.catalog.sources()
        if source["kind"] == IMPORT_KIND and source["id"][len(IMPORT_PREFIX) :].isdigit()
    ]
    return f"{IMPORT_PREFIX}{max(numbers, default=0) + 1}"


@router.post("/imports", status_code=201)
def create_import(body: ImportIn, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Confirm a checked file: its import and points now, its values by the collector."""

    if not _TOKEN.match(body.token):
        raise HTTPException(422, t("Check the file again."))
    pending = _folder(runtime, "pending")
    data_path, meta_path = pending / f"{body.token}.csv", pending / f"{body.token}.json"
    if not data_path.is_file() or not meta_path.is_file():
        raise HTTPException(410, t("The checked file is no longer here: check it again."))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    read = ReadOptions(**(meta.get("options") or {}))
    table = read_table(
        data_path.read_bytes(), meta["timezone"], options=read, file_name=meta["file_name"]
    )
    if table.errors or not table.series:
        raise HTTPException(422, t("The file has errors: check it again."))
    run = {
        "at": now_ms(),
        "by": user.username,
        "file_name": meta["file_name"],
        "bytes": int(meta["bytes"]),
        "sha256": meta["sha256"],
        "rows": table.rows,
        "values": table.values,
        "start_ms": table.start_ms,
        "end_ms": table.end_ms,
        "warnings": len(table.warnings),
    }
    saved = {**read.model_dump(), "timezone": meta["timezone"]}
    if body.into:
        import_id = _add_to(runtime, body.into, table, run, saved)
    else:
        import_id = _new_import(runtime, body.name or meta["file_name"], table, run, saved, user)
    # The collector writes the values and deletes the file (collector.imports).
    data_path.replace(_folder(runtime) / f"{import_id}.csv")
    write_json(
        _folder(runtime) / f"{import_id}.json",
        {
            "timezone": meta["timezone"],
            "file_name": meta["file_name"],
            "options": read.model_dump(),
        },
    )
    meta_path.unlink(missing_ok=True)
    runtime.audit(
        user,
        "import.add" if body.into else "import.create",
        import_id,
        {"file": meta["file_name"], "tags": len(table.series), "values": table.values},
    )
    return _item(runtime, runtime.catalog.source(import_id))


def _new_import(
    runtime: Runtime, name: str, table: Any, run: dict[str, Any], read: dict[str, Any], user: Any
) -> str:
    import_id = _next_id(runtime)
    options = {
        "file_name": run["file_name"],
        "bytes": run["bytes"],
        "sha256": run["sha256"],
        "shape": table.shape,
        "timezone": read["timezone"],
        "rows": table.rows,
        "values": table.values,
        "start_ms": table.start_ms,
        "end_ms": table.end_ms,
        "imported_by": user.username,
        "warnings": len(table.warnings),
        "read": read,
        "runs": [run],
    }
    try:
        runtime.catalog.save_source(
            SourceIn(id=import_id, name=name.strip()[:120], kind=IMPORT_KIND, options=options),
            create=True,
        )
        runtime.catalog.add_points(catalog_imports.points_of(import_id, table.series.values()))
    except (CatalogError, ValueError) as exc:
        if _exists(runtime, import_id):
            runtime.catalog.delete_source(import_id, with_points=True)
        raise HTTPException(422, str(exc)) from exc
    return import_id


def _add_to(
    runtime: Runtime, import_id: str, table: Any, run: dict[str, Any], read: dict[str, Any]
) -> str:
    """The next file of an import: its new tags become points, its values join the old ones."""

    source = _import(runtime, import_id)
    if (_folder(runtime) / f"{import_id}.csv").exists():
        raise HTTPException(409, t("The last file of this import is still being written."))
    try:
        catalog_imports.add_file(runtime.catalog, source, table, run, read)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return import_id


def _exists(runtime: Runtime, source_id: str) -> bool:
    return any(source["id"] == source_id for source in runtime.catalog.sources())


def _item(runtime: Runtime, source: dict[str, Any]) -> dict[str, Any]:
    states = runtime.archive.state()
    state = states.get(collector_imports.state_key(source["id"])) or {}
    waiting = queue.waiting_file(runtime.settings.data_dir, source["id"]).exists()
    running = state.get("status") == "running"
    status = "writing" if waiting or running else state.get("status", "done")
    total = int(state.get("total") or 0)
    repeat = source["options"].get("repeat") or {}
    checked = states.get(collector_imports.repeat_key(source["id"])) or {}
    return {
        "id": source["id"],
        "name": source["name"],
        "points": source["points"],
        "created": source["created"],
        "status": status,
        "detail": "" if waiting or running else state.get("detail", ""),
        "written": state.get("values"),
        # While written: the step, and the share of its tags done (null while read).
        "step": state.get("step", "") if running else "",
        "progress": round(int(state.get("done") or 0) / total, 3) if running and total else None,
        "queued": waiting and not running,
        **source["options"],
        "repeat": {
            **repeat,
            "checked_ms": checked.get("checked")
            if checked.get("pattern") == repeat.get("pattern")
            else None,
            "files": len(checked.get("files") or {}),
            "problem": checked.get("detail", "")
            if checked.get("pattern") == repeat.get("pattern")
            else "",
        }
        if repeat.get("pattern")
        else {},
    }


@router.get("/imports")
def imports(runtime: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """Every import, newest first, with whether its values are written yet."""

    found = [
        _item(runtime, source)
        for source in runtime.catalog.sources()
        if source["kind"] == IMPORT_KIND
    ]
    return sorted(found, key=lambda item: item["created"], reverse=True)


@router.delete("/imports/{import_id}")
def delete_import(import_id: str, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Delete an import with its points and every value it brought."""

    source = next(
        (
            item
            for item in runtime.catalog.sources()
            if item["id"] == import_id and item["kind"] == IMPORT_KIND
        ),
        None,
    )
    if source is None:
        raise HTTPException(404, t("Import {id} not found.", id=import_id))
    folder = Path(runtime.settings.data_dir) / IMPORTS_DIR
    for suffix in (".csv", ".json"):
        (folder / f"{import_id}{suffix}").unlink(missing_ok=True)
    # The collector deletes the archive of points no longer configured (Collector.reload).
    removed = runtime.catalog.delete_source(import_id, with_points=True)
    runtime.audit(user, "import.delete", import_id, {"file": source["options"].get("file_name")})
    return {"id": import_id, "points": removed}


class RepeatIn(BaseModel):
    # A file or a pattern in its last part (/csv/lab/*.csv) in one of the CSV folders; empty:
    # the import no longer repeats.
    pattern: str = Field(default="", max_length=500)
    check_minutes: float = Field(default=60, ge=5, le=1440)


@router.put("/imports/{import_id}/repeat")
def repeat_import(
    import_id: str, body: RepeatIn, runtime: RuntimeDep, user: EditorUser
) -> dict[str, Any]:
    """Repeat an import from a folder: every ``check_minutes`` the collector reads each file
    there that is new or changed, the way the import reads its files, into the same signals.
    An empty pattern stops it; the values already written stay."""

    source = _import(runtime, import_id)
    pattern = body.pattern.strip()
    if pattern:
        if not csv_pattern_allowed(pattern):
            raise HTTPException(422, outside_csv_folders())
        try:
            found = collector_imports.folder_files(pattern)
        except (OSError, PermissionError) as exc:
            raise HTTPException(422, str(exc)) from exc
        repeat = {"pattern": pattern, "check_minutes": body.check_minutes, "by": user.username}
    else:
        found, repeat = [], {}
    runtime.catalog.set_options(import_id, {**source["options"], "repeat": repeat})
    runtime.audit(user, "import.repeat", import_id, {"pattern": pattern, "files": len(found)})
    return {**_item(runtime, runtime.catalog.source(import_id)), "found": len(found)}


@router.post("/imports/{import_id}/cancel")
def cancel_import(import_id: str, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Cancel a file waiting to be written: a new import goes with its signals, the next file
    of an import leaves its list. A file being written is not stopped (409)."""

    source = _import(runtime, import_id)
    path = queue.waiting_file(runtime.settings.data_dir, import_id)
    state = runtime.archive.state().get(collector_imports.state_key(import_id)) or {}
    if not path.exists():
        raise HTTPException(409, t("Nothing of this import is waiting to be written."))
    if state.get("status") == "running":
        raise HTTPException(409, t("The file is being written: it can no longer be cancelled."))
    path.unlink(missing_ok=True)
    path.with_suffix(".json").unlink(missing_ok=True)
    runs = source["options"].get("runs") or []
    deleted = len(runs) <= 1
    if deleted:
        runtime.catalog.delete_source(import_id, with_points=True)
    else:
        catalog_imports.drop_newest(runtime.catalog, source)
    runtime.audit(user, "import.cancel", import_id, {"file": source["options"].get("file_name")})
    return {"id": import_id, "deleted": deleted}


@router.get("/queue")
def queue_numbers(
    runtime: RuntimeDep,
    _user: CurrentUser,
    window: Annotated[str, Query(pattern="^(1h|24h|7d|30d)$")] = "24h",
) -> dict[str, Any]:
    """The suite's work queue (``plantcraft-queue/1``): the imports' numbers now and over the
    window, the page the queue panel links to, and each file waiting, written or just done."""

    return {
        **queue_answer(runtime.queue_now(), runtime.queue_metrics, window),
        "url": "imports",
        "items": queue.items(
            runtime.catalog, runtime.archive, runtime.settings.data_dir, runtime.settings.root_path
        ),
    }


_EXAMPLES = {
    "wide": (
        "time,FI-101.PV,TI-102.PV,LAB.Viscosity\n"
        "2026-10-01 08:00:00,52.4,181.2,\n"
        "2026-10-01 08:01:00,52.9,181.4,\n"
        "2026-10-01 08:02:00,53.1,181.3,412\n"
        "2026-10-01 08:03:00,52.7,181.6,\n"
    ),
    "long": (
        "time,tag,value,quality\n"
        "2026-10-01T08:00:00-03:00,FI-101.PV,52.4,good\n"
        "2026-10-01T08:00:00-03:00,TI-102.PV,181.2,good\n"
        "2026-10-01T08:01:00-03:00,FI-101.PV,52.9,uncertain\n"
        "2026-10-01T08:01:00-03:00,TI-102.PV,181.4,good\n"
    ),
}


@router.get("/imports/example/{shape}.csv")
def example(shape: str, _user: CurrentUser) -> Response:
    """A small file of each layout the import reads, to start from."""

    if shape not in _EXAMPLES:
        raise HTTPException(404, t("The examples are wide and long."))
    return Response(
        _EXAMPLES[shape],
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="historian-import-{shape}.csv"'},
    )
