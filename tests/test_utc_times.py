"""Every time in UTC (owner, 2026-10-23): one text form, whatever the server's time zone, and the
rows written before in the server's local offset rewritten once."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from plantcraft_sdk.utc import is_instant, normalize_times, utc_iso
from processcraft.db import Database, Store, utc_text
from processcraft.platform.workspace import UTC_TIMES, Workspace


@pytest.fixture(params=["America/Sao_Paulo", "Asia/Kolkata", "UTC"])
def server_zone(request, monkeypatch):
    """The server's own time zone, which must change nothing."""

    monkeypatch.setenv("TZ", request.param)
    time.tzset()
    yield request.param
    monkeypatch.undo()
    time.tzset()


def test_one_form_whatever_the_servers_zone(server_zone):
    stamp = Store._now()
    assert stamp.endswith("Z") and len(stamp) == len("2026-10-23T14:05:09.123Z")
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert abs(moment - datetime.now(timezone.utc)) < timedelta(seconds=5)
    assert utc_text("2026-10-23T11:05:09-03:00") == "2026-10-23T14:05:09.000Z"
    assert utc_text("2026-10-23 14:05") == "2026-10-23T14:05:00.000Z"  # no offset: UTC
    assert (
        utc_iso(
            datetime(
                2026, 10, 23, 19, 35, 9, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30))
            )
        )
        == "2026-10-23T14:05:09.123Z"
    )


def test_text_order_is_time_order():
    texts = [
        utc_text(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=step))
        for step in (0, 0.5, 9, 10, 3600)
    ]
    assert texts == sorted(texts)
    # Local offsets did not sort: 11:00-03:00 is after 13:00+00:00 yet sorts before it.
    assert "2026-10-23T11:00:00-03:00" < "2026-10-23T13:00:00+00:00"
    assert utc_text("2026-10-23T11:00:00-03:00") > utc_text("2026-10-23T13:00:00+00:00")


def test_old_rows_are_rewritten_once_and_dates_stay(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE things (id INTEGER PRIMARY KEY, created_at TEXT, due_at TEXT, at TEXT, note TEXT)"
        )
        connection.execute(
            "INSERT INTO things (created_at, due_at, at, note) VALUES (?, ?, ?, ?)",
            (
                "2026-10-20T08:00:00-03:00",
                "2026-10-31",
                "2026-10-20T11:00:00+00:00",
                "2026-10-20T08:00:00-03:00",
            ),
        )
    workspace = Workspace(path)
    assert workspace.migrated(UTC_TIMES)
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT created_at, due_at, at, note FROM things").fetchone()
        assert row == (
            "2026-10-20T11:00:00.000Z",
            "2026-10-31",
            "2026-10-20T11:00:00.000Z",
            "2026-10-20T08:00:00-03:00",
        )
        assert normalize_times(connection) == 0  # nothing left to change


def test_api_answers_times_in_utc(tmp_path):
    workspace = Workspace(Database(tmp_path / "w.sqlite3"))
    workspace.audit.record("admin", "test.done", "x", {}, app_id="processcraft")
    row = workspace.audit.list(limit=1)[0]
    assert is_instant(row["at"]) and row["at"].endswith("Z")


def test_the_plant_day_follows_the_plant_zone(monkeypatch):
    from processcraft import config

    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "Pacific/Kiritimati")  # UTC+14
    ahead = config.plant_today()
    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "Pacific/Pago_Pago")  # UTC-11
    behind = config.plant_today()
    assert ahead > behind
    monkeypatch.setenv("PLANTCRAFT_TIMEZONE", "Not/AZone")
    assert config.plant_timezone().key == "UTC"
    assert os.environ["PLANTCRAFT_TIMEZONE"] == "Not/AZone"
