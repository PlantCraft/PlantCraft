"""The data lake feed: a saved export an administrator sends every hour or every day, as files.

A plant's data lake (or its MES's) takes files from a landing folder: a share it mounts, or a
folder its own agent picks up. The collector writes each saved export whose ``lake`` is
``hourly`` or ``daily`` into ``HISTCRAFT_LAKE_DIR`` (``/lake`` in an installation, the install
folder's ``data/lake-export/``), one CSV per period, so nothing leaves the server by itself: the
lake comes to read, the Historian opens no connection.

- ``<lake>/<export>/date=YYYY-MM-DD/<export>_<YYYYMMDDTHHMM>Z.csv``: long format, one row per
  value, ``time`` (UTC, ISO 8601), ``signal``, ``tag``, ``value``, ``unit``; the folders are
  Hive-style partitions, which Spark, Databricks, Fabric, Athena and DuckDB read as they are.
- ``<lake>/<export>/signals.csv``: each tag with its name, unit, kind and range.
- A file is written beside its place and renamed into it: a reader never sees half a file, and
  the same period written again replaces the file (an ingest keyed on the name stays right).
- Periods are UTC hours or days, written once they have ended (and ``LAG_MS`` has passed, for
  the last values to be flushed). After a stop the feed catches up from where it left off, at
  most ``CATCH_UP`` periods per pass; a new feed starts with the last period that ended.
- Day folders older than ``HISTCRAFT_LAKE_KEEP_DAYS`` (7; 0 keeps them) are deleted, so a lake
  that stopped reading never fills the server's disk.

Only the tags listed in the saved export are sent, and only those archived here; the asset tree
stays in PlantCraft (it is read with a person's token, and the feed runs as nobody). That is why
only an administrator turns a feed on (``api/routers/export.py``).
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from histcraft.archive.query import PointRef, Reader
from histcraft.db import Store
from histcraft.i18n import t

LOGGER = logging.getLogger(__name__)

SCHEDULES = {"hourly": 3_600_000, "daily": 86_400_000}
# Minutes after a period ends before it is written: the collector's last values reach the archive.
LAG_MS = 5 * 60_000
# Periods written per pass at most (a day of hours): a long stop catches up over a few passes.
CATCH_UP = 24
DAY_FOLDER = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")
COLUMNS = ("time", "signal", "tag", "value", "unit")
SIGNAL_COLUMNS = ("signal", "tag", "name", "description", "unit", "kind", "low", "high")


class LakeFeeds(Store):
    """Where each feed is: the next period to write and how the last one went."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS lake_feeds (
        export_id TEXT PRIMARY KEY,
        schedule TEXT NOT NULL,
        next_start BIGINT NOT NULL,
        last_file TEXT NOT NULL DEFAULT '',
        last_rows INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        updated TEXT NOT NULL
    );
    """

    def all(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM lake_feeds").fetchall()
        return {row["export_id"]: dict(row) for row in rows}

    def save(
        self,
        export_id: str,
        schedule: str,
        next_start: int,
        *,
        last_file: str = "",
        last_rows: int = 0,
        last_error: str = "",
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO lake_feeds VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (export_id) DO UPDATE SET schedule = excluded.schedule,"
                " next_start = excluded.next_start, last_file = excluded.last_file,"
                " last_rows = excluded.last_rows, last_error = excluded.last_error,"
                " updated = excluded.updated",
                (
                    export_id,
                    schedule,
                    next_start,
                    last_file,
                    last_rows,
                    last_error[:500],
                    self._now(),
                ),
            )

    def forget(self, keep: set[str]) -> None:
        """Drop the state of feeds turned off or deleted (a feed turned on again starts anew)."""

        with self._lock, self._connect() as connection:
            for export_id in [row for row in self.all() if row not in keep]:
                connection.execute("DELETE FROM lake_feeds WHERE export_id = ?", (export_id,))


def folder_name(export: dict[str, Any]) -> str:
    """The export's folder: its name in lowercase letters, digits and dashes, then its id (two
    exports of one name never share a folder; a rename starts a new one)."""

    slug = re.sub(r"[^a-z0-9]+", "-", str(export.get("name", "")).lower()).strip("-")[:60]
    return f"{slug or 'export'}-{export['id']}"


def due(schedule: str, next_start: int | None, now_ms: int) -> list[tuple[int, int]]:
    """The periods ``(start, end)`` in ms to write now, oldest first."""

    size = SCHEDULES[schedule]
    ready = now_ms - LAG_MS
    if next_start is None:
        # A new feed: the last period that ended, not the archive's whole past.
        next_start = (ready // size) * size - size
    periods = []
    start = next_start
    while start + size <= ready and len(periods) < CATCH_UP:
        periods.append((start, start + size))
        start += size
    return periods


def _iso(ms: int) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds")[:-6]
        + "Z"
    )


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value) if value == value else ""
    return str(value)


def _write(path: Path, text: str) -> None:
    """Write beside ``path`` and rename into it: readers see the whole file or none."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(text, encoding="utf-8", newline="")
    os.replace(temporary, path)


def _signals_csv(points: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(SIGNAL_COLUMNS)
    for point in points:
        writer.writerow(
            [
                point["signal"],
                point.get("tag", ""),
                point.get("name") or "",
                point.get("description") or "",
                point.get("unit") or "",
                point.get("kind") or "",
                _cell(point.get("low")),
                _cell(point.get("high")),
            ]
        )
    return out.getvalue()


def write_period(
    lake: Path,
    export: dict[str, Any],
    points: list[dict[str, Any]],
    reader: Reader,
    ref: Callable[[dict[str, Any]], PointRef],
    start_ms: int,
    end_ms: int,
) -> tuple[Path, int, list[str]]:
    """One period's file: its path, its rows and the tags that could not be read."""

    start = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    end = datetime.fromtimestamp(end_ms / 1000, timezone.utc)
    step = export.get("step_seconds")
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    rows, failed = 0, []
    for point in points:
        try:
            times, values = reader.series_arrays(
                ref(point), start, end, float(step) if step else None
            )
        except Exception as exc:  # noqa: BLE001 - one tag that fails leaves the others
            failed.append(f"{point['signal']}: {exc}"[:200])
            continue
        for stamp, value in zip(times, values, strict=False):
            # A read carries the value in effect at the start; a period keeps only its own.
            text = _cell(value.item() if hasattr(value, "item") else value)
            if not start_ms <= int(stamp) < end_ms or text == "":
                continue
            unit = point.get("unit") or ""
            writer.writerow([_iso(int(stamp)), point["signal"], point.get("tag", ""), text, unit])
            rows += 1
    name = folder_name(export)
    path = lake / name / f"date={start:%Y-%m-%d}" / f"{name}_{start:%Y%m%dT%H%M}Z.csv"
    _write(path, out.getvalue())
    return path, rows, failed


def prune(lake: Path, keep_days: int, now_ms: int) -> int:
    """Delete day folders older than ``keep_days`` (0: never); only ``date=`` folders, only in
    the lake folder's export folders."""

    if keep_days <= 0 or not lake.is_dir():
        return 0
    oldest = (
        datetime.fromtimestamp(now_ms / 1000, timezone.utc) - timedelta(days=keep_days)
    ).date()
    removed = 0
    for export in lake.iterdir():
        if not export.is_dir() or export.is_symlink():
            continue
        for day in export.iterdir():
            found = DAY_FOLDER.match(day.name)
            if not found or not day.is_dir() or day.is_symlink():
                continue
            try:
                stale = date.fromisoformat(found.group(1)) < oldest
            except ValueError:
                continue
            if stale:
                shutil.rmtree(day, ignore_errors=True)
                removed += 1
    return removed


def feed(
    lake: Path,
    exports: list[dict[str, Any]],
    feeds: LakeFeeds,
    points: list[dict[str, Any]],
    reader: Reader,
    ref: Callable[[dict[str, Any]], PointRef],
    now_ms: int,
    *,
    keep_days: int = 7,
) -> list[Path]:
    """Write every period that is due, for every saved export with a feed on; the files written."""

    scheduled = [item for item in exports if item.get("lake") in SCHEDULES]
    feeds.forget({item["id"] for item in scheduled})
    if not scheduled:
        return []
    state = feeds.all()
    archived = {
        point["signal"]: point
        for point in points
        if (point.get("mode") or "archive") in {"archive", "both"}
    }
    written: list[Path] = []
    for export in scheduled:
        schedule = export["lake"]
        known = state.get(export["id"])
        next_start = known["next_start"] if known and known["schedule"] == schedule else None
        chosen = [archived[signal] for signal in export.get("signals") or [] if signal in archived]
        absent = [signal for signal in export.get("signals") or [] if signal not in archived]
        for start, end in due(schedule, next_start, now_ms):
            note = (
                t("Not archived by the Historian: {signals}", signals=", ".join(absent[:5]))
                if absent
                else ""
            )
            try:
                if not chosen:
                    raise ValueError(t("No tag of this export is archived by the Historian."))
                folder = lake / folder_name(export)
                folder.mkdir(parents=True, exist_ok=True)
                _write(folder / "signals.csv", _signals_csv(chosen))
                path, rows, failed = write_period(lake, export, chosen, reader, ref, start, end)
            except Exception as exc:  # noqa: BLE001 - a full disk or a gone share: say so, retry
                LOGGER.warning("Lake feed %s: %s", export["id"], exc)
                feeds.save(
                    export["id"],
                    schedule,
                    start,
                    last_file=known["last_file"] if known else "",
                    last_error=str(exc),
                )
                break
            written.append(path)
            problems = "; ".join(item for item in [note, *failed] if item)
            feeds.save(
                export["id"],
                schedule,
                end,
                last_file=str(path.relative_to(lake)),
                last_rows=rows,
                last_error=problems,
            )
            known = {"last_file": str(path.relative_to(lake))}
    removed = prune(lake, keep_days, now_ms)
    if removed:
        LOGGER.info("Lake feed: %s day folder(s) past %s days deleted", removed, keep_days)
    return written
