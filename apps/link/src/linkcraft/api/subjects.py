"""What each schedule concluded about each of its subjects: the state and the word beside it.

Read by Executions (``api.routers.groups``) and by the events Link publishes when a subject's
state changes (``api.events``). Three kinds of schedules: the monitoring round (each loop's
health), Signal quality (each signal's verdict) and the schedules of an algorithm (the latest
execution of each subject).
"""

from __future__ import annotations

from typing import Any

from linkcraft.i18n import t
from linkcraft.loops.monitor import APPLICATION_ID
from linkcraft.loops.suite import SUITE_STATUS
from linkcraft.signals.publish import STATUS as SIGNAL_STATUS

ROUND_ID = f"round-{APPLICATION_ID}"
# The Signal quality algorithm: a system algorithm with its own round schedule.
SIGNAL_APPLICATION_ID = "signal_quality"
SIGNAL_ROUND_ID = f"round-{SIGNAL_APPLICATION_ID}"
# Each kind of verdict -> (the suite's state, the word people read).
LOOP_WORDS = {"normal": "Normal", "medium": "Medium", "high": "High", "critical": "Critical"}
ASSET_STATE = {"ok": "ok", "warning": "warning", "bad": "alarm", "alarm": "alarm"}
ASSET_WORDS = {"ok": "OK", "warning": "Warning", "bad": "Critical", "alarm": "Critical"}
SIGNAL_WORDS = {"good": "Good", "suspect": "Suspect", "bad": "Bad"}


def subjects_of(rt: Any, schedule: dict[str, Any]) -> list[str]:
    if schedule["schedule_id"] == SIGNAL_ROUND_ID:
        return [item["id"] for item in rt.signal_store.list() if item["enabled"]]
    if schedule.get("selector") is None:
        return [schedule["loop_id"]]
    return rt.schedule_subjects(schedule)


def subject_row(
    subject: str, name: str, state: str, word: str, *, measure: Any = None, at: Any = None
) -> dict[str, Any]:
    return {
        "id": subject,
        "name": name,
        "state": state,
        "status_label": t(word) if word else "",
        "measure": measure,
        "finding": "",
        "at": at,
    }


def loop_rows(rt: Any, subjects: list[str]) -> list[dict[str, Any]]:
    """A round's loops: each one's latest health (the round is the only writer)."""

    rows = {row["loop_id"]: row for row in rt.monitor.overview_rows()}
    found = []
    for loop_id in subjects:
        row = rows.get(loop_id)
        if row is None:
            continue
        health = row["health"]
        state = SUITE_STATUS.get(row["status"], "unknown") if health is not None else "unknown"
        item = subject_row(
            loop_id,
            row["name"] or loop_id,
            state,
            LOOP_WORDS.get(row["status"], "") if health is not None else "No health",
            measure={"label": t("Health"), "value": health, "format": "percent"},
            at=row["analyzed_at"],
        )
        limiting = row["limiting"] or {}
        item["finding"] = limiting.get("finding") or row["state_reason"] or ""
        found.append(item)
    return found


def signal_rows(rt: Any, subjects: list[str]) -> list[dict[str, Any]]:
    latest = rt.quality_results.summaries()
    signals = {item["id"]: item for item in rt.signal_store.list()}
    found = []
    for signal_id in subjects:
        signal = signals.get(signal_id)
        if signal is None or signal["missing"]:
            continue
        verdict = latest.get(signal_id) or {}
        status = verdict.get("status") or "unknown"
        item = subject_row(
            signal_id,
            signal_id.split(":", 1)[-1],
            SIGNAL_STATUS.get(status, "unknown"),
            SIGNAL_WORDS.get(status, "Not checked"),
            measure={"label": t("Quality"), "value": verdict.get("quality"), "format": "score"},
            at=verdict.get("checked_at"),
        )
        item["finding"] = verdict.get("message") or ""
        found.append(item)
    return found


def job_state(job: dict[str, Any] | None) -> tuple[str, str, Any]:
    """An algorithm run's verdict: (state, word, its value)."""

    if job is None:
        return "unknown", "Not run yet", None
    if job["status"] == "failed":
        return "unknown", "Did not run", None
    if job["status"] != "completed":
        return "pending", job["status"].capitalize(), None
    summary = job.get("summary") or {}
    verdict = summary.get("verdict") or worst(summary.get("outputs") or [])
    status = str(verdict.get("status") or "")
    if not status and summary.get("health") is not None:  # a loop's health
        status = {"normal": "ok", "medium": "warning"}.get(summary.get("status"), "bad")
        verdict = {"value": summary.get("health")}
    return (
        ASSET_STATE.get(status, "unknown"),
        ASSET_WORDS.get(status, "No verdict"),
        verdict.get("value"),
    )


def worst(outputs: list[Any]) -> dict[str, Any]:
    """An algorithm on loops: its verdict is the worst of its result outputs."""

    order = {"bad": 0, "warning": 1, "ok": 2}
    results = [
        item
        for item in outputs
        if isinstance(item, dict) and item.get("kind") == "result" and item.get("status") in order
    ]
    return min(results, key=lambda item: order[item["status"]], default={})


def latest_jobs(
    rt: Any, schedule_id: str | None, subjects: list[str] | None = None
) -> dict[str, dict[str, Any]]:
    """Each subject's latest ended execution in a schedule (``None``: run by a person)."""

    return rt.jobs.latest_finished(schedule_id, subjects)


def job_rows(rt: Any, schedule_id: str | None, subjects: list[str]) -> list[dict[str, Any]]:
    latest = latest_jobs(rt, schedule_id, subjects or None)
    names = {row["asset_id"]: row.get("asset_name") for row in rt.asset_runs.list()}
    found = []
    for subject in subjects or sorted(latest):
        job = latest.get(subject)
        state, word, value = job_state(job)
        item = subject_row(
            subject,
            names.get(subject) or subject,
            state,
            word,
            measure={"label": t("Score"), "value": value, "format": "score"},
            at=(job or {}).get("completed_at"),
        )
        summary = (job or {}).get("summary") or {}
        item["finding"] = (job or {}).get("error_message") or str(
            (summary.get("verdict") or {}).get("message") or ""
        )
        found.append(item)
    return found


def kind_of(schedule: dict[str, Any]) -> str:
    if schedule["schedule_id"] == SIGNAL_ROUND_ID:
        return "signal"
    if schedule["schedule_id"] == ROUND_ID:
        return "loop"
    return "job"


def subject_rows(
    rt: Any, schedule: dict[str, Any], only: list[str] | None = None
) -> list[dict[str, Any]]:
    """Each subject of a schedule (or only these) with its latest state, by name."""

    subjects = subjects_of(rt, schedule)
    if only is not None:
        subjects = [subject for subject in subjects if subject in set(only)]
    kind = kind_of(schedule)
    if kind == "signal":
        rows = signal_rows(rt, subjects)
    elif kind == "loop":
        rows = loop_rows(rt, subjects)
    else:
        rows = job_rows(rt, schedule["schedule_id"], subjects)
    return sorted(rows, key=lambda item: str(item["name"]).lower())
