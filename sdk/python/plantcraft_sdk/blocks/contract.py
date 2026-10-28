"""The block contract: typed ports, parameters and the descriptions people and assistants read.

A block is one calculation with declared inputs and outputs. Every port has a type, so a
diagram can be checked before it runs:

=============  ===========================================================================
``series``     numeric values in time (a ``pandas.Series`` on a time index), with a unit
``state``      text or discrete values in time (a mode such as AUTO/MAN)
``number``     one value per run (a ``float``), with a unit and a range
``result``     a judgement: status, score from 0 to 100 (100 is best) and one sentence
``intervals``  parts of the window (a boolean ``pandas.Series``, ``True`` inside)
=============  ===========================================================================

Wires join an output to an input of the same type. The one conversion made on the wire is
``result`` to ``number`` (the score). An input may accept several types (a data quality check
reads any signal) and, when ``multiple``, any number of wires (a "worst of" block).

The texts of a block (``BlockDocs``, each port's and each parameter's description) are English
source text served through ``plantcraft_sdk.i18n.t``; ``plantcraft_sdk.blocks.docs`` holds
them to one format and renders them for people and for the suite's assistants.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict

PortType = Literal["series", "state", "number", "result", "intervals"]
PORT_TYPES: tuple[str, ...] = ("series", "state", "number", "result", "intervals")
# What each type carries, as the editor and the assistants explain it.
TYPE_DESCRIPTIONS: dict[str, str] = {
    "series": "Numeric values in time, with a unit.",
    "state": "Text or discrete values in time, such as a controller mode.",
    "number": "One value per run, with a unit.",
    "result": "A judgement: a status, a score from 0 to 100 (100 is best) and one sentence.",
    "intervals": "Parts of the window, such as the time a loop spent in manual.",
}
# Conversions made on the wire: (from, to).
COERCIONS: frozenset[tuple[str, str]] = frozenset({("result", "number")})
STATUSES = ("ok", "warning", "bad", "unknown")
SEVERITY = {"unknown": -1, "ok": 0, "warning": 1, "bad": 2}
ID = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
BLOCK_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")


def accepts(types: tuple[str, ...], source: str) -> bool:
    """Whether an input of ``types`` takes a wire carrying ``source``."""

    return source in types or any((source, item) in COERCIONS for item in types)


@dataclass(frozen=True)
class Port:
    """One input or output of a block.

    ``types`` lists what an input accepts (an output has exactly one). ``required`` inputs must
    be wired; a ``multiple`` input takes any number of wires and receives a list. An output with
    ``record`` is written to the historian by default (people may switch it per diagram);
    ``better`` says which way is good for a number (``higher`` or ``lower``).
    """

    port_id: str
    types: tuple[str, ...]
    label: str
    description: str
    unit: str = ""
    required: bool = True
    multiple: bool = False
    record: bool = False
    low: float | None = None
    high: float | None = None
    better: Literal["higher", "lower"] | None = None

    @property
    def type(self) -> str:
        return self.types[0]


def inport(
    port_id: str,
    types: str | tuple[str, ...],
    label: str,
    description: str,
    *,
    unit: str = "",
    required: bool = True,
    multiple: bool = False,
) -> Port:
    return Port(
        port_id,
        (types,) if isinstance(types, str) else tuple(types),
        label,
        description,
        unit=unit,
        required=required,
        multiple=multiple,
    )


def outport(
    port_id: str,
    type_: str,
    label: str,
    description: str,
    *,
    unit: str = "",
    record: bool = False,
    low: float | None = None,
    high: float | None = None,
    better: Literal["higher", "lower"] | None = None,
) -> Port:
    return Port(
        port_id,
        (type_,),
        label,
        description,
        unit=unit,
        required=False,
        record=record,
        low=low,
        high=high,
        better=better,
    )


class BlockDocs(BaseModel):
    """What a block is, in the one format every block of the suite follows.

    - ``summary``: one sentence: what it measures and when to use it.
    - ``description``: how it works, in a few sentences, without the formula.
    - ``reading``: what ok, warning and bad mean, with the limits that decide them.
    - ``assumptions`` and ``limitations``: short lists.
    - ``formula`` (plain text) and ``references`` (citations), when the block has them.
    """

    model_config = ConfigDict(frozen=True)

    summary: str
    description: str
    reading: str
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    formula: str = ""
    references: tuple[str, ...] = ()


class NoParameters(BaseModel):
    """A block without parameters."""


@dataclass(frozen=True)
class BlockSpec:
    """The contract of a block: identity, docs, ports and parameters.

    ``block_id`` is dotted (``cpm.stiction``), its first part the library. ``runs_on_missing``
    blocks still run when an input carries ``NoData`` (they receive it and decide, like a
    "worst of" or an output); other blocks pass ``NoData`` on to every output.
    """

    block_id: str
    version: str
    library: str
    name: str
    docs: BlockDocs
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    parameters: type[BaseModel] = NoParameters
    runs_on_missing: bool = False
    # Shown in the palette: a short category inside the library ("Filters", "Valve").
    group: str = ""
    # Its picture (round 9 M2): a checked data URL (``plantcraft_sdk.images``), "" for none.
    image: str = ""

    def input(self, port_id: str) -> Port | None:
        return next((port for port in self.inputs if port.port_id == port_id), None)

    def output(self, port_id: str) -> Port | None:
        return next((port for port in self.outputs if port.port_id == port_id), None)


@dataclass
class Result:
    """A judgement a block gives (the ``result`` type).

    ``value`` is a score from 0 to 100 where 100 is best, ``None`` when the block could not
    judge (``unknown``). ``detail`` carries what the block found (metrics, the method's own
    result) for the blocks and pages that read more than the score.
    """

    status: str
    value: float | None
    message: str
    label: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            self.status = "unknown"
        if self.value is not None:
            try:
                number = float(self.value)
            except (TypeError, ValueError):
                number = float("nan")
            self.value = None if number != number else round(min(100.0, max(0.0, number)), 1)
        self.message = str(self.message or "")

    @classmethod
    def unknown(cls, message: str, label: str = "") -> Result:
        return cls("unknown", None, message, label)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "value": self.value,
            "message": self.message,
            "label": self.label,
        }


@dataclass(frozen=True)
class NoData:
    """Travels on a wire instead of a value a block could not give, with the reason."""

    reason: str
    where: str = ""

    def __bool__(self) -> bool:
        return False


@dataclass
class Context:
    """What a block knows besides its inputs: the window, the asset and its own state.

    ``state`` is the block's own memory between runs (one dict per node, kept by the app);
    ``extra`` holds what an app hands its own blocks (raw samples, verdicts, settings).
    """

    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    sample_seconds: float | None = None
    asset: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    states: dict[str, dict[str, Any]] = field(default_factory=dict)
    node_id: str = ""

    @property
    def state(self) -> dict[str, Any]:
        return self.states.setdefault(self.node_id, {})


Run = Callable[[dict[str, Any], BaseModel, Context], dict[str, Any]]


@dataclass(frozen=True)
class Block:
    """A block: its contract and the function that computes its outputs from its inputs."""

    spec: BlockSpec
    run: Run


def parameter_unit(model: type[BaseModel], name: str) -> str:
    """The ``unit`` a parameter declares with ``Field(json_schema_extra={"unit": "s"})``."""

    extra = model.model_fields[name].json_schema_extra
    return str(extra.get("unit", "")) if isinstance(extra, dict) else ""


__all__ = [
    "BLOCK_ID",
    "COERCIONS",
    "ID",
    "PORT_TYPES",
    "SEVERITY",
    "STATUSES",
    "TYPE_DESCRIPTIONS",
    "Block",
    "BlockDocs",
    "BlockSpec",
    "Context",
    "NoData",
    "NoParameters",
    "Port",
    "PortType",
    "Result",
    "Run",
    "accepts",
    "inport",
    "outport",
    "parameter_unit",
]
