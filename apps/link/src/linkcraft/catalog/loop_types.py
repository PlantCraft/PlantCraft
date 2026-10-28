"""Analysis defaults per loop type: the algorithm and method parameters a loop starts with.

PlantCraft's asset record says what a loop controls (attribute ``loop_type``: flow, level,
pressure, temperature, composition). LinkCraft turns that into the loop's starting algorithm and a
few method parameters that depend on how fast the process is and how the loop is meant to work.
A person can change any of them on the loop page; that choice is LinkCraft's and wins over these
defaults (``loops/store.py``). The table and its reasons are in ``docs/loop-types.md``.

Parameters here sit *under* the algorithm's own parameters: defaults of the method, then the loop
type, then the algorithm, then what a person set on the loop, then a run's own overrides.
"""

from __future__ import annotations

from typing import Any

# The loop algorithms Link ships (``blocks.algorithms``), one per kind of loop.
FLOW_LOOP = "flow_loop"
LEVEL_LOOP = "level_loop"
SLOW_LOOP = "temperature_loop"
# The algorithm every loop starts with when nothing more specific applies.
DEFAULT_ALGORITHM = FLOW_LOOP
# The protocols of version 0.2 and the algorithms of 0.3 -> the algorithm that replaced each.
ALGORITHM_OF_PROTOCOL: dict[str, str] = {
    "all": DEFAULT_ALGORITHM,
    "general": DEFAULT_ALGORITHM,
    "tracking": DEFAULT_ALGORITHM,
    "flow_control": FLOW_LOOP,
    "pressure_control": SLOW_LOOP,
    "level_control": LEVEL_LOOP,
    "temperature_control": SLOW_LOOP,
    "composition_control": SLOW_LOOP,
    "cascade": DEFAULT_ALGORITHM,
    "valve": FLOW_LOOP,
    "oscillation": FLOW_LOOP,
    "surge_drum": "surge_level",
    # 0.3: Loop health, Control valve and Oscillation and noise became Flow loop (round 6).
    "loop_health": FLOW_LOOP,
    "control_valve": FLOW_LOOP,
    "oscillation_noise": FLOW_LOOP,
}


def algorithm_id(value: str | None) -> str:
    """The algorithm a stored id names today (an old protocol id maps to its replacement)."""

    value = str(value or "").strip() or DEFAULT_ALGORITHM
    return ALGORITHM_OF_PROTOCOL.get(value, value)


# Loop type -> starting algorithm and the parameters that follow from the process's speed.
LOOP_TYPE_DEFAULTS: dict[str, dict[str, Any]] = {
    # Fast (seconds), noisy measurement, the valve works continuously: tolerate more travel and
    # reversals before calling it wear, more noise, and smaller valve moves read as stuck.
    "flow": {
        "profile_id": FLOW_LOOP,
        "why": "Fastest loops, noisy measurement, a valve that moves all the time: more travel "
        "and reversals allowed, more noise tolerated, smaller valve moves read as stuck.",
        "parameters": {
            "op_travel_reversal": {"max_travel_per_hour": 400.0, "max_reversals_per_hour": 120.0},
            "sensor_noise_ratio": {"noise_ratio_threshold": 0.25},
            "stiction_screening": {"movement_epsilon": 0.03},
        },
    },
    # The record says a level is controlled, not whether it is held tight or averaged inside
    # a band. Tight is the default: it is scored on the PV-SP error like the other types, so a
    # healthy tight level is not marked down for moving its valve. An averaging (surge) level
    # gets the Surge level algorithm on its loop page (attenuation and time in band).
    "level": {
        "profile_id": LEVEL_LOOP,
        "why": "The record does not say whether the level is held tight or averaged: scored as "
        "tight (Level loop) on the PV-SP error, valve allowed less travel. Pick the Surge level "
        "algorithm on the loop page for a level that should absorb upsets inside its band.",
        "parameters": {
            "op_travel_reversal": {"max_travel_per_hour": 100.0, "max_reversals_per_hour": 30.0},
        },
    },
    # Fast to medium (seconds to a minute), must hold its setpoint; the method defaults suit it.
    "pressure": {
        "profile_id": SLOW_LOOP,
        "why": "Fast to medium, must hold its setpoint; oscillation and stiction screened with the "
        "method defaults.",
        "parameters": {},
    },
    # Slow (minutes), smooth measurement: setpoints change rarely and the valve should not hunt.
    "temperature": {
        "profile_id": SLOW_LOOP,
        "why": "Slow, smooth measurement: rare setpoint moves, a valve that should not hunt, longer "
        "historian gaps still valid.",
        "parameters": {
            "op_travel_reversal": {"max_travel_per_hour": 100.0, "max_reversals_per_hour": 30.0},
            "setpoint_activity": {"max_changes_per_hour": 2.0},
            "dq_availability": {"max_gap_seconds": 900.0},
        },
    },
    # Slowest (minutes to hours), often an analyser sampled every few minutes and the primary of
    # a cascade: few setpoint moves, long gaps between analyser updates are normal.
    "composition": {
        "profile_id": SLOW_LOOP,
        "why": "Slowest, often an analyser and a cascade primary whose output is a flow setpoint, "
        "not a valve: few setpoint moves, long gaps between analyser updates, output moves not "
        "judged as valve wear.",
        "parameters": {
            # Valve travel is judged by the loop algorithms; a cascade primary's output is a setpoint, whose
            # moves are its job (0.2's composition protocol left travel out altogether).
            "op_travel_reversal": {"max_travel_per_hour": 2000.0, "max_reversals_per_hour": 600.0},
            "setpoint_activity": {"max_changes_per_hour": 1.0},
            "dq_availability": {"max_gap_seconds": 1800.0},
        },
    },
}

# A loop without a known type runs Flow loop with the method defaults.
GENERIC_PROFILE = DEFAULT_ALGORITHM
GENERIC_WHY = (
    "The record does not say what the loop controls: Flow loop runs with the method defaults."
)

# Criticality values of the asset record -> LinkCraft's weights (``loops/analysis.py``).
CRITICALITIES = ("critical", "high", "medium", "low")
DEFAULT_CRITICALITY = "medium"


def known_loop_type(value: Any) -> str | None:
    """The loop type in LinkCraft's table, or ``None`` (missing, not text or not known)."""

    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in LOOP_TYPE_DEFAULTS else None


def known_criticality(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned if cleaned in CRITICALITIES else None


def default_profile(loop_type: str | None) -> str:
    """The algorithm a loop of this type starts with."""

    known = known_loop_type(loop_type)
    return LOOP_TYPE_DEFAULTS[known]["profile_id"] if known else GENERIC_PROFILE


def type_parameters(loop_type: str | None) -> dict[str, dict[str, Any]]:
    """Method parameters that follow from the loop type (a fresh copy)."""

    known = known_loop_type(loop_type)
    if not known:
        return {}
    return {
        method_id: dict(values)
        for method_id, values in LOOP_TYPE_DEFAULTS[known]["parameters"].items()
    }
