"""What the archive store's parts share (``archive.store``): sizes, the statements that write
chunks and hour counts, and the array helpers that join, merge and count runs of values."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np

CHUNK_VALUES = 10_000
HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
# Hours of ``point_hours`` kept: a week, for "values per day" and its trend.
COUNT_HOURS = 7 * 24
_COUNT = (
    "INSERT INTO point_hours VALUES (?, ?, ?) ON CONFLICT(point, hour) DO UPDATE"
    " SET n = point_hours.n + excluded.n"
)

_PUT_CHUNK = (
    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?) ON CONFLICT(point, t0) DO UPDATE"
    " SET t1 = excluded.t1, n = excluded.n, data = excluded.data"
)
_PUT_CHUNKS_MANY = (
    "INSERT INTO chunks SELECT * FROM unnest(?::bigint[], ?::bigint[], ?::bigint[], ?::bigint[],"
    " ?::bytea[]) ON CONFLICT(point, t0) DO UPDATE"
    " SET t1 = excluded.t1, n = excluded.n, data = excluded.data"
)
_COUNT_MANY = (
    "INSERT INTO point_hours SELECT * FROM unnest(?::bigint[], ?::bigint[], ?::bigint[])"
    " ON CONFLICT(point, hour) DO UPDATE SET n = point_hours.n + excluded.n"
)


def _hour_counts(point: int, times: list[int]) -> list[tuple[int, int, int]]:
    """``(point, hour, values)`` rows of ``point_hours`` for values at ``times`` (ms)."""

    if not times:
        return []
    hours, counts = np.unique(np.asarray(times, dtype=np.int64) // HOUR_MS, return_counts=True)
    return [(point, int(hour) * HOUR_MS, int(count)) for hour, count in zip(hours, counts)]


# Every table keyed by point, in the order writes take them (``delete_points``).
_POINT_TABLES = (
    "rollups",
    "rollups_coarse",
    "chunks",
    "point_hours",
    "snapshots",
    "qualities",
    "point_totals",
    "run_series",
    "lab_samples",
    "edits",
)


def _marks(items: list[Any]) -> str:
    return ",".join("?" for _ in items)


def _merge(
    old_times: np.ndarray, old_values: list[Any], new_times: np.ndarray, new_values: list[Any]
) -> tuple[np.ndarray, list[Any]]:
    """Two runs of one point as one, newest value winning on equal times."""

    merged: dict[int, Any] = {}
    for at, value in zip(old_times.tolist(), old_values, strict=True):
        merged[at] = value
    for at, value in zip(new_times.tolist(), new_values, strict=True):
        merged[at] = value
    times = sorted(merged)
    return np.asarray(times, dtype=np.int64), [merged[at] for at in times]


def _hour_counts_many(runs: dict[int, tuple[str, np.ndarray, Any]]) -> list[tuple[int, int, int]]:
    """``(point, hour, values)`` rows of ``point_hours`` for every run, counted at once."""

    if not runs:
        return []
    points = np.concatenate(
        [np.full(len(times), point, dtype=np.int64) for point, (_, times, _) in runs.items()]
    )
    hours = np.concatenate([times // HOUR_MS for _, times, _ in runs.values()])
    order = np.lexsort((hours, points))
    points, hours = points[order], hours[order]
    edge = np.ones(len(points), dtype=bool)
    edge[1:] = (points[1:] != points[:-1]) | (hours[1:] != hours[:-1])
    starts = np.flatnonzero(edge)
    sizes = np.diff(np.append(starts, len(points)))
    return list(
        zip(
            points[starts].tolist(),
            (hours[starts] * HOUR_MS).tolist(),
            sizes.tolist(),
            strict=True,
        )
    )


def _ints(values: Iterable[int]) -> str:
    """A PostgreSQL array literal of integers (``?::bigint[]``): tens of thousands of them
    are sent as one text, many times faster than psycopg adapting a list item by item."""

    return "{" + ",".join(map(str, values)) + "}"


def _blobs(values: Iterable[bytes]) -> str:
    """A PostgreSQL array literal of bytes in hex (``?::bytea[]``), as ``_ints``."""

    return "{" + ",".join('"\\\\x' + value.hex() + '"' for value in values) + "}"


def _joined(times_parts: list[np.ndarray], value_parts: list[Any]) -> tuple[np.ndarray, Any]:
    """Parts of one point's values as one run in time order, the later part winning on equal
    times. Number parts are float arrays; once one part is labels, all are."""

    text = any(isinstance(part, list) for part in value_parts)
    times = np.concatenate(times_parts) if times_parts else np.empty(0, dtype=np.int64)
    if text:
        values: Any = [v for part in value_parts for v in _plain(part)]
    else:
        values = (
            np.concatenate([np.asarray(part, dtype=float) for part in value_parts])
            if value_parts
            else np.empty(0)
        )
    if len(times) < 2 or (np.diff(times) > 0).all():
        return times, values
    # Stable sort, then the last of each equal time (the later part's).
    order = np.argsort(times, kind="stable")
    times = times[order]
    last = np.append(times[1:] != times[:-1], True)
    keep = order[last]
    times = times[last]
    values = [values[i] for i in keep] if text else values[keep]
    return times, values


def _plain(values: Any) -> list[Any]:
    """Values as Python objects (floats from an array, labels as they are)."""

    return values.tolist() if isinstance(values, np.ndarray) else list(values)


def _real(value: Any) -> float | None:
    """A finite float, else None (SQLite keeps NaN as NULL; PostgreSQL would keep it)."""

    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None
