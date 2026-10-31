"""A11: oscillating loops grouped by period, with the likely origin of each group first."""

from __future__ import annotations

from types import SimpleNamespace

from linkcraft.engine.oscillation_groups import group_by_period
from tests.conftest import client_for


def loop_results(period, regularity=2.0, peak=0.6, stiction=False, status="warning"):
    return [
        {
            "method_id": "oscillation_autocorrelation",
            "status": status,
            "metrics": {
                "zero_crossing_period_seconds": period,
                "regularity": regularity,
                "autocorrelation_peak": peak,
            },
        },
        {"method_id": "stiction_screening", "status": "bad" if stiction else "ok", "metrics": {}},
    ]


def test_loops_at_one_period_form_a_group_led_by_the_sticky_valve():
    loops = {
        key: SimpleNamespace(name=key, area=area)
        for key, area in [
            ("a", "U1"),
            ("b", "U1"),
            ("c", "U2"),
            ("d", "U2"),
            ("e", "U3"),
            ("f", "U3"),
        ]
    }
    results = {
        "a": loop_results(300, regularity=3.0, peak=0.9),
        "b": loop_results(320, regularity=1.5, stiction=True),
        "c": loop_results(310, regularity=2.0),
        "d": loop_results(1200),
        "e": loop_results(60, status="ok"),  # not oscillating
        "f": loop_results(1300, regularity=4.0),
        "gone": loop_results(300),  # not a loop anyone sees
    }
    found = group_by_period(results, loops)
    assert found["oscillating"] == 5
    first, second = found["groups"]
    assert [item["loop_id"] for item in first["loops"]] == ["b", "a", "c"]
    assert first["likely_origin"] == "b" and "stiction" in first["why"][0]
    assert first["areas"] == ["U1", "U2"] and first["period_range_seconds"] == [300.0, 320.0]
    assert second["likely_origin"] == "f" and second["loop_count"] == 2
    assert found["alone"] == []


def test_a_period_far_from_the_others_stays_alone():
    loops = {key: SimpleNamespace(name=key, area="") for key in ("a", "b")}
    found = group_by_period({"a": loop_results(100), "b": loop_results(200)}, loops)
    assert found["groups"] == [] and [item["loop_id"] for item in found["alone"]] == ["a", "b"]


def test_the_api_groups_the_last_runs(analysed, fake):
    with client_for(analysed, fake, "operator") as client:
        found = client.get("/link/api/oscillation-groups")
        assert found.status_code == 200, found.text
        body = found.json()
        assert body["oscillating"] >= 1  # lic-102 oscillates in the fake plant
        listed = [item["loop_id"] for group in body["groups"] for item in group["loops"]]
        listed += [item["loop_id"] for item in body["alone"]]
        assert "lic-102" in listed


def test_the_widget_lists_the_shared_oscillations(analysed, fake):
    with client_for(analysed, fake) as client:
        answer = client.get("/link/api/widgets/oscillation-groups")
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert "items" in body or "empty" in body
