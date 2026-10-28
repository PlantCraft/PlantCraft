"""A scripted specialist names results in words, never by their ids."""

from __future__ import annotations

from processcraft.specialists.facts import SpecialistFacts, result_kind


def test_a_result_reads_in_words():
    facts = SpecialistFacts(None, ["linkcraft"], {"linkcraft": "PlantCraft Analytics"})
    line = facts.result_line(
        {
            "app": "linkcraft",
            "kind": "loop_health",
            "status": "warning",
            "score": 54.2,
            "summary": "PV–SP mean absolute error of 1.1.",
            "detail": {"limiting_method": "error_metrics_basic"},
        }
    )
    assert (
        line
        == "PlantCraft Analytics · Loop health: attention, 54/100. PV–SP mean absolute error of 1.1."
    )
    assert "error_metrics_basic" not in line


def test_protocol_outputs_lose_their_prefix():
    assert result_kind("out_valve") == "Valve"
    assert result_kind("signal_quality") == "Signal quality"
