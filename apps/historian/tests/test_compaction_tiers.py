"""Compaction by tiers of time (hour, day, month) and the archive's lighter writes: each value is
rewritten a few times at most, a full chunk never again, and the frequent rows (snapshots,
counts per hour) cost the database little."""

from datetime import datetime, timezone

from histcraft.archive.store import CHUNK_VALUES, HOUR_MS, ArchiveStore, compaction_start
from tests.conftest import database, postgres_only

MINUTE_MS = 60_000


def ms(year, month, day=1, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def minutes(archive, start, count, point=1, per=2):
    """``count`` minute chunks from ``start``, ``per`` values each (as settles write them)."""

    for minute in range(count):
        at = start + minute * MINUTE_MS
        samples = [(at + i * (MINUTE_MS // per), float(minute + i / per)) for i in range(per)]
        archive.append({point: ("number", samples)})


def tens(archive, start, count, point=1):
    """``count`` chunks of 10 values, one every 10 minutes from ``start``."""

    for index in range(count):
        at = start + index * 10 * MINUTE_MS
        archive.append({point: ("number", [(at + i * MINUTE_MS, float(i)) for i in range(10)])})


def chunks(archive, point=1):
    with archive.db.connect() as connection:
        rows = connection.execute(
            "SELECT t0, t1, n FROM chunks WHERE point = ? ORDER BY t0", (point,)
        ).fetchall()
    return [(int(row["t0"]), int(row["t1"]), int(row["n"])) for row in rows]


def test_closed_hours_merge_by_the_hour_and_the_open_hour_waits(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    day = ms(2026, 9, 10)
    minutes(archive, day, 3 * 60 + 30)  # 03:30 of minute chunks
    before = archive.read(1, day, day + 4 * HOUR_MS)
    archive.compact(day + 3 * HOUR_MS + 20 * MINUTE_MS)  # hours 0-2 closed, 3 open
    stored = chunks(archive)
    assert [t0 for t0, _, _ in stored[:3]] == [day + h * HOUR_MS for h in range(3)]
    assert [n for _, _, n in stored[:3]] == [120, 120, 120]
    assert len(stored) == 3 + 30  # the open hour keeps its minute chunks
    after = archive.read(1, day, day + 4 * HOUR_MS)
    assert after[0].tolist() == before[0].tolist() and after[1].tolist() == before[1].tolist()


def test_a_closed_day_merges_its_hours_and_a_closed_month_its_days(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    first = ms(2026, 9, 20)
    for day in range(3):  # a chunk every 10 minutes, 10 values each: 1,440 a day
        tens(archive, first + day * 24 * HOUR_MS, 144)
    tens(archive, first + 3 * 24 * HOUR_MS, 3)  # the fourth day's first 30 minutes
    archive.compact(first + 3 * 24 * HOUR_MS + 30 * MINUTE_MS)
    stored = chunks(archive)
    # Three closed days: one chunk each; the open hour of the fourth keeps its chunks.
    assert [n for _, _, n in stored] == [1440, 1440, 1440, 10, 10, 10]
    assert stored[1][0] == first + 24 * HOUR_MS
    # Once the month is closed its days merge (CHUNK_VALUES at most).
    assert archive.compact(ms(2026, 10, 1, 2)) > 0
    assert [n for _, _, n in chunks(archive)] == [3 * 1440 + 30]
    assert archive.compact(ms(2026, 10, 1, 3)) == 0  # nothing to do again


def test_full_chunks_are_never_rewritten(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    day = ms(2026, 9, 10)
    # 14,400 values in a day: the closed day gives chunks that cannot merge any more.
    for index in range(144):  # 100 values every 10 minutes
        at = day + index * 10 * MINUTE_MS
        archive.append({1: ("number", [(at + i * 6000, float(i)) for i in range(100)])})
    archive.compact(day + 25 * HOUR_MS)
    sizes = [n for _, _, n in chunks(archive)]
    assert sum(sizes) == 14_400 and max(sizes) <= CHUNK_VALUES and len(sizes) == 2
    assert archive.compact(day + 26 * HOUR_MS) == 0
    assert archive.compact(ms(2026, 11, 2)) == 0  # the month closed: still nothing


def test_the_collector_looks_back_to_the_previous_month_only(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    minutes(archive, ms(2026, 7, 10), 3)  # an old backfill's small chunks: left as written
    minutes(archive, ms(2026, 9, 10), 3)
    older = ms(2026, 10, 5)
    assert compaction_start(older) == ms(2026, 9, 1)
    assert compaction_start(ms(2026, 1, 5)) == ms(2025, 12, 1)
    assert archive.compact(older, since_ms=compaction_start(older)) == 2
    assert len(chunks(archive)) == 3 + 1


def test_counts_per_hour_go_to_the_archive_every_few_minutes(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    now = ms(2026, 9, 10, 5)
    archive.hold({1: ("number", [(now, 1.0), (now + 1000, 2.0)])})
    archive.settle(count_every=600)
    with archive.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM point_hours").fetchone()[0] == 0
    archive.hold({1: ("number", [(now + 2000, 3.0)])})
    archive.settle()  # the last settle (the collector stopping) writes them all
    with archive.db.connect() as connection:
        row = connection.execute("SELECT hour, n FROM point_hours").fetchone()
    assert (int(row["hour"]), int(row["n"])) == (now - now % HOUR_MS, 3)


@postgres_only
def test_snapshots_are_unlogged_and_refilled_from_the_archive(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    with archive.db.connect() as connection:
        row = connection.execute(
            "SELECT relpersistence FROM pg_class WHERE oid = to_regclass('snapshots')"
        ).fetchone()
    assert row[0] == "u"
    archive.append({1: ("number", [(1000, 1.0), (2000, 2.5)])})
    archive.append({2: ("text", [(1500, "AUTO")])})
    archive.put_snapshots([{"point": 2, "ts": 9000, "value": "MAN", "status": "ok"}])
    archive.refresh_totals()
    assert archive.refill_snapshots() == 1  # as after a crash: point 1 had none
    snaps = archive.snapshots()
    assert (snaps[1]["ts"], snaps[1]["value"]) == (2000, 2.5)
    assert snaps[2]["value"] == "MAN"  # a snapshot kept is never replaced
    assert archive.refill_snapshots() == 0
