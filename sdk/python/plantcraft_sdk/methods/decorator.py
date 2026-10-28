"""Write a method as one plain Python function.

A method module built by hand declares a ``METHOD_SPEC``, input and parameter
schemas, ``run()`` and ``describe()``. The ``@method`` decorator builds all of
that from a function signature, so an engineer who knows pandas only writes
the calculation::

    from plantcraft_sdk.methods import Finding, method, param

    @method("pv_spread", name="PV spread")
    def pv_spread(pv, *, tolerance: float = param(1.0, gt=0, help="Acceptable deviation")):
        \"\"\"PV standard deviation compared with a tolerance.\"\"\"
        std = float(pv.std())
        return Finding(score=100 * std / tolerance, metrics={"std": std})

Arguments without a default are required signals (``pv``, ``sp``, ``op``,
``mode`` or any column of the loop frame); arguments that default to ``None``
are optional signals. Keyword-only arguments are parameters. Three names are
reserved: ``data`` receives the aligned signals as one DataFrame, ``dataset``
the whole ``LoopDataset`` and ``sample_seconds`` the sampling period.

The function returns a ``Finding`` (or a dict with the same keys) or raises
``NotEnoughData``. The score follows the platform's convention: 0 is healthy,
100 is the worst case, and the status comes from the score unless given.
"""

from __future__ import annotations

import inspect
import string
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, create_model
from pydantic.fields import FieldInfo

from plantcraft_sdk.i18n import t
from plantcraft_sdk.methods.contracts import (
    EvidenceItem,
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodEvent,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    MethodStatus,
    OutputPort,
    ScientificReference,
)
from plantcraft_sdk.methods.findings import fmt_number, fmt_percent
from plantcraft_sdk.methods.utils import (
    estimate_sample_seconds,
    insufficient_data,
    result,
    status_from_score,
)

RESERVED_ARGUMENTS = {"data", "dataset", "sample_seconds"}
# Signals that carry labels (AUTO/MAN), not numbers.
TEXT_SIGNALS = {"mode"}
SIGNAL_TYPES = {
    "pv": ("process_variable", "Process variable"),
    "sp": ("setpoint", "Setpoint"),
    "op": ("controller_output", "Controller output"),
    "mode": ("controller_mode", "Controller mode"),
    "secondary": ("timeseries_signal", "Secondary signal"),
    "valve_position": ("valve_position", "Valve position"),
}


class NotEnoughData(Exception):
    """Raise inside a method when the window cannot answer its question."""


@dataclass
class Finding:
    """What a method found: a 0–100 score (100 is worst) and its numbers."""

    score: float
    metrics: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    status: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)


def param(
    default: Any,
    *,
    help: str = "",
    gt: float | None = None,
    ge: float | None = None,
    lt: float | None = None,
    le: float | None = None,
) -> Any:
    """A method parameter with limits and a description shown in the interface."""

    return Field(default=default, description=help or None, gt=gt, ge=ge, lt=lt, le=le)


class _NumberFormatter(string.Formatter):
    """``{std}`` in the current language's number format, ``{std:.2}`` with two decimals, ``{x:%}`` as percent."""

    def format_field(self, value: Any, format_spec: str) -> str:
        if isinstance(value, bool) or not isinstance(value, (int, float, np.number)):
            return super().format_field("—" if value is None else value, "")
        if format_spec == "%":
            return fmt_percent(value)
        if format_spec.startswith(".") and format_spec[1:].isdigit():
            return fmt_number(value, int(format_spec[1:]))
        return fmt_number(value)


class _Metrics(dict):
    def __missing__(self, key: str) -> None:
        return None


def _describer(template: str | Callable[[dict], str] | None) -> Callable[[dict], str] | None:
    if template is None or callable(template):
        return template
    formatter = _NumberFormatter()
    # The template is English; it is translated each time a finding is worded.
    return lambda metrics: formatter.vformat(t(template), (), _Metrics(metrics))


def _clean(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


@dataclass
class _Signature:
    required: list[str]
    optional: list[str]
    wants: set[str]
    parameters: dict[str, tuple[Any, Any]]


def _read_signature(function: Callable[..., Any]) -> _Signature:
    required: list[str] = []
    optional: list[str] = []
    wants: set[str] = set()
    parameters: dict[str, tuple[Any, Any]] = {}
    hints = {}
    try:
        hints = inspect.get_annotations(function, eval_str=True)
    except Exception:  # Unresolvable annotations: infer types from defaults.
        hints = {}
    for name, item in inspect.signature(function).parameters.items():
        if item.kind in (item.VAR_POSITIONAL, item.VAR_KEYWORD):
            raise TypeError(f"{function.__name__}: *args and **kwargs are not accepted.")
        if name in RESERVED_ARGUMENTS:
            wants.add(name)
            continue
        if item.kind == item.KEYWORD_ONLY:
            if item.default is item.empty:
                raise TypeError(f"Parameter {name!r} needs a default value.")
            default = item.default
            base = default.default if isinstance(default, FieldInfo) else default
            annotation = hints.get(name, type(base) if base is not None else Any)
            parameters[name] = (annotation, default)
        elif item.default is item.empty:
            required.append(name)
        elif item.default is None:
            optional.append(name)
        else:
            raise TypeError(
                f"Signal {name!r}: use None as its default (optional) or declare it "
                "after * as a parameter."
            )
    return _Signature(required, optional, wants, parameters)


def _series(frame: pd.DataFrame, name: str) -> pd.Series:
    if name in TEXT_SIGNALS:
        return frame[name].astype("string").str.strip()
    values = pd.to_numeric(frame[name], errors="coerce")
    return values.replace([np.inf, -np.inf], np.nan)


class MethodBlock:
    """A method built from a function; quacks like a hand-written method module."""

    def __init__(
        self,
        function: Callable[..., Any],
        *,
        method_id: str,
        name: str,
        application: str,
        version: str,
        maturity: MethodMaturity,
        references: list[ScientificReference],
        assumptions: list[str],
        limitations: list[str],
        formula: str | None,
        min_samples: int,
        describe: str | Callable[[dict], str] | None,
    ):
        self.function = function
        self.application = application
        self.min_samples = min_samples
        self.__name__ = function.__name__
        self.__doc__ = function.__doc__
        self.__module__ = function.__module__
        self.signature = _read_signature(function)
        doc = inspect.getdoc(function) or ""
        self.metadata = MethodMetadata(
            method_id=method_id,
            name=name,
            version=version,
            description=doc.split("\n\n", 1)[0].replace("\n", " ").strip(),
            maturity=maturity,
            references=references,
            assumptions=assumptions,
            limitations=limitations,
            required_signals=list(self.signature.required),
            implemented_formula=formula,
        )
        fields = {
            key: (annotation, default)
            for key, (annotation, default) in self.signature.parameters.items()
        }
        stem = "".join(part.title() for part in method_id.split("_"))
        self.input_schema = create_model(
            f"{stem}Input",
            __config__=ConfigDict(arbitrary_types_allowed=True),
            dataset=(LoopDataset, ...),
        )
        self.parameter_schema = create_model(f"{stem}Parameters", **fields)
        self.METHOD_SPEC = MethodBlockSpec(
            method_id=method_id,
            version=version,
            input_ports=[
                InputPort(
                    port_id=signal,
                    semantic_type=SIGNAL_TYPES.get(signal, ("timeseries_signal", ""))[0],
                    dtype="timeseries_string" if signal in TEXT_SIGNALS else "timeseries_float",
                    required=signal in self.signature.required,
                    description=SIGNAL_TYPES.get(signal, ("", signal.upper()))[1],
                )
                for signal in [*self.signature.required, *self.signature.optional]
            ],
            input_schema=self.input_schema,
            parameter_schema=self.parameter_schema,
            output_ports=[OutputPort(port_id="score", semantic_type="score", dtype="float")],
            output_schema=MethodResult,
            metadata=self.metadata,
        )
        self._describe = _describer(describe)
        if self._describe is not None:
            self.describe = self._describe

    @property
    def source_file(self) -> str | None:
        module = sys.modules.get(self.function.__module__)
        return getattr(module, "__file__", None) or inspect.getsourcefile(self.function)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the plain function, as in a notebook or a unit test."""

        return self.function(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<method {self.metadata.method_id}>"

    def _arguments(self, dataset: LoopDataset, parameters: BaseModel) -> dict[str, Any]:
        frame = dataset.data
        signature = self.signature
        missing = [name for name in signature.required if name not in frame.columns]
        if missing:
            raise _Missing(missing)
        columns = {name: _series(frame, name) for name in signature.required}
        aligned = pd.DataFrame(columns, index=frame.index).dropna()
        if len(aligned) < self.min_samples:
            raise NotEnoughData(
                t(
                    "Only {count} valid samples; the method needs {needed}.",
                    count=len(aligned),
                    needed=self.min_samples,
                )
            )
        arguments: dict[str, Any] = {name: aligned[name] for name in signature.required}
        for name in signature.optional:
            if name in frame.columns:
                values = _series(frame, name).reindex(aligned.index)
                arguments[name] = None if values.isna().all() else values
            else:
                arguments[name] = None
        if "data" in signature.wants:
            extra = {
                name: values
                for name, values in arguments.items()
                if name in signature.optional and values is not None
            }
            arguments["data"] = aligned.assign(**extra)
        if "dataset" in signature.wants:
            arguments["dataset"] = dataset
        if "sample_seconds" in signature.wants:
            arguments["sample_seconds"] = estimate_sample_seconds(dataset)
        arguments.update(parameters.model_dump())
        return arguments

    def run(self, input_data: BaseModel, parameters: BaseModel) -> MethodResult:
        dataset: LoopDataset = input_data.dataset  # type: ignore[attr-defined]
        try:
            output = self.function(**self._arguments(dataset, parameters))
        except _Missing as missing:
            return insufficient_data(
                self.metadata,
                dataset.loop_id,
                t(
                    "Missing signals: {signals}.",
                    signals=", ".join(item.upper() for item in missing.names),
                ),
                missing.names,
            )
        except NotEnoughData as reason:
            return insufficient_data(self.metadata, dataset.loop_id, str(reason))
        return self._result(dataset.loop_id, output)

    def _result(self, loop_id: str, output: Any) -> MethodResult:
        if isinstance(output, dict):
            output = Finding(**output)
        if not isinstance(output, Finding):
            raise TypeError(
                f"{self.metadata.method_id} must return Finding(...) or a dict; "
                f"it returned {type(output).__name__}."
            )
        score = float(output.score) if output.score is not None else 0.0
        status = MethodStatus(output.status) if output.status else status_from_score(score)
        return result(
            metadata=self.metadata,
            loop_id=loop_id,
            status=status,
            score=score,
            message=output.message or t("{name}: analysis complete.", name=t(self.metadata.name)),
            metrics={key: _clean(value) for key, value in output.metrics.items()},
            events=[MethodEvent(**item) for item in output.events],
            evidence=[EvidenceItem(**item) for item in output.evidence],
        )


class _Missing(Exception):
    def __init__(self, names: list[str]):
        super().__init__(", ".join(names))
        self.names = names


def method(
    method_id: str,
    *,
    name: str,
    application: str = "cpm",
    version: str = "0.1.0",
    maturity: str | MethodMaturity = MethodMaturity.EXPERIMENTAL,
    references: list[ScientificReference] | None = None,
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
    formula: str | None = None,
    min_samples: int = 3,
    describe: str | Callable[[dict], str] | None = None,
) -> Callable[[Callable[..., Any]], MethodBlock]:
    """Turn a function into a method the registry, protocols and interface use.

    ``describe`` words the finding for people: a callable ``(metrics) -> str``
    or a template such as ``"Deviation of {std:.2} ({fraction:%} of the window)."``.
    A template is English and goes through ``t()`` when the finding is worded.
    """

    def wrap(function: Callable[..., Any]) -> MethodBlock:
        return MethodBlock(
            function,
            method_id=method_id,
            name=name,
            application=application,
            version=version,
            maturity=MethodMaturity(maturity),
            references=list(references or []),
            assumptions=list(assumptions or []),
            limitations=list(limitations or []),
            formula=formula,
            min_samples=min_samples,
            describe=describe,
        )

    return wrap


__all__ = ["Finding", "MethodBlock", "NotEnoughData", "method", "param"]
