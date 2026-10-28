"""What the Signal quality algorithm publishes in PlantCraft (app standard, section 6).

- **Results** of kind ``signal_quality`` (read by others as ``linkcraft.signal_quality``): one
  per checked signal (``signal:<id>``) and one per asset that has signals (``asset:<id>``, the
  worst of its signals: the aggregate is LinkCraft's job, consumers never recompute it).
  good/suspect/bad map to ok/warning/alarm (D5), quality to ``score``, apt to ``usable``;
  ``expires_at`` is two run intervals later, so a LinkCraft that stopped never leaves a green
  light behind.
- **Derived series**: one point per judged signal and run in ``app-linkcraft:<signal id>.quality``
  (number, ``/100``), subject the signal, result ``signal_quality``.
- **Runs**: each execution of the algorithm, while it runs and when it ends. Its schedule is one
  of LinkCraft's schedules (``round-signal_quality``), published with the others.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.derived import SCORE_UNIT, source_of
from plantcraft_sdk.refs import RefError, asset_ref, signal_ref

from linkcraft.data.suite import SuiteClient, summary_text
from linkcraft.i18n import t

APP_ID = "linkcraft"
KIND = "signal_quality"
SERIES_SUFFIX = ".quality"
STATUS = {"good": "ok", "suspect": "warning", "bad": "alarm", "unknown": "unknown"}
RANK = {"ok": 0, "unknown": 1, "warning": 2, "alarm": 3}
RUN_STATUS = {"running": "running", "ok": "done", "error": "failed", "interrupted": "failed"}
RUN_TRIGGER = {"schedule": "schedule", "manual": "manual"}
ISSUE_LIMIT = 8
# Subjects one run lists (API v1 refuses a run with more than 500).
MAX_RUN_SUBJECTS = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def expires(at: datetime, interval_minutes: float) -> str:
    """About two run intervals after ``at`` (at least an hour)."""

    return _iso(at + timedelta(minutes=max(60.0, 2 * float(interval_minutes))))


def signal_result(verdict: dict[str, Any], expires_at: str) -> dict[str, Any]:
    issues = [
        {
            "check": check.get("check"),
            "status": check.get("status"),
            "score": check.get("score"),
            "message": check.get("message") or "",
        }
        for check in verdict.get("checks") or []
        if check.get("status") in ("warning", "bad")
    ]
    status = STATUS.get(str(verdict.get("status")), "unknown")
    return {
        "subject": signal_ref(str(verdict["signal"])),
        "kind": KIND,
        "status": status,
        "score": verdict.get("quality"),
        "usable": None if status == "unknown" else bool(verdict.get("apt")),
        "value": None,
        "summary": summary_text(verdict.get("message")),
        "detail": {
            "verdict": verdict.get("status"),
            "limiting": verdict.get("limiting"),
            "issues": issues[:ISSUE_LIMIT],
            "window_start": verdict.get("window_start"),
            "window_end": verdict.get("window_end"),
            "samples": verdict.get("samples"),
        },
        "at": verdict.get("checked_at") or _iso(_now()),
        "expires_at": expires_at,
    }


def asset_result(
    asset: dict[str, Any], latest: dict[str, dict[str, Any]], expires_at: str
) -> dict[str, Any] | None:
    """The worst of the asset's signals, or None when the asset has no signal LinkCraft checked."""

    members = []
    for role, signal_id in sorted((asset.get("signals") or {}).items()):
        verdict = latest.get(str(signal_id)) if signal_id else None
        if verdict is None:
            continue
        members.append(
            {
                "role": str(role),
                "signal": str(signal_id),
                "status": STATUS.get(str(verdict.get("status")), "unknown"),
                "score": verdict.get("quality"),
                "usable": bool(verdict.get("apt")),
                "message": str(verdict.get("message") or ""),
                "at": verdict.get("checked_at"),
            }
        )
    if not members:
        return None
    worst = max(members, key=lambda item: (RANK[item["status"]], -(item["score"] or 0)))
    scores = [item["score"] for item in members if item["score"] is not None]
    if any(item["status"] == "alarm" for item in members):
        usable: bool | None = False
    elif any(item["status"] == "unknown" for item in members):
        usable = None
    else:
        usable = True
    if worst["status"] == "ok":
        summary = t("All {count} signals usable.", count=len(members))
    else:
        summary = t(
            "{role} ({signal}): {message}",
            role=worst["role"].upper(),
            signal=worst["signal"],
            message=worst["message"],
        )
    return {
        "subject": asset_ref(str(asset["id"])),
        "kind": KIND,
        "status": worst["status"],
        "score": min(scores) if scores else None,
        "usable": usable,
        "value": None,
        "summary": summary_text(summary),
        "detail": {
            "signals": [
                {key: item[key] for key in ("role", "signal", "status", "score", "usable")}
                for item in members
            ]
        },
        "at": max(str(item["at"] or "") for item in members) or _iso(_now()),
        "expires_at": expires_at,
    }


def asset_results(
    assets: Iterable[dict[str, Any]], latest: dict[str, dict[str, Any]], expires_at: str
) -> list[dict[str, Any]]:
    rows = []
    for asset in assets:
        if not asset.get("id"):
            continue
        try:
            row = asset_result(asset, latest, expires_at)
        except RefError:
            continue
        if row is not None:
            rows.append(row)
    return rows


def signal_results(verdicts: Iterable[dict[str, Any]], expires_at: str) -> list[dict[str, Any]]:
    rows = []
    for verdict in verdicts:
        try:
            rows.append(signal_result(verdict, expires_at))
        except RefError:  # an id no reference can carry (never from PlantCraft's catalog)
            continue
    return rows


def run_id(round_id: int) -> str:
    return f"signal-quality-{round_id}"


def run_row(round_row: dict[str, Any], root_path: str) -> dict[str, Any]:
    counts = round_row.get("counts") or {}
    if round_row.get("status") == "error":
        summary = str(round_row.get("error") or t("The run failed."))
    elif round_row.get("status") == "running":
        summary = t("Checking the signals.")
    else:
        summary = t(
            "{signals} signals: {good} good, {suspect} suspect, {bad} bad, {unknown} unknown.",
            signals=round_row.get("signals") or 0,
            **{key: counts.get(key, 0) for key in ("good", "suspect", "bad", "unknown")},
        )
    return {
        "id": run_id(int(round_row["id"])),
        "name": t("Signal quality"),
        "status": RUN_STATUS.get(str(round_row.get("status")), "failed"),
        "trigger": RUN_TRIGGER.get(str(round_row.get("trigger")), "api"),
        "started_at": round_row.get("started_at"),
        "finished_at": round_row.get("finished_at"),
        "subjects": [],
        "summary": summary_text(summary),
        "url": f"{root_path.rstrip('/')}/runs/signal-quality-{round_row['id']}",
    }


def quality_series_id(signal_id: str) -> str:
    return f"{source_of(APP_ID)}:{signal_id}{SERIES_SUFFIX}"


def quality_points(verdicts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One point per judged signal: its quality (0-100) at the end of the window it judged."""

    points = []
    for verdict in verdicts:
        quality = verdict.get("quality")
        at = verdict.get("window_end") or verdict.get("checked_at")
        if quality is None or not at:
            continue  # unknown: no value, rather than a misleading 0
        try:
            subject = signal_ref(str(verdict["signal"]))
        except RefError:
            continue
        points.append(
            {
                "signal": quality_series_id(str(verdict["signal"])),
                "subject": subject,
                "result": KIND,
                "t": [at],
                "v": [float(quality)],
                "unit": SCORE_UNIT,
                "kind": "number",
                "name": t("Data quality of {signal}", signal=verdict["signal"])[:120],
            }
        )
    return points


class QualityPublisher:
    """Publishes through LinkCraft's ``SuiteClient``; failures are logged there, never raised."""

    def __init__(self, suite: SuiteClient | None, root_path: str):
        self.suite = suite
        self.root_path = root_path
        self.published: dict[str, Any] = {}

    def results(
        self,
        verdicts: list[dict[str, Any]],
        assets: list[dict[str, Any]],
        latest: dict[str, dict[str, Any]],
        interval_minutes: float,
    ) -> int:
        """Results of these verdicts and of the assets that hold their signals."""

        if self.suite is None:
            return 0
        until = expires(_now(), interval_minutes)
        rows = signal_results(verdicts, until)
        checked = {str(verdict["signal"]) for verdict in verdicts}
        touched = [
            asset
            for asset in assets
            if checked & {str(item) for item in (asset.get("signals") or {}).values() if item}
        ]
        rows += asset_results(touched, latest, until)
        sent = len(rows) if rows and self.suite.put_results(rows) else 0
        self.published["results"] = {"rows": len(rows), "sent": sent, "at": _iso(_now())}
        points = quality_points(verdicts)
        if points:
            self.published["series"] = {
                "points": len(points),
                "sent": self.suite.put_series(points),
                "at": _iso(_now()),
            }
        return sent

    def run(self, round_row: dict[str, Any]) -> bool:
        if self.suite is None:
            return False
        return self.suite.put_runs([run_row(round_row, self.root_path)])
