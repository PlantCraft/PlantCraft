"""Likely causes of a loop's problems, ranked from its method findings (gap G1).

A fixed table of rules: each cause names the methods whose findings point to it, and the
methods whose findings speak against it. A method that reports ``bad`` counts 2, ``warning``
counts 1. Causes with support are ranked by their count; each comes with the findings that
support it and what to do first. Nothing is measured here: the evidence is the methods'.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from linkcraft.i18n import t

WEIGHT = {"bad": 2, "warning": 1}


def _pattern(results: dict[str, dict[str, Any]]) -> str | None:
    """What kind of repetition the oscillation screening saw: ``cycle``, ``upsets`` or None."""

    metrics = (results.get("oscillation_autocorrelation") or {}).get("metrics") or {}
    pattern = metrics.get("pattern")
    return str(pattern) if pattern else None


@dataclass(frozen=True)
class Cause:
    cause_id: str
    name: str
    # Methods whose finding supports the cause; the first one must be among them.
    signs: tuple[str, ...]
    # A problem found by any of these makes the cause less likely (counts against it).
    against: tuple[str, ...]
    action: str
    # Supporting methods that only add weight when a main sign is already there.
    main: tuple[str, ...] = ()
    # A condition on the results (by method id) for the cause to apply at all.
    when: Callable[[dict[str, dict[str, Any]]], bool] | None = None


# In table order on a tie: the more specific cause first.
CAUSES = (
    Cause(
        "stiction",
        "Valve stiction",
        ("stiction_screening", "oscillation_autocorrelation"),
        (),
        "Check the valve in the field before touching the tuning: small OP steps in manual "
        "show whether it moves smoothly; a sticking valve needs maintenance (packing, "
        "positioner) and retuning will not fix it.",
        main=("stiction_screening",),
    ),
    Cause(
        "saturation",
        "Valve at its limit",
        ("op_saturation_fraction", "error_metrics_basic"),
        (),
        "The output sits at a limit, so the loop has no room to act: check the valve sizing, "
        "a closed bypass or upstream pressure, and the OP limits set in the controller.",
        main=("op_saturation_fraction",),
    ),
    Cause(
        "operation",
        "Operation in manual",
        ("manual_mode_fraction",),
        (),
        "Ask the operators why the loop is taken out of automatic: the reason (a bad valve, a "
        "poor tuning, a process limit) is the problem to fix first.",
    ),
    Cause(
        "measurement_noise",
        "Noisy measurement",
        ("sensor_noise_ratio", "op_travel_reversal"),
        (),
        "Check the transmitter, its impulse lines and wiring; a light PV filter, or less "
        "derivative action, keeps the noise from moving the valve.",
        main=("sensor_noise_ratio",),
    ),
    Cause(
        "slow_drift",
        "Slow drift: sensor or process",
        ("output_drift",),
        (),
        "The output walks away while the PV holds its setpoint. Compare the PV with a "
        "redundant measurement, a lab result or a balance: a transmitter that drifts needs "
        "calibration. If it reads right, look for fouling, valve wear or a feed changing slowly.",
    ),
    Cause(
        "external_disturbance",
        "Disturbance from another loop",
        ("interaction_cross_correlation", "oscillation_autocorrelation"),
        (),
        "Find the loop that oscillates with the same period first (Loop interaction names "
        "it) and fix it there; retuning this loop would only hide the disturbance.",
        main=("interaction_cross_correlation",),
    ),
    Cause(
        "recurring_disturbance",
        "Recurring load disturbance",
        ("oscillation_autocorrelation", "error_metrics_basic"),
        ("stiction_screening",),
        "The loop answers upsets that come back on a schedule (a feed, a batch, a consumer "
        "switching): find the source from the period; feedforward or a smoother change at the "
        "source helps more than retuning.",
        main=("oscillation_autocorrelation",),
        when=lambda results: _pattern(results) == "upsets",
    ),
    Cause(
        "aggressive_tuning",
        "Aggressive tuning or a cycling disturbance",
        ("oscillation_autocorrelation", "op_travel_reversal"),
        ("stiction_screening", "interaction_cross_correlation"),
        "First look for another loop or equipment that cycles with the same period: if one "
        "does, fix it there. If not, lower the controller gain or lengthen the integral time in "
        "small steps and watch the oscillation; confirm with a small setpoint step that the "
        "loop settles without overshoot.",
        main=("oscillation_autocorrelation",),
        when=lambda results: _pattern(results) != "upsets",
    ),
    Cause(
        "sluggish_tuning",
        "Sluggish tuning",
        ("harris_index", "error_metrics_basic"),
        (
            "oscillation_autocorrelation",
            "op_saturation_fraction",
            "manual_mode_fraction",
            "sensor_noise_ratio",
            "output_drift",
        ),
        "Raise the controller gain or shorten the integral time in small steps; the "
        "minimum-variance index says how much of the variance retuning could remove.",
        # Only with an error to show for it; a loop that cycles is not sluggish.
        main=("error_metrics_basic",),
        when=lambda results: _pattern(results) is None,
    ),
    Cause(
        "valve_wear",
        "Excessive valve movement",
        ("op_travel_reversal",),
        ("sensor_noise_ratio", "oscillation_autocorrelation"),
        "The valve reverses more than needed and wears: reduce gain or derivative action, "
        "or filter the PV, then follow the travel in the next weeks.",
    ),
    Cause(
        "setpoint_changes",
        "Frequent setpoint changes",
        ("setpoint_activity", "operational_interventions"),
        (),
        "The setpoint is moved often by hand: ask why (operating campaigns, an operator "
        "correcting a drifting process). If the moves follow a measurement, a cascade or a "
        "ratio could make them; if the loop answers each move well, this is operation, not a "
        "fault.",
    ),
)


def cause_name(cause_id: str | None) -> str:
    """A cause's name in the reader's language ('' for an unknown id)."""

    found = next((cause for cause in CAUSES if cause.cause_id == cause_id), None)
    return t(found.name) if found else ""


def _by_method(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(result.get("method_id")): result for result in results}


def _weights(results: list[dict[str, Any]]) -> dict[str, tuple[int, str]]:
    found: dict[str, tuple[int, str]] = {}
    for result in results:
        weight = WEIGHT.get(str(result.get("status")))
        if weight:
            method = str(result.get("method_id"))
            finding = str(result.get("finding") or result.get("message") or "")
            if weight > found.get(method, (0, ""))[0]:
                found[method] = (weight, finding)
    return found


def likely_causes(results: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """The causes the findings point to, most supported first, at most ``limit``."""

    found = _weights(results)
    by_method = _by_method(results)
    ranked = []
    for order, cause in enumerate(CAUSES):
        if cause.when is not None and not cause.when(by_method):
            continue
        if cause.main and not any(method in found for method in cause.main):
            continue
        support = [method for method in cause.signs if method in found]
        if not support:
            continue
        strength = sum(found[method][0] for method in support)
        strength -= sum(found[method][0] for method in cause.against if method in found)
        if strength <= 0:
            continue
        ranked.append(
            (
                -strength,
                order,
                {
                    "cause_id": cause.cause_id,
                    "cause": t(cause.name),
                    "strength": strength,
                    "evidence": [
                        {"method_id": method, "finding": found[method][1]} for method in support
                    ],
                    "action": t(cause.action),
                },
            )
        )
    return [item for _, _, item in sorted(ranked, key=lambda row: (row[0], row[1]))][:limit]
