"""Typed access to the versioned benchmark catalogs."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class LoopDefinition:
    loop_id: str
    display_name: str
    area_code: str
    area_name: str
    loop_kind: str
    control_structure: str
    controlled_variable: str
    pv_unit: str
    manipulated_variable: str
    primary_scenario: str
    scenario_description: str
    process_purpose: str


@dataclass(frozen=True)
class SignalDefinition:
    signal_id: str
    opcua_node_id: str
    display_name: str
    description: str
    area_code: str
    area_name: str
    equipment_id: str
    equipment_name: str
    scope: str
    loop_id: str | None
    analytical_role: str | None
    data_type: str
    engineering_unit: str
    nominal_cadence_seconds: int
    normal_range: str
    scenario_relevance: str
    context_for_loop_ids: tuple[str, ...]

    @property
    def node_identifier(self) -> str:
        return self.opcua_node_id.split(";s=", 1)[1]


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    layer: str
    display_name: str
    description: str
    injection_pattern: str
    opcua_effect: str
    primary_loop_ids: tuple[str, ...]
    current_analytical_coverage: str
    future_method_or_protocol_need: str


@dataclass(frozen=True)
class Catalog:
    loops: tuple[LoopDefinition, ...]
    signals: tuple[SignalDefinition, ...]
    scenarios: tuple[ScenarioDefinition, ...]

    @property
    def digest(self) -> str:
        payload = {
            "loops": [item.__dict__ for item in self.loops],
            "signals": [item.__dict__ for item in self.signals],
            "scenarios": [item.__dict__ for item in self.scenarios],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        loop_ids = {item.loop_id for item in self.loops}
        scenario_ids = {item.scenario_id for item in self.scenarios}
        signal_ids = {item.signal_id for item in self.signals}
        node_ids = {item.opcua_node_id for item in self.signals}
        if len(self.loops) != 50 or len(loop_ids) != 50:
            errors.append("catalog must contain 50 unique loops")
        if len(self.signals) != 500 or len(signal_ids) != 500 or len(node_ids) != 500:
            errors.append("catalog must contain 500 unique signals and NodeIds")
        if len(self.scenarios) != 20 or len(scenario_ids) != 20:
            errors.append("catalog must contain 20 unique scenarios")
        loop_signals = [item for item in self.signals if item.scope == "control_loop"]
        context_signals = [item for item in self.signals if item.scope == "plant_context"]
        if len(loop_signals) != 250 or len(context_signals) != 250:
            errors.append("signal split must be 250 control-loop and 250 plant-context")
        for loop in self.loops:
            members = [item for item in loop_signals if item.loop_id == loop.loop_id]
            if len(members) != 5:
                errors.append(f"{loop.loop_id} must have exactly five loop signals")
            if loop.primary_scenario not in scenario_ids:
                errors.append(f"{loop.loop_id} references an unknown scenario")
        for signal in self.signals:
            if signal.loop_id and signal.loop_id not in loop_ids:
                errors.append(f"{signal.signal_id} references an unknown loop")
            unknown = set(signal.context_for_loop_ids) - loop_ids
            if unknown:
                errors.append(f"{signal.signal_id} has unknown context loops: {sorted(unknown)}")
        return tuple(errors)


def _rows(name: str, catalog_dir: Path | None) -> Iterable[dict[str, str]]:
    resource = (catalog_dir / name) if catalog_dir else files(__package__).joinpath("catalog", name)
    with resource.open("r", encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def load_catalog(catalog_dir: str | Path | None = None) -> Catalog:
    """Load the immutable catalog shipped in the package or an explicit directory."""

    directory = Path(catalog_dir).resolve() if catalog_dir else None
    loops = tuple(
        LoopDefinition(
            loop_id=row["loop_id"],
            display_name=row["display_name_pt_br"],
            area_code=row["area_code"],
            area_name=row["area_name_pt_br"],
            loop_kind=row["loop_kind"],
            control_structure=row["control_structure"],
            controlled_variable=row["controlled_variable_pt_br"],
            pv_unit=row["pv_unit"],
            manipulated_variable=row["manipulated_variable_pt_br"],
            primary_scenario=row["primary_scenario"],
            scenario_description=row["scenario_description_pt_br"],
            process_purpose=row["process_purpose_pt_br"],
        )
        for row in _rows("loops.csv", directory)
    )
    signals = tuple(
        SignalDefinition(
            signal_id=row["signal_id"],
            opcua_node_id=row["opcua_node_id"],
            display_name=row["display_name_pt_br"],
            description=row["description_pt_br"],
            area_code=row["area_code"],
            area_name=row["area_name_pt_br"],
            equipment_id=row["equipment_id"],
            equipment_name=row["equipment_name_pt_br"],
            scope=row["scope"],
            loop_id=row["loop_id"] or None,
            analytical_role=row["analytical_role"] or None,
            data_type=row["data_type"],
            engineering_unit=row["engineering_unit"],
            nominal_cadence_seconds=int(row["nominal_cadence_seconds"]),
            normal_range=row["normal_range"],
            scenario_relevance=row["scenario_relevance"],
            context_for_loop_ids=tuple(filter(None, row["context_for_loop_ids"].split(";"))),
        )
        for row in _rows("signals.csv", directory)
    )
    scenarios = tuple(
        ScenarioDefinition(
            scenario_id=row["scenario_id"],
            layer=row["layer"],
            display_name=row["display_name_pt_br"],
            description=row["description_pt_br"],
            injection_pattern=row["injection_pattern"],
            opcua_effect=row["opcua_effect"],
            primary_loop_ids=tuple(filter(None, row["primary_loop_ids"].split(";"))),
            current_analytical_coverage=row["current_analytical_coverage"],
            future_method_or_protocol_need=row["future_method_or_protocol_need"],
        )
        for row in _rows("scenarios.csv", directory)
    )
    return Catalog(loops=loops, signals=signals, scenarios=scenarios)
