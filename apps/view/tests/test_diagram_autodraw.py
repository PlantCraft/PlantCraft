"""A unit's diagram drawn from its assets: one symbol per piece of equipment, loops as bubbles
with their PV and SP, process lines from the relations, laid out left to right on the grid."""

from __future__ import annotations

import random

from dashcraft.diagrams.autodraw import draw_unit, unit_diagrams
from dashcraft.diagrams.model import MAX_SIZE, PAGE_ELEMENTS, DiagramPayload
from tests.conftest import client_for


def _tree() -> list[dict]:
    """A tank feeding a pump, an exchanger and a column that recycles to the tank."""

    return [
        {"id": "U", "name": "Unit 1", "kind": "unit", "parent_id": None},
        {"id": "A", "name": "Area", "kind": "area", "parent_id": "U"},
        {
            "id": "T1",
            "name": "T-1",
            "kind": "tank",
            "parent_id": "A",
            "signals": {"level": "x:T1.LEVEL"},
            "relations": [{"type": "feeds", "to": "P1"}],
        },
        {
            "id": "P1",
            "name": "P-1",
            "kind": "pump",
            "parent_id": "U",
            "signals": {"running": "x:P1.RUN", "flow": "x:P1.FLOW"},
            "relations": [{"type": "feeds", "to": "E1"}],
        },
        {"id": "E1", "name": "E-1", "kind": "heat_exchanger", "parent_id": "U"},
        {
            "id": "C1",
            "name": "C-1",
            "kind": "column",
            "parent_id": "U",
            "relations": [{"type": "downstream_of", "to": "E1"}, {"type": "feeds", "to": "T1"}],
        },
        {
            "id": "L1",
            "name": "LIC-1",
            "kind": "loop",
            "parent_id": "U",
            "signals": {"pv": "x:L1.PV", "sp": "x:L1.SP"},
            "relations": [{"type": "controls", "to": "T1"}],
        },
        {"id": "L2", "name": "FIC-9", "kind": "loop", "parent_id": "U", "signals": {"pv": "x:L2"}},
        {"id": "X", "name": "Skid", "kind": "thing", "parent_id": "U"},
        {"id": "far", "name": "Elsewhere", "kind": "pump", "parent_id": None},
    ]


def _by_id(diagram: dict) -> dict[str, dict]:
    return {element["id"]: element for element in diagram["elements"]}


def test_each_piece_of_equipment_is_a_symbol_picked_from_its_kind():
    diagram, notes = draw_unit(_tree(), "U")
    DiagramPayload.model_validate(diagram)
    symbols = {
        element["asset_id"]: element["symbol"]
        for element in diagram["elements"]
        if element["type"] == "symbol"
    }
    assert symbols == {
        "T1": "vessel.tank",
        "P1": "pump.centrifugal",
        "E1": "exchanger.shell_tube",
        "C1": "column.distillation",
        "X": "shape.panel",
        "L1": "instrument.bubble",
        "L2": "instrument.bubble",
    }
    elements = _by_id(diagram)
    assert elements["e-T1"]["level"]["item"] == {
        "asset_id": "T1",
        "role": "level",
        "roles": [],
        "label": "",
    }
    assert elements["e-P1"]["running"]["item"]["role"] == "running"
    assert notes == []


def test_loops_are_bubbles_with_their_health_pv_and_sp_above_what_they_control():
    diagram, _ = draw_unit(_tree(), "U")
    elements = _by_id(diagram)
    bubble = elements["l-L1"]
    assert bubble["state"]["item"]["result"] == "linkcraft.loop_health"
    assert bubble["state"]["item"]["asset_id"] == "L1"
    values = [
        e for e in diagram["elements"] if e["type"] == "value" and e["item"]["asset_id"] == "L1"
    ]
    assert [(v["label"], v["item"]["role"]) for v in values] == [("PV", "pv"), ("SP", "sp")]
    tank = elements["e-T1"]
    assert bubble["y"] + bubble["h"] < tank["y"]
    assert tank["x"] <= bubble["x"] + bubble["w"] / 2 <= tank["x"] + tank["w"]
    signal = elements["s-L1-T1"]
    assert signal["kind"] == "signal"
    assert (signal["start"]["element"], signal["end"]["element"]) == ("l-L1", "e-T1")
    # A loop on no equipment still shows, below the rest.
    assert elements["l-L2"]["y"] > max(
        e["y"] for e in diagram["elements"] if e["type"] == "symbol" and e["id"].startswith("e-")
    )


def test_process_lines_follow_the_relations_left_to_right_and_a_recycle_goes_under():
    diagram, _ = draw_unit(_tree(), "U")
    elements = _by_id(diagram)
    lines = {
        (e["start"]["element"], e["end"]["element"]): e
        for e in diagram["elements"]
        if e["type"] == "line" and e["kind"] == "process"
    }
    assert set(lines) == {
        ("e-T1", "e-P1"),
        ("e-P1", "e-E1"),
        ("e-E1", "e-C1"),  # C-1 is downstream of E-1
        ("e-C1", "e-T1"),
    }
    # Longest path from the first in name order (C-1); the edge back to it is the recycle.
    xs = [elements[f"e-{asset}"]["x"] for asset in ("C1", "T1", "P1", "E1")]
    assert xs == sorted(xs) and len(set(xs)) == 4
    recycle = lines[("e-E1", "e-C1")]["points"]
    lowest = max(e["y"] + e["h"] for e in elements.values() if e["id"] in {"e-C1", "e-E1"})
    assert len(recycle) == 4 and recycle[1][1] > lowest
    # Every corner is a right angle.
    for line in lines.values():
        points = line["points"]
        for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
            assert x1 == x2 or y1 == y2


def test_the_drawing_is_on_the_grid_inside_the_canvas_and_the_same_every_time():
    diagram, _ = draw_unit(_tree(), "U")
    for element in diagram["elements"]:
        for key in ("x", "y", "w", "h"):
            if key in element:
                assert element[key] % 10 == 0, (element["id"], key)
        if "x" in element:
            assert 0 <= element["x"] < diagram["width"] and 0 <= element["y"] < diagram["height"]
    shuffled = _tree()
    random.Random(4).shuffle(shuffled)
    assert draw_unit(shuffled, "U") == draw_unit(_tree(), "U")
    assert "far" not in {e.get("asset_id") for e in diagram["elements"]}


def test_a_library_symbol_that_draws_the_kind_and_its_ports_come_first():
    library = [
        {
            "id": "pump.special",
            "w": 60,
            "h": 60,
            "asset_types": ["pump"],
            "ports": [
                {"id": "suction", "x": 0, "y": 30, "dir": "w"},
                {"id": "discharge_out", "x": 60, "y": 10, "dir": "e"},
            ],
        }
    ]
    diagram, _ = draw_unit(_tree(), "U", library=library)
    elements = _by_id(diagram)
    assert elements["e-P1"]["symbol"] == "pump.special"
    out = next(
        e for e in diagram["elements"] if e["type"] == "line" and e["start"]["element"] == "e-P1"
    )
    assert out["start"]["port"] == "discharge_out"
    into = next(
        e
        for e in diagram["elements"]
        if e["type"] == "line" and e["end"]["element"] == "e-P1" and e["kind"] == "process"
    )
    assert into["end"]["port"] == "suction"


def test_an_unknown_unit_an_empty_one_and_junk_never_crash():
    assert draw_unit(_tree(), "nowhere") is None
    empty, notes = draw_unit([{"id": "U", "name": "Empty", "kind": "unit"}], "U")
    assert [e["type"] for e in empty["elements"]] == ["text", "text"] and notes
    junk = [
        None,
        "x",
        {"name": "no id"},
        {"id": 5},
        {"id": "U", "kind": "unit"},
        {"id": "a", "parent_id": "b", "kind": "pump", "signals": ["pv"], "relations": "feeds"},
        {"id": "b", "parent_id": "a", "kind": None},
        {
            "id": "c",
            "parent_id": "U",
            "kind": "pump",
            "relations": [None, {"type": "feeds"}, 3, {"type": "feeds", "to": "c"}],
        },
        {"id": "d", "parent_id": ["U"], "kind": "loop", "attributes": [1]},
        {
            "id": "e",
            "parent_id": "U",
            "kind": "loop",
            "attributes": "x",
            "name": {"a": 1},
            "type_path": "loop",
            "signals": {"pv": "s", "": "t", "x" * 70: "u"},
        },
    ]
    diagram, _ = draw_unit(junk, "U")
    DiagramPayload.model_validate(diagram)


def test_a_huge_unit_stays_within_the_contract():
    assets = [{"id": "U", "name": "Big", "kind": "unit"}]
    assets += [
        {
            "id": f"P{n}",
            "name": f"P-{n:03d}",
            "kind": "pump",
            "parent_id": "U",
            "signals": {"flow": f"x:{n}", "pv": f"y:{n}"},
            "relations": [{"type": "feeds", "to": f"P{n + 1}"}],
        }
        for n in range(60)
    ]
    assets += [
        {
            "id": f"L{n}",
            "name": f"FIC-{n:03d}",
            "kind": "loop",
            "parent_id": "U",
            "signals": {"pv": "a", "sp": "b"},
        }
        for n in range(300)
    ]
    diagram, notes = draw_unit(assets, "U")
    DiagramPayload.model_validate(diagram)
    assert len(diagram["elements"]) <= PAGE_ELEMENTS
    assert diagram["width"] <= MAX_SIZE and diagram["height"] <= MAX_SIZE
    assert any("left out" in note for note in notes)


def test_each_unit_of_an_import_gets_the_assets_nearest_to_it():
    assets = _tree() + [
        {"id": "U2", "name": "Unit 2", "kind": "unit", "parent_id": "U"},
        {"id": "P9", "name": "P-9", "kind": "pump", "parent_id": "U2"},
    ]
    made = unit_diagrams(assets, ["U", "U2", "missing"])
    assert [item["name"] for item in made] == ["Unit 1 process display", "Unit 2 process display"]
    first = {e.get("asset_id") for e in made[0]["elements"]}
    assert "P9" not in first and "P1" in first


# The endpoints --------------------------------------------------------------------------


def test_an_editor_draws_a_units_diagram_from_its_assets_and_saves_it(client):
    answer = client.post("/dash/api/diagrams/draw-from-assets", json={"unit_id": "unit-100"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    elements = _by_id(body["diagram"])
    assert elements["e-fv-101"]["symbol"] == "valve.control"
    assert elements["e-p-201"]["symbol"] == "pump.centrifugal"
    assert elements["l-fic-101"]["state"]["item"]["result"] == "linkcraft.loop_health"
    assert elements["s-fic-101-fv-101"]["end"]["element"] == "e-fv-101"
    assert body["notes"]  # no feeds relation in the test plant: the lines are left to draw
    assert client.get("/dash/api/diagrams").json() == []  # a draft, not saved
    saved = client.post("/dash/api/diagrams", json=body["diagram"])
    assert saved.status_code == 201, saved.text
    data = client.get(f"/dash/api/diagrams/{saved.json()['diagram_id']}/data").json()
    pv = next(row for row in data["bindings"] if row["element"] == "v-fic-101-pv")
    assert pv["error"] is None and pv["value"] is not None


def test_drawing_from_assets_is_an_editors_and_needs_a_unit(client, runtime, fake):
    assert (
        client.post("/dash/api/diagrams/draw-from-assets", json={"unit_id": "nowhere"}).status_code
        == 404
    )
    assert client.post("/dash/api/diagrams/draw-from-assets", json={}).status_code == 422
    with client_for(runtime, fake, "operator") as operator:
        assert (
            operator.post(
                "/dash/api/diagrams/draw-from-assets", json={"unit_id": "unit-100"}
            ).status_code
            == 403
        )


def test_a_new_plants_first_step_draws_the_plant_with_a_page_per_unit(client, runtime, fake):
    body = {"units": ["unit-100", "plant"], "assets": [{"id": "unit-100", "kind": "unit"}]}
    done = client.post("/dash/api/start/unit-diagrams", json=body)
    assert done.status_code == 200, done.text
    assert done.json()["counts"] == {"created": 1, "kept": 0, "pages": 1}
    assert done.json()["open"] == "/dash/diagrams"
    [made] = client.get("/dash/api/diagrams").json()
    assert made["name"] == "Plant process" and not made.get("folder_id")
    assert made["element_count"] > 5
    full = client.get(f"/dash/api/diagrams/{made['diagram_id']}").json()
    assert [page["name"] for page in full["pages"]] == ["Unit 100"]
    assert {element["page"] for element in full["elements"]} == {"p1"}
    again = client.post("/dash/api/start/unit-diagrams", json=body).json()
    assert again["counts"] == {"created": 0, "kept": 1, "pages": 0}
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post("/dash/api/start/unit-diagrams", json=body).status_code == 403
