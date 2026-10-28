"""Lists in pages and answers that did not change (scale review E2, 2026-10-25)."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from plantcraft_sdk import client as client_module  # noqa: E402
from plantcraft_sdk.client import PlantCraftClient  # noqa: E402
from plantcraft_sdk.server.paging import NEXT_CURSOR, list_response  # noqa: E402

SIGNALS = [{"id": f"src:tag-{index:05d}", "name": f"tag-{index:05d}"} for index in range(12)]


def plant(seen: list[dict]) -> TestClient:
    app = FastAPI()

    @app.get("/api/v1/signals")
    def signals(request: Request, limit: int | None = None, cursor: str | None = None):
        seen.append(
            {"limit": limit, "cursor": cursor, "etag": request.headers.get("if-none-match")}
        )
        return list_response(request, list(reversed(SIGNALS)), limit=limit, cursor=cursor)

    return TestClient(app)


def test_a_list_comes_in_pages_in_id_order():
    http = plant([])
    first = http.get("/api/v1/signals", params={"limit": 5})
    assert [item["id"] for item in first.json()] == [item["id"] for item in SIGNALS[:5]]
    assert first.headers["X-Total-Count"] == "12"
    second = http.get("/api/v1/signals", params={"limit": 5, "cursor": first.headers[NEXT_CURSOR]})
    third = http.get("/api/v1/signals", params={"limit": 5, "cursor": second.headers[NEXT_CURSOR]})
    assert [item["id"] for item in third.json()] == [item["id"] for item in SIGNALS[10:]]
    assert NEXT_CURSOR not in third.headers
    # Without limit nor cursor the whole list, as before.
    assert len(http.get("/api/v1/signals").json()) == 12
    assert http.get("/api/v1/signals", params={"cursor": "%%%"}).status_code == 422


def test_an_unchanged_list_is_a_304_and_the_client_keeps_its_answer(monkeypatch):
    seen: list[dict] = []
    http = plant(seen)
    whole = http.get("/api/v1/signals")
    again = http.get("/api/v1/signals", headers={"If-None-Match": whole.headers["ETag"]})
    assert again.status_code == 304 and again.content == b""

    monkeypatch.setattr(client_module, "PAGE_SIZE", 5)
    client = PlantCraftClient("http://testserver", "token", http_client=http)
    found = client.signals()
    assert [item["id"] for item in found] == [item["id"] for item in SIGNALS]
    assert [call["limit"] for call in seen[2:]] == [5, 5, 5]
    found[0]["name"] = "changed by the caller"
    again = client.signals()
    assert again == SIGNALS  # every page a 304, read from the kept bytes
    assert all(call["etag"] for call in seen[5:])
