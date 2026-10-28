"""Analysis defaults per loop type (docs/loop-types.md)."""

from __future__ import annotations

from linkcraft.blocks.algorithms import BY_ID
from linkcraft.catalog.loop_types import (
    ALGORITHM_OF_PROTOCOL,
    LOOP_TYPE_DEFAULTS,
    algorithm_id,
    default_profile,
    known_criticality,
    type_parameters,
)
from linkcraft.catalog.registry import METHOD_SPECS


def test_every_loop_type_starts_with_a_shipped_algorithm():
    for loop_type, defaults in LOOP_TYPE_DEFAULTS.items():
        assert defaults["profile_id"] in BY_ID, loop_type
        assert default_profile(loop_type.upper()) == defaults["profile_id"]
    assert default_profile("steam") == "flow_loop" and type_parameters(None) == {}


def test_every_old_protocol_id_names_a_shipped_algorithm():
    # Loops, schedules and runs saved by 0.2 keep working: their protocol id is read as this.
    for old, new in ALGORITHM_OF_PROTOCOL.items():
        assert new in BY_ID and algorithm_id(old) == new
    assert algorithm_id(None) == "flow_loop" and algorithm_id("mine") == "mine"


def test_loop_type_parameters_are_valid_method_parameters():
    for loop_type, defaults in LOOP_TYPE_DEFAULTS.items():
        for method_id, values in defaults["parameters"].items():
            METHOD_SPECS[method_id].parameter_schema.model_validate(values)
        assert type_parameters(loop_type) is not defaults["parameters"]


def test_criticality_values():
    assert known_criticality(" High ") == "high"
    assert known_criticality("extreme") is None and known_criticality(None) is None


def test_the_table_is_documented():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "docs" / "loop-types.md").read_text()
    for loop_type, defaults in LOOP_TYPE_DEFAULTS.items():
        assert f"| `{loop_type}` |" in text and f"`{defaults['profile_id']}`" in text
