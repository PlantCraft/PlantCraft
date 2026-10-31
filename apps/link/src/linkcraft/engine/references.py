"""A loop's recorded reference: its results on a window someone called good, to compare against.

Siemens' ConPerMon and similar tools compare a loop's indicators with a reference period, after
commissioning or a retune, rather than with fixed limits alone (A8 of the 0.6 list). A person
records the last run as the loop's reference; every later look at the loop shows each method's
score and numeric indicators against it. One reference per loop: recording again replaces it.
"""

from __future__ import annotations

import math
from typing import Any

from linkcraft.db import Store

JUDGED = {"ok", "warning", "bad"}


class ReferenceStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS loop_references (
        loop_id TEXT PRIMARY KEY,
        recorded_at TEXT NOT NULL,
        recorded_by TEXT NOT NULL,
        -- The window the reference run read (UTC) and the algorithm version that ran.
        source_start TEXT,
        source_end TEXT,
        algorithm_version INTEGER,
        health REAL,
        results_json TEXT NOT NULL
    );
    """

    def record(self, loop_id: str, latest: dict[str, Any], actor: str) -> dict[str, Any]:
        """Keep ``latest`` (the loop's last saved run) as its reference, replacing any older one."""

        summary = latest.get("summary") or {}
        results = [
            {
                "method_id": item.get("method_id"),
                "status": item.get("status"),
                "score": item.get("score"),
                "metrics": _numbers(item.get("metrics") or {}),
            }
            for item in latest.get("results") or []
            if item.get("method_id")
        ]
        row = (
            loop_id,
            self._now(),
            actor,
            latest.get("source_start"),
            latest.get("source_end"),
            summary.get("algorithm_version"),
            latest.get("health", summary.get("health")),
            self._json(results),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO loop_references
                (loop_id, recorded_at, recorded_by, source_start, source_end, algorithm_version,
                 health, results_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        found = self.get(loop_id)
        assert found is not None
        return found

    def get(self, loop_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM loop_references WHERE loop_id = ?", (loop_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["results"] = self._loads(item.pop("results_json", None), [])
        return item

    def delete(self, loop_id: str) -> bool:
        with self._lock, self._connect() as connection:
            gone = connection.execute("DELETE FROM loop_references WHERE loop_id = ?", (loop_id,))
        return gone.rowcount > 0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _numbers(metrics: dict[str, Any]) -> dict[str, float]:
    return {key: number for key, value in metrics.items() if (number := _number(value)) is not None}


def _ratio(now: float | None, then: float | None) -> float | None:
    if now is None or then is None or then == 0:
        return None
    return round(now / then, 4)


def compare(
    reference: dict[str, Any] | None,
    results: list[dict[str, Any]],
    health: float | None,
    algorithm_version: int | None = None,
) -> dict[str, Any] | None:
    """The loop's last run against its reference: health and each method's score and numeric
    indicators then and now, with ``index`` = now / then for the indicators.

    ``methods`` lists the methods judged in both runs, the one whose score moved most first.
    ``version_changed`` says the algorithm changed since the reference, so scores may differ for
    that reason alone.
    """

    if reference is None:
        return None
    then = {item["method_id"]: item for item in reference.get("results") or []}
    methods = []
    for item in results:
        before = then.get(item.get("method_id"))
        if before is None or item.get("status") not in JUDGED or before.get("status") not in JUDGED:
            continue
        score_now, score_then = _number(item.get("score")), _number(before.get("score"))
        now_metrics = _numbers(item.get("metrics") or {})
        indicators = {
            key: {
                "reference": value,
                "now": now_metrics[key],
                "index": _ratio(now_metrics[key], value),
            }
            for key, value in (before.get("metrics") or {}).items()
            if key in now_metrics
        }
        methods.append(
            {
                "method_id": item["method_id"],
                "status_reference": before.get("status"),
                "status_now": item.get("status"),
                "score_reference": score_then,
                "score_now": score_now,
                "score_change": (
                    round(score_now - score_then, 2)
                    if score_now is not None and score_then is not None
                    else None
                ),
                "indicators": indicators,
            }
        )
    methods.sort(key=lambda item: -abs(item["score_change"] or 0.0))
    health_then = _number(reference.get("health"))
    health_now = _number(health)
    version_then = reference.get("algorithm_version")
    return {
        "recorded_at": reference.get("recorded_at"),
        "recorded_by": reference.get("recorded_by"),
        "source_start": reference.get("source_start"),
        "source_end": reference.get("source_end"),
        "health_reference": health_then,
        "health_now": health_now,
        "health_change": (
            round(health_now - health_then, 4)
            if health_now is not None and health_then is not None
            else None
        ),
        "version_changed": bool(
            version_then and algorithm_version and version_then != algorithm_version
        ),
        "methods": methods,
    }
