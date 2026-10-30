"""CSV sources: a file or folder another application keeps writing, checked
every few minutes; only rows after the newest archived value are added, and files are only read."""

from __future__ import annotations

import os

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector
from histcraft.sources.csv_watch import CsvWatcher
from tests.conftest import database, make_settings


def test_new_rows_and_new_files_are_archived_once(tmp_path):
    folder = tmp_path / "lims"
    folder.mkdir()
    day1 = folder / "day1.csv"
    day1.write_text("time,DENSITY\n2026-10-20 00:00,0.85\n2026-10-20 04:00,0.86\n")
    settings = make_settings(tmp_path)
    catalog = CatalogStore(database(tmp_path, "config"))
    archive = ArchiveStore(database(tmp_path))
    catalog.save_source(
        SourceIn(
            id="lims",
            name="LIMS",
            kind="csv",
            endpoint=str(folder / "*.csv"),
            options={"timezone": "UTC", "check_minutes": 1},
        ),
        create=True,
    )
    catalog.add_points([PointIn(tag="DENSITY", source_id="lims")])
    collector = Collector(settings, catalog, archive)
    collector.reload()
    source = catalog.source("lims")
    assert source["mode"] == "archive"
    watcher = CsvWatcher(source)
    point = catalog.point("lims:DENSITY")

    def check_and_flush():
        collector._take_csv("lims", watcher.check())
        collector.flush()
        span = archive.span(int(point["id"]))
        times, values = archive.read(int(point["id"]), 0, 2**62)
        return list(values), span

    values, _ = check_and_flush()
    assert values == [0.85, 0.86]
    # Unchanged files are not read again; a grown file adds only its new rows.
    assert check_and_flush()[0] == [0.85, 0.86]
    with day1.open("a") as handle:
        handle.write("2026-10-20 08:00,0.87\n")
    os.utime(day1, ns=(day1.stat().st_atime_ns, day1.stat().st_mtime_ns + 1_000_000))
    assert check_and_flush()[0] == [0.85, 0.86, 0.87]
    # A new daily file (another shape, ; and decimal comma) is picked up too.
    (folder / "day2.csv").write_text("Data;DENSITY\n21/10/2026 00:00;0,88\n")
    assert check_and_flush()[0] == [0.85, 0.86, 0.87, 0.88]
    # The files were only read.
    assert sorted(path.name for path in folder.iterdir()) == ["day1.csv", "day2.csv"]


def test_a_check_period_out_of_range_is_refused(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="0.5 to 1440"):
        SourceIn(
            id="lims",
            name="LIMS",
            kind="csv",
            endpoint=str(tmp_path / "*.csv"),
            options={"check_minutes": 0},
        )


def test_a_pattern_only_in_the_file_name(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="reads only files in"):
        SourceIn(id="lims", name="LIMS", kind="csv", endpoint=str(tmp_path / "*" / "a.csv"))
