"""The Signal quality algorithm (its settings, its runs, run now) and the Overview.

Signal quality is a system algorithm: it runs the data quality checks (Methods, Data quality) on
every signal PlantCraft knows, on its own schedule (``round-signal_quality`` in Runs). Admins
set its window, which checks run and their default parameters; a signal can switch a check off
or on and override parameters for itself (Signals).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from linkcraft.api.deps import AdminUser, CurrentUser, EditorUser, RuntimeDep
from linkcraft.api.routers.results import signal_label
from linkcraft.api.routers.signals import signal_overview
from linkcraft.api.runtime import ROUND_ID, SIGNAL_ROUND_ID
from linkcraft.api.scope import Scope, sees_loop
from linkcraft.blocks.algorithms import SIGNAL_QUALITY
from linkcraft.catalog.signal_checks import CHECKS, describe, validate_parameters
from linkcraft.i18n import t
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND
from linkcraft.signals.models import SignalQualitySettings

router = APIRouter(prefix="/api")
WEEK_DAYS = 7
# The suite's dashboards app: the Overview links to it (it never draws dashboards itself).
DASHBOARD_URL = "/dash/"


def algorithm(rt: Any) -> dict[str, Any]:
    settings = rt.quality_settings.get()
    schedule = rt.jobs.get_schedule(SIGNAL_ROUND_ID) or {}
    enabled = set(settings.enabled_checks or CHECKS)
    running, progress = rt.round_state(SIGNAL_ROUND_ID, rt.quality_engine)
    return {
        "id": SIGNAL_QUALITY,
        "name": t("Signal quality"),
        "description": t(
            "Checks every signal's raw samples with the data quality methods and gives each "
            "signal a result (good, suspect, bad), a 0-100 quality and whether its data is "
            "usable; each asset gets the worst of its signals. Loops read these results "
            "before they are judged."
        ),
        "system": True,
        "settings": settings.model_dump(),
        "schedule": {
            key: schedule.get(key)
            for key in ("schedule_id", "enabled", "interval_minutes", "next_run_at", "last_run_at")
        },
        "checks": [
            {
                **describe(check_id, settings.check_parameters.get(check_id)),
                "enabled": check_id in enabled,
            }
            for check_id in CHECKS
        ],
        "running": running,
        "progress": progress,
        "sync": rt.quality_engine.last_sync,
        "signal_count": rt.signal_store.count(),
        "published": rt.quality_publisher.published,
    }


@router.get("/signal-quality")
def get_algorithm(_user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    return algorithm(rt)


class AlgorithmUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: float | None = Field(default=None, ge=1.0, le=7 * 24 * 60)
    window_hours: float | None = Field(default=None, gt=0.0, le=31 * 24)
    enabled_checks: list[str] | None = None
    # Every check runs (including checks added later) when this is true.
    all_checks: bool = False
    check_parameters: dict[str, dict[str, Any]] | None = None


def merge_check_parameters(
    current: dict[str, dict[str, Any]], given: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Parameters merge per check; a null value puts that parameter back to its default."""

    for check_id, values in given.items():
        if check_id not in CHECKS:
            raise HTTPException(422, t("Unknown checks: {names}.", names=check_id))
        try:
            validate_parameters(
                check_id, {key: value for key, value in values.items() if value is not None}
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    merged = {key: dict(value) for key, value in current.items()}
    for check_id, values in given.items():
        entry = merged.setdefault(check_id, {})
        for name, value in values.items():
            if value is None:
                entry.pop(name, None)
            else:
                entry[name] = value
    return {key: value for key, value in merged.items() if value}


@router.put("/signal-quality")
def update_algorithm(body: AlgorithmUpdate, rt: RuntimeDep, user: AdminUser) -> dict[str, Any]:
    current = rt.quality_settings.get().model_dump()
    given = body.model_dump(exclude_unset=True)
    if body.enabled_checks is not None:
        unknown = [item for item in body.enabled_checks if item not in CHECKS]
        if unknown:
            raise HTTPException(422, t("Unknown checks: {names}.", names=", ".join(unknown)))
        current["enabled_checks"] = list(body.enabled_checks)
    if body.all_checks:
        current["enabled_checks"] = None
    if body.window_hours is not None:
        current["window_hours"] = body.window_hours
    if body.check_parameters is not None:
        current["check_parameters"] = merge_check_parameters(
            current.get("check_parameters") or {}, body.check_parameters
        )
    try:
        settings = SignalQualitySettings(**current)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rt.quality_settings.save(settings, user.username)
    if body.enabled is not None:
        rt.jobs.set_schedule_enabled(SIGNAL_ROUND_ID, body.enabled)
    if body.interval_minutes is not None:
        rt.jobs.update_schedule(SIGNAL_ROUND_ID, interval_minutes=body.interval_minutes)
    rt.audit(user, "signal_quality.updated", "algorithm:signal_quality", given)
    rt.publish_schedules()
    return algorithm(rt)


@router.post("/signal-quality/run", status_code=202)
def run_now(user: EditorUser, rt: RuntimeDep) -> dict[str, Any]:
    """Start the algorithm now in the background (the app's service token reads the data)."""

    if not rt.has_service_key:
        raise HTTPException(
            409,
            t(
                "Runs need an app key: an admin creates one in PlantCraft and sets "
                "PLANTCRAFT_APP_KEY for Analytics."
            ),
        )
    schedule = rt.jobs.get_schedule(SIGNAL_ROUND_ID)
    job_id = rt.queue_round(SIGNAL_ROUND_ID, user=user.username) if schedule else None
    if job_id is None:
        raise HTTPException(409, t("The Signal quality algorithm is already running."))
    rt.audit(user, "signal_quality.run", "algorithm:signal_quality")
    return {"started": True, "job_id": job_id}


@router.get("/signal-quality/runs")
def runs(
    _user: CurrentUser, rt: RuntimeDep, limit: int = Query(default=50, ge=1, le=500)
) -> list[dict[str, Any]]:
    return rt.quality_results.rounds(limit)


@router.get("/signal-quality/runs/{run_id}")
def run(run_id: int, _user: CurrentUser, rt: RuntimeDep, scope: Scope) -> dict[str, Any]:
    """The run, with the signals it judged whose latest verdict it still is, worst first."""

    found = rt.quality_results.round(run_id)
    if found is None:
        raise HTTPException(404, t("Run not found."))
    order = {"bad": 0, "suspect": 1, "unknown": 2, "good": 3}
    found["results"] = sorted(
        (
            {**row, "name": signal_label(row["signal_id"])}
            for row in rt.quality_results.of_round(run_id)
            if scope.signal(row["signal_id"])
        ),
        key=lambda row: (
            order.get(row["status"], 9),
            101 if row["quality"] is None else row["quality"],
            row["name"],
        ),
    )
    return found


def _week_of_loops(rt: Any) -> list[dict[str, Any]]:
    """Per day of the last week: the loops' mean health and how many were judged."""

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=WEEK_DAYS)
    stamp = "%Y-%m-%d %H:%M:%S"
    last = rt.latest.last_source_end(APPLICATION_ID, SUBJECT_KIND)
    if last:  # a recorded plant: its week ends at its newest data
        try:
            newest = datetime.fromisoformat(str(last).replace(" ", "T"))
            if newest.tzinfo is None:
                newest = newest.replace(tzinfo=timezone.utc)
            end = min(end, newest.astimezone(timezone.utc) + timedelta(seconds=1))
            start = end - timedelta(days=WEEK_DAYS)
        except ValueError:
            pass
    buckets = rt.latest.health_buckets(
        APPLICATION_ID,
        SUBJECT_KIND,
        _stored(rt, start, stamp),
        _stored(rt, end, stamp),
        86400,
    )
    days: dict[int, list[float]] = {}
    for item in buckets:
        if item["health"] is not None:
            days.setdefault(int(item["bucket"]), []).append(float(item["health"]))
    found = []
    first = int(start.timestamp()) // 86400 * 86400
    for offset in range(WEEK_DAYS + 1):
        bucket = first + offset * 86400
        values = days.get(bucket, [])
        found.append(
            {
                "day": datetime.fromtimestamp(bucket, timezone.utc).date().isoformat(),
                "loops": len(values),
                "mean_health": round(sum(values) / len(values), 1) if values else None,
                "below_60": sum(1 for value in values if value < 60),
            }
        )
    return [item for item in found if item["loops"]] or found[-WEEK_DAYS:]


def _stored(rt: Any, moment: datetime, stamp: str) -> str:
    """A time in the format ``source_end`` is stored in (``engine.latest``)."""

    return moment.astimezone(timezone.utc).strftime(stamp)


@router.get("/overview")
def overview(scope: Scope, rt: RuntimeDep) -> dict[str, Any]:
    """Now and the week, for signals and loops, and where the app's dashboard lives."""

    loops = [row for row in rt.monitor.overview_rows() if sees_loop(scope, rt, row["loop_id"])]
    counts: dict[str, int] = {}
    for row in loops:
        status = str(row.get("status") or "pending")
        counts[status] = counts.get(status, 0) + 1
    worst = [row for row in loops if row.get("status") in {"critical", "high", "medium"}][:8]
    healths = [float(row["health"]) for row in loops if row.get("health") is not None]
    round_status = rt.status()
    return {
        "signals": signal_overview(rt, scope),
        "loops": {
            "total": len(loops),
            "counts": counts,
            "mean_health": round(sum(healths) / len(healths), 1) if healths else None,
            "worst": worst,
            "last_round": round_status.get("round"),
            "running": round_status.get("running"),
        },
        "week": {
            "signals": rt.quality_results.daily(WEEK_DAYS),
            "loops": _week_of_loops(rt),
        },
        "dashboard_url": DASHBOARD_URL,
        "round_id": ROUND_ID,
    }
