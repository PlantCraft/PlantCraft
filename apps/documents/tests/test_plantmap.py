"""The plant map: diagrams read from the documents, scored against the demo's answer key, and
joined into one plant (``doccraft.plantmap``)."""

from __future__ import annotations

import json

import pytest

from doccraft.plantmap.build import asset_file, build_map
from doccraft.plantmap.diagrams import describe, read_diagrams
from doccraft.plantmap.reader import DrawingError, read_drawing
from doccraft.plantmap.reader import tags as isa
from doccraft.plantmap.reader.score import score, total
from doccraft.plantmap.sample.draw import draw_all, draw_sheet, spec
from tests.conftest import index, send


@pytest.fixture(scope="module")
def sheets():
    return draw_all()


def test_isa_tags_are_whole_words_and_line_numbers_are_not_tags():
    assert isa.parse("FIC-1003").cls == "controller"
    assert isa.parse("FIC 1003").tag == "FIC-1003"
    assert isa.parse("LT-1004").cls == "transmitter"
    assert isa.parse("FV-1003").cls == "valve"
    assert isa.parse("P-1001A").family == "equipment"
    assert isa.parse("TK-1001").cls == "tank"
    for word in ('8"-P-1001-A1A', "PID-U-100-01", "U-100", "2025-11-20", "REV", "ISA-5.1"):
        assert isa.parse(word) is None, word


def test_every_demo_sheet_is_read_back_from_svg(sheets):
    scores = []
    for _, canvas, key in sheets:
        result = read_drawing(canvas.svg().encode(), "sheet.svg")[0]
        scores.append(score(result, key))
        assert scores[-1]["sheet_read"], key["sheet"]
        assert scores[-1]["line_numbers_taken_as_tags"] == 0
    assert total(scores, "tags")["recall"] == 1.0
    assert total(scores, "tags")["precision"] == 1.0
    assert total(scores, "relations")["recall"] >= 0.98
    assert total(scores, "relations")["precision"] >= 0.98


def test_a_vector_pdf_reads_like_its_svg(tmp_path, sheets):
    _, canvas, key = sheets[3]  # four loops on a column and a drum
    pdf = tmp_path / "sheet.pdf"
    canvas.pdf(pdf)
    result = read_drawing(pdf.read_bytes(), "sheet.pdf")[0]
    s = score(result, key)
    assert s["tags"]["recall"] == 1.0 and s["relations"]["recall"] >= 0.95


def test_without_arrows_the_flow_runs_left_to_right_with_low_confidence():
    from doccraft.plantmap.sample.draw import Style

    canvas, key = draw_sheet(spec()["sheets"][0], Style(arrows=False))
    result = read_drawing(canvas.svg().encode(), "a.svg")[0]
    feeds = [r for r in result["relations"] if r["type"] == "feeds"]
    assert {(r["from"], r["to"]) for r in feeds} >= {tuple(f) for f in key["feeds"]}
    assert all(r["confidence"] == "low" for r in feeds)


@pytest.mark.parametrize(
    "data",
    [b"", b"<svg", b"<!DOCTYPE svg [<!ENTITY a 'x'>]><svg/>", b"%PDF-1.4 broken", b"\x89PNG\r\n"],
)
def test_a_broken_drawing_says_why_and_never_crashes(data):
    with pytest.raises(DrawingError):
        read_drawing(data, "x")
    assert read_diagrams(data, "x.pdf") == []


def test_a_diagram_in_words_names_its_lines(sheets):
    _, canvas, _ = sheets[0]
    page = read_diagrams(canvas.svg().encode(), "PID-U-100-01.svg")[0]
    text = describe(page)
    assert "P-1001 feeds E-1009" in text and "FIC-1001 controls FV-1001" in text


def test_sheets_join_into_one_plant_and_an_asset_file(sheets):
    rows = []
    for n, (sheet, canvas, _) in enumerate(sheets):
        page = read_drawing(canvas.svg().encode(), f"{sheet}.svg")[0]
        rows.append(
            {
                "doc_id": f"d{n}",
                "rev_id": f"r{n}",
                "page": 1,
                "sheet": page["sheet"],
                "unit": page["unit"],
                "title": page["title"],
                "source": page["source"],
                "doc_title": sheet,
                "result": page,
            }
        )
    plant = build_map(rows, known={"P-1001", "FIC-1001"})
    summary = plant["summary"]
    assert summary["sheets"] == 14 and summary["loops"] == 50 and summary["loops_complete"] == 50
    assert summary["equipment"] == 21 and summary["in_plantcraft"] == 2
    # The line leaving sheet 01 arrives on sheet 02: one plant, not fourteen drawings.
    feeds = {(r["from"], r["to"]) for r in plant["relations"] if r["type"] == "feeds"}
    assert ("P-1001", "E-1009") in feeds and ("E-1009", "F-1104") in feeds
    document = asset_file(plant)
    types = {a["asset_id"]: a["type"] for a in document["assets"]}
    assert types["P-1001"] == "pump" and types["FIC-1001"] == "loop"
    assert types["FV-1001"] == "control_valve" and types["U-100"] == "unit"
    parents = {a["asset_id"]: a.get("parent_id") for a in document["assets"]}
    assert parents["FT-1001"] == "P-1001" and parents["P-1001"] == "u-100-feed"
    assert {"from": "FIC-1001", "type": "controls", "to": "FV-1001"} in document["relations"]


def test_a_pdf_sent_to_the_library_lands_in_diagrams_and_the_map(client, runtime, tmp_path, sheets):
    _, canvas, _ = sheets[1]
    pdf = tmp_path / "PID-U-100-02.pdf"
    canvas.pdf(pdf)
    doc = send(client, "PID-U-100-02.pdf", pdf.read_bytes(), number="PID-U-100-02", kind="P&ID")
    svg = send(
        client, "PID-U-100-01.svg", canvas_svg(sheets[0]), number="PID-U-100-01", kind="P&ID"
    )
    index(runtime)
    listed = client.get("/api/diagrams").json()
    assert {d["sheet"] for d in listed} == {"PID-U-100-01", "PID-U-100-02"}
    one = next(d for d in listed if d["doc_id"] == doc["doc_id"])
    detail = client.get(f"/api/diagrams/{one['rev_id']}/1").json()
    assert detail["result"]["relations"] and "sha256" not in detail
    image = client.get(f"/api/diagrams/{one['rev_id']}/1/image")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    plant = client.get("/api/plant-map").json()
    assert ("P-1001", "E-1009") in {(r["from"], r["to"]) for r in plant["relations"]}
    found = client.post("/api/search", json={"query": "what feeds E-1009"}).json()
    assert any("P-1001 feeds E-1009" in hit["text"] for hit in found["passages"])
    exported = client.get("/api/plant-map/asset-file")
    assert exported.status_code == 200
    assert json.loads(exported.content)["format"] == "processcraft-assets"
    assert svg["doc_id"]


def canvas_svg(sheet) -> bytes:
    return sheet[1].svg().encode()


FOREIGN = {
    "sheet": "PID-U-200-07",
    "equipment": [{"tag": t} for t in ("V-201", "P-202", "E-203")],
    "instruments": [{"tag": t} for t in ("LT-201", "LIC-201", "LV-201", "PI-202")],
    "feeds": [["R-205", "V-201"], ["V-201", "P-202"], ["P-202", "E-203"]],
    "measures": [["LT-201", "V-201"], ["PI-202", "P-202"]],
    "controls": [["LIC-201", "LV-201"]],
    "signals": [["LT-201", "LIC-201"]],
    "valve_on": [["LV-201", "P-202"]],
}


def test_a_drawing_in_another_style_is_read_too():
    """Drawn by hand, not by the demo's generator: flow top to bottom, a drum with arc heads,
    a vertical valve, open chevron arrows, tags on one line inside the bubbles."""
    from pathlib import Path

    data = (Path(__file__).parent / "files" / "foreign-pid.svg").read_bytes()
    result = read_drawing(data, "foreign-pid.svg")[0]
    s = score(result, FOREIGN)
    assert s["sheet_read"] and result["unit"] == "U-200" and result["title"] == "Knock-Out Drum"
    assert s["tags"]["recall"] == 1.0 and s["tags"]["precision"] == 1.0
    assert s["relations"]["recall"] == 1.0 and s["relations"]["precision"] == 1.0
    # Its own number in the title block is not a connector to another sheet.
    assert not any(i.get("ref_sheet") == "PID-U-200-07" for i in result["items"])
