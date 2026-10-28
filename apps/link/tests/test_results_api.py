"""The Results page's API: every algorithm's latest result on every asset, in the suite's words."""

from __future__ import annotations

from plantcraft_sdk import apptest

RANK = {"alarm": 0, "warning": 1, "unknown": 2, "ok": 3}


def test_signals_are_results_in_the_suite_words(checked, sq_client):
    answer = sq_client.get("/link/api/results?kind=signal&limit=500").json()
    items = answer["items"]
    assert items and {item["kind"] for item in items} == {"signal"}
    assert [RANK[item["status"]] for item in items] == sorted(
        RANK[item["status"]] for item in items
    )
    first = items[0]
    assert first["status"] == "alarm" and first["native_status"] == "bad"
    assert first["measure"]["label"] == "Quality" and first["measure"]["format"] == "score"
    assert first["algorithm"] == {"id": "signal_quality", "name": "Signal quality", "version": 1}
    assert first["tags"] == ["data quality"] and first["asset_type"] == "signal"
    assert first["asset_type_label"] == "Signal" and first["group"] is None
    assert first["path"].startswith("/signals/historian%3A")
    assert answer["counts"]["status"]["alarm"] == sum(
        1 for item in items if item["status"] == "alarm"
    )
    alarms = sq_client.get("/link/api/results?status=alarm").json()["items"]
    assert alarms and {item["status"] for item in alarms} == {"alarm"}
    found = sq_client.get("/link/api/results?q=bed temperature").json()["items"]
    assert {item["id"] for item in found} == {"historian:TI-108A.PV", "historian:TI-108B.PV"}


def test_loops_are_results_with_their_health_and_algorithm(client, analysed):
    answer = client.get("/link/api/results?kind=loop").json()
    loops = {item["id"]: item for item in answer["items"]}
    lic = loops["lic-102"]
    assert lic["status"] == "alarm" and lic["native_status"] in {"critical", "high"}
    assert lic["measure"]["label"] == "Health" and lic["measure"]["format"] == "percent"
    assert lic["measure"]["value"] is not None and lic["algorithm"]["name"]
    assert lic["path"] == "/loops/lic-102"
    every = client.get("/link/api/results").json()
    assert every["counts"]["kind"]["loop"] == len(loops)
    assert [item["id"] for item in every["kinds"]] == ["signal", "loop", "asset"]
    # Filters by algorithm, tag and asset type, each with what every choice would show.
    options = every["options"]
    assert {item["id"] for item in options["asset_type"]} >= {"loop"}
    assert "control loop" in {item["id"] for item in options["tag"]}
    tagged = client.get("/link/api/results?tag=control loop").json()
    assert tagged["total"] == len(loops) and {item["kind"] for item in tagged["items"]} == {"loop"}
    one = lic["algorithm"]["id"]
    by_algorithm = client.get(f"/link/api/results?algorithm={one}").json()["items"]
    assert by_algorithm and {item["algorithm"]["id"] for item in by_algorithm} == {one}
    assert client.get("/link/api/results?asset_type=furnace").json()["total"] == 0


def test_the_results_report_is_a_pdf_of_any_filter(client, analysed):
    answer = client.get("/link/api/reports/results.pdf?tag=control loop&status=alarm")
    assert answer.status_code == 200 and answer.content[:5] == b"%PDF-"
    assert answer.headers["content-disposition"].startswith('attachment; filename="results-')
    empty = client.get("/link/api/reports/results.pdf?asset_type=nothing")
    assert empty.status_code == 200 and empty.content[:5] == b"%PDF-"


def test_runs_of_every_algorithm_are_one_history(checked, sq_client):
    """Signal quality rounds and loop runs on one list (owner, 2026-10-21: no split)."""

    answer = sq_client.get("/link/api/runs").json()
    assert answer["total"] == len(answer["items"]) >= 1
    first = answer["items"][0]
    assert first["algorithm"] == {"id": "signal_quality", "name": "Signal quality"}
    assert first["path"].startswith("/runs/signal-quality-")
    assert first["state"] in {"ok", "alarm", "warning", "running"}
    stamps = [item["started_at"] for item in answer["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_an_algorithm_says_where_it_is_used(client, analysed):
    signal = client.get("/link/api/algorithms/signal_quality/usage").json()
    assert signal["subjects"]["kind"] == "signal" and signal["subjects"]["every"] is True
    assert [item["schedule_id"] for item in signal["schedules"]] == ["round-signal_quality"]
    loops = client.get("/link/api/results?kind=loop").json()["items"]
    algorithm = loops[0]["algorithm"]["id"]
    used = client.get(f"/link/api/algorithms/{algorithm}/usage").json()
    assert used["algorithm"]["id"] == algorithm and used["subjects"]["kind"] == "loop"
    assert loops[0]["id"] in {item["id"] for item in used["subjects"]["items"]}
    # An id of 0.2 names the algorithm that replaced it.
    assert client.get("/link/api/algorithms/general/usage").json()["algorithm"]["id"] == (
        "flow_loop"
    )
    assert client.get("/link/api/algorithms/no-such/usage").status_code == 404


def test_link_publishes_overview_widgets(client, analysed):
    """The Overview's widgets, as app.toml declares them: each answers in its shape, a widget
    about one schedule or subject lists its choices, and links stay under Link's prefix."""

    listed = client.get("/link/api/widgets").json()
    assert {item["id"] for item in listed["widgets"] if item["default"]} == {"attention"}
    assert {item["id"] for item in listed["widgets"] if item.get("pick")} == {
        "results",
        "schedule",
        "subject",
    }
    assert apptest.widget_problems(client, "/link") == []
    attention = client.get("/link/api/widgets/attention").json()
    worst = client.get("/link/api/widgets/worst").json()
    assert len(worst["items"]) == min(8, attention["value"])
    shown = [float(item["value"].split()[-2]) for item in worst["items"] if item.get("value")]
    assert shown == sorted(shown)  # the lowest result first
    # A value reads with its measure ("Health 30 %"), never as a bare number.
    assert all(
        item.get("value") is None or str(item["value"]).endswith("%") for item in worst["items"]
    )
    signals = client.get("/link/api/widgets/results?item=signal").json()
    assert signals["kind"] == "split"
    assert all("kind=signal" in part["href"] for part in signals["parts"])
