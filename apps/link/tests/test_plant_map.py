"""A6: the plant map, each loop's KPI values and bands for the heat map and the treemap."""

from __future__ import annotations

from types import SimpleNamespace

from linkcraft.engine.plant_map import band, plant_map
from linkcraft.loops.analysis import CRITICALITY_WEIGHTS
from tests.conftest import client_for


def test_bands_read_every_kpi_on_one_scale():
    assert [band(v) for v in (None, 95, 90, 80, 60, 10)] == [
        "none",
        "good",
        "good",
        "fair",
        "poor",
        "bad",
    ]


def test_each_loop_carries_its_kpis_weight_and_area():
    loops = {
        "b": SimpleNamespace(name="FIC B", area="U2", metadata={"criticality": "critical"}),
        "a": SimpleNamespace(name="FIC A", area="", metadata={}),
    }
    summaries = {"b": {"health": 42.04, "status": "bad"}}
    results = {
        "b": [
            {
                "method_id": "manual_mode_fraction",
                "status": "ok",
                "metrics": {"manual_fraction": 0.1},
            },
            {
                "method_id": "operating_band_fraction",
                "status": "ok",
                "metrics": {"inside_fraction": 0.5},
            },
        ]
    }
    found = plant_map(loops, summaries, results, CRITICALITY_WEIGHTS)
    assert [kpi["key"] for kpi in found["kpis"]][:2] == ["health", "effective_control"]
    first, second = found["loops"]
    assert first["loop_id"] == "b" and second["loop_id"] == "a"  # no area last
    assert first["weight"] == 2.0 and second["weight"] == 1.0
    assert first["values"]["health"] == 42.0 and first["bands"]["health"] == "bad"
    assert first["values"]["effective_control"] == 45.0
    assert first["values"]["not_saturated"] is None and first["bands"]["not_saturated"] == "none"
    assert second["values"]["health"] is None


def test_the_api_maps_the_analysed_loops(analysed, fake):
    with client_for(analysed, fake, "operator") as client:
        answer = client.get("/link/api/plant-map")
        assert answer.status_code == 200, answer.text
        body = answer.json()
        ids = {row["loop_id"] for row in body["loops"]}
        assert "lic-102" in ids
        row = next(row for row in body["loops"] if row["loop_id"] == "lic-102")
        assert row["values"]["health"] is not None and row["bands"]["health"] in {
            "good",
            "fair",
            "poor",
            "bad",
        }
