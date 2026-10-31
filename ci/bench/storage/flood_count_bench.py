"""Alarms' flood count (``NoticeStore.raised_for``) on 30 days of outbox (report 13, 2026-10-31).

Fills an outbox shaped like Alarms' (``--rows`` notices over 30 days, 5 of 50 people each) and
times the flood count of every person for the last 10 minutes, the query the notifier runs each
cycle, as it was (``COUNT(DISTINCT alarm_id)``, no index on ``at``) and as it is now.

    python ci/bench/storage/flood_count_bench.py --rows 300000
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TABLE = """CREATE TABLE outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, alarm_id TEXT NOT NULL,
 name TEXT NOT NULL, policy_id TEXT NOT NULL, event TEXT NOT NULL, priority TEXT NOT NULL,
 at TEXT NOT NULL, recipients_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
CREATE INDEX outbox_status ON outbox (status, at);
CREATE INDEX outbox_alarm ON outbox (alarm_id, policy_id, at);"""
WHERE = (
    " FROM outbox, json_each(outbox.recipients_json) WHERE json_each.value = ? AND at >= ?"
    " AND event = 'raised' AND status NOT IN ('digest', 'chatter', 'dropped')"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=300_000)
    args = ap.parse_args()
    rng = random.Random(1)
    end = datetime(2026, 10, 31, tzinfo=timezone.utc)
    people = [f"user:p{i}" for i in range(50)]
    with tempfile.TemporaryDirectory() as folder:
        con = sqlite3.connect(Path(folder) / "alarmcraft.sqlite3")
        con.executescript(TABLE)
        con.executemany(
            "INSERT INTO outbox (alarm_id, name, policy_id, event, priority, at, recipients_json,"
            " status) VALUES (?, 'n', 'p', 'raised', 'high', ?, ?, ?)",
            (
                (f"a{rng.randrange(2000)}",
                 (end - timedelta(seconds=rng.uniform(0, 30 * 86400))).isoformat(),
                 json.dumps(rng.sample(people, 5)), rng.choice(["sent"] * 3 + ["digest", "dropped"]))
                for _ in range(args.rows)
            ),
        )  # fmt: skip
        con.commit()
        since = (end - timedelta(minutes=10)).isoformat()
        out = {"rows": args.rows}
        for label, query, index in (
            ("before", "SELECT COUNT(DISTINCT alarm_id)" + WHERE, None),
            (
                "after",
                "SELECT COUNT(DISTINCT +alarm_id)" + WHERE,
                "CREATE INDEX outbox_at ON outbox (at)",
            ),
        ):
            if index:
                con.execute(index)
            con.execute("ANALYZE")
            t0 = time.perf_counter()
            counts = [con.execute(query, (p, since)).fetchone()[0] for p in people]
            out[f"{label}_ms_per_person"] = round(
                (time.perf_counter() - t0) / len(people) * 1000, 3
            )
            out[f"{label}_total"] = sum(counts)
        print(json.dumps(out))


if __name__ == "__main__":
    main()
