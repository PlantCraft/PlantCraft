"""A public demo visit in an app: editors shown, nothing saved, a few requests at once."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from plantcraft_sdk.contract import TOKEN_COOKIE
from plantcraft_sdk.server.access import Access
from plantcraft_sdk.server.demo import DemoVisitLimit, demo_of
from plantcraft_sdk.server.files import AppFiles
from plantcraft_sdk.server.web import mount, suite_api
from plantcraft_sdk.testing import FakePlantCraft

ACCESS = Access("Demo")
router = APIRouter()
VISIT = {"visit": "v1", "ends": 2_000_000_000, "queries": 2, "queries_total": 3}


@router.post("/api/things")
def make_thing(user: ACCESS.EditorUser) -> dict:
    return {"by": user.username}


@pytest.fixture()
def client(tmp_path):
    fake = FakePlantCraft()
    (tmp_path / "app.toml").write_text('[app]\nid = "demoapp"\nname = "Demo"\n')
    runtime = SimpleNamespace(
        settings=SimpleNamespace(root_path="/demo", processcraft_public_url="/"),
        verifier=fake.verifier("linkcraft"),
        shutdown=lambda: None,
    )
    api = suite_api(
        runtime,
        title="Demo",
        version="0.1.0",
        files=AppFiles("demoapp", tmp_path),
        routers=[router],
        status_route=False,
    )
    return fake, TestClient(mount(api, runtime, version="0.1.0"))


def test_a_visitor_sees_the_editors_but_saves_nothing(client):
    fake, http = client
    visitor = {"Authorization": f"Bearer {fake.token('operator', demo=VISIT)}"}
    me = http.get("/demo/api/me", headers=visitor).json()
    assert me["can_edit"] is True and me["access"] == "editor"
    assert me["demo"] == {"ends": VISIT["ends"]}
    refused = http.post("/demo/api/things", headers=visitor)
    assert refused.status_code == 403 and "nothing is saved" in refused.json()["detail"]
    # Anyone else: as before.
    operator = {"Authorization": f"Bearer {fake.token('operator')}"}
    assert http.get("/demo/api/me", headers=operator).json()["demo"] is None
    assert http.post("/demo/api/things", headers=operator).json()["detail"].endswith("read-only.")


def test_the_claim_is_read_only_when_it_names_a_visit():
    assert demo_of({"demo": VISIT}) == VISIT
    assert demo_of({"demo": {"ends": 1}}) is None and demo_of({}) is None and demo_of(None) is None


def _app(state):
    async def app(scope, receive, send):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.05)
        state["now"] -= 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return app


def _token(fake, visit):
    return fake.token("operator", demo={**VISIT, "visit": visit})


async def _burst(limit, cookies_list, path="/demo/api/series"):
    transport = httpx.ASGITransport(app=limit)
    async with httpx.AsyncClient(transport=transport, base_url="http://app") as http:
        answers = await asyncio.gather(
            *(
                http.get(path, headers={"cookie": f"{TOKEN_COOKIE}={cookie}"})
                for cookie in cookies_list
            )
        )
    return [answer.status_code for answer in answers]


def test_a_visit_has_a_few_requests_in_flight_and_all_visits_a_few_more():
    fake = FakePlantCraft()
    state = {"now": 0, "peak": 0}
    limit = DemoVisitLimit(_app(state))
    one = _token(fake, "v1")
    assert asyncio.run(_burst(limit, [one] * 6)) == [200] * 6
    assert state["peak"] == 2
    state["peak"] = 0
    many = [_token(fake, f"v{n}") for n in range(6)]
    assert asyncio.run(_burst(limit, many)) == [200] * 6
    assert state["peak"] == 3
    assert limit._visits == {}


def test_over_the_wait_a_request_gets_a_429_and_others_are_not_held():
    fake = FakePlantCraft()
    state = {"now": 0, "peak": 0}
    limit = DemoVisitLimit(_app(state), wait_seconds=0.01)
    codes = asyncio.run(_burst(limit, [_token(fake, "v1")] * 4))
    assert codes.count(200) == 2 and codes.count(429) == 2
    state["peak"] = 0
    # No demo claim, or not the API: never counted.
    plain = fake.token("operator")
    assert asyncio.run(_burst(limit, [plain] * 5)) == [200] * 5
    assert state["peak"] == 5
    assert (
        asyncio.run(_burst(limit, [_token(fake, "v1")] * 4, path="/demo/static/a.js")) == [200] * 4
    )
