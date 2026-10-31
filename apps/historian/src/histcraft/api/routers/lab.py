"""Laboratory results as signals (``laboratory:<analysis>``, 2026-10-31).

A laboratory result describes the process when the sample was taken, not when it arrived. The
value is stored at the sampling time, however late it is written (hours, or days for a retest),
and the times it reached the laboratory and was approved are kept beside it (``lab_samples``).
A result not yet approved reads as ``uncertain``, a rejected one as ``bad`` (the quality holds
from that sample to the next, as for any signal); writing the same sample again replaces its
value and counts the write. Trends, Analytics and the estimators then read the analysis like
any signal, at the right time.

Editors write by hand or a bridge from the LIMS writes with a person's key:
``POST /api/v1/lab``. ``GET /api/v1/lab/{signal}`` gives the samples of a window with their
times.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from histcraft.api.deps import EditorUser, RuntimeDep, Scope, in_scope
from histcraft.archive.query import iso_ms
from histcraft.catalog.models import LAB_SOURCE, CatalogError, split_signal
from histcraft.clock import now_ms
from histcraft.i18n import t

router = APIRouter(prefix="/api/v1/lab", tags=["lab"])
MAX_RESULTS = 5000
# The quality a sample reads with, by its status.
QUALITY = {"entered": "uncertain", "approved": "good", "rejected": "bad"}
DAY_MS = 86_400_000


class LabResult(BaseModel):
    signal: str = Field(min_length=5, max_length=340)
    sampled_at: str
    value: float
    received_at: str | None = None
    approved_at: str | None = None
    # entered: the laboratory gave it, not yet approved; approved; rejected (kept, read as bad).
    status: Literal["entered", "approved", "rejected"] | None = None
    name: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=500)


class LabIn(BaseModel):
    results: list[LabResult] = Field(min_length=1, max_length=MAX_RESULTS)


def _ms(stamp: str | None, field: str) -> int | None:
    if stamp is None:
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            t("{field}: {value} is not an ISO 8601 time.", field=field, value=stamp[:40])
        ) from exc
    if moment.tzinfo is None:
        raise ValueError(t("{field}: times need an offset (Z or +hh:mm).", field=field))
    return int(moment.astimezone(timezone.utc).timestamp() * 1000)


def _checked(item: LabResult, now: int) -> tuple[int, int | None, int | None, str]:
    """The sample's times and status; raises ``ValueError`` with the reason."""

    source, tag = split_signal(item.signal)
    if source != LAB_SOURCE or not tag:
        raise ValueError(t("Laboratory signals are laboratory:<analysis>."))
    if not math.isfinite(item.value):
        raise ValueError(t("The value must be a number."))
    sampled = _ms(item.sampled_at, "sampled_at") or 0
    received = _ms(item.received_at, "received_at")
    approved = _ms(item.approved_at, "approved_at")
    if sampled > now + DAY_MS:
        raise ValueError(t("Values more than a day in the future are refused."))
    for later, field in ((received, "received_at"), (approved, "approved_at")):
        if later is not None and later < sampled:
            raise ValueError(t("{field} comes before sampled_at.", field=field))
    status = item.status or ("approved" if approved is not None else "entered")
    return sampled, received, approved, status


@router.post("")
def write_results(body: LabIn, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Store laboratory results at their sampling times, late or not; the samples written."""

    now = now_ms()
    errors: list[dict[str, Any]] = []
    ready: dict[str, list[tuple[LabResult, int, int | None, int | None, str]]] = {}
    for item in body.results:
        try:
            checked = _checked(item, now)
        except ValueError as exc:
            errors.append({"signal": item.signal, "status": 422, "detail": str(exc)})
            continue
        ready.setdefault(item.signal, []).append((item, *checked))
    if not ready:
        return {"written": 0, "errors": errors}
    described = []
    for signal, items in ready.items():
        last = items[-1][0]
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
    try:
        points = runtime.catalog.lab(described)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    written = 0
    snapshots, qualities, samples = [], [], []
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
        by_time = {
            sampled: (item, received, approved, status)
            for item, sampled, received, approved, status in items
        }
        order = sorted(by_time)
        written += runtime.archive.replace(
            point_id, "number", [(at, float(by_time[at][0].value)) for at in order]
        )
        for at in order:
            item, received, approved, status = by_time[at]
            qualities.append((point_id, at, QUALITY[status]))
            samples.append((point_id, at, received, approved, status, now, user.username))
        newest = order[-1]
        snapshots.append(
            {
                "point": point_id,
                "ts": newest,
                "value": float(by_time[newest][0].value),
                "status": "ok",
            }
        )
    if samples:
        runtime.archive.put_qualities(qualities)
        runtime.archive.put_lab_samples(samples)
        runtime.archive.put_snapshots(_newer(runtime, snapshots))
        runtime.audit(user, "lab.write", LAB_SOURCE, {"signals": sorted(ready), "values": written})
    return {"written": written, "errors": errors}


def _newer(runtime: Any, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The snapshots newer than the stored ones (a late result does not hide a newer one)."""

    stored = runtime.archive.snapshots([item["point"] for item in snapshots])
    return [
        item
        for item in snapshots
        if (stored.get(item["point"]) or {}).get("ts") is None
        or int(stored[item["point"]]["ts"]) <= item["ts"]
    ]


@router.get("/{signal_id:path}")
def samples(
    signal_id: str,
    runtime: RuntimeDep,
    scope: Scope,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """A laboratory signal's samples between ``start`` and ``end`` (default: the last 30 days),
    each with its value, status and times (sampled, received, approved, written)."""

    in_scope(scope, signal_id)
    try:
        point = runtime.catalog.point(signal_id)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    if point.get("source_kind") != "lab":
        raise HTTPException(404, t("{id} is not a laboratory signal.", id=signal_id))
    try:
        end_ms = _ms(end, "end") or now_ms()
        start_ms = _ms(start, "start") or end_ms - 30 * DAY_MS
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    found = runtime.archive.lab_samples(int(point["id"]), start_ms, end_ms)
    values = {}
    if found:
        times, stored = runtime.archive.read(
            int(point["id"]), int(found[0]["t"]), int(found[-1]["t"])
        )
        values = {int(at): value for at, value in zip(times, stored, strict=False)}

    def iso(at: Any) -> str | None:
        return None if at is None else iso_ms(np.asarray([int(at)]))[0]

    return {
        "signal": signal_id,
        "unit": point.get("unit") or "",
        "samples": [
            {
                "sampled_at": iso(row["t"]),
                "value": values.get(int(row["t"])),
                "status": row["status"],
                "received_at": iso(row["received"]),
                "approved_at": iso(row["approved"]),
                "written_at": iso(row["written"]),
                "written_by": row["author"],
                "writes": int(row["writes"]),
                "delay_hours": round((int(row["written"]) - int(row["t"])) / 3_600_000, 2),
            }
            for row in found
        ],
    }
