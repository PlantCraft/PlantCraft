"""Runs (jobs), schedules and the monitoring round."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response
from plantcraft_sdk.server.queue import queue_answer
from plantcraft_sdk.utc import utc_iso
from pydantic import BaseModel, Field

from linkcraft.api.deps import AdminUser, CurrentUser, EditorUser, RuntimeDep, frame_rows
from linkcraft.api.routers.executions import queue_items
from linkcraft.api.runtime import ROUND_ID, SIGNAL_ROUND_ID
from linkcraft.api.schemas import BatchPayload, JobPayload, SchedulePatchPayload, SchedulePayload
from linkcraft.api.scope import Scope, paged, sees_job
from linkcraft.assets.outputs import checked_choices, runs_per_day, schedule_outputs
from linkcraft.blocks.algorithms import SIGNAL_QUALITY
from linkcraft.catalog.loop_types import ALGORITHM_OF_PROTOCOL, algorithm_id
from linkcraft.catalog.registry import list_method_specs
from linkcraft.engine.jobs import JOB_KINDS, JOB_STATUSES, SCHEDULE_CADENCES, schedule_work
from linkcraft.i18n import current_language, t
from linkcraft.loops.monitor import incomplete_reason
from linkcraft.loops.replay import MAX_HOURS
from linkcraft.loops.suite import schedule_when

router = APIRouter()
# Every page of the suite asks every app's queue, and the sidebar asks again every few seconds:
# the same answer for everyone, so it is built once per QUEUE_CACHE_SECONDS. With 100 people at
# once it was most of Analytics' time (p95 18 s, load test 2026-10-27).
QUEUE_CACHE_SECONDS = 5.0
_queue_lock = threading.Lock()

JOB_WAIT_SECONDS = 300


@router.get("/api/status")
def status(_user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    return rt.status()


@router.post("/api/round", status_code=202)
def run_round(user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """Start the monitoring round now (in the background)."""

    job_id = rt.queue_round(ROUND_ID, user=user.username)
    if job_id:
        rt.audit(user, "round.started", ROUND_ID)
    return {"started": job_id is not None, "job_id": job_id}


@router.get("/api/queue")
def queue(
    _user: CurrentUser,
    rt: RuntimeDep,
    window: Annotated[str, Query(pattern="^(1h|24h|7d|30d)$")] = "24h",
) -> dict[str, Any]:
    """The queue now and over ``window`` (``plantcraft_sdk.server.queue``), for its panel,
    with the Executions page it links to and the executions it lists by name."""

    key = (window, current_language())
    with _queue_lock:
        cache = rt.__dict__.setdefault("queue_answers", {})
        kept = cache.get(key)
        if kept is None or time.monotonic() - kept[0] > QUEUE_CACHE_SECONDS:
            answer = {
                **queue_answer(rt.engine.live(), rt.engine.metrics, window),
                "url": "executions",
                "items": queue_items(rt),
            }
            kept = (time.monotonic(), answer)
            cache[key] = kept
    return kept[1]


@router.get("/api/jobs")
def jobs(
    scope: Scope,
    rt: RuntimeDep,
    response: Response,
    loop_id: Annotated[list[str] | None, Query()] = None,
    status: Annotated[list[str] | None, Query()] = None,
    kind: Annotated[list[str] | None, Query()] = None,
    hours: Annotated[float | None, Query(gt=0, le=24 * 400)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    schedule_id: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 300,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    """Run history, newest first; ``X-Total-Count`` carries the match count."""

    filters: dict[str, Any] = {
        "schedule_id": schedule_id,
        "loop_ids": loop_id or None,
        "statuses": set(status) if status else None,
        "kinds": set(kind) if kind else None,
        "since": (utc_iso(datetime.now(UTC) - timedelta(hours=hours)) if hours else None),
        "query": q.strip() if q and q.strip() else None,
    }
    if not scope.everything:
        page, total = paged(scope, rt, rt.jobs.list_jobs(**filters, limit=5000), limit, offset)
        response.headers["X-Total-Count"] = str(total)
        return page
    response.headers["X-Total-Count"] = str(rt.jobs.count_jobs(**filters))
    return rt.jobs.list_jobs(**filters, limit=limit, offset=offset)


@router.get("/api/jobs/{job_id}")
def job_detail(job_id: str, scope: Scope, rt: RuntimeDep) -> dict[str, Any]:
    job = rt.jobs.get_job(job_id)
    if job is None or not sees_job(scope, rt, job):
        raise HTTPException(status_code=404, detail=t("Run not found."))
    job["results"] = rt.jobs.job_results(job_id)
    job["status_label"] = t(JOB_STATUSES.get(job["status"], job["status"]))
    loop = rt.loops.get_loop(job["loop_id"])
    job["loop"] = {"loop_id": loop.loop_id, "name": loop.name, "area": loop.area} if loop else None
    schedule = rt.jobs.get_schedule(job["schedule_id"]) if job.get("schedule_id") else None
    job["schedule"] = (
        {"schedule_id": schedule["schedule_id"], "name": schedule["name"]} if schedule else None
    )
    profile = rt.presets.get_profile(job["profile_id"]) if job.get("profile_id") else None
    job["profile"] = (
        {"profile_id": profile["profile_id"], "name": profile["name"]} if profile else None
    )
    return job


@router.get("/api/jobs/{job_id}/series")
def job_series(job_id: str, user: CurrentUser, rt: RuntimeDep, scope: Scope) -> dict[str, Any]:
    """PV, SP, OP and mode over the exact period one run analysed."""

    job = rt.jobs.get_job(job_id)
    if job is None or not sees_job(scope, rt, job):
        raise HTTPException(status_code=404, detail=t("Run not found."))
    try:
        frame = rt.monitor.job_frame(job, plant=rt.user_plant(user))
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=t("History unavailable: {error}", error=str(exc))
        ) from exc
    return {
        "start": job.get("source_start"),
        "end": job.get("source_end"),
        "series": frame_rows(frame if frame is not None else pd.DataFrame(), 600),
    }


def _method_config(
    rt: Any,
    loop_id: str,
    profile_id: str | None,
    method_ids: Any = None,
    parameters: Any = None,
) -> dict[str, Any]:
    if method_ids:
        known = {spec.method_id for spec in list_method_specs()}
        unknown = [method_id for method_id in method_ids if method_id not in known]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=t("Method not found: {methods}.", methods=", ".join(unknown)),
            )
    if profile_id and rt.presets.get_profile(profile_id) is None:
        raise HTTPException(status_code=422, detail=t("Algorithm not found: {id}.", id=profile_id))
    loop = rt.loops.get_loop(loop_id) if loop_id != "*" else None
    if loop is None:
        preset = rt.presets.get_profile(profile_id) if profile_id else None
        config = dict((preset or {}).get("method_config") or {})
        if method_ids:
            config["method_ids"] = list(method_ids)
        if parameters:
            config["parameters"] = parameters
        return {**config, "profile_id": profile_id}
    return rt.loops.effective_method_config(
        loop, profile_id=profile_id, method_ids=method_ids, parameters=parameters
    )


def _require_loop(rt: Any, loop_id: str) -> None:
    loop = rt.loops.get_loop(loop_id)
    if loop is None:
        raise HTTPException(status_code=404, detail=t("Loop not found: {loop}.", loop=loop_id))
    if loop.incomplete:
        raise HTTPException(status_code=409, detail=incomplete_reason(loop))


@router.post("/api/jobs", status_code=201)
def create_job(
    payload: JobPayload, user: EditorUser, rt: RuntimeDep, response: Response
) -> dict[str, Any]:
    """Run one loop now; answered with the result (202 when the queue is busy)."""

    if payload.kind not in JOB_KINDS:
        raise HTTPException(status_code=422, detail=t("Invalid run type."))
    _require_loop(rt, payload.loop_id)
    config = _method_config(
        rt, payload.loop_id, payload.profile_id, payload.method_ids, payload.parameters
    )
    job_id = rt.jobs.create_job(
        loop_id=payload.loop_id,
        name=payload.name,
        kind=payload.kind,
        lookback_minutes=payload.lookback_minutes,
        profile_id=config.get("profile_id") or payload.profile_id,
        method_config=config,
        created_by=user.username,
    )
    rt.queued()
    if not rt.wait_for([job_id], JOB_WAIT_SECONDS):
        response.status_code = 202
    return job_detail(job_id, rt.asset_scope(user), rt)


@router.post("/api/jobs/batch", status_code=202)
def create_batch(payload: BatchPayload, user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """Queue one run per loop: the named ones, else those the rule selects (all by default)."""

    if payload.kind not in JOB_KINDS:
        raise HTTPException(status_code=422, detail=t("Invalid run type."))
    if payload.loop_ids:
        missing = [item for item in payload.loop_ids if rt.loops.get_loop(item) is None]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=t("Loops not found: {loops}", loops=", ".join(missing[:20])),
            )
        loop_ids = list(dict.fromkeys(payload.loop_ids))
        for loop_id in loop_ids:
            _require_loop(rt, loop_id)
    else:
        loop_ids = rt.resolve_selector(payload.selector or {"mode": "all"})
    if not loop_ids:
        raise HTTPException(status_code=422, detail=t("No loop matches the selection."))
    job_ids = []
    cache: dict[Any, Any] = {}
    for loop_id in loop_ids:
        loop = rt.loops.get_loop(loop_id)
        config = rt.loops.effective_method_config(loop, profile_id=payload.profile_id, cache=cache)
        job_ids.append(
            rt.jobs.create_job(
                loop_id=loop_id,
                name=payload.name,
                kind=payload.kind,
                lookback_minutes=payload.lookback_minutes,
                profile_id=config.get("profile_id"),
                method_config=config,
                created_by=user.username,
            )
        )
    rt.queued()
    return {"job_ids": job_ids, "queued": len(job_ids), "workers": rt.engine.dispatcher.slots}


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    if rt.jobs.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail=t("Run not found."))
    if not rt.jobs.cancel_job(job_id):
        raise HTTPException(status_code=409, detail=t("The run can no longer be cancelled."))
    rt.queue_changed()
    rt.cancel_compute(job_id)
    return job_detail(job_id, rt.asset_scope(user), rt)


def _on_assets(rt: Any, profile_id: str | None) -> bool:
    """Whether the algorithm runs on assets (else on loops, with the loop's own settings)."""

    profile = rt.presets.get_profile(profile_id) if profile_id else None
    return ((profile or {}).get("method_config") or {}).get("subject_kind") == "asset"


def _algorithm_config(rt: Any, profile_id: str | None) -> dict[str, Any]:
    profile = rt.presets.get_profile(profile_id) if profile_id else None
    return (profile or {}).get("method_config") or {}


def _checked_outputs(rt: Any, profile_id: str | None, chosen: Any) -> dict[str, Any]:
    """A schedule's "Recorded outputs" choices, checked against its algorithm (422)."""

    try:
        return checked_choices(_algorithm_config(rt, profile_id), chosen)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _checked_node_parameters(rt: Any, profile_id: str | None, chosen: Any) -> dict[str, Any]:
    """A monitor's own parameter values, kept to the nodes and parameters its algorithm has; a
    value of ``None`` (or left out) follows the algorithm."""

    from linkcraft.blocks.catalog import CATALOG
    from linkcraft.blocks.convert import diagram_of

    nodes = {
        str(node.get("id")): str(node.get("block"))
        for node in diagram_of(_algorithm_config(rt, profile_id)).get("nodes") or []
        if isinstance(node, dict)
    }
    kept: dict[str, Any] = {}
    for node_id, values in (chosen or {}).items():
        block = CATALOG.get(nodes.get(str(node_id), ""))
        if block is None or not isinstance(values, dict):
            raise HTTPException(
                status_code=422, detail=t("The algorithm has no block {node}.", node=node_id)
            )
        known = block.spec.parameters.model_fields
        unknown = [name for name in values if name not in known]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=t(
                    "{block} has no parameter {names}.", block=node_id, names=", ".join(unknown)
                ),
            )
        own = {name: value for name, value in values.items() if value is not None}
        if own:
            kept[str(node_id)] = own
    return kept


def _recorded_outputs(
    rt: Any, schedule: dict[str, Any], upcoming: list[str] | None = None
) -> list[dict[str, Any]]:
    """The outputs an asset schedule records, each with its choice and its cost per asset."""

    if schedule.get("subject_kind") != "asset":
        return []
    if upcoming is None and schedule.get("cadence") == "calendar":
        try:
            upcoming = rt.jobs.upcoming(schedule, 20)
        except ValueError:
            upcoming = []
    return schedule_outputs(
        _algorithm_config(rt, schedule.get("profile_id")),
        schedule.get("outputs"),
        runs_per_day=runs_per_day(schedule, upcoming),
    )


def _refuse_overlap(rt: Any, schedule: dict[str, Any], exclude: str | None = None) -> None:
    """Each asset runs an algorithm in one schedule only (owner, 2026-10-24): its results and
    signals then have one origin."""

    if schedule.get("kind") == "round":
        return
    subjects = (
        rt.schedule_subjects(schedule)
        if schedule.get("selector") is not None
        else [schedule.get("loop_id")]
    )
    found = rt.schedule_overlap(schedule.get("profile_id"), subjects, exclude=exclude)
    if found:
        raise HTTPException(
            status_code=409,
            detail=t(
                "{schedule} already runs this algorithm on {subjects}. An asset runs an "
                "algorithm in one monitor only: change that monitor, or choose other assets.",
                schedule=found["schedule"]["name"],
                subjects=", ".join(found["subjects"][:5])
                + ("…" if len(found["subjects"]) > 5 else ""),
            ),
        )


def _label(rt: Any, schedule: dict[str, Any]) -> str:
    if schedule.get("schedule_id") == SIGNAL_ROUND_ID:
        return t("Every signal")
    if schedule.get("kind") == "round":
        return t("Every enabled loop")
    if schedule.get("subject_kind") == "asset":
        ids = (schedule.get("selector") or {}).get("ids") or []
        return ids[0] if len(ids) == 1 else t("{count} assets", count=len(ids))
    if schedule.get("selector") is not None:
        mode = (schedule.get("selector") or {}).get("mode", "all")
        return t("Every enabled loop") if mode == "all" else t("Loops matching a rule")
    loop = rt.loops.get_loop(schedule["loop_id"])
    return f"{schedule['loop_id']} · {loop.name}" if loop else schedule["loop_id"]


def _described(rt: Any, schedule: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    """A schedule as its pages read it: what it runs, on what, and its executions' kind."""

    profile = schedule.get("profile_id") or ""
    if schedule.get("schedule_id") == SIGNAL_ROUND_ID:
        algorithm = {"id": SIGNAL_QUALITY, "name": t("Signal quality")}
    elif schedule.get("kind") == "round":
        algorithm = {"id": "", "name": t("Each loop's own algorithm")}
    else:
        algorithm = (
            {"id": algorithm_id(profile), "name": names.get(profile, profile)} if profile else None
        )
    # "Last" is when it last ran, by the calendar or by hand ("Run now").
    ran = [
        value for value in (schedule.get("last_run_at"), schedule.get("last_manual_at")) if value
    ]
    return {
        **schedule,
        "last_run_at": max(ran) if ran else None,
        "last_run_by_hand": bool(ran) and max(ran) == schedule.get("last_manual_at"),
        "subject_label": _label(rt, schedule),
        "when": schedule_when(schedule),
        "work": schedule_work(schedule),
        "algorithm": algorithm,
        "editable": {
            "subjects": schedule.get("kind") != "round",
            "timing": True,
            "algorithm": schedule.get("kind") != "round",
            "delete": schedule.get("kind") != "round",
        },
    }


def _profile_names(rt: Any) -> dict[str, str]:
    """Each algorithm's name by id, also under the 0.2 protocol ids a schedule may still keep."""

    names = {item["profile_id"]: item["name"] for item in rt.presets.list_profiles()}
    for old, new in ALGORITHM_OF_PROTOCOL.items():
        if old not in names and new in names:
            names[old] = names[new]
    return names


@router.get("/api/schedules")
def schedules(_user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    names = _profile_names(rt)
    return [_described(rt, item, names) for item in rt.jobs.list_schedules()]


def _schedule(rt: Any, schedule_id: str) -> dict[str, Any]:
    schedule = rt.jobs.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail=t("Monitor not found."))
    return _described(rt, schedule, _profile_names(rt))


@router.get("/api/schedules/{schedule_id}")
def schedule_detail(schedule_id: str, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    found = _schedule(rt, schedule_id)
    subjects = rt.schedule_subjects(found) if found["work"] != "round" else []
    return {
        **found,
        "subject_count": len(subjects),
        "subjects": subjects[:200],
        "stats": rt.jobs.schedule_stats(schedule_id),
        "recorded_outputs": _recorded_outputs(rt, found),
    }


@router.post("/api/schedules/preview")
def preview_schedule(
    payload: SchedulePayload,
    _user: EditorUser,
    rt: RuntimeDep,
    schedule_id: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    """What a schedule would do before it is saved: how many executions each occurrence
    queues, the next occurrences, and whether the queue keeps up (``Runtime.capacity``).
    With ``schedule_id`` it is that saved schedule with the form's changes."""

    if payload.cadence not in SCHEDULE_CADENCES:
        raise HTTPException(status_code=422, detail=t("Invalid frequency."))
    saved = _schedule(rt, schedule_id) if schedule_id else {}
    schedule = {
        **saved,
        "selector": payload.selector,
        "loop_id": payload.loop_id or "*",
        "profile_id": payload.profile_id,
        "cadence": payload.cadence,
        "timezone": payload.timezone,
        "time_local": payload.time_local,
        "weekday": payload.weekday,
        "scheduled_for": payload.scheduled_for,
        "interval_minutes": payload.interval_minutes,
        "spread_minutes": payload.spread_minutes,
        "recurrence": payload.recurrence.model_dump(mode="json") if payload.recurrence else None,
    }
    if saved and not saved["editable"]["timing"]:
        schedule.update(
            {
                key: saved.get(key)
                for key in ("cadence", "interval_minutes", "time_local", "weekday", "recurrence")
            }
        )
    if saved and not saved["editable"]["subjects"]:
        schedule.update({key: saved.get(key) for key in ("selector", "loop_id", "profile_id")})
    if schedule_work(schedule) == "round":
        subjects = ["*"]
    elif schedule.get("selector") is not None:
        subjects = rt.schedule_subjects(schedule)
    else:
        subjects = [payload.loop_id] if payload.loop_id else []
    try:
        upcoming = rt.jobs.upcoming(schedule, 5)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if _on_assets(rt, schedule.get("profile_id")):
        schedule["subject_kind"] = "asset"
        schedule["outputs"] = _checked_outputs(rt, schedule.get("profile_id"), payload.outputs)
        recorded = _recorded_outputs(rt, schedule, rt.jobs.upcoming(schedule, 20))
    else:
        recorded = []
    return {
        "executions": len(subjects),
        "subjects": subjects[:50],
        "next_runs": upcoming,
        "recorded_outputs": recorded,
        "when": schedule_when(schedule),
        **rt.capacity(len(subjects), schedule),
    }


@router.post("/api/schedules", status_code=201)
def create_schedule(payload: SchedulePayload, user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    if payload.cadence not in SCHEDULE_CADENCES:
        raise HTTPException(status_code=422, detail=t("Invalid frequency."))
    if payload.cadence == "once" and not payload.scheduled_for:
        raise HTTPException(
            status_code=422, detail=t("Choose the date and time of the one-off run.")
        )
    if payload.cadence == "calendar" and payload.recurrence is None:
        raise HTTPException(status_code=422, detail=t("Choose when it runs."))
    on_assets = _on_assets(rt, payload.profile_id)
    if on_assets:
        # An algorithm on assets runs on the assets the schedule names (owner, 2026-10-24).
        if not (payload.selector or {}).get("ids"):
            raise HTTPException(status_code=422, detail=t("Choose the assets it runs on."))
        payload.selector = {"mode": "list", "ids": list(dict.fromkeys(payload.selector["ids"]))}
    elif payload.selector is None:
        if not payload.loop_id:
            raise HTTPException(status_code=422, detail=t("Choose a loop or a selection rule."))
        _require_loop(rt, payload.loop_id)
    subject_id = payload.loop_id if payload.selector is None else "*"
    if on_assets:
        config: dict[str, Any] = {"profile_id": payload.profile_id}
        if payload.node_parameters:
            config["node_parameters"] = _checked_node_parameters(
                rt, payload.profile_id, payload.node_parameters
            )
    else:
        config = _method_config(
            rt, subject_id, payload.profile_id, payload.method_ids, payload.parameters
        )
    _refuse_overlap(
        rt,
        {
            "profile_id": config.get("profile_id") or payload.profile_id,
            "selector": payload.selector,
            "loop_id": subject_id,
            "subject_kind": "asset" if on_assets else "loop",
        },
    )
    try:
        schedule_id = rt.jobs.create_schedule(
            name=payload.name,
            loop_id=subject_id,
            cadence=payload.cadence,
            timezone=payload.timezone,
            lookback_minutes=payload.lookback_minutes,
            profile_id=config.get("profile_id") or payload.profile_id,
            method_config=config,
            time_local=payload.time_local,
            weekday=payload.weekday,
            scheduled_for=payload.scheduled_for,
            selector=payload.selector,
            interval_minutes=payload.interval_minutes,
            created_by=user.username,
            priority=payload.priority,
            spread_minutes=payload.spread_minutes,
            owner=payload.owner or user.username,
            subject_kind="asset" if on_assets else "loop",
            recurrence=payload.recurrence.model_dump(mode="json") if payload.recurrence else None,
            retry=payload.retry.model_dump() if payload.retry else None,
            outputs=(
                _checked_outputs(
                    rt, config.get("profile_id") or payload.profile_id, payload.outputs
                )
                if on_assets
                else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.audit(user, "schedule.created", f"schedule:{schedule_id}", payload.model_dump(mode="json"))
    rt.publish_schedules()
    return _schedule(rt, schedule_id)


@router.patch("/api/schedules/{schedule_id}")
def update_schedule(
    schedule_id: str, payload: SchedulePatchPayload, user: EditorUser, rt: RuntimeDep
) -> dict[str, Any]:
    schedule = _schedule(rt, schedule_id)
    if schedule.get("kind") == "round" and not user.is_admin:
        raise HTTPException(status_code=403, detail=t("Only admins change the loop monitor."))
    if payload.cadence is not None and payload.cadence not in SCHEDULE_CADENCES:
        raise HTTPException(status_code=422, detail=t("Invalid frequency."))
    if schedule.get("kind") == "round" and payload.selector is not None:
        raise HTTPException(status_code=422, detail=t("A run in turn covers every target."))
    if payload.enabled is not None:
        rt.jobs.set_schedule_enabled(schedule_id, payload.enabled)
    fields = payload.model_dump(mode="json", exclude_none=True, exclude={"enabled"})
    if (fields.get("cadence") or schedule.get("cadence")) == "calendar" and not (
        fields.get("recurrence") or schedule.get("recurrence")
    ):
        raise HTTPException(status_code=422, detail=t("Choose when it runs."))
    if schedule.get("subject_kind") == "asset" and payload.selector is not None:
        if not payload.selector.get("ids"):
            raise HTTPException(status_code=422, detail=t("Choose the assets it runs on."))
        fields["selector"] = {"mode": "list", "ids": list(dict.fromkeys(payload.selector["ids"]))}
    if payload.profile_id is not None and payload.profile_id != schedule.get("profile_id"):
        if schedule.get("kind") == "round":
            raise HTTPException(
                status_code=422,
                detail=t("The loop monitor runs each loop's own algorithm."),
            )
        if _on_assets(rt, payload.profile_id) != (schedule.get("subject_kind") == "asset"):
            raise HTTPException(
                status_code=422,
                detail=t(
                    "That algorithm runs on other kinds of targets: make a new monitor for it."
                ),
            )
        if schedule.get("subject_kind") == "asset":
            config = {"profile_id": payload.profile_id}
        else:
            config = _method_config(rt, schedule["loop_id"], payload.profile_id)
        fields["profile_id"] = config.get("profile_id") or payload.profile_id
        fields["method_config"] = config
    if {"profile_id", "selector"} & set(fields):
        _refuse_overlap(rt, {**schedule, **fields}, exclude=schedule_id)
    fields.pop("outputs", None)
    fields.pop("node_parameters", None)
    if schedule.get("subject_kind") == "asset" and (
        payload.node_parameters is not None or "method_config" in fields
    ):
        # The monitor's own values follow it to a new algorithm only where its blocks match.
        profile_id = fields.get("profile_id") or schedule.get("profile_id")
        config = dict(fields.get("method_config") or schedule.get("method_config") or {})
        chosen = (
            payload.node_parameters
            if payload.node_parameters is not None
            else (schedule.get("method_config") or {}).get("node_parameters")
        )
        try:
            own = _checked_node_parameters(rt, profile_id, chosen)
        except HTTPException:
            if payload.node_parameters is not None:
                raise
            own = {}
        config.pop("node_parameters", None)
        fields["method_config"] = {**config, **({"node_parameters": own} if own else {})}
    if schedule.get("subject_kind") == "asset" and (
        payload.outputs is not None or "profile_id" in fields
    ):
        chosen = payload.outputs if payload.outputs is not None else schedule.get("outputs")
        profile_id = fields.get("profile_id") or schedule.get("profile_id")
        fields["outputs"] = _checked_outputs(rt, profile_id, chosen)
    if fields:
        try:
            rt.jobs.update_schedule(schedule_id, **fields)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.audit(user, "schedule.updated", f"schedule:{schedule_id}", payload.model_dump(mode="json"))
    rt.publish_schedules()
    return _schedule(rt, schedule_id)


@router.post("/api/schedules/{schedule_id}/run", status_code=202)
def run_schedule(schedule_id: str, user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """Run one occurrence now (the round, or one run per selected loop)."""

    schedule = _schedule(rt, schedule_id)
    if schedule.get("kind") == "round":
        job_id = rt.queue_round(schedule_id, user=user.username)
        return {"started": job_id is not None, "job_ids": [job_id] if job_id else []}
    subjects = rt.schedule_subjects(schedule) if schedule.get("selector") is not None else None
    job_ids = rt.jobs.run_schedule_now(schedule_id, subjects, user=user.username)
    rt.queued()
    return {"started": bool(job_ids), "job_ids": job_ids}


class ScheduleReplayPayload(BaseModel):
    hours: float = Field(default=24, gt=0, le=MAX_HOURS)
    step_minutes: float = Field(default=60, ge=5, le=24 * 60)


@router.post("/api/schedules/{schedule_id}/replay", status_code=202)
def replay_schedule(
    schedule_id: str, user: AdminUser, rt: RuntimeDep, payload: ScheduleReplayPayload | None = None
) -> dict[str, Any]:
    """Run a schedule's past occurrences over the archive (admins; one replay at a time)."""

    schedule = _schedule(rt, schedule_id)
    if schedule["work"] not in {"round", "loop"} or schedule_id == SIGNAL_ROUND_ID:
        raise HTTPException(
            status_code=409, detail=t("Only the loops' monitors can be replayed for now.")
        )
    payload = payload or ScheduleReplayPayload()
    job_id = rt.queue_replay(payload.hours, payload.step_minutes, user.username, schedule_id)
    if job_id is None:
        raise HTTPException(status_code=409, detail=t("A replay is already waiting or running."))
    rt.audit(user, "schedule.replayed", f"schedule:{schedule_id}", payload.model_dump())
    return {"started": True, "job_id": job_id}


@router.delete("/api/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, user: EditorUser, rt: RuntimeDep) -> Response:
    schedule = _schedule(rt, schedule_id)
    if not schedule["editable"]["delete"]:
        raise HTTPException(
            status_code=409,
            detail=t("This monitor can be paused, not deleted."),
        )
    rt.jobs.delete_schedule(schedule_id)
    rt.folders.forget("schedule", schedule_id)
    rt.audit(user, "schedule.deleted", f"schedule:{schedule_id}")
    rt.publish_schedules()
    return Response(status_code=204)


@router.patch("/api/round")
def update_round(
    user: AdminUser,
    rt: RuntimeDep,
    enabled: Annotated[bool | None, Query()] = None,
    interval_minutes: Annotated[float | None, Query(ge=1, le=60 * 24)] = None,
) -> dict[str, Any]:
    """Pause, resume or re-time the monitoring round (admins)."""

    if enabled is not None:
        rt.jobs.set_schedule_enabled(ROUND_ID, enabled)
    if interval_minutes is not None:
        rt.jobs.update_schedule(ROUND_ID, interval_minutes=interval_minutes)
    rt.audit(
        user, "round.updated", ROUND_ID, {"enabled": enabled, "interval_minutes": interval_minutes}
    )
    rt.publish_schedules()
    return rt.status()


class ReplayPayload(BaseModel):
    hours: float = Field(default=48, gt=0, le=MAX_HOURS)
    step_minutes: float = Field(default=60, ge=5, le=24 * 60)


@router.post("/api/history/replay", status_code=202)
def replay_history(
    user: AdminUser, rt: RuntimeDep, payload: ReplayPayload | None = None
) -> dict[str, Any]:
    """Fill the past from the archive: the round's health history and the schedules' runs
    (admins; in the background, ``GET`` says how far it got)."""

    payload = payload or ReplayPayload()
    job_id = rt.queue_replay(payload.hours, payload.step_minutes, user=user.username)
    if job_id:
        rt.audit(user, "history.replayed", ROUND_ID, payload.model_dump())
    return {"started": job_id is not None, **rt.replay_state()}


@router.get("/api/history/replay")
def replay_status(_user: AdminUser, rt: RuntimeDep) -> dict[str, Any]:
    return rt.replay_state()
