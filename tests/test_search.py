"""PlantCraft's part of the suite's search (Ctrl+K, docs/en/search.md): assets, people, groups
and the actions the person sees, in the shared format the frame reads."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_route_permissions import ADMIN_PASSWORD, _login, app  # noqa: F401


def test_search_finds_assets_people_and_only_visible_actions(app):  # noqa: F811
    with TestClient(app):
        admin = _login(app, "admin", ADMIN_PASSWORD)
        asset = admin.get("/api/assets").json()["items"][1]
        body = admin.get("/api/search", params={"q": asset["asset_id"]}).json()
        assert body["format"] == "plantcraft-search/1"
        hrefs = [item["href"] for item in body["items"]]
        assert f"/assets/{asset['asset_id']}" in hrefs
        assert all(set(item) == {"title", "detail", "type", "href"} for item in body["items"])

        people = admin.get("/api/search", params={"q": "vera"}).json()["items"]
        assert any(item["href"] == "/people/vera" for item in people)

        made = admin.post("/api/actions", json={"title": "Recalibrate zeta transmitter"})
        assert made.status_code in (200, 201), made.text
        found = admin.get("/api/search", params={"q": "zeta transmitter"}).json()["items"]
        assert [item["type"] for item in found] == ["Action"]
        vera = _login(app, "vera", "vera-strong-password")
        assert vera.get("/api/search", params={"q": "zeta transmitter"}).json()["items"] == []


def test_search_needs_two_letters_and_caps_its_answer(app):  # noqa: F811
    with TestClient(app):
        admin = _login(app, "admin", ADMIN_PASSWORD)
        assert admin.get("/api/search", params={"q": " a "}).json()["items"] == []
        assert len(admin.get("/api/search", params={"q": "a", "limit": 3}).json()["items"]) == 0
        many = admin.get("/api/search", params={"q": "un", "limit": 2}).json()["items"]
        assert len(many) <= 2
        assert admin.get("/api/search", params={"limit": 99}).status_code == 422
        assert TestClient(app).get("/api/search", params={"q": "vera"}).status_code == 401


def test_plantcraft_answers_the_queue_probe_with_no_queue(app):  # noqa: F811
    """The frame's queue indicator asks every app; PlantCraft says it holds none (no 404)."""

    with TestClient(app):
        response = _login(app, "admin", ADMIN_PASSWORD).get("/api/queue?window=1h")
        assert response.status_code == 200
        assert response.json() == {"format": "plantcraft-queue/1", "now": None, "history": []}
