"""Likely causes ranked from the findings (gap G1): the rule table, the loop page and the PDF."""

from __future__ import annotations

from linkcraft.report.causes import CAUSES, likely_causes
from linkcraft.report.loop import loop_report_pdf


def _result(method_id, status, finding="x"):
    return {"method_id": method_id, "status": status, "finding": finding}


def test_stiction_with_oscillation_ranks_the_valve_first_and_not_the_tuning():
    causes = likely_causes(
        [
            _result("stiction_screening", "bad", "Stick-slip in 12 moves."),
            _result("oscillation_autocorrelation", "bad", "Period 5 min."),
            _result("error_metrics_basic", "ok"),
        ]
    )
    assert [c["cause_id"] for c in causes] == ["stiction"]
    assert [e["method_id"] for e in causes[0]["evidence"]] == [
        "stiction_screening",
        "oscillation_autocorrelation",
    ]
    assert "valve" in causes[0]["action"]


def test_an_oscillation_alone_points_to_tuning_and_one_shared_with_a_neighbour_to_it():
    alone = likely_causes([_result("oscillation_autocorrelation", "bad")])
    assert [c["cause_id"] for c in alone] == ["aggressive_tuning"]
    shared = likely_causes(
        [
            _result("oscillation_autocorrelation", "bad"),
            _result("interaction_cross_correlation", "warning"),
        ]
    )
    # The neighbour comes first; tuning stays possible, weakened by the shared oscillation.
    assert [c["cause_id"] for c in shared] == ["external_disturbance", "aggressive_tuning"]
    assert shared[0]["strength"] == 3 and shared[1]["strength"] == 1


def test_causes_are_ranked_by_support_and_capped():
    causes = likely_causes(
        [
            _result("op_saturation_fraction", "bad"),
            _result("error_metrics_basic", "bad"),
            _result("manual_mode_fraction", "warning"),
            _result("sensor_noise_ratio", "warning"),
            _result("op_travel_reversal", "warning"),
        ]
    )
    assert [c["cause_id"] for c in causes] == ["saturation", "measurement_noise", "operation"]
    assert causes[0]["strength"] == 4


def test_healthy_or_unjudged_findings_give_no_cause():
    assert likely_causes([_result("stiction_screening", "ok")]) == []
    assert likely_causes([_result("oscillation_autocorrelation", "insufficient_data")]) == []
    assert all(cause.signs for cause in CAUSES)


def test_the_pdf_builds_with_its_causes():
    import pandas as pd

    results = [_result("stiction_screening", "bad", "Stick-slip in 12 moves.")]
    pdf = loop_report_pdf(
        loop={"loop_id": "FIC-1"},
        summary={"health": 40, "status": "bad"},
        results=results,
        frame=pd.DataFrame(),
        source_start=None,
        source_end=None,
    )
    assert pdf.startswith(b"%PDF")
