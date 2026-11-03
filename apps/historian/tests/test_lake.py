"""The data lake feed (``export.lake``): saved exports written as CSV files, one per hour or day,
into the lake's landing folder."""

from __future__ import annotations

import csv
from datetime import timedelta

from histcraft.archive.query import Reader, point_ref
from histcraft.collector.service import Collector
from histcraft.export import lake
from tests.conftest import client_for, make_settings
from tests.test_api import loaded  # noqa: F401
from tests.test_query import MS

HOUR = 3_600_000
FEED = {"name": "Unit 100 to the lake", "signals": ["plant:TI-100.PV", "plant:FIC-101.MODE"]}


def _rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_periods_are_whole_utc_hours_or_days_once_they_ended():
    now = MS + HOUR + 6 * 60_000
    # A new feed starts with the last period that ended, not the whole archive.
    assert lake.due("hourly", None, now) == [(MS, MS + HOUR)]
    # Before the lag has passed the period waits.
    assert lake.due("hourly", None, MS + HOUR + 60_000) == [(MS - HOUR, MS)]
    assert lake.due("hourly", MS + HOUR, now) == []
    # After a stop it catches up from where it left off, a day of hours per pass at most.
    behind = lake.due("hourly", MS - 30 * 24 * HOUR, now)
    assert len(behind) == lake.CATCH_UP and behind[0][0] == MS - 30 * 24 * HOUR
    day = 24 * HOUR
    assert lake.due("daily", None, MS + day + 10 * 60_000) == [(MS, MS + day)]


def test_an_hour_becomes_one_csv_in_a_dated_folder(runtime, loaded, tmp_path):  # noqa: F811
    saved = runtime.saved_exports.create(FEED["name"], {**FEED, "lake": "hourly"}, "admin")
    folder = tmp_path / "lake"
    written = lake.feed(
        folder,
        runtime.saved_exports.list(),
        runtime.lake_feeds,
        runtime.catalog.points(),
        Reader(runtime.archive),
        point_ref,
        MS + HOUR + 6 * 60_000,
    )
    name = f"unit-100-to-the-lake-{saved['id']}"
    assert written == [folder / name / "date=2026-10-19" / f"{name}_20261019T0000Z.csv"]
    rows = _rows(written[0])
    numbers = [row for row in rows if row["tag"] == "TI-100.PV"]
    # Every value of the hour, none of the next: 10 s apart from 00:00:00 to 00:59:50.
    assert len(numbers) == 360 and numbers[0]["time"] == "2026-10-19T00:00:00.000Z"
    assert numbers[-1]["time"] == "2026-10-19T00:59:50.000Z" and numbers[1]["value"] == "1.0"
    assert numbers[0]["unit"] == "degC" and numbers[0]["signal"] == "plant:TI-100.PV"
    assert [row["value"] for row in rows if row["tag"] == "FIC-101.MODE"] == ["AUTO", "MAN"]
    signals = _rows(folder / name / "signals.csv")
    assert {row["tag"] for row in signals} == {"TI-100.PV", "FIC-101.MODE"}
    state = runtime.lake_feeds.all()[saved["id"]]
    assert state["next_start"] == MS + HOUR and state["last_rows"] == 362
    assert state["last_error"] == "" and state["last_file"].endswith("T0000Z.csv")
    # Nothing is due again until the next hour ends; no half-written file is left behind.
    again = lake.feed(
        folder,
        runtime.saved_exports.list(),
        runtime.lake_feeds,
        runtime.catalog.points(),
        Reader(runtime.archive),
        point_ref,
        MS + HOUR + 7 * 60_000,
    )
    assert again == [] and not list(folder.rglob(".*.part"))


def test_a_feed_turned_off_stops_and_a_gone_tag_is_named(runtime, loaded, tmp_path):  # noqa: F811
    body = {"signals": ["plant:TI-100.PV", "plant:GONE"], "lake": "hourly"}
    saved = runtime.saved_exports.create("Feed", body, "admin")
    args = (runtime.catalog.points(), Reader(runtime.archive), point_ref, MS + HOUR + 6 * 60_000)
    lake.feed(tmp_path, runtime.saved_exports.list(), runtime.lake_feeds, *args)
    assert "plant:GONE" in runtime.lake_feeds.all()[saved["id"]]["last_error"]
    runtime.saved_exports.update(saved["id"], "Feed", {**body, "lake": "off"}, "admin")
    assert lake.feed(tmp_path, runtime.saved_exports.list(), runtime.lake_feeds, *args) == []
    assert runtime.lake_feeds.all() == {}


def test_a_folder_that_cannot_be_written_is_retried_from_the_same_hour(
    runtime,
    loaded,  # noqa: F811
    tmp_path,
):
    saved = runtime.saved_exports.create("Feed", {**FEED, "lake": "hourly"}, "admin")
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("a file where the lake folder should be")
    args = (runtime.catalog.points(), Reader(runtime.archive), point_ref, MS + HOUR + 6 * 60_000)
    assert lake.feed(blocked, runtime.saved_exports.list(), runtime.lake_feeds, *args) == []
    state = runtime.lake_feeds.all()[saved["id"]]
    assert state["next_start"] == MS and state["last_error"]
    assert lake.feed(tmp_path / "lake", runtime.saved_exports.list(), runtime.lake_feeds, *args)
    assert runtime.lake_feeds.all()[saved["id"]]["next_start"] == MS + HOUR


def test_old_day_folders_are_deleted_and_nothing_else(tmp_path):
    export = tmp_path / "feed-1"
    for day in ("2026-10-01", "2026-10-18", "2026-10-19"):
        (export / f"date={day}").mkdir(parents=True)
    (export / "signals.csv").write_text("signal\n")
    (tmp_path / "someone-elses.txt").write_text("kept")
    (export / "notes").mkdir()
    assert lake.prune(tmp_path, 7, MS) == 1
    assert sorted(item.name for item in export.iterdir()) == [
        "date=2026-10-18",
        "date=2026-10-19",
        "notes",
        "signals.csv",
    ]
    assert lake.prune(tmp_path, 0, MS + int(timedelta(days=90).total_seconds() * 1000)) == 0


def test_only_an_administrator_sends_an_export_to_the_lake(runtime, fake, loaded):  # noqa: F811
    body = {**FEED, "hours": 1, "lake": "hourly"}
    with client_for(runtime, fake, "engineer") as editor:
        assert editor.post("/hist/api/export/saved", json=body).status_code == 403
        plain = editor.post("/hist/api/export/saved", json={**body, "lake": "off"}).json()
        assert editor.get("/hist/api/export/options").json()["lake"]["can_schedule"] is False
    with client_for(runtime, fake, "admin") as admin:
        options = admin.get("/hist/api/export/options").json()["lake"]
        assert options["can_schedule"] is True and options["keep_days"] == 7
        assert options["folder"].endswith("lake")
        fed = admin.put(f"/hist/api/export/saved/{plain['id']}", json=body)
        assert fed.status_code == 200 and fed.json()["lake"] == "hourly"
        listed = admin.get("/hist/api/export/saved").json()[0]
        assert listed["lake"] == "hourly" and listed["lake_state"]["last_file"] == ""
    with client_for(runtime, fake, "engineer") as editor:
        # An export whose feed is on is the administrator's to change or delete.
        assert editor.delete(f"/hist/api/export/saved/{plain['id']}").status_code == 403
        off = {**body, "lake": "off"}
        assert editor.put(f"/hist/api/export/saved/{plain['id']}", json=off).status_code == 403


def test_the_collector_writes_the_feeds_that_are_due(tmp_path, loaded):  # noqa: F811
    settings = make_settings(tmp_path, lake_dir=str(tmp_path / "landing"))
    collector = Collector(settings, loaded.catalog, loaded.archive)
    assert collector.feed_lake(force=True) == []  # no feed on: nothing written
    loaded.saved_exports.create("Feed", {**FEED, "lake": "daily"}, "admin")
    written = collector.feed_lake(force=True)
    assert len(written) == 1 and written[0].is_relative_to(tmp_path / "landing")
    assert written[0].name.endswith("T0000Z.csv")
    assert collector.feed_lake() == []  # checked once a minute
