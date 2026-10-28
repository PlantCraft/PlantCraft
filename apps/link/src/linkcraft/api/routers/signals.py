"""Signals: the list with their latest quality verdicts, one signal's page, its settings."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from linkcraft.api.deps import CurrentUser, EditorUser, RuntimeDep
from linkcraft.api.runtime import SIGNAL_ROUND_ID
from linkcraft.api.scope import Scope
from linkcraft.catalog.signal_checks import CHECKS, effective_limits, validate_parameters
from linkcraft.data.samples import iso_utc, naive_utc, thin
from linkcraft.i18n import t
from linkcraft.signals.assess import is_sampled
from linkcraft.signals.models import SETTING_KEYS

router = APIRouter(prefix="/api")
PLOT_POINTS = 4000
ORDER = {"bad": 0, "suspect": 1, "unknown": 2, "good": 3}


def _row(signal: dict[str, Any], latest: dict[str, Any] | None) -> dict[str, Any]:
    latest = latest or {}
    low, high = effective_limits(signal)
    return {
        "id": signal["id"],
        "name": signal["name"],
        "unit": signal["unit"],
        "source": signal["source"],
        "kind": signal["kind"],
        "source_kind": signal.get("source_kind") or "",
        # Laboratory or manual samples, judged by their own rules (``assess.plan``).
        "sampled": is_sampled(signal),
        "description": signal["description"],
        "roles": signal["roles"],
        "assets": signal["assets"],
        "low": low,
        "high": high,
        "enabled": signal["enabled"],
        "missing": signal["missing"],
        "status": latest.get("status") if signal["enabled"] else "off",
        "quality": latest.get("quality"),
        "apt": latest.get("apt"),
        "limiting": latest.get("limiting"),
        "message": latest.get("message") or "",
        "checked_at": latest.get("checked_at"),
        "flagged": latest.get("flagged") or [],
    }


def _signal_or_404(rt, signal_id: str, scope: Any) -> dict[str, Any]:
    signal = rt.signal_store.get(signal_id)
    if signal is None or not scope.signal(signal_id):
        raise HTTPException(404, t("Signal {signal} not found.", signal=signal_id))
    return signal


@router.get("/signals")
def list_signals(
    rt: RuntimeDep,
    scope: Scope,
    q: str = "",
    status: str = "",
    source: str = "",
    check: str = "",
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    latest = rt.quality_results.summaries()
    rows = [
        _row(signal, latest.get(signal["id"]))
        for signal in rt.signal_store.list()
        if scope.signal(signal["id"])
    ]
    query = q.strip().lower()
    wanted = {item for item in status.split(",") if item}
    if query:
        rows = [
            row
            for row in rows
            if query
            in f"{row['id']} {row['name']} {row['description']} {' '.join(row['assets'])}".lower()
        ]
    if wanted:
        rows = [row for row in rows if (row["status"] or "unchecked") in wanted]
    if source:
        wanted_source = "" if source == "-" else source
        rows = [row for row in rows if row["source"] == wanted_source]
    if check:
        rows = [row for row in rows if check in row["flagged"] or row["limiting"] == check]
    rows.sort(key=lambda row: (ORDER.get(row["status"] or "", 4), row["quality"] or 0, row["id"]))
    return {"total": len(rows), "items": rows[offset : offset + limit]}


def signal_overview(rt: Any, scope: Any) -> dict[str, Any]:
    """The signals part of the Overview: counts, what is wrong, worst signals, by source."""

    latest = rt.quality_results.summaries()
    signals = [
        signal
        for signal in rt.signal_store.list()
        if signal["enabled"] and not signal["missing"] and scope.signal(signal["id"])
    ]
    counts = {"good": 0, "suspect": 0, "bad": 0, "unknown": 0, "unchecked": 0}
    by_check: dict[str, dict[str, int]] = {}
    by_source: dict[str, dict[str, int]] = {}
    qualities = []
    for signal in signals:
        verdict = latest.get(signal["id"])
        status = verdict["status"] if verdict else "unchecked"
        counts[status] = counts.get(status, 0) + 1
        source = by_source.setdefault(signal["source"] or "-", {"total": 0, "bad": 0, "suspect": 0})
        source["total"] += 1
        if status in ("bad", "suspect"):
            source[status] += 1
            limiting = verdict.get("limiting") or ""
            entry = by_check.setdefault(limiting, {"bad": 0, "suspect": 0})
            entry[status] += 1
        if verdict and verdict.get("quality") is not None:
            qualities.append(float(verdict["quality"]))
    worst = sorted(
        (_row(signal, latest.get(signal["id"])) for signal in signals if signal["id"] in latest),
        key=lambda row: (ORDER.get(row["status"], 4), row["quality"] or 0),
    )[:10]
    names = {check_id: t(block.metadata.name) for check_id, block in CHECKS.items()}
    return {
        "signals": len(signals),
        "counts": counts,
        "apt_share": (counts["good"] + counts["suspect"]) / len(signals) if signals else None,
        "mean_quality": round(sum(qualities) / len(qualities), 1) if qualities else None,
        "by_check": [
            {"check": key, "name": names.get(key, key), **value}
            for key, value in sorted(by_check.items(), key=lambda item: -sum(item[1].values()))
        ],
        "by_source": [{"source": key, **value} for key, value in sorted(by_source.items())],
        "worst": [row for row in worst if row["status"] in ("bad", "suspect")],
        "last_run": next(iter(rt.quality_results.rounds(1)), None),
        "running": rt.round_state(SIGNAL_ROUND_ID, rt.quality_engine)[0],
    }


@router.get("/signals/{signal_id:path}/data")
def signal_data(
    signal_id: str,
    rt: RuntimeDep,
    scope: Scope,
    user: CurrentUser,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """The samples of the signal's last checked window (or ``[start, end]``) for the chart."""

    signal = _signal_or_404(rt, signal_id, scope)
    latest = rt.quality_results.latest(signal_id) or {}
    try:
        end_at = naive_utc(end or latest.get("window_end") or pd.Timestamp.now(tz="UTC"))
        start_at = naive_utc(
            start or latest.get("window_start") or (end_at - pd.Timedelta(hours=24))
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, t("Times must be ISO 8601.")) from exc
    if start_at >= end_at:
        raise HTTPException(422, t("The start must be before the end."))
    reference = str((signal.get("settings") or {}).get("reference") or "")
    wanted = [signal_id] + ([reference] if reference else [])
    step = max(1.0, (end_at - start_at).total_seconds() / 20000)
    samples = rt.user_signal_reader(user).read(wanted, start_at, end_at, fallback_step=step)
    if signal_id in samples.failed:
        raise HTTPException(502, samples.failed[signal_id])

    def points(values: pd.Series | None) -> dict[str, list[Any]]:
        if values is None or values.empty:
            return {"t": [], "v": []}
        values = thin(values, PLOT_POINTS)
        return {
            "t": [stamp.tz_localize("UTC").isoformat() for stamp in values.index],
            "v": [None if pd.isna(item) else item for item in values.tolist()],
        }

    return {
        "signal": signal_id,
        "start": iso_utc(start_at),
        "end": iso_utc(end_at),
        "resampled": signal_id in samples.resampled,
        "series": points(samples.series.get(signal_id)),
        "reference": points(samples.series.get(reference)) if reference else None,
    }


@router.get("/signals/{signal_id:path}/history")
def signal_history(
    signal_id: str,
    rt: RuntimeDep,
    scope: Scope,
    _user: CurrentUser,
    days: float = Query(30, gt=0, le=90),
) -> list[dict[str, Any]]:
    _signal_or_404(rt, signal_id, scope)
    return rt.quality_results.history(signal_id, days)


class CheckRequest(BaseModel):
    start: str | None = None
    end: str | None = None


@router.post("/signals/{signal_id:path}/check")
def check_signal(
    signal_id: str, rt: RuntimeDep, scope: Scope, user: EditorUser, body: CheckRequest | None = None
) -> dict[str, Any]:
    """Check one signal now, with the person's token. The algorithm's window is kept as its verdict."""

    signal = _signal_or_404(rt, signal_id, scope)
    body = body or CheckRequest()
    plant = rt.user_signal_reader(user)
    settings = rt.quality_settings.get()
    custom = bool(body.start or body.end)
    try:
        if custom:
            end_at = naive_utc(body.end) if body.end else naive_utc(pd.Timestamp.now(tz="UTC"))
            start_at = (
                naive_utc(body.start)
                if body.start
                else end_at - pd.Timedelta(hours=settings.window_hours)
            )
        else:
            start_at, end_at = rt.quality_engine.window(plant, [signal_id], settings)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, t("Times must be ISO 8601.")) from exc
    if start_at >= end_at:
        raise HTTPException(422, t("The start must be before the end."))
    verdict = rt.quality_engine.check(plant, [signal], start_at, end_at, settings)[0]
    if not custom:
        rt.quality_results.save([verdict])
        rt.quality_engine.publish_results([verdict], settings)
    return {**verdict, "saved": not custom}


@router.get("/signals/{signal_id:path}")
def get_signal(signal_id: str, rt: RuntimeDep, scope: Scope) -> dict[str, Any]:
    signal = _signal_or_404(rt, signal_id, scope)
    latest = rt.quality_results.latest(signal_id)
    return {
        **_row(signal, latest),
        "settings": signal["settings"],
        "processcraft_limits": {"low": signal["low"], "high": signal["high"]},
        "verdict": latest,
    }


class SignalSettings(BaseModel):
    enabled: bool | None = None
    low: float | None = None
    high: float | None = None
    reference: str | None = Field(default=None, max_length=300)
    checks_off: list[str] | None = None
    checks_on: list[str] | None = None
    parameters: dict[str, dict[str, Any]] | None = None
    # "lab": sampled (laboratory analyses, manual entries), judged by its own rules;
    # "continuous": a process signal. Cleared, a CSV source's signal is sampled.
    sampling: Literal["lab", "continuous"] | None = None
    # A sampled signal's expected interval between samples; cleared, read from its samples.
    sample_interval_minutes: float | None = Field(default=None, gt=0, le=31 * 24 * 60)
    # Which fields to clear (back to PlantCraft's limits, no reference, defaults...).
    clear: list[str] = Field(default_factory=list)


@router.patch("/signals/{signal_id:path}")
def update_signal(
    signal_id: str, body: SignalSettings, rt: RuntimeDep, scope: Scope, user: EditorUser
) -> dict[str, Any]:
    signal = _signal_or_404(rt, signal_id, scope)
    given = body.model_dump(exclude_unset=True)
    changes: dict[str, Any] = {}
    for key in SETTING_KEYS:
        if key in given and given[key] is not None:
            changes[key] = given[key]
    for key in body.clear:
        changes[key] = None
    for key in ("checks_off", "checks_on"):
        unknown = [item for item in changes.get(key) or [] if item not in CHECKS]
        if unknown:
            raise HTTPException(422, t("Unknown checks: {names}.", names=", ".join(unknown)))
    for check_id, values in (changes.get("parameters") or {}).items():
        if check_id not in CHECKS:
            raise HTTPException(422, t("Unknown checks: {names}.", names=check_id))
        try:
            validate_parameters(check_id, values)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    low = changes.get("low", (signal["settings"] or {}).get("low", signal["low"]))
    high = changes.get("high", (signal["settings"] or {}).get("high", signal["high"]))
    if low is not None and high is not None and high <= low:
        raise HTTPException(422, t("The high limit must be above the low limit."))
    reference = changes.get("reference")
    if reference:
        if reference == signal_id:
            raise HTTPException(422, t("A signal cannot be its own reference."))
        if rt.signal_store.get(reference) is None:
            raise HTTPException(422, t("Signal {signal} not found.", signal=reference))
    updated = rt.signal_store.update(signal_id, enabled=body.enabled, settings=changes)
    rt.audit(
        user,
        "signal.update",
        signal_id,
        {"enabled": body.enabled, **{key: value for key, value in changes.items()}},
    )
    return get_signal(signal_id, rt, scope) if updated else {}


@router.post("/signals/sync")
def sync_signals(rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Read the signal list from PlantCraft now, with the person's token."""

    result = rt.quality_engine.sync(rt.user_signal_reader(user))
    rt.audit(user, "signals.sync", "signals", result)
    return result
