"""What every block library of PlantCraft Analytics shares: libraries, signal roles, parameter texts.

The block contract itself is the SDK's (``plantcraft_sdk.blocks``); this module holds the texts
Link's libraries reuse, so a PV port, a parameter or a library reads the same everywhere.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo

from linkcraft.catalog.labels import PARAMETER_LABELS

# Libraries in the order the palette lists them. Texts are English; t() serves them.
LIBRARIES: dict[str, dict[str, str]] = {
    "input": {
        "name": "Inputs",
        "description": "The asset's signals as the algorithm reads them, and verdicts other "
        "algorithms already gave on them.",
    },
    "dq": {
        "name": "Data quality",
        "description": "Whether a signal's recorded data can be trusted, and whether a loop's "
        "data is fit for analysis.",
    },
    "transform": {
        "name": "Transforms",
        "description": "Signal arithmetic, filters, engineering units and the operating "
        "window: a new series from one or more series.",
    },
    "stats": {
        "name": "Statistics",
        "description": "Numbers that summarise a series over the window: mean, spread, "
        "percentiles, distribution, correlation, steps and time outside limits.",
    },
    "cpm": {
        "name": "Control loop performance",
        "description": "Tracking, oscillation, valve, saturation, noise and operating mode of a "
        "control loop.",
    },
    "equipment": {
        "name": "Equipment",
        "description": "Performance of common equipment from its measurements: a heat "
        "exchanger's UA, a pump's efficiency against its curve.",
    },
    "model": {
        "name": "Models",
        "description": "Process models (FMUs) run on the asset's signals, and how far the plant "
        "is from them.",
    },
    "logic": {
        "name": "Logic",
        "description": "Conditions on signals (a limit, AND, OR), combined verdicts and numbers "
        "turned into verdicts.",
    },
    "custom": {
        "name": "Site blocks",
        "description": "Blocks written on this site, with their Python code and their versions.",
    },
    "output": {
        "name": "Outputs",
        "description": "Where the algorithm's results go: the asset's health, a result on the "
        "asset, a message.",
    },
}

# The signals an asset gives an algorithm, by role: label and what the role carries.
ROLES: dict[str, tuple[str, str]] = {
    "pv": (
        "PV",
        "Process variable: the measurement the loop controls, in its engineering unit.",
    ),
    "sp": ("SP", "Setpoint: the value the loop is asked to hold, in the PV's unit."),
    "op": (
        "OP",
        "Controller output: the command the controller sends to the final element, in percent.",
    ),
    "mode": (
        "Mode",
        "The controller's mode over time (AUTO, MAN, CAS), as the control system records it.",
    ),
    "secondary": (
        "Secondary",
        "Another loop's signal, read to see whether the two loops move together.",
    ),
    "valve_position": (
        "Valve position",
        "The valve's measured position, in percent, when its positioner reports it.",
    ),
    "signal": (
        "Signal",
        "The signal the algorithm runs on, when it runs on signals rather than on assets.",
    ),
    "reference": (
        "Reference",
        "The signal set as this signal's reference (a redundant transmitter), for drift.",
    ),
}
NUMERIC_ROLES = ("pv", "sp", "op", "secondary", "valve_position", "signal", "reference")
TEXT_ROLES = ("mode",)

ROLE_TEXT = (
    "Which signal of the asset to read: pv, sp, op, secondary or valve_position on a loop; "
    "signal (and reference) when the algorithm runs on each signal."
)


def described(
    model: type[BaseModel], texts: dict[str, tuple[str, str]] | None = None, name: str = ""
) -> type[BaseModel]:
    """``model`` with a title and a description on every field, for the editor and the help.

    A field's own title and description win; otherwise ``texts`` then ``PARAMETER_LABELS``
    give them. Constraints and defaults are kept, so the model validates exactly as before.
    """

    texts = texts or {}
    fields: dict[str, Any] = {}
    for key, field in model.model_fields.items():
        title, description = texts.get(key) or PARAMETER_LABELS.get(key) or ("", "")
        updated = FieldInfo.merge_field_infos(
            field,
            title=field.title or title or key.replace("_", " ").capitalize(),
            description=field.description or description or None,
        )
        fields[key] = (field.annotation, updated)
    if not fields:
        return model
    return create_model(name or f"{model.__name__}Described", __base__=model, **fields)


def merged_model(name: str, *models: type[BaseModel]) -> type[BaseModel]:
    """One parameters model holding the fields of ``models`` (their names never clash)."""

    fields: dict[str, Any] = {}
    for model in models:
        for key, field in model.model_fields.items():
            fields[key] = (field.annotation, field)
    return create_model(name, **fields)


class RoleParameters(BaseModel):
    role: str = Field(
        default="pv",
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_]*$",
        title="Role",
        description=ROLE_TEXT,
    )


class StateRole(BaseModel):
    role: str = Field(
        default="mode",
        min_length=1,
        max_length=40,
        pattern=r"^[a-z][a-z0-9_]*$",
        title="Role",
        description="Which text signal of the asset to read; mode on a control loop.",
    )


def grid_series(frame: pd.DataFrame | None, column: str) -> pd.Series | None:
    """One column of a loop's regular frame as a series in time, ``None`` when absent."""

    if frame is None or column not in frame.columns or "timestamp" not in frame.columns:
        return None
    index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], errors="coerce"))
    values = frame[column]
    if column not in TEXT_ROLES:
        values = pd.to_numeric(values, errors="coerce")
    series = pd.Series(values.to_numpy(), index=index, name=column)
    return series[~series.index.isna()]


def clean(series: pd.Series) -> pd.Series:
    """A computed series without the metadata of the one it came from."""

    series = series.copy()
    series.attrs = {}
    return series


def numeric(series: Any) -> pd.Series:
    """A series' values as numbers (text and gaps become NaN)."""

    return pd.to_numeric(series, errors="coerce")


def condition(intervals: Any, index: pd.Index) -> pd.Series:
    """Intervals (a true/false series) on ``index``: false where they say nothing."""

    if not isinstance(intervals, pd.Series):
        return pd.Series(True, index=index)
    found = intervals.reindex(index)
    return found.where(found.notna(), False).astype(bool)


def seconds(index: pd.Index) -> np.ndarray:
    """Each sample's time in seconds from the first one."""

    if isinstance(index, pd.DatetimeIndex) and len(index):
        return np.asarray((index - index[0]).total_seconds(), dtype=float)
    return np.arange(len(index), dtype=float)


def within(series: Any, when: Any) -> pd.Series:
    """The numeric values of a series inside optional intervals, without gaps."""

    x = numeric(series)
    return x[condition(when, x.index)].dropna()


def shipped(block_id: str, inputs: dict[str, Any], params: Any, ctx: Any) -> dict[str, Any]:  # noqa: ANN401
    """Run a block Link ships from a site block's code (a copy starts by calling the original).

    ``params`` are the site block's parameters (a copy keeps the original's); those the original
    does not know are left out.
    """

    from linkcraft.blocks.catalog import BUILTIN_IDS, CATALOG

    if block_id not in BUILTIN_IDS:
        raise ValueError(f"{block_id} is not a block Link ships")
    block = CATALOG[block_id]
    values = getattr(params, "_values", None)
    given = dict(values) if isinstance(values, dict) else dict(params or {})
    # An optional parameter left empty (no value, "null" in the file) takes the original's default.
    known = {
        key: value
        for key, value in given.items()
        if key in block.spec.parameters.model_fields and value not in (None, "", "null")
    }
    return block.run(dict(inputs), block.spec.parameters.model_validate(known), ctx)


__all__ = [
    "LIBRARIES",
    "NUMERIC_ROLES",
    "ROLES",
    "TEXT_ROLES",
    "RoleParameters",
    "StateRole",
    "clean",
    "condition",
    "described",
    "grid_series",
    "merged_model",
    "numeric",
    "seconds",
    "shipped",
    "within",
]
