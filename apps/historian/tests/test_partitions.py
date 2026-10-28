"""Monthly partitions of the PostgreSQL archive: months made as writes need them, reads across
months, the migration of an archive made before them, and retention dropping whole months."""

import threading
from datetime import datetime, timezone

import psycopg
import pytest

from histcraft.archive import codec, partitions
from histcraft.archive.store import HOUR_MS, ArchiveStore
from histcraft.db import Database
from tests.conftest import TEST_DATABASE_URL, database, postgres_only, postgres_url


def ms(year, month, day=1, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def tables(db, prefix):
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT relname FROM pg_class WHERE relname LIKE ? AND relkind = 'r' AND relnamespace ="
            " (SELECT oid FROM pg_namespace WHERE nspname = current_schema())",
            (f"{prefix}%",),
        ).fetchall()
    return sorted(str(row[0]) for row in rows)


def test_months_and_bounds():
    assert partitions.month_of(ms(2026, 10, 31, 23)) == (2026, 10)
    assert partitions.month_of(-1) == (1969, 12)
    assert partitions.month_of(ms(1899, 12)) is None
    assert partitions.month_of(ms(2200, 1)) is None
    assert partitions.bounds(2026, 12) == (ms(2026, 12), ms(2027, 1))
    assert partitions.partition_name("chunks", 2026, 3) == "chunks_y2026m03"


@postgres_only
def test_a_write_makes_its_months_and_reads_cross_them(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    end_of_september = ms(2026, 10) - 60_000
    archive.append({1: ("number", [(end_of_september, 1.0), (ms(2026, 10) - 1, 2.0)])})
    archive.append({1: ("number", [(ms(2026, 10, 1, 1), 3.0)])})
    archive.append({2: ("number", [(ms(1850, 1), 9.0), (ms(2300, 1), 8.0)])})
    assert tables(archive.db, "chunks_") == [
        "chunks_after",
        "chunks_before",
        "chunks_y2026m09",
        "chunks_y2026m10",
    ]
    times, values = archive.read(1, end_of_september + 1, ms(2026, 10, 1, 0) + 1)
    assert values.tolist() == [1.0, 2.0, 3.0]  # both neighbours, from both months
    assert archive.read(2, ms(1900, 1), ms(2100, 1))[1].tolist() == [9.0, 8.0]
    archive.replace(1, "number", [(ms(2026, 11, 15), 4.0)])
    archive.put_rollups(1, False, [(ms(2026, 12, 1), 1.0, 2.0)])
    assert "chunks_y2026m11" in tables(archive.db, "chunks_")
    assert "rollups_y2026m12" in tables(archive.db, "rollups_")
    assert archive.file_bytes() > 0


@postgres_only
def test_a_new_month_while_another_write_is_open(tmp_path):
    """Making a month never waits for writes in flight (it is attached, not created in place)."""

    archive = ArchiveStore(database(tmp_path))
    archive.append({1: ("number", [(ms(2026, 9, 2), 1.0)])})
    url = postgres_url(tmp_path)
    with psycopg.connect(url) as other:
        other.execute(
            "INSERT INTO chunks VALUES (2, %s, %s, 1, %s)",
            (ms(2026, 9, 3), ms(2026, 9, 3), codec.encode([ms(2026, 9, 3)], [1.0], "number")),
        )
        done = threading.Event()

        def write():
            archive.append({1: ("number", [(ms(2027, 1, 5), 2.0)])})
            done.set()

        threading.Thread(target=write, daemon=True).start()
        assert done.wait(20), "a new month waited for an open write"
        other.rollback()
    assert archive.read(1, ms(2027, 1, 1), ms(2027, 2, 1))[1].tolist() == [1.0, 2.0]


@postgres_only
def test_a_month_dropped_by_another_process_is_made_again(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    archive.append({1: ("number", [(ms(2026, 5, 2), 1.0)])})
    with archive.db.connect() as connection:
        connection.execute("DROP TABLE chunks_y2026m05")
    archive.append({1: ("number", [(ms(2026, 5, 3), 2.0)])})  # its cache still has May
    assert archive.read(1, ms(2026, 5, 1), ms(2026, 6, 1))[1].tolist() == [2.0]


@postgres_only
def test_retention_drops_whole_past_months(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    for month in (1, 2, 3):
        archive.append({1: ("number", [(ms(2026, month, 10), float(month))])})
        archive.append({2: ("number", [(ms(2026, month, 10), float(month))])})
        archive.put_rollups(1, False, [(ms(2026, month, 10), 1.0, 1.0)])
    archive.append({3: ("number", [(ms(2026, 1, 20), 5.0)])})
    # Point 3 is not in the catalog any more: January stays; February goes for 1 and 2.
    removed = archive.prune({1: ms(2026, 3, 1), 2: ms(2026, 3, 1)})
    assert tables(archive.db, "chunks_y") == ["chunks_y2026m01", "chunks_y2026m03"]
    assert tables(archive.db, "rollups_y") == ["rollups_y2026m03"]
    assert removed == 4  # February's two chunks dropped with its table, January's two deleted
    assert archive.read(1, ms(2026, 1, 1), ms(2026, 4, 1))[1].tolist() == [3.0]
    assert archive.read(3, ms(2026, 1, 1), ms(2026, 4, 1))[1].tolist() == [5.0]
    # Values past retention but in a month still holding newer ones stay a month table.
    archive.append({1: ("number", [(ms(2026, 3, 20), 6.0)])})
    archive.prune({1: ms(2026, 3, 15), 2: ms(2026, 3, 15), 3: ms(2026, 3, 15)})
    assert tables(archive.db, "chunks_y") == ["chunks_y2026m03"]
    assert archive.read(1, ms(2026, 3, 1), ms(2026, 4, 1))[1].tolist() == [6.0]


@postgres_only
def test_an_archive_from_before_partitions_is_migrated_once(tmp_path):
    url = postgres_url(tmp_path)
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(
            "CREATE TABLE chunks (point BIGINT NOT NULL, t0 BIGINT NOT NULL, t1 BIGINT NOT NULL,"
            " n BIGINT NOT NULL, data BYTEA NOT NULL, PRIMARY KEY(point, t0))"
        )
        connection.execute(
            "CREATE TABLE rollups (point BIGINT NOT NULL, hour BIGINT NOT NULL,"
            " step BIGINT NOT NULL, cover DOUBLE PRECISION NOT NULL,"
            " area DOUBLE PRECISION NOT NULL, PRIMARY KEY(point, hour))"
        )
        for point, at, value in ((1, ms(2026, 8, 31, 23), 1.0), (1, ms(2026, 9, 2), 2.0),
                                 (2, ms(1969, 12, 31, 23), 3.0)):  # fmt: skip
            connection.execute(
                "INSERT INTO chunks VALUES (%s, %s, %s, 1, %s)",
                (point, at, at, codec.encode([at], [value], "number")),
            )
        connection.execute(
            "INSERT INTO rollups VALUES (1, %s, 0, %s, 1.0)", (ms(2026, 9, 2), HOUR_MS)
        )
    archive = ArchiveStore(Database(url))
    db = archive.db
    with db.connect() as connection:
        kinds = connection.execute(
            "SELECT relname, relkind FROM pg_class WHERE oid IN"
            " (to_regclass('chunks'), to_regclass('rollups'))"
        ).fetchall()
    assert {str(row[0]): str(row[1]) for row in kinds} == {"chunks": "p", "rollups": "p"}
    assert tables(db, "chunks_y") == ["chunks_y1969m12", "chunks_y2026m08", "chunks_y2026m09"]
    assert tables(db, "chunks_unpartitioned") == []
    assert archive.read(1, ms(2026, 8, 1), ms(2026, 10, 1))[1].tolist() == [1.0, 2.0]
    assert archive.read(2, ms(1969, 1, 1), ms(1970, 1, 1))[1].tolist() == [3.0]
    assert archive.rollups(1, False, 0, ms(2027, 1)) == {
        ms(2026, 9, 2): (float(HOUR_MS), 1.0, None, None, None)
    }
    # A second start (another process, a restart) finds it done.
    assert partitions.prepare(db, {}) == {}
    ArchiveStore(Database(url)).append({1: ("number", [(ms(2026, 9, 3), 4.0)])})
    assert archive.point_stats()[1]["chunks"] == 3


@pytest.mark.skipif(bool(TEST_DATABASE_URL), reason="SQLite files only")
def test_sqlite_archives_are_not_partitioned(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    assert archive.partitions is None
    archive.append({1: ("number", [(ms(2026, 9, 2), 1.0), (ms(2026, 10, 2), 2.0)])})
    assert archive.prune({1: ms(2026, 10, 1)}) == 0  # one chunk, ending after the cutoff


@postgres_only
def test_a_closed_month_is_rewritten_once_with_the_same_values(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    for minute in range(120):  # small chunks, merged by compaction: dead space left behind
        at = ms(2026, 9, 10) + minute * 60_000
        archive.append({1: ("number", [(at, float(minute)), (at + 30_000, minute + 0.5)])})
    archive.append({1: ("number", [(ms(2026, 10, 5), 7.0)])})
    archive.compact(ms(2026, 9, 11))
    hours = [(ms(2026, 9, 10, h), float(HOUR_MS), 1.0 * h, 0.0, 1.0, 60) for h in range(3)]
    archive.put_rollups(1, False, hours)
    before = archive.read(1, ms(2026, 9, 1), ms(2026, 10, 31))
    # Not before the month has been closed for a day; the current month never.
    assert archive.rewrite_closed(ms(2026, 10, 1, 12)) is None
    assert archive.rewrite_closed(ms(2026, 10, 2, 1)) == "chunks_y2026m09"
    # Then its rollups, in point order: a year's trend reads them a few pages a month.
    assert archive.rewrite_closed(ms(2026, 10, 2, 2)) == "rollups_y2026m09"
    assert archive.rewrite_closed(ms(2026, 10, 2, 3)) is None  # once
    after = archive.read(1, ms(2026, 9, 1), ms(2026, 10, 31))
    assert after[0].tolist() == before[0].tolist() and after[1].tolist() == before[1].tolist()
    assert sorted(archive.rollups(1, False, ms(2026, 9), ms(2026, 10))) == [h[0] for h in hours]
    assert tables(archive.db, "chunks_y2026m09") == ["chunks_y2026m09"]
    # Still a partition taking writes (a backfill), with its key.
    archive.replace(1, "number", [(ms(2026, 9, 20), 9.0)])
    assert 9.0 in archive.read(1, ms(2026, 9, 19), ms(2026, 9, 21))[1].tolist()
    with archive.db.connect() as connection:
        index = connection.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'chunks_y2026m09'"
            " AND schemaname = current_schema()"
        ).fetchall()
    assert [row[0] for row in index] == ["chunks_y2026m09_pkey"]


@postgres_only
def test_a_busy_month_is_left_for_the_next_housekeeping(tmp_path, monkeypatch):
    archive = ArchiveStore(database(tmp_path))
    archive.append({1: ("number", [(ms(2026, 9, 10), 1.0)])})
    monkeypatch.setattr(partitions, "SWAP_LOCK_TIMEOUT", "100ms")
    holder = psycopg.connect(postgres_url(tmp_path))
    holder.execute("LOCK TABLE chunks_y2026m09 IN ROW EXCLUSIVE MODE")  # a write under way
    try:
        assert archive.rewrite_closed(ms(2026, 10, 3)) is None
    finally:
        holder.rollback()
        holder.close()
    assert archive.rewrite_closed(ms(2026, 10, 3)) == "chunks_y2026m09"
