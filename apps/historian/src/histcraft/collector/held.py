"""Values the collector read but could not archive, kept on disk until the archive takes them.

The archive is written in one transaction per flush: when the database cannot be reached the
values stay in memory and every flush tries again. They reach this file only when the collector
stops (its lease lost with the database, or a restart) before the database came back; the next
collector of the archive writes them on its first flush and removes the file. One JSON line per
point: ``{"point": <id>, "kind": "number" | "text", "samples": [[ms, value], ...]}``, where a
number point's "no data" marker (NaN) is ``null``.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)
FILE_NAME = "held-values.jsonl"

Batch = dict[int, tuple[str, list[tuple[int, Any]]]]


def held_path(data_dir: Path) -> Path:
    return Path(data_dir) / "collector" / FILE_NAME


def save(path: Path, batch: Batch) -> int:
    """Add ``batch`` to the file (atomically, beside what it already holds); values saved."""

    merged = load(path)
    for point, (kind, samples) in batch.items():
        if samples:
            old = merged.get(point, (kind, []))[1]
            merged[point] = (kind, [*old, *samples])
    count = sum(len(samples) for _, samples in merged.values())
    if not count:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(".tmp")
    with scratch.open("w", encoding="utf-8") as handle:
        for point, (kind, samples) in merged.items():
            values = [[at, _out(value)] for at, value in samples]
            line = {"point": point, "kind": kind, "samples": values}
            handle.write(json.dumps(line, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(scratch, path)
    return count


def load(path: Path) -> Batch:
    """The values in the file by point (empty when there is none); a bad line is skipped."""

    if not path.exists():
        return {}
    found: Batch = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            item = json.loads(line)
            point, kind = int(item["point"]), str(item["kind"])
            samples = [(int(at), _in(kind, value)) for at, value in item["samples"]]
        except (ValueError, KeyError, TypeError):
            LOGGER.warning("Held values: line %s of %s is not readable, skipped", number, path)
            continue
        old = found.get(point, (kind, []))[1]
        found[point] = (kind, [*old, *samples])
    return found


def _out(value: Any) -> Any:
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _in(kind: str, value: Any) -> Any:
    return math.nan if value is None and kind == "number" else value
