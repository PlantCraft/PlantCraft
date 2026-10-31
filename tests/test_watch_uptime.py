"""Uptime by app and maintenance windows that silence the watch (plantcraft.watch.uptime)."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from plantcraft.watch.uptime import check_window, covers, uptime
from tests.test_apps_api import audit, sign_in, world  # noqa: F401
from tests.test_operations_requests import PASSWORD
from tests.test_watch import World

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def _at(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def test_uptime_counts_outages_and_leaves_planned_maintenance_out():
    incidents = [
        # The Historian down 1 h yesterday, and 2 h inside a maintenance window 3 days ago.
        {"check_key": "service:histcraft", "opened_at": _at(20), "closed_at": _at(19)},
        {"check_key": "service:histcraft", "opened_at": _at(74), "closed_at": _at(72)},
        # Load is not downtime.
        {"check_key": "load:histcraft", "opened_at": _at(5), "closed_at": _at(4)},
    ]
    windows = [
        {"starts_at": _at(75), "ends_at": _at(71), "ended_at": None, "services": ["histcraft"]},
    ]
    found = {
        row["service"]: row
        for row in uptime(
            ["histcraft", "dashcraft"],
            incidents,
            windows,
            now=NOW,
            first_seen=NOW - timedelta(days=60),
        )
    }
    history = found["histcraft"]
    assert history["uptime"]["24h"] == round(100 * 23 / 24, 2)
    assert history["down_seconds"]["24h"] == 3600 and history["outages"]["24h"] == 1
    # 7 days: 1 h lost of 168 h watched less the 4 h planned.
    assert history["uptime"]["7d"] == round(100 * (164 - 1) / 164, 2)
    assert history["outages"]["7d"] == 1
    assert found["dashcraft"]["uptime"] == {"24h": 100.0, "7d": 100.0, "30d": 100.0}
    # Watched only since an hour ago: the day counts that hour, not the whole day.
    fresh = uptime(["dashcraft"], [], [], now=NOW, first_seen=NOW - timedelta(hours=1))
    assert fresh[0]["uptime"]["24h"] == 100.0
    # An outage still open counts until now.
    open_now = uptime(
        ["histcraft"],
        [{"check_key": "service:histcraft", "opened_at": _at(6), "closed_at": None}],
        [],
        now=NOW,
        first_seen=None,
    )
    assert open_now[0]["uptime"]["24h"] == 75.0


def test_a_window_is_checked_and_covers_its_apps():
    assert check_window(NOW, NOW + timedelta(hours=2), " Update ", NOW) == "Update"
    for starts, ends, reason in (
        (NOW, NOW + timedelta(hours=2), ""),
        (NOW, NOW - timedelta(hours=1), "x"),
        (NOW - timedelta(hours=3), NOW - timedelta(hours=1), "x"),
        (NOW, NOW + timedelta(hours=100), "x"),
    ):
        with pytest.raises(ValueError):
            check_window(starts, ends, reason, NOW)
    assert covers({"services": None}, "service:histcraft")
    assert covers({"services": ["histcraft"]}, "load:histcraft")
    assert not covers({"services": ["histcraft"]}, "service:dashcraft")


def test_a_maintenance_window_keeps_the_watch_quiet_about_its_apps(tmp_path):
    world = World(tmp_path)
    up = {"processcraft": "healthy", "histcraft": "healthy", "dashcraft": "healthy"}
    world.ticks(2, **up)
    store = world.watch.store
    store.add_window(world.now, world.now + timedelta(hours=1), ["histcraft"], "Upgrade", "ana")
    # The Historian stops inside the window: nothing opens, nobody is told.
    stopped = {**up, "histcraft": "exited"}
    assert world.ticks(10, **stopped) == []
    assert "service:histcraft" not in store.open_incidents()
    # Another app is still watched.
    posted = world.ticks(10, **{**stopped, "dashcraft": "exited"})
    assert any("dashcraft" in text for text in posted)
    assert not any("histcraft" in text for text in posted)
    assert world.watch.overview()["maintenance"][0]["reason"] == "Upgrade"
    # After the window, the Historian down is an incident again.
    world.now += timedelta(hours=1)
    posted = world.ticks(10, **{**stopped, "dashcraft": "healthy"})
    assert any("histcraft" in text for text in posted)
    report = world.watch.uptime()
    rows = {row["service"]: row for row in report["services"]}
    assert rows["histcraft"]["uptime"]["24h"] < 100
    assert report["windows"][0]["services"] == ["histcraft"]


def test_an_administrator_plans_and_ends_a_window(world):
    admin = sign_in(world.client())
    op = sign_in(world.client(), "op", PASSWORD)
    plan = {"hours": 2, "services": ["histcraft"], "reason": "Historian upgrade"}
    assert op.post("/api/operations/maintenance/windows", json=plan).status_code == 403
    answer = admin.post("/api/operations/maintenance/windows", json=plan)
    assert answer.status_code == 201, answer.text
    window = answer.json()
    assert window["services"] == ["histcraft"]
    assert audit(admin, "operations.maintenance.planned")
    shown = admin.get("/api/operations/uptime").json()
    assert [item["window_id"] for item in shown["windows"]] == [window["window_id"]]
    bad = admin.post("/api/operations/maintenance/windows", json={**plan, "reason": " "})
    assert bad.status_code == 422
    ended = admin.delete(f"/api/operations/maintenance/windows/{window['window_id']}")
    assert ended.status_code == 200 and ended.json()["ended_at"]
    assert audit(admin, "operations.maintenance.ended")
    again = admin.delete(f"/api/operations/maintenance/windows/{window['window_id']}")
    assert again.status_code == 409
    # A window planned for later is cancelled outright.
    later = admin.post(
        "/api/operations/maintenance/windows",
        json={**plan, "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    ).json()
    cancelled = admin.delete(f"/api/operations/maintenance/windows/{later['window_id']}")
    assert cancelled.json()["cancelled"] is True
