"""What PlantCraft PID adds to PlantCraft (``app.toml [contributes]``): the search, what a
``#pid:<id>`` names, the widgets, and the routes behind each table."""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk import apptest

from pidcraft.api.app import create_app
from pidcraft.plantmap.sample.draw import draw_all
from tests.conftest import client_for, index, send

ROOT = Path(__file__).resolve().parents[1]


def _one(client, runtime) -> dict:
    _, canvas, key = draw_all()[0]
    drawing = send(client, "sheet.svg", canvas.svg().encode(), number=key["sheet"], unit="U-100")
    index(runtime)
    return drawing


def test_a_reference_names_the_drawing_for_whoever_reads_it(runtime, fake, client):
    drawing = _one(client, runtime)
    with client_for(runtime, fake, "operator") as operator:
        ref = operator.get(f"/api/refs/pid/{drawing['drawing_id']}")
        assert operator.get("/api/refs/pid/nowhere").status_code == 404
    assert ref.status_code == 200
    assert ref.json()["url"] == f"/pid/drawings/{drawing['drawing_id']}"
    assert ref.json()["title"].startswith("PID-U-100-01")


def test_search_finds_drawings_and_the_tags_on_them(runtime, client):
    _one(client, runtime)
    found = client.get("/api/search", params={"q": "PID-U-100"}).json()["items"]
    assert any(item["type"] == "Drawing" for item in found)
    tags = client.get("/api/search", params={"q": "P-1001"}).json()["items"]
    assert any(item["type"] == "Tag on a drawing" for item in tags)


def test_the_widgets_answer_in_the_shapes_app_toml_declares(runtime, client):
    _one(client, runtime)
    assert apptest.widget_problems(client, "") == []
    assert client.get("/api/widgets/count").json()["value"] == 1


def test_what_app_toml_contributes_is_wired(runtime):
    routes = apptest.api_routes(create_app(runtime))
    assert not apptest.contribution_problems(ROOT, "pidcraft", routes)
