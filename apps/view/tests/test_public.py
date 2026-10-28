"""Public links open one dashboard, read-only, without sign-in, until revoked."""

from __future__ import annotations

from datetime import datetime

from tests.conftest import client_for, dashboard, kpi, make_runtime


def _shared(client) -> tuple[dict, dict]:
    created = client.post("/dash/api/dashboards", json=dashboard()).json()
    share = client.post(
        f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={"label": "Wall"}
    )
    assert share.status_code == 201
    return created, share.json()


def _token(share: dict) -> str:
    assert share["path"].startswith("/dash/share/")
    return share["path"].rsplit("/", 1)[-1]


def test_a_link_opens_its_dashboard_without_sign_in(runtime, fake, client):
    created, share = _shared(client)
    token = _token(share)
    with client_for(runtime, fake, None) as anonymous:
        opened = anonymous.get(f"/dash/api/public/{token}")
        assert opened.status_code == 200
        assert opened.json()["name"] == "Feed" and "created_by" not in opened.json()
        data = anonymous.get(f"/dash/api/public/{token}/cards/k1").json()
        assert data["rows"][0]["value"] is not None
        # Nothing else is open: other routes still need a token.
        assert anonymous.get("/dash/api/dashboards").status_code == 401
        assert anonymous.get(f"/dash/api/dashboards/{created['dashboard_id']}").status_code == 401
    listed = client.get(f"/dash/api/dashboards/{created['dashboard_id']}/shares").json()
    assert [item["label"] for item in listed] == ["Wall"] and "path" not in listed[0]
    assert [row["action"] for row in fake.audit_log][-1] == "dashcraft.share.create"


def test_revoked_or_deleted_links_stop_at_once(runtime, fake, client):
    created, share = _shared(client)
    token = _token(share)
    with client_for(runtime, fake, None) as anonymous:
        base = f"/dash/api/dashboards/{created['dashboard_id']}"
        assert client.delete(f"{base}/shares/{share['share_id']}").status_code == 204
        assert anonymous.get(f"/dash/api/public/{token}").status_code == 404
        assert client.delete(f"{base}/shares/{share['share_id']}").status_code == 404
        _, again = _shared(client)
        token = _token(again)
        other = client.get("/dash/api/dashboards").json()[0]["dashboard_id"]
        client.delete(f"/dash/api/dashboards/{other}")
        assert anonymous.get(f"/dash/api/public/{token}").status_code == 404
        assert anonymous.get("/dash/api/public/made-up-token").status_code == 404


def test_a_link_only_shows_its_dashboards_kind_of_asset(runtime, fake, client):
    created = client.post(
        "/dash/api/dashboards",
        json=dashboard(context_kind="pump", cards=[kpi(asset_id="$context", role="flow")]),
    ).json()
    share = client.post(f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={})
    token = _token(share.json())
    with client_for(runtime, fake, None) as anonymous:
        assert [
            item["id"] for item in anonymous.get(f"/dash/api/public/{token}/context").json()
        ] == ["p-201"]
        ok = anonymous.get(f"/dash/api/public/{token}/cards/k1", params={"context": "p-201"})
        assert ok.json()["rows"][0]["signal"] == "fake:P-201.FLOW"
        refused = anonymous.get(f"/dash/api/public/{token}/cards/k1", params={"context": "fic-101"})
        assert refused.status_code == 422


def test_links_can_be_turned_off(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake, public_links=False)
    with client_for(runtime, fake) as client:
        created = client.post("/dash/api/dashboards", json=dashboard()).json()
        refused = client.post(f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={})
        assert refused.status_code == 403
        # A link made while they were on stops working when they are turned off.
        _, token = runtime.dashboards.create_share(created["dashboard_id"], "engineer")
        assert client.get(f"/dash/api/public/{token}").status_code == 404


def test_a_link_shows_every_page_of_its_dashboard(runtime, fake, client):
    pages = [{"page_id": "p1", "name": "Overview"}, {"page_id": "p2", "name": "Pumps"}]
    cards = [kpi("k1"), {**kpi("k2"), "page_id": "p2"}]
    created = client.post(
        "/dash/api/dashboards", json=dashboard(pages=pages, page_seconds=30, cards=cards)
    ).json()
    share = client.post(f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={}).json()
    with client_for(runtime, fake, None) as anonymous:
        opened = anonymous.get(f"/dash/api/public/{_token(share)}").json()
        assert opened["pages"] == pages and opened["page_seconds"] == 30
        assert [card["page_id"] for card in opened["cards"]] == [None, "p2"]
        data = anonymous.get(f"/dash/api/public/{_token(share)}/cards/k2").json()
        assert data["rows"][0]["value"] is not None


def test_a_link_lasts_90_days_unless_an_administrator_says_otherwise(runtime, fake, client):
    """Review decision D4 (2026-10-27): a link forgotten in an old e-mail stops by itself."""

    created, share = _shared(client)
    days = (
        datetime.fromisoformat(share["expires_at"]) - datetime.fromisoformat(share["created_at"])
    ).days
    assert days == 90
    base = f"/dash/api/dashboards/{created['dashboard_id']}/shares"
    # "Until revoked" (a control room screen) is an administrator's; an editor picks days.
    assert client.post(base, json={"label": "Wall", "days": None}).status_code == 403
    assert client.post(base, json={"days": 7}).status_code == 201
    assert client.post(base, json={"days": 0}).status_code == 422
    # Past its day the link opens nothing and leaves the lists.
    with runtime.dashboards._connect() as connection:
        connection.execute(
            "UPDATE dashboard_shares SET expires_at = '2000-01-01T00:00:00.000+00:00' "
            "WHERE share_id = ?",
            (share["share_id"],),
        )
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get(f"/dash/api/public/{_token(share)}").status_code == 404
    assert share["share_id"] not in {item["share_id"] for item in client.get(base).json()}
    # Only an administrator reviews every link of the installation, and revokes any.
    assert client.get("/dash/api/shares").status_code == 403
    with client_for(runtime, fake, "admin") as admin:
        forever = admin.post(base, json={"label": "Control room", "days": None})
        assert forever.status_code == 201 and forever.json()["expires_at"] is None
        listed = admin.get("/dash/api/shares").json()
        assert {item["name"] for item in listed} == {"Feed"} and len(listed) == 2
        assert admin.delete(f"/dash/api/shares/{forever.json()['share_id']}").status_code == 204
        assert len(admin.get("/dash/api/shares").json()) == 1
