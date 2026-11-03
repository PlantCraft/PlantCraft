"""``linkcraft compact`` gives back the pages the history thinning freed, and only then."""

from __future__ import annotations

import sqlite3

from linkcraft.compact import compact, create_incremental, incremental, release_free


def _file(path, rows: int) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (v TEXT)")
    connection.executemany("INSERT INTO t VALUES (?)", [("x" * 500,)] * rows)
    connection.commit()
    connection.close()


def test_a_thinned_file_shrinks_and_a_full_one_is_left_alone(tmp_path):
    path = tmp_path / "linkcraft.sqlite3"
    _file(path, 4000)
    assert compact(path)["status"] == "skipped"  # nothing was deleted
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM t WHERE rowid % 4 != 0")
    connection.commit()
    connection.close()
    assert compact(path, dry_run=True)["status"] == "would_compact"
    found = compact(path)
    assert found["status"] == "ok" and found["free_share"] > 0.5
    assert found["size_after_bytes"] < found["size_bytes"] / 2
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1000
    # The rewrite turns on INCREMENTAL: from now on the hourly upkeep gives pages back itself.
    assert incremental(path)


def _delete(path, where: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(f"DELETE FROM t WHERE {where}")
    connection.commit()
    connection.close()


def test_a_new_file_gives_its_free_pages_back_a_step_at_a_time(tmp_path):
    path = tmp_path / "linkcraft.sqlite3"
    assert create_incremental(path) and not create_incremental(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.close()
    _file(path, 4000)
    assert incremental(path) and release_free(path, pause=0) == 0  # nothing free yet
    _delete(path, "rowid % 4 != 0")
    before = path.stat().st_size
    # At most max_bytes a call, in steps of step_pages.
    first = release_free(path, max_bytes=64 * 4096, step_pages=16, pause=0)
    assert first == 64 * 4096
    assert release_free(path, pause=0) > 0
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert connection.execute("PRAGMA freelist_count").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1000
    connection.close()
    assert path.stat().st_size < before / 2


def test_an_old_file_is_left_to_linkcraft_compact(tmp_path):
    path = tmp_path / "linkcraft.sqlite3"
    _file(path, 2000)
    _delete(path, "rowid % 2 = 0")
    assert not incremental(path) and release_free(path, pause=0) == 0


def test_the_compact_hour_and_the_room_the_disk_needs(monkeypatch):
    from linkcraft.compact import DISK_MARGIN_BYTES, compact_hour, room_needed

    monkeypatch.delenv("LINKCRAFT_COMPACT_HOUR", raising=False)
    assert compact_hour() == 3
    for value, hour in (("off", None), ("0", 0), ("23", 23), ("24", 3), ("x", 3)):
        monkeypatch.setenv("LINKCRAFT_COMPACT_HOUR", value)
        assert compact_hour() == hour
    # The live pages twice (the temporary copy and the write-ahead log), and a margin.
    assert room_needed(10, 4) == 12 + DISK_MARGIN_BYTES


def _old_file_with_free_pages(path) -> None:
    _file(path, 4000)
    _delete(path, "rowid % 4 != 0")


class _Jobs:
    def __init__(self, running: int):
        self.running = running

    def running_count(self) -> int:
        return self.running


def _runtime(path, running: int = 0):
    from types import SimpleNamespace

    from linkcraft.api.runtime import Runtime

    runtime = SimpleNamespace(
        db=SimpleNamespace(path=str(path)), jobs=_Jobs(running), _compact_named=False
    )
    runtime.compact_due = lambda now=None: Runtime.compact_due(runtime, now)
    runtime.compact_once = lambda found: Runtime.compact_once(runtime, found)
    return runtime, Runtime


def test_the_upkeep_compacts_an_old_file_once_in_the_quiet_hour(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setenv("LINKCRAFT_COMPACT_HOUR", "3")
    monkeypatch.setattr("linkcraft.api.runtime.zone_of", lambda _name: UTC)
    path = tmp_path / "linkcraft.sqlite3"
    _old_file_with_free_pages(path)
    before = path.stat().st_size
    runtime, Runtime = _runtime(path)
    # Another hour: the file keeps its size, and the log names the quiet hour once.
    assert Runtime.release_disk(runtime, datetime(2026, 11, 3, 14, tzinfo=UTC)) == 0
    assert path.stat().st_size == before and not incremental(path)
    assert runtime._compact_named
    # The quiet hour with an execution running: it waits for another day.
    runtime.jobs.running = 1
    Runtime.release_disk(runtime, datetime(2026, 11, 4, 3, 20, tzinfo=UTC))
    assert path.stat().st_size == before and not incremental(path)
    # The quiet hour with nothing running: compacted, and from then on INCREMENTAL.
    runtime.jobs.running = 0
    Runtime.release_disk(runtime, datetime(2026, 11, 5, 3, 20, tzinfo=UTC))
    assert path.stat().st_size < before / 2 and incremental(path)


def test_the_quiet_hour_off_leaves_the_compact_to_a_person(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.setenv("LINKCRAFT_COMPACT_HOUR", "off")
    monkeypatch.setattr("linkcraft.api.runtime.zone_of", lambda _name: UTC)
    path = tmp_path / "linkcraft.sqlite3"
    _old_file_with_free_pages(path)
    runtime, Runtime = _runtime(path)
    Runtime.release_disk(runtime, datetime(2026, 11, 5, 3, 20, tzinfo=UTC))
    assert not incremental(path)


def test_compact_skips_when_the_disk_cannot_hold_both_copies(tmp_path, monkeypatch):
    path = tmp_path / "linkcraft.sqlite3"
    _old_file_with_free_pages(path)
    live = path.stat().st_size // 4
    usage = shutil_usage(free=live + 1)
    monkeypatch.setattr("linkcraft.compact.shutil.disk_usage", lambda _p: usage)
    found = compact(path)
    assert found["status"] == "skipped" and "disk" in found["reason"]


def shutil_usage(free: int):
    from collections import namedtuple

    return namedtuple("usage", "total used free")(free * 10, free * 9, free)
