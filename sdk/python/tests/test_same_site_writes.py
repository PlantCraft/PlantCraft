"""Apps refuse a write sent with the cookie from another site, as the platform does."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plantcraft_sdk.server.origin import SameSiteWrites


def _client() -> TestClient:
    api = FastAPI()

    @api.post("/api/things")
    def create() -> dict[str, bool]:
        return {"ok": True}

    @api.get("/api/things")
    def read() -> dict[str, bool]:
        return {"ok": True}

    api.add_middleware(SameSiteWrites)
    return TestClient(api)


def test_writes_from_another_site_are_refused():
    client = _client()
    for site in ("same-site", "cross-site"):
        assert client.post("/api/things", headers={"Sec-Fetch-Site": site}).status_code == 403


def test_own_pages_scripts_and_reads_pass():
    client = _client()
    assert client.post("/api/things", headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200
    assert client.post("/api/things").status_code == 200
    bearer = {"Sec-Fetch-Site": "cross-site", "Authorization": "Bearer x"}
    assert client.post("/api/things", headers=bearer).status_code == 200
    assert client.get("/api/things", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
