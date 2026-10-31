"""Loops: the portfolio list, one loop's page, its PDF, loop settings and the weekly report."""

from __future__ import annotations

from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from plantcraft_sdk.client import NotFound, PlantCraftError
from plantcraft_sdk.contributes import StartIn, StartOut
from pydantic import ValidationError

from linkcraft.api.deps import CurrentUser, EditorUser, RuntimeDep, frame_rows
from linkcraft.api.runtime import ROUND_ID
from linkcraft.api.schemas import LoopPatchPayload, LoopPayload
from linkcraft.api.scope import Scope, sees_job, sees_loop
from linkcraft.catalog.loop_types import known_loop_type
from linkcraft.catalog.registry import METHOD_SPECS
from linkcraft.config import LoopConfig, LoopSignals
from linkcraft.engine.references import compare
from linkcraft.i18n import t
from linkcraft.loops.defaults import record_defaults, setting_sources
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND, incomplete_reason, missing_roles
from linkcraft.loops.suite import suite_status
from linkcraft.report.causes import likely_causes
from linkcraft.report.loop import loop_report_pdf
from linkcraft.report.weekly import weekly_report_pdf

router = APIRouter()
SERIES_POINTS = 420


def _loop_or_404(rt: Any, loop_id: str, scope: Any = None) -> LoopConfig:
    loop = rt.loops.get_loop(loop_id)
    if loop is not None and scope is not None and not sees_loop(scope, rt, loop_id, loop):
        loop = None
    if loop is None:
        raise HTTPException(status_code=404, detail=t("Loop not found."))
    return loop


@router.get("/api/loops")
def loops(scope: Scope, rt: RuntimeDep) -> list[dict[str, Any]]:
    return [row for row in rt.monitor.overview_rows() if sees_loop(scope, rt, row["loop_id"])]


@router.post("/api/loops", status_code=201)
def create_loop(payload: LoopPayload, user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """A loop defined here, by PlantCraft signal ids (each must exist there)."""

    if rt.loops.get_loop(payload.loop_id) is not None:
        raise HTTPException(status_code=409, detail=t("A loop with this id already exists."))
    signals = _check_signals(rt, user, payload.signals.model_dump())
    _check_profile(rt, payload.profile_id)
    loop = LoopConfig(
        loop_id=payload.loop_id,
        name=payload.name,
        area=payload.area or "No area",
        service=payload.service,
        unit=payload.unit,
        signals=LoopSignals(**signals),
        profile_id=payload.profile_id,
        metadata={"criticality": payload.criticality},
    )
    rt.loops.save_loop(loop, actor=user.username, origin="user")
    rt.audit(user, "loop.created", f"loop:{loop.loop_id}", loop.model_dump(mode="json"))
    return {"loop": loop.model_dump(mode="json"), "origin": "user"}


@router.post("/api/loops/sync")
def sync_loops(user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """Read the loop assets from PlantCraft now (as this person)."""

    result = rt.sync_loops(rt.user_client(user))
    if result.get("status") != "ok":
        raise HTTPException(status_code=502, detail=result.get("error") or t("Sync failed."))
    return result


@router.post("/api/start/analyze-loops")
def start_analyze_loops(body: StartIn, user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """A new plant's first step here (``[[contributes.start]]``, sent by PlantCraft once an
    import is applied): read its loop assets now, as this person, and queue the first monitoring
    round, whose results start each loop's baseline. Taken twice, it reads them again."""

    result = rt.sync_loops(rt.user_client(user))
    if result.get("status") != "ok":
        raise HTTPException(status_code=502, detail=result.get("error") or t("Sync failed."))
    imported = {asset.id for asset in body.assets}
    loops = [loop for loop in rt.loops.list_loops() if loop.loop_id in imported]
    job_id = rt.queue_round(ROUND_ID, user=user.username) if loops else None
    if job_id:
        rt.audit(user, "round.started", ROUND_ID)
    if not loops:
        summary = t("The import has no loops to monitor.")
    elif job_id:
        summary = t(
            "{count} loops of the import are monitored; their first round is queued.",
            count=len(loops),
        )
    else:
        summary = t(
            "{count} loops of the import are monitored in the round already queued.",
            count=len(loops),
        )
    counts = {"loops": len(loops), "rounds": 1 if job_id else 0}
    return StartOut(summary=summary, counts=counts, open="/link/results").model_dump()


@router.get("/api/loops/{loop_id}")
def loop_detail(loop_id: str, user: CurrentUser, rt: RuntimeDep, scope: Scope) -> dict[str, Any]:
    loop = _loop_or_404(rt, loop_id, scope)
    origin = rt.loops.origins().get(loop_id, "user")
    if loop.incomplete:
        payload: dict[str, Any] = {
            "summary": {
                "status": "incomplete",
                "operating_state": "incomplete_record",
                "operating_state_reason": incomplete_reason(loop),
            }
        }
    else:
        payload = rt.monitor.loop_payload(loop_id, plant=rt.user_plant(user)) or {}
    record = loop.asset_record
    summary = payload.get("summary") or {}
    return {
        "loop": loop.model_dump(mode="json"),
        "origin": origin,
        "incomplete": loop.incomplete,
        "missing_roles": missing_roles(loop) if loop.incomplete else [],
        "settings_source": setting_sources(loop, origin),
        "record_defaults": record_defaults(loop) if origin == "processcraft" else None,
        "loop_type_known": bool(record and known_loop_type(record.loop_type)),
        "summary": payload.get("summary"),
        "suite_status": suite_status(payload.get("summary")),
        "results": payload.get("results") or [],
        "likely_causes": likely_causes(payload.get("results") or []),
        "source_start": payload.get("source_start"),
        "source_end": payload.get("source_end"),
        "analyzed_at": payload.get("analyzed_at"),
        "series": frame_rows(payload.get("frame"), SERIES_POINTS),
        "history": rt.latest.history(APPLICATION_ID, SUBJECT_KIND, loop_id, days=30),
        "jobs": rt.jobs.list_jobs(loop_id=loop_id, limit=20),
        "reference": compare(
            rt.monitor.references.get(loop_id),
            payload.get("results") or [],
            summary.get("health"),
            summary.get("algorithm_version"),
        ),
    }


@router.post("/api/loops/{loop_id}/reference")
def record_reference(
    loop_id: str, user: EditorUser, rt: RuntimeDep, scope: Scope
) -> dict[str, Any]:
    """Keep the loop's last run as its reference: later runs are shown against it (A8)."""

    loop = _loop_or_404(rt, loop_id, scope)
    latest = rt.latest.get(APPLICATION_ID, SUBJECT_KIND, loop_id)
    if loop.incomplete or latest is None or not latest.get("results"):
        raise HTTPException(
            status_code=409,
            detail=t("Run the loop first: there is no result to keep as its reference."),
        )
    reference = rt.monitor.references.record(loop_id, latest, user.username)
    rt.audit(
        user,
        "loop.reference_recorded",
        f"loop:{loop_id}",
        {"source_start": reference["source_start"], "source_end": reference["source_end"]},
    )
    summary = latest.get("summary") or {}
    return (
        compare(
            reference, latest["results"], summary.get("health"), summary.get("algorithm_version")
        )
        or {}
    )


@router.delete("/api/loops/{loop_id}/reference", status_code=204)
def delete_reference(loop_id: str, user: EditorUser, rt: RuntimeDep, scope: Scope) -> Response:
    _loop_or_404(rt, loop_id, scope)
    if not rt.monitor.references.delete(loop_id):
        raise HTTPException(status_code=404, detail=t("This loop has no reference."))
    rt.audit(user, "loop.reference_deleted", f"loop:{loop_id}")
    return Response(status_code=204)


@router.patch("/api/loops/{loop_id}")
def update_loop(
    loop_id: str, payload: LoopPatchPayload, user: EditorUser, rt: RuntimeDep, scope: Scope
) -> dict[str, Any]:
    loop = _loop_or_404(rt, loop_id, scope)
    origin = rt.loops.origins().get(loop_id, "user")
    owned = {"name": payload.name, "area": payload.area, "service": payload.service}
    if origin == "processcraft" and (payload.signals or any(v is not None for v in owned.values())):
        raise HTTPException(
            status_code=409,
            detail=t("This loop comes from PlantCraft: change its name and signals there."),
        )
    update: dict[str, Any] = {key: value for key, value in owned.items() if value is not None}
    if payload.signals is not None:
        update["signals"] = LoopSignals(**_check_signals(rt, user, payload.signals.model_dump()))
    if payload.enabled is not None:
        update["enabled"] = payload.enabled
    if payload.profile_id is not None:
        _check_profile(rt, payload.profile_id)
        update["profile_id"] = payload.profile_id
    if payload.criticality is not None:
        update["metadata"] = {**loop.metadata, "criticality": payload.criticality}
    if payload.method_parameters is not None:
        _check_parameters(payload.method_parameters)
        update["method_parameters"] = payload.method_parameters
    changed = loop.model_copy(update=update)
    rt.loops.save_loop(changed, actor=user.username)
    if payload.reset:
        if origin != "processcraft":
            raise HTTPException(
                status_code=409,
                detail=t("This loop was defined in Analytics: it has no asset record to reset to."),
            )
        changed = rt.loops.reset_settings(loop_id, payload.reset, actor=user.username) or changed
    rt.audit(user, "loop.updated", f"loop:{loop_id}", payload.model_dump(exclude_none=True))
    return {"loop": changed.model_dump(mode="json"), "origin": origin}


@router.delete("/api/loops/{loop_id}", status_code=204)
def delete_loop(loop_id: str, user: EditorUser, rt: RuntimeDep, scope: Scope) -> Response:
    _loop_or_404(rt, loop_id, scope)
    if rt.loops.origins().get(loop_id) == "processcraft":
        raise HTTPException(
            status_code=409,
            detail=t("This loop comes from PlantCraft: disable it here or remove it there."),
        )
    rt.loops.delete_loop(loop_id, actor=user.username)
    rt.audit(user, "loop.deleted", f"loop:{loop_id}")
    return Response(status_code=204)


@router.get("/api/loops/{loop_id}/report.pdf")
def loop_report(loop_id: str, user: CurrentUser, rt: RuntimeDep, scope: Scope) -> Response:
    """The loop's diagnosis as a PDF: score, limiting criterion, trends and every finding."""

    loop = _loop_or_404(rt, loop_id, scope)
    payload = rt.monitor.loop_payload(loop_id, plant=rt.user_plant(user)) or {}
    content = loop_report_pdf(
        loop=loop.model_dump(mode="json"),
        summary=payload.get("summary"),
        results=payload.get("results") or [],
        frame=payload.get("frame") if payload.get("frame") is not None else pd.DataFrame(),
        source_start=payload.get("source_start"),
        source_end=payload.get("source_end"),
    )
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in loop_id)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="loop-{safe}.pdf"'},
    )


@router.get("/api/reports/weekly.pdf")
def weekly_report(scope: Scope, rt: RuntimeDep) -> Response:
    """The weekly portfolio PDF: priority loops, score trend and diagnoses to confirm."""

    snapshot = rt.round_header()
    end = pd.to_datetime(snapshot.get("source_end"), errors="coerce")
    now = None if pd.isna(end) else end.to_pydatetime()
    content = weekly_report_pdf(
        scenario_name="PlantCraft Analytics",
        loops=[row for row in rt.monitor.overview_rows() if sees_loop(scope, rt, row["loop_id"])],
        jobs=[
            job
            for job in rt.jobs.list_jobs(statuses={"completed"}, limit=5000)
            if sees_job(scope, rt, job)
        ],
        actions=[],
        now=now,
    )
    stamp = (now or pd.Timestamp.now().to_pydatetime()).strftime("%Y-%m-%d")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="weekly-report-{stamp}.pdf"'},
    )


@router.get("/api/signal-search")
def signal_search(
    user: CurrentUser,
    rt: RuntimeDep,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[dict[str, Any]]:
    """PlantCraft's signals (for the loop editor), read as this person."""

    try:
        return rt.user_client(user).signals(q or None)[:limit]
    except PlantCraftError as exc:
        raise HTTPException(status_code=502, detail=str(exc.detail)) from exc


def _check_signals(rt: Any, user: Any, signals: dict[str, Any]) -> dict[str, Any]:
    """The signals as PlantCraft names them: each id typed is looked up and its ``id`` kept.

    Ids are opaque (``<source id>:<tag>`` in API v1); a bare tag one source has still reads until
    API v1 is frozen, and is stored by the id PlantCraft answers for it.
    """

    client = rt.user_client(user)
    named = dict(signals)
    for role, signal_id in signals.items():
        if not signal_id:
            continue
        try:
            answered = client.signal(signal_id)
        except NotFound as exc:
            raise HTTPException(
                status_code=422,
                detail=t(
                    "PlantCraft has no signal {signal} ({role}): {reason}",
                    signal=signal_id,
                    role=role.upper(),
                    reason=str(exc.detail),
                ),
            ) from exc
        except PlantCraftError as exc:
            raise HTTPException(status_code=502, detail=str(exc.detail)) from exc
        if isinstance(answered, dict) and isinstance(answered.get("id"), str) and answered["id"]:
            named[role] = answered["id"]
    return named


def _check_profile(rt: Any, profile_id: str) -> None:
    if rt.presets.get_profile(profile_id) is None:
        raise HTTPException(status_code=422, detail=t("Algorithm not found: {id}.", id=profile_id))


def _check_parameters(parameters: dict[str, dict[str, Any]]) -> None:
    for method_id, values in parameters.items():
        if method_id not in METHOD_SPECS:
            raise HTTPException(
                status_code=422, detail=t("Parameters of an unknown method: {m}", m=method_id)
            )
        try:
            METHOD_SPECS[method_id].parameter_schema.model_validate(values)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=t(
                    "Invalid parameters in {method}: {error}",
                    method=method_id,
                    error=exc.errors()[0]["msg"],
                ),
            ) from exc
