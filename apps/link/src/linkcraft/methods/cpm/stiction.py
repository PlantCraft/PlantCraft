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

A sticky valve behind a smooth controller output shows no stuck moves, so the screen also reads
the *shape* of the oscillation, as the curve-fitting test of He et al. (2007): each half cycle of
the OP and of the PV is fitted with a sine and with a triangle. Stiction makes the controller
output of a self-regulating loop (and the PV of an integrating one) triangular, while aggressive
tuning or an outside disturbance keeps both sinusoidal. The shape index is the sine error over the
sum of both errors (above ``shape_index_high`` reads as stiction, 0.5 is undecided); the higher of
the OP and PV indices counts. The score is the larger of the stick-slip and the shape evidence.

Horch's cross-correlation test (1999) reads the phase between OP and PV in a cycling loop: the
ratio of the cross-correlation at lag 0 to its largest value within half a period is reported as
``horch_index`` (near 0 odd, the 90 degree shift of stiction; near 1 even, in or against phase as
tuning or a disturbance make it). It holds only when the OP is the controller's own output, so it
counts only when ``op_is`` says so: then an index of ``horch_even`` or more leaves the shape
evidence out (the stick-slip evidence stays). The default ``op_is="valve_command"`` keeps the
screen as before, because a recorded valve movement cycles in phase with the PV in a sticky loop
too (the simulator's FIC-105).

An OP that is not on the 0-100 scale of ``lower_limit``/``upper_limit`` (a normalised record) is
not checked for saturation. The bicoherence test of Choudhury et al. (2006) is not implemented;
see ``docs/gaps.md`` (G28).
"""

from __future__ import annotations

from typing import Literal

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
    HE_2007_CURVE_FITTING_STICTION,
    HORCH_1999_CROSS_CORRELATION_STICTION,
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
    # Curve-fitting shape test (He et al. 2007): index where a half cycle reads fully triangular.
    shape_index_high: float = Field(default=0.65, gt=0.5, le=1.0)
    min_half_cycles: int = Field(default=4, ge=2)
    # Horch (1999): what the OP records, and the lag-0 cross-correlation ratio that reads as even.
    op_is: Literal["valve_command", "controller_output"] = "valve_command"
    horch_even: float = Field(default=0.8, gt=0.0, le=1.0)


METHOD_METADATA = MethodMetadata(
    method_id="stiction_screening",
    name="Possible valve stiction screening",
    description="Signs of a sticky valve: output that sticks, then jumps, while the PV cycles.",
    maturity=MethodMaturity.ENGINEERING_HEURISTIC,
    references=[
        CHOUDHURY_THORNHILL_SHAH_2005_STICTION_MODEL,
        HE_2007_CURVE_FITTING_STICTION,
        HORCH_1999_CROSS_CORRELATION_STICTION,
        CHOUDHURY_2006_STICTION,
        JELALI_HUANG_2010_STICTION_BOOK,
        THORNHILL_HAGGLUND_1997_OSCILLATION,
    ],
    required_signals=["pv", "op"],
    implemented_formula=(
        "Leave out OP moves touching a saturated sample (op<=lower+margin or op>=upper-margin); "
        "flat = share of |dOP|<=movement_epsilon; slip = share of |dOP|>=jump_threshold right "
        "after a flat move; score = 100*min(1, pv_peak/min_autocorrelation)"
        "*max(0.5*flat + 0.5*min(1, slip/jump_fraction_reference), shape), where shape = "
        "clip((index-0.5)/(shape_index_high-0.5), 0, 1) and index = max over OP and PV of "
        "sine SSE / (sine SSE + triangle SSE) fitted per half cycle (He et al. 2007). "
        "horch = |r(0)| / max |r(tau)| of the OP-PV cross-correlation for |tau| <= period/2 "
        "(Horch 1999); with op_is = controller_output, horch >= horch_even sets shape to 0."
    ),
    assumptions=["The OP represents the valve command and routine data are representative."],
    limitations=[
        "This is a simplified screening, not a full reproduction of the "
        "bicoherence or ellipse methods of Choudhury et al.",
        "The stick-slip part needs an OP that shows the valve's movement; the shape part needs "
        "a sustained oscillation of at least a few cycles in the window.",
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
    on_scale = (
        float(np.nanmin(op)) >= parameters.lower_limit - parameters.margin
        and float(np.nanmax(op)) <= parameters.upper_limit + parameters.margin
    )
    # A normalised OP (negative values, or above the top of the scale) has no known limits.
    saturated = (
        (op <= parameters.lower_limit + parameters.margin)
        | (op >= parameters.upper_limit - parameters.margin)
        if on_scale
        else np.zeros(op.shape, dtype=bool)
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
    # The shape of a cycle means something only when the PV clearly cycles.
    cycling = bool(lag) and peak >= parameters.min_autocorrelation
    op_shape = shape_index(op, lag, parameters.min_half_cycles) if cycling else None
    pv_shape = shape_index(pv, lag, parameters.min_half_cycles) if cycling else None
    shapes = [value for value in (op_shape, pv_shape) if value is not None]
    index = max(shapes) if shapes else None
    shape_factor = (
        min(1.0, max(0.0, (index - 0.5) / (parameters.shape_index_high - 0.5)))
        if index is not None
        else 0.0
    )
    horch = horch_index(op, pv, lag) if cycling else None
    # An even cross-correlation of the controller's output and the PV: tuning or a disturbance.
    in_phase = (
        parameters.op_is == "controller_output"
        and horch is not None
        and horch >= parameters.horch_even
    )
    if in_phase:
        shape_factor = 0.0
    # Too few moves off the limits to read a pattern: stiction cannot be judged here.
    screenable = screened >= 3
    evidence = max(op_pattern_factor, shape_factor)
    score = 100.0 * oscillation_factor * evidence if screenable else 0.0
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
            "op_shape_index": op_shape,
            "pv_shape_index": pv_shape,
            "shape_factor": shape_factor,
            "horch_index": horch,
            "horch_in_phase": in_phase,
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


def horch_index(op: np.ndarray, pv: np.ndarray, period: int) -> float | None:
    """Horch (1999): |r(0)| / max |r(tau)| of the OP-PV cross-correlation over lags within half
    a ``period``. Near 0 the cross-correlation is odd (stiction behind a controller output), near
    1 even (tuning or a disturbance). None without a period or a moving OP and PV."""

    keep = np.isfinite(op) & np.isfinite(pv)
    x, y = op[keep], pv[keep]
    half = max(1, int(period) // 2)
    if period < 4 or x.size < 2 * period:
        return None
    x, y = x - x.mean(), y - y.mean()
    scale = float(np.sqrt(np.sum(x * x) * np.sum(y * y)))
    if scale <= 0:
        return None
    n = x.size
    values = [
        float(np.sum(x[max(0, -lag) : n - max(0, lag)] * y[max(0, lag) : n - max(0, -lag)]))
        for lag in range(-half, half + 1)
    ]
    largest = max(abs(value) for value in values)
    return abs(values[half]) / largest if largest > 0 else None


def _half_cycle_errors(segment: np.ndarray) -> tuple[float, float]:
    """Sum of squared errors of the best sine half wave and the best triangle (peak anywhere)
    through the zero crossings at both ends of ``segment``."""

    if segment.size > 64:  # the shape, not the samples: 64 points are plenty
        segment = np.interp(np.linspace(0, segment.size - 1, 64), np.arange(segment.size), segment)
    n = segment.size
    k = np.arange(n, dtype=float)
    span = float(n - 1)
    sine = np.sin(np.pi * k / span)
    amplitude = float(sine @ segment) / float(sine @ sine)
    sine_error = float(np.sum((segment - amplitude * sine) ** 2))
    best = np.inf
    for peak in range(1, n - 1):
        tri = np.where(k <= peak, k / peak, (span - k) / (span - peak))
        height = float(tri @ segment) / float(tri @ tri)
        best = min(best, float(np.sum((segment - height * tri) ** 2)))
    return sine_error, best


def shape_index(
    values: np.ndarray, period: int, min_half_cycles: int = 4, max_spread: float = 0.5
) -> float | None:
    """He et al. (2007): sine error / (sine + triangle error) summed over the half cycles of
    ``values`` (a signal oscillating with ``period`` samples). Near 1 triangular (stiction), near 0
    sinusoidal, 0.5 undecided; None with too few half cycles, or half cycles whose lengths spread
    more than ``max_spread`` of their mean (no regular oscillation)."""

    if period < 8:
        return None
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 2 * period:
        return None
    # Smooth over a tenth of the period so noise makes no extra zero crossings, then centre on a
    # running mean over one period (a slow drift would shift the crossings).
    width = max(1, period // 10)
    smooth = np.convolve(x, np.ones(width) / width, mode="same")
    level = np.convolve(x, np.ones(period) / period, mode="same")
    centred = smooth - level
    edge = period // 2
    centred = centred[edge : centred.size - edge]
    signs = np.sign(centred)
    crossings = np.flatnonzero(signs[1:] * signs[:-1] < 0) + 1
    lengths = np.diff(crossings)
    # A limit cycle repeats: half cycles of about one length (SACAC's stiction runs spread up to
    # 0.45 of their mean, sampled at an uneven rate; a healthy level riding disturbances 0.73). A wandering signal (a healthy
    # loop riding disturbances) crosses at random, and its half cycles look triangular too.
    if lengths.size < min_half_cycles or float(np.std(lengths)) > max_spread * float(
        np.mean(lengths)
    ):
        return None
    sine_total = tri_total = 0.0
    halves = 0
    for start, end in zip(crossings[:-1], crossings[1:], strict=False):
        length = end - start + 1
        # A half cycle near half the period: shorter ones are noise, longer ones a pause.
        if not 0.25 * period <= length <= 1.0 * period:
            continue
        segment = centred[start : end + 1]
        segment = segment - np.linspace(segment[0], segment[-1], length)
        sine_error, tri_error = _half_cycle_errors(np.abs(segment))
        sine_total += sine_error
        tri_total += tri_error
        halves += 1
    if halves < min_half_cycles or sine_total + tri_total <= 0:
        return None
    return sine_total / (sine_total + tri_total)


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
    shapes = [
        v for v in (metrics.get("op_shape_index"), metrics.get("pv_shape_index")) if v is not None
    ]
    if shapes and float(metrics.get("shape_factor") or 0) > float(
        metrics.get("op_pattern_factor") or 0
    ):
        facts = t(
            "{facts}; the oscillation cycles in triangles (shape index {index}, 1 is a triangle, "
            "0 a sine)",
            facts=facts,
            index=f"{max(shapes):.2f}",
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
