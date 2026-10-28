import math

import numpy as np
import pytest

from histcraft.archive.store import CHUNK_VALUES, ArchiveStore
from histcraft.db import Database
from tests.conftest import database, sqlite_only


def make(tmp_path) -> ArchiveStore:
    return ArchiveStore(database(tmp_path))


def fill(archive, point=1, chunks=10, per=100, kind="number"):
    for c in range(chunks):
        samples = [((c * per + i) * 1000, float(c * per + i)) for i in range(per)]
        if kind == "text":
            samples = [(at, str(int(v))) for at, v in samples]
        archive.append({point: (kind, samples)})


def test_read_returns_the_range_and_one_neighbour_each_side(tmp_path):
    archive = make(tmp_path)
    fill(archive)
    times, values = archive.read(1, 150_500, 420_200)
    assert times[0] == 150_000 and times[-1] == 421_000
    assert values[1] == 151.0
    assert np.all(np.diff(times) > 0)


def test_read_finds_the_chunks_of_any_range_by_their_start(tmp_path):
    # Ranges starting and ending inside a chunk, on its first or last value, between chunks,
    # all inside one chunk: the values in the range and exactly one neighbour each side.
    archive = make(tmp_path)
    fill(archive, chunks=6, per=100)
    every = np.arange(600) * 1000
    edges = (-5_000, 0, 50_500, 99_000, 99_500, 100_000, 250_000, 399_000, 599_000, 700_000)
    for start in edges:
        for end in edges:
            if end < start:
                continue
            inside = every[(every >= start) & (every <= end)].tolist()
            before, after = every[every < start][-1:], every[every > end][:1]
            expected = before.tolist() + inside + after.tolist()
            assert archive.read(1, start, end)[0].tolist() == expected, (start, end)
    assert archive.read(1, 120_200, 120_700)[0].tolist() == [120_000, 121_000]


def test_read_outside_the_data(tmp_path):
    archive = make(tmp_path)
    fill(archive, chunks=1, per=10)
    times, _ = archive.read(1, 100_000, 200_000)
    assert times.tolist() == [9000]
    times, _ = archive.read(1, -50_000, -10_000)
    assert times.tolist() == [0]
    assert len(archive.read(2, 0, 10)[0]) == 0


def test_compact_merges_chunks_without_changing_values(tmp_path):
    archive = make(tmp_path)
    fill(archive, chunks=30, per=50)
    before = archive.read(1, 0, 10**9)
    removed = archive.compact(10**12)
    assert removed == 29
    assert archive.point_stats()[1]["chunks"] == 1
    after = archive.read(1, 0, 10**9)
    assert before[0].tolist() == after[0].tolist()
    assert before[1].tolist() == after[1].tolist()


def test_compact_keeps_chunks_at_most_chunk_values(tmp_path):
    archive = make(tmp_path)
    fill(archive, chunks=25, per=1000)
    archive.compact(10**12)
    stats = archive.point_stats()[1]
    assert stats["values"] == 25_000
    assert stats["chunks"] == math.ceil(25_000 / CHUNK_VALUES)


def test_a_long_backlog_compacts_in_steps_with_the_same_result(tmp_path, monkeypatch):
    # A backfill leaves a point with thousands of small chunks: they merge a few at a time
    # (COMPACT_CHUNKS) and in batches of fewer points, never all in memory at once.
    from histcraft.archive import store

    archive = make(tmp_path)
    for point in (1, 2, 3):
        fill(archive, point=point, chunks=40, per=10)
    before = [archive.read(point, 0, 10**9) for point in (1, 2, 3)]
    monkeypatch.setattr(store, "COMPACT_CHUNKS", 7)
    assert archive.compact(10**12) == 3 * 39
    for point, (times, values) in zip((1, 2, 3), before, strict=True):
        assert archive.point_stats()[point]["chunks"] == 1
        assert archive.read(point, 0, 10**9)[0].tolist() == times.tolist()
        assert archive.read(point, 0, 10**9)[1].tolist() == values.tolist()
    assert archive.compact(10**12, points=[1, 2, 3]) == 0


def test_compact_leaves_text_readable(tmp_path):
    archive = make(tmp_path)
    fill(archive, chunks=3, per=5, kind="text")
    archive.compact(10**12)
    assert archive.read(1, 0, 10**9)[1][:3] == ["0", "1", "2"]


def test_prune_deletes_whole_chunks_before_the_cutoff(tmp_path):
    archive = make(tmp_path)
    fill(archive, chunks=5, per=100)
    assert archive.prune({1: 250_000}) == 2
    assert archive.point_stats()[1]["first"] == 200_000


def test_a_second_write_at_the_same_start_merges(tmp_path):
    archive = make(tmp_path)
    archive.append({1: ("number", [(0, 1.0), (2000, 2.0)])})
    archive.append({1: ("number", [(0, 1.5), (1000, 3.0)])})
    times, values = archive.read(1, 0, 5000)
    assert times.tolist() == [0, 1000, 2000]
    assert values.tolist() == [1.5, 3.0, 2.0]


def test_delete_points_and_point_ids(tmp_path):
    archive = make(tmp_path)
    fill(archive, point=1, chunks=1)
    fill(archive, point=2, chunks=1)
    archive.put_snapshots([{"point": 3, "ts": 1, "value": 1.0, "status": "ok"}])
    assert archive.point_ids() == {1, 2, 3}
    archive.delete_points([1, 3])
    assert archive.point_ids() == {2}


def test_delete_points_leaves_no_row_of_them_in_any_table(tmp_path):
    """The bench's cleanup left 218,400 rows in point_hours (2026-10-26): every point table is
    deleted from, and rows a failed delete left are found again by ``point_ids``."""

    archive = make(tmp_path)
    for point in range(1, 1201):  # more than one batch
        fill(archive, point=point, chunks=1)
    with archive._connect() as connection:
        connection.execute("INSERT INTO point_hours VALUES (5000, 0, 3)")
    assert 5000 in archive.point_ids()  # left only in point_hours: still swept
    archive.delete_points([*range(1, 1201), 5000])
    assert archive.point_ids() == set()
    with archive._connect() as connection:
        for table in ("chunks", "point_hours", "rollups", "snapshots", "point_totals"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_delete_points_tries_again_after_a_deadlock(tmp_path, monkeypatch):
    archive = make(tmp_path)
    fill(archive, point=1, chunks=1)
    real = archive._connect
    failures = []

    class Deadlock(Exception):
        sqlstate = "40P01"

    def connect():
        if not failures:
            failures.append(1)
            raise Deadlock("deadlock detected")
        return real()

    monkeypatch.setattr(archive, "_connect", connect)
    archive.delete_points([1])
    assert failures == [1]
    assert archive.point_ids() == set()

    class Broken(Exception):
        sqlstate = "42P01"

    monkeypatch.setattr(archive, "_connect", lambda: (_ for _ in ()).throw(Broken("no table")))
    with pytest.raises(Broken):
        archive.delete_points([1])


@sqlite_only
def test_database_files_are_shared_with_the_group(tmp_path):
    """Server and direct collector run as different users in one group (app standard)."""

    ArchiveStore(Database(tmp_path / "archive.sqlite3"))
    files = list(tmp_path.glob("archive.sqlite3*"))
    assert files
    for path in files:
        assert path.stat().st_mode & 0o777 == 0o660, path.name


def test_read_many_answers_as_read_of_each_point(tmp_path):
    archive = make(tmp_path)
    fill(archive, point=1)
    fill(archive, point=2, chunks=3, per=50)
    fill(archive, point=3, chunks=2, per=10, kind="text")
    for start, end in ((150_500, 420_200), (-50_000, -10_000), (10_000_000, 20_000_000), (0, 0)):
        many = archive.read_many([3, 1, 2, 4, 1], start, end)
        assert sorted(many) == [1, 2, 3, 4]
        for point in (1, 2, 3, 4):
            times, values = archive.read(point, start, end)
            assert many[point][0].tolist() == times.tolist()
            assert list(many[point][1]) == list(values)
    assert archive.read_many([], 0, 10) == {}


def test_point_totals_are_kept_by_the_collector_and_counted_live_before(tmp_path):
    archive = make(tmp_path)
    fill(archive, chunks=2, per=50)
    # Before the first refresh the counts are taken from the chunks.
    assert archive.point_stats()[1]["values"] == 100
    assert archive.refresh_totals() == 1
    fill(archive, point=2, chunks=1, per=10)
    # After it, the page reads what the collector counted (point 2 waits for the next one).
    assert set(archive.point_stats()) == {1}
    archive.refresh_totals()
    assert archive.point_stats()[2]["values"] == 10
    archive.delete_points([2])
    assert set(archive.point_stats()) == {1}


def test_values_per_day_count_the_last_24_hours_by_value_time(tmp_path):
    from histcraft.archive.store import HOUR_MS, now_ms

    archive = make(tmp_path)
    now = now_ms()
    recent = [(now - 3 * HOUR_MS + i * 1000, float(i)) for i in range(30)]
    old = [(now - 3 * 24 * HOUR_MS + i * 1000, float(i)) for i in range(20)]
    archive.append({1: ("number", old)})
    archive.append({1: ("number", recent)})
    archive.replace(2, "number", [(now - HOUR_MS, 1.0), (now - HOUR_MS + 1000, 2.0)])
    stats = archive.point_stats()
    assert stats[1]["values"] == 50 and stats[1]["day"] == 30
    assert stats[2]["day"] == 2
