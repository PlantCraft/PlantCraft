"""Calibrate: what a deviation block (or an empirical model, M4) judges by, learned from a
period of normal operation.

The algorithm runs on one asset over the period people choose, as its cycle would have run it
(one run per judged part, end to end), and every residual wired to the deviation block is kept.
Their mean and covariance (``models.stats.calibrate``) become the block's ``calibration``
parameter, so the diagram holds everything it judges by. Runs whose residuals could not be
judged (an output not measured, the unit out of operation, the model failed) are left out and
counted, with the first reason.

An empirical model block (``model.empirical``) is calibrated the same way on the signals wired
to it: their principal components (``models.pca.fit_pca``) become its ``calibration``. A
regression block (``model.regression``, A4) is fitted on the target's samples against its inputs
at those times (``models.regression.fit_regression``), with each input's training range.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import NoData

from linkcraft.assets.run import AssetTiming, runs_over, segment_ends
from linkcraft.blocks.models import JUDGED_SECONDS, PREFIX, residual_frame, unjudgeable
from linkcraft.i18n import t
from linkcraft.models.pca import fit_pca
from linkcraft.models.regression import fit_regression
from linkcraft.models.stats import calibrate

DEVIATION_BLOCK = "model.deviation"
EMPIRICAL_BLOCK = "model.empirical"
REGRESSION_BLOCK = "model.regression"
# The port each calibrated block reads its series on.
CALIBRATED = {DEVIATION_BLOCK: "residuals", EMPIRICAL_BLOCK: "signals", REGRESSION_BLOCK: "inputs"}
# Runs one calibration makes at most: three and a half days of ten-minute parts, a minute or
# two of simulation while the editor waits.
MAX_RUNS = 500


def wires_into(diagram: dict[str, Any], node_id: str, port: str) -> list[tuple[str, str]]:
    """The (node, port) wired to ``node_id``'s ``port``, in the diagram's order."""

    return [
        (str(edge["source"]), str(edge["source_port"]))
        for edge in diagram.get("edges") or []
        if edge.get("target") == node_id and edge.get("target_port") == port
    ]


def judged_part(diagram: dict[str, Any], sources: list[tuple[str, str]], timing: AssetTiming):
    """Seconds between two calibration runs: the shortest judged part of the model blocks that
    feed the deviation block (each run then adds the residuals of one judged part), else the
    window."""

    nodes = {str(node.get("id")): node for node in diagram.get("nodes") or []}
    parts = []
    for source, _port in sources:
        node = nodes.get(source) or {}
        if str(node.get("block") or "").startswith(PREFIX):
            value = (node.get("parameters") or {}).get("judged_seconds")
            parts.append(float(value) if value else JUDGED_SECONDS)
    part = min(parts) if parts else float(timing.window_seconds)
    return max(min(part, float(timing.window_seconds)), float(timing.step_seconds))


def calibrate_on_asset(
    diagram: dict[str, Any],
    node_id: str,
    asset_id: str,
    *,
    client: Any,
    start: pd.Timestamp,
    end: pd.Timestamp,
    timing: AssetTiming,
    models: Any = None,
) -> dict[str, Any]:
    """The calibration of deviation block ``node_id`` on ``asset_id`` over ``start``-``end``.

    ``ValueError`` (in words people read) when it cannot calibrate: not a deviation block,
    nothing wired, a period too short or too long, too few samples; ``LookupError`` when the
    asset cannot be read.
    """

    node = next(
        (item for item in diagram.get("nodes") or [] if str(item.get("id")) == node_id), None
    )
    if node is None or node.get("block") not in CALIBRATED:
        raise ValueError(
            t(
                "Calibrate works on a Deviation (T²), an Empirical model or a Regression block "
                "of the diagram."
            )
        )
    if node.get("block") == REGRESSION_BLOCK:
        return _calibrate_regression(
            diagram,
            node,
            asset_id,
            client=client,
            start=start,
            end=end,
            timing=timing,
            models=models,
        )
    empirical = node.get("block") == EMPIRICAL_BLOCK
    residuals = wires_into(diagram, node_id, CALIBRATED[str(node.get("block"))])
    if not residuals:
        raise ValueError(
            t("Wire the unit's signals into the Empirical model block first.")
            if empirical
            else t("Wire the model's residuals into the Deviation block first.")
        )
    active = wires_into(diagram, node_id, "active")
    stride = judged_part(diagram, residuals, timing)
    ends = segment_ends(start, end, stride)
    if not ends:
        raise ValueError(
            t(
                "The period is shorter than one judged part ({seconds} s): choose a longer one.",
                seconds=f"{stride:g}",
            )
        )
    if len(ends) > MAX_RUNS:
        raise ValueError(
            t("The period needs more than {count} runs: choose a shorter one.", count=MAX_RUNS)
        )
    frames: list[pd.DataFrame] = []
    skipped: list[str] = []
    for run in runs_over(
        diagram,
        asset_id,
        client=client,
        ends=ends,
        window=float(timing.window_seconds),
        step=float(timing.step_seconds),
        models=models,
        keep=residuals + active,
    ):
        kept = run["kept"]
        items = [kept[wire] for wire in residuals]
        missing = next((item for item in items if isinstance(item, NoData)), None)
        if missing is not None:
            skipped.append(missing.reason)
            continue
        frame = residual_frame(items)
        if frame.empty:
            skipped.append(t("No residual to judge."))
            continue
        reason = unjudgeable(frame, kept[active[0]] if active else None)
        if reason:
            skipped.append(reason)
            continue
        if frames and list(frame.columns) != list(frames[0].columns):
            raise ValueError(t("The residuals changed during the period: check the wiring."))
        frames.append(frame)
    if not frames:
        raise ValueError(
            t(
                "No run in the period could be used: {reason}",
                reason=skipped[0] if skipped else t("No residual to judge."),
            )
        )
    names = [str(name) for name in frames[0].columns]
    if empirical:
        rows = np.vstack([frame.ffill().to_numpy(dtype=float) for frame in frames])
        variance = float((node.get("parameters") or {}).get("variance") or 0.9)
        try:
            model = fit_pca(rows, names, variance=variance)
        except ValueError as exc:
            raise ValueError(t("Too few samples to calibrate: {why}.", why=exc)) from exc
        return {
            "node_id": node_id,
            "asset_id": asset_id,
            "calibration": {
                **model.as_dict(),
                # As a deviation's calibration reads, so the editor lists the signals.
                "outputs": model.signals,
                "asset": asset_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
            "outputs": model.signals,
            "std": model.std,
            "samples": model.samples,
            "warnings": list(model.warnings),
            "runs": len(ends),
            "used": len(frames),
            "skipped": len(skipped),
            "skipped_reason": skipped[0] if skipped else "",
            "period": {"start": start.isoformat(), "end": end.isoformat(), "every": stride},
        }
    rows = np.vstack([frame.to_numpy(dtype=float) for frame in frames])
    try:
        found = calibrate(rows, names)
    except ValueError as exc:
        raise ValueError(t("Too few samples to calibrate: {why}.", why=exc)) from exc
    return {
        "node_id": node_id,
        "asset_id": asset_id,
        "calibration": {
            **found.as_dict(),
            "asset": asset_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "outputs": names,
        "std": found.std,
        "samples": found.samples,
        "warnings": list(found.warnings),
        "runs": len(ends),
        "used": len(frames),
        "skipped": len(skipped),
        "skipped_reason": skipped[0] if skipped else "",
        "period": {"start": start.isoformat(), "end": end.isoformat(), "every": stride},
    }


def _calibrate_regression(
    diagram: dict[str, Any],
    node: dict[str, Any],
    asset_id: str,
    *,
    client: Any,
    start: pd.Timestamp,
    end: pd.Timestamp,
    timing: AssetTiming,
    models: Any = None,
) -> dict[str, Any]:
    """A regression block's coefficients and training range: each target sample in the period
    against the inputs at that time (the last value at or before it)."""

    node_id = str(node.get("id"))
    inputs = wires_into(diagram, node_id, "inputs")
    target = wires_into(diagram, node_id, "target")
    if not inputs or not target:
        raise ValueError(t("Wire the inputs and the target into the Regression block first."))
    stride = float(timing.window_seconds)
    ends = segment_ends(start, end, stride)
    if not ends:
        raise ValueError(
            t(
                "The period is shorter than one judged part ({seconds} s): choose a longer one.",
                seconds=f"{stride:g}",
            )
        )
    if len(ends) > MAX_RUNS:
        raise ValueError(
            t("The period needs more than {count} runs: choose a shorter one.", count=MAX_RUNS)
        )
    names: list[str] = []
    rows: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    skipped: list[str] = []
    target_name = ""
    used = 0
    for run in runs_over(
        diagram,
        asset_id,
        client=client,
        ends=ends,
        window=stride,
        step=float(timing.step_seconds),
        models=models,
        keep=inputs + target,
    ):
        kept = run["kept"]
        items = [kept[wire] for wire in inputs]
        sampled = kept[target[0]]
        missing = next((item for item in [*items, sampled] if isinstance(item, NoData)), None)
        if missing is not None:
            skipped.append(missing.reason)
            continue
        frame = residual_frame(items)
        samples = pd.to_numeric(sampled, errors="coerce").dropna()
        if frame.empty or samples.empty:
            skipped.append(t("No target sample in the run."))
            continue
        if names and list(frame.columns) != names:
            raise ValueError(t("The inputs changed during the period: check the wiring."))
        names = [str(name) for name in frame.columns]
        target_name = str(sampled.name or "")
        at = frame.sort_index().ffill().reindex(samples.index, method="ffill")
        rows.append(at.to_numpy(dtype=float))
        targets.append(samples.to_numpy(dtype=float))
        used += 1
    if not rows:
        raise ValueError(
            t(
                "No run in the period could be used: {reason}",
                reason=skipped[0] if skipped else t("No target sample in the run."),
            )
        )
    parameters = node.get("parameters") or {}
    try:
        model = fit_regression(
            np.vstack(rows),
            np.concatenate(targets),
            names,
            target_name=target_name,
            method=str(parameters.get("method") or "ridge"),
            alpha=float(parameters.get("alpha", 1.0)),
            components=int(parameters.get("components") or 2),
        )
    except ValueError as exc:
        raise ValueError(t("Too few samples to calibrate: {why}.", why=exc)) from exc
    return {
        "node_id": node_id,
        "asset_id": asset_id,
        "calibration": {
            **model.as_dict(),
            # As a deviation's calibration reads, so the editor lists the inputs.
            "outputs": model.inputs,
            "mean": [(low + high) / 2 for low, high in zip(model.low, model.high, strict=True)],
            "asset": asset_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        "outputs": model.inputs,
        "std": [],
        "samples": model.samples,
        "warnings": list(model.warnings),
        "runs": len(ends),
        "used": used,
        "skipped": len(skipped),
        "skipped_reason": skipped[0] if skipped else "",
        "period": {"start": start.isoformat(), "end": end.isoformat(), "every": stride},
    }


__all__ = [
    "DEVIATION_BLOCK",
    "EMPIRICAL_BLOCK",
    "REGRESSION_BLOCK",
    "calibrate_on_asset",
    "judged_part",
    "wires_into",
]
