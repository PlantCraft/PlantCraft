"""Shared fixtures: the fake PlantCraft of ``tests/plant.py`` and a PlantCraft Alarms wired to it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.testing import BASE_URL

from alarmcraft.api.app import create_app
from alarmcraft.api.runtime import Runtime
from alarmcraft.config import Settings
from tests.plant import APP_KEY, make_fake


def make_runtime(tmp_path, fake, *, app_key: bool = True, **settings) -> Runtime:
    settings.setdefault("monitor", False)
    return Runtime(
        Settings(processcraft_url=BASE_URL, data_dir=tmp_path, **settings),
        verifier=fake.verifier("alarmcraft"),
        service_client=fake.client(None, app="alarmcraft", key=APP_KEY) if app_key else None,
        http_client=fake.http_client(),
        clock=lambda: fake.now,
    )


@pytest.fixture
def fake():
    return make_fake()


@pytest.fixture
def runtime(tmp_path, fake):
    rt = make_runtime(tmp_path, fake)
    yield rt
    rt.shutdown()


def client_for(runtime: Runtime, fake, username: str | None = "engineer") -> TestClient:
    client = TestClient(
        create_app(runtime), base_url="http://testserver/alarm/", raise_server_exceptions=False
    )
    if username:
        client.headers["Authorization"] = f"Bearer {fake.token(username)}"
    return client


@pytest.fixture
def client(runtime, fake):
    with client_for(runtime, fake) as test_client:
        yield test_client


PV = "plantcraft:CPM.Loops.FIC-1001.PV"


def high(
    limit: float | None = 50.0,
    *,
    role: str = "pv",
    signal_id: str | None = None,
    assets: list[str] | None = None,
    under: list[str] | None = None,
    unit: str = "m3/h",
    deadband: float = 0.5,
    op: str = ">=",
    for_seconds: float = 0.0,
    **fields,
) -> dict:
    """A Simple rule on FIC-1001's PV (about 55) at or above ``limit``: raised at once with the
    default 50. One asset, so its one alarm takes the rule's id."""

    # A signal named instead of the role: ``signal_id=..., role=""``.
    value = {"role": role, "unit": unit}
    if signal_id is not None:
        value["signal"] = signal_id
    where = {"assets": ["FIC-1001"] if assets is None else assets}
    if under:
        where["under"] = under
    condition = {"input": "value", "value": value, "op": op, "limit": limit, "deadband": deadband}
    if for_seconds:
        condition["for_seconds"] = for_seconds
    return {
        "name": "FIC-1001 PV high",
        "where": where,
        "editor": "simple",
        "simple": {"conditions": [condition]},
        "priority": "high",
        "cause": "Feed pump overspeed",
        "consequence": "Downstream column floods",
        "action": "Reduce the pump speed",
        **fields,
    }


def events_rule(kinds: list[str], *, test: str = "open", about: str = "subject", **fields) -> dict:
    """A Simple rule on events of ``kinds`` about each asset (``where`` from ``fields``, any
    asset the events name by default; ``about="any"`` with ``where={}``: one alarm for all)."""

    condition = {"input": "event", "event": {"kinds": kinds, "about": about}, "test": test}
    for key in ("count", "window_minutes", "for_seconds"):
        if key in fields:
            condition[key] = fields.pop(key)
    return {
        "name": f"{kinds[0]} events",
        "where": fields.pop("where", {"anywhere": True}),
        "editor": "simple",
        "simple": {"conditions": [condition]},
        "priority": "medium",
        **fields,
    }


def notify(**fields) -> dict:
    """A rule's notifications: sent at once (no gathering), no reminders, unless set."""

    return {"group_seconds": 0, "repeat_minutes": 0, **fields}


def make_rule(client, body: dict) -> dict:
    created = client.post("/api/rules", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def pytest_sessionfinish(session, exitstatus):
    """The app's token used only what app.toml [permissions] declares (PlantCraft answers 403)."""

    from pathlib import Path

    from plantcraft_sdk import apptest

    problems = apptest.permission_problems(Path(__file__).resolve().parents[1], "alarmcraft")
    if problems and exitstatus == 0:
        print("\n" + "\n".join(problems))
        session.exitstatus = 1
