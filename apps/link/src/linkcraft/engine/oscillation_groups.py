"""Loops that oscillate with the same period, grouped to find where the oscillation starts (A11).

A plant-wide oscillation shows in many loops at one period: it starts in one place (a sticky
valve, a badly tuned loop, an outside disturbance) and travels through the process. Grouping
the oscillating loops by period (Thornhill, Huang and Zhang 2003; Thornhill and Horch 2007)
turns a list of alarms into a few disturbances, each with a short list of where to look first.

Two loops are in one group when their periods are within ``tolerance`` of each other (the
group grows from the shortest period). In a group, a loop is a likelier origin when its valve
shows stiction (a non-linearity makes the regular, non-sinusoidal limit cycle that then spreads),
then the more regular its cycle and the higher its autocorrelation peak: the cycle is cleanest
near its source and blurs as it travels.
"""

from __future__ import annotations

from typing import Any

OSCILLATION = "oscillation_autocorrelation"
STICTION = "stiction_screening"
FLAGGED = {"warning", "bad"}


def _result(results: list[dict[str, Any]], method_id: str) -> dict[str, Any] | None:
    return next((item for item in results if item.get("method_id") == method_id), None)


def _period(metrics: dict[str, Any]) -> float | None:
    for key in ("zero_crossing_period_seconds", "dominant_period_seconds"):
        value = metrics.get(key)
        if isinstance(value, int | float) and value > 0:
            return float(value)
    return None


def oscillating_loops(
    results: dict[str, list[dict[str, Any]]], loops: dict[str, Any]
) -> list[dict[str, Any]]:
    """Each loop whose oscillation check flagged it, with its period and what points at it."""

    found = []
    for loop_id, items in results.items():
        if loop_id not in loops:
            continue
        oscillation = _result(items, OSCILLATION)
        if oscillation is None or oscillation.get("status") not in FLAGGED:
            continue
        metrics = oscillation.get("metrics") or {}
        period = _period(metrics)
        if period is None:
            continue
        stiction = _result(items, STICTION)
        loop = loops[loop_id]
        found.append(
            {
                "loop_id": loop_id,
                "name": getattr(loop, "name", loop_id),
                "area": getattr(loop, "area", ""),
                "period_seconds": round(period, 1),
                "regularity": float(metrics.get("regularity") or 0.0),
                "autocorrelation_peak": float(metrics.get("autocorrelation_peak") or 0.0),
                "stiction": bool(stiction and stiction.get("status") in FLAGGED),
            }
        )
    return found


def _rank(item: dict[str, Any]) -> tuple[float, ...]:
    return (
        1.0 if item["stiction"] else 0.0,
        min(item["regularity"], 10.0),
        item["autocorrelation_peak"],
    )


def group_by_period(
    results: dict[str, list[dict[str, Any]]], loops: dict[str, Any], tolerance: float = 0.15
) -> dict[str, Any]:
    """Groups of oscillating loops with periods within ``tolerance`` (relative), largest first,
    each with its loops ranked as likely origins; loops alone at their period last."""

    found = sorted(oscillating_loops(results, loops), key=lambda item: item["period_seconds"])
    groups: list[list[dict[str, Any]]] = []
    for item in found:
        if groups and item["period_seconds"] <= groups[-1][0]["period_seconds"] * (1 + tolerance):
            groups[-1].append(item)
        else:
            groups.append([item])
    shaped = []
    for members in groups:
        ranked = sorted(members, key=_rank, reverse=True)
        first = ranked[0]
        why = []
        if first["stiction"]:
            why.append("its valve shows stiction")
        if len(ranked) > 1:
            why.append("its cycle is the most regular of the group")
        periods = [item["period_seconds"] for item in members]
        shaped.append(
            {
                "period_seconds": round(sum(periods) / len(periods), 1),
                "period_range_seconds": [min(periods), max(periods)],
                "loop_count": len(members),
                "areas": sorted({item["area"] for item in members if item["area"]}),
                "likely_origin": first["loop_id"],
                "why": why,
                "loops": ranked,
            }
        )
    shaped.sort(key=lambda group: (-group["loop_count"], group["period_seconds"]))
    return {
        "oscillating": len(found),
        "groups": [group for group in shaped if group["loop_count"] > 1],
        "alone": [group["loops"][0] for group in shaped if group["loop_count"] == 1],
        "tolerance": tolerance,
    }
