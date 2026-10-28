"""The symbol library: every file loads, and no drawing can carry a script, a style or a link."""

from __future__ import annotations

import json
import re

import pytest

from dashcraft.diagrams.symbols import LIBRARY, UnsafeSvg, clean_svg, library, load_symbol

FILES = sorted(LIBRARY.glob("*/*.json"))


@pytest.mark.skipif(not FILES, reason="the library is empty")
@pytest.mark.parametrize("path", FILES, ids=[path.stem for path in FILES])
def test_every_symbol_file_loads(path):
    symbol = load_symbol(path)
    assert path.stem == symbol.id


POINTS = re.compile(r'points="([^"]*)"')
NUMBERS = re.compile(r"^\s*-?[\d.]+[ ,]-?[\d.]+(\s+-?[\d.]+[ ,]-?[\d.]+)*\s*$")


def test_polylines_and_polygons_hold_only_numbers():
    # A path command in points ("M40,60") is a console error in every browser (site test,
    # 2026-10-27, the furnace).
    for path in FILES:
        svg = json.loads(path.read_text())["svg"]
        for points in POINTS.findall(svg):
            assert NUMBERS.match(points), f"{path.stem}: points={points!r}"


def test_symbol_ids_are_unique_and_served(client):
    ids = [json.loads(path.read_text())["id"] for path in FILES]
    assert len(ids) == len(set(ids))
    served = client.get("/dash/api/diagram-symbols").json()
    assert {item["id"] for item in served} == set(ids)


@pytest.mark.parametrize(
    "svg",
    [
        '<script>alert(1)</script><rect width="1" height="1"/>',
        '<rect width="1" height="1" onload="alert(1)"/>',
        '<rect width="1" height="1" fill="url(https://x.example/a.svg)"/>',
        '<image href="https://x.example/a.png"/><rect width="1" height="1"/>',
        '<a href="javascript:alert(1)"><circle r="1"/></a><rect width="1" height="1"/>',
        '<rect width="1" height="1" style="fill:red"/>',
        '<foreignObject><div>x</div></foreignObject><rect width="1" height="1"/>',
        '<rect width="1" height="1" transform="matrix(1 0 0 1 0 0)"/>',
    ],
)
def test_unsafe_parts_are_dropped(svg):
    cleaned = clean_svg(svg)
    for word in ("script", "onload", "url(", "image", "href", "style", "foreign", "matrix"):
        assert word not in cleaned
    assert "<rect" in cleaned


@pytest.mark.parametrize(
    "svg",
    [
        '<!DOCTYPE x [<!ENTITY a "aaaa">]><rect/>',
        "<rect>&a;</rect>",
        "<rect",
        "<script>x</script>",
        "x" * 50_000,
    ],
)
def test_drawings_that_cannot_be_used_are_refused(svg):
    with pytest.raises(UnsafeSvg):
        clean_svg(svg)


def test_a_broken_file_leaves_the_others(tmp_path):
    (tmp_path / "pump").mkdir()
    (tmp_path / "pump" / "pump.bad.json").write_text("{not json")
    good = {
        "id": "pump.any",
        "title": "Pump",
        "category": "Pumps",
        "w": 60,
        "h": 60,
        "svg": '<circle class="pc-state" cx="30" cy="30" r="24"/>',
        "ports": [{"id": "in", "x": 6, "y": 30, "dir": "w"}],
        "extra": "ignored",
    }
    (tmp_path / "pump" / "pump.good.json").write_text(json.dumps({**good, "id": "pump.good"}))
    outside = {**good, "id": "pump.outside", "ports": [{"id": "a", "x": -5, "y": 0}]}
    (tmp_path / "pump" / "pump.outside.json").write_text(json.dumps(outside))
    assert [item["id"] for item in library(tmp_path)] == ["pump.good"]
