"""The plant map (A6): every loop's value of one KPI, as a heat map by area and as a treemap
whose areas are sized by criticality.

Each KPI is a percentage where higher is better, so one colour scale reads them all:

- ``health``: the loop's health from its latest round;
- ``effective_control``: % of the time really controlling (``engine.losses``, A7);
- ``normal_mode``, ``in_band``, ``not_saturated``: the three fractions effective control
  multiplies (% in its normal mode, % with the PV inside its band, % with the output off its
  limits).

A value falls in a band: ``good`` from 90, ``fair`` from 75, ``poor`` from 50, ``bad`` below,
``none`` when the loop's algorithm does not measure it. A loop's weight in the treemap is its
criticality weight (``loops.analysis.CRITICALITY_WEIGHTS``, passed in): a critical loop takes
about three times the room of a low one.
"""

from __future__ import annotations

from typing import Any

from linkcraft.engine.losses import effective_control

KPIS = (
    ("health", "Health"),
    ("effective_control", "Effective control"),
    ("normal_mode", "In normal mode"),
    ("in_band", "Inside its band"),
    ("not_saturated", "Output off its limits"),
)
BANDS = ((90.0, "good"), (75.0, "fair"), (50.0, "poor"))
NO_AREA = "No area"


def band(value: float | None) -> str:
    """The colour band of a percentage where higher is better."""

    if value is None:
        return "none"
    for floor, name in BANDS:
        if value >= floor:
            return name
    return "bad"


def _number(value: Any) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return round(float(value), 1)
    return None


def plant_map(
    loops: dict[str, Any],
    summaries: dict[str, dict[str, Any]],
    results: dict[str, list[dict[str, Any]]],
    weights: dict[str, float],
) -> dict[str, Any]:
    """Every loop with each KPI's value and band, its area, criticality and weight; the areas
    sorted by name (no area last) and the loops in each by name."""

    rows = []
    for loop_id, loop in loops.items():
        summary = summaries.get(loop_id) or {}
        control = effective_control(results.get(loop_id) or [])
        values = {
            "health": _number(summary.get("health")),
            "effective_control": control["score"],
            "normal_mode": control["normal_mode"],
            "in_band": control["in_band"],
            "not_saturated": control["not_saturated"],
        }
        criticality = str((getattr(loop, "metadata", None) or {}).get("criticality") or "medium")
        rows.append(
            {
                "loop_id": loop_id,
                "name": getattr(loop, "name", "") or loop_id,
                "area": getattr(loop, "area", "") or "",
                "criticality": criticality,
                "weight": weights.get(criticality, 1.0),
                "status": summary.get("status"),
                "values": values,
                "bands": {key: band(value) for key, value in values.items()},
            }
        )
    rows.sort(key=lambda row: (not row["area"], row["area"].casefold(), row["name"].casefold()))
    return {
        "kpis": [{"key": key, "label": label} for key, label in KPIS],
        "bands": [{"band": name, "from": floor} for floor, name in BANDS],
        "loops": rows,
    }
