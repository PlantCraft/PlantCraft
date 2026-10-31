"""A8: a loop's run recorded as its reference, and later runs shown against it."""

from __future__ import annotations

from linkcraft.engine.references import compare
from tests.conftest import client_for


def test_a_loop_compares_its_last_run_with_the_recorded_reference(analysed, fake):
    with client_for(analysed, fake) as client:
        before = client.get("/link/api/loops/fic-101").json()
        assert before["reference"] is None
        recorded = client.post("/link/api/loops/fic-101/reference")
        assert recorded.status_code == 200, recorded.text
        body = recorded.json()
        assert body["recorded_by"] == "engineer" and body["source_end"]
        # Right after recording, now and the reference are the same run.
        assert body["methods"]
        assert all(item["score_change"] in (0, 0.0, None) for item in body["methods"])
        for item in body["methods"]:
            assert all(value["index"] in (1.0, None) for value in item["indicators"].values())
        detail = client.get("/link/api/loops/fic-101").json()
        assert detail["reference"]["recorded_at"] == body["recorded_at"]
        assert client.delete("/link/api/loops/fic-101/reference").status_code == 204
        assert client.get("/link/api/loops/fic-101").json()["reference"] is None
        assert client.delete("/link/api/loops/fic-101/reference").status_code == 404
    with client_for(analysed, fake, "operator") as viewer:
        assert viewer.post("/link/api/loops/fic-101/reference").status_code == 403


def test_a_loop_without_a_run_has_nothing_to_record(runtime, fake):
    runtime.sync_loops()
    with client_for(runtime, fake) as client:
        assert client.post("/link/api/loops/fic-101/reference").status_code == 409


def test_compare_reads_scores_and_indicators_against_the_reference():
    reference = {
        "recorded_at": "2026-10-31T12:00:00Z",
        "health": 0.9,
        "algorithm_version": 3,
        "results": [
            {"method_id": "harris", "status": "ok", "score": 10.0, "metrics": {"index": 0.2}},
            {"method_id": "travel", "status": "ok", "score": 5.0, "metrics": {"reversals": 40}},
            {"method_id": "gone", "status": "ok", "score": 1.0, "metrics": {}},
        ],
    }
    now = [
        {"method_id": "harris", "status": "warning", "score": 40.0, "metrics": {"index": 0.5}},
        {"method_id": "travel", "status": "ok", "score": 6.0, "metrics": {"reversals": 44, "x": 1}},
        {"method_id": "new", "status": "ok", "score": 0.0, "metrics": {}},
        {"method_id": "gone", "status": "insufficient_data", "score": None, "metrics": {}},
    ]
    found = compare(reference, now, 0.7, algorithm_version=4)
    assert [item["method_id"] for item in found["methods"]] == ["harris", "travel"]
    harris = found["methods"][0]
    assert harris["score_change"] == 30.0 and harris["status_now"] == "warning"
    assert harris["indicators"]["index"] == {"reference": 0.2, "now": 0.5, "index": 2.5}
    assert found["methods"][1]["indicators"] == {
        "reversals": {"reference": 40.0, "now": 44.0, "index": 1.1}
    }
    assert found["health_change"] == -0.2 and found["version_changed"] is True
    assert compare(None, now, 0.7) is None
