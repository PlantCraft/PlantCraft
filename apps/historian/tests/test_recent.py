"""The recent values (Historian 0.5): the collector writes every point's new values as one row
every few seconds and moves them into chunks once a minute; reads see them either way."""

from __future__ import annotations

import numpy as np

from histcraft.archive.store import ArchiveStore
from tests.conftest import database


def _store(tmp_path) -> ArchiveStore:
    return ArchiveStore(database(tmp_path))


def _count(archive: ArchiveStore, table: str) -> int:
    with archive.db.connect() as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_held_values_read_before_and_after_they_settle(tmp_path):
    archive = _store(tmp_path)
    archive.append({1: ("number", [(0, 1.0), (1000, 2.0)])})
    assert archive.hold({1: ("number", [(2000, 3.0)]), 2: ("text", [(2000, "AUTO")])}) == 2
    assert archive.hold({1: ("number", [(3000, 4.0)])}) == 1
    assert _count(archive, "recent") == 2
    before = archive.read_many([1, 2], 0, 10_000)
    assert before[1][0].tolist() == [0, 1000, 2000, 3000]
    assert before[1][1].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert before[2][1] == ["AUTO"]
    assert archive.settle() == 3
    assert _count(archive, "recent") == 0
    after = archive.read_many([1, 2], 0, 10_000)
    assert after[1][0].tolist() == before[1][0].tolist()
    assert after[1][1].tolist() == before[1][1].tolist()
    assert after[2][1] == ["AUTO"]
    # One chunk per point for all the rows settled together.
    assert archive.point_stats()[1]["chunks"] == 2


def test_a_read_keeps_the_range_and_its_neighbours_across_held_values(tmp_path):
    archive = _store(tmp_path)
    archive.append({1: ("number", [(0, 0.0), (10_000, 10.0)])})
    archive.hold({1: ("number", [(20_000, 20.0), (30_000, 30.0)])})
    times, _ = archive.read(1, 12_000, 18_000)
    assert times.tolist() == [10_000, 20_000]


def test_a_settle_in_between_never_loses_or_repeats_values(tmp_path):
    archive = _store(tmp_path)
    archive.hold({1: ("number", [(1000, 1.0)])})
    archive.read(1, 0, 5000)  # the row is now decoded in this process
    archive.settle()
    archive.hold({1: ("number", [(2000, 2.0)])})
    times, values = archive.read(1, 0, 5000)
    assert times.tolist() == [1000, 2000] and values.tolist() == [1.0, 2.0]


def test_nothing_held_settles_nothing(tmp_path):
    archive = _store(tmp_path)
    assert archive.hold({1: ("number", [])}) == 0
    assert archive.settle() == 0
    assert _count(archive, "recent") == 0


def test_settled_values_count_per_hour_and_merge_with_a_repeated_chunk(tmp_path):
    archive = _store(tmp_path)
    archive.hold({1: ("number", [(0, 1.0), (3_600_000, 2.0)])})
    archive.settle()
    # The same run again (a flush retried after a failure) merges into the chunk it starts.
    archive.hold({1: ("number", [(0, 1.0), (3_600_000, 2.0), (3_601_000, 3.0)])})
    archive.settle()
    times, values = archive.read(1, 0, 4_000_000)
    assert times.tolist() == [0, 3_600_000, 3_601_000]
    assert values.tolist() == [1.0, 2.0, 3.0]
    assert archive.point_stats()[1]["chunks"] == 1


def test_a_damaged_row_is_skipped_not_a_failed_read(tmp_path):
    archive = _store(tmp_path)
    archive.hold({1: ("number", [(1000, 1.0)])})
    with archive.db.connect() as connection:
        connection.execute("INSERT INTO recent VALUES (?, ?)", (2**40, b"\x30junk"))
    times, _ = archive.read(1, 0, 5000)
    assert times.tolist() == [1000]
    assert archive.settle() == 1
    assert np.array_equal(archive.read(1, 0, 5000)[0], [1000])
