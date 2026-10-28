"""Backfill: copy a source's own history of its archived signals into the archive.

An archive starts the moment a signal is added. A source that keeps history (an OPC UA server
with Historical Access, such as the Simulator) already holds the days before that: a backfill reads
them once and stores them as they are, up to the first value the archive holds, so every later
read comes from the archive instead of the plant system (docs/data-layer.md).

The source is read in windows of a few hours and groups of signals, so one request never asks a
plant server for more than it answers comfortably.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

from histcraft.archive.query import PointRef, Reader
from histcraft.archive.store import ArchiveStore
from histcraft.i18n import t

LOGGER = logging.getLogger(__name__)
WINDOW_MS = 6 * 3600 * 1000
GROUP = 50
MAX_HOURS = 24 * 366
# Errors listed in the answer, at most.
MAX_ERRORS = 20


def backfill(
    history: Any,
    archive: ArchiveStore,
    points: list[dict[str, Any]],
    start_ms: int,
    until_ms: int,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Store ``history``'s recorded values of ``points`` from ``start_ms`` to each point's
    first archived value (or ``until_ms``, when that comes first). Returns what was written."""

    firsts = archive.point_stats()
    bounds = {
        int(p["id"]): min(until_ms, firsts.get(int(p["id"]), {}).get("first") or until_ms)
        for p in points
    }
    written: dict[int, int] = {}
    errors: dict[str, str] = {}
    groups = [points[offset : offset + GROUP] for offset in range(0, len(points), GROUP)]
    for number, group in enumerate(groups):
        end = max(bounds[int(p["id"])] for p in group)
        for w0 in range(start_ms, end, WINDOW_MS):
            w1 = min(w0 + WINDOW_MS, end)
            wanted = [p for p in group if bounds[int(p["id"])] > w0]
            if not wanted:
                continue
            answers = history.recorded(sorted({p["address"] for p in wanted}), w0, w1)
            for point in wanted:
                answer = answers.get(point["address"])
                if answer is None or isinstance(answer, str):
                    errors.setdefault(point["signal"], answer or t("The source sent no values."))
                    continue
                ref = PointRef(int(point["id"]), point["signal"], kind=point["kind"])
                times, values = Reader.normalize(ref, *answer)
                # Half-open windows: the value read just before a window (its boundary) belongs
                # to the window before.
                keep = (times >= w0) & (times < min(w1, bounds[ref.id]))
                if not keep.any():
                    continue
                samples = list(
                    zip(
                        times[keep].tolist(),
                        [values[i] for i in np.flatnonzero(keep)]
                        if ref.kind == "text"
                        else np.asarray(values)[keep].tolist(),
                        strict=True,
                    )
                )
                written[ref.id] = written.get(ref.id, 0) + archive.replace(
                    ref.id, ref.kind, samples
                )
        if progress is not None:
            progress(number + 1, len(groups))
    LOGGER.info(
        "Backfill: %d values of %d signals (%d failed)",
        sum(written.values()),
        len(written),
        len(errors),
    )
    return {
        "signals": len(written),
        "values": sum(written.values()),
        "failed": len(errors),
        "errors": dict(list(errors.items())[:MAX_ERRORS]),
    }
