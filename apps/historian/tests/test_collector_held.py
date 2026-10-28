"""Values the collector read are not lost when the archive's database fails (collector.held)."""

from __future__ import annotations

import math

import pytest

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector import held
from histcraft.collector.service import Collector
from histcraft.db import Database
from tests.conftest import make_settings

T0 = 1_760_000_000_000


@pytest.fixture
def parts(tmp_path):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:1/"), create=True
    )
    catalog.add_points(
        [
            PointIn(tag="TI-1", source_id="plant", address="ns=2;s=TI-1"),
            PointIn(tag="MODE", source_id="plant", address="ns=2;s=MODE", kind="text"),
        ]
    )
    return settings, catalog, archive


def collector_with_values(parts):
    settings, catalog, archive = parts
    collector = Collector(settings, catalog, archive)
    collector.reload()
    by_tag = {state.point["tag"]: state for state in collector.points.values()}
    by_tag["TI-1"].pending = [(T0, 1.0), (T0 + 1000, 2.0), (T0 + 2000, math.nan)]
    by_tag["MODE"].pending = [(T0, "AUTO")]
    return collector, by_tag


def failing(*_args, **_kwargs):
    raise ConnectionError("database restarting")


def test_a_failed_write_keeps_the_values_for_the_next_flush(parts, monkeypatch):
    _, _, archive = parts
    collector, by_tag = collector_with_values(parts)
    with monkeypatch.context() as patch:
        patch.setattr(archive, "hold", failing)
        with pytest.raises(ConnectionError):
            collector.flush()
    assert len(by_tag["TI-1"].pending) == 3
    assert by_tag["MODE"].pending == [(T0, "AUTO")]
    assert collector.flush() == 4
    times, values = archive.read(by_tag["TI-1"].id, T0, T0 + 2000)
    assert times.tolist() == [T0, T0 + 1000, T0 + 2000]
    assert values[:2].tolist() == [1.0, 2.0] and math.isnan(values[2])
    assert by_tag["TI-1"].pending == []


def test_a_long_outage_keeps_the_newest_values(parts, monkeypatch):
    _, _, archive = parts
    collector, by_tag = collector_with_values(parts)
    monkeypatch.setattr("histcraft.collector.service.HELD_LIMIT", 2)
    monkeypatch.setattr(archive, "hold", failing)
    with pytest.raises(ConnectionError):
        collector.flush()
    assert by_tag["TI-1"].pending[0] == (T0 + 1000, 2.0)
    assert collector.dropped == 1


def test_values_left_at_a_stop_wait_on_disk_for_the_next_collector(parts, monkeypatch):
    settings, catalog, archive = parts
    collector, by_tag = collector_with_values(parts)
    with monkeypatch.context() as patch:
        patch.setattr(archive, "hold", failing)
        with pytest.raises(ConnectionError):
            collector.flush()
        assert collector.save_held() == 4
    path = held.held_path(settings.data_dir)
    assert path.exists() and by_tag["TI-1"].pending == []

    following = Collector(settings, catalog, archive)
    following.reload()
    following.flush()
    assert not path.exists()
    times, values = archive.read(by_tag["MODE"].id, T0, T0)
    assert times.tolist() == [T0] and list(values) == ["AUTO"]
    times, _ = archive.read(by_tag["TI-1"].id, T0, T0 + 2000)
    assert len(times) == 3


def test_a_held_file_adds_to_what_it_holds_and_skips_bad_lines(tmp_path):
    path = held.held_path(tmp_path)
    held.save(path, {1: ("number", [(T0, 1.5)])})
    held.save(path, {1: ("number", [(T0 + 1, math.nan)]), 2: ("text", [(T0, None)])})
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
    found = held.load(path)
    assert found[1][1][0] == (T0, 1.5) and math.isnan(found[1][1][1][1])
    assert found[2] == ("text", [(T0, None)])


def test_flushes_write_recent_values_and_move_them_into_chunks_each_minute(parts):
    _, _, archive = parts
    collector, by_tag = collector_with_values(parts)
    collector.flush()  # the first flush settles what a last collector left
    with archive.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM recent").fetchone()[0] == 0
    by_tag["TI-1"].pending = [(T0 + 3000, 4.0)]
    collector.flush()  # within archive_seconds: one recent row, read all the same
    with archive.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM recent").fetchone()[0] == 1
    assert archive.read(by_tag["TI-1"].id, T0, T0 + 3000)[0].tolist()[-1] == T0 + 3000
    collector.flush(settle=True)  # at archive_seconds, or when the collector stops
    with archive.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM recent").fetchone()[0] == 0
    assert archive.read(by_tag["TI-1"].id, T0, T0 + 3000)[0].tolist()[-1] == T0 + 3000
