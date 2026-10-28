"""Screening for possible valve stiction from routine PV and OP data.

The screen looks for the movement a sticky valve makes, as the two-parameter stiction model of
Choudhury, Thornhill and Shah (2005) describes it: the valve stays stuck while the command moves
inside the stick band, then slips in one jump. Two signatures in the OP, while the PV oscillates
(autocorrelation peak, Thornhill and Hagglund 1997), raise the score:

* sticking: the share of sample-to-sample moves below ``movement_epsilon`` (a stuck valve);
* stick-slip: the share of moves of at least ``jump_threshold`` that come right after a stuck
  sample. A jump counts only when the valve was stuck before it: an output that moves by a large
  step at every sample (a loop cycling from aggressive tuning, a noisy controller) is continuous
  movement, not stick-slip.

Spans where the OP sits at a limit (``lower_limit``/``upper_limit`` with ``margin``, the same
rule as ``op_saturation_fraction``) are left out before screening: a valve held against its stop
is flat because the controller is saturated, not because it sticks, and stiction cannot be seen
there. Jelali and Huang (2010) list saturation among the conditions to rule out before a stiction
test. When the whole window is saturated the screen returns ``not_applicable`` and says why.

This is a screening of the OP pattern only. The published shape tests (Horch's PV-OP cross-
correlation, the PV-OP ellipse or the bicoherence test of Choudhury et al. 2006) are not
implemented; see ``docs/gaps.md`` (G28).
"""

from __future__ import annotations

import numpy as np
from plantcraft_sdk.methods import (
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    MethodStatus,
    OutputPort,
)
from plantcraft_sdk.methods.findings import fmt_percent as _pct
from plantcraft_sdk.methods.utils import (
    autocorrelation_peak,
    insufficient_data,
    missing_columns,
    numeric_frame,
    result,
    status_from_score,
)
from pydantic import BaseModel, Field

from linkcraft.methods.references import (
    CHOUDHURY_2006_STICTION,
    CHOUDHURY_THORNHILL_SHAH_2005_STICTION_MODEL,
    JELALI_HUANG_2010_STICTION_BOOK,
    THORNHILL_HAGGLUND_1997_OSCILLATION,
)


class StictionInput(BaseModel):
    dataset: LoopDataset


class StictionParameters(BaseModel):
    movement_epsilon: float = Field(default=0.05, ge=0.0)
    jump_threshold: float = Field(default=0.50, gt=0.0)
    min_autocorrelation: float = Field(default=0.30, ge=0.0, le=1.0)
    min_lag_samples: int = Field(default=3, ge=1)
    jump_fraction_reference: float = Field(default=0.10, gt=0.0)
    lower_limit: float = 0.0
    upper_limit: float = 100.0
    margin: float = Field(default=1.0, ge=0.0)


METHOD_METADATA = MethodMetadata(
    method_id="stiction_screening",
    name="Possible valve stiction screening",
    description="Signs of a sticky valve: output that sticks, then jumps, while the PV cycles.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[
        CHOUDHURY_THORNHILL_SHAH_2005_STICTION_MODEL,
        CHOUDHURY_2006_STICTION,
        JELALI_HUANG_2010_STICTION_BOOK,
        THORNHILL_HAGGLUND_1997_OSCILLATION,
    ],
    required_signals=["pv", "op"],
    implemented_formula=(
        "Leave out OP moves touching a saturated sample (op<=lower+margin or op>=upper-margin); "
        "flat = share of |dOP|<=movement_epsilon; slip = share of |dOP|>=jump_threshold right "
        "after a flat move; score = 100*min(1, pv_peak/min_autocorrelation)"
        "*(0.5*flat + 0.5*min(1, slip/jump_fraction_reference))."
    ),
    assumptions=["The OP represents the valve command and routine data are representative."],
    limitations=[
        "This is a simplified screening, not a full reproduction of the "
        "bicoherence or ellipse methods of Choudhury et al.",
        "It reads the stick-slip in the OP signal, so it suits an OP that shows the valve's "
        "movement; a smooth controller output of a sticky valve is not recognised.",
        "Valve position feedback improves the diagnosis but is not "
        "required by this screening block.",
    ],
)

METHOD_SPEC = MethodBlockSpec(
    method_id=METHOD_METADATA.method_id,
    version=METHOD_METADATA.version,
    input_ports=[
        InputPort(
            port_id="pv", semantic_type="process_variable", dtype="timeseries_float", required=True
        ),
        InputPort(
            port_id="op",
            semantic_type="controller_output",
            dtype="timeseries_float",
            required=True,
            unit="percent",
        ),
        InputPort(
            port_id="valve_position",
            semantic_type="valve_position",
            dtype="timeseries_float",
            required=False,
            unit="percent",
        ),
    ],
    input_schema=StictionInput,
    parameter_schema=StictionParameters,
    output_ports=[
        OutputPort(port_id="stiction_score", semantic_type="score", dtype="float"),
        OutputPort(port_id="op_flat_fraction", semantic_type="fraction", dtype="float"),
        OutputPort(port_id="op_jump_fraction", semantic_type="fraction", dtype="float"),
    ],
    output_schema=MethodResult,
    metadata=METHOD_METADATA,
)
from linkcraft.i18n import t


def run(input_data: StictionInput, parameters: StictionParameters) -> MethodResult:
    dataset = input_data.dataset
    missing = missing_columns(dataset, ["pv", "op"])
    if missing:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("PV and OP are required for stiction screening."),
            missing,
        )

    frame = numeric_frame(dataset, ["pv", "op"])
    if len(frame) < parameters.min_lag_samples + 3:
        return insufficient_data(
            METHOD_METADATA,
            dataset.loop_id,
            t("PV and OP need more aligned numeric samples for stiction screening."),
        )

    pv = frame["pv"].to_numpy(dtype=float)
    op = frame["op"].to_numpy(dtype=float)
    saturated = (op <= parameters.lower_limit + parameters.margin) | (
        op >= parameters.upper_limit - parameters.margin
    )
    # A move is screened only when both of its samples are off the limits.
    usable = ~(saturated[1:] | saturated[:-1])
    moves = np.abs(np.diff(op))
    if moves.size == 0:
        return insufficient_data(
            METHOD_METADATA, dataset.loop_id, t("OP needs at least two valid samples.")
        )
    saturated_fraction = float(np.mean(saturated))
    screened = int(usable.sum())
    stuck = moves <= parameters.movement_epsilon
    jumps = moves >= parameters.jump_threshold
    # Stick-slip: a jump right after a move where the valve did not move.
    slips = np.zeros_like(jumps)
    slips[1:] = jumps[1:] & stuck[:-1] & usable[:-1]
    if screened:
        flat_fraction = float(np.mean(stuck[usable]))
        jump_fraction = float(np.mean(jumps[usable]))
        slip_fraction = float(np.mean(slips[usable]))
    else:
        flat_fraction = jump_fraction = slip_fraction = 0.0
    peak, lag = autocorrelation_peak(pv, min_lag=parameters.min_lag_samples)
    oscillation_factor = (
        min(1.0, max(0.0, peak) / parameters.min_autocorrelation)
        if parameters.min_autocorrelation > 0
        else 0.0
    )
    slip_factor = min(1.0, slip_fraction / parameters.jump_fraction_reference)
    op_pattern_factor = 0.50 * flat_fraction + 0.50 * slip_factor
    # Too few moves off the limits to read a pattern: stiction cannot be judged here.
    screenable = screened >= 3
    score = 100.0 * oscillation_factor * op_pattern_factor if screenable else 0.0
    status = status_from_score(score) if screenable else MethodStatus.NOT_APPLICABLE

    return result(
        metadata=METHOD_METADATA,
        loop_id=dataset.loop_id,
        status=status,
        score=score,
        message=(
            t("Possible valve stiction screening completed.")
            if screenable
            else t("Stiction not screened: the output sat at its limit.")
        ),
        metrics={
            "op_flat_fraction": flat_fraction,
            "op_jump_fraction": jump_fraction,
            "op_slip_fraction": slip_fraction,
            "op_saturated_fraction": saturated_fraction,
            "screened_moves": screened,
            "pv_autocorrelation_peak": peak,
            "pv_lag_samples": lag,
            "op_pattern_factor": op_pattern_factor,
            "stiction_screening_score": float(score),
            "valid_samples": int(len(frame)),
        },
        limitations=[
            t(
                "Use as a screening indicator; confirm with a valve test, position "
                "feedback or a full stiction method before a maintenance action."
            )
        ],
    )


def describe(metrics: dict) -> str:
    saturated = metrics.get("op_saturated_fraction")
    if metrics.get("screened_moves") is not None and int(metrics.get("screened_moves") or 0) < 3:
        return t(
            "Stiction not screened: the output sat at its limit for {saturated} of the window, where "
            "a valve cannot show stiction (see the saturation finding).",
            saturated=_pct(saturated),
        )
    slips = metrics.get("op_slip_fraction")
    facts = t(
        "output stuck in {flat} of the samples and jumping right after sticking in {slips}",
        flat=_pct(metrics.get("op_flat_fraction")),
        slips=_pct(slips if slips is not None else metrics.get("op_jump_fraction")),
    )
    if saturated:
        facts = t(
            "{facts}; {saturated} of the window at an output limit left out",
            facts=facts,
            saturated=_pct(saturated),
        )
    if float(metrics.get("stiction_screening_score") or 0) < 25:
        return t("No clear valve stiction signature ({facts}).", facts=facts)
    peak = float(metrics.get("pv_autocorrelation_peak") or 0)
    if peak >= 0.3:
        return t(
            "Possible valve stiction: {facts}, with the PV oscillating. This is a screening; "
            "confirm in the field.",
            facts=facts,
        )
    return t(
        "Possible valve stiction: {facts}; the PV repeats only weakly (autocorrelation {peak}). "
        "This is a screening; confirm in the field.",
        facts=facts,
        peak=f"{peak:.2f}",
    )
