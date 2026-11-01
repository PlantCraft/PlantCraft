"""Equipment: the performance of common process equipment from its measurements.

- ``equipment.heat_exchanger``: duty and UA (overall coefficient times area) from the four
  terminal temperatures and one side's flow, by the log-mean temperature difference; its fall
  against the clean UA is fouling.
- ``equipment.pump``: a pump's efficiency from its flow, differential pressure and power, and how
  far it sits below the manufacturer's efficiency curve.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, NoData, inport, outport
from pydantic import BaseModel, Field, field_validator

from linkcraft.blocks.base import clean, numeric
from linkcraft.i18n import t

LIBRARY = "equipment"
INCROPERA = (
    "Bergman, T. L., Lavine, A. S., Incropera, F. P., DeWitt, D. P. (2011). Fundamentals of Heat "
    "and Mass Transfer, 7th ed. Wiley. Chapter 11: the log mean temperature difference method."
)
KERN = "Kern, D. Q. (1950). Process Heat Transfer. McGraw-Hill: fouling and dirt factors."
ISO_9906 = (
    "ISO 9906:2012. Rotodynamic pumps: hydraulic performance acceptance tests, grades 1, 2 and 3."
)
KARASSIK = (
    "Karassik, I. J., Messina, J. P., Cooper, P., Heald, C. C. (2008). Pump Handbook, 4th ed. "
    "McGraw-Hill: pump power and efficiency."
)


class HeatExchanger(BaseModel):
    duty_side: Literal["cold", "hot"] = Field(
        default="cold",
        title="Duty from",
        description="The side whose flow is measured: its flow and temperature change give the "
        "duty.",
    )
    cp: float = Field(
        default=4.18,
        gt=0,
        le=100,
        title="Specific heat",
        description="Specific heat of that side's fluid (4.18 for water, about 2 for oils).",
        json_schema_extra={"unit": "kJ/(kg·K)"},
    )
    arrangement: Literal["counter", "parallel"] = Field(
        default="counter",
        title="Flow arrangement",
        description="Counter-current (most shell-and-tube and plate exchangers) or co-current.",
    )
    clean_ua: float = Field(
        default=0.0,
        ge=0,
        title="Clean UA",
        description="UA of the clean exchanger (design or after cleaning); 0: not compared.",
        json_schema_extra={"unit": "kW/K"},
    )


def _lmtd(dt1: pd.Series, dt2: pd.Series) -> pd.Series:
    valid = (dt1 > 0) & (dt2 > 0)
    with np.errstate(all="ignore"):
        ratio = dt1 / dt2
        log_mean = (dt1 - dt2) / np.log(ratio)
    # Equal differences: the log mean is the difference itself.
    near = (ratio - 1.0).abs() < 1e-6
    return log_mean.where(~near, dt1).where(valid)


def _heat_exchanger(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    hot_in, hot_out = numeric(inputs["hot_in"]), numeric(inputs["hot_out"])
    cold_in, cold_out = numeric(inputs["cold_in"]), numeric(inputs["cold_out"])
    flow = numeric(inputs["flow"])
    change = (cold_out - cold_in) if parameters.duty_side == "cold" else (hot_in - hot_out)
    duty = flow * parameters.cp * change
    if parameters.arrangement == "counter":
        dt1, dt2 = hot_in - cold_out, hot_out - cold_in
    else:
        dt1, dt2 = hot_in - cold_in, hot_out - cold_out
    ua = (duty / _lmtd(dt1, dt2)).where(duty > 0).replace([np.inf, -np.inf], np.nan)
    found = ua.dropna()
    if found.empty:
        reason = NoData(
            t("No sample where both temperature differences and the duty are positive.")
        )
        return {"ua": clean(ua), "duty": clean(duty), "mean_ua": reason, "ratio": reason}
    mean = float(found.mean())
    ratio = 100.0 * mean / parameters.clean_ua if parameters.clean_ua > 0 else None
    return {
        "ua": clean(ua),
        "duty": clean(duty),
        "mean_ua": mean,
        "ratio": ratio if ratio is not None else NoData(t("No clean UA given.")),
    }


class Pump(BaseModel):
    curve: list[list[float]] = Field(
        default=[[0.0, 0.0], [50.0, 60.0], [100.0, 75.0], [150.0, 65.0]],
        min_length=2,
        max_length=50,
        title="Efficiency curve",
        description="The manufacturer's best efficiency curve as [flow m³/h, efficiency %] "
        "points, flows increasing.",
    )
    min_flow: float = Field(
        default=0.0,
        ge=0,
        title="Judged from flow",
        description="Below this flow (m³/h) the pump is not judged: at shut-off efficiency means "
        "little.",
        json_schema_extra={"unit": "m³/h"},
    )

    @field_validator("curve")
    @classmethod
    def _curve(cls, value: list[list[float]]) -> list[list[float]]:
        if any(len(point) != 2 for point in value):
            raise ValueError(t("Each point is [flow, efficiency]."))
        flows = [point[0] for point in value]
        if any(later <= earlier for earlier, later in zip(flows, flows[1:], strict=False)):
            raise ValueError(t("The flows increase from one point to the next."))
        if any(not 0 <= point[1] <= 100 for point in value):
            raise ValueError(t("Efficiencies are between 0 and 100 %."))
        return value


def _pump(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    flow = numeric(inputs["flow"])
    dp = numeric(inputs["dp"])
    power = numeric(inputs["power"])
    # Hydraulic power in kW: Q [m³/s] · Δp [Pa] / 1000 = Q [m³/h] / 3600 · Δp [bar] · 100.
    hydraulic = flow / 3600.0 * dp * 100.0
    with np.errstate(all="ignore"):
        efficiency = (100.0 * hydraulic / power).where(power > 0)
    efficiency = efficiency.where(flow >= max(parameters.min_flow, 1e-9))
    efficiency = efficiency.replace([np.inf, -np.inf], np.nan)
    flows, curve = zip(*parameters.curve, strict=True)
    expected = pd.Series(np.interp(flow, flows, curve), index=flow.index).where(efficiency.notna())
    gap = expected - efficiency
    found = gap.dropna()
    mean = float(found.mean()) if not found.empty else NoData(t("No sample to judge."))
    return {"efficiency": clean(efficiency), "gap": clean(gap), "mean_gap": mean}


BLOCKS = (
    Block(
        BlockSpec(
            "equipment.heat_exchanger",
            "1.0",
            LIBRARY,
            "Heat exchanger UA",
            BlockDocs(
                summary="A heat exchanger's duty and UA from its temperatures and one flow, to "
                "follow fouling.",
                description=(
                    "Computes the duty from one side's mass flow, specific heat and temperature "
                    "change, and divides it by the log mean temperature difference of the four "
                    "terminal temperatures: the UA, the exchanger's ability to transfer heat. "
                    "Fouling lowers UA over weeks; against the clean UA, the ratio says how much "
                    "of the clean performance is left."
                ),
                reading="UA in kW/K (higher is better), the duty in kW and the share of the clean "
                "UA in %.",
                formula="Q = ṁ·cp·ΔT_side; LMTD = (ΔT1 − ΔT2) / ln(ΔT1/ΔT2); UA = Q / LMTD",
                assumptions=(
                    "Steady state, no phase change and no heat lost to the surroundings.",
                    "Pure counter- or co-current flow (a multi-pass exchanger needs its F factor; "
                    "the trend is still right).",
                ),
                limitations=(
                    "Samples where a temperature difference is not positive (a temperature "
                    "cross, a stopped side) give no UA.",
                ),
                references=(INCROPERA, KERN),
            ),
            inputs=(
                inport("hot_in", "series", "Hot in", "Hot side inlet temperature.", unit="°C"),
                inport("hot_out", "series", "Hot out", "Hot side outlet temperature.", unit="°C"),
                inport("cold_in", "series", "Cold in", "Cold side inlet temperature.", unit="°C"),
                inport(
                    "cold_out", "series", "Cold out", "Cold side outlet temperature.", unit="°C"
                ),
                inport(
                    "flow",
                    "series",
                    "Flow",
                    "Mass flow of the duty side (Engineering unit converts t/h).",
                    unit="kg/s",
                ),
            ),
            outputs=(
                outport("ua", "series", "UA", "UA at each sample.", unit="kW/K", record=True),
                outport("duty", "series", "Duty", "Heat duty at each sample.", unit="kW"),
                outport(
                    "mean_ua",
                    "number",
                    "Mean UA",
                    "Mean UA over the window.",
                    unit="kW/K",
                    better="higher",
                ),
                outport(
                    "ratio",
                    "number",
                    "Share of clean UA",
                    "Mean UA as a share of the clean UA.",
                    unit="%",
                    low=0,
                    better="higher",
                ),
            ),
            parameters=HeatExchanger,
            group="Heat transfer",
        ),
        _heat_exchanger,
    ),
    Block(
        BlockSpec(
            "equipment.pump",
            "1.0",
            LIBRARY,
            "Pump efficiency",
            BlockDocs(
                summary="A pump's efficiency from flow, differential pressure and power, against "
                "its curve.",
                description=(
                    "Computes the hydraulic power from the flow and the differential pressure "
                    "and divides it by the power drawn: the overall (wire-to-water) efficiency. "
                    "The manufacturer's curve gives the efficiency expected at each flow; the gap "
                    "between them grows as the impeller and wear rings wear, so it says when an "
                    "overhaul pays."
                ),
                reading="Efficiency in %; the gap in percentage points below the curve (0: as new, "
                "lower is better).",
                formula="P_h = Q·Δp; η = P_h / P_electric · 100; gap = η_curve(Q) − η",
                assumptions=(
                    "The power is what the motor draws, so η includes the motor; use a curve of "
                    "the same kind, or the shaft power for the pump alone.",
                ),
                limitations=(
                    "Near shut-off flow the efficiency is small and noisy: set Judged from flow.",
                ),
                references=(ISO_9906, KARASSIK),
            ),
            inputs=(
                inport("flow", "series", "Flow", "Volume flow through the pump.", unit="m³/h"),
                inport(
                    "dp",
                    "series",
                    "Differential pressure",
                    "Discharge minus suction pressure.",
                    unit="bar",
                ),
                inport("power", "series", "Power", "Power drawn by the motor.", unit="kW"),
            ),
            outputs=(
                outport(
                    "efficiency",
                    "series",
                    "Efficiency",
                    "Efficiency at each sample.",
                    unit="%",
                    record=True,
                ),
                outport(
                    "gap",
                    "series",
                    "Below the curve",
                    "Curve minus measured efficiency.",
                    unit="%",
                ),
                outport(
                    "mean_gap",
                    "number",
                    "Mean gap",
                    "Mean gap below the curve over the window.",
                    unit="%",
                    better="lower",
                ),
            ),
            parameters=Pump,
            group="Rotating equipment",
        ),
        _pump,
    ),
)

__all__ = ["BLOCKS"]
