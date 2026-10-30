"""PlantCraft's connections are kept per thread and used again (plantcraft/db.py)."""

from __future__ import annotations

import sqlite3
import threading

from plantcraft.db import Database


def test_a_connection_whose_block_ended_serves_the_next_block(tmp_path):
    db = Database(tmp_path / "pc.sqlite3")
    with db.connect() as first:
        first.execute("CREATE TABLE t (x INTEGER)")
    with db.connect() as second:
        assert second is first
        assert second.row_factory is sqlite3.Row
        assert second.isolation_level == "IMMEDIATE"


def test_a_block_inside_another_gets_its_own_connection(tmp_path):
    db = Database(tmp_path / "pc.sqlite3")
    with db.connect() as outer, db.connect() as inner:
        assert inner is not outer


def test_a_transaction_left_open_is_rolled_back_when_given_back(tmp_path):
    db = Database(tmp_path / "pc.sqlite3")
    with db.connect() as connection:
        connection.execute("CREATE TABLE t (x INTEGER)")
    connection = db.write()
    connection.execute("INSERT INTO t VALUES (1)")
    connection.close()  # no commit: the insert is dropped, the connection kept
    with db.connect() as again:
        assert again is connection
        assert not again.in_transaction
        assert again.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
        again.row_factory = None  # a block may change it: the next one starts as usual
    with db.connect() as after:
        assert after.row_factory is sqlite3.Row


def test_each_thread_has_its_own_connections(tmp_path):
    db = Database(tmp_path / "pc.sqlite3")
    with db.connect() as mine:
        pass
    seen = []

    def other() -> None:
        with db.connect() as theirs:
            seen.append(theirs)
            theirs.execute("SELECT 1").fetchone()

    worker = threading.Thread(target=other)
    worker.start()
    worker.join()
    assert seen and seen[0] is not mine
