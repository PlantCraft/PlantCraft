# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""Round 5: an action's checklist and mentions, people's profiles and their role in each app."""

from __future__ import annotations

from tests.test_collaboration import _asset_id, _person, signed  # noqa: F401


def test_a_checklist_is_kept_with_its_history(signed, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_TRANSLATIONS", "1")
    _person(signed, "ana")
    action = signed.post("/api/actions", json={"title": "Tune FIC-101"}).json()
    base = f"/api/actions/{action['action_id']}/items"
    first = signed.post(base, json={"text": "Step test", "owner": "ana", "due_at": "2026-10-20"})
    assert first.status_code == 201, first.text
    signed.post(base, json={"text": "New tuning"})
    items = first.json()["items"]
    assert items[0]["owner_name"] == "Ana" and items[0]["overdue"] and not items[0]["done"]
    item_id = items[0]["item_id"]
    ticked = signed.patch(f"{base}/{item_id}", json={"done": True}).json()
    assert ticked["items"][0]["done"] and ticked["items"][0]["done_by"] == "admin"
    assert not ticked["items"][0]["overdue"]
    listed = signed.get("/api/actions").json()["items"][0]
    assert listed["checklist"] == {"total": 2, "done": 1}
    texts = [entry["text"] for entry in ticked["history"] if entry["kind"] == "checklist"]
    assert texts == [
        "Checklist, added: Step test",
        "Checklist, added: New tuning",
        "Checklist, done: Step test",
    ]
    # Read in Portuguese, the same history speaks Portuguese.
    pt = signed.get(f"/api/actions/{action['action_id']}", headers={"X-Language": "pt-BR"}).json()
    assert (
        pt["history"][1]["text"].startswith("Checklist") and "Step test" in pt["history"][1]["text"]
    )
    removed = signed.delete(f"{base}/{item_id}").json()
    assert [item["text"] for item in removed["items"]] == ["New tuning"]
    assert signed.patch(f"{base}/999", json={"done": True}).status_code == 404
    assert signed.post(base, json={"text": "x", "owner": "nobody"}).status_code == 422
    assert signed.post(base, json={"text": " "}).status_code == 422


def test_viewers_read_but_do_not_tick_items(signed):
    viewer = _person(signed, "leo", level="viewer")
    # Leo's own action: he sees it (an action reaches its owner, groups and leaders only).
    action = signed.post("/api/actions", json={"title": "Review", "owner": "leo"}).json()
    base = f"/api/actions/{action['action_id']}/items"
    item = signed.post(base, json={"text": "Read the report"}).json()["items"][0]
    assert viewer.patch(f"{base}/{item['item_id']}", json={"done": True}).status_code == 403
    assert (
        viewer.get(f"/api/actions/{action['action_id']}").json()["items"][0]["text"]
        == "Read the report"
    )


def test_mentions_in_the_description_and_comments_resolve(signed):
    _person(signed, "ana")
    asset = _asset_id(signed)
    action = signed.post(
        "/api/actions",
        json={"title": "Check", "description": f"See #asset:{asset} with #user:ana."},
    ).json()
    mentions = {item["ref"]: item for item in action["mentions"]}
    assert mentions[f"asset:{asset}"]["href"] == f"/assets/{asset}"
    assert mentions["user:ana"]["href"] == "/people/ana" and mentions["user:ana"]["title"] == "Ana"
    commented = signed.post(
        f"/api/actions/{action['action_id']}/comments", json={"text": "Also #action:1"}
    ).json()
    assert "action:1" in {item["ref"] for item in commented["mentions"]}


def test_archived_is_the_name_of_cancelled(signed):
    statuses = {item["id"]: item["label"] for item in signed.get("/api/actions").json()["statuses"]}
    assert statuses["cancelled"] == "Archived"


def test_people_keep_their_own_profile_and_others_see_it(signed):
    ana = _person(signed, "ana", level="viewer")
    profile = {
        "job_title": "Process engineer",
        "affiliation": "external",
        "organization": "Partner Engineering",
        "email": "ana@example.com",
        "phone": "+55 11 5555-0000",
        "unit": "U-200",
    }
    saved = ana.put(
        "/api/me/profile",
        json={"display_name": "Ana Lima", "role": "Process engineering", "profile": profile},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["profile"] == profile and saved.json()["is_me"]
    assert saved.json()["access"]["access_level"] == "viewer"
    # Colleagues see the profile, not the access, and only the actions they may see.
    signed.post("/api/actions", json={"title": "Report", "owner": "ana"})
    leo = _person(signed, "leo", level="viewer")
    card = leo.get("/api/people/ana").json()
    assert card["display_name"] == "Ana Lima" and card["profile"]["email"] == "ana@example.com"
    assert card["actions"] == [] and "access" not in card
    # Administrators see it all.
    admin_card = signed.get("/api/people/ana").json()
    assert admin_card["access"]["profile"]["unit"] == "U-200"
    assert [item["title"] for item in admin_card["actions"]] == ["Report"]
    bad = ana.put(
        "/api/me/profile", json={"display_name": "Ana", "profile": {"email": "not an email"}}
    )
    assert bad.status_code == 422
    assert leo.get("/api/people/nobody").status_code == 404


def test_a_role_per_app_goes_into_the_token(signed):
    _person(signed, "ana", level="editor")
    accounts = signed.get("/api/users/accounts").json()
    ana = next(user for user in accounts["users"] if user["username"] == "ana")
    body = {key: ana[key] for key in ("display_name", "role", "access_level", "applications")}
    saved = signed.put("/api/users/ana", json={**body, "app_roles": {"dashcraft": "viewer"}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["app_roles"] == {"dashcraft": "viewer"}
    rt = signed.app.state.runtime
    from plantcraft.api.identity import user_claims

    assert user_claims(rt, "ana")["apps"] == {"linkcraft": "editor", "dashcraft": "viewer"}
    # Leaving app_roles out keeps them; an unknown app or role is refused.
    signed.put("/api/users/ana", json=body)
    assert user_claims(rt, "ana")["apps"]["dashcraft"] == "viewer"
    assert (
        signed.put("/api/users/ana", json={**body, "app_roles": {"nope": "viewer"}}).status_code
        == 422
    )
    assert (
        signed.put("/api/users/ana", json={**body, "app_roles": {"dashcraft": "admin"}}).status_code
        == 422
    )
    # A viewer may edit in one app.
    signed.put(
        "/api/users/ana",
        json={**body, "access_level": "viewer", "app_roles": {"linkcraft": "editor"}},
    )
    assert user_claims(rt, "ana")["apps"] == {"linkcraft": "editor", "dashcraft": "viewer"}
    card = signed.get("/api/people/ana").json()
    assert {item["application_id"]: item["role"] for item in card["apps"]} == {
        "linkcraft": "editor",
        "dashcraft": "viewer",
    }
