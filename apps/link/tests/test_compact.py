"""``linkcraft compact`` gives back the pages the history thinning freed, and only then."""

from __future__ import annotations

import sqlite3

from linkcraft.compact import compact


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
