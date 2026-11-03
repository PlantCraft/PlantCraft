"""Historian's own database and the base class for module stores.

Every module owns its tables and declares them in a ``SCHEMA`` string. The
``Database`` applies each module schema once, in dependency order, so a fresh
database and an existing installation converge on the same structure.

Two engines, one SQL: **PostgreSQL** for plants (``HISTCRAFT_DATABASE_URL``,
decided 2026-10-19: many writers, backups and replication client IT knows) and
**SQLite** files for tests, demos and one-laptop installs. Stores write SQLite
SQL that PostgreSQL also accepts (``ON CONFLICT``, ``RETURNING``, ``?`` and
``:name`` parameters); ``_postgres_sql`` and ``_postgres_schema`` translate the
few differences, and ``{ANY}`` in a schema marks a column holding a number or a
text (untyped in SQLite, ``JSONB`` in PostgreSQL, written through ``Database.any``).
"""

from __future__ import annotations

import atexit
import json
import math
import os
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from plantcraft_sdk.utc import is_instant, utc_iso

from histcraft.i18n import t

_CLOCK: ContextVar[datetime | None] = ContextVar("histcraft_clock", default=None)
# Seconds a PostgreSQL statement may run in this context (``read_timeout``); None: no limit.
_READ_TIMEOUT: ContextVar[float | None] = ContextVar("histcraft_read_timeout", default=None)


class ReadTimeout(RuntimeError):
    """A read past ``HISTCRAFT_QUERY_TIMEOUT`` (the API answers 504); says what to ask instead."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(
            t(
                "This read took longer than {seconds} s: ask for a shorter period or a larger step.",
                seconds=f"{seconds:g}",
            )
        )


@contextmanager
def read_timeout(seconds: float) -> Iterator[None]:
    """Limit each PostgreSQL statement in this block to ``seconds`` (``statement_timeout``,
    for its transaction only), so one huge read cannot hold the database; past it the block
    raises ``ReadTimeout``. Only people's and apps' reads use it: the collector's writes and
    migrations never do. SQLite has no such limit and ignores it."""

    token = _READ_TIMEOUT.set(seconds if seconds > 0 else None)
    try:
        yield
    except Exception as exc:
        if type(exc).__name__ == "QueryCanceled":
            raise ReadTimeout(seconds) from exc
        raise
    finally:
        _READ_TIMEOUT.reset(token)


@contextmanager
def recorded_at(moment: datetime) -> Iterator[None]:
    """Stamp every row written in this block with ``moment`` (demo story only)."""

    token = _CLOCK.set(moment)
    try:
        yield
    finally:
        _CLOCK.reset(token)


def is_url(target: str | Path) -> bool:
    return isinstance(target, str) and target.startswith(("postgresql://", "postgres://"))


def safe_url(url: str) -> str:
    """The URL without its password, for logs and pages."""

    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    user = f"{parts.username}:***@" if parts.username else ""
    return urlunsplit((parts.scheme, user + host, parts.path, parts.query, parts.fragment))


class Database:
    """One database shared by the module stores of an installation: a SQLite file or PostgreSQL.

    ``target`` is a file path (SQLite) or a ``postgresql://`` URL. The password of a URL comes
    best from ``password`` (read from a secret file by the caller), never logged.
    """

    def __init__(self, target: str | Path, *, password: str = ""):
        self.lock = threading.RLock()
        self._applied: set[str] = set()
        self._shared = False
        if is_url(target):
            self.dialect = "postgresql"
            self.url = str(target)
            self.path: Path | None = None
            self._password = password
            self.IntegrityError: type[Exception] = _postgres().IntegrityError
        else:
            self.dialect = "sqlite"
            self.url = ""
            self.path = Path(target).expanduser().resolve()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.IntegrityError = sqlite3.IntegrityError

    @property
    def postgres(self) -> bool:
        return self.dialect == "postgresql"

    def describe(self) -> str:
        return safe_url(self.url) if self.postgres else str(self.path)

    def connect(self) -> Any:
        """A connection used as a context manager: commits on success, rolls back on error."""

        if self.postgres:
            return _PostgresConnection(_pool(self.url, self._password))
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        if not self._shared:
            self._share()
        return connection

    def own_connection(self) -> Any:
        """A PostgreSQL connection outside the pool, in autocommit (a session lock's holder).

        The caller closes it; closing ends the session and every advisory lock it holds."""

        assert self.postgres
        kwargs: dict[str, Any] = {"autocommit": True, "connect_timeout": 10}
        if self._password:
            kwargs["password"] = self._password
        return _postgres().connect(self.url, **kwargs)

    def any(self, value: Any) -> Any:
        """A number, text or JSON value (a structured point's) for an ``{ANY}`` column."""

        if isinstance(value, float) and not math.isfinite(value):
            value = None
        if not self.postgres:
            # SQLite keeps a JSON value as its text; reads of a structured point parse it.
            return (
                json.dumps(value, ensure_ascii=False) if isinstance(value, dict | list) else value
            )
        from psycopg.types.json import Jsonb

        return None if value is None else Jsonb(value)

    def _share(self) -> None:
        """Make this process's database files group read-write.

        In the suite the server (uid 10008) and the direct collector (uid 10013, group 10008)
        share the data folder: each reads the other's file, and SQLite readers of a WAL file
        write its ``-shm``. SQLite creates files 0644 whatever the umask, so set 0660 here.
        """

        assert self.path is not None
        for suffix in ("", "-wal", "-shm"):
            path = self.path.with_name(self.path.name + suffix)
            try:
                if path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o777 != 0o660:
                    path.chmod(0o660)
            except OSError:
                continue
        self._shared = True

    def apply_schema(self, owner: str, schema: str) -> None:
        """Create the tables declared by one module, idempotently."""

        if owner in self._applied:
            return
        with self.lock, self.connect() as connection:
            if self.postgres:
                # Server and collector may start together: one creates, the other waits.
                connection.execute("SELECT pg_advisory_xact_lock(4207100810)")
                connection.executescript(_postgres_schema(schema))
            else:
                connection.executescript(schema.replace("{ANY}", ""))
        self._applied.add(owner)

    def once(self, key: str, step: Any) -> None:
        """Run ``step()`` the first time this database is given ``key`` in this process."""

        if key in self._applied:
            return
        step()
        self._applied.add(key)

    def add_columns(self, owner: str, columns: tuple[tuple[str, str, str], ...]) -> None:
        """Add the ``(table, column, definition)`` columns a module added after its first
        release, each only when missing (the guarded ``ALTER TABLE`` of AGENTS.md: schema
        changes are additive, existing rows keep their values and get the column's default)."""

        key = f"{owner}:columns"
        if key in self._applied or not columns:
            return
        if self.postgres:
            # ALTER TABLE takes the table's strongest lock even when the column is already there,
            # so with readers on a busy archive every start of a worker could deadlock them
            # (pc-carga, 3 months at plant scale, 2026-11-01). Only missing columns are altered.
            with self.connect() as connection:
                present = {
                    (row[0], row[1])
                    for row in connection.execute(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema()"
                    )
                }
            columns = tuple(item for item in columns if (item[0], item[1]) not in present)
            if not columns:
                self._applied.add(key)
                return
        with self.lock, self.connect() as connection:
            if self.postgres:
                connection.execute("SELECT pg_advisory_xact_lock(4207100810)")
            for table, column, definition in columns:
                if self.postgres:
                    connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} "
                        f"{_postgres_schema(definition)}"
                    )
                    continue
                present = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                if column not in present:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self._applied.add(key)


# PostgreSQL ------------------------------------------------------------------------------

_POOLS: dict[tuple[str, str], Any] = {}
_POOLS_LOCK = threading.Lock()
# Connections per process: the API's worker threads plus the collector.
POOL_SIZE = 12


def _postgres() -> Any:
    import psycopg

    return psycopg


def _pool(url: str, password: str) -> Any:
    with _POOLS_LOCK:
        pool = _POOLS.get((url, password))
        if pool is None:
            from psycopg_pool import ConnectionPool

            kwargs: dict[str, Any] = {"row_factory": _row_factory, "connect_timeout": 10}
            if password:
                kwargs["password"] = password
            pool = ConnectionPool(
                url, min_size=1, max_size=POOL_SIZE, kwargs=kwargs, open=True, timeout=30
            )
            _POOLS[(url, password)] = pool
        return pool


@contextmanager
def scratch_schema(url: str, password: str = "") -> Iterator[str]:
    """A throwaway schema in a PostgreSQL database (benchmarks): its URL, dropped afterwards."""

    psycopg = _postgres()
    schema = f"histcraft_scratch_{os.getpid()}_{threading.get_ident() % 100000}"
    kwargs = {"password": password} if password else {}
    with psycopg.connect(url, autocommit=True, **kwargs) as connection:
        connection.execute(f"CREATE SCHEMA {schema}")
    try:
        join = "&" if "?" in url else "?"
        yield f"{url}{join}options=-csearch_path%3D{schema}"
    finally:
        close_pools()
        with psycopg.connect(url, autocommit=True, **kwargs) as connection:
            connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@atexit.register
def close_pools() -> None:
    with _POOLS_LOCK:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close()


class Row(dict):
    """A row read by name (``row["tag"]``) or position (``row[0]``), like ``sqlite3.Row``."""

    __slots__ = ("_values",)

    def __init__(self, names: list[str], values: tuple[Any, ...]):
        super().__init__(zip(names, values, strict=True))
        self._values = values

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _row_factory(cursor: Any) -> Any:
    names = [column.name for column in cursor.description or []]

    def make(values: tuple[Any, ...]) -> Row:
        return Row(names, values)

    return make


class _PostgresConnection:
    """The few ``sqlite3.Connection`` methods the stores use, on a pooled psycopg connection."""

    def __init__(self, pool: Any):
        self._pool = pool
        self._context: Any = None
        self._connection: Any = None

    def __enter__(self) -> _PostgresConnection:
        self._context = self._pool.connection()
        self._connection = self._context.__enter__()
        limit = _READ_TIMEOUT.get()
        if limit is not None:
            # SET LOCAL ends with the transaction: the pooled connection comes back unlimited.
            self._connection.execute(f"SET LOCAL statement_timeout = {int(limit * 1000)}")
        return self

    def __exit__(self, *exc: Any) -> Any:
        context, self._context, self._connection = self._context, None, None
        return context.__exit__(*exc)  # commits, or rolls back on error; returns it to the pool

    def execute(self, sql: str, params: Any = None) -> Any:
        return self._connection.execute(_postgres_sql(sql), _params(params))

    def executemany(self, sql: str, rows: Any) -> Any:
        cursor = self._connection.cursor()
        cursor.executemany(_postgres_sql(sql), [_params(row) for row in rows])
        return cursor

    def executescript(self, script: str) -> None:
        self._connection.execute(script)


def _params(params: Any) -> Any:
    """Parameters as psycopg takes them. PostgreSQL text cannot hold NUL, which SQLite stores:
    it becomes U+FFFD (no tag or address has one, so a lookup with NUL still finds nothing)."""

    if params is None:
        return None
    if isinstance(params, dict):
        return {key: _text(value) for key, value in params.items()}
    return tuple(_text(value) for value in params)


def _text(value: Any) -> Any:
    return value.replace("\x00", "\ufffd") if isinstance(value, str) else value


_NAMED = re.compile(r"(?<![:\w]):([a-z_][a-z0-9_]*)")


@lru_cache(maxsize=512)
def _postgres_sql(sql: str) -> str:
    """SQLite-flavoured SQL as PostgreSQL runs it: parameters and case-blind ``LIKE``."""

    sql = sql.replace("%", "%%").replace("?", "%s")
    sql = _NAMED.sub(r"%(\1)s", sql)
    return re.sub(r"\bLIKE\b", "ILIKE", sql)


@lru_cache(maxsize=64)
def _postgres_schema(schema: str) -> str:
    schema = schema.replace("{ANY}", "JSONB")
    schema = re.sub(
        r"\bINTEGER PRIMARY KEY AUTOINCREMENT\b",
        "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        schema,
    )
    schema = re.sub(r"\)\s*WITHOUT ROWID", ")", schema)
    schema = re.sub(r"\bINTEGER\b", "BIGINT", schema)  # times are milliseconds
    schema = re.sub(r"\bREAL\b", "DOUBLE PRECISION", schema)
    return re.sub(r"\bBLOB\b", "BYTEA", schema)


def utc_times(db: Database, tables: tuple[tuple[str, str, tuple[str, ...]], ...]) -> int:
    """Rewrite the instants of ``tables`` not yet in UTC form; returns how many (0 the next time)."""

    changed = 0
    with db.lock, db.connect() as connection:
        for table, key, columns in tables:
            for column in columns:
                rows = connection.execute(
                    f"SELECT {key}, {column} FROM {table} WHERE {column} NOT LIKE '%Z'"
                ).fetchall()
                for row in rows:
                    value = row[1]
                    if not is_instant(value):
                        continue
                    try:
                        fixed = utc_iso(value)
                    except ValueError:
                        continue
                    connection.execute(
                        f"UPDATE {table} SET {column} = ? WHERE {key} = ?", (fixed, row[0])
                    )
                    changed += 1
    return changed


class Store:
    """Base class giving module stores the shared connection helpers."""

    SCHEMA = ""
    # Columns added after a table's first release: ``(table, column, definition)``, applied
    # with a guarded ``ALTER TABLE`` (``Database.add_columns``). Never edit ``SCHEMA`` for them.
    COLUMNS: tuple[tuple[str, str, str], ...] = ()
    # Text columns holding instants: ``(table, key column, (columns...))``. Rows written before
    # 2026-10-23 carry the server's local offset; ``utc_times`` rewrites them once in ``_now``'s form.
    TIMES: tuple[tuple[str, str, tuple[str, ...]], ...] = ()

    def __init__(self, db: Database):
        self.db = db
        if self.SCHEMA:
            db.apply_schema(type(self).__qualname__, self.SCHEMA)
        if self.COLUMNS:
            db.add_columns(type(self).__qualname__, self.COLUMNS)
        if self.TIMES:
            db.once(f"{type(self).__qualname__}:utc", lambda: utc_times(db, self.TIMES))

    @property
    def path(self) -> Path | None:
        return self.db.path

    @property
    def _lock(self) -> threading.RLock:
        return self.db.lock

    def _connect(self) -> Any:
        return self.db.connect()

    @staticmethod
    def _now() -> str:
        """Now (or the demo's clock) in UTC, ``2026-10-23T14:05:09.123Z`` (``plantcraft_sdk.utc``)."""

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
        row: Any,
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
