"""The installation's time zone (Setup › Installation), each person's Preferences, and the
backups that run at "local" time (owner, 2026-10-24/25: Local time by default, picked from a list)."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from plantcraft import config
from plantcraft.apps import operations
from tests.test_apps_api import PASSWORD, sign_in, world  # noqa: F401


@pytest.fixture(autouse=True)
def _forget_saved_zone():
    yield
    config.use_installation_zone(None)


def test_the_saved_zone_wins_over_the_installers(world, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "UTC")
    client = sign_in(world.client())
    first = client.get("/api/setup/installation").json()
    assert first["time_zone"] == "UTC" and first["installed_time_zone"] == "UTC"
    assert first["chosen"] is False
    saved = client.put("/api/setup/installation", json={"time_zone": "America/Sao_Paulo"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["time_zone"] == "America/Sao_Paulo" and saved.json()["chosen"] is True
    assert saved.json()["now"].endswith("-03:00")
    assert config.plant_timezone(fresh=True).key == "America/Sao_Paulo"
    # Every app reads it from API v1, and the browser from the cookie.
    assert client.get("/api/v1/installation").json()["time_zone"] == "America/Sao_Paulo"
    client.get("/api/setup/installation")
    assert client.cookies.get("processcraft_time_zone") == "America%2FSao_Paulo"
    # A fixed offset is a zone too (UTC−3, no daylight saving).
    assert client.put("/api/setup/installation", json={"time_zone": "Etc/GMT+3"}).status_code == 200
    bad = client.put("/api/setup/installation", json={"time_zone": "Mars/Olympus"})
    assert bad.status_code == 422
    assert config.plant_timezone(fresh=True).key == "Etc/GMT+3"


def test_only_admins_set_the_installation_zone(world):
    client = sign_in(world.client())
    made = client.post(
        "/api/users",
        json={
            "username": "ana",
            "display_name": "Ana",
            "password": PASSWORD,
            "access_level": "viewer",
        },
    )
    assert made.status_code == 201, made.text
    viewer = sign_in(world.client(), "ana")
    assert viewer.get("/api/setup/installation").status_code == 403
    assert viewer.put("/api/setup/installation", json={"time_zone": "UTC"}).status_code == 403
    # Preferences are each person's, read-only access included.
    assert viewer.get("/api/me/preferences").json()["time_zone"] == "plant"
    saved = viewer.put("/api/me/preferences", json={"time_zone": "utc"})
    assert saved.status_code == 200 and saved.json()["time_zone"] == "utc"
    assert viewer.get("/api/me/preferences").json()["time_zone"] == "utc"
    assert client.get("/api/me/preferences").json()["time_zone"] == "plant"
    assert viewer.put("/api/me/preferences", json={"time_zone": "mars"}).status_code == 422


def test_backups_at_local_time_follow_the_installation(world, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "UTC")
    client = sign_in(world.client())
    assert client.get("/api/operations").json()["schedule"]["timezone"] == "local"
    client.put("/api/operations/schedule", json={"daily_at": "02:00", "timezone": "local"})
    client.put("/api/setup/installation", json={"time_zone": "America/Sao_Paulo"})
    on_disk = json.loads((world.requests / "ops-settings.json").read_text())["backup"]
    assert on_disk["timezone"] == "local" and on_disk["local_zone"] == "America/Sao_Paulo"
    settings = operations.schedule_settings(world.requests / "ops-settings.json")
    # 04:30 UTC is 01:30 in São Paulo: not yet; 05:30 UTC is 02:30 there: due.
    assert not operations.due(settings, None, datetime(2026, 10, 25, 4, 30, tzinfo=timezone.utc))
    assert operations.due(settings, None, datetime(2026, 10, 25, 5, 30, tzinfo=timezone.utc))
    assert client.put("/api/operations/schedule", json={"timezone": "Etc/GMT+3"}).status_code == 200
    assert client.put("/api/operations/schedule", json={"timezone": "Not/AZone"}).status_code == 422


def test_local_resolves_to_the_installation_zone(monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "America/Sao_Paulo")
    assert config.resolve_zone("local").key == "America/Sao_Paulo"
    assert config.resolve_zone(None).key == "America/Sao_Paulo"
    assert config.resolve_zone("Not/AZone").key == "America/Sao_Paulo"
    assert config.resolve_zone("Etc/GMT-5").key == "Etc/GMT-5"


def test_the_installation_has_one_id_for_good(world, monkeypatch):
    """E11 (2026-10-25): every installation names itself; install.sh's id wins, else one is
    made once and kept."""

    monkeypatch.delenv("PLANTCRAFT_INSTALLATION_ID", raising=False)
    client = sign_in(world.client())
    first = client.get("/api/v1/installation").json()["id"]
    assert len(first) == 36 and first.count("-") == 4
    assert client.get("/api/v1/installation").json()["id"] == first
    assert client.get("/api/setup/installation").json()["id"] == first
    monkeypatch.setenv("PLANTCRAFT_INSTALLATION_ID", "3B8C3B66-246E-4F08-A18C-EFBBCF7562B0")
    assert client.get("/api/v1/installation").json()["id"] == "3b8c3b66-246e-4f08-a18c-efbbcf7562b0"
    monkeypatch.setenv("PLANTCRAFT_INSTALLATION_ID", "not-an-id")
    assert client.get("/api/v1/installation").json()["id"] == first


def test_a_backup_names_its_installation(tmp_path):
    (tmp_path / ".env").write_text(
        "PLANTCRAFT_VERSION=0.5.0\nPLANTCRAFT_INSTALLATION_ID=3b8c3b66-246e-4f08-a18c-efbbcf7562b0\n"
    )
    ops = operations.Driver.__new__(operations.Driver)
    ops.install = tmp_path
    ops.images = lambda: {}
    assert ops.context()["installation_id"] == "3b8c3b66-246e-4f08-a18c-efbbcf7562b0"
