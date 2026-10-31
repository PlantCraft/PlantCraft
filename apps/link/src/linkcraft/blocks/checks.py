"""Data quality checks (``dq.*``): one block per signal check of ``catalog.signal_checks``.

A check reads one signal, preferably as recorded, and judges whether its data can be trusted.
On the Signal quality algorithm (one run per signal) a signal's own settings can switch a check
off or change its parameters; the block then says so in its verdict and the verdict is left out.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, Result, inport, outport

from linkcraft.blocks.base import described
from linkcraft.catalog.help_docs import _reference
from linkcraft.catalog.signal_checks import (
    ACTIONS,
    CHECKS,
    JUDGED,
    TEXT_CHECKS,
    check_result,
    dataset_for,
    naive,
    parameters_for,
)
from linkcraft.i18n import t

# How each check works and how to read it, beyond its one-sentence summary.
TEXTS: dict[str, tuple[str, str]] = {
    "sq_availability": (
        "Measures how much of the window the recorded samples cover. An interval between two "
        "samples longer than the maximum gap counts as missing; the rest counts as covered, "
        "since historians that record on change leave long intervals on a steady signal.",
        "Ok above the warning coverage, warning below it, bad below the minimum coverage: the "
        "data is then too sparse to judge anything else.",
    ),
    "sq_freshness": (
        "Measures the age of the last sample at the end of the window. A signal whose source "
        "stopped updating keeps its last value in many systems, so a stale value looks normal "
        "until its age is checked.",
        "Ok while the last sample is recent, warning past the warning age, bad past the stale "
        "age: the signal stopped updating.",
    ),
    "sq_frozen": (
        "Finds stretches where consecutive samples stay within the tolerance of each other for "
        "longer than the minimum duration: a stuck sensor, a frozen transmitter or a value the "
        "control system substituted.",
        "Ok without frozen stretches, warning with some, bad when the frozen share of the window "
        "reaches the limit; the sentence says how long and when.",
    ),
    "sq_spikes": (
        "Finds samples that jump away from their neighbours and come straight back, with a "
        "Hampel filter (median and median absolute deviation of a sliding window), ignoring "
        "jumps smaller than a share of the signal's normal range.",
        "Ok without spikes, warning with a few, bad when the spiky share of the samples reaches "
        "the limit: wiring, grounding or the transmitter.",
    ),
    "sq_range": (
        "Counts the samples outside the instrument's low and high limits, with a margin as a "
        "share of the range. Values a healthy instrument cannot give point to a failed sensor, "
        "a wrong unit or wrong limits.",
        "Ok inside the range, warning with a few values outside, bad when the share outside "
        "reaches the limit. Without limits the check cannot judge.",
    ),
    "sq_noise": (
        "Estimates the high-frequency noise from the first differences of the samples (white "
        "noise estimate that ignores slow process moves) and compares it with the signal's "
        "range.",
        "Ok when the noise is small against the range, warning past the warning share, bad "
        "when the noise hides the process.",
    ),
    "sq_resolution": (
        "Looks for coarse steps (a quantised signal, a wide recording deadband) and for stretches "
        "of samples on straight lines (interpolated compressed data), both of which hide the "
        "process's real movement.",
        "Ok with fine steps and recorded samples, warning or bad when steps are coarse against "
        "the spread or many samples sit on straight lines.",
    ),
    "sq_drift": (
        "Tests whether the signal (or its difference from a reference, such as a redundant "
        "transmitter) walks steadily in one direction over the window, by comparing the medians "
        "of time slices with a trend test.",
        "Ok without a significant trend, warning or bad when the change over the window reaches "
        "the share of the range set; with a reference it points to sensor drift.",
    ),
}


def block_id(check_id: str) -> str:
    return f"dq.{check_id.removeprefix('sq_')}"


def _record(series: pd.Series, ctx: Any) -> dict[str, Any]:
    signal = ctx.extra.get("signal")
    if isinstance(signal, dict):
        return signal
    text = series.dtype == object
    return {
        "id": str(series.name or ctx.node_id),
        "kind": "text" if text else "number",
        "unit": ctx.extra.get("unit") or "",
        "low": None,
        "high": None,
    }


def _window(series: pd.Series, ctx: Any) -> tuple[pd.Timestamp, pd.Timestamp]:
    if ctx.start is not None and ctx.end is not None:
        return naive(ctx.start), naive(ctx.end)
    if len(series.index):
        return naive(series.index.min()), naive(series.index.max())
    stamp = pd.Timestamp("1970-01-01")
    return stamp, stamp


def _check_block(check_id: str) -> Block:
    check = CHECKS[check_id]
    meta = check.metadata
    name = meta.name
    description, reading = TEXTS[check_id]
    action = ACTIONS.get(check_id, "")

    def run(inputs: dict[str, Any], values: Any, ctx: Any) -> dict[str, Any]:
        series = inputs["x"]
        label = t(name)
        switched_on = ctx.extra.get("checks_on")
        if switched_on is not None and check_id not in switched_on:
            return {
                "result": Result(
                    "unknown", None, t("Switched off for this signal."), label, {"off": True}
                )
            }
        record = _record(series, ctx)
        if record.get("kind") == "text" and check_id not in TEXT_CHECKS:
            return {
                "result": Result(
                    "unknown", None, t("Does not apply to a text signal."), label, {"off": True}
                )
            }
        layers = (ctx.extra.get("check_layers") or {}).get(check_id) or []
        parameters = parameters_for(check_id, values.model_dump(exclude_unset=True), *layers)
        start, end = _window(series, ctx)
        resampled = ctx.extra.get("resampled")
        if resampled is None:
            resampled = not series.attrs.get("recorded", False)
        dataset = dataset_for(
            record, series, start, end, inputs.get("reference"), ctx.extra.get("quality")
        )
        outcome = check_result(check_id, parameters, dataset, bool(resampled))
        status = outcome["status"] if outcome["status"] in JUDGED else "unknown"
        value = None if status == "unknown" else 100.0 - float(outcome["score"])
        return {"result": Result(status, value, outcome["message"], label, {"check": outcome})}

    inputs = [
        inport(
            "x",
            ("series", "state"),
            "Signal",
            "The signal to check, best as recorded (raw samples at their own times).",
        )
    ]
    if check_id == "sq_drift":
        inputs.append(
            inport(
                "reference",
                "series",
                "Reference",
                "A redundant or model measurement of the same quantity; drift is read on the "
                "difference when it is wired.",
                required=False,
            )
        )
    return Block(
        BlockSpec(
            block_id(check_id),
            meta.version,
            "dq",
            name,
            BlockDocs(
                summary=meta.description,
                description=description,
                reading=f"{reading} {action}".strip(),
                assumptions=tuple(meta.assumptions),
                limitations=tuple(meta.limitations),
                formula=meta.implemented_formula or "",
                references=tuple(
                    _reference(
                        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    )
                    for item in meta.references
                ),
            ),
            inputs=tuple(inputs),
            outputs=(
                outport(
                    "result",
                    "result",
                    "Verdict",
                    "The check's verdict: status, quality from 0 to 100 (100 is clean data) and "
                    "what it found.",
                ),
            ),
            parameters=described(check.parameter_schema, name=f"{check_id}_parameters"),
            group="Signals",
        ),
        run,
    )


BLOCKS = tuple(_check_block(check_id) for check_id in CHECKS)
