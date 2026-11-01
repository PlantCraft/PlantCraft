"""Monthly partitions of the archive in PostgreSQL: ``chunks`` by ``t0`` and ``rollups`` by ``hour``.

A plant's archive grows by the month and leaves by the month: retention past a month's end drops
that month's table at once instead of deleting its rows one by one, which leaves no dead rows for
VACUUM and gives the disk back. Each month is ``<table>_yYYYYmMM`` (UTC months, times in ms); two
edge partitions take any time before 1900 or from 2200 on, so a write never lacks a partition.

``prepare`` runs once per process before the tables are used: it creates the partitioned tables,
or turns the plain tables of an archive made by Historian 0.3.0 or earlier into partitioned ones (one transaction:
rename, create, copy, drop; the server and the collector wait on the schema lock meanwhile).
``Partitions.ensure`` creates the months a write needs before it starts. SQLite archives are not
partitioned (one file, retention deletes rows as before).

``ArchiveStore.rewrite_closed`` copies a month that no longer takes the collector's writes into
a fresh table once, in key order (a day after it ends, when compaction is done with it), and
swaps it in: the compaction's rewrites leave dead space in a month (half again its size) that
only a rewrite gives back, a closed month is never written to again by the collector, and in key
order a point's rows of the month sit together (a year's trend reads a few pages per month, not
one per hour). Reads go on during the copy; a write to that month (a backfill, an app's series)
waits for it.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any, TypeVar

from histcraft.db import Database

LOGGER = logging.getLogger(__name__)

# Table -> the column it is partitioned by.
MONTHLY = {"chunks": "t0", "rollups": "hour"}
# The schema lock every process takes before changing tables (``Database.apply_schema``).
SCHEMA_LOCK = 4207100810
FIRST_YEAR, LAST_YEAR = 1900, 2200
_NAME = re.compile(r"_y(\d{4})m(\d{2})$")
T = TypeVar("T")
# A month is rewritten this long after it ends (compaction merges chunks an hour old).
REWRITE_AFTER_MS = 86_400_000
# The comment a rewritten month carries (``COMMENT ON TABLE``): it is never rewritten again.
REWRITTEN = "histcraft:rewritten"
# How long the swap waits for the reads under way (they are short), else it is tried again later.
SWAP_LOCK_TIMEOUT = "5s"


def _ms(year: int, month: int) -> int:
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)


LOW, HIGH = _ms(FIRST_YEAR, 1), _ms(LAST_YEAR, 1)


def month_of(ms: int) -> tuple[int, int] | None:
    """The UTC ``(year, month)`` holding ``ms``, or None when an edge partition holds it."""

    if ms < LOW or ms >= HIGH:
        return None
    moment = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return moment.year, moment.month


def bounds(year: int, month: int) -> tuple[int, int]:
    """The month's first ms and the next month's first ms."""

    following = (year + 1, 1) if month == 12 else (year, month + 1)
    return _ms(year, month), _ms(*following)


def partition_name(table: str, year: int, month: int) -> str:
    return f"{table}_y{year:04d}m{month:02d}"


def _create_month(connection: Any, table: str, year: int, month: int) -> None:
    low, high = bounds(year, month)
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {partition_name(table, year, month)} PARTITION OF {table}"
        f" FOR VALUES FROM ({low}) TO ({high})"
    )


def _create_edges(connection: Any, table: str) -> None:
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {table}_before PARTITION OF {table}"
        f" FOR VALUES FROM (MINVALUE) TO ({LOW})"
    )
    connection.execute(
        f"CREATE TABLE IF NOT EXISTS {table}_after PARTITION OF {table}"
        f" FOR VALUES FROM ({HIGH}) TO (MAXVALUE)"
    )


def _kind(connection: Any, table: str) -> str | None:
    row = connection.execute(
        "SELECT relkind FROM pg_class WHERE oid = to_regclass(?)", (table,)
    ).fetchone()
    return str(row[0]) if row else None


def prepare(db: Database, definitions: dict[str, str]) -> dict[str, int]:
    """Make ``chunks`` and ``rollups`` partitioned tables; rows copied per table migrated.

    ``definitions`` are the tables' ``CREATE TABLE`` statements in PostgreSQL SQL, without
    ``IF NOT EXISTS`` or a ``PARTITION BY`` clause.
    """

    migrated: dict[str, int] = {}
    with db.lock, db.connect() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(?)", (SCHEMA_LOCK,))
        for table, column in MONTHLY.items():
            kind = _kind(connection, table)
            if kind == "p":
                continue
            started = time.monotonic()
            if kind is not None:
                old = f"{table}_unpartitioned"
                connection.execute(f"ALTER TABLE {table} RENAME TO {old}")
                connection.execute(f"ALTER INDEX IF EXISTS {table}_pkey RENAME TO {old}_pkey")
            connection.execute(f"{definitions[table]} PARTITION BY RANGE ({column})")
            _create_edges(connection, table)
            if kind is None:
                continue
            months = connection.execute(
                f"SELECT DISTINCT floor({column} / 86400000.0)::bigint * 86400000 AS day FROM {old}"
                f" WHERE {column} >= ? AND {column} < ?",
                (LOW, HIGH),
            ).fetchall()
            for year, month in sorted({month_of(int(row[0])) for row in months} - {None}):
                _create_month(connection, table, year, month)
            copied = connection.execute(f"INSERT INTO {table} SELECT * FROM {old}").rowcount
            connection.execute(f"DROP TABLE {old}")
            migrated[table] = int(copied)
            LOGGER.info(
                "%s: %d rows moved into monthly partitions in %.1f s",
                table,
                copied,
                time.monotonic() - started,
            )
    return migrated


def missing_partition(exc: BaseException) -> bool:
    """True when a write failed because its month's table went away meanwhile (a drop)."""

    state = getattr(exc, "sqlstate", None)
    return state == "42P01" or (state == "23514" and "no partition" in str(exc))


class Partitions:
    """The months this process knows exist; creates the ones a write needs, and drops the past
    months retention has emptied."""

    def __init__(self, db: Database):
        self.db = db
        self._known: set[tuple[str, int, int]] = set()

    def ensure(self, table: str, times: Iterable[int]) -> None:
        """Create the months of ``table`` that hold ``times`` (ms) and do not exist yet.

        Safe inside an open write on ``table``: a month is made as its own table and attached,
        which takes ``SHARE UPDATE EXCLUSIVE`` on ``table``, a lock writes and reads never wait
        for (``CREATE TABLE ... PARTITION OF`` would wait for them, here for ever).
        """

        needed = {
            (table, *month)
            for month in {month_of(int(at)) for at in times}
            if month is not None and (table, *month) not in self._known
        }
        if not needed:
            return
        with self.db.lock, self.db.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(?)", (SCHEMA_LOCK,))
            for name, year, month in sorted(needed):
                partition = partition_name(name, year, month)
                if connection.execute("SELECT to_regclass(?)", (partition,)).fetchone()[0]:
                    continue
                low, high = bounds(year, month)
                # Lower case: the stores' SQL turns an upper-case LIKE into ILIKE.
                connection.execute(f"CREATE TABLE {partition} (like {name} INCLUDING ALL)")
                connection.execute(
                    f"ALTER TABLE {name} ATTACH PARTITION {partition}"
                    f" FOR VALUES FROM ({low}) TO ({high})"
                )
        self._known |= needed

    def writing(self, write: Callable[[], T]) -> T:
        """Run ``write``; again once if a month it wrote to was dropped meanwhile."""

        try:
            return write()
        except Exception as exc:
            if not missing_partition(exc):
                raise
            self._known.clear()
            return write()

    def months(self, table: str) -> list[tuple[str, int, int]]:
        """``(name, start ms, end ms)`` of each month of ``table``, oldest first."""

        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                " WHERE i.inhparent = to_regclass(?)",
                (table,),
            ).fetchall()
        found = []
        for row in rows:
            match = _NAME.search(str(row[0]))
            if match and str(row[0]) == partition_name(table, int(match[1]), int(match[2])):
                found.append((str(row[0]), *bounds(int(match[1]), int(match[2]))))
        return sorted(found, key=lambda item: item[1])

    def drop_expired(
        self, cutoffs: dict[int, int], now_ms: int, hour_cutoffs: dict[int, int] | None = None
    ) -> tuple[int, set[int]]:
        """Drop each past month whose every row is past its point's retention.

        A chunk is past retention when it ends before its point's cutoff (``ArchiveStore.prune``
        deletes those); an hourly rollup when its month ends by its point's hourly cutoff
        (``hour_cutoffs``, H9; the raw cutoff when not given). A point without a cutoff (not in
        the catalog, or kept forever) keeps its month. Returns the chunks dropped and their
        points.
        """

        current = month_of(now_ms)
        current_start = bounds(*current)[0] if current else HIGH
        dropped, points = 0, set()
        for table in MONTHLY:
            for name, start, end in self.months(table):
                if end > current_start:
                    break
                with self.db.connect() as connection:
                    rows = _rows(connection, table, name)
                limits = (
                    hour_cutoffs if table == "rollups" and hour_cutoffs is not None else cutoffs
                )
                if not _expired(table, rows, limits, end):
                    continue
                with self.db.lock, self.db.connect() as connection:
                    # The table first, as writes take it: a write waits, never deadlocks.
                    connection.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
                    rows = _rows(connection, table, name)
                    if not _expired(table, rows, limits, end):
                        continue
                    connection.execute(f"DROP TABLE {name}")
                if table == "chunks":
                    dropped += sum(int(row["n"]) for row in rows)
                    points |= {int(row["point"]) for row in rows}
                year, month = month_of(start) or (0, 0)
                self._known.discard((table, year, month))
                LOGGER.info("%s: dropped, past retention", name)
        return dropped, points


def _rows(connection: Any, table: str, name: str) -> list[Any]:
    last = "MAX(t1)" if table == "chunks" else "0"
    return connection.execute(
        f"SELECT point, {last} AS last, COUNT(*) AS n FROM {name} GROUP BY point"
    ).fetchall()


def _expired(table: str, rows: list[Any], cutoffs: dict[int, int], end: int) -> bool:
    for row in rows:
        cutoff = cutoffs.get(int(row["point"]))
        if cutoff is None:
            return False
        if table == "chunks" and int(row["last"]) >= cutoff:
            return False
        if table == "rollups" and end > cutoff:
            return False
    return True


def rewrite_month(db: Database, table: str, name: str, start: int, end: int) -> bool:
    """Copy month ``name`` of ``table`` into a new table in key order and swap it in; whether it
    was swapped (a busy table leaves it for the next try).

    One transaction: the month is locked against writes (``SHARE``: reads go on), copied, and
    the new table carries the partition's bounds as a ``CHECK`` so attaching it needs no scan;
    detaching and attaching take the parent's lock for a moment only, with ``lock_timeout``.
    """

    fresh = f"{name}_rw"
    column = MONTHLY[table]
    try:
        with db.lock, db.connect() as connection:
            connection.execute(f"SET LOCAL lock_timeout = '{SWAP_LOCK_TIMEOUT}'")
            connection.execute(f"LOCK TABLE {name} IN SHARE MODE")
            connection.execute(f"DROP TABLE IF EXISTS {fresh}")
            connection.execute(f"CREATE TABLE {fresh} (like {table} INCLUDING ALL)")
            connection.execute(
                f"ALTER TABLE {fresh} ADD CONSTRAINT {fresh}_month"
                f" CHECK ({column} IS NOT NULL AND {column} >= {start} AND {column} < {end})"
            )
            key = "point, t0" if table == "chunks" else "point, hour"
            connection.execute(f"INSERT INTO {fresh} SELECT * FROM {name} ORDER BY {key}")
            # Changes to the tables (``ensure``, ``drop_expired``) wait for the swap, not the copy.
            connection.execute("SELECT pg_advisory_xact_lock(?)", (SCHEMA_LOCK,))
            connection.execute(f"ALTER TABLE {table} DETACH PARTITION {name}")
            connection.execute(
                f"ALTER TABLE {table} ATTACH PARTITION {fresh} FOR VALUES FROM ({start}) TO ({end})"
            )
            connection.execute(f"DROP TABLE {name}")
            connection.execute(f"ALTER TABLE {fresh} RENAME TO {name}")
            connection.execute(f"ALTER INDEX IF EXISTS {fresh}_pkey RENAME TO {name}_pkey")
            connection.execute(f"COMMENT ON TABLE {name} IS '{REWRITTEN}'")
    except Exception as exc:
        if getattr(exc, "sqlstate", None) in ("55P03", "40P01"):  # lock timeout, deadlock
            LOGGER.info("%s: busy, rewritten at a later housekeeping", name)
            return False
        raise
    return True


def closed_months(db: Database, table: str, now_ms: int) -> list[tuple[str, int, int]]:
    """``(name, start, end)`` of the months of ``table`` that ended over a day ago and were
    never rewritten, oldest first."""

    with db.connect() as connection:
        rows = connection.execute(
            "SELECT c.relname, obj_description(c.oid, 'pg_class') AS note FROM pg_inherits i"
            " JOIN pg_class c ON c.oid = i.inhrelid WHERE i.inhparent = to_regclass(?)",
            (table,),
        ).fetchall()
    done = {str(row[0]) for row in rows if row[1] == REWRITTEN}
    found = []
    for name, start, end in Partitions(db).months(table):
        if name not in done and end + REWRITE_AFTER_MS <= now_ms:
            found.append((name, start, end))
    return found
