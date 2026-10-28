"""A person sees only their part of the plant (docs/asset-scope.md, decision D2, 2026-10-27).

An administrator gives a person, or a group, the roots of the asset tree they see. Everything
the platform keeps about the plant follows: the tree, an asset's page, its signals and their
values, references, the search, and actions about those assets. The token carries the roots
(claim ``assets``) for the apps, and a change ends the tokens issued before it.
"""

from __future__ import annotations

import pytest

from processcraft.api.identity import issue_user_token
from tests.test_collaboration import (  # noqa: F401 (the fixture)
    _person,
    _publish_result,
    _specialist,
    _talk,
    signed,
)

SECRET = "Recalibrate the feed transmitter"


def _unit(client) -> None:
    """A second unit, U-200, with one loop, beside the demo's unit (where FIC-101 sits)."""

    rt = client.app.state.runtime
    root = rt.platform.root_asset_id
    for body in (
        {"asset_id": "U-200", "name": "Unit 200", "kind": "unit", "parent_id": root},
        {
            "asset_id": "TIC-201",
            "name": "Reactor temperature",
            "kind": "loop",
            "parent_id": "U-200",
        },
    ):
        response = client.post("/api/assets", json=body)
        assert response.status_code == 201, response.text


def _limited(client, username: str = "ana", roots: list[str] | None = None, level="editor"):
    person = _person(client, username, level)
    response = client.put(
        f"/api/users/{username}",
        json={
            "display_name": username.title(),
            "access_level": level,
            "asset_scope": roots if roots is not None else ["U-200"],
        },
    )
    assert response.status_code == 200, response.text
    return person


def _pv(client) -> str:
    """The id of a signal bound to FIC-101 only."""

    rt = client.app.state.runtime
    uses = rt.workspace.assets.signal_assets()
    tag = next(
        tag for tag, found in uses.items() if [use["asset_id"] for use in found] == ["FIC-101"]
    )
    return rt.platform.signal_catalog().find(tag)


def test_the_tree_and_an_asset_page_stop_at_the_persons_roots(signed):  # noqa: F811
    _unit(signed)
    ana = _limited(signed)

    tree = ana.get("/api/assets").json()
    ids = {item["asset_id"] for item in tree["items"]}
    assert ids == {"U-200", "TIC-201"}
    # The tree starts at the person's root: the site above it is not theirs to read.
    assert next(item for item in tree["items"] if item["asset_id"] == "U-200")["parent_id"] is None
    assert tree["root_id"] is None
    assert sum(kind["count"] for kind in tree["kinds"]) == 2

    assert ana.get("/api/assets/FIC-101").status_code == 404
    assert ana.get("/api/assets/FIC-101/signals").status_code == 404
    assert ana.get("/api/assets/FIC-101/situation").status_code == 404
    page = ana.get("/api/assets/TIC-201").json()
    assert [item["asset_id"] for item in page["path"]] == ["U-200", "TIC-201"]
    # Editing an asset out of reach is not possible either.
    response = ana.patch("/api/assets/FIC-101/attributes", json={"values": {}})
    assert response.status_code == 404

    # The administrator still sees the whole plant.
    assert {"FIC-101", "U-200"} <= {
        item["asset_id"] for item in signed.get("/api/assets").json()["items"]
    }


def test_signals_references_and_search_follow_the_scope(signed):  # noqa: F811
    _unit(signed)
    ana = _limited(signed)
    signal = _pv(signed)

    assert ana.get(f"/api/signals/{signal}/value").status_code == 404
    assert ana.get(f"/api/signals/{signal}/series").status_code == 404
    assert signed.get(f"/api/signals/{signal}/series").status_code != 404

    refs = ana.get("/api/refs", params={"ref": ["asset:FIC-101", "asset:TIC-201"]}).json()
    assert refs["asset:FIC-101"]["hidden"] is True
    assert "Feed" not in refs["asset:FIC-101"]["title"]
    assert refs["asset:TIC-201"]["title"] == "Reactor temperature"
    assert ana.get("/api/refs/asset:FIC-101/timeline").status_code == 404
    assert ana.get("/api/refs/asset:FIC-101/backlinks").status_code == 404

    found = ana.get("/api/search", params={"q": "FIC"}).json()["items"]
    assert not [item for item in found if "FIC-101" in item["href"]]
    found = signed.get("/api/search", params={"q": "FIC"}).json()["items"]
    assert [item for item in found if "FIC-101" in item["href"]]


def test_actions_about_assets_out_of_scope_are_hidden_unless_ones_own(signed):  # noqa: F811
    _unit(signed)
    eva = _person(signed, "eva")
    ana = _limited(signed)
    response = signed.post("/api/groups", json={"name": "Lab", "members": ["eva", "ana"]})
    assert response.status_code == 201, response.text
    outside = eva.post(
        "/api/actions", json={"title": SECRET, "group_id": "lab", "refs": ["asset:FIC-101"]}
    ).json()["action_id"]
    inside = eva.post(
        "/api/actions", json={"title": "Tune TIC-201", "group_id": "lab", "refs": ["asset:TIC-201"]}
    ).json()["action_id"]
    plain = eva.post("/api/actions", json={"title": "Order gaskets", "group_id": "lab"}).json()[
        "action_id"
    ]

    assert ana.get(f"/api/actions/{outside}").status_code == 404
    assert ana.get(f"/api/actions/{inside}").status_code == 200
    assert ana.get(f"/api/actions/{plain}").status_code == 200
    listed = {item["action_id"] for item in ana.get("/api/actions").json()["items"]}
    assert outside not in listed and {inside, plain} <= listed
    assert SECRET not in str(ana.get("/api/search", params={"q": "Recalibrate"}).json())
    # The group still works on it: eva sees it, and so does ana once it is hers.
    assert eva.get(f"/api/actions/{outside}").status_code == 200
    rt = signed.app.state.runtime
    rt.workspace.actions.update(
        outside, actor="eva", title=SECRET, owner="ana", group_id="lab", refs=["asset:FIC-101"]
    )
    assert ana.get(f"/api/actions/{outside}").status_code == 200


def test_a_group_scope_limits_its_members_and_never_widens_others(signed):  # noqa: F811
    _unit(signed)
    _person(signed, "bia", "viewer")
    _person(signed, "caio", "viewer")
    response = signed.post(
        "/api/groups",
        json={"name": "Contractor U-200", "members": ["bia"], "asset_scope": ["U-200"]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["asset_scope"] == ["U-200"]
    # A group without a scope adds nothing: caio sees the whole plant.
    assert (
        signed.post("/api/groups", json={"name": "Shift A", "members": ["bia", "caio"]}).status_code
        == 201
    )

    rt = signed.app.state.runtime
    assert rt.asset_scope("bia").roots == ("U-200",)
    assert rt.asset_scope("caio").everything
    accounts = {
        item["username"]: item for item in signed.get("/api/users/accounts").json()["users"]
    }
    assert accounts["bia"]["asset_roots"] == ["U-200"] and accounts["bia"]["asset_scope"] is None
    assert accounts["caio"]["asset_roots"] is None


def test_the_token_carries_the_roots_and_a_change_ends_older_tokens(signed):  # noqa: F811
    _unit(signed)
    _limited(signed)
    rt = signed.app.state.runtime
    token = issue_user_token(rt, "ana")["token"]
    assert rt.tokens.verify(token)["assets"] == ["U-200"]
    headers = {"Authorization": f"Bearer {token}"}
    assert signed.get("/api/v1/me", headers=headers).status_code == 200

    # A later second keeps the new token apart from the revocation.
    rt.workspace.users.revoke_tokens("ana")
    response = signed.put(
        "/api/users/ana",
        json={"display_name": "Ana", "access_level": "editor", "asset_scope": None},
    )
    assert response.status_code == 200
    assert signed.get("/api/v1/me", headers=headers).status_code == 401
    assert "assets" not in rt.tokens.verify(issue_user_token(rt, "ana")["token"])
    # Leaving the field out keeps the scope as it is.
    signed.put(
        "/api/users/ana",
        json={"display_name": "Ana", "access_level": "editor", "asset_scope": ["U-200"]},
    )
    signed.put("/api/users/ana", json={"display_name": "Ana", "access_level": "editor"})
    assert rt.workspace.users.get_user("ana")["asset_scope"] == ["U-200"]
    # An administrator is never limited, whatever is stored.
    assert "assets" not in rt.tokens.verify(issue_user_token(rt, "admin")["token"])


def test_joining_a_limited_group_ends_tokens_and_only_admins_change_its_members(signed):  # noqa: F811
    _unit(signed)
    eva = _person(signed, "eva")
    _person(signed, "bia", "viewer")
    response = signed.post(
        "/api/groups",
        json={"name": "Crew", "coordinator": "eva", "members": ["eva"], "asset_scope": ["U-200"]},
    )
    assert response.status_code == 201, response.text
    rt = signed.app.state.runtime
    before = rt.workspace.users.tokens_valid_after("bia")
    # The coordinator may not bring people in: joining changes what they see.
    response = eva.put("/api/groups/crew/members", json={"members": ["eva", "bia"]})
    assert response.status_code == 403
    response = signed.put("/api/groups/crew/members", json={"members": ["eva", "bia"]})
    assert response.status_code == 200
    assert rt.workspace.users.tokens_valid_after("bia") > before
    assert rt.asset_scope("bia").roots == ("U-200",)


@pytest.mark.parametrize("roots", [["nope"], ["U-200", "nope"]])
def test_an_unknown_root_is_refused(signed, roots):  # noqa: F811
    _unit(signed)
    _person(signed, "ana")
    response = signed.put(
        "/api/users/ana",
        json={"display_name": "Ana", "access_level": "editor", "asset_scope": roots},
    )
    assert response.status_code == 422
    assert "nope" in response.json()["detail"]


def _bearer(client, username: str) -> dict[str, str]:
    issued = issue_user_token(client.app.state.runtime, username)
    return {"Authorization": f"Bearer {issued['token']}"}


def test_api_v1_reads_only_the_scope_and_apps_read_everything(signed):  # noqa: F811
    _unit(signed)
    _limited(signed)
    ana = _bearer(signed, "ana")
    signal = _pv(signed)

    assets = signed.get("/api/v1/assets", headers=ana).json()
    assert {item["id"] for item in assets} == {"U-200", "TIC-201"}
    assert signed.get("/api/v1/assets/FIC-101", headers=ana).status_code == 404
    assert signal not in {item["id"] for item in signed.get("/api/v1/signals", headers=ana).json()}
    for path in ("", "/series", "/value"):
        assert signed.get(f"/api/v1/signals/{signal}{path}", headers=ana).status_code == 404
    batch = signed.post("/api/v1/series", json={"signals": [signal]}, headers=ana).json()
    assert batch["series"] == [] and batch["errors"][0]["status"] == 404
    explored = signed.get("/api/v1/explore", params={"q": "FIC"}, headers=ana).json()
    assert "FIC-101" not in str(explored)
    assert (
        signed.get("/api/v1/explore", params={"asset": "FIC-101"}, headers=ana).status_code == 404
    )

    # The administrator reads it all.
    admin = _bearer(signed, "admin")
    assert signal in {item["id"] for item in signed.get("/api/v1/signals", headers=admin).json()}
    assert signed.get("/api/v1/assets/FIC-101", headers=admin).status_code == 200
    # So does an app's own token: it computes for everyone.
    assert signed.app.state.runtime.asset_scope("app:linkcraft").everything


def test_a_specialist_answers_with_the_askers_part_of_the_plant(signed):  # noqa: F811
    _unit(signed)
    ana = _limited(signed)
    _specialist(signed, apps=["linkcraft"])
    _publish_result(signed, "asset:FIC-101")

    _id, messages = _talk(ana, "E a #asset:FIC-101?")
    assert "Valve stiction suspected" not in messages[-1]["text"]
    _id, messages = _talk(ana, "o que precisa de atenção?")
    assert "Valve stiction suspected" not in messages[-1]["text"]
    # The administrator, who sees the whole plant, reads it.
    _id, messages = _talk(signed, "E a #asset:FIC-101?")
    assert "Valve stiction suspected" in messages[-1]["text"]


def test_home_lists_only_results_about_the_persons_assets(signed):  # noqa: F811
    _unit(signed)
    ana = _limited(signed)
    _publish_result(signed, "asset:FIC-101")
    _publish_result(signed, "asset:TIC-201")
    subjects = {item["subject"] for item in ana.get("/api/home/attention").json()}
    assert subjects == {"asset:TIC-201"}
    subjects = {item["subject"] for item in signed.get("/api/home/attention").json()}
    assert {"asset:FIC-101", "asset:TIC-201"} <= subjects


def test_api_v1_results_history_and_runs_follow_the_scope(signed):  # noqa: F811
    _unit(signed)
    _limited(signed)
    ana = _bearer(signed, "ana")
    _publish_result(signed, "asset:FIC-101")
    _publish_result(signed, "asset:TIC-201")

    subjects = {item["subject"] for item in signed.get("/api/v1/results", headers=ana).json()}
    assert subjects == {"asset:TIC-201"}
    found = signed.get("/api/v1/results", params={"subject": "asset:FIC-101"}, headers=ana).json()
    assert found == []
    placed = signed.get("/api/v1/results", params={"group": "site"}, headers=ana).json()
    assert [item["group"] for item in placed] == [None]
    history = signed.get(
        "/api/v1/results/history", params={"subject": "asset:FIC-101"}, headers=ana
    )
    assert history.status_code == 404
    assert (
        signed.get(
            "/api/v1/results/history", params={"subject": "asset:TIC-201"}, headers=ana
        ).status_code
        == 200
    )
    events = signed.get("/api/v1/events", headers=ana).json()
    assert not [item for item in events if item["subject"] == "asset:FIC-101"]
    admin = {
        item["subject"]
        for item in signed.get("/api/v1/results", headers=_bearer(signed, "admin")).json()
    }
    assert {"asset:FIC-101", "asset:TIC-201"} <= admin
