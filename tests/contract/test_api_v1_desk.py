"""API v1's calendar feeds and to-dos: what an app puts in Desk (plantcraft_sdk.desk).

The fixture ``central`` is the one of ``test_api_v1.py``: ``op`` opens Link (``linkcraft``),
``nobody`` opens no app.
"""

from __future__ import annotations

from plantcraft_sdk.testing import FakePlantCraft
from tests.contract.test_api_v1 import _as, _rt
from tests.contract.test_api_v1_links import _service

DECLARES = {
    "version": "0.1.0",
    "contributes": {
        "calendar": [
            {"id": "reviews", "title": "Loop reviews"},
            {"id": "runs", "title": "Long runs", "visible": False},
        ],
        "todo": [{"id": "review", "title": "Review a loop"}],
    },
}


def _declared(central) -> dict[str, str]:
    headers = _service(central)
    assert central.put("/api/v1/contributions", json=DECLARES, headers=headers).status_code == 200
    return headers


def _sign_in(central, username: str) -> None:
    answer = central.post("/api/login", json={"username": username, "password": "password-123"})
    assert answer.status_code == 200, answer.text


def test_a_feed_is_replaced_whole_and_reaches_who_it_is_for_in_desk(central):
    headers = _declared(central)
    group = _rt(central).workspace.groups.create("Shift A", members=["op"])
    items = [
        {"id": "1", "title": "Review FIC-101", "start": "2026-11-03", "all_day": True},
        {
            "id": "2",
            "title": "Review TIC-7",
            "start": "2026-11-04T09:00:00Z",
            "end": "2026-11-04T10:00:00Z",
            "audience": f"group:{group['group_id']}",
            "url": "/link/loops/7",
            "ref": "asset:tic-7",
        },
        {"id": "3", "title": "Someone else's", "start": "2026-11-05", "all_day": True,
         "audience": "user:eng"},
    ]  # fmt: skip
    put = central.put("/api/v1/calendar/reviews", json=items, headers=headers)
    assert put.status_code == 200, put.text
    assert put.json() == {"app": "linkcraft", "feed": "reviews", "items": 3}
    _sign_in(central, "op")
    answer = central.get("/api/desk/calendar?start=2026-11-01&end=2026-11-30").json()
    feeds = {feed["id"]: feed for feed in answer["feeds"]}
    assert feeds["linkcraft:reviews"]["visible"] is True
    assert feeds["linkcraft:runs"]["visible"] is False
    mine = [event for event in answer["events"] if event["kind"] == "feed"]
    assert [event["title"] for event in mine] == ["Review FIC-101", "Review TIC-7"]
    assert mine[1]["href"] == "/link/loops/7" and mine[1]["feed"] == "linkcraft:reviews"
    # Replaced whole: what the app stops sending is gone.
    assert (
        central.put("/api/v1/calendar/reviews", json=items[:1], headers=headers).status_code == 200
    )
    answer = central.get("/api/desk/calendar?start=2026-11-01&end=2026-11-30").json()
    assert [event["title"] for event in answer["events"] if event["kind"] == "feed"] == [
        "Review FIC-101"
    ]
    # A person who does not open the app sees none of it.
    _sign_in(central, "nobody")
    answer = central.get("/api/desk/calendar?start=2026-11-01&end=2026-11-30").json()
    assert answer["feeds"] == [] and not [e for e in answer["events"] if e["kind"] == "feed"]


def test_a_feed_or_an_item_outside_the_rules_is_refused(central):
    headers = _declared(central)
    day = {"id": "1", "title": "x", "start": "2026-11-03", "all_day": True}
    for feed, body, status in (
        ("nope", [day], 422),  # not declared
        ("reviews", [day, day], 422),  # the same id twice
        ("reviews", [{**day, "all_day": False}], 422),  # a day without all_day
        ("reviews", [{**day, "audience": "people"}], 422),
        ("reviews", [{**day, "url": "/other/x"}], 422),  # outside the app's prefix
        ("reviews", [{**day, "id": str(n)} for n in range(2001)], 422),
    ):
        answer = central.put(f"/api/v1/calendar/{feed}", json=body, headers=headers)
        assert answer.status_code == status, (feed, answer.text)
    # A person writes for an app only with editor access to it.
    assert (
        central.put(
            "/api/v1/calendar/reviews?app=linkcraft", json=[day], headers=_as(central, "op")
        ).status_code
        == 403
    )


def test_an_app_gives_a_to_do_the_person_ticks_it_and_the_app_reads_it_back(central):
    headers = _declared(central)
    todo = {"key": "loop:7", "kind": "review", "title": "Review TIC-7", "for": "user:op",
            "due": "2026-01-01", "url": "/link/loops/7"}  # fmt: skip
    made = central.post("/api/v1/todos", json=todo, headers=headers)
    assert made.status_code == 200, made.text
    assert made.json()["done"] is False and made.json()["for"] == "user:op"
    # The same key changes it, never makes a second one.
    changed = central.post(
        "/api/v1/todos", json={**todo, "title": "Review TIC-7 now"}, headers=headers
    )
    assert changed.json()["title"] == "Review TIC-7 now"
    assert len(central.get("/api/v1/todos", headers=headers).json()) == 1
    _sign_in(central, "op")
    view = central.get("/api/desk/todos?view=today").json()
    assert view["counts"]["apps"] == 1
    [due] = view["app_todos"]
    assert due["app_name"] and due["kind_title"] == "Review a loop"
    ticked = central.post("/api/desk/app-todos/linkcraft/loop:7", json={"done": True})
    assert ticked.status_code == 200 and ticked.json()["done_by"] == "op"
    [back] = central.get("/api/v1/todos?state=done", headers=headers).json()
    assert back["key"] == "loop:7" and back["done_by"] == "op"
    # Sent again, a done to-do stays done; the app closes it and it is gone.
    again = central.post("/api/v1/todos", json=todo, headers=headers)
    assert again.json()["done"] is True
    close = {"keys": ["loop:7", "ghost"]}
    assert central.post("/api/v1/todos/close", json=close, headers=headers).json()["closed"] == 1
    assert central.post("/api/v1/todos/close", json=close, headers=headers).json()["closed"] == 0
    assert central.get("/api/desk/todos?view=apps").json()["app_todos"] == []


def test_a_to_do_outside_the_rules_is_refused_and_nobody_else_ticks_it(central):
    headers = _declared(central)
    todo = {"key": "k", "kind": "review", "title": "x", "for": "user:op"}
    for body in (
        {**todo, "kind": "nope"},
        {**todo, "for": "everyone"},
        {**todo, "for": "user:ghost"},
        {**todo, "for": "group:ghost"},
        {**todo, "due": "tomorrow"},
    ):
        assert central.post("/api/v1/todos", json=body, headers=headers).status_code == 422, body
    assert central.post("/api/v1/todos", json=todo, headers=headers).status_code == 200
    _sign_in(central, "nobody")
    assert central.post("/api/desk/app-todos/linkcraft/k", json={"done": True}).status_code == 404


def test_an_app_gives_one_person_200_open_to_dos_at_most(central, monkeypatch):
    from processcraft.desk import app_items

    monkeypatch.setattr(app_items, "MAX_OPEN_TODOS", 2)
    headers = _declared(central)
    todo = {"kind": "review", "title": "x", "for": "user:op"}
    for key in ("a", "b"):
        assert (
            central.post("/api/v1/todos", json={**todo, "key": key}, headers=headers).status_code
            == 200
        )
    assert (
        central.post("/api/v1/todos", json={**todo, "key": "c"}, headers=headers).status_code == 429
    )
    # Changing one already there is never refused.
    assert (
        central.post("/api/v1/todos", json={**todo, "key": "a"}, headers=headers).status_code == 200
    )


def test_the_fake_holds_an_app_to_the_same_rules():
    fake = FakePlantCraft()
    client = fake.client(app="linkcraft", key=fake.app_keys["linkcraft"])
    client.put_contributions(DECLARES)
    assert (
        client.put_calendar(
            "reviews", [{"id": "1", "title": "x", "start": "2026-11-03", "all_day": True}]
        )["items"]
        == 1
    )
    assert fake.links.calendar[("linkcraft", "reviews")][0]["audience"] == "everyone"
    client.put_todo({"key": "loop:7", "kind": "review", "title": "Review", "for": "user:op"})
    fake.tick_todo("linkcraft", "loop:7", "op")
    [item] = client.todos("done")
    assert item["done_by"] == "op"
    assert client.close_todos(["loop:7"])["closed"] == 1
    assert client.todos() == []
