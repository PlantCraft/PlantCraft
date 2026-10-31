"""Old history keeps a point an hour (``thin_history``): fewer rows, the same days' answers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from linkcraft.db import Database
from linkcraft.engine.latest import LatestStore
from linkcraft.signals.store import QualityResultStore

APP, KIND = "cpm", "loop"


def _day(store, subject: str, day: str) -> list[tuple]:
    with store._connect() as connection:
        return connection.execute(
            "SELECT source_end, status, health FROM subject_health WHERE subject_id = ?"
            " AND source_end >= ? AND source_end < ? ORDER BY source_end",
            (subject, day + " 00:00:00", day + " 99"),
        ).fetchall()


def _count(store, table: str) -> int:
    with store._connect() as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608


def test_loop_health_keeps_an_hour_s_last_point_past_the_full_days(tmp_path):
    store = LatestStore(Database(tmp_path / "latest.sqlite3"))
    now = datetime.now(UTC).replace(minute=5, second=0, microsecond=0)
    rows = []
    for tenth in range(10 * 144):  # 10 days, a round every 10 minutes, 2 loops
        moment = now - timedelta(minutes=10 * tenth)
        for number in range(2):
            rows.append(
                {
                    "subject_id": f"L{number}",
                    "source_end": moment.strftime("%Y-%m-%d %H:%M:%S"),
                    "status": ("ok", "warning")[(tenth + number) % 2],
                    "health": float(tenth % 100),
                }
            )
    store.add_history(APP, KIND, rows)
    before = _count(store, "subject_health")
    day = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    last_before = tuple(_day(store, "L0", day)[-1])

    removed, calls = 0, 0
    while thinned := store.thin_history(full_days=2):  # a day a call: spread over ticks
        removed, calls = removed + thinned, calls + 1
    assert removed and calls >= 7 and store.thin_history(full_days=2) == 0
    after = _count(store, "subject_health")
    # 2 days in full (288 rounds), 8 days at 24 a day, per loop; edges may keep one more.
    assert after <= 2 * (2 * 144 + 8 * 24 + 4) and after < before / 2.5
    kept = _day(store, "L0", day)
    assert len(kept) == 24 and tuple(kept[-1]) == last_before
    # The newest two days are untouched.
    recent = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    assert len(_day(store, "L1", recent)) == 144


def test_signal_checks_keep_every_problem_and_an_hour_s_last_good_verdict(tmp_path):
    store = QualityResultStore(Database(tmp_path / "quality.sqlite3"))
    now = datetime.now(UTC)
    verdicts = []
    for quarter in range(10 * 96):  # 10 days, a check every 15 minutes
        moment = now - timedelta(minutes=15 * quarter)
        verdicts.append(
            {
                "signal": "plant:S1",
                "checked_at": moment.isoformat(),
                "status": "bad" if quarter % 50 == 7 else "good",
                "quality": 90.0,
            }
        )
    store.save(verdicts)
    problems = sum(1 for item in verdicts if item["status"] == "bad")
    while store.thin_history(full_days=2):
        pass
    rows = store.history("plant:S1", days=30)
    assert sum(1 for row in rows if row["status"] == "bad") == problems
    assert len(rows) <= 2 * 96 + 8 * 24 + problems + 4
