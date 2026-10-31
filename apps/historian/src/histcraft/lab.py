"""Laboratory results written at their sampling times (``laboratory:<analysis>``, 2026-10-31).

One path for every writer: a person or a LIMS bridge through ``POST /api/v1/lab``
(``api.routers.lab``) and a SQL source read as a LIMS (``laboratory`` option of a SQL source,
written by the collector). Each result's value goes to the archive at its sampling time, its
quality from its status (``uncertain`` until approved, ``bad`` when rejected), its times to
``lab_samples``, and the snapshot only when it is the newest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from histcraft.catalog.models import LAB_SOURCE, CatalogError, split_signal
from histcraft.i18n import t

# The quality a sample reads with, by its status.
QUALITY = {"entered": "uncertain", "approved": "good", "rejected": "bad"}
STATUSES = tuple(QUALITY)
DAY_MS = 86_400_000


@dataclass(frozen=True)
class Sample:
    signal: str
    sampled: int
    value: float
    received: int | None = None
    approved: int | None = None
    status: str = "entered"
    name: str | None = None
    unit: str | None = None
    description: str | None = None


def stamp_ms(stamp: Any, field: str) -> int | None:
    """A time given as ISO 8601 text with an offset, or as epoch milliseconds; None for none."""

    if stamp is None or stamp == "":
        return None
    if isinstance(stamp, int | float) and not isinstance(stamp, bool):
        return int(stamp)
    text = str(stamp)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            t("{field}: {value} is not an ISO 8601 time.", field=field, value=text[:40])
        ) from exc
    if moment.tzinfo is None:
        raise ValueError(t("{field}: times need an offset (Z or +hh:mm).", field=field))
    return int(moment.astimezone(timezone.utc).timestamp() * 1000)


def checked(
    signal: str,
    sampled: int,
    value: Any,
    now: int,
    *,
    received: int | None = None,
    approved: int | None = None,
    status: str | None = None,
    **described: Any,
) -> Sample:
    """A sample once its signal, value, times and status hold; ``ValueError`` with the reason."""

    source, tag = split_signal(signal)
    if source != LAB_SOURCE or not tag:
        raise ValueError(t("Laboratory signals are laboratory:<analysis>."))
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(t("The value must be a number."))
    if sampled > now + DAY_MS:
        raise ValueError(t("Values more than a day in the future are refused."))
    for later, field in ((received, "received_at"), (approved, "approved_at")):
        if later is not None and later < sampled:
            raise ValueError(t("{field} comes before sampled_at.", field=field))
    status = status or ("approved" if approved is not None else "entered")
    if status not in QUALITY:
        raise ValueError(t("The status is one of {names}.", names=", ".join(STATUSES)))
    return Sample(signal, sampled, float(value), received, approved, status, **described)


def write(
    catalog: Any,
    archive: Any,
    samples: list[Sample],
    author: str,
    now: int,
    *,
    only_changed: bool = False,
) -> tuple[int, list[dict[str, Any]]]:
    """Store ``samples``; the values written and the errors by signal.

    ``only_changed``: a sample already stored with the same value, status and times is left as
    it is, so a LIMS read again every few minutes does not count each read as a new write.
    """

    errors: list[dict[str, Any]] = []
    ready: dict[str, list[Sample]] = {}
    for sample in samples:
        ready.setdefault(sample.signal, []).append(sample)
    if not ready:
        return 0, errors
    described = []
    for signal, items in ready.items():
        last = items[-1]
        described.append(
            {
                "signal": signal,
                "kind": "number",
                **{
                    key: getattr(last, key)
                    for key in ("name", "unit", "description")
                    if getattr(last, key) is not None
                },
            }
        )
    points = catalog.lab(described)
    written = 0
    snapshots, qualities, rows = [], [], []
    for signal, items in ready.items():
        point = points[signal]
        if point["kind"] != "number":
            errors.append(
                {
                    "signal": signal,
                    "status": 409,
                    "detail": t("{id} is not a number signal.", id=signal),
                }
            )
            continue
        point_id = int(point["id"])
        # One value per sampling time: the last given wins.
        by_time = {sample.sampled: sample for sample in items}
        if only_changed:
            by_time = _changed(archive, point_id, by_time)
            if not by_time:
                continue
        order = sorted(by_time)
        written += archive.replace(point_id, "number", [(at, by_time[at].value) for at in order])
        for at in order:
            sample = by_time[at]
            qualities.append((point_id, at, QUALITY[sample.status]))
            rows.append(
                (point_id, at, sample.received, sample.approved, sample.status, now, author)
            )
        newest = order[-1]
        snapshots.append(
            {"point": point_id, "ts": newest, "value": by_time[newest].value, "status": "ok"}
        )
    if rows:
        archive.put_qualities(qualities)
        archive.put_lab_samples(rows)
        archive.put_snapshots(_newer(archive, snapshots))
    return written, errors


def _changed(archive: Any, point_id: int, by_time: dict[int, Sample]) -> dict[int, Sample]:
    """The samples whose value, status or times differ from the stored ones."""

    first, last = min(by_time), max(by_time)
    stored = {int(row["t"]): row for row in archive.lab_samples(point_id, first, last)}
    if not stored:
        return by_time
    times, values = archive.read(point_id, first, last)
    value_at = {int(at): value for at, value in zip(times, values, strict=False)}
    out = {}
    for at, sample in by_time.items():
        row = stored.get(at)
        if (
            row is None
            or value_at.get(at) != sample.value
            or row["status"] != sample.status
            or row["received"] != sample.received
            or row["approved"] != sample.approved
        ):
            out[at] = sample
    return out


def _newer(archive: Any, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The snapshots newer than the stored ones (a late result does not hide a newer one)."""

    stored = archive.snapshots([item["point"] for item in snapshots])
    return [
        item
        for item in snapshots
        if (stored.get(item["point"]) or {}).get("ts") is None
        or int(stored[item["point"]]["ts"]) <= item["ts"]
    ]


__all__ = ["CatalogError", "QUALITY", "Sample", "checked", "stamp_ms", "write"]
