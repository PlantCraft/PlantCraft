"""The API: who may do what, card data, previews, starters, conflicts and the audit log."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dashcraft.api.app import create_app
from dashcraft.dashboards.model import CONTEXT
from tests.conftest import client_for, dashboard, kpi, make_runtime


def _create(client, **fields) -> dict:
    response = client.post("/dash/api/dashboards", json=dashboard(**fields))
    assert response.status_code == 201, response.text
    return response.json()


def test_health_and_me(client):
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/dash/healthz").json()["status"] == "ok"
    me = client.get("/dash/api/me").json()
    assert me["username"] == "engineer" and me["can_edit"] and me["public_links"]


@pytest.mark.parametrize(
    ("user", "role"), [("admin", "admin"), ("engineer", "editor"), ("operator", "viewer")]
)
def test_me_role_shows_an_admin_as_admin(runtime, fake, user, role):
    # An admin's app access is "editor" in the token; the user menu shows the level.
    with client_for(runtime, fake, user) as client:
        assert client.get("/dash/api/me").json()["role"] == role


@pytest.mark.parametrize(
    ("user", "status"), [(None, 401), ("outsider", 403), ("operator", 200), ("wallboard", 200)]
)
def test_who_may_open_dashcraft(runtime, fake, user, status):
    with client_for(runtime, fake, user) as client:
        assert client.get("/dash/api/dashboards").status_code == status


def test_viewers_read_and_editors_change(runtime, fake, client):
    created = _create(client)
    path = f"/dash/api/dashboards/{created['dashboard_id']}"
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get(path).status_code == 200
        assert viewer.put(path, json=dashboard(name="X")).status_code == 403
        assert viewer.delete(path).status_code == 403
        assert viewer.post("/dash/api/dashboards", json=dashboard()).status_code == 403
        assert viewer.post(f"{path}/shares", json={}).status_code == 403
        assert viewer.post("/dash/api/preview", json={"card": kpi()}).status_code == 403
        assert viewer.get("/dash/api/assets").status_code == 403


def test_create_update_copy_delete_are_audited(client, fake):
    created = _create(client)
    path = f"/dash/api/dashboards/{created['dashboard_id']}"
    saved = client.put(path, json=dashboard(name="Feed v2", base_updated_at=created["updated_at"]))
    assert saved.status_code == 200 and saved.json()["name"] == "Feed v2"
    copy = client.post(f"{path}/copy").json()
    assert copy["name"] == "Feed v2 (copy)" and copy["cards"] == saved.json()["cards"]
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    actions = [(row["action"], row["app"], row["username"]) for row in fake.audit_log]
    assert actions == [
        ("dashcraft.dashboard.create", "dashcraft", "engineer"),
        ("dashcraft.dashboard.update", "dashcraft", "engineer"),
        ("dashcraft.dashboard.copy", "dashcraft", "engineer"),
        ("dashcraft.dashboard.delete", "dashcraft", "engineer"),
    ]


def test_a_save_over_someone_elses_is_a_409_naming_them(runtime, fake, client):
    created = _create(client)
    path = f"/dash/api/dashboards/{created['dashboard_id']}"
    with client_for(runtime, fake, "admin") as other:
        other.put(path, json=dashboard(name="Admin's", base_updated_at=created["updated_at"]))
    clash = client.put(path, json=dashboard(name="Mine", base_updated_at=created["updated_at"]))
    assert clash.status_code == 409
    assert "admin saved this dashboard" in clash.json()["detail"]
    assert clash.json()["current"]["name"] == "Admin's"
    assert client.put(path, json=dashboard(name="Mine")).status_code == 200


def test_card_data_with_the_dashboards_asset_and_window(client):
    created = _create(
        client,
        context_kind="loop",
        cards=[
            kpi("pv", asset_id=CONTEXT, role="pv"),
            {"card_id": "t", "kind": "trend", "items": [{"asset_id": CONTEXT, "role": "pv"}]},
        ],
    )
    base = f"/dash/api/dashboards/{created['dashboard_id']}"
    options = client.get(f"{base}/context").json()
    assert [item["id"] for item in options] == ["fic-101", "fic-109", "lic-102"]
    assert options[0]["parent"] == "Unit 100"
    data = client.get(f"{base}/cards/pv", params={"context": "lic-102"}).json()
    assert data["rows"][0]["signal"] == "fake:LIC-102.PV" and data["rows"][0]["value"] is not None
    trend = client.get(f"{base}/cards/t", params={"context": "fic-101", "window": "2h"}).json()
    assert trend["window"] == "2h" and len(trend["lines"][0]["v"]) == 480
    # The dashboard shows loops only: another kind of asset, or junk, is refused.
    assert client.get(f"{base}/cards/pv", params={"context": "p-201"}).status_code == 422
    assert client.get(f"{base}/cards/pv", params={"context": "nowhere"}).status_code == 404
    assert client.get(f"{base}/cards/pv", params={"window": "1w"}).status_code == 422
    assert client.get(f"{base}/cards/nope").status_code == 404


def test_dashboards_only_people_see_data_read_with_the_app_key(runtime, fake, client):
    created = _create(client)
    with client_for(runtime, fake, "wallboard") as wallboard:
        path = f"/dash/api/dashboards/{created['dashboard_id']}/cards/k1"
        assert wallboard.get(path).json()["rows"][0]["value"] is not None


def test_without_an_app_key_people_read_with_their_own_token(tmp_path, fake):
    runtime = make_runtime(tmp_path, fake, app_key=False)
    with client_for(runtime, fake) as client:
        created = _create(client)
        path = f"/dash/api/dashboards/{created['dashboard_id']}/cards/k1"
        assert client.get(path).json()["rows"][0]["value"] is not None
        assert client.get("/dash/api/me").json()["public_links"] is False
        assert (
            client.post(
                f"/dash/api/dashboards/{created['dashboard_id']}/shares", json={}
            ).status_code
            == 503
        )
    with client_for(runtime, fake, "wallboard") as wallboard:
        # PlantCraft refuses plant data to a dashboards-only token: that is said on the card.
        rows = wallboard.get(path).json()["rows"]
        assert "does not let this dashboard read" in rows[0]["error"]


def test_a_refused_app_key_is_a_503_not_a_sign_in(tmp_path, fake):
    fake.app_keys["dashcraft"] = "rotated"
    runtime = make_runtime(tmp_path, fake)
    with client_for(runtime, fake) as client:
        created = _create(client)
        response = client.get(f"/dash/api/dashboards/{created['dashboard_id']}/cards/k1")
        assert response.status_code == 503 and "app key" in response.json()["detail"]


def test_preview_and_pickers_use_the_editors_token(client, fake):
    preview = client.post(
        "/dash/api/preview",
        json={"card": kpi(asset_id=CONTEXT, role="op"), "context": "fic-101"},
    )
    assert preview.status_code == 200 and preview.json()["rows"][0]["signal"] == "fake:FIC-101.OP"
    kinds = {item["kind"]: item for item in client.get("/dash/api/asset-kinds").json()}
    assert kinds["loop"]["count"] == 3 and "pv" in kinds["loop"]["roles"]
    pumps = client.get("/dash/api/assets", params={"kind": "pump"}).json()
    assert [item["id"] for item in pumps] == ["p-201"] and pumps[0]["signals"]["flow"]
    assert [item["id"] for item in client.get("/dash/api/assets", params={"q": "lic"}).json()] == [
        "lic-102"
    ]
    signals = client.get("/dash/api/signals", params={"q": "FIC-101"}).json()
    assert {item["id"] for item in signals} >= {"fake:FIC-101.PV", "fake:FIC-101.SP"}


def test_signal_search_lists_plant_signals_before_derived_series(client, fake):
    # Analytics' FIC-101 loop health series match "FIC-101" too and PlantCraft lists them
    # first here (they were written last, say); the plant tags still come first.
    fake.signals.sort(key=lambda item: not item["id"].startswith("app-"))
    ids = [item["id"] for item in client.get("/dash/api/signals", params={"q": "FIC-101"}).json()]
    derived = [index for index, signal in enumerate(ids) if signal.startswith("app-")]
    plant = [index for index, signal in enumerate(ids) if not signal.startswith("app-")]
    assert derived and plant and max(plant) < min(derived)


def test_starter_dashboards_come_from_the_assets(client):
    created = client.post("/dash/api/dashboards/starter")
    assert created.status_code == 201
    names = [item["name"] for item in created.json()]
    assert names == ["Loop detail", "Unit 100 overview"]
    detail = created.json()[0]
    assert detail["context_kind"] == "loop"
    data = client.get(
        f"/dash/api/dashboards/{detail['dashboard_id']}/cards/trend-pv",
        params={"context": "fic-101"},
    ).json()
    assert [line["signal"] for line in data["lines"]] == ["fake:FIC-101.PV", "fake:FIC-101.SP"]


def test_a_new_plants_first_step_draws_an_overview_per_unit(client, runtime, fake):
    body = {"units": ["unit-100", "plant"], "assets": [{"id": "unit-100", "kind": "unit"}]}
    done = client.post("/dash/api/start/unit-overviews", json=body)
    assert done.status_code == 200, done.text
    assert done.json()["counts"] == {"created": 1, "kept": 0} and done.json()["open"] == "/dash/"
    [made] = [
        item for item in client.get("/dash/api/dashboards").json() if "overview" in item["name"]
    ]
    assert made["name"] == "Unit 100 overview" and not made.get("folder_id")
    again = client.post("/dash/api/start/unit-overviews", json=body).json()
    assert again["counts"] == {"created": 0, "kept": 1}
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.post("/dash/api/start/unit-overviews", json=body).status_code == 403


def test_pages_need_sign_in_but_public_links_do_not(runtime, fake):
    from dashcraft.api.app import ui_folder

    if ui_folder() is None:
        pytest.skip("The interface is not built (npm run build in frontend/).")
    with client_for(runtime, fake, None) as anonymous:
        page = anonymous.get("/dash/", headers={"Accept": "text/html"}, follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"].startswith("/login?next=")
        shared = anonymous.get("/dash/share/anything", headers={"Accept": "text/html"})
        assert shared.status_code == 200 and shared.headers["cache-control"] == "no-store"
        assert shared.headers["referrer-policy"] == "no-referrer"


def test_unknown_api_paths_are_404(client):
    assert client.get("/dash/api/nothing").status_code == 404


def test_cards_show_other_apps_results(runtime, fake, client):
    from tests.plant import publish_loop_health

    publish_loop_health(fake)
    kinds = client.get("/dash/api/result-kinds", params={"kind": "loop"}).json()
    # Both loops have a result; only FIC-101's health is archived as a series (trends).
    assert kinds == [{"result": "linkcraft.loop_health", "count": 2, "history": 1}]
    one = client.get("/dash/api/result-kinds", params={"asset": "fic-101"}).json()
    assert [item["result"] for item in one] == ["linkcraft.loop_health"]
    health = kpi("health", asset_id=CONTEXT, result="linkcraft.loop_health")
    created = _create(client, context_kind="loop", cards=[health])
    with client_for(runtime, fake, "operator") as viewer:
        assert viewer.get("/dash/api/result-kinds").status_code == 403
        data = viewer.get(
            f"/dash/api/dashboards/{created['dashboard_id']}/cards/health",
            params={"context": "fic-101"},
        ).json()
    assert data["rows"][0]["state"] == "warning" and data["rows"][0]["value"] == 62.5


def test_variables_pick_what_the_cards_show(client):
    """Round 7 (D4): pickers at the top; values are checked against what the dashboard offers."""

    created = _create(
        client,
        variables=[
            {"name": "unit", "type": "asset", "asset_kind": "unit"},
            {
                "name": "loop",
                "type": "asset",
                "asset_kind": "loop",
                "parent": "unit",
                "multi": True,
                "include_all": True,
            },
            {"name": "period", "type": "interval", "options": ["1h", "8h"]},
        ],
        cards=[
            {
                "card_id": "t",
                "kind": "trend",
                "window": "$period",
                "items": [{"asset_id": "$loop", "role": "pv"}],
            },
        ],
    )
    base = f"/dash/api/dashboards/{created['dashboard_id']}"
    assert created["context_kind"] == "unit"
    loops = client.get(f"{base}/variables/loop", params={"parent": "unit-100"}).json()
    assert [item["value"] for item in loops] == ["fic-101", "fic-109", "lic-102"]
    assert client.get(f"{base}/variables/loop", params={"parent": "nowhere"}).json() == []
    assert len(client.get(f"{base}/variables/loop").json()) == 3
    assert client.get(f"{base}/variables/period").json()[1]["value"] == "8h"
    assert client.get(f"{base}/variables/nope").status_code == 404
    data = client.get(f"{base}/cards/t?var-loop=fic-101&var-loop=lic-102&var-period=8h").json()
    assert data["window"] == "8h"
    assert [line["signal"] for line in data["lines"]] == ["fake:FIC-101.PV", "fake:LIC-102.PV"]
    every = client.get(f"{base}/cards/t?var-unit=unit-100&var-loop=$__all").json()
    signals = ["fake:FIC-101.PV", "fake:GONE.PV", "fake:LIC-102.PV"]
    assert [line["signal"] for line in every["lines"]] == signals
    assert "not found" in every["lines"][1]["error"]
    # A value the dashboard does not offer is refused: the cards read with the app's key.
    assert client.get(f"{base}/cards/t?var-loop=p-201").status_code == 422
    assert client.get(f"{base}/cards/t?var-period=30d").status_code == 422
    asked = client.get(f"{base}/cards/t").json()
    assert "Pick loop" in asked["lines"][0]["error"]


def test_a_public_demo_visit_reads_what_the_editors_show_but_saves_nothing(runtime, fake):
    # The visitor is shown the editors (plantcraft_sdk.server.demo): their pickers, templates and
    # dialogs answer instead of a 403 on every page, and every save stays refused.
    with client_for(runtime, fake, "engineer") as editor:
        board = editor.post("/dash/api/dashboards", json=dashboard()).json()["dashboard_id"]
    visit = {"visit": "v1", "ends": 4102444800, "queries": 4, "queries_total": 8}
    with TestClient(create_app(runtime), raise_server_exceptions=False) as visitor:
        visitor.headers["Authorization"] = f"Bearer {fake.token('operator', demo=visit)}"
        for path in (
            "/dash/api/directory",
            "/dash/api/templates",
            "/dash/api/assets",
            "/dash/api/asset-kinds",
            "/dash/api/event-kinds",
            f"/dash/api/dashboards/{board}/versions",
        ):
            assert visitor.get(path).status_code == 200, path
        assert visitor.get(f"/dash/api/dashboards/{board}/shares").json() == []
        refused = visitor.post("/dash/api/folders", json={"name": "Mine"})
        assert refused.status_code == 403 and "nothing is saved" in refused.json()["detail"]
    with client_for(runtime, fake, "operator") as operator:
        assert operator.get("/dash/api/templates").status_code == 403
