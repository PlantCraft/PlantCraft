"""Loop-hours lost by cause (A13) and each loop's effective control (A7).

**Effective control** is our composite score for a loop: the share of the time it was really
controlling, that is in its normal (automatic) mode, with the PV inside its operating band and the
output off its limits. It is the product of three fractions the loop's own methods measure:

    effective control = (1 - manual fraction) x inside-band fraction x (1 - saturation fraction)

A fraction a loop's algorithm does not measure counts as 1 (nothing known against it), and the
score is None when none of the three is measured.

**Loop-hours lost** turn the same findings into time, the way plants count losses: each monitoring
round on a loop adds the part of its window no earlier round covered, and splits it by cause:

- ``manual``: the time the loop was out of its normal mode (``manual_mode_fraction``);
- ``saturated``: the time its output sat at a limit (``op_saturation_fraction``);
- ``oscillating``: the whole new time when the oscillation check found the loop oscillating
  (``oscillation_autocorrelation`` warning or bad);
- ``bad_signal``: the time its PV was missing or frozen (``dq_availability``,
  ``dq_value_integrity``).

Causes can overlap (a loop in manual with a frozen PV), so each is counted on its own; ``lost`` is
the time outside effective control. Rounds are kept 400 days, enough for a year by area.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.utc import parse_instant, utc_iso

from linkcraft.db import Store

CAUSES = ("manual", "saturated", "oscillating", "bad_signal")
CAUSE_LABELS = {
    "manual": "Out of normal mode",
    "saturated": "Output at a limit",
    "oscillating": "Oscillating",
    "bad_signal": "Bad signal",
}
KEEP_DAYS = 400
PROBLEM = {"warning", "bad"}


def _metric(results: list[dict[str, Any]], method_id: str, key: str) -> float | None:
    for item in results:
        if item.get("method_id") != method_id or item.get("status") in {
            "not_applicable",
            "insufficient_data",
        }:
            continue
        value = (item.get("metrics") or {}).get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return min(1.0, max(0.0, float(value)))
    return None


def _status(results: list[dict[str, Any]], method_id: str) -> str | None:
    for item in results:
        if item.get("method_id") == method_id:
            return item.get("status")
    return None


def effective_control(results: list[dict[str, Any]]) -> dict[str, Any]:
    """A loop's effective control (percent) and the three fractions it multiplies."""

    manual = _metric(results, "manual_mode_fraction", "manual_fraction")
    inside = _metric(results, "operating_band_fraction", "inside_fraction")
    saturated = _metric(results, "op_saturation_fraction", "saturation_fraction")
    parts = {
        "normal_mode": None if manual is None else 1.0 - manual,
        "in_band": inside,
        "not_saturated": None if saturated is None else 1.0 - saturated,
    }
    known = [value for value in parts.values() if value is not None]
    score = None
    if known:
        score = 1.0
        for value in known:
            score *= value
        score = round(100.0 * score, 1)
    return {
        "score": score,
        **{key: None if value is None else round(100.0 * value, 1) for key, value in parts.items()},
    }


def cause_fractions(results: list[dict[str, Any]]) -> dict[str, float]:
    """The share of a round's window lost to each cause."""

    manual = _metric(results, "manual_mode_fraction", "manual_fraction") or 0.0
    saturated = _metric(results, "op_saturation_fraction", "saturation_fraction") or 0.0
    oscillating = 1.0 if _status(results, "oscillation_autocorrelation") in PROBLEM else 0.0
    coverage = _metric(results, "dq_availability", "coverage_pv")
    frozen = _metric(results, "dq_value_integrity", "frozen_fraction") or 0.0
    bad = max(0.0 if coverage is None else 1.0 - coverage, frozen)
    return {"manual": manual, "saturated": saturated, "oscillating": oscillating, "bad_signal": bad}


class LossStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS loop_losses (
        loop_id TEXT NOT NULL,
        -- The part of the round's window no earlier round on the loop covered (UTC).
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        seconds REAL NOT NULL,
        manual_s REAL NOT NULL,
        saturated_s REAL NOT NULL,
        oscillating_s REAL NOT NULL,
        bad_signal_s REAL NOT NULL,
        -- Seconds outside effective control (A7); NULL when it is not measured.
        lost_s REAL,
        PRIMARY KEY (loop_id, end)
    );
    CREATE INDEX IF NOT EXISTS idx_loop_losses_end ON loop_losses(end);
    """

    def record(self, rounds: list[dict[str, Any]]) -> int:
        """Add each round's new time: ``{loop_id, start, end, results}``. Returns rows added."""

        rounds = [item for item in rounds if item.get("start") and item.get("end")]
        if not rounds:
            return 0
        with self._lock, self._connect() as connection:
            last = {
                row["loop_id"]: row["end"]
                for row in connection.execute(
                    "SELECT loop_id, MAX(end) AS end FROM loop_losses GROUP BY loop_id"
                )
            }
            rows = []
            for item in rounds:
                start, end = parse_instant(item["start"]), parse_instant(item["end"])
                before = parse_instant(last.get(item["loop_id"]))
                if before is not None and before > start:
                    start = before
                if start is None or end is None or end <= start:
                    continue
                seconds = (end - start).total_seconds()
                share = cause_fractions(item.get("results") or [])
                score = effective_control(item.get("results") or [])["score"]
                rows.append(
                    (
                        item["loop_id"],
                        utc_iso(start),
                        utc_iso(end),
                        seconds,
                        *(seconds * share[cause] for cause in CAUSES),
                        None if score is None else seconds * (1.0 - score / 100.0),
                    )
                )
            connection.executemany(
                "INSERT OR REPLACE INTO loop_losses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
            )
            oldest = utc_iso(datetime.now(UTC) - timedelta(days=KEEP_DAYS))
            connection.execute("DELETE FROM loop_losses WHERE end < ?", (oldest,))
        return len(rows)

    def totals(self, since: datetime, until: datetime) -> dict[str, dict[str, float]]:
        """Each loop's seconds (watched, per cause, lost) in rounds ending in [since, until)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT loop_id, SUM(seconds) AS seconds, SUM(manual_s) AS manual,
                       SUM(saturated_s) AS saturated, SUM(oscillating_s) AS oscillating,
                       SUM(bad_signal_s) AS bad_signal, SUM(lost_s) AS lost,
                       SUM(CASE WHEN lost_s IS NOT NULL THEN seconds END) AS scored
                FROM loop_losses WHERE end >= ? AND end < ? GROUP BY loop_id
                """,
                (utc_iso(since), utc_iso(until)),
            ).fetchall()
        return {
            row["loop_id"]: {key: row[key] for key in row.keys() if key != "loop_id"}
            for row in rows
        }


def losses_by(
    totals: dict[str, dict[str, float]], loops: dict[str, Any], group_by: str = "area"
) -> list[dict[str, Any]]:
    """Loop-hours per cause, summed by area (or one row per loop), worst first."""

    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "loops": 0,
            "watched_h": 0.0,
            "scored_h": 0.0,
            "lost_h": 0.0,
            **{cause: 0.0 for cause in CAUSES},
        }
    )
    for loop_id, found in totals.items():
        loop = loops.get(loop_id)
        if loop is None:
            continue
        if group_by == "loop":
            key = loop_id
        elif group_by == "all":
            key = "all"
        else:
            key = getattr(loop, "area", "") or "No area"
        row = groups[key]
        if group_by == "loop":
            row["name"] = getattr(loop, "name", loop_id)
            row["area"] = getattr(loop, "area", "") or "No area"
        row["loops"] += 1
        row["watched_h"] += (found.get("seconds") or 0.0) / 3600
        row["scored_h"] += (found.get("scored") or 0.0) / 3600
        row["lost_h"] += (found.get("lost") or 0.0) / 3600
        for cause in CAUSES:
            row[cause] += (found.get(cause) or 0.0) / 3600
    found = []
    for key, row in groups.items():
        rounded = {
            name: round(value, 2) if isinstance(value, float) else value
            for name, value in row.items()
        }
        scored = rounded.pop("scored_h")
        rounded["effective_control"] = (
            round(100.0 * (1.0 - row["lost_h"] / row["scored_h"]), 1) if scored else None
        )
        found.append({"key": key, **rounded})
    found.sort(key=lambda item: (-item["lost_h"], item["key"]))
    return found
