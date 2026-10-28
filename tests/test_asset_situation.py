# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""An asset's Situation (owner, 2026-10-23): what every app published about the asset, its
signals and the assets inside it, worst first and by app, with events, runs and open actions."""

from __future__ import annotations

from plantcraft_sdk.links import now_text
from tests.test_collaboration import signed  # noqa: F401


def _result(app, subject, status, score, summary, **detail):
    return {
        "app": app, "subject": subject, "kind": "state", "status": status, "score": score,
        "usable": None, "value": score, "summary": summary, "detail": detail, "at": now_text(),
        "expires_at": None,
    }  # fmt: skip


def test_the_situation_gathers_every_app_worst_first(signed):
    rt = signed.app.state.runtime
    store = rt.workspace.assets
    items = store.list()
    parent = next(
        item for item in items if store.descendants(item["asset_id"]) - {item["asset_id"]}
    )
    child = sorted(store.descendants(parent["asset_id"]) - {parent["asset_id"]})[0]
    rt.workspace.results.put_results(
        [
            _result(
                "linkcraft", f"asset:{child}", "warning", 54, "Oscillating", url="/link/loops/x"
            ),
            _result("linkcraft", f"asset:{parent['asset_id']}", "ok", 90, "Healthy"),
            _result("alarmcraft", f"asset:{child}", "alarm", None, "1 active: high level"),
            _result("alarmcraft", "asset:somewhere-else", "alarm", None, "Not ours"),
            _result("modelcraft", f"asset:{child}", "ok", None, "Bad link", url="javascript:x"),
        ],
        now=now_text(),
        cutoff="2000-01-01T00:00:00+00:00",
    )
    made = signed.post(
        "/api/actions", json={"title": "Check it", "refs": [f"asset:{parent['asset_id']}"]}
    )
    assert made.status_code in (200, 201), made.text

    body = signed.get(f"/api/assets/{parent['asset_id']}/situation").json()
    assert body["status"] == "alarm"
    assert [group["app"] for group in body["apps"]] == ["alarmcraft", "linkcraft", "modelcraft"]
    link = body["apps"][1]
    assert link["status"] == "warning" and link["counts"] == {"warning": 1, "ok": 1}
    assert [row["summary"] for row in link["results"]] == ["Oscillating", "Healthy"]
    assert link["results"][0]["url"] == "/link/loops/x"
    assert link["results"][0]["about"]["kind"] == "inside"
    assert body["apps"][2]["results"][0]["url"] is None
    assert all(row["summary"] != "Not ours" for group in body["apps"] for row in group["results"])
    assert body["counts"]["alarm"] == 1 and body["inside"]["included"] >= 1
    assert [item["title"] for item in body["actions"]] == ["Check it"]

    alone = signed.get(f"/api/assets/{parent['asset_id']}/situation?inside=false").json()
    assert [group["app"] for group in alone["apps"]] == ["linkcraft"]
    assert signed.get("/api/assets/nope/situation").status_code == 404
