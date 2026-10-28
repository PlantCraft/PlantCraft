"""A loop's health from its methods' verdicts: the score, its limiting method and the state.

The ``output.loop_health`` block computes it (``blocks.outputs``); the functions are plain, so
the loop page, a round and a replay all reach the same number.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from plantcraft_sdk.methods import MethodResult
from plantcraft_sdk.methods.findings import fmt_percent

from linkcraft.catalog.registry import describe_result
from linkcraft.i18n import t


def _json_result(result: MethodResult) -> dict[str, Any]:
    data = result.model_dump(mode="json")
    data["finding"] = describe_result(data)
    return data


def _manual_fraction(series: pd.Series) -> float | None:
    clean = series.dropna()
    if clean.empty:
        return None
    normalized = clean.astype(str).str.strip().str.lower()
    manual_tokens = {"manual", "man", "m", "0", "false"}
    return float(normalized.isin(manual_tokens).mean())


def _last_numeric(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame:
        return None
    clean = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


# Mean |PV - SP| relative to the SP above which a pinned output is saturation, not inactivity.
SATURATED_TRACKING_RATIO = 0.02


def _operating_state(frame: pd.DataFrame) -> tuple[str, str]:
    pv = pd.to_numeric(frame.get("pv"), errors="coerce").dropna()
    if len(pv) < 3:
        return "insufficient_samples", t("PV without enough samples.")

    if "mode" in frame:
        manual_fraction = _manual_fraction(frame["mode"])
        if manual_fraction is not None and manual_fraction >= 0.5:
            return "manual", t(
                "Manual mode for {fraction} of the window.", fraction=fmt_percent(manual_fraction)
            )

    op = pd.to_numeric(frame.get("op"), errors="coerce").dropna()
    sp = pd.to_numeric(frame.get("sp"), errors="coerce").dropna()
    if len(op) >= 3:
        op_span = float(op.quantile(0.95) - op.quantile(0.05))
        op_limit_fraction = float(((op <= 1.0) | (op >= 99.0)).mean())
        flat_output = op_span <= 0.10
        tracking_ratio = 0.0
        aligned = pd.concat(
            [
                pd.to_numeric(frame.get("pv"), errors="coerce"),
                pd.to_numeric(frame.get("sp"), errors="coerce"),
            ],
            axis=1,
        ).dropna()
        if len(aligned) and not sp.empty:
            scale = max(abs(float(sp.median())), 1e-12)
            tracking_ratio = float((aligned.iloc[:, 0] - aligned.iloc[:, 1]).abs().mean() / scale)
        # Output pinned at a limit while a live PV stays away from the SP is a
        # saturated loop, which the saturation method scores. Pinned with the PV
        # on target (a selector or override in control) or with a dead PV (the
        # equipment is stopped) is not a loop in operation.
        scale = max(abs(float(sp.median())), 1.0) if not sp.empty else 1.0
        pv_alive = float(pv.quantile(0.95) - pv.quantile(0.05)) > 1e-3 * scale
        saturated = pv_alive and tracking_ratio >= SATURATED_TRACKING_RATIO
        if op_limit_fraction >= 0.95 and not saturated:
            return (
                "possibly_inactive",
                t(
                    "Output stayed at a limit with the PV at the setpoint; check the mode or selector."
                ),
            )
        if flat_output and tracking_ratio >= 0.20 and op_limit_fraction < 0.95:
            return (
                "possibly_inactive",
                t("Output stayed constant despite the PV–SP deviation."),
            )

    return "active", t("Signals consistent with a loop in operation.")


def loop_summary(
    frame: pd.DataFrame,
    results: list[MethodResult],
    excluded_methods: set[str] | None = None,
    context_methods: set[str] | None = None,
    diagnostic_methods: set[str] | None = None,
) -> dict[str, Any]:
    pv = pd.to_numeric(frame.get("pv"), errors="coerce")
    valid_fraction = float(pv.notna().mean()) if len(frame) else 0.0
    state, state_reason = _operating_state(frame)
    scored = [
        result
        for result in results
        if result.status.value
        not in {
            "insufficient_data",
            "not_applicable",
        }
        and result.method_id not in (excluded_methods or set())
    ]
    worst = max(scored, key=lambda item: item.score) if scored else None
    worst_score = float(worst.score) if worst else 0.0
    functional_components = [
        {
            "method_id": item.method_id,
            "value": round(float(item.metrics["performance_component"]), 1),
        }
        for item in scored
        if isinstance(item.metrics.get("performance_component"), (int, float))
    ]
    functional_score = None
    if functional_components:
        product = 1.0
        for component in functional_components:
            product *= max(0.0, min(100.0, component["value"])) / 100.0
        functional_score = round(100.0 * product, 1)
    # The component that pulls the multiplied score down the most explains it.
    limiting = min(functional_components, key=lambda item: item["value"], default=None)
    limiting_result = next(
        (item for item in scored if limiting and item.method_id == limiting["method_id"]), None
    )
    current_pv = _last_numeric(frame, "pv")
    current_sp = _last_numeric(frame, "sp")
    current_op = _last_numeric(frame, "op")
    current_error = (
        current_pv - current_sp if current_pv is not None and current_sp is not None else None
    )
    last_sample = None
    if "timestamp" in frame:
        timestamps = pd.to_datetime(frame["timestamp"], errors="coerce").dropna()
        if not timestamps.empty:
            last_sample = str(timestamps.iloc[-1])
    if state in {"insufficient_samples"}:
        status = "no_data"
        health = None
    elif state in {"manual", "possibly_inactive"}:
        status = "inactive"
        health = None
    else:
        health = (
            functional_score
            if functional_score is not None
            else round(max(0.0, 100.0 - worst_score), 1)
        )
        if health <= 25:
            status = "critical"
        elif health <= 50:
            status = "high"
        elif health <= 75:
            status = "medium"
        else:
            status = "normal"
    return {
        "status": status,
        "health": health,
        "functional_score": functional_score,
        "functional_components": functional_components,
        "worst_score": round(worst_score, 1),
        "worst_method": worst.method_id if worst else None,
        # Operator behaviour shown beside the score, never inside it.
        "context": [
            {
                "method_id": item.method_id,
                "value": round(float(item.metrics["performance_component"]), 1),
                "finding": describe_result(_json_result(item)),
            }
            for item in results
            if item.method_id in (context_methods or set())
            and item.status.value not in {"insufficient_data", "not_applicable"}
            and isinstance(item.metrics.get("performance_component"), (int, float))
        ],
        # Fault screenings outside the score (stiction, oscillation...) that flagged something.
        "alerts": [
            {
                "method_id": item.method_id,
                "severity": item.status.value,
                "finding": describe_result(_json_result(item)),
            }
            for item in sorted(
                results, key=lambda item: (item.status.value != "bad", -float(item.score or 0))
            )
            if item.status.value in {"warning", "bad"}
            and item.method_id in (diagnostic_methods or set())
        ],
        "limiting": (
            {
                "method_id": limiting["method_id"],
                "value": limiting["value"],
                "finding": describe_result(_json_result(limiting_result)),
            }
            if limiting and limiting_result and limiting["value"] < 100
            else None
        ),
        "operating_state": state,
        "operating_state_reason": state_reason,
        "valid_fraction": round(valid_fraction, 4),
        "missing_fraction": round(1.0 - valid_fraction, 4),
        "sample_count": int(len(frame)),
        "method_count": len(results),
        "method_ok_count": len(scored),
        "current_pv": current_pv,
        "current_sp": current_sp,
        "current_op": current_op,
        "current_error": current_error,
        "last_sample": last_sample,
    }
