"""``linkcraft compact``: give the disk back after the history was thinned (2026-10-31).

SQLite reuses the pages a delete frees, but the file keeps its size until ``VACUUM`` rewrites
it. The hourly upkeep (``LINKCRAFT_HISTORY_DAYS``, ``LINKCRAFT_HISTORY_FULL_DAYS``) stops the
growth; a file that grew before it (F9: 18.5 GB) shrinks only with this command. ``VACUUM``
writes a whole copy and holds the database while it does (about 16 s for 1.9 GB on a cloud
machine), so it runs by hand, in a quiet hour, and only when enough is free and the disk can
hold the copy.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any

# Compact only when at least this share of the file is free pages (``--min-free``).
MIN_FREE = 0.2


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
