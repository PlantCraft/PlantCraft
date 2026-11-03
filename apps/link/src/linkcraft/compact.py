"""Give the disk back after the history was thinned.

SQLite reuses the pages a delete frees, but the file keeps its size until they are handed back.
The hourly upkeep (``LINKCRAFT_HISTORY_DAYS``, ``LINKCRAFT_HISTORY_FULL_DAYS``) deletes old rows;
at 3 months of a 2,050-loop plant the file stayed at 23.8 GB with 9 GB of it free (2026-11-02).

- A new database is made with ``auto_vacuum = INCREMENTAL`` (``create_incremental``), and the
  hourly upkeep hands its free pages back a few megabytes at a time (``release_free``), each step
  a short write of its own: the file follows the history down without anyone doing anything.
- A database made before that keeps ``auto_vacuum = NONE`` until ``linkcraft compact`` runs once:
  ``VACUUM`` rewrites the whole file (about 16 s for 1.9 GB on a cloud machine) and holds the
  database meanwhile, so it runs by hand, in a quiet hour, only when enough is free and the disk
  can hold the copy. It turns on ``INCREMENTAL`` on the way, so it is needed only that once.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

# Compact only when at least this share of the file is free pages (``--min-free``).
MIN_FREE = 0.2
# PRAGMA auto_vacuum: 0 none, 1 full, 2 incremental.
INCREMENTAL = 2
# What one upkeep hands back at most, in steps of this many pages (each its own write).
RELEASE_MAX_BYTES = 1 << 30
RELEASE_STEP_PAGES = 2048
RELEASE_PAUSE_SECONDS = 0.05


def create_incremental(path: Path) -> bool:
    """Make the database at ``path`` with ``auto_vacuum = INCREMENTAL`` when it does not exist
    yet (the mode is fixed when the first table is written); ``True`` when it made it."""

    if path.exists() and path.stat().st_size > 0:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        connection.execute("VACUUM")
    finally:
        connection.close()
    return True


def incremental(path: Path) -> bool:
    connection = sqlite3.connect(path, timeout=30)
    try:
        return int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]) == INCREMENTAL
    finally:
        connection.close()


def release_free(
    path: Path,
    *,
    max_bytes: int = RELEASE_MAX_BYTES,
    step_pages: int = RELEASE_STEP_PAGES,
    pause: float = RELEASE_PAUSE_SECONDS,
) -> int:
    """Hand back up to ``max_bytes`` of the free pages of an ``INCREMENTAL`` database, a step at
    a time; the bytes handed back (0 for a database without ``INCREMENTAL``)."""

    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        if int(connection.execute("PRAGMA auto_vacuum").fetchone()[0]) != INCREMENTAL:
            return 0
        size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        released = 0
        while released < max_bytes:
            free = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            if not free:
                break
            pages = min(free, step_pages, max(1, (max_bytes - released) // size))
            # The pragma works as its rows are read: fetchall() runs it to the end.
            connection.execute(f"PRAGMA incremental_vacuum({int(pages)})").fetchall()
            connection.commit()
            released += pages * size
            if pause:
                time.sleep(pause)
        if released:
            connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchall()
        return released
    finally:
        connection.close()


def _pages(connection: sqlite3.Connection) -> tuple[int, int, int]:
    size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    free = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    return size, count, free


def compact(path: Path, *, min_free: float = MIN_FREE, dry_run: bool = False) -> dict[str, Any]:
    """Rewrite the database at ``path`` without its free pages; what it found and did."""

    connection = sqlite3.connect(path, timeout=60)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        size, count, free = _pages(connection)
        before = path.stat().st_size
        answer: dict[str, Any] = {
            "path": str(path),
            "size_bytes": before,
            "free_bytes": free * size,
            "free_share": round(free / count, 3) if count else 0.0,
        }
        disk = shutil.disk_usage(path.parent).free
        if not count or free / count < min_free:
            return {**answer, "status": "skipped", "reason": f"less than {min_free:.0%} free"}
        if disk < before - free * size:
            return {**answer, "status": "skipped", "reason": "the disk cannot hold the copy"}
        if dry_run:
            return {**answer, "status": "would_compact"}
        started = time.monotonic()
        # From now on the hourly upkeep hands free pages back itself (release_free).
        connection.execute("PRAGMA auto_vacuum = INCREMENTAL")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {
            **answer,
            "status": "ok",
            "seconds": round(time.monotonic() - started, 1),
            "size_after_bytes": path.stat().st_size,
        }
    finally:
        connection.close()
