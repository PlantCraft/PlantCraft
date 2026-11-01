"""An app's own SQLite database and the base class for module stores.

Every module of an app owns its tables and declares them in a ``SCHEMA`` string. The
``Database`` applies each module schema once, in dependency order, so a fresh
file and an existing installation converge on the same structure. ``recorded_at`` stamps the
rows written in a block with a past moment (a demo's story).

**Migrations** (scale review E10, 2026-10-25): a change to a table a release already shipped is
a ``Migration`` in the store's ``MIGRATIONS``, never code that inspects the file at start. Each
runs once per database, in the order listed, in its own transaction, and is recorded in
``sdk_migrations`` as ``<store>:<name>``, so an installation that skipped versions (0.3 to 0.9)
runs every step it missed, in order. Names never change and steps are never removed; a step
that adds columns uses ``add_columns``, which skips columns already there. The store's class
name keys its steps, so a store keeps its class name.

Migrations only go forward, so a database written by a newer version of the app is never opened
by an older one: given the app's ``version``, ``Database`` stamps the file with it
(``PRAGMA user_version``) and refuses, with ``SchemaTooNew``, a file stamped by a later version.
Going back a version restores the data of its backup instead (``docs/operations.md``).

**Journal** (2026-10-26): WAL, except on a folder SQLite's shared memory is not safe on: a
Docker Desktop bind mount (macOS ``virtiofs``/``fakeowner``, Windows ``9p``/``grpcfuse``), a
network share or a FUSE file system, where several processes mapping the ``-shm`` file of one
database end in a bus error (SIGBUS, seen on the Mac mini). There the rollback journal
(``TRUNCATE``) is used; ``PLANTCRAFT_SQLITE_JOURNAL`` (``wal``, ``truncate``, ``delete``)
overrides the choice.
"""

from __future__ import annotations

import functools
import json
import os
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from plantcraft_sdk.server import demo_slots
from plantcraft_sdk.utc import normalize_times, utc_iso

# File systems where SQLite's WAL shared memory (an mmapped -shm file) is not safe.
NO_WAL_FILESYSTEMS = frozenset(
    {"virtiofs", "fakeowner", "9p", "grpcfuse", "osxfs", "nfs", "nfs4", "cifs", "smb3", "smbfs",
     "vboxsf", "prl_fs", "drvfs"}
)  # fmt: skip
JOURNAL_MODES = ("WAL", "TRUNCATE", "DELETE")


def _unescape(field: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), field)


def filesystem_of(path: Path, mountinfo: str | None = None) -> str:
    """The type of the file system ``path`` is on (Linux ``/proc/self/mountinfo``); "" when
    it cannot be told."""

    if mountinfo is None:
        try:
            mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        except OSError:
            return ""
    target = str(path)
    best, found = -1, ""
    for line in mountinfo.splitlines():
        fields = line.split()
        if " - " not in line or len(fields) < 5:
            continue
        point = _unescape(fields[4]).rstrip("/") or "/"
        inside = target == point or target.startswith(point if point == "/" else point + "/")
        if inside and len(point) > best:
            best, found = len(point), line.split(" - ", 1)[1].split()[0]
    return found


@functools.lru_cache(maxsize=64)
def journal_mode(folder: Path) -> str:
    """WAL where it is safe, TRUNCATE on a Docker Desktop bind mount, a share or FUSE."""

    chosen = os.environ.get("PLANTCRAFT_SQLITE_JOURNAL", "").strip().upper()
    if chosen in JOURNAL_MODES:
        return chosen
    kind = filesystem_of(folder.resolve())
    return "TRUNCATE" if kind in NO_WAL_FILESYSTEMS or kind.startswith("fuse") else "WAL"


_CLOCK: ContextVar[datetime | None] = ContextVar("plantcraft_sdk_store_clock", default=None)


@contextmanager
def recorded_at(moment: datetime) -> Iterator[None]:
    """Stamp every row written in this block with ``moment`` (a demo's story only)."""

    token = _CLOCK.set(moment)
    try:
        yield
    finally:
        _CLOCK.reset(token)


_SEMVER = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:[-+].*)?$")


def schema_stamp(version: str) -> int:
    """The ``user_version`` stamp of an app version: ``0.10.3`` -> ``10003``, ``1.2.0`` ->
    ``1002000`` (major, minor and patch up to 999 each)."""

    match = _SEMVER.match(version.strip())
    if not match:
        raise ValueError(f"not a version like 1.2.3: {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return major * 1_000_000 + minor * 1_000 + patch


def stamp_version(stamp: int) -> str:
    """The version a ``user_version`` stamp stands for (``schema_stamp`` reversed)."""

    return f"{stamp // 1_000_000}.{stamp // 1_000 % 1_000}.{stamp % 1_000}"


UTC_TIMES = "utc-times-2026-10-23"
MIGRATIONS_TABLE = (
    "CREATE TABLE IF NOT EXISTS sdk_migrations (name TEXT PRIMARY KEY, applied_at TEXT)"
)


@dataclass(frozen=True)
class Migration:
    """One step of a store's tables: SQL statements (``;``-separated) or a function of the
    connection, run once inside a transaction."""

    name: str
    run: str | Callable[[sqlite3.Connection], None]


def add_columns(table: str, columns: dict[str, str]) -> Callable[[sqlite3.Connection], None]:
    """A step that adds each missing column (``{"place": "TEXT NOT NULL DEFAULT ''"}``)."""

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
        raise ValueError(f"not a table name: {table!r}")

    def run(connection: sqlite3.Connection) -> None:
        have = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
                raise ValueError(f"not a column name: {column!r}")
            if column not in have:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # What the step adds, for the upgrade test (plantcraft_sdk.apptest.upgrade_problems).
    run.table = table  # type: ignore[attr-defined]
    run.columns = dict(columns)  # type: ignore[attr-defined]
    return run


class SchemaTooNew(RuntimeError):
    """The database was written by a later version of the app: this one must not open it."""

    def __init__(self, path: Path, found: int, mine: int):
        super().__init__(
            f"{path.name} was written by version {stamp_version(found)} of this app and this is "
            f"version {stamp_version(mine)}: an older version never opens a newer database. "
            "Go back with the backup taken before the update (install.sh --rollback), "
            "or install the newer version again."
        )
        self.found = found
        self.mine = mine


class Database:
    """One SQLite file shared by all module stores of an app's installation.

    ``version`` (the app's version) turns on the schema stamp: the file is stamped with it and a
    file stamped by a later version raises ``SchemaTooNew``.
    """

    def __init__(self, path: str | Path, *, version: str | None = None):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._applied: set[str] = set()
        if version is not None:
            self._check_stamp(schema_stamp(version))
        self._utc_once()

    def _utc_once(self) -> None:
        """Every stored time in UTC (2026-10-23): rows written before are rewritten once."""

        with self.lock, self.connect() as connection:
            connection.execute(MIGRATIONS_TABLE)
            done = connection.execute(
                "SELECT 1 FROM sdk_migrations WHERE name = ?", (UTC_TIMES,)
            ).fetchone()
            if done is None:
                normalize_times(connection)
                connection.execute(
                    "INSERT OR IGNORE INTO sdk_migrations (name, applied_at) VALUES (?, ?)",
                    (UTC_TIMES, utc_iso()),
                )

    def _check_stamp(self, mine: int) -> None:
        with self.lock, self.connect() as connection:
            found = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if found > mine:
                raise SchemaTooNew(self.path, found, mine)
            if found < mine:
                connection.execute(f"PRAGMA user_version = {int(mine)}")

    def connect(self, *, shared: bool = False) -> sqlite3.Connection:
        """A connection to the app's file, or to the current demo visit's copy of it
        (``plantcraft_sdk.server.demo_slots``) unless ``shared``."""

        path = self.path
        key = None if shared else demo_slots.visit_key()
        if key is not None and demo_slots.copyable(self.path):
            path = demo_slots.prepare(self.path, key)
        connection = sqlite3.connect(path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        if path == self.path:
            connection.execute(f"PRAGMA journal_mode = {journal_mode(self.path.parent)}")
        return connection

    def apply_schema(self, owner: str, schema: str) -> None:
        """Create the tables declared by one module, idempotently."""

        if owner in self._applied:
            return
        with self.lock, self.connect() as connection:
            connection.executescript(schema)
        self._applied.add(owner)

    def migrate(self, owner: str, steps: tuple[Migration, ...] | list[Migration]) -> list[str]:
        """Run the steps of ``owner`` this database has not run yet, in order; their names."""

        if not steps:
            return []
        names = [step.name for step in steps]
        if len(set(names)) != len(names):
            raise ValueError(f"{owner}: a migration name is listed twice")
        ran: list[str] = []
        with self.lock:
            connection = self.connect()
            try:
                connection.execute(MIGRATIONS_TABLE)
                connection.commit()
                for step in steps:
                    key = f"{owner}:{step.name}"
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        found = connection.execute(
                            "SELECT 1 FROM sdk_migrations WHERE name = ?", (key,)
                        ).fetchone()
                        if found is None:
                            if callable(step.run):
                                step.run(connection)
                            else:
                                for statement in step.run.split(";"):
                                    if statement.strip():
                                        connection.execute(statement)
                            connection.execute(
                                "INSERT INTO sdk_migrations (name, applied_at) VALUES (?, ?)",
                                (key, utc_iso()),
                            )
                            ran.append(step.name)
                        connection.commit()
                    except BaseException:
                        connection.rollback()
                        raise
            finally:
                connection.close()
        return ran


class Store:
    """Base class giving module stores the shared connection helpers."""

    SCHEMA = ""
    # True: a demo visit's requests still use the app's own file (counters a visit's copy must
    # not reset; plantcraft_sdk.server.demo_slots).
    DEMO_SHARED = False
    # Changes to tables already shipped, in order (``Migration``; never renamed, never removed).
    MIGRATIONS: tuple[Migration, ...] = ()
    # Kept for apps that still name it: every time ``_now`` writes has milliseconds (utc_iso).
    TIMESPEC = "milliseconds"

    def __init__(self, db: Database):
        self.db = db
        if self.SCHEMA:
            db.apply_schema(type(self).__qualname__, self.SCHEMA)
        if self.MIGRATIONS:
            db.migrate(type(self).__qualname__, self.MIGRATIONS)

    @property
    def path(self) -> Path:
        return self.db.path

    @property
    def _lock(self) -> threading.RLock:
        return self.db.lock

    def _connect(self) -> sqlite3.Connection:
        if self.DEMO_SHARED:
            return self.db.connect(shared=True)
        return self.db.connect()

    @classmethod
    def _now(cls) -> str:
        """Now (or the demo's clock) as ``2026-10-23T14:05:09.123Z`` (``plantcraft_sdk.utc``)."""

        return utc_iso(_CLOCK.get())

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _loads(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _row_with_json(
        row: sqlite3.Row,
        fields: dict[str, tuple[str, Any]],
    ) -> dict[str, Any]:
        item = dict(row)
        for output_name, (column_name, default) in fields.items():
            raw = item.pop(column_name, None)
            try:
                item[output_name] = json.loads(raw) if raw else default
            except json.JSONDecodeError:
                item[output_name] = default
        return item
