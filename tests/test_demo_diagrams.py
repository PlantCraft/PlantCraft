"""The demo's process display (``deploy/demo/diagrams``), which the seed creates in View.

It is drawn on the plant map shipped with the demo, so it must keep up with it: the whole plant
on one page, every loop of the map drawn exactly once, every bound asset in
the map, every line between two symbols of the display and every symbol at the library's own
proportions. View checks the rest of the contract when the seed posts it
(``apps/view/src/dashcraft/diagrams/model.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "deploy" / "demo" / "diagrams"
MAP = ROOT / "deploy" / "demo" / "plantcraft-50-loops-map.json"
LIBRARY = ROOT / "apps" / "view" / "src" / "dashcraft" / "diagrams" / "symbols"
ROLES = {"pv", "sp", "op", "mode"}


def _plant() -> dict[str, Any]:
    displays = [json.loads(path.read_text(encoding="utf-8")) for path in FOLDER.glob("*.json")]
    assert [display["name"] for display in displays] == ["Riverbend plant"]
    return displays[0]


def _items(element: dict[str, Any]) -> list[dict[str, Any]]:
    found = [element["item"]] if "item" in element else []
    found += [
        element[slot]["item"] for slot in ("state", "level", "running", "flow") if slot in element
    ]
    return found


def test_every_loop_is_drawn_exactly_once_on_one_page() -> None:
    plant = json.loads(MAP.read_text(encoding="utf-8"))
    display = _plant()
    assert not display.get("pages")
    assert display["width"] <= 8000 and display["height"] <= 8000
    seen = [e["asset_id"] for e in display["elements"] if e.get("symbol") == "instrument.bubble"]
    assert sorted(seen) == sorted(loop["loop_id"] for loop in plant["loops"])
    for e in display["elements"]:
        for x, y in [(e["x"], e["y"])] if "x" in e else e.get("points", []):
            assert 0 <= x <= display["width"] and 0 <= y <= display["height"], e["id"]


def test_the_parts_are_tabs_to_each_tile_of_the_page() -> None:
    """Overview and a tab per part: every part a tile inside the canvas."""

    display = _plant()
    parts = display["parts"]
    assert [part["name"] for part in parts][:2] == ["Preheat and furnace", "Column"]
    assert len({part["id"] for part in parts}) == len(parts) == 7
    for part in parts:
        x, y, w, h = (float(n) for n in part["area"].split(","))
        assert x + w <= display["width"] and y + h <= display["height"], part


def test_bindings_read_assets_and_roles_of_the_map() -> None:
    plant = json.loads(MAP.read_text(encoding="utf-8"))
    assets = {a["asset_id"] for a in plant["assets"]} | {loop["loop_id"] for loop in plant["loops"]}
    for element in _plant()["elements"]:
        if element.get("asset_id"):
            assert element["asset_id"] in assets, element["id"]
        for item in _items(element):
            assert item["asset_id"] in assets, element["id"]
            assert item.get("role") in ROLES or item.get("result"), element["id"]


def test_ids_are_unique_no_page_links_and_lines_join_symbols() -> None:
    display = _plant()
    ids = [element["id"] for element in display["elements"]]
    assert len(ids) == len(set(ids))
    symbols = {e["id"] for e in display["elements"] if e["type"] == "symbol"}
    for element in display["elements"]:
        assert "page" not in element and (element.get("link") or {}).get("kind") != "page"
        if (element.get("link") or {}).get("kind") == "area":
            x, y, w, h = (float(part) for part in element["link"]["target"].split(","))
            assert x + w <= display["width"] and y + h <= display["height"], element["id"]
        for end in ("start", "end"):
            if end in element:
                assert element[end]["element"] in symbols, element["id"]


def test_symbols_are_in_views_library_at_their_own_proportions() -> None:
    library = {}
    for path in LIBRARY.rglob("*.json"):
        spec = json.loads(path.read_text(encoding="utf-8"))
        library[spec["id"]] = spec["w"] / spec["h"]
    for element in _plant()["elements"]:
        if element["type"] != "symbol":
            continue
        assert element["symbol"] in library, element["id"]
        ratio = element["w"] / element["h"]
        assert abs(ratio - library[element["symbol"]]) < 0.02, element["id"]


class _View:
    """View's diagram and folder API, as much as the seed uses of it."""

    def __init__(self) -> None:
        self.diagrams: dict[str, dict[str, Any]] = {}
        self.folders = [
            {"name": "Operation", "folder_id": "f-op"},
            {"name": "Control loops", "folder_id": "f-loops"},
        ]

    def call(self, method: str, path: str, body: Any = None, **_: Any) -> tuple[int, Any]:
        if (method, path) == ("GET", "/api/diagrams"):
            return 200, [{"diagram_id": key, **value} for key, value in self.diagrams.items()]
        if method == "GET":
            key = path.rsplit("/", 1)[1]
            return 200, {"diagram_id": key, "updated_at": "t1", **self.diagrams[key]}
        if method == "PUT":
            key = path.rsplit("/", 1)[1]
            assert body.pop("base_updated_at") == "t1"
            self.diagrams[key] = body
            return 200, body
        if method == "DELETE":
            self.diagrams.pop(path.rsplit("/", 1)[1])
            return 204, None
        raise AssertionError(path)

    def get(self, path: str, **_: Any) -> Any:
        assert path == "/api/folders"
        return self.folders

    def post(self, path: str, body: Any = None, **_: Any) -> Any:
        assert path == "/api/diagrams"
        key = f"d{len(self.diagrams) + 1}"
        self.diagrams[key] = body
        return {"diagram_id": key, **body}


def test_seed_creates_it_once_and_replaces_the_old_one_page_diagrams() -> None:
    from plantcraft.demo_seed import Suite, view_diagrams

    view = _View()
    view.diagrams["old"] = {"name": "Atmospheric column", "tags": ["demo"], "elements": []}
    view.diagrams["mine"] = {"name": "Atmospheric column", "tags": [], "elements": []}
    suite = Suite("http://pc", {}, "admin", "pw", "pw", MAP)
    view_diagrams(view, suite)  # type: ignore[arg-type]
    names = sorted(body["name"] for body in view.diagrams.values())
    assert names == ["Atmospheric column", "Riverbend plant"]
    assert "mine" in view.diagrams  # a diagram someone made under the same name stays
    made = next(body for body in view.diagrams.values() if body["name"] == "Riverbend plant")
    assert made["folder_id"] == "f-op" and not made.get("pages")
    view_diagrams(view, suite)  # type: ignore[arg-type]
    assert sorted(body["name"] for body in view.diagrams.values()) == names


def test_seed_redraws_the_paged_demo_display_on_one_page_and_leaves_a_redrawn_one() -> None:
    from plantcraft.demo_seed import Suite, view_diagrams

    paged = {"id": "overview", "name": "Overview"}, {"id": "column", "name": "Column"}
    view = _View()
    view.diagrams["g7"] = {
        "name": "Riverbend plant",
        "tags": ["demo"],
        "folder_id": "f-loops",
        "pages": list(paged),
        "elements": [],
    }
    suite = Suite("http://pc", {}, "admin", "pw", "pw", MAP)
    view_diagrams(view, suite)  # type: ignore[arg-type]
    redrawn = view.diagrams["g7"]
    assert not redrawn.get("pages") and redrawn["elements"] and redrawn["folder_id"] == "f-loops"
    assert len(redrawn["parts"]) == 7
    # The one-page display of 2026-10-27, without parts, gets its tabs too.
    view.diagrams["g7"] = {**redrawn, "parts": []}
    view_diagrams(view, suite)  # type: ignore[arg-type]
    assert len(view.diagrams["g7"]["parts"]) == 7
    view.diagrams["g7"] = {**redrawn, "tags": [], "pages": list(paged)}
    view_diagrams(view, suite)  # type: ignore[arg-type]
    assert view.diagrams["g7"]["pages"] == list(paged)  # someone's own copy is left alone
