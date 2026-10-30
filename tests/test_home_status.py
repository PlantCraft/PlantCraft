# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""Home's quick status (``/api/home/status``): which apps are online and the Historian's
connections, at a glance."""

from __future__ import annotations

from plantcraft.platform.datalayer import DataLayerError
from tests.test_collaboration import signed  # noqa: F401


def test_apps_are_online_when_their_key_was_used_lately_or_the_watch_says_so(signed):
    rt = signed.app.state.runtime
    first = signed.get("/api/home/status").json()
    assert {app["id"]: app["state"] for app in first["apps"]} == {
        "linkcraft": "unknown",
        "dashcraft": "unknown",
    }
    _row, key = rt.workspace.app_keys.create("linkcraft", label="test")
    assert rt.workspace.app_keys.verify("linkcraft", key)
    rt.watch._last = {
        "checks": [
            {"key": "service:dashcraft", "subject": "x", "bad": True, "detail": "exited (1)"}
        ]
    }
    apps = {app["id"]: app for app in signed.get("/api/home/status").json()["apps"]}
    assert apps["linkcraft"]["state"] == "online" and apps["linkcraft"]["seen_at"]
    assert apps["dashcraft"]["state"] == "offline" and apps["dashcraft"]["detail"] == "exited (1)"


def test_without_a_historian_the_sources_are_listed_as_read_directly(signed):
    historian = signed.get("/api/home/status").json()["historian"]
    assert historian["kind"] == "local" and historian["ok"] is True


class _Historian:
    manages_sources = True

    def __init__(self, items=None, error=None):
        self.items, self.error = items or [], error

    def close(self):
        pass

    def sources(self):
        if self.error:
            raise DataLayerError(502, self.error)
        return self.items


def _source(source_id, enabled=True, state=None, type="opcua"):
    return {
        "source_id": source_id,
        "name": source_id.upper(),
        "type": type,
        "type_label": "OPC UA",
        "enabled": enabled,
        "state": state,
    }


def test_each_historian_connection_says_whether_it_is_online(signed, monkeypatch):
    rt = signed.app.state.runtime
    sources = [
        _source("plant", state={"status": "connected", "detail": "", "since": 1}),
        _source("lab", state={"status": "disconnected", "detail": "timeout", "since": 1}),
        _source("old", enabled=False),
        _source("file"),
        # what apps write, the suite's health and an import have no connection to show
        _source("app-linkcraft", type="derived"),
        _source("system", type="system"),
        _source("import-1", type="import"),
    ]
    monkeypatch.setattr(rt.platform, "datalayer", _Historian(sources))
    historian = signed.get("/api/home/status").json()["historian"]
    assert historian["kind"] == "histcraft" and historian["ok"] is True
    states = {item["id"]: (item["state"], item["detail"]) for item in historian["sources"]}
    assert states == {
        "plant": ("online", ""),
        "lab": ("offline", "timeout"),
        "old": ("off", ""),
        "file": ("unknown", ""),
    }
    monkeypatch.setattr(rt.platform, "datalayer", _Historian(error="Historian unreachable"))
    down = signed.get("/api/home/status").json()["historian"]
    assert down == {
        "kind": "histcraft",
        "ok": False,
        "detail": "Historian unreachable",
        "sources": [],
    }


def test_the_alarms_page_lists_more_than_home_did(signed):
    from tests.test_collaboration import _publish_result

    for number in range(10):
        _publish_result(signed, f"asset:FIC-{100 + number}", "alarm")
    assert len(signed.get("/api/home").json()["attention"]) == 8
    everything = signed.get("/api/home/attention").json()
    assert len(everything) == 10 and {item["status"] for item in everything} == {"alarm"}
    assert len(signed.get("/api/home/attention", params={"limit": 3}).json()) == 3


def test_an_action_says_since_when_it_has_its_status(signed):
    """The Kanban board shows how long each card has been in its column."""

    created = signed.post("/api/actions", json={"title": "Check the valve", "priority": "high"})
    action = created.json()
    assert action["status_since"] == action["created_at"]
    body = {"title": "Check the valve", "priority": "high", "status": "in_progress"}
    signed.put(f"/api/actions/{action['action_id']}", json=body)
    moved = signed.get(f"/api/actions/{action['action_id']}").json()
    assert moved["status_since"] >= action["created_at"]
    entries = [item for item in moved["history"] if item["kind"] == "status"]
    assert moved["status_since"] == entries[-1]["created_at"]
    listed = signed.get("/api/actions").json()["items"][0]
    assert listed["status_since"] == moved["status_since"]


def test_each_person_keeps_their_own_overview_widgets(signed):
    client = signed
    assert client.get("/api/home/layout").json() == {"widgets": None}
    saved = client.put(
        "/api/home/layout", json={"widgets": ["attention", "linkcraft:worst", "attention"]}
    )
    assert saved.json() == {"widgets": ["attention", "linkcraft:worst"]}
    assert client.get("/api/home/layout").json() == {"widgets": ["attention", "linkcraft:worst"]}
    assert client.put("/api/home/layout", json={"widgets": ["../etc"]}).status_code == 422
    assert client.delete("/api/home/layout").json() == {"widgets": None}
    assert client.get("/api/home/layout").json() == {"widgets": None}


def test_each_app_overview_keeps_its_own_layout(signed):
    """Every app's first page is an Overview of widgets (AppOverview): one layout per app."""

    client = signed
    client.put("/api/home/layout", json={"widgets": ["attention"]})
    link = client.put("/api/home/layout?page=linkcraft", json={"widgets": ["linkcraft:worst"]})
    assert link.json() == {"widgets": ["linkcraft:worst"]}
    assert client.get("/api/home/layout?page=linkcraft").json() == {"widgets": ["linkcraft:worst"]}
    assert client.get("/api/home/layout?page=alarmcraft").json() == {"widgets": None}
    assert client.get("/api/home/layout?page=processcraft").json() == {"widgets": ["attention"]}
    assert client.get("/api/home/layout?page=../x").status_code == 422
    assert client.delete("/api/home/layout?page=linkcraft").json() == {"widgets": None}
    assert client.get("/api/home/layout").json() == {"widgets": ["attention"]}
