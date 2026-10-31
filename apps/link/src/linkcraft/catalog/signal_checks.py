"""The signal data quality checks, registered once: the Signal quality algorithm, the API and
the interface call them by id (the loop methods are in ``catalog.registry``).

Order matters: it is the order checks run in and are listed. ``TEXT_CHECKS``
are the only ones that judge a text signal (labels such as controller modes).
Their ids are ``sq_<name>``, so they never clash with the loop gate's ``dq_*`` methods.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from plantcraft_sdk.methods import LoopDataset, MethodBlock

from linkcraft.i18n import t
from linkcraft.methods.signal import METHOD_BLOCKS

GROUP_ID = "signal_quality"
GROUP = {
    "group_id": GROUP_ID,
    "name": "Data quality",
    "description": "Whether each signal's recorded data can be trusted: gaps, stale, frozen, "
    "spiky, out-of-range, noisy, coarse and drifting data. The Signal quality algorithm runs "
    "them on every signal.",
    "role": "signal",
}
CHECKS: dict[str, MethodBlock] = {block.metadata.method_id: block for block in METHOD_BLOCKS}
TEXT_CHECKS = ("sq_availability", "sq_source_quality", "sq_freshness")
# A check's verdicts that judge the data (the others say it could not).
JUDGED = ("ok", "warning", "bad")
# Checks that need samples as recorded: on a signal read as means they do not judge.
RAW_ONLY = ("sq_frozen", "sq_spikes", "sq_resolution")
# What each check tells a person to look at (shown in the catalog and on findings).
ACTIONS = {
    "sq_availability": "Check the source connection and the historian's collection for this tag.",
    "sq_source_quality": "Check the device and its connection where the source marks the "
    "values bad, and who or what substituted values (manual entry, a held last value).",
    "sq_freshness": "Check that the source still updates this tag (scan class, interface, device).",
    "sq_frozen": "Check the transmitter: a stuck sensor, a frozen value in the DCS or a "
    "substituted value.",
    "sq_spikes": "Check wiring, grounding and the transmitter; a filter may hide the cause.",
    "sq_range": "Check the instrument's range, its units and the limits recorded for the tag.",
    "sq_noise": "Check the transmitter's damping, the impulse lines and electrical noise.",
    "sq_resolution": "Check the historian's compression deadband and the tag's recorded precision.",
    "sq_drift": "Calibrate the instrument against a reference measurement.",
}


def check(check_id: str) -> MethodBlock | None:
    return CHECKS.get(check_id)


def default_parameters(check_id: str) -> dict[str, Any]:
    block = CHECKS[check_id]
    return block.parameter_schema().model_dump()


def parameters_for(check_id: str, *layers: dict[str, Any] | None) -> dict[str, Any]:
    """The check's defaults, overridden by each layer in turn (admin defaults, then signal).

    Unknown keys are dropped and invalid values fall back to the layer below,
    so a bad stored value never stops a round.
    """

    block = CHECKS[check_id]
    merged = default_parameters(check_id)
    for layer in layers:
        for key, value in (layer or {}).items():
            if key not in merged:
                continue
            trial = {**merged, key: value}
            try:
                merged = block.parameter_schema(**trial).model_dump()
            except ValueError:
                continue
    return merged


def validate_parameters(check_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """Parameters a person sent, checked (raises ``ValueError`` with the reason)."""

    block = CHECKS[check_id]
    unknown = sorted(set(values) - set(default_parameters(check_id)))
    if unknown:
        raise ValueError(t("Unknown parameters: {names}.", names=", ".join(unknown)))
    block.parameter_schema(**{**default_parameters(check_id), **values})
    return dict(values)


def describe(check_id: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    """One check as the catalog shows it: what it does, how, its sources and parameters."""

    block = CHECKS[check_id]
    metadata = block.metadata.model_dump(mode="json")
    schema = block.parameter_schema.model_json_schema()
    current = parameters_for(check_id, defaults)
    parameters = [
        {
            "name": name,
            "label": name.replace("_", " ").capitalize(),
            "help": t(spec.get("description") or ""),
            "type": spec.get("type", "number"),
            "default": spec.get("default"),
            "value": current.get(name),
            "minimum": spec.get("minimum", spec.get("exclusiveMinimum")),
            "maximum": spec.get("maximum", spec.get("exclusiveMaximum")),
        }
        for name, spec in (schema.get("properties") or {}).items()
    ]
    return {
        "id": check_id,
        "name": metadata["name"],
        "description": metadata["description"],
        "maturity": metadata["maturity"],
        "formula": metadata.get("implemented_formula"),
        "assumptions": metadata.get("assumptions") or [],
        "limitations": metadata.get("limitations") or [],
        "references": metadata.get("references") or [],
        "action": t(ACTIONS.get(check_id, "")),
        "text_signals": check_id in TEXT_CHECKS,
        "parameters": parameters,
    }


# Running one check on one signal (the Signal quality algorithm and its blocks) -----


def effective_limits(signal: dict[str, Any]) -> tuple[float | None, float | None]:
    settings = signal.get("settings") or {}
    low = settings.get("low", signal.get("low"))
    high = settings.get("high", signal.get("high"))
    return low, high


def check_result(
    check_id: str, parameters: dict[str, Any], dataset: LoopDataset, resampled: bool
) -> dict[str, Any]:
    block = CHECKS[check_id]
    name = t(block.metadata.name)
    if resampled and check_id in RAW_ONLY:
        return {
            "check": check_id,
            "name": name,
            "status": "not_applicable",
            "score": 0.0,
            "message": t("Read as means (too many samples in the window); needs raw samples."),
            "metrics": {},
            "events": [],
        }
    try:
        outcome = block.run(
            block.input_schema(dataset=dataset), block.parameter_schema(**parameters)
        )
    except Exception as exc:  # A check never stops the others: it reports what went wrong.
        return {
            "check": check_id,
            "name": name,
            "status": "insufficient_data",
            "score": 0.0,
            "message": t("The check failed on this data: {error}", error=str(exc)[:200]),
            "metrics": {},
            "events": [],
        }
    payload = outcome.model_dump(mode="json")
    message = payload.get("message") or ""
    describe = getattr(block, "describe", None)
    if payload["status"] in JUDGED and callable(describe):
        message = describe(payload.get("metrics") or {})
    return {
        "check": check_id,
        "name": name,
        "status": payload["status"],
        "score": round(float(payload.get("score") or 0.0), 1),
        "message": message,
        "metrics": payload.get("metrics") or {},
        "events": [
            {key: item.get(key) for key in ("start_time", "end_time", "label", "details")}
            for item in payload.get("events") or []
        ],
    }


def naive(stamp: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(stamp)
    return stamp.tz_convert("UTC").tz_localize(None) if stamp.tzinfo is not None else stamp


def _naive_series(values: pd.Series | None) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    index = values.index
    if not isinstance(index, pd.DatetimeIndex):
        index = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce", utc=True))
    elif index.tz is None:
        index = index.tz_localize("UTC")
    values = values.copy()
    values.index = index.tz_convert("UTC").tz_localize(None)
    values = values[~values.index.isna()]
    # One sample per instant (the last one recorded), in time order.
    return values[~values.index.duplicated(keep="last")].sort_index()


def dataset_for(
    signal: dict[str, Any],
    values: pd.Series | None,
    start: pd.Timestamp,
    end: pd.Timestamp,
    reference: pd.Series | None = None,
    quality: list[dict[str, Any]] | None = None,
) -> LoopDataset:
    """The dataset a signal check reads. ``quality``: the source's quality changes
    (``[{t, quality}]``, else the ones read with ``values``), in ``metadata["quality"]``."""

    if quality is None and values is not None:
        quality = values.attrs.get("quality")
    columns = {"value": _naive_series(values)}
    if reference is not None and len(reference):
        columns["reference"] = _naive_series(reference)
    raw = (
        pd.concat(columns, axis=1).sort_index()
        if any(len(v) for v in columns.values())
        else (pd.DataFrame({"value": pd.Series(dtype=float)}, index=pd.DatetimeIndex([])))
    )
    raw = raw[(raw.index >= start) & (raw.index <= end)]
    low, high = effective_limits(signal)
    data = raw.reset_index(names="timestamp")
    return LoopDataset(
        loop_id=str(signal["id"]),
        data=data,
        raw=raw,
        start_time=start.isoformat(),
        end_time=end.isoformat(),
        metadata={
            "kind": signal.get("kind") or "number",
            "unit": signal.get("unit") or "",
            "low": low,
            "high": high,
            **({"quality": list(quality)} if quality is not None else {}),
        },
    )
