"""Inputs: the asset's signals and the verdicts other algorithms already gave on them."""

from __future__ import annotations

from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, NoData, Result, outport
from pydantic import Field

from linkcraft.blocks.base import TEXT_ROLES, RoleParameters, StateRole, grid_series
from linkcraft.i18n import t

# A Signal quality verdict -> a block status.
VERDICT_STATUS = {"good": "ok", "suspect": "warning", "bad": "bad"}


def _absent(role: str) -> NoData:
    return NoData(t("The asset has no {role} signal.", role=role.upper()))


def _recorded(raw: Any, role: str) -> pd.Series | None:
    if not isinstance(raw, pd.DataFrame) or role not in raw.columns:
        return None
    values = raw[role].dropna()
    if role not in TEXT_ROLES:
        values = pd.to_numeric(values, errors="coerce").dropna()
    series = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(values.index), name=role)
    series.attrs["recorded"] = True
    return series


class SignalParameters(RoleParameters):
    asset: str = Field(
        default="",
        max_length=200,
        title="Of the asset",
        description="Read the role of another asset (its id in PlantCraft), such as a loop of "
        "the unit the algorithm runs on. Empty: the algorithm's own asset.",
    )
    signal: str = Field(
        default="",
        max_length=300,
        title="Signal id",
        description="Read this signal (its id in PlantCraft) whatever the asset's roles say. "
        "Empty: the signal in the role.",
    )


def _named(parameters: Any, ctx: Any) -> dict[str, Any] | None:
    """A signal an asset run read for this node (another asset's role, or a signal by id)."""

    named = ctx.extra.get("named")
    if named is not None and ctx.node_id in named:
        value = named[ctx.node_id]
        return {"value": value, "recorded": value}
    if getattr(parameters, "asset", "") or getattr(parameters, "signal", ""):
        missing = NoData(
            t(
                "A signal of another asset or by id is read only when the algorithm runs on an asset."
            )
        )
        return {"value": missing, "recorded": missing}
    return None


def _signal(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    named = _named(parameters, ctx)
    if named is not None:
        return named
    role = parameters.role
    roles = ctx.extra.get("roles")
    if roles is not None and role not in roles:
        missing = _absent(role)
        return {"value": missing, "recorded": missing}
    recorded = _recorded(ctx.extra.get("raw"), role)
    value = grid_series(ctx.extra.get("frame"), role)
    if value is None:
        # An algorithm on one signal has no grid: it reads the samples as recorded.
        value = recorded.copy() if recorded is not None else None
        if value is not None:
            value.attrs = {}
    return {
        "value": value if value is not None else _absent(role),
        "recorded": recorded if recorded is not None else _absent(role),
    }


def _verdict(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    found = (ctx.extra.get("verdicts") or {}).get(parameters.role)
    label = parameters.role.upper()
    if not found:
        return {
            "result": Result.unknown(t("The Signal quality algorithm has no recent result."), label)
        }
    return {
        "result": Result(
            VERDICT_STATUS.get(str(found.get("status")), "unknown"),
            found.get("quality"),
            str(found.get("message") or ""),
            label,
            {"verdict": found},
        )
    }


VALUE_TEXT = (
    "The signal on the algorithm's regular time grid (one value per step, held or "
    "interpolated between samples): what the analysis blocks read."
)
RECORDED_TEXT = (
    "The signal's samples exactly as recorded, at their own times: what data quality checks "
    "read to find gaps, freezes and spikes."
)

SIGNAL = Block(
    BlockSpec(
        "input.signal",
        "1.0",
        "input",
        "Signal",
        BlockDocs(
            summary="Reads one numeric signal of the asset the algorithm runs on, by its role.",
            description=(
                "Gives the signal PlantCraft records for the chosen role (PV, SP, OP, a "
                "secondary signal) over the run's window, twice: on the algorithm's regular "
                "time grid for the analysis blocks, and as recorded for the data quality checks. "
                "An asset without a signal in that role gives no value, and the blocks wired to "
                "it say so. On an asset it can also read the role of another asset (a loop of "
                "the unit) or a signal by its id."
            ),
            reading=(
                "Nothing to read: it is the data. A block after it that reports 'the asset has "
                "no SP signal' means the asset record has no signal in that role."
            ),
            assumptions=("The asset record in PlantCraft names its signals by role.",),
        ),
        outputs=(
            outport("value", "series", "On the grid", VALUE_TEXT),
            outport("recorded", "series", "As recorded", RECORDED_TEXT),
        ),
        parameters=SignalParameters,
        group="Signals",
    ),
    _signal,
)

STATE = Block(
    BlockSpec(
        "input.state",
        "1.0",
        "input",
        "State signal",
        BlockDocs(
            summary="Reads one text signal of the asset, such as the controller's mode.",
            description=(
                "Gives the text signal PlantCraft records for the chosen role (mode on a "
                "control loop: AUTO, MAN, CAS) over the run's window, held between changes on "
                "the algorithm's grid and as recorded. An asset without that signal gives no "
                "value; blocks that only use it when present still run."
            ),
            reading="Nothing to read: it is the data the mode blocks read.",
        ),
        outputs=(
            outport("value", "state", "On the grid", VALUE_TEXT),
            outport("recorded", "state", "As recorded", RECORDED_TEXT),
        ),
        parameters=StateRole,
        group="Signals",
    ),
    _signal,
)

VERDICT = Block(
    BlockSpec(
        "input.verdict",
        "1.0",
        "input",
        "Signal quality verdict",
        BlockDocs(
            summary="The latest verdict of the Signal quality algorithm on one of the asset's "
            "signals.",
            description=(
                "Reads what the Signal quality algorithm last said about the signal in the "
                "chosen role: good, suspect or bad, with its quality score and the sentence of "
                "its worst check. It runs nothing itself, so a loop algorithm can act on its "
                "signals' quality without checking them again."
            ),
            reading=(
                "Ok, warning and bad are the verdict's good, suspect and bad; unknown when the "
                "Signal quality algorithm has not judged the signal recently."
            ),
        ),
        outputs=(
            outport(
                "result",
                "result",
                "Verdict",
                "The signal's quality verdict: status, quality from 0 to 100 and its sentence.",
            ),
        ),
        parameters=RoleParameters,
        group="Signals",
    ),
    _verdict,
)

BLOCKS = (SIGNAL, STATE, VERDICT)
