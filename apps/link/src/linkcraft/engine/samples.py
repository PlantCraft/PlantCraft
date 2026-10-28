"""The samples of a subject's last runs (owner, round 10, 2026-10-26): what each wire carried.

A run keeps what each block said and the last value on each wire (``blocks.run.wires``); its
page draws the diagram with them. The samples behind those values, a thinned series per wire
(``blocks.run.samples``), are kept here for the newest ``SAMPLES_KEPT`` runs of each subject
and schedule only, so clicking a block on a recent run draws its charts while a schedule that
runs every few minutes never fills the database. The Historian keeps the recorded outputs for
good; an older run still runs its window again (Show every sample).

``run_key`` is the run's id: a job's ``job_id``, or ``<subject>@<source_end>`` for a loop's
round (``loop_run_key``), which keeps no job per loop. ``detail`` is what the run page draws:
the wires with their samples and, for a loop's round, the rest of the run (its blocks, outputs,
window and the signals it read).
"""

from __future__ import annotations

from typing import Any

from linkcraft.db import Store

SAMPLES_KEPT = 10
# A loop's round, which runs no schedule of its own.
ROUND_SCOPE = "round"


def loop_run_key(subject_id: str, source_end: str) -> str:
    return f"{subject_id}@{source_end}"


class RunSampleStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS run_samples (
        run_key TEXT PRIMARY KEY,
        scope TEXT NOT NULL,
        subject_id TEXT NOT NULL,
        at TEXT NOT NULL,
        detail_json TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_run_samples_subject
    ON run_samples(scope, subject_id, at);
    """

    def save(self, rows: list[dict[str, Any]], *, keep: int = SAMPLES_KEPT) -> None:
        """Keep each row (``run_key``, ``scope``, ``subject_id``, ``at``, ``detail``), then only
        the newest ``keep`` runs of each subject in each scope it touched."""

        rows = [row for row in rows if row.get("detail") and row.get("at")]
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO run_samples (run_key, scope, subject_id, at, detail_json) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        str(row["run_key"]),
                        str(row.get("scope") or ""),
                        str(row["subject_id"]),
                        str(row["at"]),
                        self._json(row["detail"]),
                    )
                    for row in rows
                ],
            )
            for scope, subject in sorted(
                {(str(row.get("scope") or ""), str(row["subject_id"])) for row in rows}
            ):
                connection.execute(
                    """
                    DELETE FROM run_samples WHERE run_key IN (
                        SELECT run_key FROM run_samples WHERE scope = ? AND subject_id = ?
                        ORDER BY at DESC LIMIT -1 OFFSET ?
                    )
                    """,
                    (scope, subject, int(keep)),
                )

    def get(self, run_key: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT detail_json FROM run_samples WHERE run_key = ?", (run_key,)
            ).fetchone()
        return self._loads(row["detail_json"], None) if row else None

    def kept(self, scope: str, subject_id: str) -> set[str]:
        """The runs of a subject whose samples are kept."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT run_key FROM run_samples WHERE scope = ? AND subject_id = ?",
                (scope, subject_id),
            ).fetchall()
        return {row["run_key"] for row in rows}

    def forget(self, run_keys: list[str]) -> None:
        with self._lock, self._connect() as connection:
            connection.executemany(
                "DELETE FROM run_samples WHERE run_key = ?", [(key,) for key in run_keys]
            )


__all__ = ["ROUND_SCOPE", "SAMPLES_KEPT", "RunSampleStore", "loop_run_key"]
