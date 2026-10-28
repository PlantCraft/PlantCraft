"""Derived series apps publish (``PUT /api/v1/series``), kept here when there is no HistCraft.

With HistCraft configured the writes go there (``platform.datalayer``); without it, as in tests
and installs without a historian, they live in these tables and are read back through API v1
like any other signal, under the source ``app-<app id>``. Values are kept as written: a later
write at the same instant replaces the value.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from processcraft.db import Database, Migration, Store, add_columns


class DerivedSeriesStore(Store):
    """Derived signals (one row each) and their points."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS derived_series (
        signal_id TEXT PRIMARY KEY,
        app TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'number',
        subject TEXT,
        result TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_derived_series_app ON derived_series(app);

    CREATE TABLE IF NOT EXISTS derived_points (
        signal_id TEXT NOT NULL,
        ts TEXT NOT NULL,
        value,
        PRIMARY KEY(signal_id, ts)
    ) WITHOUT ROWID;

    -- A runs point's executions (kind 'runs'): one whole series per run, newest kept.
    CREATE TABLE IF NOT EXISTS derived_runs (
        signal_id TEXT NOT NULL,
        run_at TEXT NOT NULL,
        t_json TEXT NOT NULL,
        v_json TEXT NOT NULL,
        PRIMARY KEY(signal_id, run_at)
    ) WITHOUT ROWID;
    """

    # Kinds kept as written and read back as recorded values (no grid, no aggregation but last).
    TYPED_KINDS = ("integer", "boolean", "instant", "structured")

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "derived_series",
                {
                    "description": "TEXT NOT NULL DEFAULT ''",
                    # Round 8 (2026-10-25): retention set by the writing app and its lock; runs kept.
                    "retention_days": "INTEGER",
                    "managed_by": "TEXT NOT NULL DEFAULT ''",
                    "keep_runs": "INTEGER",
                    "keep_days": "INTEGER",
                },
            ),
        ),
    )

    def __init__(self, db: Database):
        super().__init__(db)
        self.version = 0

    def _describe(self, connection: Any, app: str, item: dict[str, Any], kind: str) -> None:
        """Insert or update the point's row; fields the item leaves out (None) keep theirs."""

        current = connection.execute(
            "SELECT * FROM derived_series WHERE signal_id = ?", (item["signal"],)
        ).fetchone()
        keep = dict(current) if current else {}

        def given(key: str, default: Any = "") -> Any:
            return item[key] if item.get(key) is not None else keep.get(key, default)

        connection.execute(
            """
            INSERT INTO derived_series
                (signal_id, app, name, unit, description, kind, subject, result, retention_days,
                 managed_by, keep_runs, keep_days, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signal_id) DO UPDATE SET
                name = excluded.name, unit = excluded.unit,
                description = excluded.description, kind = excluded.kind,
                subject = excluded.subject, result = excluded.result,
                retention_days = excluded.retention_days, managed_by = excluded.managed_by,
                keep_runs = excluded.keep_runs, keep_days = excluded.keep_days,
                updated_at = excluded.updated_at
            """,
            (
                item["signal"],
                app,
                given("name"),
                given("unit"),
                given("description"),
                kind,
                item.get("subject") or keep.get("subject"),
                item.get("result") or keep.get("result"),
                given("retention_days", None),
                given("managed_by"),
                given("keep_runs", None),
                item.get("keep_days") if "keep_runs" in item else keep.get("keep_days"),
                self._now(),
            ),
        )

    def write(self, app: str, item: dict[str, Any]) -> None:
        """One series as validated by ``plantcraft_sdk.derived.DerivedIn`` (UTC ``t``)."""

        kind = item["kind"]
        with self._lock, self._write() as connection:
            self._describe(connection, app, item, kind)
            connection.executemany(
                "INSERT OR REPLACE INTO derived_points (signal_id, ts, value) VALUES (?, ?, ?)",
                [
                    (item["signal"], _key(stamp), _encode(kind, value))
                    for stamp, value in zip(item["t"], item["v"], strict=True)
                ],
            )
        self.version += 1

    def write_run(self, app: str, item: dict[str, Any]) -> None:
        """One execution of a runs point (``plantcraft_sdk.derived.RunIn``); a run at the
        same ``run_at`` is replaced, then only the newest ``keep_runs`` (and none older than
        ``keep_days``) stay."""

        signal = item["signal"]
        with self._lock, self._write() as connection:
            self._describe(connection, app, item, "runs")
            connection.execute(
                "INSERT OR REPLACE INTO derived_runs (signal_id, run_at, t_json, v_json)"
                " VALUES (?, ?, ?, ?)",
                (signal, _key(item["run_at"]), json.dumps(item["t"]), json.dumps(item["v"])),
            )
            connection.execute(
                """
                DELETE FROM derived_runs WHERE signal_id = ? AND run_at NOT IN (
                    SELECT run_at FROM derived_runs WHERE signal_id = ?
                    ORDER BY run_at DESC LIMIT ?)
                """,
                (signal, signal, int(item["keep_runs"])),
            )
            if item.get("keep_days"):
                oldest = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(item["keep_days"]))
                connection.execute(
                    "DELETE FROM derived_runs WHERE signal_id = ? AND run_at < ?",
                    (signal, _key(oldest)),
                )
        self.version += 1

    def runs(self, signal_id: str, *, at: Any = None, last: int = 1) -> list[dict[str, Any]]:
        """Runs of a runs point, newest first: the one at ``at``, else the ``last`` newest."""

        query = "SELECT run_at, t_json, v_json FROM derived_runs WHERE signal_id = ?"
        args: list[Any] = [signal_id]
        if at is not None:
            query += " AND run_at = ?"
            args.append(_key(at))
        query += " ORDER BY run_at DESC LIMIT ?"
        args.append(1 if at is not None else int(last))
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, args).fetchall()
        return [
            {
                "run_at": _iso(row["run_at"]),
                "t": json.loads(row["t_json"]),
                "v": json.loads(row["v_json"]),
            }
            for row in rows
        ]

    def run_list(self, signal_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """``[{run_at, start, end, n}]`` of a runs point, newest first."""

        return [
            {
                "run_at": run["run_at"],
                "start": run["t"][0] if run["t"] else None,
                "end": run["t"][-1] if run["t"] else None,
                "n": len(run["t"]),
            }
            for run in self.runs(signal_id, last=limit)
        ]

    def read_typed(
        self, signal_id: str, kind: str, start: Any, end: Any
    ) -> tuple[list[str], list[Any]]:
        """Recorded instants (UTC ISO) and values of a ``TYPED_KINDS`` point, decoded."""

        values = self.read(signal_id, start, end)
        return (
            [stamp.isoformat() for stamp in values.index],
            [_decode(kind, value) for value in values.tolist()],
        )

    def kind_of(self, signal_id: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT kind FROM derived_series WHERE signal_id = ?", (signal_id,)
            ).fetchone()
        return row["kind"] if row else None

    def retire(self, app: str, signal_ids: list[str]) -> list[str]:
        """Remove ``app``'s own signals and their points: the ids removed."""

        removed: list[str] = []
        with self._lock, self._write() as connection:
            for signal_id in signal_ids:
                found = connection.execute(
                    "DELETE FROM derived_series WHERE signal_id = ? AND app = ?", (signal_id, app)
                ).rowcount
                if found:
                    connection.execute(
                        "DELETE FROM derived_points WHERE signal_id = ?", (signal_id,)
                    )
                    connection.execute("DELETE FROM derived_runs WHERE signal_id = ?", (signal_id,))
                    removed.append(signal_id)
        if removed:
            self.version += 1
        return removed

    def signals(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM derived_series ORDER BY signal_id").fetchall()
        return [dict(row) for row in rows]

    def read(self, signal_id: str, start: Any = None, end: Any = None) -> pd.Series:
        """The points of one signal in ``[start, end]`` (UTC instants), indexed in UTC."""

        query = "SELECT ts, value FROM derived_points WHERE signal_id = ?"
        args: list[Any] = [signal_id]
        if start is not None:
            query += " AND ts >= ?"
            args.append(_key(start))
        if end is not None:
            query += " AND ts <= ?"
            args.append(_key(end))
        with self._lock, self._connect() as connection:
            rows = connection.execute(query + " ORDER BY ts", args).fetchall()
        index = pd.DatetimeIndex(pd.to_datetime([row["ts"] for row in rows], utc=True))
        return pd.Series([row["value"] for row in rows], index=index, dtype=object)

    def last_time(self, signal_id: str) -> pd.Timestamp | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(ts) AS ts FROM derived_points WHERE signal_id = ?", (signal_id,)
            ).fetchone()
        return pd.Timestamp(row["ts"], tz="UTC") if row and row["ts"] else None


def _key(stamp: Any) -> str:
    """A UTC instant as sortable text (microseconds, no offset)."""

    value = pd.Timestamp(stamp)
    value = value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")


def _iso(key: str) -> str:
    return pd.Timestamp(key, tz="UTC").isoformat()


def _encode(kind: str, value: Any) -> Any:
    """A checked value as SQLite keeps it (structured as JSON text, booleans as 0 and 1)."""

    if value is None:
        return None
    if kind == "structured":
        return json.dumps(value, separators=(",", ":"))
    if kind == "boolean":
        return int(bool(value))
    return value


def _decode(kind: str, value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if kind == "structured":
        return json.loads(value)
    if kind == "boolean":
        return bool(value)
    if kind == "integer":
        return int(value)
    return value
