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
