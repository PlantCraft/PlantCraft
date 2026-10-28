"""The week summaries of the Analytics home read closed days from their day tables: the same
answer as summing every row, and summed up again when a closed day gets rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from linkcraft.db import Database
from linkcraft.engine.latest import LatestStore
from linkcraft.signals.store import QualityResultStore, _day_rows

APP, KIND = "cpm", "loop"


def _health_rows(now: datetime, days: int) -> list[dict]:
    rows = []
    for hours in range(days * 24):
        moment = now - timedelta(hours=hours)
        for number in range(3):
            rows.append(
                {
                    "subject_id": f"L{number}",
                    "source_end": moment.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": ("ok", "warning", "critical")[(hours + number) % 3],
                    "health": float((hours * 7 + number * 13) % 100),
                }
            )
    return rows


def _every_row(store: LatestStore, start: str, end: str) -> list[tuple]:
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT subject_id, (CAST(strftime('%s', source_end) AS INTEGER) / 86400) * 86400
               AS bucket, AVG(health) AS health, status, MAX(source_end) FROM subject_health
               WHERE application_id = ? AND subject_kind = ? AND source_end >= ? AND source_end <= ?
               GROUP BY subject_id, bucket""",
            (APP, KIND, start, end),
        ).fetchall()
    return sorted((r[0], r[1], round(r[2], 6), r[3]) for r in rows)


def _answer(rows: list[dict]) -> list[tuple]:
    return sorted((r["subject_id"], r["bucket"], round(r["health"], 6), r["status"]) for r in rows)


def test_day_buckets_match_every_row_and_follow_new_points(tmp_path):
    store = LatestStore(Database(tmp_path / "latest.sqlite3"))
    now = datetime.now(UTC).replace(microsecond=0)
    store.add_history(APP, KIND, _health_rows(now, 9))
    start = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    end = now.strftime("%Y-%m-%d %H:%M:%S")

    first = store.health_buckets(APP, KIND, start, end, 86400)
    assert _answer(first) == _every_row(store, start, end)
    with store._connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM subject_health_days_done").fetchone()[0] >= 5
        )
    assert _answer(store.health_buckets(APP, KIND, start, end, 86400)) == _answer(first)

    # A replay writes into a closed day: that day is summed up again.
    past = (now - timedelta(days=3)).replace(hour=12, minute=0, second=0)
    store.add_history(
        APP,
        KIND,
        [
            {
                "subject_id": "L0",
                "source_end": past.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "critical",
                "health": 0.0,
            }
        ],
    )
    assert _answer(store.health_buckets(APP, KIND, start, end, 86400)) == _every_row(
        store, start, end
    )


def _worst_every_row(store: QualityResultStore, days: int) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT date(checked_at) AS day, signal_id, status, quality FROM quality_history
            WHERE julianday(checked_at) >= julianday(?)""",
            (since,),
        ).fetchall()
    return _day_rows(rows, days)


def test_week_of_checks_matches_every_row_and_follows_new_verdicts(tmp_path):
    store = QualityResultStore(Database(tmp_path / "quality.sqlite3"))
    now = datetime.now(UTC)
    verdicts = []
    for quarter in range(9 * 96):
        moment = now - timedelta(minutes=15 * quarter)
        for number in range(4):
            verdicts.append(
                {
                    "signal": f"plant:S{number}",
                    "checked_at": moment.isoformat(),
                    "status": ("good", "suspect", "bad", "unknown")[(quarter + number) % 4],
                    "quality": float((quarter + number * 11) % 100),
                }
            )
    store.save(verdicts)
    expected = _worst_every_row(store, 7)
    assert store.daily(7) == expected
    assert store.daily(7) == expected  # from the day table this time

    store.save(
        [
            {
                "signal": "plant:S0",
                "checked_at": (now - timedelta(days=2)).isoformat(),
                "status": "bad",
                "quality": 1.0,
            }
        ]
    )
    assert store.daily(7) == _worst_every_row(store, 7)
