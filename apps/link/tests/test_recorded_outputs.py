"""What each execution of a schedule records (Link round 8, D6, "Recorded outputs").

A schedule on assets lists the ports its algorithm records, one row each: record it or not and
for how long, with what it costs. Each execution writes them under
``app-linkcraft:<asset>.<schedule key>.<output>``: a verdict as its score and its status (two
points), a series whole (a runs point, the last executions); their retention is the schedule's
(``managed_by``). A result asset per asset of the schedule holds those points.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from linkcraft.assets.outputs import (
    SERIES,
    VERDICT,
    checked_choices,
    cost,
    retention,
    role_of,
    runs_per_day,
)
from tests.conftest import client_for
from tests.plant import NOW
from tests.test_asset_algorithms import (  # noqa: F401 (the calibration fixture)
    UNIT,
    _save,
    calibration,
    twin_diagram,
    unit_fake,
    unit_runtime,
)

SCHEDULE = {
    "name": "Revisão do forno",
    "profile_id": "unit-twin",
    "selector": {"mode": "list", "ids": [UNIT]},
    "cadence": "interval",
    "interval_minutes": 15,
}


def _diagram(found: dict) -> dict:
    """The unit twin, its deviation verdict recorded too."""

    diagram = twin_diagram(found)
    for node in diagram["nodes"]:
        if node["id"] == "dev":
            node["record"] = ["result"]
    return diagram


def test_the_cost_and_the_choices_of_one_output():
    series = {"key": "y", "kind": SERIES, "values_per_run": 360}
    assert cost(series, {"runs": 10}, 96) == {
        "values_per_day": 34560.0,
        "stored_values": 3600,
        "stored_bytes": 21600,
        "grows": False,
    }
    verdict = {"key": "health", "kind": VERDICT, "values_per_run": 1}
    forever = cost(verdict, {"forever": True}, 24)
    assert forever["values_per_day"] == 48 and forever["stored_values"] == 48 * 365
    assert forever["grows"] is True
    assert retention({"forever": True}) == {"retention_days": 0}
    assert retention({"days": 400}) == {"retention_days": 400}
    assert retention({"runs": 5}) == {"keep_runs": 5, "keep_days": None}
    assert runs_per_day({"cadence": "interval", "interval_minutes": 15}) == 96
    assert runs_per_day({"cadence": "weekly"}) == pytest.approx(1 / 7)
    taken: set[str] = set()
    assert [role_of(key, taken) for key in ("health.status", "health-status", "3d")] == [
        "health_status",
        "health_status_2",
        "o_3d",
    ]


def test_choices_are_checked_against_the_algorithm(calibration):  # noqa: F811
    config = {"diagram": _diagram(calibration), "timing": {"window_seconds": 1800}}
    assert checked_choices(config, None) == {}
    assert checked_choices(config, {"gone": {"record": True}}) == {}
    with pytest.raises(ValueError, match="derived signal"):
        checked_choices(config, {"plantcrafttwin-loopprocess.y": {"keep": {"forever": True}}})
    with pytest.raises(ValueError, match="runs"):
        checked_choices(config, {"deviation-t": {"keep": {"runs": 3}}})
    assert checked_choices(config, {"deviation-t": {"record": False}}) == {
        "deviation-t": {"record": False}
    }


def test_a_schedule_records_what_it_says_for_as_long_as_it_says(tmp_path, calibration):  # noqa: F811
    fake = unit_fake(bias=1.5, minutes=12)
    runtime = unit_runtime(tmp_path, fake)
    try:
        with client_for(runtime, fake, "admin") as client:
            _save(client, calibration, diagram=_diagram(calibration))
            preview = client.post("/link/api/schedules/preview", json=SCHEDULE).json()
            rows = {row["key"]: row for row in preview["recorded_outputs"]}
            assert set(rows) == {
                "plantcrafttwin-loopprocess.y",
                "plantcrafttwin-loopprocess.y-residual",
                "deviation-t",
            }
            verdict, residual = rows["deviation-t"], rows["plantcrafttwin-loopprocess.y-residual"]
            # The defaults: the verdict forever, a series its last 10 executions.
            assert (verdict["kind"], verdict["keep"], verdict["unit"]) == (
                "verdict",
                {"forever": True},
                "/100",
            )
            assert residual["kind"] == "series" and residual["keep"] == {"runs": 10}
            assert residual["values_per_run"] == 360 and residual["values_per_day"] == 360 * 96
            choices = {
                "plantcrafttwin-loopprocess.y": {"record": False},
                "plantcrafttwin-loopprocess.y-residual": {"keep": {"runs": 3}},
                "deviation-t": {"keep": {"days": 30}},
            }
            refused = client.post(
                "/link/api/schedules",
                json={**SCHEDULE, "outputs": {"deviation-t": {"keep": {"runs": 3}}}},
            )
            assert refused.status_code == 422
            made = client.post("/link/api/schedules", json={**SCHEDULE, "outputs": choices})
            assert made.status_code == 201, made.text
            schedule = made.json()
            assert schedule["output_key"] == "revisao-do-forno"
            detail = client.get(f"/link/api/schedules/{schedule['schedule_id']}").json()
            kept = {row["key"]: (row["record"], row["keep"]) for row in detail["recorded_outputs"]}
            assert kept["plantcrafttwin-loopprocess.y"][0] is False
            assert kept["deviation-t"] == (True, {"days": 30})

            # The schedule's result asset under the furnace holds its three points.
            [result] = [item for item in fake.assets if item["kind"] == "result"]
            base = f"app-linkcraft:{UNIT}.revisao-do-forno"
            assert result["id"] == f"linkcraft.{UNIT}.revisao-do-forno"
            assert result["parent_id"] == UNIT and result["attributes"]["state"] == "active"
            assert sorted(result["signals"].values()) == sorted(
                [
                    f"{base}.plantcrafttwin-loopprocess.y-residual",
                    f"{base}.deviation-t",
                    f"{base}.deviation-t.status",
                ]
            )

            profile = runtime.presets.get_profile("unit-twin")
            recording = runtime.recording(
                runtime.jobs.get_schedule(schedule["schedule_id"]), profile
            )
            for minutes in (4, 3, 2, 1, 0):
                runtime.assets.run_one(
                    profile, UNIT, now=NOW - timedelta(minutes=minutes), schedule=recording
                )
            score = fake.series_data[f"{base}.deviation-t"]
            status = fake.series_data[f"{base}.deviation-t.status"]
            assert len(score) == 5 and set(status) <= {"ok", "warning", "bad"}
            shapes = {item["id"]: item for item in fake.signals}
            assert shapes[f"{base}.deviation-t"]["name"] == (
                "Furnace · Revisão do forno · Deviation (T²)"
            )
            assert shapes[f"{base}.deviation-t"]["retention_days"] == 30
            assert shapes[f"{base}.deviation-t"]["managed_by"] == (
                f"link:{schedule['schedule_id']}"
            )
            assert shapes[f"{base}.deviation-t.status"]["kind"] == "text"
            # A series goes whole, one per execution: the last three are kept.
            client_runs = runtime.service_client.series_runs(
                f"{base}.plantcrafttwin-loopprocess.y-residual", last=10
            )
            assert len(client_runs) == 3 and len(client_runs[0]["v"]) > 100
            assert f"{base}.plantcrafttwin-loopprocess.y" not in fake.series_data
            assert not [
                key
                for key in fake.series_data
                if key.startswith(f"app-linkcraft:{UNIT}.unit-twin.")
            ]

            # Executions charts what the schedule writes, under its own key (round 9, D11).
            page = client.get(
                f"/link/api/executions/groups/{schedule['schedule_id']}/{UNIT}"
            ).json()
            assert [item["id"] for item in page["series"]] == [f"{base}.deviation-t"]

            # What the algorithm wrote before round 8 is retired once; its schedule's points and
            # the algorithm's version marks stay.
            from linkcraft.loops.suite import ASSET_SERIES_MARK, retire_old_series

            older = f"app-linkcraft:{UNIT}.unit-twin.plantcrafttwin-loopprocess.y"
            runtime.suite.put_series([{"signal": older, "t": [NOW.isoformat()], "v": [1.0]}])
            assert retire_old_series(runtime.suite, runtime.presets) == 1
            mine = {item["id"] for item in fake.signals if item.get("app") == "linkcraft"}
            assert older not in mine and f"{base}.deviation-t" in mine
            assert "app-linkcraft:algorithm.unit-twin.version" in mine
            assert runtime.presets.marked(ASSET_SERIES_MARK) == "1"

            # Deleting the schedule ends its result asset; its points stay.
            client.delete(f"/link/api/schedules/{schedule['schedule_id']}")
            [ended] = [item for item in fake.assets if item["kind"] == "result"]
            assert ended["attributes"]["state"] == "ended"
            assert f"{base}.deviation-t" in fake.series_data
    finally:
        runtime.shutdown()
