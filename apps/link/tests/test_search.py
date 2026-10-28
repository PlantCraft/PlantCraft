"""Link's part of the suite's search (Ctrl+K): loops, algorithms and blocks."""

from __future__ import annotations

from tests.conftest import client_for


def test_search_finds_loops_algorithms_and_blocks(analysed, fake):
    loop = analysed.loops.list_loops()[0]
    with client_for(analysed, fake) as client:
        body = client.get("/link/api/search", params={"q": loop.loop_id}).json()
        assert body["format"] == "plantcraft-search/1"
        assert body["items"][0] == {
            "title": loop.loop_id,
            "detail": " · ".join(part for part in (loop.name, loop.area) if part),
            "type": "Loop",
            "href": f"/loops/{loop.loop_id}",
        }
        profile = analysed.presets.list_profiles()[0]
        hrefs = [
            item["href"]
            for item in client.get(
                "/link/api/search", params={"q": profile["name"], "limit": 20}
            ).json()["items"]
        ]
        assert f"/algorithms/{profile['profile_id']}" in hrefs
        blocks = client.get("/link/api/search", params={"q": "harris"}).json()["items"]
        assert any(
            item["type"] == "Block" and item["href"].startswith("/blocks/") for item in blocks
        )
        assert client.get("/link/api/search", params={"q": "x"}).json()["items"] == []


def test_search_needs_a_sign_in(runtime, fake):
    with client_for(runtime, fake) as client:
        client.headers.pop("Authorization")
        assert client.get("/link/api/search", params={"q": "fic"}).status_code == 401
