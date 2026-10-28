"""Limits on how much one person asks API v1 for (``processcraft.api.usage``): a notebook, a
script or an assistant slows down its owner alone, never the apps of the suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from processcraft.api.identity import issue_service_token
from processcraft.auth.usage import Refusal, UsageStore
from processcraft.db import Database
from tests.test_route_permissions import ADMIN_PASSWORD, _login, app  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "notebooks" / "python"))
import plantcraft_notebook as pc  # noqa: E402

EDGE = {"X-PlantCraft-Edge": "1"}


def test_requests_wait_past_the_minute_and_past_the_reads_at_once(tmp_path):
    store = UsageStore(Database(tmp_path / "db.sqlite3"))
    slots = [store.begin("token:a", per_minute=3, concurrent=5, now=100.0 + i) for i in range(3)]
    assert all(isinstance(slot, str) for slot in slots)
    for slot in slots:
        store.end(slot, now=104.0)
    refused = store.begin("token:a", per_minute=3, concurrent=5, now=110.0)
    # Free again when the first request of the minute (at 100 s) leaves the window.
    assert refused == Refusal("rate", 50)
    assert isinstance(store.begin("token:b", per_minute=3, concurrent=5, now=110.0), str)
    assert isinstance(store.begin("token:a", per_minute=3, concurrent=5, now=160.5), str)

    first = store.begin("person:vera", per_minute=100, concurrent=1, now=200.0)
    assert store.begin("person:vera", per_minute=100, concurrent=1, now=201.0) == Refusal("busy", 1)
    store.end(first, now=202.0)
    assert isinstance(store.begin("person:vera", per_minute=100, concurrent=1, now=203.0), str)
    # A request a dead process left open stops counting after five minutes.
    assert isinstance(store.begin("person:vera", per_minute=100, concurrent=1, now=504.0), str)


def test_the_limits_are_an_administrators_and_stay_in_range(app):  # noqa: F811
    with TestClient(app):
        vera = _login(app, "vera", "vera-strong-password")
        limits = vera.get("/api/notebooks").json()["limits"]
        assert (limits["per_minute"], limits["concurrent"]) == (120, 2)
        assert (
            vera.put("/api/notebooks/limits", json={"per_minute": 60, "concurrent": 1}).status_code
            == 403
        )
        admin = _login(app, "admin", ADMIN_PASSWORD)
        assert (
            admin.put("/api/notebooks/limits", json={"per_minute": 5, "concurrent": 1}).status_code
            == 422
        )
        assert (
            admin.put("/api/notebooks/limits", json={"per_minute": 60, "concurrent": 0}).status_code
            == 422
        )
        saved = admin.put("/api/notebooks/limits", json={"per_minute": 60, "concurrent": 3}).json()
        assert (saved["per_minute"], saved["concurrent"], saved["updated_by"]) == (60, 3, "admin")
        rows = admin.get("/api/audit", params={"action": "notebooks.limits"}).json()["rows"]
    assert rows[0]["detail"] == {"per_minute": 60, "concurrent": 3}


def _token(app):  # noqa: F811
    admin = _login(app, "admin", ADMIN_PASSWORD)
    assert admin.put("/api/notebooks/settings", json={"enabled": True}).status_code == 200
    assert (
        admin.put("/api/notebooks/limits", json={"per_minute": 10, "concurrent": 2}).status_code
        == 200
    )
    vera = _login(app, "vera", "vera-strong-password")
    return (
        admin,
        vera,
        vera.post("/api/assistant-access/mine", json={"label": "laptop"}).json()["token"],
    )


def test_an_access_token_slows_down_alone_and_the_first_refusal_is_audited(app):  # noqa: F811
    with TestClient(app):
        admin, _vera, token = _token(app)
        reader = TestClient(app)
        bearer = {"Authorization": f"Bearer {token}"}
        assert all(reader.get("/api/v1/me", headers=bearer).status_code == 200 for _ in range(10))
        refused = reader.get("/api/v1/me", headers=bearer)
        assert refused.status_code == 429 and refused.json()["reason"] == "rate"
        assert 1 <= int(refused.headers["retry-after"]) <= 60
        assert "10 a minute" in refused.json()["detail"]
        assert reader.get("/api/v1/me", headers=bearer).status_code == 429
        # Another token of the same person, and the person's own pages, are not held back.
        other = _login(app, "vera", "vera-strong-password")
        second = other.post("/api/assistant-access/mine", json={"label": "desk"}).json()["token"]
        assert (
            reader.get("/api/v1/me", headers={"Authorization": f"Bearer {second}"}).status_code
            == 200
        )
        assert other.get("/api/v1/me").status_code == 200
        rows = admin.get("/api/audit", params={"action": "usage.limited"}).json()["rows"]
    assert len(rows) == 1 and rows[0]["username"] == "vera"
    assert rows[0]["detail"]["reason"] == "rate" and rows[0]["subject"] == "/api/v1/me"


def test_browser_reads_count_through_the_proxy_and_the_apps_never(app):  # noqa: F811
    with TestClient(app):
        _admin, vera, _token_unused = _token(app)
        signal = vera.get("/api/v1/signals").json()[0]["id"]
        path = f"/api/v1/signals/{signal}/series"
        # The apps call PlantCraft inside the network, without the proxy's mark: never counted.
        assert all(vera.get(path).status_code == 200 for _ in range(12))
        # The same reads from the person's browser, through the proxy, are.
        statuses = [vera.get(path, headers=EDGE).status_code for _ in range(11)]
        assert statuses[:10] == [200] * 10 and statuses[10] == 429
        # Other API v1 reads of the browser (the frame's inbox, the apps list) are not.
        assert vera.get("/api/v1/me", headers=EDGE).status_code == 200
        service = issue_service_token(app.state.runtime, "linkcraft", "no-such-key")["token"]
        headers = {**EDGE, "Authorization": f"Bearer {service}"}
        assert all(vera.get(path, headers=headers).status_code != 429 for _ in range(12))


def test_the_package_waits_when_asked_to_slow_down(monkeypatch):
    answers = [(429, '{"detail": "Too many requests"}', "3"), (200, '{"username": "vera"}', "")]
    waits: list[float] = []
    monkeypatch.setattr(pc.Client, "_computer", lambda self, method, path, body: answers.pop(0))
    monkeypatch.setattr(pc.time, "sleep", waits.append)
    pc.connect("http://testserver", token="pcat_x.y")
    with pytest.warns(UserWarning, match="slow down"):
        assert pc.me() == {"username": "vera"}
    assert waits == [3.0]

    monkeypatch.setattr(pc.Client, "_computer", lambda *_args: (429, '{"detail": "busy"}', "99"))
    with pytest.warns(UserWarning), pytest.raises(pc.PlantCraftError) as refused:
        pc.me()
    assert refused.value.status == 429 and waits[1:] == [pc.MAX_WAIT] * pc.RETRIES
