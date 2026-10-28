"""Numbered migrations (scale review E10): each step once per database, in order, recorded."""

import sqlite3
from pathlib import Path

import pytest

from plantcraft_sdk.server.store import Database, Migration, Store, add_columns


class Notes(Store):
    SCHEMA = "CREATE TABLE IF NOT EXISTS notes (note_id INTEGER PRIMARY KEY, text TEXT NOT NULL);"


def columns(db: Database, table: str) -> list[str]:
    with db.connect() as connection:
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]


def recorded(db: Database) -> list[str]:
    with db.connect() as connection:
        rows = connection.execute("SELECT name FROM sdk_migrations ORDER BY name").fetchall()
    return [row[0] for row in rows if ":" in row[0]]


def test_each_step_runs_once_in_order_and_is_recorded(tmp_path):
    db = Database(tmp_path / "app.db")
    Notes(db)
    calls: list[str] = []
    steps = (
        Migration("add-author", add_columns("notes", {"author": "TEXT NOT NULL DEFAULT ''"})),
        Migration("fill-author", "UPDATE notes SET author = 'someone' WHERE author = ''"),
        Migration("count", lambda connection: calls.append("count")),
    )
    assert db.migrate("Notes", steps) == ["add-author", "fill-author", "count"]
    assert db.migrate("Notes", steps) == []
    assert calls == ["count"]
    assert "author" in columns(db, "notes")
    assert recorded(db) == ["Notes:add-author", "Notes:count", "Notes:fill-author"]


def test_an_installation_that_skipped_versions_runs_every_step_it_missed(tmp_path):
    db = Database(tmp_path / "app.db")
    Notes(db)
    first = (Migration("a", add_columns("notes", {"a": "TEXT"})),)
    db.migrate("Notes", first)
    later = (
        *first,
        Migration("b", add_columns("notes", {"b": "TEXT"})),
        Migration("c", add_columns("notes", {"c": "INTEGER"})),
    )
    assert db.migrate("Notes", later) == ["b", "c"]
    assert columns(db, "notes")[-3:] == ["a", "b", "c"]


def test_add_columns_skips_a_column_the_schema_already_has(tmp_path):
    db = Database(tmp_path / "app.db")
    Notes(db)
    assert db.migrate("Notes", (Migration("text", add_columns("notes", {"text": "TEXT"})),)) == [
        "text"
    ]
    assert columns(db, "notes") == ["note_id", "text"]


def test_a_failed_step_is_rolled_back_and_runs_again_next_start(tmp_path):
    db = Database(tmp_path / "app.db")
    Notes(db)
    broken = (Migration("x", "ALTER TABLE notes ADD COLUMN x TEXT; SELECT * FROM missing"),)
    with pytest.raises(sqlite3.OperationalError):
        db.migrate("Notes", broken)
    assert "x" not in columns(db, "notes")
    assert recorded(db) == []
    fixed = (Migration("x", "ALTER TABLE notes ADD COLUMN x TEXT"),)
    assert db.migrate("Notes", fixed) == ["x"]


def test_a_store_runs_its_migrations_when_it_opens(tmp_path):
    class Tagged(Notes):
        MIGRATIONS = (Migration("tag", add_columns("notes", {"tag": "TEXT"})),)

    db = Database(tmp_path / "app.db")
    Tagged(db)
    Tagged(db)
    assert "tag" in columns(db, "notes")
    assert [name.rsplit(".", 1)[-1] for name in recorded(db)] == ["Tagged:tag"]


def test_names_must_be_unique_and_safe(tmp_path):
    with pytest.raises(ValueError):
        add_columns("notes; DROP TABLE notes", {"a": "TEXT"})
    db = Database(tmp_path / "app.db")
    with pytest.raises(ValueError):
        db.migrate("Notes", (Migration("a", "SELECT 1"), Migration("a", "SELECT 2")))


def test_upgrade_problems_opens_a_store_on_its_older_tables(tmp_path):
    from plantcraft_sdk import apptest
    from plantcraft_sdk.server.store import Migration, Store, add_columns

    class Things(Store):
        SCHEMA = """
        -- the app's things
        CREATE TABLE IF NOT EXISTS things (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL, -- shown
            place TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS things_name ON things (name);
        """
        MIGRATIONS = (
            Migration(
                "columns-before-0.5", add_columns("things", {"place": "TEXT NOT NULL DEFAULT ''"})
            ),
        )

    assert apptest.upgrade_problems(Things, Things, tmp_path / "a") == []

    class Broken(Things):
        # An index on a column a step adds fails on a real upgrade: SCHEMA runs first.
        SCHEMA = Things.SCHEMA + "CREATE INDEX IF NOT EXISTS things_place ON things (place);"

    problems = apptest.upgrade_problems(Broken, Broken, tmp_path / "b")
    assert problems and "opening an older database failed" in problems[0]

    class Plain(Store):
        SCHEMA = "CREATE TABLE IF NOT EXISTS plain (id TEXT);"

    (problem,) = apptest.upgrade_problems(Plain, Plain, tmp_path / "c")
    assert problem.endswith("Plain has no add_columns step to try")


MOUNTINFO = (
    "22 1 0:21 / / rw,relatime - overlay overlay rw\n"
    "40 22 0:52 /Users/me/PlantCraft/data/linkcraft /data rw,relatime - fakeowner"
    " fakeowner rw\n"
    "41 22 0:53 / /srv/my\\040data rw - ext4 /dev/sda1 rw\n"
    "42 22 0:54 / /mnt/share rw - fuse.sshfs host:/x rw\n"
)


def test_the_file_system_of_a_folder_is_read_from_mountinfo():
    from plantcraft_sdk.server.store import filesystem_of

    assert filesystem_of(Path("/data/linkcraft.sqlite3"), MOUNTINFO) == "fakeowner"
    assert filesystem_of(Path("/data"), MOUNTINFO) == "fakeowner"
    assert filesystem_of(Path("/database"), MOUNTINFO) == "overlay"
    assert filesystem_of(Path("/srv/my data/x"), MOUNTINFO) == "ext4"
    assert filesystem_of(Path("/mnt/share/a"), MOUNTINFO) == "fuse.sshfs"


def test_wal_only_where_its_shared_memory_is_safe(tmp_path, monkeypatch):
    """A Docker Desktop bind mount (macOS fakeowner/virtiofs) ends WAL in a bus error when
    several processes map one database's -shm (the Mac mini, 2026-10-26): TRUNCATE there."""

    from plantcraft_sdk.server import store

    kinds = {"desktop": "fakeowner", "linux": "ext4", "share": "fuse.sshfs"}
    monkeypatch.setattr(store, "filesystem_of", lambda path: kinds[path.name])
    store.journal_mode.cache_clear()
    try:
        assert store.journal_mode(tmp_path / "desktop") == "TRUNCATE"
        assert store.journal_mode(tmp_path / "linux") == "WAL"
        assert store.journal_mode(tmp_path / "share") == "TRUNCATE"
        store.journal_mode.cache_clear()
        monkeypatch.setenv("PLANTCRAFT_SQLITE_JOURNAL", "wal")
        assert store.journal_mode(tmp_path / "desktop") == "WAL"
        store.journal_mode.cache_clear()
        monkeypatch.setenv("PLANTCRAFT_SQLITE_JOURNAL", "delete")
        (tmp_path / "linux").mkdir()
        database = store.Database(tmp_path / "linux" / "app.sqlite3")
        with database.connect() as connection:
            assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        store.journal_mode.cache_clear()
