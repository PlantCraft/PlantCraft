"""Models: process models (FMUs) run on the asset's signals, and how far the plant is from them.

Three kinds of block, the library PlantCraft Twin became:

- ``model.fmu_<model id>``: one block per published model (``linkcraft.models.store``). Its
  ports are the FMU's own: a signal per FMU input, the measured value of each FMU output (the
  run starts from it and the residual is taken against it), and per output the prediction and
  the residual (measured minus predicted) over the judged part of the window. Its parameters
  are the FMU's tunable parameters, the step, the judged part and, per output, the FMU
  parameter that sets where the output starts.
- ``model.deviation``: Hotelling's T² of the residuals against a calibration of normal
  operation (``linkcraft.models.stats``): normal, attention, problem or unknown, with the share
  of the deviation each output explains. The calibration is one of its parameters, filled by
  the editor's Calibrate on a period people choose, so the diagram holds everything it judges by.
- ``model.operating``: the parts of the window a signal is inside a band (the unit running),
  outside which the deviation block does not judge.

A model block runs its FMU through ``ctx.extra["models"]`` (a ``ModelRuntime``: the store and
the worker pool); an FMU never runs in the server process.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from plantcraft_sdk.blocks import (
    Block,
    BlockDocs,
    BlockSpec,
    NoData,
    Result,
    inport,
    outport,
)
from pydantic import BaseModel, Field, create_model, model_validator

from linkcraft.i18n import t
from linkcraft.models.pca import PcaModel, judge_pca
from linkcraft.models.regression import Regression
from linkcraft.models.simulate import Simulation, SimulationError
from linkcraft.models.stats import Calibration, judge

LIBRARY = "model"
PREFIX = "model.fmu_"
# Inputs may miss at most this share of the window after holding short gaps.
MAX_INPUT_GAP_SHARE = 0.1
# Gaps held in an input: this many seconds, or three steps if longer.
HOLD_SECONDS = 120.0
# Measured samples averaged for an output's start value, from the first steps of the window.
START_SAMPLES = 3
START_STEPS = 10
# The judged part needs every output measured, and the unit in operation, this share of it.
MIN_MEASURED_SHARE = 0.5
MIN_ACTIVE_SHARE = 0.5
# The judged part of a model's window by default: what a deviation block judges each run.
JUDGED_SECONDS = 600.0


@dataclass
class ModelRuntime:
    """What a model block needs from the app: the published models and the worker pool."""

    store: Any
    pool: Any


def model_block_id(model_id: str) -> str:
    """``plantcrafttwin-loopprocess`` -> ``model.fmu_plantcrafttwin_loopprocess``."""

    return PREFIX + model_id.replace("-", "_")


def _slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not text or not text[0].isalpha():
        text = f"v_{text}" if text else "v"
    return text[:40]


def _unique(name: str, taken: set[str]) -> str:
    candidate, number = name, 2
    while candidate in taken:
        candidate = f"{name}_{number}"
        number += 1
    taken.add(candidate)
    return candidate


@dataclass(frozen=True)
class Layout:
    """How an FMU's variables become a block's ports and parameters."""

    inputs: tuple[tuple[str, dict[str, Any]], ...]  # (port, variable)
    outputs: tuple[tuple[str, dict[str, Any]], ...]  # (port, variable)
    parameters: tuple[tuple[str, dict[str, Any]], ...]  # (field, variable)


def layout_of(info: dict[str, Any]) -> Layout:
    """The ports and parameters of the block of an FMU, from its variables (``fmu.inspect_fmu``)."""

    variables = [item for item in info.get("variables") or [] if item.get("numeric")]
    taken_in: set[str] = set()
    taken_out: set[str] = set()
    taken_fields = {"step_seconds", "judged_seconds"}
    inputs = tuple(
        (_unique(_slug(item["name"]), taken_in), item)
        for item in variables
        if item["causality"] == "input"
    )
    outputs = []
    for item in variables:
        if item["causality"] != "output":
            continue
        port = _unique(_slug(item["name"]), taken_out | taken_in)
        taken_out.add(port)
        taken_in.add(f"{port}_measured")
        taken_out.add(f"{port}_residual")
        taken_fields.add(f"{port}_start")
        outputs.append((port, item))
    parameters = tuple(
        (_unique(f"p_{_slug(item['name'])}", taken_fields), item)
        for item in variables
        if item["causality"] == "parameter"
    )
    return Layout(inputs, tuple(outputs), parameters)


def _start_parameter(output: str, names: list[str]) -> str | None:
    """The FMU parameter that most likely sets where ``output`` starts: ``T`` -> ``T_start``,
    and in a model of several parts ``TIC1104_PV`` -> ``TIC1104.y_start`` or ``TIC1104.PV_start``.
    """

    lowered = {name.lower(): name for name in names}
    candidates = [f"{output}_start", f"{output}0", f"{output}_0", f"start_{output}"]
    if "_" in output:
        head, tail = output.rsplit("_", 1)
        candidates += [f"{head}.{tail}_start", f"{head}.y_start", f"{head}.{tail}0"]
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _parameters_model(model_id: str, info: dict[str, Any], layout: Layout) -> type[BaseModel]:
    step = info.get("step_seconds")
    fields: dict[str, Any] = {
        "step_seconds": (
            float,
            Field(
                default=float(step) if step and 0.1 <= float(step) <= 600 else 5.0,
                ge=0.1,
                le=600,
                title="Step",
                description="The model's time step: it reads its inputs and gives its outputs "
                "once per step.",
                json_schema_extra={"unit": "s"},
            ),
        ),
        "judged_seconds": (
            float,
            Field(
                default=JUDGED_SECONDS,
                ge=10,
                le=86_400,
                title="Judged part",
                description="The last part of the window whose residuals are compared with "
                "the plant; before it the model settles from where the plant was.",
                json_schema_extra={"unit": "s"},
            ),
        ),
    }
    parameter_names = [item["name"] for _field, item in layout.parameters]
    if parameter_names:
        choice: Any = Literal[tuple(parameter_names)]  # type: ignore[valid-type]
        for port, item in layout.outputs:
            fields[f"{port}_start"] = (
                choice | None,
                Field(
                    default=_start_parameter(item["name"], parameter_names),
                    title=f"{item['name']} starts from",
                    description=f"The model parameter set to {item['name']} as measured at the "
                    "start of the window, so every run starts where the plant was. Empty: the "
                    "model's own start value.",
                ),
            )
    for field, item in layout.parameters:
        unit = item.get("unit") or ""
        start = item.get("start")
        fields[field] = (
            float | None,
            Field(
                default=float(start) if start is not None else None,
                title=item["name"],
                description=_described(item, "A parameter of the model"),
                json_schema_extra={"unit": unit} if unit else None,
            ),
        )
    return create_model(f"Model_{model_id.replace('-', '_')}", **fields)


def _utc(stamp: Any) -> pd.Timestamp:
    value = pd.Timestamp(stamp)
    return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")


def make_grid(start: Any, end: Any, step: float) -> pd.DatetimeIndex:
    """``start, start + step, ...`` up to ``end`` (UTC)."""

    first, last = _utc(start), _utc(end)
    count = int(math.floor((last - first).total_seconds() / step + 1e-9)) + 1
    return pd.date_range(first, periods=max(count, 0), freq=pd.Timedelta(seconds=step))


def on_grid(values: Any, grid: pd.DatetimeIndex, step: float) -> pd.Series:
    """A series laid on ``grid``: the nearest sample within three quarters of a step."""

    if not isinstance(values, pd.Series) or values.empty or not len(grid):
        return pd.Series(np.nan, index=grid)
    numbers = pd.to_numeric(values, errors="coerce").astype(float)
    numbers = numbers[np.isfinite(numbers.to_numpy())]
    if numbers.empty:
        return pd.Series(np.nan, index=grid)
    index = pd.DatetimeIndex(numbers.index)
    numbers.index = index.tz_localize("UTC") if index.tz is None else index.tz_convert("UTC")
    numbers = numbers.sort_index()
    numbers = numbers[~numbers.index.duplicated(keep="last")]
    return numbers.reindex(grid, method="nearest", tolerance=pd.Timedelta(seconds=step * 0.75))


def _window(inputs: dict[str, Any], ctx: Any) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    if ctx.start is not None and ctx.end is not None:
        return _utc(ctx.start), _utc(ctx.end)
    found = [value for value in inputs.values() if isinstance(value, pd.Series) and len(value)]
    if not found:
        return None
    return (
        min(_utc(series.index.min()) for series in found),
        max(_utc(series.index.max()) for series in found),
    )


def _model_runner(model_id: str, layout: Layout):  # noqa: ANN202 - a block's run
    def run(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
        def nothing(reason: str) -> dict[str, Any]:
            gone = NoData(reason, ctx.node_id)
            return {
                key: gone for port, _item in layout.outputs for key in (port, f"{port}_residual")
            }

        runtime = ctx.extra.get("models")
        model = runtime.store.get(model_id) if runtime is not None else None
        if model is None:
            return nothing(t("Model {model} is not published in Analytics.", model=model_id))
        window = _window(inputs, ctx)
        step = float(parameters.step_seconds)
        if window is None:
            return nothing(t("No plant data in this window."))
        grid = make_grid(window[0], window[1], step)
        if len(grid) < 2:
            return nothing(t("No plant data in this window."))
        hold = max(1, int(math.ceil(max(HOLD_SECONDS, 3 * step) / step)))
        fed: dict[str, np.ndarray] = {}
        for port, item in layout.inputs:
            given = inputs.get(port)
            if given is None:
                continue  # not wired: the model keeps its own start value
            if isinstance(given, NoData):
                return nothing(given.reason)
            column = on_grid(given, grid, step).ffill(limit=hold).bfill(limit=hold)
            share = float(column.isna().mean())
            if share > MAX_INPUT_GAP_SHARE:
                return nothing(
                    t(
                        "Input {name} has no values for {share}% of the window.",
                        name=item["name"],
                        share=f"{share * 100:.0f}",
                    )
                )
            fed[item["name"]] = column.ffill().bfill().to_numpy(dtype=float)
        measured = {
            port: on_grid(inputs.get(f"{port}_measured"), grid, step)
            for port, _item in layout.outputs
            if isinstance(inputs.get(f"{port}_measured"), pd.Series)
        }
        start_values: dict[str, float] = {}
        for field, item in layout.parameters:
            value = getattr(parameters, field, None)
            if value is not None and math.isfinite(float(value)):
                start_values[item["name"]] = float(value)
        for port, _item in layout.outputs:
            target = getattr(parameters, f"{port}_start", None)
            if not target or port not in measured:
                continue
            head = measured[port].iloc[:START_STEPS].dropna()
            if len(head):
                start_values[target] = float(head.iloc[:START_SAMPLES].mean())
        seconds = (grid - grid[0]).total_seconds().to_numpy(dtype=float)
        job = Simulation(
            fmu=str(runtime.store.runnable(model)),
            times=seconds,
            inputs=fed,
            outputs=[item["name"] for _port, item in layout.outputs],
            start_values=start_values,
            step=step,
        )
        try:
            result = runtime.pool.run(job)
        except SimulationError as exc:
            return nothing(str(exc))
        judged = grid >= grid[-1] - pd.Timedelta(seconds=float(parameters.judged_seconds))
        given: dict[str, Any] = {}
        for port, item in layout.outputs:
            predicted = pd.Series(
                np.asarray(result[item["name"]], dtype=float), index=grid, name=item["name"]
            )
            if not np.isfinite(predicted.to_numpy()).all():
                return nothing(t("The model returned values that are not numbers."))
            given[port] = predicted
            if port in measured:
                residual = (measured[port] - predicted).where(judged)
                residual.name = item["name"]
                given[f"{port}_residual"] = residual
            else:
                absent = inputs.get(f"{port}_measured")
                given[f"{port}_residual"] = (
                    absent
                    if isinstance(absent, NoData)
                    else NoData(
                        t("{name} has no measured value wired.", name=item["name"]), ctx.node_id
                    )
                )
        return given

    return run


def _described(item: dict[str, Any], kind: str) -> str:
    """An FMU variable's description, or what it is when the FMU gives none."""

    text = str(item.get("description") or "").strip().rstrip(".")
    return f"{text} ({item['name']})." if text else f"{kind}: {item['name']}."


def model_block(model: dict[str, Any]) -> Block:
    """The block of one published model.

    Its texts are English source like every block's; the model's own name and descriptions
    are kept as the FMU gives them.
    """

    info = model.get("info") or {}
    layout = layout_of(info)
    name = " ".join(str(model.get("name") or model["model_id"]).split())[:48]
    if len(name) < 3:
        name = f"Model {name}"
    inports = [
        inport(
            port,
            "series",
            item["name"],
            _described(item, "An input of the model")
            + " Not wired: the model keeps its own start value.",
            unit=item.get("unit") or "",
            required=False,
        )
        for port, item in layout.inputs
    ]
    outports = []
    for port, item in layout.outputs:
        unit = item.get("unit") or ""
        inports.append(
            inport(
                f"{port}_measured",
                "series",
                f"{item['name']} measured",
                f"What the plant measures for {item['name']}: the run starts from it and the "
                "residual is taken against it.",
                unit=unit,
                required=False,
            )
        )
        outports.append(
            outport(
                port,
                "series",
                f"{item['name']} predicted",
                _described(item, "An output of the model")
                + " As the model predicts it over the window.",
                unit=unit,
            )
        )
        outports.append(
            outport(
                f"{port}_residual",
                "series",
                f"{item['name']} residual",
                "Measured minus predicted over the judged part of the window: small noise in "
                "normal operation.",
                unit=unit,
            )
        )
    tool = info.get("generation_tool") or ""
    own = str(model.get("description") or info.get("description") or "").strip()
    docs = BlockDocs(
        summary="Runs a published process model (FMU) on the asset's signals.",
        description=(
            (own + "\n\n" if own else "")
            + "The FMU is simulated over the run's window on the signals wired to its inputs, "
            "each output starting where the plant measured it, and gives what it predicts and "
            "the residual against the measurement for every output. It runs in a separate "
            "worker process with a time limit."
        ),
        reading=(
            "Wire each residual to a Deviation (T²) block to judge it. A residual that drifts "
            "away from zero means the plant no longer behaves as the model."
        ),
        assumptions=(
            "The model describes the unit in normal operation.",
            "Inputs are held across short gaps (up to two minutes).",
        ),
        limitations=(
            "Each run starts from the measurement: slow states the plant does not measure start "
            "at the model's own value.",
        ),
        references=tuple(
            item
            for item in (f"FMI {info['fmi_version']}" if info.get("fmi_version") else "", tool)
            if item
        ),
    )
    return Block(
        BlockSpec(
            model_block_id(model["model_id"]),
            "1.0",
            LIBRARY,
            name,
            docs,
            inputs=tuple(inports),
            outputs=tuple(outports),
            parameters=_parameters_model(model["model_id"], info, layout),
            # It receives a missing input to say which one, never to run without it.
            runs_on_missing=True,
            group="Published models",
        ),
        _model_runner(model["model_id"], layout),
    )


# Deviation (T²) ------------------------------------------------------------------------------

SUITE_LEVEL = {"normal": "ok", "attention": "warning", "problem": "bad"}


class Deviation(BaseModel):
    confidence: float = Field(
        default=0.99,
        ge=0.9,
        le=0.9999,
        title="Confidence",
        description="Confidence of the T² limit: 0.99 means 1 sample in 100 is beyond it in "
        "normal operation.",
    )
    share: float = Field(
        default=0.2,
        ge=0.01,
        le=1.0,
        title="Share beyond the limit",
        description="A run deviates when at least this share of its judged samples is beyond "
        "the limit.",
    )
    persistence: int = Field(
        default=3,
        ge=1,
        le=50,
        title="Runs in a row",
        description="Deviating runs in a row before attention becomes a problem.",
    )
    centre: bool = Field(
        default=False,
        title="Centre on the calibration",
        description="Judge residuals around their calibrated mean (off: the model is expected "
        "to be unbiased).",
    )
    calibration: dict[str, Any] | None = Field(
        default=None,
        title="Calibration",
        description="Mean and covariance of the residuals in normal operation, one entry per "
        "residual. Filled by Calibrate in the editor on a period you choose.",
    )

    @model_validator(mode="after")
    def _calibration(self) -> Deviation:
        if self.calibration is not None:
            try:
                Calibration.from_dict(self.calibration)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(t("Use a calibration made by Calibrate.")) from exc
        return self


def residual_frame(items: list[Any]) -> pd.DataFrame:
    """The residual series wired to a deviation block, one column each, named by their output."""

    columns: dict[str, pd.Series] = {}
    for index, item in enumerate(items):
        if not isinstance(item, pd.Series):
            continue
        name = str(item.name or f"residual {index + 1}")
        key, number = name, 2
        while key in columns:
            key, number = f"{name} ({number})", number + 1
        columns[key] = pd.to_numeric(item, errors="coerce").astype(float)
    if not columns:
        return pd.DataFrame()
    frame = pd.concat(columns, axis=1)
    return frame[frame.notna().any(axis=1)]


def unjudgeable(residuals: pd.DataFrame, active: Any = None) -> str | None:
    """Why these residuals cannot be judged (or calibrated on), or None when they can: an
    output measured for less than half of the judged part, or the unit out of operation."""

    seen = residuals.notna().mean()
    for name in residuals.columns:
        if float(seen.get(name, 0.0)) < MIN_MEASURED_SHARE:
            return t("{name} was measured for less than half of the judged time.", name=name)
    if isinstance(active, pd.Series) and len(active):
        inside = active.astype(bool).reindex(residuals.index, method="nearest").fillna(False)
        if float(inside.mean()) < MIN_ACTIVE_SHARE:
            return t("The unit was out of operation (its activity condition was not met).")
    return None


def _level(streak: int, persistence: int) -> str:
    if streak <= 0:
        return "normal"
    return "problem" if streak >= persistence else "attention"


def _deviation(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    state = ctx.state
    residuals = residual_frame(inputs.get("residuals") or [])

    def inactive(reason: str) -> dict[str, Any]:
        state["verdict"] = "inactive"
        missing = NoData(reason, ctx.node_id)
        return {"result": Result.unknown(reason), "t2": missing, "exceed": missing}

    if residuals.empty:
        reasons = [
            item.reason for item in inputs.get("residuals") or [] if isinstance(item, NoData)
        ]
        return inactive(reasons[0] if reasons else t("No residual to judge."))
    names = list(residuals.columns)
    reason = unjudgeable(residuals, inputs.get("active"))
    if reason:
        return inactive(reason)
    if parameters.calibration is None:
        return inactive(
            t("Not calibrated yet: press Calibrate in the editor on a period of normal operation.")
        )
    calibration = Calibration.from_dict(parameters.calibration)
    if calibration.outputs != names:
        return inactive(t("The residuals changed since the calibration: calibrate again."))
    judgement = judge(
        residuals.to_numpy(dtype=float),
        calibration,
        confidence=parameters.confidence,
        centre=parameters.centre,
    )
    deviating = judgement.exceed_share >= parameters.share
    streak = int(state.get("streak") or 0)
    streak = streak + 1 if deviating else 0
    level = _level(streak, parameters.persistence)
    state.update(streak=streak, verdict=level)
    score = round(100.0 * (1.0 - judgement.exceed_share), 1)
    top = max(judgement.contributions.items(), key=lambda pair: pair[1], default=None)
    if level == "normal":
        message = t("The plant follows the model.")
    else:
        message = (
            t("Deviating from the model for {count} run(s).", count=streak)
            if level == "attention"
            else t("Persistent deviation from the model.")
        )
        if top and top[1] > 0:
            message += t(" {name} explains {share}% of it.", name=top[0], share=f"{top[1]:.0f}")
            mean = (judgement.outputs.get(top[0]) or {}).get("mean")
            if mean is not None and math.isfinite(mean):
                message += t(
                    " It measures {value} {direction} the model.",
                    value=f"{abs(mean):.3g}",
                    direction=t("above") if mean > 0 else t("below"),
                )
    t2 = pd.Series(judgement.t2, index=residuals.index, name="T²")
    return {
        "result": Result(
            SUITE_LEVEL[level],
            score,
            message,
            t("Model deviation"),
            {
                "limit": judgement.limit,
                "exceed_share": judgement.exceed_share,
                "contributions": judgement.contributions,
                "outputs": judgement.outputs,
                "streak": streak,
                "level": level,
            },
        ),
        "t2": t2,
        "exceed": round(judgement.exceed_share * 100.0, 1),
    }


DEVIATION = Block(
    BlockSpec(
        "model.deviation",
        "1.0",
        LIBRARY,
        "Deviation (T²)",
        BlockDocs(
            summary="Judges how far the plant is from a model: normal, attention or problem.",
            description=(
                "Takes the residuals of one or more model outputs (measured minus predicted) and "
                "computes Hotelling's T² of every judged sample against the residuals' mean and "
                "covariance in normal operation (the calibration). Beyond its limit the outputs "
                "together are farther from the model than normal operation explains. A run "
                "deviates when enough samples are beyond the limit; a deviation that lasts "
                "for several runs in a row is a problem, a shorter one attention. The share of "
                "the deviation each output explains points at where to look."
            ),
            reading=(
                "Ok: the plant follows the model. Warning (attention): deviating for fewer runs "
                "than the persistence. Bad (problem): a persistent deviation; the sentence names "
                "the output that explains most of it and whether the plant is above or below the "
                "model. Unknown: it could not judge (not calibrated, outputs not measured, the "
                "unit out of operation, the model failed) and says why. The score is the share "
                "of judged samples inside the limit."
            ),
            assumptions=(
                "Residuals in normal operation are noise around a steady mean: calibrate on a "
                "period of normal operation.",
                "The residuals wired are the ones it was calibrated on, in the same order.",
            ),
            limitations=(
                "T² says the outputs left normal operation together; the contributions are the "
                "share of the deviation each output explains, not the probability it failed.",
            ),
            formula="T² = rᵀ S⁻¹ r; limit = χ²(confidence, outputs); contribution_i = r_i (S⁻¹ r)_i",
            references=(
                "Hotelling, H. (1931). The generalization of Student's ratio.",
                "MacGregor, J. F., Kourti, T. (1995). Statistical process control of "
                "multivariate processes.",
                "Westerhuis, J. A. et al. (2000). Generalized contribution plots in multivariate "
                "statistical process monitoring.",
            ),
        ),
        inputs=(
            inport(
                "residuals",
                "series",
                "Residuals",
                "The residuals of the model's outputs, one wire each.",
                multiple=True,
            ),
            inport(
                "active",
                "intervals",
                "In operation",
                "When the unit runs; outside it the block does not judge. Not wired: always.",
                required=False,
            ),
        ),
        outputs=(
            outport(
                "result",
                "result",
                "Verdict",
                "Normal, attention, problem or unknown, with the score and the sentence.",
            ),
            outport("t2", "series", "T²", "Hotelling's T² of every judged sample.", record=False),
            outport(
                "exceed",
                "number",
                "Beyond the limit",
                "Share of the judged samples beyond the T² limit.",
                unit="%",
                low=0,
                high=100,
                better="lower",
            ),
        ),
        parameters=Deviation,
        runs_on_missing=True,
        group="Judge",
    ),
    _deviation,
)


class Band(BaseModel):
    above: float | None = Field(
        default=None,
        title="Above",
        description="The unit runs while the signal is above this value.",
    )
    below: float | None = Field(
        default=None,
        title="Below",
        description="The unit runs while the signal is below this value.",
    )

    @model_validator(mode="after")
    def _band(self) -> Band:
        if self.above is None and self.below is None:
            raise ValueError(t("Give a value it must stay above, below, or both."))
        return self


def _operating(inputs: dict[str, Any], parameters: Any, _ctx: Any) -> dict[str, Any]:
    level = pd.to_numeric(inputs["x"], errors="coerce").ffill()
    inside = level.notna()
    if parameters.above is not None:
        inside &= level > parameters.above
    if parameters.below is not None:
        inside &= level < parameters.below
    inside.name = "in operation"
    return {"intervals": inside}


OPERATING = Block(
    BlockSpec(
        "model.operating",
        "1.0",
        LIBRARY,
        "Unit in operation",
        BlockDocs(
            summary="The parts of the window a signal is inside a band: the unit running.",
            description=(
                "Marks the samples where a signal (a feed flow, a firing rate) is above, below "
                "or between the values given. A model describes the unit while it runs: wire "
                "this to a Deviation block so it does not judge a stopped unit."
            ),
            reading="Nothing to read: the deviation block says when the unit was out of operation.",
        ),
        inputs=(inport("x", "series", "Signal", "The signal that says the unit runs."),),
        outputs=(
            outport(
                "intervals",
                "intervals",
                "In operation",
                "True where the signal is inside the band.",
            ),
        ),
        parameters=Band,
        group="Operation",
    ),
    _operating,
)

# Empirical model (PCA, M4) -------------------------------------------------------------------


class Empirical(BaseModel):
    variance: float = Field(
        default=0.9,
        ge=0.5,
        le=0.99,
        title="Variance kept",
        description="Calibrate keeps the principal components that explain this share of the "
        "signals' variance in normal operation.",
    )
    confidence: float = Field(
        default=0.99,
        ge=0.9,
        le=0.9999,
        title="Confidence",
        description="Confidence of the T² and SPE limits: 0.99 means about 1 sample in 100 is "
        "beyond each in normal operation.",
    )
    share: float = Field(
        default=0.2,
        ge=0.01,
        le=1.0,
        title="Share beyond the limits",
        description="A run deviates when at least this share of its samples is beyond a limit.",
    )
    persistence: int = Field(
        default=3,
        ge=1,
        le=50,
        title="Runs in a row",
        description="Deviating runs in a row before attention becomes a problem.",
    )
    calibration: dict[str, Any] | None = Field(
        default=None,
        title="Calibration",
        description="The principal components of the signals in normal operation. Filled by "
        "Calibrate in the editor on a period you choose.",
    )

    @model_validator(mode="after")
    def _calibration(self) -> Empirical:
        if self.calibration is not None:
            try:
                PcaModel.from_dict(self.calibration)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(t("Use a calibration made by Calibrate.")) from exc
        return self


def _empirical(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    state = ctx.state
    signals = residual_frame(inputs.get("signals") or [])

    def inactive(reason: str) -> dict[str, Any]:
        state["verdict"] = "inactive"
        missing = NoData(reason, ctx.node_id)
        return {"result": Result.unknown(reason), "t2": missing, "spe": missing, "exceed": missing}

    if signals.empty:
        reasons = [item.reason for item in inputs.get("signals") or [] if isinstance(item, NoData)]
        return inactive(reasons[0] if reasons else t("No signal to judge."))
    reason = unjudgeable(signals, inputs.get("active"))
    if reason:
        return inactive(reason)
    if parameters.calibration is None:
        return inactive(
            t("Not calibrated yet: press Calibrate in the editor on a period of normal operation.")
        )
    model = PcaModel.from_dict(parameters.calibration)
    missing = [name for name in model.signals if name not in signals.columns]
    if missing:
        return inactive(t("The signals changed since the calibration: calibrate again."))
    rows = signals[model.signals].ffill().to_numpy(dtype=float)
    judgement = judge_pca(rows, model, confidence=parameters.confidence)
    deviating = judgement.exceed_share >= parameters.share
    streak = int(state.get("streak") or 0)
    streak = streak + 1 if deviating else 0
    level = _level(streak, parameters.persistence)
    state.update(streak=streak, verdict=level)
    score = round(100.0 * (1.0 - judgement.exceed_share), 1)
    top = max(judgement.contributions.items(), key=lambda pair: pair[1], default=None)
    if level == "normal":
        message = t("The signals move together as in normal operation.")
    else:
        message = (
            t("Off normal operation for {count} run(s).", count=streak)
            if level == "attention"
            else t("Persistently off normal operation.")
        )
        message += " " + (
            t("The signals no longer move together as they did.")
            if judgement.spe_share >= 0.5
            else t("The signals move as usual, but farther than normal.")
        )
        if top and top[1] > 0:
            message += t(" {name} explains {share}% of it.", name=top[0], share=f"{top[1]:.0f}")
    t2 = pd.Series(judgement.t2, index=signals.index, name="T²")
    spe = pd.Series(judgement.spe, index=signals.index, name="SPE")
    return {
        "result": Result(
            SUITE_LEVEL[level],
            score,
            message,
            t("Empirical model"),
            {
                "t2_limit": judgement.t2_limit,
                "spe_limit": judgement.spe_limit,
                "exceed_share": judgement.exceed_share,
                "spe_share": judgement.spe_share,
                "contributions": judgement.contributions,
                "components": model.components,
                "streak": streak,
                "level": level,
            },
        ),
        "t2": t2,
        "spe": spe,
        "exceed": round(judgement.exceed_share * 100.0, 1),
    }


EMPIRICAL = Block(
    BlockSpec(
        "model.empirical",
        "1.0",
        LIBRARY,
        "Empirical model (PCA)",
        BlockDocs(
            summary="Judges a unit with no physical model by how its signals moved together in "
            "normal operation.",
            description=(
                "Learns, on a period of normal operation, how the unit's signals move together: "
                "their principal components (PCA). Each run then measures every sample two "
                "ways. T² says how far the plant moved along its normal directions; SPE (Q) says "
                "how far the signals left the way they moved together, which is how most faults "
                "show. A run deviates when enough samples are beyond either limit; a deviation "
                "that lasts several runs in a row is a problem. The share each signal explains "
                "points at where to look."
            ),
            reading=(
                "Ok: the signals move together as in normal operation. Warning (attention): off "
                "normal operation for fewer runs than the persistence. Bad (problem): "
                "persistently off; the sentence says whether the signals stopped moving together "
                "(SPE) or moved farther than normal (T²) and names the signal that explains most "
                "of it. Unknown: not calibrated, a signal not measured or the unit out of "
                "operation. The score is the share of samples inside both limits."
            ),
            assumptions=(
                "The calibration period is normal operation that covers the unit's usual "
                "operating points.",
                "The signals wired are the ones it was calibrated on.",
            ),
            limitations=(
                "An empirical model knows only the operation it saw: a new normal operating point "
                "reads as a deviation until it is calibrated again.",
                "The contributions are the share of the excess each signal explains, not the "
                "probability it failed; a fault often shows first on signals downstream of it.",
            ),
            formula=(
                "z = (x - mean)/std; t = z P; T² = Σ t_a²/λ_a; SPE = ‖z - t Pᵀ‖²; "
                "limits χ²(confidence, k) and g χ²(confidence, h)"
            ),
            references=(
                "Jackson, J. E. (1991). A User's Guide to Principal Components. Wiley.",
                "MacGregor, J. F., Kourti, T. (1995). Statistical process control of "
                "multivariate processes.",
                "Box, G. E. P. (1954). Some theorems on quadratic forms applied in the study of "
                "analysis of variance problems.",
                "Qin, S. J. (2003). Statistical process monitoring: basics and beyond. Journal of "
                "Chemometrics 17, 480-502.",
                "Westerhuis, J. A. et al. (2000). Generalized contribution plots in multivariate "
                "statistical process monitoring.",
            ),
        ),
        inputs=(
            inport(
                "signals",
                "series",
                "Signals",
                "The unit's signals, one wire each.",
                multiple=True,
            ),
            inport(
                "active",
                "intervals",
                "In operation",
                "When the unit runs; outside it the block does not judge. Not wired: always.",
                required=False,
            ),
        ),
        outputs=(
            outport(
                "result",
                "result",
                "Verdict",
                "Normal, attention, problem or unknown, with the score and the sentence.",
            ),
            outport("t2", "series", "T²", "Hotelling's T² of every sample.", record=False),
            outport(
                "spe", "series", "SPE", "Squared prediction error of every sample.", record=False
            ),
            outport(
                "exceed",
                "number",
                "Beyond the limits",
                "Share of the samples beyond the T² or the SPE limit.",
                unit="%",
                low=0,
                high=100,
                better="lower",
            ),
        ),
        parameters=Empirical,
        runs_on_missing=True,
        group="Judge",
    ),
    _empirical,
)


# Regression with a validity range (A4) -------------------------------------------------------


class RegressionParameters(BaseModel):
    method: Literal["ols", "ridge", "pls"] = Field(
        default="ridge",
        title="Method",
        description="OLS: least squares. Ridge: least squares that keeps the coefficients "
        "small, steadier with few samples. PLS: for inputs that move together.",
    )
    alpha: float = Field(
        default=1.0,
        ge=0.0,
        le=1e6,
        title="Ridge strength",
        description="Ridge only: how strongly the coefficients are kept small (on standardised "
        "inputs).",
    )
    components: int = Field(
        default=2,
        ge=1,
        le=20,
        title="PLS components",
        description="PLS only: the directions of the inputs it keeps.",
    )
    margin: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        title="Margin outside the training range",
        description="How far beyond each input's training range still counts as inside, as a "
        "share of that range (0.1: 10% on each side).",
    )
    share: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        title="Share outside before a warning",
        description="The verdict is a warning when the inputs are outside their range for more "
        "than this share of the window.",
    )
    calibration: dict[str, Any] | None = Field(
        default=None,
        title="Calibration",
        description="The coefficients and each input's training range. Filled by Calibrate in "
        "the editor on a period with target samples.",
    )

    @model_validator(mode="after")
    def _calibration(self) -> RegressionParameters:
        if self.calibration is not None:
            try:
                Regression.from_dict(self.calibration)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(t("Use a calibration made by Calibrate.")) from exc
        return self


def _regression(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:
    wired = residual_frame(inputs.get("inputs") or [])

    def inactive(reason: str) -> dict[str, Any]:
        missing = NoData(reason, ctx.node_id)
        return {
            "value": missing,
            "valid": missing,
            "result": Result.unknown(reason),
            "outside": missing,
        }

    if wired.empty:
        return inactive(t("No input to predict from."))
    if parameters.calibration is None:
        return inactive(
            t("Not calibrated yet: press Calibrate in the editor on a period with target samples.")
        )
    model = Regression.from_dict(parameters.calibration)
    if [name for name in model.inputs if name not in wired.columns]:
        return inactive(t("The inputs changed since the calibration: calibrate again."))
    rows = wired[model.inputs].ffill().to_numpy(dtype=float)
    value = pd.Series(model.predict(rows), index=wired.index, name=model.target or "estimate")
    flags = model.outside(rows, parameters.margin)
    out_rows = np.any(flags != 0, axis=1)
    valid = pd.Series(~out_rows, index=wired.index, name="valid")
    share = float(out_rows.mean()) if len(out_rows) else 0.0
    details: dict[str, Any] = {
        "method": model.method,
        "r2": model.r2,
        "rmse": model.rmse,
        "outside_share": share,
        "inputs": {},
    }
    worst = None
    for index, name in enumerate(model.inputs):
        below = float(np.mean(flags[:, index] < 0)) if len(flags) else 0.0
        above = float(np.mean(flags[:, index] > 0)) if len(flags) else 0.0
        details["inputs"][name] = {
            "low": model.low[index],
            "high": model.high[index],
            "below": below,
            "above": above,
        }
        if below + above > 0 and (worst is None or below + above > worst[1] + worst[2]):
            worst = (name, below, above, index)
    target = inputs.get("target")
    if isinstance(target, pd.Series):
        measured = pd.to_numeric(target, errors="coerce").dropna()
        if len(measured):
            at = value.reindex(measured.index, method="nearest")
            error = (measured - at).dropna()
            if len(error):
                details["rmse_now"] = float(np.sqrt(np.mean(error.to_numpy() ** 2)))
                details["target_samples"] = int(len(error))
    if worst is None:
        status, message = "ok", t("Every input stayed inside the range it was trained on.")
    else:
        name, below, above, index = worst
        side = t("below") if below >= above else t("above")
        bound = model.low[index] if below >= above else model.high[index]
        message = t(
            "Outside the training range {share}% of the time: {name} went {side} {bound:.4g}, "
            "so the estimate extrapolates there.",
            share=f"{100 * share:.0f}",
            name=name,
            side=side,
            bound=bound,
        )
        status = "warning" if share > parameters.share else "ok"
    return {
        "value": value,
        "valid": valid,
        "result": Result(
            status, round(100.0 * (1.0 - share), 1), message, t("Regression"), details
        ),
        "outside": round(100.0 * share, 1),
    }


REGRESSION = Block(
    BlockSpec(
        "model.regression",
        "1.0",
        LIBRARY,
        "Regression (OLS, Ridge, PLS)",
        BlockDocs(
            summary="A value the plant only samples (a lab analysis) predicted at every step "
            "by a regression trained once, with the range it is valid in.",
            description=(
                "Calibrate fits the regression on a period: the target's samples (a lab or "
                "analyzer series) against the inputs at those times, by OLS, ridge or PLS. It "
                "keeps the coefficients, the fit (R², RMSE) and each input's range in the "
                "training. Each run predicts at every step and marks where an input left its "
                "range: there the regression extrapolates."
            ),
            reading=(
                "Estimate: the target at every step. Valid: true where every input is inside its "
                "training range. The verdict is a warning when the inputs were outside for more "
                "than the share set, and names the input and the side. When the target is wired "
                "its samples in the window give the error now, against the RMSE of the training."
            ),
            assumptions=(
                "The inputs explain the target the same way as in the training period.",
                "The target's samples are at the times the process was in that state (shift "
                "the lab by its sampling delay before wiring it).",
            ),
            limitations=(
                "Inside the range is necessary, not enough: a combination of inputs never seen "
                "together can still extrapolate.",
                "Linear: a process that bends inside the range is fitted by a straight line.",
            ),
            formula="ŷ = b₀ + Σ bᵢ xᵢ; valid when lowᵢ − m·spanᵢ ≤ xᵢ ≤ highᵢ + m·spanᵢ",
            references=(
                "Hoerl, A. E., Kennard, R. W. (1970). Ridge regression: biased estimation for "
                "nonorthogonal problems. Technometrics 12(1), 55-67.",
                "Wold, S., Sjöström, M., Eriksson, L. (2001). PLS-regression: a basic tool of "
                "chemometrics. Chemometrics and Intelligent Laboratory Systems 58, 109-130.",
                "Kadlec, P., Gabrys, B., Strandt, S. (2009). Data-driven soft sensors in the "
                "process industry. Computers & Chemical Engineering 33(4), 795-814.",
            ),
        ),
        inputs=(
            inport(
                "inputs",
                "series",
                "Inputs",
                "The signals that explain the target, one wire each.",
                multiple=True,
            ),
            inport(
                "target",
                "series",
                "Target",
                "The sampled value it predicts (gaps between samples). Needed to calibrate; "
                "wired at run time it also gives the error now.",
                required=False,
            ),
        ),
        outputs=(
            outport("value", "series", "Estimate", "The target at every step."),
            outport(
                "valid",
                "intervals",
                "Valid",
                "True where every input is inside its training range.",
            ),
            outport(
                "result",
                "result",
                "Verdict",
                "Ok, or a warning when the inputs left their range, with the input named.",
            ),
            outport(
                "outside",
                "number",
                "Outside the range",
                "Share of the window with an input outside its training range.",
                unit="%",
                low=0,
                high=100,
                better="lower",
            ),
        ),
        parameters=RegressionParameters,
        runs_on_missing=True,
        group="Soft sensors",
    ),
    _regression,
)


BLOCKS = (DEVIATION, OPERATING, EMPIRICAL, REGRESSION)

__all__ = [
    "BLOCKS",
    "JUDGED_SECONDS",
    "DEVIATION",
    "LIBRARY",
    "OPERATING",
    "PREFIX",
    "Layout",
    "ModelRuntime",
    "layout_of",
    "make_grid",
    "model_block",
    "model_block_id",
    "on_grid",
    "residual_frame",
    "unjudgeable",
]
