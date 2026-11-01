"""The plant tests read: ``FakePlantCraft`` with loops, a pump, a text mode and View users.

Signals are the fake's deterministic synthetic waves, live (not a recorded file), at a
fixed ``NOW``. Users cover every way in:

| User | Level | View |
|---|---|---|
| ``admin``, ``engineer`` | admin, editor | editor |
| ``operator`` | viewer | viewer |
| ``wallboard`` | dashboards | viewer (dashboards-only people) |
| ``outsider`` | viewer | none |
"""

from __future__ import annotations

from datetime import datetime, timezone

from plantcraft_sdk.testing import DEFAULT_ASSETS, DEFAULT_SIGNALS, FakePlantCraft

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
APP_KEY = "test-app-key"
# Another app of the suite, publishing results View cards can show.
LINK_KEY = "test-linkcraft-key"
# Alarms, publishing each area's alarm performance for the reports.
ALARM_KEY = "test-alarmcraft-key"

USERS = {
    "admin": {"name": "Administrator", "level": "admin", "apps": {"dashcraft": "editor"}},
    "engineer": {"name": "Process Engineer", "level": "editor", "apps": {"dashcraft": "editor"}},
    "operator": {"name": "Operator", "level": "viewer", "apps": {"dashcraft": "viewer"}},
    "wallboard": {"name": "Control Room", "level": "dashboards", "apps": {"dashcraft": "viewer"}},
    "outsider": {"name": "No Apps", "level": "viewer", "apps": {}},
}
APPS = [
    {"id": "dashcraft", "name": "PlantCraft View", "url": "/dash/", "version": "0.1.0"},
]
EXTRA_SIGNALS = [
    {
        "id": "fake:P-201.FLOW",
        "name": "Pump discharge flow",
        "source": "fake",
        "unit": "m3/h",
        "description": "Pump discharge flow",
        "low": 0.0,
        "high": 200.0,
    },
    {
        "id": "fake:P-201.STATE",
        "name": "Pump state",
        "source": "fake",
        "unit": "",
        "description": "Pump running state",
        "low": None,
        "high": None,
        "kind": "text",
    },
]
# What Analytics archives in Historian about FIC-101: its loop health over time (derived signals).
DERIVED_SIGNALS = [
    {
        "id": "app-linkcraft:FIC-101.health",
        "name": "FIC-101 loop health",
        "source": "app-linkcraft",
        "unit": "/100",
        "description": "Loop health score",
        "low": 0.0,
        "high": 100.0,
        "app": "linkcraft",
        "subject": "asset:fic-101",
        "result": "loop_health",
    },
    {
        "id": "app-linkcraft:FIC-101.health.status",
        "name": "FIC-101 loop health status",
        "source": "app-linkcraft",
        "unit": "",
        "description": "Loop health status",
        "low": None,
        "high": None,
        "kind": "text",
        "app": "linkcraft",
        "subject": "asset:fic-101",
        "result": "loop_health",
    },
]
EXTRA_ASSETS = [
    {
        "id": "p-201",
        "name": "P-201",
        "kind": "pump",
        "parent_id": "unit-100",
        "attributes": {"description": "Feed pump"},
        "signals": {"flow": "fake:P-201.FLOW", "state": "fake:P-201.STATE"},
    },
    {
        "id": "fic-109",
        "name": "FIC-109",
        "kind": "loop",
        "parent_id": "unit-100",
        "attributes": {"description": "A loop whose PV points at a signal PlantCraft lost"},
        "signals": {"pv": "fake:GONE.PV"},
    },
]


def make_fake(**options) -> FakePlantCraft:
    return FakePlantCraft(
        users=USERS,
        apps=APPS,
        app_keys={"dashcraft": APP_KEY, "linkcraft": LINK_KEY, "alarmcraft": ALARM_KEY},
        assets=DEFAULT_ASSETS + EXTRA_ASSETS,
        signals=DEFAULT_SIGNALS + EXTRA_SIGNALS + DERIVED_SIGNALS,
        now=NOW,
        **options,
    )


def publish_loop_health(fake: FakePlantCraft) -> None:
    """Analytics' loop health as it publishes it: FIC-101 needs attention, LIC-102's expired."""

    linkcraft = fake.client(None, app="linkcraft", key=LINK_KEY)
    receipt = linkcraft.put_results(
        [
            {
                "subject": "asset:fic-101",
                "kind": "loop_health",
                "status": "warning",
                "score": 62.5,
                "summary": "Oscillating, period 4 min",
                "expires_at": "2026-10-02T12:00:00+00:00",
            },
            {
                "subject": "asset:lic-102",
                "kind": "loop_health",
                "status": "ok",
                "score": 91,
                "summary": "Within limits",
                "expires_at": "2026-09-30T00:00:00+00:00",
            },
        ]
    )
    assert not receipt["errors"], receipt
