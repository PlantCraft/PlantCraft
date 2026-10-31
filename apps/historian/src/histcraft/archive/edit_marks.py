"""The mark a value edited by a person carries in reads (H7, ``api.routers.edits``)."""

from __future__ import annotations

from typing import Any

import numpy as np

from histcraft.archive.query import iso_ms


def edit_marks(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """``[{"t", "action"}]``: each edited time once, with its latest action (``inserted``,
    ``edited`` or ``deleted``), oldest first. ``rows`` come in time and edit order."""

    latest: dict[int, str] = {}
    for row in rows:
        latest[int(row["t"])] = str(row["action"])
    if not latest:
        return []
    times = sorted(latest)
    stamps = iso_ms(np.asarray(times, dtype=np.int64))
    return [{"t": at, "action": latest[ms]} for at, ms in zip(stamps, times, strict=True)]
