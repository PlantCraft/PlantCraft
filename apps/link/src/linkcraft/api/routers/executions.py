"""Executions: everything the queue ran, runs and will run, on one list.

An execution is one item of the queue (``engine.jobs``): an algorithm on a loop, a round (every
loop, or Signal quality on every signal), an algorithm on an asset, or the past replayed. The
Executions page lists them with the queue's panel (``GET /api/queue``); a person cancels one
still waiting or runs one again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.utc import utc_iso

from linkcraft.api.deps import EditorUser, RuntimeDep
from linkcraft.api.runtime import SIGNAL_ROUND_ID
from linkcraft.api.scope import Scope, paged, sees_job
from linkcraft.catalog.loop_types import ALGORITHM_OF_PROTOCOL, algorithm_id
from linkcraft.engine.dispatcher import schedule_tries
from linkcraft.engine.jobs import JOB_STATUSES, WORKS
from linkcraft.i18n import t
from linkcraft.knowledge import SIGNAL_RUN_PREFIX

router = APIRouter(prefix="/api/executions")

# An execution's state in the suite's words (the colours of its pill).
STATE = {
    "completed": "ok",
    "failed": "alarm",
    "cancelled": "unknown",
    "skipped": "warning",
    "running": "running",
    "queued": "pending",
    "scheduled": "pending",
    "waiting_data": "pending",
}


def _moment(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _seconds(start: Any, end: Any) -> float | None:
    first, last = _moment(start), _moment(end)
    if first is None or last is None:
        return None
    return round(max(0.0, (last - first).total_seconds()), 1)


def _subject(job: dict[str, Any]) -> tuple[str, str | None]:
    """What an execution worked on, and the page that shows it."""

    work = job.get("work") or "loop"
    subject = job["loop_id"]
    if work == "round":
        signals = job.get("schedule_id") == SIGNAL_ROUND_ID
        found = (job.get("summary") or {}).get("round")
        path = f"/runs/{SIGNAL_RUN_PREFIX}{found}" if signals and found else None
        return (t("Every signal") if signals else t("Every loop")), path
    if work == "replay":
        hours = (job.get("payload") or {}).get("hours")
        return t("The last {hours} hours", hours=f"{float(hours or 0):g}"), None
    if work == "asset":
        return subject, f"/assets/{quote(subject, safe='')}"
    return subject, f"/loops/{quote(subject, safe='')}"


def execution_row(
    job: dict[str, Any],
    schedules: dict[str, str],
    profiles: dict[str, str],
    tries: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    work = job.get("work") or "loop"
    subject, subject_path = _subject(job)
    status = job["status"]
    algorithm = job.get("profile_id") or ""
    return {
        "id": job["job_id"],
        "name": job.get("name") or "",
        "work": work,
        "work_label": t(WORKS.get(work, work)),
        "algorithm": (
            {"id": algorithm_id(algorithm), "name": profiles.get(algorithm, "")}
            if algorithm
            else None
        ),
        "subject": subject,
        "subject_path": subject_path,
        "path": f"/runs/{job['job_id']}" if work == "loop" else subject_path,
        "schedule": (
            {"id": job["schedule_id"], "name": schedules.get(job["schedule_id"], "")}
            if job.get("schedule_id")
            else None
        ),
        "status": status,
        "state": STATE.get(status, "unknown"),
        "status_label": t(JOB_STATUSES.get(status, status)),
        "kind": job.get("kind"),
        "priority": job.get("priority"),
        "requested_at": job.get("requested_at"),
        "due_at": job.get("due_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("completed_at"),
        "wait_seconds": _seconds(
            job.get("due_at") or job.get("requested_at"), job.get("started_at")
        ),
        "duration_seconds": _seconds(job.get("started_at"), job.get("completed_at")),
        "attempts": job.get("attempts") or 0,
        # How many tries its schedule gives it ("try 2 of 3"); None: the queue's own.
        "max_attempts": (tries or {}).get(job.get("schedule_id") or ""),
        "progress": (
            {"done": job.get("progress_done") or 0, "total": job["progress_total"]}
            if job.get("progress_total")
            else None
        ),
        "error": job.get("error_message") or "",
        "by": job.get("created_by") or "",
        "worker": job.get("worker") or "",
        "can_cancel": status in {"queued", "scheduled", "waiting_data"},
        "can_rerun": status not in {"queued", "running", "scheduled", "waiting_data"},
    }


# The suite Queue's words for an execution's status (``plantcraft-queue/1`` items).
QUEUE_STATUS = {
    "scheduled": "queued",
    "waiting_data": "queued",
    "queued": "queued",
    "running": "running",
    "completed": "done",
    "failed": "failed",
    "cancelled": "cancelled",
    "skipped": "cancelled",
}
# Who the engine itself names when no person asked.
NOBODY = {"", "System", "Engineering"}
# Works the Queue lists while they run even when no person asked (a round, a replay); the
# scheduled algorithm on each loop stays in the numbers only.
LISTED_WORKS = {"round", "replay"}
QUEUE_ITEMS = 30
QUEUE_KEEP_HOURS = 24


def queue_item(job: dict[str, Any], root: str) -> dict[str, Any]:
    """One execution as an item of the suite Queue: who asked, how far it got, Cancel."""

    status = QUEUE_STATUS.get(job["status"], "queued")
    subject, subject_path = _subject(job)
    path = f"/runs/{job['job_id']}" if (job.get("work") or "loop") == "loop" else subject_path
    total = int(job.get("progress_total") or 0)
    progress = None
    if status == "running" and total:
        progress = round(min(1.0, int(job.get("progress_done") or 0) / total), 3)
    elif status == "done":
        progress = 1.0
    by = job.get("created_by") or ""
    item = {
        "id": job["job_id"],
        "name": job.get("name") or subject,
        "by": "" if by in NOBODY else by,
        "status": status,
        "progress": progress,
        "step": (
            f"{int(job.get('progress_done') or 0)}/{total}" if status == "running" and total else ""
        ),
        "url": f"{root.rstrip('/')}{path or '/executions'}",
        "started_at": job.get("started_at"),
        "finished_at": job.get("completed_at"),
        "queued_at": job.get("requested_at"),
    }
    if job["status"] in {"queued", "scheduled", "waiting_data"}:
        item["cancel"] = {
            "label": "Cancel",
            "method": "POST",
            "href": f"{root.rstrip('/')}/api/executions/{job['job_id']}/cancel",
        }
    return item


def queue_items(rt: Any) -> list[dict[str, Any]]:
    """What the suite Queue lists by name: the executions a person asked for (waiting, running
    or ended in the last 24 hours) and the rounds and replays running now, newest first."""

    since = utc_iso(datetime.now(UTC) - timedelta(hours=QUEUE_KEEP_HOURS))
    active = rt.jobs.list_jobs(statuses={"queued", "running"}, limit=200)
    recent = rt.jobs.list_jobs(since=since, limit=200)
    found: dict[str, dict[str, Any]] = {}
    for job in [*active, *recent]:
        asked = (job.get("created_by") or "") not in NOBODY
        running = job["status"] == "running" and (job.get("work") or "loop") in LISTED_WORKS
        if asked or running:
            found.setdefault(job["job_id"], job)
    order = {"running": 0, "queued": 1}
    items = [queue_item(job, rt.root_path) for job in found.values()]
    items.sort(
        key=lambda item: item["finished_at"] or item["started_at"] or item["queued_at"] or "",
        reverse=True,
    )
    items.sort(key=lambda item: order.get(item["status"], 2))
    return items[:QUEUE_ITEMS]


def schedule_names(rt: Any) -> tuple[dict[str, str], dict[str, int | None]]:
    """Each schedule's name and the tries it gives an execution, for its executions' rows."""

    found = rt.jobs.list_schedules()
    return (
        {item["schedule_id"]: item["name"] for item in found},
        {item["schedule_id"]: schedule_tries(item) for item in found},
    )


def _names(rt: Any) -> tuple[dict[str, str], dict[str, str], dict[str, int | None]]:
    schedules, tries = schedule_names(rt)
    profiles = {item["profile_id"]: item["name"] for item in rt.presets.list_profiles()}
    # schedules and runs may still keep a 0.2 protocol id: named as the algorithm that replaced it
    for old, new in ALGORITHM_OF_PROTOCOL.items():
        if old not in profiles and new in profiles:
            profiles[old] = profiles[new]
    return schedules, profiles, tries


@router.get("")
def executions(
    scope: Scope,
    rt: RuntimeDep,
    status: Annotated[list[str] | None, Query()] = None,
    work: Annotated[list[str] | None, Query()] = None,
    schedule_id: Annotated[str | None, Query(max_length=120)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    hours: Annotated[float | None, Query(gt=0, le=24 * 400)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The executions, newest first, with how many match."""

    filters: dict[str, Any] = {
        "statuses": set(status) if status else None,
        "works": set(work) if work else None,
        "schedule_id": schedule_id or None,
        "query": q.strip() if q and q.strip() else None,
        "since": (utc_iso(datetime.now(UTC) - timedelta(hours=hours)) if hours else None),
    }
    schedules, profiles, tries = _names(rt)
    if scope.everything:
        rows, total = rt.jobs.list_jobs(**filters, limit=limit, offset=offset), None
    else:
        rows, total = paged(scope, rt, rt.jobs.list_jobs(**filters, limit=5000), limit, offset)
    return {
        "total": rt.jobs.count_jobs(**filters) if total is None else total,
        "items": [execution_row(job, schedules, profiles, tries) for job in rows],
        "works": {key: t(label) for key, label in WORKS.items()},
        "statuses": {key: t(label) for key, label in JOB_STATUSES.items()},
    }


# Series one chart asks for at once (a subject's outputs and its algorithm's version).
MAX_SERIES = 20
OWN_SERIES = "app-linkcraft:"


@router.get("/series")
def series(
    scope: Scope,
    rt: RuntimeDep,
    signal: Annotated[list[str], Query(max_length=MAX_SERIES)],
    start: Annotated[str | None, Query(max_length=40)] = None,
) -> dict[str, Any]:
    """Link's own series in the Historian (``app-linkcraft:...``), for the Executions charts.

    A series that cannot be read comes back empty with why, so one missing series never hides
    the others."""

    found = []
    for item in dict.fromkeys(signal):
        if not item.startswith(OWN_SERIES):
            raise HTTPException(
                status_code=422, detail=t("Only Analytics' own derived signals are read here.")
            )
        if not scope.signal(item):
            # Outside the person's part of the plant: as a series not written yet.
            found.append({"signal": item, "t": [], "v": [], "error": t("Signal not found.")})
            continue
        try:
            answer = rt.own_series(item, start)
            found.append({"signal": item, "t": answer.get("t") or [], "v": answer.get("v") or []})
        except Exception as exc:  # not written yet, or the Historian away
            found.append({"signal": item, "t": [], "v": [], "error": str(exc)})
    return {"series": found}


def _job(rt: Any, execution_id: str, scope: Any = None) -> dict[str, Any]:
    job = rt.jobs.get_job(execution_id)
    if job is None or (scope is not None and not sees_job(scope, rt, job)):
        raise HTTPException(status_code=404, detail=t("Execution not found."))
    return job


def _row(rt: Any, execution_id: str) -> dict[str, Any]:
    schedules, profiles, tries = _names(rt)
    return execution_row(_job(rt, execution_id), schedules, profiles, tries)


@router.post("/{execution_id}/cancel")
def cancel(execution_id: str, user: EditorUser, rt: RuntimeDep, scope: Scope) -> dict[str, Any]:
    """Take an execution out of the queue before it starts."""

    _job(rt, execution_id, scope)
    if not rt.jobs.cancel_job(execution_id):
        raise HTTPException(status_code=409, detail=t("Only a run still waiting can be cancelled."))
    rt.queue_changed()
    rt.cancel_compute(execution_id)
    rt.audit(user, "execution.cancelled", f"execution:{execution_id}")
    return _row(rt, execution_id)


@router.post("/{execution_id}/rerun", status_code=202)
def rerun(execution_id: str, user: EditorUser, rt: RuntimeDep, scope: Scope) -> dict[str, Any]:
    """Run an execution again now, as a person's request (ahead of the schedules)."""

    job = _job(rt, execution_id, scope)
    if job["status"] in {"queued", "running", "scheduled", "waiting_data"}:
        raise HTTPException(status_code=409, detail=t("This run has not ended yet."))
    work = job.get("work") or "loop"
    if work == "round":
        new_id = rt.queue_round(job.get("schedule_id") or "", user=user.username)
    elif work == "replay":
        payload = job.get("payload") or {}
        new_id = rt.queue_replay(
            float(payload.get("hours") or 48),
            float(payload.get("step_minutes") or 60),
            user.username,
        )
    else:
        new_id = rt.jobs.create_job(
            loop_id=job["loop_id"],
            name=job.get("name") or "",
            kind="manual",
            lookback_minutes=job.get("lookback_minutes"),
            range_start=job.get("range_start"),
            range_end=job.get("range_end"),
            profile_id=job.get("profile_id"),
            method_config=job.get("method_config") or {},
            created_by=user.username,
            application_id=job.get("application_id") or "cpm",
            subject_kind=job.get("subject_kind") or "loop",
            work=work,
            payload=job.get("payload") or None,
        )
        rt.queued()
    if not new_id:
        raise HTTPException(
            status_code=409, detail=t("The same work is already waiting or running.")
        )
    rt.audit(user, "execution.rerun", f"execution:{execution_id}", {"execution": new_id})
    return _row(rt, new_id)
