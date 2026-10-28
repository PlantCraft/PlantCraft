"""Each algorithm's latest run on each of its assets, its blocks' memory, and what it wrote.

One row per algorithm and asset: the summary people read (outputs, every block's verdict, the
run's verdict), the blocks' memory carried to the next run (``states``), and the last instant
each recorded series reached the historian (``written``), so a run sends only what is new.
"""

from __future__ import annotations

from typing import Any

from linkcraft.db import Store


class AssetRunStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS asset_runs (
        algorithm_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        asset_name TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'unknown',
        value REAL,
        message TEXT NOT NULL DEFAULT '',
        summary_json TEXT NOT NULL DEFAULT '{}',
        states_json TEXT NOT NULL DEFAULT '{}',
        written_json TEXT NOT NULL DEFAULT '{}',
        error TEXT,
        window_end TEXT,
        analyzed_at TEXT NOT NULL,
        PRIMARY KEY (algorithm_id, asset_id)
    );
    """

    def _row(self, row: Any) -> dict[str, Any]:
        return self._row_with_json(
            row,
            {
                "summary": ("summary_json", {}),
                "states": ("states_json", {}),
                "written": ("written_json", {}),
            },
        )

    def get(self, algorithm_id: str, asset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM asset_runs WHERE algorithm_id = ? AND asset_id = ?",
                (algorithm_id, asset_id),
            ).fetchone()
        return self._row(row) if row else None

    def list(
        self, algorithm_id: str | None = None, asset_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses, values = [], []
        for column, value in (("algorithm_id", algorithm_id), ("asset_id", asset_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM asset_runs {where} ORDER BY asset_name, algorithm_id",  # noqa: S608
                values,
            ).fetchall()
        return [self._row(row) for row in rows]

    def save(
        self,
        algorithm_id: str,
        asset_id: str,
        *,
        asset_name: str,
        summary: dict[str, Any],
        states: dict[str, Any],
        written: dict[str, Any],
        window_end: str | None,
        error: str | None = None,
    ) -> None:
        verdict = summary.get("verdict") or {}
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO asset_runs
                (algorithm_id, asset_id, asset_name, status, value, message, summary_json,
                 states_json, written_json, error, window_end, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(algorithm_id, asset_id) DO UPDATE SET
                    asset_name = excluded.asset_name, status = excluded.status,
                    value = excluded.value, message = excluded.message,
                    summary_json = excluded.summary_json, states_json = excluded.states_json,
                    written_json = excluded.written_json, error = excluded.error,
                    window_end = excluded.window_end, analyzed_at = excluded.analyzed_at
                """,
                (
                    algorithm_id,
                    asset_id,
                    asset_name,
                    str(verdict.get("status") or "unknown"),
                    verdict.get("value"),
                    str(verdict.get("message") or ""),
                    self._json({key: value for key, value in summary.items() if key != "samples"}),
                    self._json(states),
                    self._json(written),
                    error,
                    window_end,
                    self._now(),
                ),
            )

    def forget(self, algorithm_id: str, keep: set[str] | None = None) -> int:
        """Drop the rows of an algorithm's assets not in ``keep`` (all of them without it)."""

        rows = self.list(algorithm_id)
        gone = [row["asset_id"] for row in rows if keep is None or row["asset_id"] not in keep]
        with self._lock, self._connect() as connection:
            connection.executemany(
                "DELETE FROM asset_runs WHERE algorithm_id = ? AND asset_id = ?",
                [(algorithm_id, asset_id) for asset_id in gone],
            )
        return len(gone)

    def reset_states(self, algorithm_id: str) -> None:
        """Forget the blocks' memory (the diagram changed: a new calibration starts afresh)."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE asset_runs SET states_json = '{}' WHERE algorithm_id = ?", (algorithm_id,)
            )


__all__ = ["AssetRunStore"]
