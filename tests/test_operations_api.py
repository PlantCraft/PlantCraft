"""The Operations page API (/api/operations): requests to the installer and its answers."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

import json

from tests.test_apps_api import PASSWORD, audit, sign_in, world  # noqa: F401

NAME = "20261021-020005-daily"


def _status(world, name, value):
    folder = world.install_dir / "data" / "installer" / "status"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(value))


def _requests(world):
    return [json.loads(p.read_text()) for p in sorted(world.requests.glob("*.json"))
            if p.name != "ops-settings.json"]  # fmt: skip


def test_the_page_shows_what_the_installer_wrote(world):
    client = sign_in(world.client())
    _status(world, "backups.json", {"backups": [{"name": NAME, "state": "ok"}], "free_bytes": 9})
    _status(world, "update.json", {"from": "0.1.0", "to": "0.2.0", "state": "ok"})
    _status(world, "release.json", {"version": "0.2.0", "notes": "# PlantCraft 0.2.0"})
    body = client.get("/api/operations").json()
    assert body["backups"][0]["name"] == NAME and body["free_bytes"] == 9
    assert body["update"]["state"] == "ok" and body["release"]["version"] == "0.2.0"
    assert body["schedule"]["daily_at"] == "02:00" and body["running"] is None


def test_only_admins_reach_it(world):
    client = sign_in(world.client(), "eng", "password-123")
    assert client.get("/api/operations").status_code == 403
    assert client.post("/api/operations/backup", json={}).status_code == 403


def test_a_backup_request_goes_to_the_installer_and_is_audited(world):
    client = sign_in(world.client())
    queued = client.post("/api/operations/backup", json={}).json()
    assert queued["state"] == "queued"
    assert _requests(world)[0]["action"] == "backup"
    assert (
        client.get(f"/api/operations/requests/{queued['request_id']}").json()["state"] == "queued"
    )
    assert audit(client, "operations.backup")
    _status(world, "operation.json", {"action": "backup", "phase": "copying"})
    busy = client.post("/api/operations/drill", json={})
    assert busy.status_code == 409


def test_a_restore_needs_the_password_and_the_name_typed_again(world):
    client = sign_in(world.client())
    _status(world, "backups.json", {"backups": [{"name": NAME, "state": "ok"}]})
    wrong = {"name": NAME, "typed_name": NAME, "password": "nope"}
    assert client.post("/api/operations/restore", json=wrong).status_code == 403
    mistyped = {"name": NAME, "typed_name": "x", "password": PASSWORD}
    assert client.post("/api/operations/restore", json=mistyped).status_code == 422
    assert client.post("/api/operations/restore", json={}).status_code == 422
    assert client.post("/api/operations/restore-x", json={}).status_code == 404
    assert (
        client.post("/api/operations/restore", json={**wrong, "password": PASSWORD}).status_code
        == 200
    )
    assert [r["action"] for r in _requests(world)] == ["restore"]
    assert audit(client, "operations.restore.refused") and audit(client, "operations.restore")
    unknown = {"name": "20261021-020005-manual", "typed_name": "20261021-020005-manual",
               "password": PASSWORD}  # fmt: skip
    assert client.post("/api/operations/restore", json=unknown).status_code == 404


def test_the_schedule_is_checked_and_stored_for_the_installer(world):
    client = sign_in(world.client())
    assert client.put("/api/operations/schedule", json={"daily_at": "25:00"}).status_code == 422
    assert client.put("/api/operations/schedule", json={"drill_weekday": 9}).status_code == 422
    stored = client.put("/api/operations/schedule",
                        json={"daily_at": "03:30", "timezone": "America/Sao_Paulo"}).json()  # fmt: skip
    assert stored["daily_at"] == "03:30" and stored["drill"] is True
    on_disk = json.loads((world.requests / "ops-settings.json").read_text())
    assert on_disk["backup"]["timezone"] == "America/Sao_Paulo"
    client.put("/api/operations/schedule", json={"drill_weekday": 2, "drill_at": "04:15"})
    from plantcraft.apps import operations

    read = operations.schedule_settings(world.requests / "ops-settings.json")
    assert (read["daily_at"], read["drill_weekday"], read["drill_at"]) == ("03:30", 2, "04:15")


def test_the_watch_tells_the_admins_as_system(world):
    from datetime import datetime, timezone

    client = sign_in(world.client())
    rt = client.app.state.runtime
    now = datetime.now(timezone.utc).isoformat()
    _status(world, "backups.json", {"backups": [{"name": NAME, "state": "ok", "created_at": now}]})
    _status(world, "metrics.json", {"at": now, "error": None, "disk": {"free_pct": 3.0},
                                    "services": [{"service": "histcraft", "state": "running",
                                                  "health": "healthy"}]})  # fmt: skip
    posted = rt.watch.tick()
    assert len(posted) == 1 and "Disk" in posted[0]
    body = client.get("/api/operations/health").json()
    assert body["watching"] is True and body["open"][0]["check_key"] == "disk"
    assert body["metrics"]["services"][0]["service"] == "histcraft"
    conversation = client.get(f"/api/messages/conversations/{body['conversation_id']}").json()
    assert conversation["conversation"]["title"] == "Suite health"
    assert conversation["messages"][0]["author"] == "system"
    assert (
        sign_in(world.client(), "eng", "password-123").get("/api/operations/health").status_code
        == 403
    )
    # Everyone sees whether each part runs; never the disk or the backups.
    seen = sign_in(world.client(), "eng", "password-123").get("/api/operations/status")
    assert seen.status_code == 200
    status = seen.json()
    assert status["watching"] is True and status["open"] == []  # the disk incident is the admins'
    assert status["services"] == [
        {"service": "histcraft", "name": None, "state": "running", "health": "healthy",
         "started_at": None}
    ]  # fmt: skip
    assert "metrics" not in status and "certificates" not in status


def test_a_diagnostic_bundle_is_asked_for_downloaded_and_audited(world):
    client = sign_in(world.client())
    queued = client.post("/api/operations/diagnostics").json()
    request_id = queued["request_id"]
    assert queued["action"] == "diagnostics" and _requests(world)[0]["action"] == "diagnostics"
    assert audit(client, "operations.diagnostics")
    assert client.get(f"/api/operations/diagnostics/{request_id}").status_code == 404  # not yet
    (world.install_dir / "data" / "installer" / "status" / "requests").mkdir(parents=True)
    _status(world, f"requests/{request_id}.json",
            {"request_id": request_id, "action": "diagnostics", "state": "done"})  # fmt: skip
    assert client.get(f"/api/operations/diagnostics/{request_id}").status_code == 404  # pruned
    folder = world.install_dir / "data" / "installer" / "status" / "diagnostics"
    folder.mkdir(parents=True)
    (folder / f"{request_id}.zip").write_bytes(b"PK zip")
    answer = client.get(f"/api/operations/diagnostics/{request_id}")
    assert answer.status_code == 200 and answer.content == b"PK zip"
    assert "processcraft-diagnostics-" in answer.headers["content-disposition"]
    assert audit(client, "operations.diagnostics.download")
    # another request id is not a way to read other files
    assert client.get("/api/operations/diagnostics/..%2Fmetrics").status_code == 404
    engineer = sign_in(world.client(), "eng", "password-123")
    assert engineer.post("/api/operations/diagnostics").status_code == 403
    assert engineer.get(f"/api/operations/diagnostics/{request_id}").status_code == 403
