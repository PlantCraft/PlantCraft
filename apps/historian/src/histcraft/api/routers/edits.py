"""People's edits of archived values, audited (2026-10-31, gap H7).

An editor inserts a value where there was none, changes one, or deletes one: a wrong reading
from a sensor being calibrated, a value typed in by hand. Every value changed keeps its mark
(``inserted``, ``edited`` or ``deleted``), read beside the values as ``edits`` (``POST
/api/v1/series`` with ``quality``, and here); the value it replaced is kept with who changed
it, when and why (the ``edits`` table), and each request is one entry of PlantCraft's audit
log (``histcraft.values.edit``). Nothing is lost: the original stays in the edit history.

Signals an app writes (derived, system, laboratory) are their app's to change, and a signal
read from its source on request (``mode`` source) has no archive to edit.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from histcraft.api.deps import EditorUser, RuntimeDep, Scope, in_scope
from histcraft.archive.query import iso_ms
from histcraft.catalog.models import WRITTEN_KINDS, CatalogError
from histcraft.clock import now_ms
from histcraft.i18n import t
from histcraft.lab import DAY_MS
from histcraft.lab import stamp_ms as _ms

router = APIRouter(prefix="/api/v1/edits", tags=["edits"])
MAX_CHANGES = 1000
ACTIONS = ("inserted", "edited", "deleted")


class ValueChange(BaseModel):
    t: str
    # The new value; null deletes the value stored at ``t``.
    value: float | str | None = None
    delete: bool = False


class EditIn(BaseModel):
    signal: str = Field(min_length=3, max_length=340)
    changes: list[ValueChange] = Field(min_length=1, max_length=MAX_CHANGES)
    reason: str = Field(min_length=1, max_length=500)


def _iso(at: int) -> str:
    return iso_ms(np.asarray([int(at)]))[0]


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


def _plain(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


def _point(runtime: Any, scope: Any, signal: str) -> dict[str, Any]:
    in_scope(scope, signal)
    try:
        point = runtime.catalog.point(signal)
    except CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return point


@router.post("")
def edit(body: EditIn, user: EditorUser, runtime: RuntimeDep, scope: Scope) -> dict[str, Any]:
    """Insert, change or delete values of an archived signal, all or nothing; answers each
    change with its action and the value it replaced."""

    point = _point(runtime, scope, body.signal)
    if point.get("source_kind") in WRITTEN_KINDS or point.get("managed_by"):
        raise HTTPException(409, t("{id} is written by its app: change it there.", id=body.signal))
    if point.get("mode") == "source" or point["kind"] == "runs":
        raise HTTPException(422, t("{id} has no archived values to edit.", id=body.signal))
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(422, t("Say why the values change."))
    wanted: dict[int, ValueChange] = {}
    for index, change in enumerate(body.changes):
        try:
            at = _ms(change.t, f"changes[{index}].t")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        assert at is not None
        if at > now_ms():
            raise HTTPException(422, t("changes[{i}]: a value cannot be in the future.", i=index))
        if not change.delete and change.value is None:
            raise HTTPException(422, t("changes[{i}]: give a value, or delete.", i=index))
        if not change.delete and point["kind"] == "number":
            try:
                number = float(change.value)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    422, t("changes[{i}]: {id} holds numbers.", i=index, id=body.signal)
                ) from exc
            if not math.isfinite(number):
                raise HTTPException(422, t("changes[{i}]: not a number.", i=index))
            change.value = number
        elif not change.delete:
            change.value = str(change.value)
        wanted[at] = change  # a time given twice: the last change wins
    point_id = int(point["id"])
    times = sorted(wanted)
    stored_times, stored_values = runtime.archive.read(point_id, times[0], times[-1])
    stored = {
        int(at): _plain(value)
        for at, value in zip(np.asarray(stored_times).tolist(), stored_values, strict=False)
    }
    written: list[tuple[int, Any]] = []
    dropped: list[int] = []
    rows: list[tuple[Any, ...]] = []
    answer: list[dict[str, Any]] = []
    stamp = now_ms()
    for at in times:
        change = wanted[at]
        old = stored.get(at)
        had = at in stored
        if change.delete:
            if not had:
                raise HTTPException(422, t("No value at {t} to delete.", t=_iso(at)))
            action, new = "deleted", None
            dropped.append(at)
        else:
            action, new = ("edited" if had else "inserted"), change.value
            written.append((at, new))
        rows.append(
            (
                point_id,
                at,
                action,
                _json(old if had else None),
                _json(new),
                user.username,
                stamp,
                reason,
            )
        )
        answer.append({"t": _iso(at), "action": action, "old": old if had else None, "new": new})
    runtime.archive.edit(point_id, point["kind"], written, dropped)
    runtime.archive.put_edits(rows)
    counts = {action: sum(1 for item in answer if item["action"] == action) for action in ACTIONS}
    runtime.audit(
        user,
        "values.edit",
        body.signal,
        {"reason": reason, **counts, "from": answer[0]["t"], "to": answer[-1]["t"]},
    )
    return {"signal": body.signal, "changes": answer, **counts}


@router.get("/{signal_id:path}")
def history(
    signal_id: str,
    runtime: RuntimeDep,
    scope: Scope,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """The edits of a signal's values in ``[start, end]`` (default: the last 30 days): each with
    the value it replaced, the new one, who, when and why."""

    point = _point(runtime, scope, signal_id)
    try:
        end_ms = _ms(end, "end") or now_ms()
        start_ms = _ms(start, "start") or end_ms - 30 * DAY_MS
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rows = runtime.archive.edits([int(point["id"])], start_ms, end_ms)[int(point["id"])]
    return {
        "signal": signal_id,
        "edits": [
            {
                "t": _iso(row["t"]),
                "action": row["action"],
                "old": None if row["old_value"] is None else json.loads(row["old_value"]),
                "new": None if row["new_value"] is None else json.loads(row["new_value"]),
                "by": row["author"],
                "at": _iso(row["at"]),
                "reason": row["reason"],
            }
            for row in rows
        ],
    }
