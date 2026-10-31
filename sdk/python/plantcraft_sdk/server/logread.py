"""Reading a server's own log back, newest first, with filters.

Every server writes its records to ``<data_dir>/logs/<app>.jsonl`` and its rotated copies
(``.1`` ... ``.4``, :mod:`plantcraft_sdk.server.logs`). ``GET /api/ops/logs`` answers what
:func:`read_logs` finds there, for PlantCraft's Operations › Logs, which asks every server and
shows one list (with a token of the ``ops`` scope, like the metrics). The files are bounded
(10 MB each, five of them), so a read scans them as they are, newest line first, and stops at
``limit`` records, at the first record older than ``since``, or after ``MAX_SCAN_BYTES``. A
line that is not JSON (written by something else) is skipped. What a record carries was
already redacted when it was written.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_RANK = {name: index for index, name in enumerate(LEVELS)}
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
# What one read scans at most (the five files of a server are 50 MB at most).
MAX_SCAN_BYTES = 64 * 1024 * 1024
# A record's longest text in an answer (the traceback of an error is kept whole up to this).
MAX_TEXT = 8000


def log_files(path: str | Path | None) -> list[Path]:
    """The log file and its rotated copies that exist, newest first."""

    if path is None:
        return []
    path = Path(path)
    found = [path] if path.is_file() else []
    index = 1
    while (copy := path.with_name(f"{path.name}.{index}")).is_file():
        found.append(copy)
        index += 1
    return found


def level_rank(level: str | None) -> int:
    return _RANK.get(str(level or "").upper(), _RANK["INFO"])


def _instant(text: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _clip(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (value[:MAX_TEXT] if isinstance(value, str) else value)
        for key, value in record.items()
    }


def read_logs(
    path: str | Path | None,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    level: str | None = None,
    text: str | None = None,
    request_id: str | None = None,
    logger: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """The records that match, newest first: ``{"records", "truncated", "scanned_bytes"}``.

    ``level`` is the lowest level kept (``WARNING`` keeps warnings, errors and critical ones);
    ``text`` is looked for, ignoring case, in the message, the logger and the error; ``logger``
    keeps a logger and its children (``linkcraft.monitor`` keeps ``linkcraft.monitor.x``).
    ``truncated`` is True when the read stopped at ``limit`` or at the scan budget with older
    lines left unread."""

    limit = max(1, min(int(limit), MAX_LIMIT))
    lowest = level_rank(level) if level else 0
    needle = (text or "").strip().lower()
    wanted_request = (request_id or "").strip()
    wanted_logger = (logger or "").strip()
    records: list[dict[str, Any]] = []
    scanned = 0
    truncated = False
    finished = False
    for file in log_files(path):
        if finished:
            break
        try:
            data = file.read_bytes()
        except OSError:
            continue
        scanned += len(data)
        for raw in reversed(data.splitlines()):
            # Cheap tests on the raw line before parsing it.
            if wanted_request and wanted_request.encode() not in raw:
                continue
            line = raw.decode("utf-8", "replace")
            if needle and needle not in line.lower():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            moment = _instant(record.get("time"))
            if moment is None:
                continue
            if since is not None and moment < since:
                finished = True  # every older line is older still
                break
            if until is not None and moment > until:
                continue
            if level_rank(record.get("level")) < lowest:
                continue
            if wanted_request and record.get("request_id") != wanted_request:
                continue
            name = str(record.get("logger") or "")
            if wanted_logger and not (
                name == wanted_logger or name.startswith(f"{wanted_logger}.")
            ):
                continue
            if needle and not any(
                needle in str(record.get(key) or "").lower()
                for key in ("message", "logger", "error")
            ):
                continue
            records.append(_clip(record))
            if len(records) >= limit:
                truncated = True
                finished = True
                break
        if not finished and scanned >= MAX_SCAN_BYTES:
            truncated = True
            break
    return {"records": records, "truncated": truncated, "scanned_bytes": scanned}


__all__ = ["DEFAULT_LIMIT", "LEVELS", "MAX_LIMIT", "level_rank", "log_files", "read_logs"]
