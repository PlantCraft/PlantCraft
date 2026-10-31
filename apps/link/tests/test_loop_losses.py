"""Loop-hours lost by cause (A13) and each loop's effective control (A7): engine.losses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from linkcraft.db import Database
from linkcraft.engine.losses import LossStore, cause_fractions, effective_control, losses_by

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def _results(manual=0.1, inside=0.8, saturated=0.25, oscillating="ok", coverage=0.9, frozen=0.0):
    return [
        {
            "method_id": "manual_mode_fraction",
            "status": "ok",
            "metrics": {"manual_fraction": manual},
        },
        {
            "method_id": "operating_band_fraction",
            "status": "ok",
            "metrics": {"inside_fraction": inside},
        },
        {
            "method_id": "op_saturation_fraction",
            "status": "warning",
            "metrics": {"saturation_fraction": saturated},
        },
        {"method_id": "oscillation_autocorrelation", "status": oscillating, "metrics": {}},
        {"method_id": "dq_availability", "status": "ok", "metrics": {"coverage_pv": coverage}},
        {"method_id": "dq_value_integrity", "status": "ok", "metrics": {"frozen_fraction": frozen}},
    ]


class Loop:
    def __init__(self, loop_id, area):
        self.loop_id, self.name, self.area = loop_id, loop_id.upper(), area


def test_effective_control_multiplies_the_three_fractions():
    found = effective_control(_results())
    assert (
        found["normal_mode"] == 90.0 and found["in_band"] == 80.0 and found["not_saturated"] == 75.0
    )
    assert found["score"] == 54.0  # 0.9 x 0.8 x 0.75
    # A fraction the algorithm does not measure counts as nothing against the loop.
    only_manual = [
        {"method_id": "manual_mode_fraction", "status": "ok", "metrics": {"manual_fraction": 0.5}}
    ]
    assert effective_control(only_manual)["score"] == 50.0
    assert effective_control([])["score"] is None
    skipped = [
        {
            "method_id": "manual_mode_fraction",
            "status": "insufficient_data",
            "metrics": {"manual_fraction": 1},
        }
    ]
    assert effective_control(skipped)["score"] is None


def test_causes_split_the_window():
    share = cause_fractions(_results(oscillating="bad", coverage=0.95, frozen=0.2))
    assert share == {"manual": 0.1, "saturated": 0.25, "oscillating": 1.0, "bad_signal": 0.2}


def test_rounds_add_only_new_time_and_sum_by_area(tmp_path):
    store = LossStore(Database(tmp_path / "link.db"))
    iso = lambda moment: moment.isoformat()  # noqa: E731
    # Two rounds of a 24 h window, 1 h apart: the second adds 1 h, not 24.
    assert (
        store.record(
            [
                {
                    "loop_id": "fic-1",
                    "start": iso(NOW - timedelta(hours=24)),
                    "end": iso(NOW),
                    "results": _results(),
                },
                {
                    "loop_id": "tic-2",
                    "start": iso(NOW - timedelta(hours=24)),
                    "end": iso(NOW),
                    "results": _results(manual=1.0),
                },
            ]
        )
        == 2
    )
    later = NOW + timedelta(hours=1)
    store.record(
        [
            {
                "loop_id": "fic-1",
                "start": iso(later - timedelta(hours=24)),
                "end": iso(later),
                "results": _results(),
            }
        ]
    )
    totals = store.totals(NOW - timedelta(days=2), later + timedelta(seconds=1))
    assert totals["fic-1"]["seconds"] == 25 * 3600
    assert round(totals["fic-1"]["manual"] / 3600, 6) == 2.5
    loops = {"fic-1": Loop("fic-1", "Reactor"), "tic-2": Loop("tic-2", "Utilities")}
    by_area = losses_by(totals, loops, "area")
    assert [row["key"] for row in by_area] == ["Utilities", "Reactor"]  # most hours lost first
    utilities = by_area[0]
    assert utilities["manual"] == 24.0 and utilities["effective_control"] == 0.0
    reactor = by_area[1]
    assert reactor["watched_h"] == 25.0 and reactor["saturated"] == 6.25
    assert reactor["effective_control"] == 54.0
    by_loop = losses_by(totals, loops, "loop")
    assert {row["key"] for row in by_loop} == {"fic-1", "tic-2"} and by_loop[0][
        "area"
    ] == "Utilities"
    # A period before the rounds has nothing.
    assert store.totals(NOW - timedelta(days=9), NOW - timedelta(days=8)) == {}


def test_the_api_after_a_round(client, analysed):
    answer = client.get("/link/api/loop-losses?days=30&until=2026-10-02T00:00:00Z")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert [item["key"] for item in body["causes"]] == [
        "manual",
        "saturated",
        "oscillating",
        "bad_signal",
    ]
    assert body["rows"] and body["total"]["watched_h"] > 0
    assert sum(row["loops"] for row in body["rows"]) == body["total"]["loops"]
    per_loop = client.get(
        "/link/api/loop-losses?days=30&until=2026-10-02T00:00:00Z&group_by=loop"
    ).json()["rows"]
    assert len(per_loop) == body["total"]["loops"]
    scores = client.get("/link/api/loop-effective-control").json()
    assert scores and all(row["score"] is None or 0 <= row["score"] <= 100 for row in scores)
    measured = [row["score"] for row in scores if row["score"] is not None]
    assert measured == sorted(measured)
    assert client.get("/link/api/loop-losses?group_by=plant").status_code == 422


def test_the_widgets(client, analysed):
    scores = client.get("/link/api/widgets/effective-control").json()
    assert scores["kind"] == "list" and scores["items"]
    assert (
        scores["items"][0]["value"].endswith("%") and "Normal mode" in scores["items"][0]["detail"]
    )
    # The fake plant's rounds are a month old: nothing in the last 7 days.
    losses = client.get("/link/api/widgets/loop-losses").json()
    assert losses["kind"] == "list" and losses["empty"]
