"""Runs and where an algorithm is used, read the same way whatever the algorithm.

A run is one execution of an algorithm: a Signal quality round over every signal, or a loop
algorithm on one loop. The Results page lists them on one history (no page
split between signal quality and loops); an algorithm's page says where it is used (its schedules
and the subjects that use it), not its last runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query

from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.api.routers.engine import _label
from linkcraft.api.runtime import SIGNAL_ROUND_ID
from linkcraft.api.scope import Scope, sees_job
from linkcraft.blocks.algorithms import SIGNAL_QUALITY
from linkcraft.catalog.loop_types import algorithm_id
from linkcraft.engine.jobs import JOB_STATUSES
from linkcraft.i18n import t
from linkcraft.knowledge import SIGNAL_RUN_PREFIX

router = APIRouter(prefix="/api")

SIGNAL_ALGORITHM = SIGNAL_QUALITY
# A run's state in the suite's words: done ok, failed alarm, the rest not settled yet.
ROUND_STATE = {"ok": "ok", "error": "alarm", "interrupted": "warning", "running": "running"}
ROUND_LABEL = {
    "ok": "Finished",
    "error": "Failed",
    "interrupted": "Interrupted",
    "running": "Running",
}
JOB_STATE = {
    "completed": "ok",
    "failed": "alarm",
    "cancelled": "unknown",
    "running": "running",
    "queued": "pending",
    "scheduled": "pending",
    "waiting_data": "pending",
    "skipped": "unknown",
}
VERDICTS = ("bad", "suspect", "good", "unchecked")


def _round_run(row: dict[str, Any]) -> dict[str, Any]:
    counts = row.get("counts") or {}
    found = ", ".join(f"{counts[key]} {t(key)}" for key in VERDICTS if counts.get(key))
    return {
        "id": f"{SIGNAL_RUN_PREFIX}{row['id']}",
        "path": f"/runs/{SIGNAL_RUN_PREFIX}{row['id']}",
        "algorithm": {"id": SIGNAL_ALGORITHM, "name": t("Signal quality")},
        "subject": t("{count} signals", count=row.get("signals") or 0),
        "state": ROUND_STATE.get(str(row.get("status")), "unknown"),
        "status_label": t(ROUND_LABEL.get(str(row.get("status")), str(row.get("status")))),
        "started_at": row.get("started_at"),
        "duration_seconds": row.get("duration_seconds"),
        "finding": row.get("error") or found,
        "trigger": t("Monitor") if row.get("trigger") == "schedule" else t("Run now"),
        "by": row.get("started_by") or "",
    }


def _job_run(job: dict[str, Any], profiles: dict[str, str]) -> dict[str, Any]:
    summary = job.get("summary") or {}
    limiting = summary.get("limiting") or {}
    health = summary.get("health")
    finding = job.get("error_message") or limiting.get("finding") or ""
    if health is not None and not job.get("error_message"):
        finding = t("Health {health}", health=round(float(health))) + (
            f" · {finding}" if finding else ""
        )
    started = job.get("started_at") or job.get("requested_at")
    duration = None
    if job.get("started_at") and job.get("finished_at"):
        try:
            duration = (
                datetime.fromisoformat(str(job["finished_at"]))
                - datetime.fromisoformat(str(job["started_at"]))
            ).total_seconds()
        except ValueError:
            duration = None
    return {
        "id": job["job_id"],
        "path": f"/runs/{job['job_id']}",
        "algorithm": {
            "id": algorithm_id(job.get("profile_id")) if job.get("profile_id") else "",
            "name": profiles.get(algorithm_id(job.get("profile_id") or ""), "")
            or job.get("name")
            or "",
        },
        "subject": job["loop_id"],
        "subject_path": f"/loops/{quote(job['loop_id'], safe='')}",
        "state": JOB_STATE.get(job["status"], "unknown"),
        "status_label": t(JOB_STATUSES.get(job["status"], job["status"])),
        "started_at": started,
        "duration_seconds": duration,
        "finding": finding,
        "trigger": t("Monitor") if job.get("schedule_id") else t("Run now"),
        "by": job.get("created_by") or "",
    }


def run_rows(rt: Any, limit: int, scope: Any) -> list[dict[str, Any]]:
    """Every algorithm's runs (on what the person sees), newest first."""

    profiles = {item["profile_id"]: item["name"] for item in rt.presets.list_profiles()}
    rows = [_round_run(row) for row in rt.quality_results.rounds(limit)]
    # A round's own execution is in Executions; its runs are the Signal quality round above
    # and each loop's latest result.
    rows += [
        _job_run(job, profiles)
        for job in rt.jobs.list_jobs(works={"loop"}, limit=limit)
        if sees_job(scope, rt, job)
    ]
    rows.sort(key=lambda row: str(row["started_at"] or ""), reverse=True)
    return rows[:limit]


@router.get("/runs")
def runs(
    rt: RuntimeDep, scope: Scope, limit: int = Query(default=500, ge=1, le=2000)
) -> dict[str, Any]:
    """Runs of every algorithm on one history, newest first."""

    items = run_rows(rt, limit, scope)
    return {"total": len(items), "items": items}


@router.get("/algorithms/{profile_id}/usage")
def usage(profile_id: str, rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """Where an algorithm is used: its schedules and the subjects it works on."""

    profile_id = algorithm_id(profile_id)
    schedules = []
    for item in rt.jobs.list_schedules():
        mine = (
            item["schedule_id"] == SIGNAL_ROUND_ID
            if profile_id == SIGNAL_ALGORITHM
            else algorithm_id(item.get("profile_id")) == profile_id and item.get("kind") != "round"
        )
        if mine:
            schedules.append({**item, "subject_label": _label(rt, item)})
    if profile_id == SIGNAL_ALGORITHM:
        count = sum(1 for row in rt.signal_store.list() if row["enabled"] and not row["missing"])
        return {
            "algorithm": {"id": SIGNAL_ALGORITHM, "name": t("Signal quality")},
            "schedules": schedules,
            "subjects": {"kind": "signal", "count": count, "items": [], "every": True},
        }
    profile = rt.presets.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=t("Algorithm not found."))
    loops = [
        {
            "id": row["loop_id"],
            "name": row["name"],
            "caption": row["service"] or row["area"] or "",
            "status": row["status"],
            "health": row["health"],
            "path": f"/loops/{quote(row['loop_id'], safe='')}",
        }
        for row in rt.monitor.overview_rows()
        if algorithm_id(row["profile_id"]) == profile_id
    ]
    return {
        "algorithm": {"id": profile_id, "name": profile["name"]},
        "schedules": schedules,
        "subjects": {"kind": "loop", "count": len(loops), "items": loops, "every": False},
    }
