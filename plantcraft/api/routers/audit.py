"""HTTP routes: the audit log, read by administrators (Settings › Audit log).

Who changed what in PlantCraft and in every app (``POST /api/v1/audit``), and every sign-in,
failed sign-in and sign-out (``session.*``). Read only: no route edits or removes a row.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from plantcraft.api.deps import AdminUser, Runtime
from plantcraft.audit import KINDS, MAX_ROWS
from plantcraft.db import utc_text
from plantcraft.i18n import t

router = APIRouter()
COLUMNS = ("at", "username", "app_id", "action", "subject", "detail")


class Filters:
    """What the page asks for: a period (``days`` back from now, or ``start`` to ``end``), a
    person, an app, an action family and one of the quick filters (``KINDS``)."""

    def __init__(
        self,
        days: int = Query(default=7, ge=1, le=3650),
        start: str = Query(default="", max_length=40),
        end: str = Query(default="", max_length=40),
        username: str = Query(default="", max_length=200),
        app_id: str = Query(default="", max_length=80),
        action: str = Query(default="", max_length=120),
        kind: str = Query(default="", max_length=20),
    ) -> None:
        if kind and kind not in KINDS:
            raise HTTPException(status_code=422, detail=t("Unknown filter: {kind}.", kind=kind))
        try:
            self.since = utc_text(start) if start else None
            self.until = utc_text(end) if end else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=t("Times are ISO 8601.")) from exc
        if not self.since:
            self.since = utc_text(datetime.now(timezone.utc) - timedelta(days=days))
        self.seconds = (
            datetime.fromisoformat((self.until or utc_text()).replace("Z", "+00:00"))
            - datetime.fromisoformat(self.since.replace("Z", "+00:00"))
        ).total_seconds()
        self.query = {
            "username": username.strip().lower() or None,
            "app_id": app_id.strip() or None,
            "action": action.strip() or None,
            "since": self.since,
            "until": self.until,
            "kind": kind or None,
        }


AuditFilters = Annotated[Filters, Depends()]


def _rows(rt: Any, filters: Filters, limit: int, before_id: int | None = None) -> list:
    return rt.workspace.audit.list(limit=limit, before_id=before_id, **filters.query)


@router.get("/api/audit")
def audit_log(
    _admin: AdminUser,
    rt: Runtime,
    filters: AuditFilters,
    limit: int = Query(default=500, ge=1, le=MAX_ROWS),
    before_id: int | None = Query(default=None, ge=1),
) -> dict[str, Any]:
    """The rows of the period, newest first, at most ``limit``; ``before_id`` reads on."""

    rows = _rows(rt, filters, limit, before_id)
    return {"rows": rows, "limit": limit, "truncated": len(rows) >= limit}


@router.get("/api/audit/volume")
def audit_volume(_admin: AdminUser, rt: Runtime, filters: AuditFilters) -> dict[str, Any]:
    """Rows per hour (periods up to three days) or per day, and who and which apps wrote them."""

    bucket = "hour" if filters.seconds <= 3 * 86_400 else "day"
    return rt.workspace.audit.volume(bucket=bucket, **filters.query)


@router.get("/api/audit.csv")
def audit_csv(_admin: AdminUser, rt: Runtime, filters: AuditFilters) -> Response:
    """The same rows as a CSV file (at most ``MAX_ROWS``), for a review or an auditor."""

    rows = _rows(rt, filters, MAX_ROWS)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for row in rows:
        detail = row.get("detail")
        cells = [row.get(key) or "" for key in COLUMNS[:-1]]
        cells.append("" if detail is None else json.dumps(detail, ensure_ascii=False))
        # A cell starting with = + - @ would run as a formula in a spreadsheet.
        writer.writerow([f"'{cell}" if str(cell)[:1] in "=+-@" else cell for cell in cells])
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )
