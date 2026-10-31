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

from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from histcraft import lab
from histcraft.api.deps import EditorUser, RuntimeDep, Scope, in_scope
from histcraft.archive.query import iso_ms
from histcraft.catalog.models import LAB_SOURCE, CatalogError
from histcraft.clock import now_ms
from histcraft.i18n import t

router = APIRouter(prefix="/api/v1/lab", tags=["lab"])
MAX_RESULTS = 5000


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


def _sample(item: LabResult, now: int) -> lab.Sample:
    """The result as a sample; raises ``ValueError`` with the reason."""

    return lab.checked(
        item.signal,
        lab.stamp_ms(item.sampled_at, "sampled_at") or 0,
        item.value,
        now,
        received=lab.stamp_ms(item.received_at, "received_at"),
        approved=lab.stamp_ms(item.approved_at, "approved_at"),
        status=item.status,
        name=item.name,
        unit=item.unit,
        description=item.description,
    )


@router.post("")
def write_results(body: LabIn, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Store laboratory results at their sampling times, late or not; the samples written."""

    now = now_ms()
    errors: list[dict[str, Any]] = []
    samples = []
    for item in body.results:
        try:
            samples.append(_sample(item, now))
        except ValueError as exc:
            errors.append({"signal": item.signal, "status": 422, "detail": str(exc)})
    if not samples:
        return {"written": 0, "errors": errors}
    try:
        written, failed = lab.write(runtime.catalog, runtime.archive, samples, user.username, now)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    errors += failed
    signals = sorted({sample.signal for sample in samples})
    runtime.audit(user, "lab.write", LAB_SOURCE, {"signals": signals, "values": written})
    return {"written": written, "errors": errors}


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
        end_ms = lab.stamp_ms(end, "end") or now_ms()
        start_ms = lab.stamp_ms(start, "start") or end_ms - 30 * lab.DAY_MS
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
