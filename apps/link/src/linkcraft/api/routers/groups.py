"""Executions by schedule: the schedules, each schedule's subjects, one subject's history.

One page answers what Link concluded and when (Executions and Results were
the same thing by two paths). It opens on the schedules (what each runs, on how many subjects,
its last execution and the next); a schedule shows its subjects with the latest result of each;
a subject shows that result first, its outputs over time (the Historian series Link writes, one
per asset, algorithm and output, with a mark where a version started) and its past executions.
Executions a person asked for outside any schedule are in one more folder, ``manual``.

Status is a discreet word beside each subject (Normal, High, Critical...), never an order:
lists are by name, and what deserves attention is the Alarms app's job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query

from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.api.routers.executions import execution_row, schedule_names
from linkcraft.api.runtime import DETAIL_KEPT
from linkcraft.api.scope import Scope, sees_subject
from linkcraft.api.subjects import (
    ASSET_STATE,
    ASSET_WORDS,
    LOOP_WORDS,
    ROUND_ID,
    SIGNAL_ROUND_ID,
    SIGNAL_WORDS,
    job_rows,
    job_state,
    kind_of,
    latest_jobs,
    subject_rows,
    subjects_of,
)
from linkcraft.assets.outputs import SERIES
from linkcraft.blocks.algorithms import SIGNAL_QUALITY
from linkcraft.catalog.loop_types import algorithm_id as current_algorithm
from linkcraft.engine.samples import ROUND_SCOPE, SAMPLES_KEPT, loop_run_key
from linkcraft.i18n import t
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND
from linkcraft.loops.suite import (
    DEFAULT_ALGORITHM,
    HEALTH_SERIES,
    SUITE_STATUS,
    VERSION_PREFIX,
    VERSION_SERIES,
    schedule_when,
    series_id,
)
from linkcraft.signals.publish import STATUS as SIGNAL_STATUS

router = APIRouter(prefix="/api/executions/groups")

MANUAL = "manual"
# A signal check's status as a result's (Signal quality: ok, warning, bad, insufficient data).
CHECK_STATUS = {"ok": "ok", "warning": "warning", "suspect": "warning", "bad": "bad"}
COUNTED = ("ok", "warning", "alarm", "unknown")


def _algorithms(rt: Any) -> dict[str, dict[str, Any]]:
    return {
        item["profile_id"]: {
            "id": item["profile_id"],
            "name": item["name"],
            "version": int(item.get("version") or 1),
        }
        for item in rt.presets.list_profiles()
    }


def _algorithm(rt: Any, schedule: dict[str, Any], algorithms: dict[str, Any]) -> dict | None:
    if schedule["schedule_id"] == SIGNAL_ROUND_ID:
        found = algorithms.get(SIGNAL_QUALITY) or {}
        return {"id": SIGNAL_QUALITY, "name": t("Signal quality"), "version": found.get("version")}
    if schedule["schedule_id"] == ROUND_ID:
        return {"id": "", "name": t("Each loop's own algorithm"), "version": None}
    # a schedule made before 0.3 may keep a protocol id: the algorithm that replaced it
    profile = current_algorithm(schedule.get("profile_id")) if schedule.get("profile_id") else ""
    return algorithms.get(profile) or ({"id": profile, "name": profile} if profile else None)


def _rows(rt: Any, schedule: dict[str, Any], scope: Any) -> list[dict[str, Any]]:
    rows = [item for item in subject_rows(rt, schedule) if sees_subject(scope, rt, item["id"])]
    base = f"/executions/{quote(schedule['schedule_id'], safe='')}"
    for item in rows:
        item["path"] = f"{base}/{quote(item['id'], safe='')}"
    return rows


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(COUNTED, 0)
    for row in rows:
        counts[row["state"] if row["state"] in counts else "unknown"] += 1
    return counts


def _group(
    rt: Any, schedule: dict[str, Any], algorithms: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "id": schedule["schedule_id"],
        "name": schedule["name"],
        "kind": schedule.get("kind") or "protocol",
        "algorithm": _algorithm(rt, schedule, algorithms),
        "subject_kind": kind_of(schedule)
        if kind_of(schedule) != "job"
        else schedule["subject_kind"],
        "subjects": len(rows),
        "counts": _counts(rows),
        "enabled": bool(schedule.get("enabled")),
        "priority": int(schedule.get("priority") or 0),
        "owner": schedule.get("owner") or "",
        # A round run by hand counts too: the newest result of its subjects.
        "last_run_at": max(
            [
                str(value)
                for value in [schedule.get("last_run_at"), *(r["at"] for r in rows)]
                if value
            ],
            default=None,
        ),
        "next_run_at": schedule.get("next_run_at") if schedule.get("enabled") else None,
        "interval_minutes": schedule.get("interval_minutes"),
        "cadence": schedule.get("cadence"),
        "when": schedule_when(schedule),
        "path": f"/executions/{quote(schedule['schedule_id'], safe='')}",
        "schedule_path": f"/schedules/{quote(schedule['schedule_id'], safe='')}",
    }


def _manual(rt: Any, scope: Any) -> dict[str, Any]:
    rows = [row for row in job_rows(rt, None, []) if sees_subject(scope, rt, row["id"])]
    for row in rows:
        row["path"] = f"/executions/{MANUAL}/{quote(row['id'], safe='')}"
    return {
        "id": MANUAL,
        "name": t("Manual runs"),
        "kind": MANUAL,
        "algorithm": None,
        "subject_kind": "job",
        "subjects": len(rows),
        "counts": _counts(rows),
        "enabled": True,
        "priority": 0,
        "owner": "",
        "last_run_at": max((row["at"] for row in rows if row["at"]), default=None),
        "next_run_at": None,
        "interval_minutes": None,
        "cadence": None,
        "when": "",
        "path": f"/executions/{MANUAL}",
        "schedule_path": None,
    }


@router.get("")
def groups(scope: Scope, rt: RuntimeDep) -> dict[str, Any]:
    """Every schedule (rounds first, then by name) and the manual runs."""

    algorithms = _algorithms(rt)
    schedules = sorted(
        rt.jobs.list_schedules(),
        key=lambda item: (item.get("kind") != "round", str(item["name"]).lower()),
    )
    return {
        "groups": [_group(rt, item, algorithms, _rows(rt, item, scope)) for item in schedules],
        "manual": _manual(rt, scope),
    }


def _schedule(rt: Any, group_id: str) -> dict[str, Any]:
    schedule = rt.jobs.get_schedule(group_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail=t("Monitor not found."))
    return schedule


@router.get("/{group_id}")
def group(group_id: str, scope: Scope, rt: RuntimeDep) -> dict[str, Any]:
    """One schedule (or the manual runs): its summary and each subject's latest result."""

    if group_id == MANUAL:
        found = _manual(rt, scope)
        return {"group": found, "subjects": _job_rows_for_manual(rt, scope)}
    schedule = _schedule(rt, group_id)
    rows = _rows(rt, schedule, scope)
    return {"group": _group(rt, schedule, _algorithms(rt), rows), "subjects": rows}


def _job_rows_for_manual(rt: Any, scope: Any) -> list[dict[str, Any]]:
    rows = [row for row in job_rows(rt, None, []) if sees_subject(scope, rt, row["id"])]
    for row in rows:
        row["path"] = f"/executions/{MANUAL}/{quote(row['id'], safe='')}"
    return sorted(rows, key=lambda row: str(row["name"]).lower())


def _since(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


def _series_ids(
    kind: str,
    subject: str,
    algorithm_id: str,
    job: dict[str, Any] | None,
    recording: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The Historian series this subject's results are in, as Link writes them.

    An asset schedule writes what it records under its own key (round 8, D6:
    ``<asset>.<schedule key>.<output>``); a series of whole windows goes to the Historian's
    runs, not to these charts."""

    if recording is not None:
        return [
            {
                "id": series_id(subject, f"{recording['key']}.{row['key']}"),
                "name": str(row.get("name") or row["key"]),
                "unit": str(row.get("unit") or ""),
            }
            for row in recording["outputs"]
            if row.get("kind") != SERIES
        ]

    found = []
    if kind == "loop":
        # The health, then every output the algorithm records (round 10: any of them charted).
        found.append(
            {
                "id": series_id(subject, f"{algorithm_id or DEFAULT_ALGORITHM}.{HEALTH_SERIES}"),
                "name": t("Health"),
                "unit": "/100",
            }
        )
        algorithm_id = algorithm_id or DEFAULT_ALGORITHM
    if kind == "signal":
        return [{"id": series_id(subject, "quality"), "name": t("Quality"), "unit": "/100"}]
    for entry in ((job or {}).get("summary") or {}).get("recorded") or []:
        key = entry.get("key") or f"{entry.get('node_id')}.{entry.get('port')}"
        name = str(entry.get("label") or key)
        if "." in str(key):
            name = f"{name} {t(str(entry.get('port_label') or ''))}".strip()
        unit = "/100" if entry.get("type") == "result" else str(entry.get("unit") or "")
        item = {"id": series_id(subject, f"{algorithm_id}.{key}"), "name": name, "unit": unit}
        if item["id"] not in {other["id"] for other in found}:
            found.append(item)
    return found


def _past(
    rt: Any, kind: str, schedule_id: str | None, subject: str, algorithms: dict[str, Any]
) -> list[dict[str, Any]]:
    """The subject's last executions in this schedule, newest first (detail kept for 50)."""

    if kind == "loop":
        rows = rt.latest.history(APPLICATION_ID, SUBJECT_KIND, subject, days=90)[-DETAIL_KEPT:]
        # A loop's round keeps no job: the last ones open from their kept samples.
        kept = rt.jobs.samples.kept(ROUND_SCOPE, subject)
        return [
            {
                "id": key if (key := loop_run_key(subject, row["source_end"])) in kept else None,
                "at": row["source_end"],
                "state": SUITE_STATUS.get(row["status"], "unknown")
                if row["health"] is not None
                else "unknown",
                "status_label": t(LOOP_WORDS.get(row["status"], "No health")),
                "value": row["health"],
                "path": None,
            }
            for row in reversed(rows)
        ]
    if kind == "signal":
        rows = rt.quality_results.history(subject, days=90)[-DETAIL_KEPT:]
        return [
            {
                "at": row["checked_at"],
                "state": SIGNAL_STATUS.get(row["status"], "unknown"),
                "status_label": t(SIGNAL_WORDS.get(row["status"], "Not checked")),
                "value": row["quality"],
                "path": None,
            }
            for row in reversed(rows)
        ]
    schedules, tries = schedule_names(rt)
    kept = rt.jobs.samples.kept(schedule_id or "", subject)
    names = {key: value["name"] for key, value in algorithms.items()}
    jobs = [
        job
        for job in rt.jobs.list_jobs(
            schedule_id=schedule_id,
            kinds={"manual"} if schedule_id is None else None,
            loop_id=subject,
            limit=DETAIL_KEPT,
        )
        if schedule_id is not None or not job["schedule_id"]
    ]
    found = []
    for job in jobs:
        state, word, value = job_state(job)
        row = execution_row(job, schedules, names, tries)
        found.append(
            {
                **row,
                "at": job.get("completed_at") or job.get("started_at") or job["requested_at"],
                "state": state if job["status"] in {"completed", "failed"} else row["state"],
                "status_label": t(word),
                "value": value,
                "version": ((job.get("summary") or {}).get("algorithm_version")),
                "sampled": job["job_id"] in kept,
            }
        )
    return found


def _output(name: str, key: str, status: str, value: Any, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "key": key,
        "kind": "result",
        "status": status,
        "state": ASSET_STATE.get(status, "unknown"),
        "status_label": t(ASSET_WORDS.get(status, "No verdict")),
        "value": value,
        "message": message,
    }


def _outputs(rt: Any, kind: str, subject: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Each output of the latest result on its own (round 9, D11): what the algorithm's
    outputs said, a loop's methods or a signal's checks, not only the score that sums them."""

    if kind == "loop":
        row = rt.latest.get(APPLICATION_ID, SUBJECT_KIND, subject) or {}
        summary = row.get("summary") or {}
    if kind == "signal":
        latest = rt.quality_results.latest(subject) or {}
        return [
            _output(
                str(check.get("name") or check.get("check")),
                str(check.get("check") or ""),
                CHECK_STATUS.get(str(check.get("status")), "unknown"),
                None,
                str(check.get("message") or ""),
            )
            for check in latest.get("checks") or []
            if isinstance(check, dict)
        ]
    found = [
        {
            **item,
            "state": ASSET_STATE.get(str(item.get("status")), "unknown"),
            "status_label": t(ASSET_WORDS.get(str(item.get("status")), ""))
            if item.get("kind") == "result"
            else "",
        }
        for item in summary.get("outputs") or []
        if isinstance(item, dict)
    ]
    if found or kind != "loop":
        return found
    # A loop's default algorithm: one verdict per method (``summary.blocks``).
    return [
        _output(
            str(block.get("label") or key),
            str(key),
            str(block.get("status") or ""),
            block.get("value"),
            str(block.get("message") or ""),
        )
        for key, block in (summary.get("blocks") or {}).items()
        if isinstance(block, dict)
    ]


@router.get("/{group_id}/{subject:path}")
def subject_history(
    group_id: str,
    subject: str,
    user: CurrentUser,
    rt: RuntimeDep,
    scope: Scope,
    days: Annotated[float, Query(gt=0, le=400)] = 7,
    run: Annotated[str | None, Query(max_length=120)] = None,
) -> dict[str, Any]:
    """One subject in one schedule: the latest result, its outputs over time, past executions.
    ``run`` (one of its runs) answers that run as ``run`` (none when retention deleted it)."""

    algorithms = _algorithms(rt)
    if group_id == MANUAL:
        found = _manual(rt, scope)
        kind, schedule_id = "job", None
        rows = [row for row in _job_rows_for_manual(rt, scope) if row["id"] == subject]
    else:
        schedule = _schedule(rt, group_id)
        found = _group(rt, schedule, algorithms, [])
        kind, schedule_id = kind_of(schedule), group_id
        rows = [row for row in _rows(rt, schedule, scope) if row["id"] == subject]
        found["subjects"] = len(subjects_of(rt, schedule))
    if not rows:
        raise HTTPException(status_code=404, detail=t("Not in this monitor."))
    latest_job = None
    recording = None
    algorithm_id = (found.get("algorithm") or {}).get("id") or ""
    if kind == "job":
        latest_job = latest_jobs(rt, schedule_id, [subject]).get(subject)
        algorithm_id = algorithm_id or str((latest_job or {}).get("profile_id") or "")
    elif kind == "loop":
        loop = rt.loops.get_loop(subject)
        algorithm_id = str((loop.profile_id if loop else "") or DEFAULT_ALGORITHM)
    summary = (latest_job or {}).get("summary") or {}
    if kind == "job" and schedule_id is not None:
        profile = rt.presets.get_profile(algorithm_id) if algorithm_id else None
        recording = rt.recording(schedule, profile or {})
    algorithm = algorithms.get(algorithm_id) or (
        {"id": algorithm_id, "name": algorithm_id, "version": None} if algorithm_id else None
    )
    return {
        "group": found,
        "subject": rows[0],
        "algorithm": algorithm,
        "last_run": _last_run(rt, kind, subject, latest_job),
        "run": _asked_run(rt, kind, schedule_id, subject, run) if run else None,
        "outputs": _outputs(rt, kind, subject, summary),
        "execution_id": (latest_job or {}).get("job_id"),
        "subject_path": _subject_path(kind, subject),
        "series": _series_ids(
            kind,
            subject,
            algorithm_id,
            latest_job if kind != "loop" else {"summary": _loop_summary(rt, subject)},
            recording,
        ),
        "versions": (
            f"app-linkcraft:{VERSION_PREFIX}.{algorithm_id}.{VERSION_SERIES}"
            if algorithm_id
            else None
        ),
        "executions": _past(rt, kind, schedule_id, subject, algorithms),
        "detail_kept": DETAIL_KEPT,
        "samples_kept": SAMPLES_KEPT,
        "since": _since(days),
    }


def _last_run(
    rt: Any, kind: str, subject: str, job: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The subject's last run as its page draws it (owner D23, 2026-10-26): what each block
    said and what each wire carried (``summary.wires``), its outputs and what it read."""

    if kind == "job" and job:
        summary = job.get("summary") or {}
        at = job.get("completed_at") or job.get("started_at") or job.get("requested_at")
        run_id = job.get("job_id")
        on = str(job.get("subject_kind") or "loop")
        span = {"start": job.get("source_start"), "end": job.get("source_end")}
    elif kind == "loop":
        row = rt.latest.get(APPLICATION_ID, SUBJECT_KIND, subject) or {}
        summary = row.get("summary") or {}
        at = row.get("source_end")
        run_id = loop_run_key(subject, at) if at else None
        on = "loop"
        span = {"start": row.get("source_start"), "end": row.get("source_end")}
    else:
        return None
    if not summary:
        return None
    # The wires' samples when this run is one of the last (``engine.samples``), else their
    # last values only.
    kept = rt.jobs.samples.get(run_id) if run_id else None
    return {
        "id": run_id,
        "at": at,
        "on": on,
        "version": summary.get("algorithm_version"),
        "blocks": summary.get("blocks") or {},
        "wires": (kept or {}).get("wires") or summary.get("wires") or {},
        "sampled": bool(kept),
        # The window it read, to run again with every sample (an asset run keeps its own).
        "window": summary.get("window") or (span if span["start"] and span["end"] else None),
        "signals": summary.get("signals") or {},
        "outputs": summary.get("outputs") or [],
    }


def _asked_run(
    rt: Any, kind: str, schedule_id: str | None, subject: str, run_id: str
) -> dict[str, Any] | None:
    """One past run of this subject in this schedule, drawn as the last run is; none when it
    is not one of them or retention deleted it (``prune_jobs``). A loop's round is kept only
    with its samples, for its last runs (``engine.samples``)."""

    if kind == "loop":
        if not run_id.startswith(f"{subject}@"):
            return None
        detail = rt.jobs.samples.get(run_id)
        if not detail:
            return None
        return {
            "id": run_id,
            "at": run_id.removeprefix(f"{subject}@"),
            "on": "loop",
            "version": detail.get("version"),
            "blocks": detail.get("blocks") or {},
            "wires": detail.get("wires") or {},
            "sampled": True,
            "window": detail.get("window"),
            "signals": detail.get("signals") or {},
            "outputs": detail.get("outputs") or [],
        }
    job = rt.jobs.get_job(run_id)
    if not job or job.get("loop_id") != subject or job.get("schedule_id") != schedule_id:
        return None
    return _last_run(rt, "job", subject, job)


def _loop_summary(rt: Any, subject: str) -> dict[str, Any]:
    return (rt.latest.get(APPLICATION_ID, SUBJECT_KIND, subject) or {}).get("summary") or {}


def _subject_path(kind: str, subject: str) -> str:
    if kind == "signal":
        return f"/signals/{quote(subject, safe='')}"
    if kind == "loop":
        return f"/loops/{quote(subject, safe='')}"
    return f"/assets/{quote(subject, safe='')}"


__all__ = ["DETAIL_KEPT", "MANUAL", "router"]
