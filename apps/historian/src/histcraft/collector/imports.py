"""The collector's part of a CSV import: write the values of each confirmed file, then delete it.

The server checks a file and creates the import (``api/routers/imports.py``); the values are
archived here, as they are in the file (no compression: an import is data already chosen), with
their qualities and each point's newest value. The file is deleted once written, or when its
import is gone. While it is written, and after, the archive state ``import:<id>`` says how it
goes (``status`` running, done or error, ``step``, ``done`` of ``total`` tags, ``started``,
``finished``): the Imports list and the suite's work queue (``GET /api/queue``) read it.

An import that repeats from a folder (``options.repeat``: a file or a pattern in one of the CSV
folders, owner 2026-10-26) is checked every ``check_minutes``: each file new or changed since
the last check (its time and size, kept in ``import-repeat:<id>``) is read the way the import
reads its files, joins it as a person's next file would (new tags become points) and is written
the same way. The folder's files are only read: never moved, renamed or changed.
"""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from histcraft.archive.store import ArchiveStore, now_ms
from histcraft.catalog import imports as catalog_imports
from histcraft.catalog.models import IMPORT_KIND
from histcraft.catalog.store import CatalogStore
from histcraft.config import IMPORTS_DIR, csv_path_allowed, csv_pattern_allowed, outside_csv_folders
from histcraft.i18n import t
from histcraft.sources.csv_table import ReadOptions, Table, read_table

LOGGER = logging.getLogger(__name__)

# A file read from a folder holds at most what a person may send (api/routers/imports.py).
MAX_BYTES = 200 * 1024 * 1024
# Files one check of a folder writes at most (the oldest first); the next check takes the rest.
FILES_PER_CHECK = 20
# How often the progress of a file being written is saved, in seconds.
PROGRESS_SECONDS = 1.0


def state_key(import_id: str) -> str:
    return f"import:{import_id}"


def repeat_key(import_id: str) -> str:
    return f"import-repeat:{import_id}"


def waiting(data_dir: Path) -> list[Path]:
    """Confirmed imports whose values are not written yet."""

    folder = Path(data_dir) / IMPORTS_DIR
    return sorted(folder.glob("import-*.csv")) if folder.is_dir() else []


def _source(catalog: CatalogStore, import_id: str) -> dict[str, Any] | None:
    return catalog_imports.find(catalog, import_id)


def archive_values(
    import_id: str,
    table: Table,
    catalog: CatalogStore,
    archive: ArchiveStore,
    progress: dict[str, Any],
) -> int:
    """Archive a read file's values into the import's points; the values written. ``progress``
    (the state ``import:<id>`` while running) gets ``done`` of ``total`` tags as it goes."""

    points = {point["tag"]: point for point in catalog.points(source_id=import_id)}
    items = [(tag, series) for tag, series in table.series.items() if len(series.times)]
    progress.update(step=t("Writing the values"), done=0, total=len(items))
    archive.set_state(state_key(import_id), progress)
    saved = time.monotonic()
    written, snapshots, qualities = 0, [], []
    for index, (tag, series) in enumerate(items, start=1):
        point = points.get(tag)
        if point is not None:
            samples = list(zip(series.times.tolist(), series.values, strict=True))
            written += archive.replace(int(point["id"]), point["kind"], samples)
            qualities += [(int(point["id"]), at, code) for at, code in series.qualities]
            at, value = samples[-1]
            snapshots.append({"point": int(point["id"]), "ts": at, "value": value, "status": "ok"})
        if time.monotonic() - saved >= PROGRESS_SECONDS:
            saved = time.monotonic()
            progress["done"] = index
            archive.set_state(state_key(import_id), progress)
    if qualities:
        archive.put_qualities(qualities)
    if snapshots:
        archive.put_snapshots(snapshots)
    return written


def _failed(progress: dict[str, Any], exc: Exception) -> dict[str, Any]:
    keep = {key: progress[key] for key in ("started", "by", "file_name") if key in progress}
    return {
        **keep,
        "status": "error",
        "detail": t("The values could not be written: {error}", error=exc),
        "finished": now_ms(),
    }


def write_import(path: Path, catalog: CatalogStore, archive: ArchiveStore) -> dict[str, Any]:
    """Archive one confirmed file's values and delete it; the outcome."""

    import_id = path.stem
    meta_path = path.with_suffix(".json")
    source = _source(catalog, import_id)
    progress: dict[str, Any] = {"status": "running", "started": now_ms()}
    try:
        if source is None:  # deleted before its values were written
            return {"status": "gone"}
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        progress.update(
            by=meta.get("user") or source["options"].get("imported_by") or "",
            file_name=meta.get("file_name") or "",
            step=t("Reading the file"),
        )
        archive.set_state(state_key(import_id), progress)
        table = read_table(
            path.read_bytes(),
            meta.get("timezone") or "UTC",
            options=ReadOptions(**(meta.get("options") or {})),
            file_name=meta.get("file_name") or "",
        )
        written = archive_values(import_id, table, catalog, archive, progress)
        outcome = {
            "status": "done",
            "values": written,
            "started": progress["started"],
            "finished": now_ms(),
            "by": progress["by"],
            "file_name": progress["file_name"],
        }
        LOGGER.info("Import %s: %s values archived", import_id, written)
    except Exception as exc:  # noqa: BLE001 - the list says what failed
        LOGGER.exception("Import %s failed", import_id)
        outcome = _failed(progress, exc)
    archive.set_state(state_key(import_id), outcome)
    path.unlink(missing_ok=True)
    meta_path.unlink(missing_ok=True)
    return outcome


# Repeating from a folder -----------------------------------------------------------------


def folder_files(pattern: str) -> list[Path]:
    """The files of a repeat's pattern, oldest first (by modification time). Raises
    ``PermissionError`` outside the CSV folders, ``FileNotFoundError`` when the folder is
    missing."""

    if not csv_pattern_allowed(pattern):
        raise PermissionError(outside_csv_folders())
    path = Path(pattern).expanduser()
    if not path.parent.is_dir():
        raise FileNotFoundError(t("Folder not found: {path}", path=path.parent))
    if any(ch in path.name for ch in "*?["):
        found = [Path(name) for name in glob.glob(str(path)) if Path(name).is_file()]
    else:
        found = [path] if path.is_file() else []
    # A link out of the CSV folders is never followed (security audit 2026-10-22).
    found = [item for item in found if csv_path_allowed(item)]
    return sorted(found, key=lambda item: item.stat().st_mtime_ns)


def repeating(catalog: CatalogStore) -> list[dict[str, Any]]:
    """The imports that repeat from a folder."""

    return [
        source
        for source in catalog.sources()
        if source["kind"] == IMPORT_KIND
        and source["enabled"]
        and (source["options"].get("repeat") or {}).get("pattern")
    ]


def due(source: dict[str, Any], archive: ArchiveStore, at: int | None = None) -> bool:
    """Whether a repeating import's folder is checked now."""

    repeat = source["options"].get("repeat") or {}
    seen = archive.state().get(repeat_key(source["id"])) or {}
    # A new pattern, or files left over by the last check (FILES_PER_CHECK), go at once.
    if seen.get("pattern") != repeat.get("pattern") or seen.get("waiting"):
        return True
    minutes = float(repeat.get("check_minutes") or 60)
    return (at or now_ms()) - int(seen.get("checked") or 0) >= minutes * 60_000


def check_folder(
    source: dict[str, Any], catalog: CatalogStore, archive: ArchiveStore
) -> dict[str, Any]:
    """Check a repeating import's folder once: write each new or changed file. The state kept
    in ``import-repeat:<id>`` (files seen, when, and what went wrong)."""

    import_id = source["id"]
    repeat = source["options"].get("repeat") or {}
    pattern = str(repeat.get("pattern") or "")
    seen = archive.state().get(repeat_key(import_id)) or {}
    files: dict[str, list[int]] = (
        dict(seen.get("files") or {}) if seen.get("pattern") == pattern else {}
    )
    state: dict[str, Any] = {"pattern": pattern, "checked": now_ms(), "files": files, "detail": ""}
    try:
        found = folder_files(pattern)
    except (OSError, PermissionError) as exc:
        state["detail"] = str(exc)
        archive.set_state(repeat_key(import_id), state)
        return state
    present = {str(path) for path in found}
    for name in [name for name in files if name not in present]:
        del files[name]
    fresh = []
    for path in found:
        stat = path.stat()
        if files.get(str(path)) != [stat.st_mtime_ns, stat.st_size]:
            fresh.append((path, [stat.st_mtime_ns, stat.st_size]))
    state["waiting"] = max(0, len(fresh) - FILES_PER_CHECK)
    problems = []
    for path, signature in fresh[:FILES_PER_CHECK]:
        problem = _write_file(path, signature[1], catalog, archive, import_id, repeat)
        files[str(path)] = signature
        if problem:
            problems.append(f"{path.name}: {problem}")
        # A source deleted meanwhile ends the check.
        if _source(catalog, import_id) is None:
            break
    state["detail"] = "; ".join(problems)[:1000]
    state["written"] = len(fresh[:FILES_PER_CHECK]) - len(problems)
    archive.set_state(repeat_key(import_id), state)
    return state


def _write_file(
    path: Path,
    size: int,
    catalog: CatalogStore,
    archive: ArchiveStore,
    import_id: str,
    repeat: dict[str, Any],
) -> str:
    """Read one file of a folder into its import and write it; what went wrong, or ''."""

    by = str(repeat.get("by") or "")
    progress: dict[str, Any] = {
        "status": "running",
        "started": now_ms(),
        "by": by,
        "file_name": path.name,
        "step": t("Reading the file"),
    }
    if size > MAX_BYTES:
        problem = t("A file read from a folder holds at most 200 MB.")
        archive.set_state(state_key(import_id), _failed(progress, ValueError(problem)))
        return problem
    source = _source(catalog, import_id)
    if source is None:
        return ""
    archive.set_state(state_key(import_id), progress)
    try:
        data = path.read_bytes()
        read = dict(source["options"].get("read") or {})
        zone = str(read.pop("timezone", "") or source["options"].get("timezone") or "UTC")
        table = read_table(data, zone, options=ReadOptions(**read), file_name=path.name)
        if table.errors or not table.series:
            first = table.errors[0]["message"] if table.errors else t("No values in the file.")
            raise ValueError(first)
        run = {
            "at": now_ms(),
            "by": by,
            "file_name": path.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "rows": table.rows,
            "values": table.values,
            "start_ms": table.start_ms,
            "end_ms": table.end_ms,
            "warnings": len(table.warnings),
            "folder": True,
        }
        catalog_imports.add_file(catalog, source, table, run, {**read, "timezone": zone})
        written = archive_values(import_id, table, catalog, archive, progress)
    except Exception as exc:  # noqa: BLE001 - the import's state says why
        LOGGER.warning("Import %s: %s not written: %s", import_id, path, exc)
        archive.set_state(state_key(import_id), _failed(progress, exc))
        return str(exc)
    archive.set_state(
        state_key(import_id),
        {
            "status": "done",
            "values": written,
            "started": progress["started"],
            "finished": now_ms(),
            "by": by,
            "file_name": path.name,
        },
    )
    LOGGER.info("Import %s: %s values archived from %s", import_id, written, path)
    return ""
