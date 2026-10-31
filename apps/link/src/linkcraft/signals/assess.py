"""One signal's verdict: run the Signal quality algorithm on its samples.

``assess`` is a plain function of plain data so a round can run it in worker processes. It runs
the algorithm's diagram (``blocks.algorithms``, ``signal_quality``): the signal as recorded
through each data quality check (``dq.*``) into the Signal verdict block, which combines them:

- ``status``: ``bad`` when any check is bad, ``suspect`` when any warns,
  ``good`` when every check that could judge passed, ``unknown`` when none could;
- ``quality``: 100 minus the worst check score (100 is clean data), ``None`` when unknown;
- ``apt``: the data can be used for analysis (``good`` or ``suspect``). Analytics'
  loop methods (and other apps, through the published result) read this flag before a loop
  is judged;
- ``limiting``: the check with the worst score, whose message heads the verdict.

Which checks run, and with which parameters, is the signal's own (``plan``): the admins' choice
of checks and defaults, then the signal's settings, handed to the check blocks.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import Context, Plan, execute

from linkcraft.blocks.algorithms import SIGNAL_QUALITY, system_algorithm
from linkcraft.blocks.catalog import CATALOG, compile_algorithm
from linkcraft.blocks.outputs import collected, combine_checks
from linkcraft.catalog.signal_checks import (
    CHECKS,
    TEXT_CHECKS,
    check_result,
    dataset_for,
    naive,
    parameters_for,
)
from linkcraft.signals.models import CONSTANT_ROLES, SignalQualitySettings

# Kept for the callers that import them from here.
_check_result = check_result
combine = combine_checks
__all__ = ["assess", "combine", "dataset_for", "is_sampled", "plan", "sample_interval_minutes"]


# A sampled signal (laboratory analyses, manual entries) is not judged as a process signal:
# a value repeats until the next sample and the time between samples is no noise, so these
# checks run on it only when a person switches them on. Range, jumps between samples (spikes)
# and drift still judge it; freshness and gaps are measured against its sampling interval.
LAB_SKIPPED = ("sq_frozen", "sq_noise", "sq_resolution")
# The interval assumed when a sampled signal has too few samples to show its own (4 h).
LAB_DEFAULT_INTERVAL_MINUTES = 240.0


def is_sampled(signal: dict[str, Any]) -> bool:
    """A laboratory or manual signal: set by a person, else read from its source (a CSV file)."""

    sampling = (signal.get("settings") or {}).get("sampling")
    if sampling in ("lab", "continuous"):
        return sampling == "lab"
    return signal.get("source_kind") == "csv"


def sample_interval_minutes(signal: dict[str, Any], values: Any = None) -> float:
    """A sampled signal's expected interval: its setting, else the median between its samples."""

    given = (signal.get("settings") or {}).get("sample_interval_minutes")
    try:
        if given is not None and float(given) > 0:
            return float(given)
    except (TypeError, ValueError):
        pass
    if values is not None and len(values) > 2:
        steps = pd.Series(pd.DatetimeIndex(values.index).sort_values()).diff().dropna()
        median = steps.median().total_seconds() / 60.0 if len(steps) else 0.0
        if median > 0:
            return float(median)
    return LAB_DEFAULT_INTERVAL_MINUTES


def _lab_layers(interval: float) -> dict[str, dict[str, Any]]:
    """Freshness and gaps measured against the sampling interval (one missed sample warns)."""

    return {
        "sq_freshness": {"warn_age_minutes": 1.5 * interval, "bad_age_minutes": 3.0 * interval},
        "sq_availability": {"max_gap_seconds": 1.5 * interval * 60.0},
    }


def plan(
    signal: dict[str, Any], settings: SignalQualitySettings, values: Any = None
) -> list[tuple[str, dict[str, Any]]]:
    """The checks a signal gets, each with its parameters (defaults, admin, signal).

    A sampled signal (``is_sampled``) gets its own rules between the admin's defaults and its
    own parameters; ``values`` (its samples, when read) tell its interval when none is set.
    """

    own = signal.get("settings") or {}
    chosen = [item for item in (settings.enabled_checks or list(CHECKS)) if item in CHECKS]
    switched_on = set(own.get("checks_on") or [])
    chosen += [item for item in CHECKS if item in switched_on and item not in chosen]
    off = set(own.get("checks_off") or [])
    if set(signal.get("roles") or []) & set(CONSTANT_ROLES) and "sq_frozen" not in switched_on:
        off.add("sq_frozen")
    lab: dict[str, dict[str, Any]] = {}
    if is_sampled(signal):
        off.update(item for item in LAB_SKIPPED if item not in switched_on)
        lab = _lab_layers(sample_interval_minutes(signal, values))
    if signal.get("kind") == "text":
        chosen = [item for item in chosen if item in TEXT_CHECKS]
    ordered = [item for item in CHECKS if item in chosen and item not in off]
    parameters = own.get("parameters") or {}
    return [
        (
            check_id,
            parameters_for(
                check_id,
                settings.check_parameters.get(check_id),
                lab.get(check_id),
                parameters.get(check_id),
            ),
        )
        for check_id in ordered
    ]


@cache
def _plan() -> Plan:
    found = system_algorithm(SIGNAL_QUALITY)
    assert found is not None
    return compile_algorithm(found["diagram"])


def _given(values: Any) -> pd.Series:
    """Samples as recorded; none is an empty series, so each check says why it cannot judge."""

    series = values.copy() if values is not None else pd.Series(dtype=float)
    series.attrs = {"recorded": True}
    return series


def assess(task: dict[str, Any]) -> dict[str, Any]:
    """Verdict of one signal. ``task``: signal, values, reference, start, end, checks, resampled,
    quality (the source's quality changes, when the Historian keeps them)."""

    signal = task["signal"]
    start, end = naive(task["start"]), naive(task["end"])
    plan_ = _plan()
    checks = dict(task["checks"])
    context = Context(
        start=start,
        end=end,
        asset={"id": str(signal["id"])},
        extra={
            "signal": signal,
            "checks_on": list(checks),
            # The parameters ``plan`` resolved win over the diagram's.
            "check_layers": {check_id: [parameters] for check_id, parameters in checks.items()},
            "resampled": bool(task.get("resampled")),
            "quality": task.get("quality"),
        },
    )
    # The samples go in as given: a text signal keeps its text.
    given = {"signal": task.get("values"), "reference": task.get("reference")}
    preset = {}
    for node_id in plan_.blocks_of("input.signal"):
        role = str(plan_.nodes[node_id].get("parameters", {}).get("role"))
        value = _given(given.get(role))
        preset[(node_id, "value")] = value
        preset[(node_id, "recorded")] = value
    execute(plan_, CATALOG, context, preset=preset)
    verdict = collected(context).get("signal") or combine_checks(str(signal["id"]), [])
    dataset = dataset_for(signal, task.get("values"), start, end, task.get("reference"))
    verdict["window_start"] = start.tz_localize("UTC").isoformat()
    verdict["window_end"] = end.tz_localize("UTC").isoformat()
    verdict["samples"] = int(len(dataset.raw)) if dataset.raw is not None else 0
    return verdict
