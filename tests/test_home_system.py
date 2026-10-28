# ruff: noqa: F811  (the fixture ``signed`` comes from test_collaboration.py)
"""The "System" widget of PlantCraft's Overview (``/api/home/system``): is the installation
healthy? Read from what the suite watch and the Backups and Updates pages keep (2026-10-27)."""

from __future__ import annotations

from tests.test_collaboration import _person, signed  # noqa: F401

GB = 2**30


def _watch(rt, monkeypatch, **seen):
    base = {"at": None, "watching": True, "checks": [], "open": [], "metrics": None}
    monkeypatch.setattr(rt.watch, "overview", lambda: {**base, **seen})


def _operations(rt, monkeypatch, **found):
    base = {"backups": [], "update": None, "release": None}
    monkeypatch.setattr(rt.operations, "overview", lambda: {**base, **found})


def _disk(pct):
    return {"total_bytes": 100 * GB, "free_bytes": int(pct * GB), "free_pct": pct}


def test_a_fresh_installation_answers_without_the_installer(signed):
    body = signed.get("/api/home/system").json()
    assert body["admin"] is True and body["open"] == 0 and body["services"] is None
    assert body["version"] and body["update"] is None and body["backup"] is None
    # No installer metrics: the data folder's own disk.
    assert body["disk"]["free_bytes"] > 0 and body["disk"]["state"] in {"ok", "warning", "alarm"}
    # The administrator signed in to run this test.
    assert body["signed_in_today"] == 1


def test_the_disk_takes_the_watch_thresholds(signed, monkeypatch):
    rt = signed.app.state.runtime
    _operations(rt, monkeypatch)
    _watch(rt, monkeypatch, metrics={"disk": _disk(40)})
    assert signed.get("/api/home/system").json()["disk"]["state"] == "ok"
    _watch(rt, monkeypatch, metrics={"disk": _disk(11)})
    assert signed.get("/api/home/system").json()["disk"]["state"] == "warning"
    _watch(rt, monkeypatch, metrics={"disk": _disk(9)})
    assert signed.get("/api/home/system").json()["disk"]["state"] == "alarm"
    filling = [{"key": "disk_trend", "subject": "Disk forecast", "bad": True, "detail": ""}]
    _watch(rt, monkeypatch, metrics={"disk": _disk(40)}, checks=filling,
           disk_forecast={"days_left": 12.0, "bytes_per_day": GB, "hours": 48})  # fmt: skip
    disk = signed.get("/api/home/system").json()["disk"]
    assert disk["state"] == "warning" and disk["days_left"] == 12.0
    # Still under the hysteresis while the incident is open.
    incident = [{"incident_id": 1, "check_key": "disk", "subject": "Disk", "detail": "",
                 "opened_at": "2026-10-27T00:00:00Z", "closed_at": None, "notified": 1}]  # fmt: skip
    _watch(rt, monkeypatch, metrics={"disk": _disk(11)}, open=incident)
    body = signed.get("/api/home/system").json()
    assert body["disk"]["state"] == "alarm" and body["open"] == 1


def test_the_last_backup_the_version_and_the_services(signed, monkeypatch):
    rt = signed.app.state.runtime
    services = [
        {"service": "processcraft", "state": "running", "health": "healthy"},
        {"service": "linkcraft", "state": "running", "health": "unhealthy"},
        {"service": "dashcraft", "state": "exited", "health": ""},
    ]
    _watch(rt, monkeypatch, metrics={"services": services})
    backups = [
        {"name": "a", "state": "ok", "created_at": "2026-10-26T02:00:00Z"},
        {"name": "b", "state": "failed", "created_at": "2026-10-27T02:00:00Z"},
        # Set aside by a restore: not the schedule's.
        {"name": "c", "state": "aside", "created_at": "2026-10-27T05:00:00Z"},
    ]
    update = {"from": "0.1.0", "to": "0.2.0", "state": "ok", "at": "2026-10-20T10:00:00Z"}
    _operations(rt, monkeypatch, backups=backups, update=update, release={"version": "0.2.0"})
    body = signed.get("/api/home/system").json()
    assert body["services"] == {"running": 1, "total": 3}
    assert body["backup"] == {"name": "b", "at": "2026-10-27T02:00:00Z", "state": "alarm"}
    assert body["version"] == "0.2.0" and body["update"]["state"] == "ok"
    # A good backup older than the watch allows is a warning.
    late = [{"key": "backup", "subject": "Backups", "bad": True, "detail": "26 h"}]
    _watch(rt, monkeypatch, checks=late)
    _operations(rt, monkeypatch, backups=backups[:1])
    assert signed.get("/api/home/system").json()["backup"]["state"] == "warning"


def test_others_see_the_version_and_the_services_only(signed, monkeypatch):
    rt = signed.app.state.runtime
    incidents = [
        {"incident_id": 1, "check_key": "disk", "subject": "Disk", "detail": "",
         "opened_at": "2026-10-27T00:00:00Z", "closed_at": None, "notified": 1},
        {"incident_id": 2, "check_key": "service:linkcraft", "subject": "Link", "detail": "",
         "opened_at": "2026-10-27T00:00:00Z", "closed_at": None, "notified": 1},
    ]  # fmt: skip
    _watch(rt, monkeypatch, open=incidents, metrics={"disk": _disk(5)})
    viewer = _person(signed, "vera", "viewer")
    body = viewer.get("/api/home/system").json()
    assert body["admin"] is False and body["open"] == 1
    assert not {"disk", "backup", "signed_in_today"} & set(body)
    assert signed.get("/api/home/system").json()["open"] == 2
    # Recent changes read the audit log, which stays with the administrators.
    assert viewer.get("/api/audit", params={"kind": "changes", "limit": 5}).status_code == 403


def test_people_signed_in_today_are_counted_once(signed):
    audit = signed.app.state.runtime.workspace.audit
    for name in ("ana", "ana", "bruno"):
        audit.record(name, "session.sign_in")
    audit.record("carla", "session.sign_in_failed")
    assert signed.get("/api/home/system").json()["signed_in_today"] == 3
    assert audit.signed_in("2999-01-01T00:00:00Z") == 0
