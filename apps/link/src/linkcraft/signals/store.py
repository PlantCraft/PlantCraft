"""What the Signal quality algorithm keeps: the signals, their verdicts and its runs.

The signals are PlantCraft's signals plus LinkCraft's own settings.

PlantCraft owns a signal's name, unit, source, kind and limits; every sync
overwrites them. LinkCraft owns ``enabled`` and ``settings`` (limit overrides,
a reference signal, checks switched off or on, parameters per check); a sync
keeps them. A signal that disappears from PlantCraft is marked ``missing``
and skipped, never deleted, so its history stays.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.refs import split_signal_id
from plantcraft_sdk.utc import utc_iso

from linkcraft.db import Migration, Store, add_columns
from linkcraft.engine.latest import THIN_STEP_DAYS, mark_thinned, thin_window
from linkcraft.signals.models import (
    SETTING_KEYS,
    STATUSES,
    SignalQualitySettings,
)


class SignalStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS quality_signals (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'number',
        source_kind TEXT NOT NULL DEFAULT '',
        low REAL,
        high REAL,
        roles TEXT NOT NULL DEFAULT '[]',
        assets TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 1,
        missing INTEGER NOT NULL DEFAULT 0,
        settings TEXT NOT NULL DEFAULT '{}',
        synced_at TEXT,
        created_at TEXT NOT NULL
    );
    """

    JSON_FIELDS = {
        "roles": ("roles", []),
        "assets": ("assets", []),
        "settings": ("settings", {}),
    }

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns("quality_signals", {"source_kind": "TEXT NOT NULL DEFAULT ''"}),
        ),
    )

    def _row(self, row: Any) -> dict[str, Any]:
        item = self._row_with_json(row, self.JSON_FIELDS)
        item["enabled"] = bool(item["enabled"])
        item["missing"] = bool(item["missing"])
        return item

    def list(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM quality_signals"
        if active_only:
            query += " WHERE enabled = 1 AND missing = 0"
        with self._connect() as connection:
            rows = connection.execute(query + " ORDER BY id").fetchall()
        return [self._row(row) for row in rows]

    def get(self, signal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM quality_signals WHERE id = ?", (signal_id,)
            ).fetchone()
        return self._row(row) if row else None

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM quality_signals").fetchone()[0])

    def sync(
        self, signals: list[dict[str, Any]], usage: dict[str, dict[str, list[str]]]
    ) -> dict[str, int]:
        """Write PlantCraft's signals; ``usage`` maps a signal id to its asset roles and names."""

        now = self._now()
        seen = set()
        added = updated = 0
        with self._lock, self._connect() as connection:
            known = {row[0] for row in connection.execute("SELECT id FROM quality_signals")}
            for item in signals:
                signal_id = str(item.get("id") or "").strip()
                if not signal_id or signal_id in seen:
                    continue
                seen.add(signal_id)
                found = usage.get(signal_id, {})
                values = (
                    str(item.get("name") or signal_id),
                    str(item.get("unit") or ""),
                    str(item.get("source") or ""),
                    str(item.get("description") or ""),
                    "text" if item.get("kind") == "text" else "number",
                    str(item.get("source_kind") or ""),
                    _number(item.get("low")),
                    _number(item.get("high")),
                    self._json(sorted(set(found.get("roles", [])))),
                    self._json(sorted(set(found.get("assets", [])))),
                    now,
                )
                if signal_id in known:
                    connection.execute(
                        """UPDATE quality_signals SET name = ?, unit = ?, source = ?, description = ?,
                        kind = ?, source_kind = ?, low = ?, high = ?, roles = ?, assets = ?,
                        synced_at = ?,
                        missing = 0 WHERE id = ?""",
                        (*values, signal_id),
                    )
                    updated += 1
                else:
                    connection.execute(
                        """INSERT INTO quality_signals (name, unit, source, description, kind,
                        source_kind, low, high, roles, assets, synced_at, id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (*values, signal_id, now),
                    )
                    added += 1
            gone = known - seen
            for signal_id in gone:
                connection.execute(
                    "UPDATE quality_signals SET missing = 1 WHERE id = ?", (signal_id,)
                )
        return {"added": added, "updated": updated, "missing": len(gone)}

    def bare_tag_renames(self, signals: list[dict[str, Any]]) -> dict[str, str]:
        """Rows stored under a bare tag that PlantCraft now names ``<source id>:<tag>`` (D2).

        Only a tag exactly one of PlantCraft's signals carries is renamed, as API v1 reads it.
        """

        with self._connect() as connection:
            known = {row[0] for row in connection.execute("SELECT id FROM quality_signals")}
        owners: dict[str, list[str]] = {}
        for item in signals:
            signal_id = str(item.get("id") or "")
            source, tag = split_signal_id(signal_id)
            if source is not None and tag in known and signal_id not in known:
                owners.setdefault(tag, []).append(signal_id)
        return {tag: ids[0] for tag, ids in owners.items() if len(set(ids)) == 1}

    def rename(self, renames: dict[str, str]) -> None:
        """Move rows (and reference settings pointing at them) to their new ids."""

        if not renames:
            return
        with self._lock, self._connect() as connection:
            for old, new in renames.items():
                connection.execute("UPDATE quality_signals SET id = ? WHERE id = ?", (new, old))
            for row in connection.execute("SELECT id, settings FROM quality_signals").fetchall():
                settings = self._loads(row["settings"], {})
                reference = settings.get("reference")
                if reference in renames:
                    settings["reference"] = renames[reference]
                    connection.execute(
                        "UPDATE quality_signals SET settings = ? WHERE id = ?",
                        (self._json(settings), row["id"]),
                    )

    def update(
        self, signal_id: str, *, enabled: bool | None = None, settings: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Change LinkCraft's own fields; ``settings`` keys given replace the stored ones."""

        current = self.get(signal_id)
        if current is None:
            return None
        merged = dict(current["settings"])
        for key, value in (settings or {}).items():
            if key not in SETTING_KEYS:
                continue
            if value is None or value == [] or value == {}:
                merged.pop(key, None)
            else:
                merged[key] = value
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE quality_signals SET enabled = ?, settings = ? WHERE id = ?",
                (
                    int(current["enabled"] if enabled is None else enabled),
                    self._json(merged),
                    signal_id,
                ),
            )
        return self.get(signal_id)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


class QualityResultStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS quality_latest (
        signal_id TEXT PRIMARY KEY,
        checked_at TEXT NOT NULL,
        window_start TEXT,
        window_end TEXT,
        status TEXT NOT NULL,
        quality REAL,
        apt INTEGER NOT NULL DEFAULT 0,
        limiting TEXT,
        message TEXT NOT NULL DEFAULT '',
        checks TEXT NOT NULL DEFAULT '[]',
        round_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS quality_history (
        signal_id TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        status TEXT NOT NULL,
        quality REAL
    );
    CREATE INDEX IF NOT EXISTS quality_quality_history_signal ON quality_history (signal_id, checked_at);
    -- A row per signal every round for 90 days (71 million at 8,000 signals): the week's summary
    -- and the pruning read it by time.
    CREATE INDEX IF NOT EXISTS quality_history_time ON quality_history (checked_at);
    -- How far back each table's history is thinned to a point an hour (``thin_history``).
    CREATE TABLE IF NOT EXISTS history_thinned (
        name TEXT PRIMARY KEY,
        upto TEXT NOT NULL
    );
    -- Each signal's worst verdict of a closed day (UTC), kept once the day is over: the week's
    -- summary of the Analytics home reads 6 closed days here and only today in quality_history.
    CREATE TABLE IF NOT EXISTS quality_days (
        day TEXT NOT NULL,
        signal_id TEXT NOT NULL,
        status TEXT NOT NULL,
        quality REAL,
        PRIMARY KEY (day, signal_id)
    );
    CREATE TABLE IF NOT EXISTS quality_days_done (day TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS quality_rounds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        trigger TEXT NOT NULL DEFAULT 'schedule',
        started_by TEXT NOT NULL DEFAULT '',
        window_start TEXT,
        window_end TEXT,
        signals INTEGER NOT NULL DEFAULT 0,
        counts TEXT NOT NULL DEFAULT '{}',
        duration_seconds REAL,
        error TEXT
    );
    """

    def _latest_row(self, row: Any) -> dict[str, Any]:
        item = self._row_with_json(row, {"checks": ("checks", [])})
        item["apt"] = bool(item["apt"])
        return item

    # Verdicts -------------------------------------------------------------

    def daily(self, days: int = 7) -> list[dict[str, Any]]:
        """The last ``days`` days (UTC), oldest first: signals checked, their worst status,
        quality (``daily_quality``)."""

        return daily_quality(self, days)

    def save(self, verdicts: list[dict[str, Any]], round_id: int | None = None) -> None:
        with self._lock, self._connect() as connection:
            for verdict in verdicts:
                connection.execute(
                    """INSERT OR REPLACE INTO quality_latest (signal_id, checked_at, window_start,
                    window_end, status, quality, apt, limiting, message, checks, round_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        verdict["signal"],
                        verdict["checked_at"],
                        verdict.get("window_start"),
                        verdict.get("window_end"),
                        verdict["status"],
                        verdict.get("quality"),
                        int(bool(verdict.get("apt"))),
                        verdict.get("limiting"),
                        verdict.get("message") or "",
                        self._json(verdict.get("checks") or []),
                        round_id,
                    ),
                )
                connection.execute(
                    "INSERT INTO quality_history (signal_id, checked_at, status, quality) VALUES (?, ?, ?, ?)",
                    (
                        verdict["signal"],
                        verdict["checked_at"],
                        verdict["status"],
                        verdict.get("quality"),
                    ),
                )
            _forget_days(connection, {str(verdict["checked_at"])[:10] for verdict in verdicts})

    def rename(self, renames: dict[str, str]) -> None:
        """Keep a signal's verdict and history when PlantCraft renames it (see SignalStore)."""

        with self._lock, self._connect() as connection:
            for old, new in renames.items():
                connection.execute(
                    "UPDATE quality_latest SET signal_id = ? WHERE signal_id = ?", (new, old)
                )
                connection.execute(
                    "UPDATE quality_history SET signal_id = ? WHERE signal_id = ?", (new, old)
                )
            connection.execute("DELETE FROM quality_days")
            connection.execute("DELETE FROM quality_days_done")

    def latest(self, signal_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM quality_latest WHERE signal_id = ?", (signal_id,)
            ).fetchone()
        return self._latest_row(row) if row else None

    def latest_many(self, signal_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            if signal_ids is None:
                rows = connection.execute("SELECT * FROM quality_latest").fetchall()
            else:
                rows = []
                for offset in range(0, len(signal_ids), 500):
                    part = signal_ids[offset : offset + 500]
                    marks = ",".join("?" * len(part))
                    rows += connection.execute(
                        f"SELECT * FROM quality_latest WHERE signal_id IN ({marks})", part
                    ).fetchall()
        return {row["signal_id"]: self._latest_row(row) for row in rows}

    def of_round(self, round_id: int) -> list[dict[str, Any]]:
        """The signals whose latest verdict this run gave (a later run judges them again)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT signal_id, checked_at, status, quality, apt, limiting, message "
                "FROM quality_latest WHERE round_id = ?",
                (int(round_id),),
            ).fetchall()
        return [{**dict(row), "apt": bool(row["apt"])} for row in rows]

    def summaries(self) -> dict[str, dict[str, Any]]:
        """Latest status per signal without the check details (cheap, for lists)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT signal_id, checked_at, status, quality, apt, limiting, message, checks "
                "FROM quality_latest"
            ).fetchall()
        found = {}
        for row in rows:
            item = dict(row)
            checks = self._loads(item.pop("checks"), [])
            item["apt"] = bool(item["apt"])
            # Every check that warned or failed, not only the limiting one.
            item["flagged"] = [
                check.get("check") for check in checks if check.get("status") in ("warning", "bad")
            ]
            found[row["signal_id"]] = item
        return found

    def history(self, signal_id: str, days: float = 30) -> list[dict[str, Any]]:
        since = utc_iso(datetime.now(timezone.utc) - timedelta(days=days))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT checked_at, status, quality FROM quality_history
                WHERE signal_id = ? AND checked_at >= ? ORDER BY checked_at""",
                (signal_id, since),
            ).fetchall()
        return [dict(row) for row in rows]

    def statuses_between(self, start: str, end: str) -> dict[str, str]:
        """signal_id -> the status of its last verdict in ``[start, end)``: how each signal
        ended a day. One read on the time index, whatever the signals."""

        with self._connect() as connection:
            rows = connection.execute(
                """SELECT signal_id, status, MAX(checked_at) FROM quality_history
                WHERE checked_at >= ? AND checked_at < ? GROUP BY signal_id""",
                (start, end),
            ).fetchall()
        return {row[0]: row[1] for row in rows}

    def thin_history(self, *, full_days: float, step_days: float = THIN_STEP_DAYS) -> int:
        """Past ``full_days`` ago, keep of each signal's good verdicts the last of every hour,
        and every other verdict; the rows deleted, at most ``step_days`` more a call
        (``LatestStore.thin_history``). A check every 15 minutes of 8,000 signals is 71 million
        rows in 90 days, nearly all good: each day keeps its worst and its last verdict
        (``daily``, ``statuses_between``) at about a quarter of the rows."""

        now = datetime.now(timezone.utc)
        with self._lock, self._connect() as connection:
            oldest = connection.execute("SELECT MIN(checked_at) FROM quality_history").fetchone()[0]
            if oldest is None:
                return 0
            window = thin_window(
                connection,
                "quality_history",
                str(oldest),
                utc_iso(now),
                full_days,
                step_days,
                write=utc_iso,
            )
            if window is None:
                return 0
            start, end = window
            removed = connection.execute(
                "DELETE FROM quality_history WHERE checked_at >= ? AND checked_at < ?"
                " AND status = 'good' AND rowid NOT IN (SELECT rowid FROM (SELECT rowid,"
                " MAX(checked_at) FROM quality_history WHERE checked_at >= ? AND checked_at < ?"
                " AND status = 'good' GROUP BY signal_id, substr(checked_at, 1, 13)))",
                (start, end, start, end),
            ).rowcount
            mark_thinned(connection, "quality_history", end)
        return removed

    def prune(self, days: float = 90) -> int:
        since = utc_iso(datetime.now(timezone.utc) - timedelta(days=days))
        with self._lock, self._connect() as connection:
            removed = connection.execute(
                "DELETE FROM quality_history WHERE checked_at < ?", (since,)
            )
            connection.execute("DELETE FROM quality_rounds WHERE started_at < ?", (since,))
            connection.execute("DELETE FROM quality_days WHERE day < ?", (since[:10],))
            connection.execute("DELETE FROM quality_days_done WHERE day < ?", (since[:10],))
        return removed.rowcount

    # Rounds ---------------------------------------------------------------

    def start_round(self, trigger: str, started_by: str = "") -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO quality_rounds (started_at, status, trigger, started_by) VALUES (?, ?, ?, ?)",
                (self._now(), "running", trigger, started_by),
            )
            return int(cursor.lastrowid)

    def discard_round(self, round_id: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM quality_rounds WHERE id = ?", (round_id,))

    def finish_round(self, round_id: int, **fields: Any) -> None:
        allowed = {
            "status",
            "window_start",
            "window_end",
            "signals",
            "counts",
            "duration_seconds",
            "error",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if "counts" in values:
            values["counts"] = self._json(values["counts"])
        values["finished_at"] = self._now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE quality_rounds SET {assignments} WHERE id = ?",
                (*values.values(), round_id),
            )

    def interrupt_running(self) -> None:
        """Rounds left running by a stopped server end as interrupted."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE quality_rounds SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
                (self._now(),),
            )

    def round(self, round_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM quality_rounds WHERE id = ?", (round_id,)
            ).fetchone()
        return self._row_with_json(row, {"counts": ("counts", {})}) if row else None

    def rounds(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM quality_rounds ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_with_json(row, {"counts": ("counts", {})}) for row in rows]


class SettingsStore(Store):
    """The algorithm's settings (one JSON row)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS quality_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );
    """

    def __init__(self, db, defaults: SignalQualitySettings):
        super().__init__(db)
        self.defaults = defaults

    def get(self) -> SignalQualitySettings:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM quality_settings WHERE key = 'protocol'"
            ).fetchone()
        stored = self._loads(row["value"] if row else None, {})
        try:
            return SignalQualitySettings(**{**self.defaults.model_dump(), **stored})
        except ValueError:
            return self.defaults

    def save(self, settings: SignalQualitySettings, by: str = "") -> SignalQualitySettings:
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO quality_settings (key, value, updated_at, updated_by)
                VALUES ('protocol', ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                updated_at = excluded.updated_at, updated_by = excluded.updated_by""",
                (self._json(settings.model_dump()), self._now(), by),
            )
        return self.get()


def _day_rows(rows: list[Any], days: int) -> list[dict[str, Any]]:
    """Per day: each signal's worst status that day, counted, and the day's mean quality."""

    rank = {"bad": 3, "suspect": 2, "unknown": 1, "good": 0}
    worst: dict[str, dict[str, tuple[int, float | None]]] = {}
    for row in rows:
        day, signal, status, quality = row["day"], row["signal_id"], row["status"], row["quality"]
        if day is None:
            continue
        current = worst.setdefault(day, {}).get(signal)
        item = (rank.get(status, 1), quality)
        if current is None or item[0] > current[0]:
            worst[day][signal] = item
    end = datetime.now(timezone.utc).date()
    found = []
    for offset in range(days - 1, -1, -1):
        day = (end - timedelta(days=offset)).isoformat()
        entries = worst.get(day, {})
        counts = dict.fromkeys(STATUSES, 0)
        names = {value: key for key, value in rank.items()}
        qualities = []
        for status, quality in entries.values():
            counts[names[status]] += 1
            if quality is not None:
                qualities.append(float(quality))
        found.append(
            {
                "day": day,
                "signals": len(entries),
                **counts,
                "mean_quality": round(sum(qualities) / len(qualities), 1) if qualities else None,
            }
        )
    return found


_DAY_WORST = """
    SELECT date(checked_at) AS day, signal_id, status, quality,
           MAX((CASE status WHEN 'bad' THEN 3 WHEN 'suspect' THEN 2 WHEN 'good' THEN 0 ELSE 1 END)
               * 1000000000000 - rowid) AS pick
    FROM quality_history WHERE checked_at >= ? AND checked_at < ? GROUP BY signal_id
"""


def _forget_days(connection: Any, days: set[str]) -> None:
    """Closed days that got a verdict again are summed up again at the next read."""

    for day in days:
        connection.execute("DELETE FROM quality_days WHERE day = ?", (day,))
        connection.execute("DELETE FROM quality_days_done WHERE day = ?", (day,))


def _day_worst(connection: Any, day: str) -> list[Any]:
    """Each signal's worst verdict of UTC ``day`` (its first one of that rank, as ``_day_rows``
    keeps it). Stored times are UTC text, so the day's rows are the ones from ``day`` (as text)
    up to the next day, whatever their separator or fraction."""

    following = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    return connection.execute(_DAY_WORST, (day, following)).fetchall()


def daily_quality(store: QualityResultStore, days: int = 7) -> list[dict[str, Any]]:
    """The last ``days`` days (UTC), oldest first: signals checked, their worst status, quality.

    A closed day is summed up once (``quality_days``), today each time: at 8,000 signals checked
    every 15 minutes a week is 5 million rows, read in 20 s when the summary scanned them all."""

    today = datetime.now(timezone.utc).date()
    rows: list[Any] = []
    with store._lock, store._connect() as connection:
        for offset in range(days - 1, 0, -1):
            day = (today - timedelta(days=offset)).isoformat()
            if connection.execute(
                "SELECT 1 FROM quality_days_done WHERE day = ?", (day,)
            ).fetchone():
                rows += connection.execute(
                    "SELECT day, signal_id, status, quality FROM quality_days WHERE day = ?", (day,)
                ).fetchall()
                continue
            found = _day_worst(connection, day)
            connection.executemany(
                "INSERT OR REPLACE INTO quality_days (day, signal_id, status, quality)"
                " VALUES (?, ?, ?, ?)",
                [(row["day"], row["signal_id"], row["status"], row["quality"]) for row in found],
            )
            connection.execute("INSERT OR IGNORE INTO quality_days_done (day) VALUES (?)", (day,))
            rows += found
        rows += _day_worst(connection, today.isoformat())
    return _day_rows(rows, days)
