"""Operator positions (L2): the ISA-18.2 load targets are for one operator, so a plant with
several boards splits its alarms by console and measures each against its own target."""

from __future__ import annotations

from alarmcraft.alarms.philosophy import Console, PhilosophyDraft
from tests.conftest import client_for, high, make_rule


def test_an_alarm_goes_to_the_console_naming_its_deepest_area():
    philosophy = PhilosophyDraft(
        consoles=[
            Console(id="unit", name="Unit board", areas=["U-SIM"]),
            Console(id="feed", name="Feed board", areas=["FIC-1001"], per_hour=3),
            Console(id="also", name="Also the unit", areas=["U-SIM"]),
        ]
    )
    assert philosophy.console_of(["plant", "U-SIM", "FIC-1001"]).id == "feed"
    assert philosophy.console_of(["plant", "U-SIM", "TIC-1104"]).id == "unit"  # first on a tie
    assert philosophy.console_of(["plant", "U-OTHER"]) is None
    assert philosophy.console_of([]) is None
    assert philosophy.for_console(philosophy.console("feed")).per_person_hour == 3
    assert philosophy.for_console(philosophy.console("unit")).per_person_hour == 6


def _consoles(client, consoles: list[dict]) -> dict:
    found = client.get("/api/philosophy").json()
    body = {**found["defaults"], "consoles": consoles}
    saved = client.put("/api/philosophy", json=body)
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_consoles_are_kept_in_the_philosophy_and_checked(client):
    saved = _consoles(client, [{"id": "Board-1", "name": " Board  1 ", "areas": ["U-SIM", "U-SIM"],
                                "operators": ["operator"]}])  # fmt: skip
    [board] = saved["consoles"]
    assert board == {"id": "board-1", "name": "Board 1", "areas": ["U-SIM"],
                     "operators": ["operator"], "per_hour": None}  # fmt: skip
    defaults = client.get("/api/philosophy").json()["defaults"]
    for bad in (
        [{"id": "a", "name": "A", "areas": []}],
        [{"id": "a b", "name": "A", "areas": ["U-SIM"]}],
        [{"id": "a", "name": "A", "areas": ["x"]}, {"id": "a", "name": "B", "areas": ["y"]}],
        [{"id": "a", "name": "A", "areas": ["x"]}, {"id": "b", "name": "a", "areas": ["y"]}],
        [{"id": "a", "name": "A", "areas": ["x"], "per_hour": 0}],
    ):
        answer = client.put("/api/philosophy", json={**defaults, "consoles": bad})
        assert answer.status_code == 422, bad


def test_performance_is_measured_by_console_against_its_own_target(client, runtime, fake):
    rule = make_rule(client, high(name="PV high", assets=[], under=["U-SIM"], limit=1.0))
    every = {row["alarm_id"] for row in rule["alarm_rows"]}
    assert "pv-high--fic-1001" in every and len(every) > 2
    client.post("/api/run")
    whole = client.get("/api/performance").json()
    assert whole["total"] == len(every) and whole["console"] is None

    # Before any console: the whole installation is one position.
    alone = client.get("/api/performance/consoles").json()
    assert alone["defined"] == 0
    assert [row["id"] for row in alone["consoles"]] == ["none"]

    _consoles(client, [
        {"id": "unit", "name": "Unit board", "areas": ["U-SIM"], "operators": ["operator"]},
        {"id": "feed", "name": "Feed board", "areas": ["FIC-1001"], "per_hour": 2},
        {"id": "far", "name": "Far board", "areas": ["U-OTHER"]},
    ])  # fmt: skip
    feed = client.get("/api/performance?console=feed").json()
    assert feed["total"] == 1 and [item["alarm_id"] for item in feed["top"]] == [
        "pv-high--fic-1001"
    ]
    assert feed["console"] == {"id": "feed", "name": "Feed board", "per_hour": 2}
    figures = {item["id"]: item for item in feed["figures"]}
    assert figures["per_hour"]["target"].startswith("≤ 2 ")
    unit = client.get("/api/performance?console=unit").json()
    assert unit["total"] == len(every) - 1
    assert "pv-high--fic-1001" not in {item["alarm_id"] for item in unit["top"]}
    assert client.get("/api/performance?console=none").json()["total"] == 0
    assert client.get("/api/performance?console=nope").status_code == 404

    rows = {row["id"]: row for row in client.get("/api/performance/consoles").json()["consoles"]}
    assert set(rows) == {"unit", "feed", "far"}  # nothing outside a console: no "none" row
    assert (rows["feed"]["total"], rows["feed"]["alarms"], rows["feed"]["target_per_hour"]) == (
        1,
        1,
        2,
    )
    assert rows["unit"]["total"] == len(every) - 1 and rows["unit"]["operators"] == ["operator"]
    assert rows["far"]["total"] == 0 and rows["far"]["eemua"] == "robust"
    assert rows["feed"]["per_hour"] == round(1 / 24, 2)

    # A viewer reads the load of every console too.
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/api/performance/consoles").status_code == 200
        assert (
            viewer.put(
                "/api/philosophy", json=client.get("/api/philosophy").json()["defaults"]
            ).status_code
            == 403
        )
