"""Diagrams outside their own page: a public link (read-only, no sign-in, until revoked or
expired) and a dashboard's diagram card (live, as its viewer may see the diagram's folder)."""

from __future__ import annotations

from tests.conftest import client_for, dashboard, kpi, make_runtime
from tests.test_diagrams import unit


def _diagram(client, **fields) -> str:
    created = client.post("/dash/api/diagrams", json=unit(**fields))
    assert created.status_code == 201, created.text
    return created.json()["diagram_id"]


def _token(share: dict) -> str:
    assert share["path"].startswith("/dash/share/diagram/")
    return share["path"].rsplit("/", 1)[-1]


def _closed_folder(client) -> str:
    folder = client.post(
        "/dash/api/folders", json={"name": "Engineering", "viewers": ["user:engineer"]}
    )
    assert folder.status_code == 201, folder.text
    return folder.json()["folder_id"]


def diagram_card(diagram_id: str, card_id: str = "dg", **fields) -> dict:
    return {
        "card_id": card_id,
        "kind": "diagram",
        "diagram_id": diagram_id,
        "width": 6,
        "height": 4,
        **fields,
    }


# Public links ------------------------------------------------------------------------------


def test_a_link_opens_its_diagram_live_and_played_back_without_sign_in(runtime, fake, client):
    diagram_id = _diagram(client)
    made = client.post(f"/dash/api/diagrams/{diagram_id}/shares", json={"label": "Wall"})
    assert made.status_code == 201, made.text
    token = _token(made.json())
    with client_for(runtime, fake, None) as anonymous:
        opened = anonymous.get(f"/dash/api/public/diagram/{token}")
        assert opened.status_code == 200
        body = opened.json()
        assert body["name"] == "Feed section" and "created_by" not in body
        # The symbols it draws come with it: the page needs no library route.
        assert {item["id"] for item in body["symbols"]} == {
            "vessel.tank",
            "pump.centrifugal",
            "instrument.bubble",
        }
        live = anonymous.get(f"/dash/api/public/diagram/{token}/data").json()
        assert live["range"]["live"] is True
        assert any(row["element"] == "pv" and row["value"] is not None for row in live["bindings"])
        past = anonymous.get(
            f"/dash/api/public/diagram/{token}/data",
            params={"window": "8h", "end": "2026-10-20T08:00:00Z"},
        ).json()
        assert past["range"]["live"] is False
        assert (
            anonymous.get(
                f"/dash/api/public/diagram/{token}/data", params={"window": "soon"}
            ).status_code
            == 422
        )
        # The link opens this diagram only: not the diagram routes, nor as a dashboard.
        assert anonymous.get(f"/dash/api/diagrams/{diagram_id}").status_code == 401
        assert anonymous.get(f"/dash/api/public/{token}").status_code == 404
    listed = client.get(f"/dash/api/diagrams/{diagram_id}/shares").json()
    assert [item["label"] for item in listed] == ["Wall"] and "path" not in listed[0]
    assert [row["action"] for row in fake.audit_log][-1] == "dashcraft.diagram.share.create"


def test_a_dashboard_link_does_not_open_a_diagram(runtime, fake, client):
    created = client.post("/dash/api/dashboards", json=dashboard()).json()
    share = client.post(f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={})
    token = share.json()["path"].rsplit("/", 1)[-1]
    with client_for(runtime, fake, None) as anonymous:
        assert anonymous.get(f"/dash/api/public/diagram/{token}").status_code == 404
        assert anonymous.get("/dash/api/public/diagram/made-up").status_code == 404


def test_revoked_or_deleted_diagram_links_stop_at_once(runtime, fake, client):
    diagram_id = _diagram(client)
    base = f"/dash/api/diagrams/{diagram_id}/shares"
    first = client.post(base, json={}).json()
    second = client.post(base, json={}).json()
    with client_for(runtime, fake, None) as anonymous:
        assert client.delete(f"{base}/{first['share_id']}").status_code == 204
        assert anonymous.get(f"/dash/api/public/diagram/{_token(first)}").status_code == 404
        assert client.delete(f"{base}/{first['share_id']}").status_code == 404
        assert anonymous.get(f"/dash/api/public/diagram/{_token(second)}").status_code == 200
        assert client.delete(f"/dash/api/diagrams/{diagram_id}").status_code == 204
        assert anonymous.get(f"/dash/api/public/diagram/{_token(second)}").status_code == 404
        assert anonymous.get(f"/dash/api/public/diagram/{_token(second)}/data").status_code == 404


def test_only_its_editors_share_a_diagram_with_the_dashboards_rules(runtime, fake, client):
    diagram_id = _diagram(client)
    base = f"/dash/api/diagrams/{diagram_id}/shares"
    with client_for(runtime, fake, "operator") as operator:
        assert operator.post(base, json={}).status_code == 403
        assert operator.get(base).status_code == 403
    # "Until revoked" is an administrator's choice, as for dashboards.
    assert client.post(base, json={"days": None}).status_code == 403
    with client_for(runtime, fake, "admin") as admin:
        forever = admin.post(base, json={"days": None})
        assert forever.status_code == 201 and forever.json()["expires_at"] is None
        every = admin.get("/dash/api/shares").json()
        assert [(item["target"], item["name"]) for item in every] == [("diagram", "Feed section")]
        assert admin.delete(f"/dash/api/shares/{forever.json()['share_id']}").status_code == 204


def test_diagram_links_are_off_with_the_others(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake, public_links=False)
    with client_for(runtime, fake) as client:
        diagram_id = _diagram(client)
        assert client.post(f"/dash/api/diagrams/{diagram_id}/shares", json={}).status_code == 403
    runtime = make_runtime(tmp_path / "nokey", fake, app_key=False)
    with client_for(runtime, fake) as client:
        diagram_id = _diagram(client)
        assert client.post(f"/dash/api/diagrams/{diagram_id}/shares", json={}).status_code == 503


# The diagram card ------------------------------------------------------------------------


def _with_card(client, diagram_id: str) -> str:
    created = client.post(
        "/dash/api/dashboards", json=dashboard(cards=[kpi(), diagram_card(diagram_id)])
    )
    assert created.status_code == 201, created.text
    return created.json()["dashboard_id"]


def test_a_diagram_card_shows_the_diagram_live_and_opens_its_page(client):
    diagram_id = _diagram(client)
    dashboard_id = _with_card(client, diagram_id)
    data = client.get(f"/dash/api/dashboards/{dashboard_id}/cards/dg").json()
    assert data["kind"] == "diagram" and "unavailable" not in data
    assert data["diagram"]["diagram_id"] == diagram_id and data["diagram"]["symbols"]
    assert data["url"] == f"/diagrams/{diagram_id}"
    # The plant now: values, without the window's series (the diagram's page plays them back).
    assert "series" not in data["data"] and data["data"]["range"]["live"] is True
    assert any(
        row["element"] == "pv" and row["value"] is not None for row in data["data"]["bindings"]
    )
    # It follows the dashboard's Time picker, else its own window.
    assert data["window"] == "1h"
    picked = client.get(f"/dash/api/dashboards/{dashboard_id}/cards/dg", params={"window": "8h"})
    assert picked.json()["window"] == "8h"


def test_a_diagram_card_respects_the_diagrams_folder(runtime, fake, client):
    closed = _diagram(client, folder_id=_closed_folder(client))
    dashboard_id = _with_card(client, closed)
    assert "diagram" in client.get(f"/dash/api/dashboards/{dashboard_id}/cards/dg").json()
    with client_for(runtime, fake, "operator") as operator:
        data = operator.get(f"/dash/api/dashboards/{dashboard_id}/cards/dg")
        assert data.status_code == 200
        assert "not available" in data.json()["unavailable"]
        assert "diagram" not in data.json() and "data" not in data.json()
        # The dashboard's other cards still draw.
        assert operator.get(f"/dash/api/dashboards/{dashboard_id}/cards/k1").status_code == 200


def test_a_deleted_diagram_leaves_a_not_available_card(client):
    diagram_id = _diagram(client)
    dashboard_id = _with_card(client, diagram_id)
    client.delete(f"/dash/api/diagrams/{diagram_id}")
    data = client.get(f"/dash/api/dashboards/{dashboard_id}/cards/dg").json()
    assert "unavailable" in data and "diagram" not in data


def test_a_public_dashboard_shows_only_diagrams_everyone_sees(runtime, fake, client):
    open_one = _diagram(client)
    closed = _diagram(client, folder_id=_closed_folder(client))
    created = client.post(
        "/dash/api/dashboards",
        json=dashboard(cards=[diagram_card(open_one, "a"), diagram_card(closed, "b")]),
    ).json()
    share = client.post(f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={})
    token = share.json()["path"].rsplit("/", 1)[-1]
    with client_for(runtime, fake, None) as anonymous:
        shown = anonymous.get(f"/dash/api/public/{token}/cards/a").json()
        assert shown["diagram"]["diagram_id"] == open_one
        # No page to open without signing in.
        assert "url" not in shown
        hidden = anonymous.get(f"/dash/api/public/{token}/cards/b").json()
        assert "unavailable" in hidden and "diagram" not in hidden


def test_a_diagram_card_names_a_diagram_and_no_signal(client):
    refused = client.post("/dash/api/dashboards", json=dashboard(cards=[diagram_card("", "dg")]))
    assert refused.status_code == 422 and "Pick the process display" in refused.text
    with_items = diagram_card("abc", items=[{"signal_id": "fake:FIC-101.PV"}])
    refused = client.post("/dash/api/dashboards", json=dashboard(cards=[with_items]))
    assert refused.status_code == 422
    short = diagram_card("abc", height=1)
    assert client.post("/dash/api/dashboards", json=dashboard(cards=[short])).status_code == 422


def test_the_editor_previews_a_diagram_card_as_the_editor(runtime, fake, client):
    diagram_id = _diagram(client, folder_id=_closed_folder(client))
    body = {"card": diagram_card(diagram_id), "window": None}
    preview = client.post("/dash/api/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["diagram"]["name"] == "Feed section"
    with client_for(runtime, fake, "admin") as admin:
        assert "diagram" in admin.post("/dash/api/preview", json=body).json()


def test_a_report_has_no_diagram_panel(client):
    diagram_id = _diagram(client)
    report = {
        "name": "Shift",
        "period": "8h",
        "sections": [{"section_id": "s1", "kind": "card", "card": diagram_card(diagram_id)}],
    }
    refused = client.post("/dash/api/reports", json=report)
    assert refused.status_code == 422 and "process displays stay on screens" in refused.text
