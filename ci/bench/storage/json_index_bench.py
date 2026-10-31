"""The notification feed's query with and without an index on the JSON field it filters by.

Report 13 (storage), 2026-10-31. ``ConversationStore.notices_for`` (Desk's feed, the
notifications panel) keeps the messages whose ``meta_json`` says ``"kind": "notification"``.
This fills PlantCraft's real messages tables (``--users`` people, a direct conversation with
each of 3 app robots, ``--per-day`` notifications each a day for ``--days`` days, and group
chats) and times the real method for a week of notifications.

    python ci/bench/storage/json_index_bench.py --users 300 --days 365 --per-day 5
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from plantcraft.db import Database  # noqa: E402
from plantcraft.messages import ConversationStore  # noqa: E402

ROBOTS = ("alarmcraft", "linkcraft", "system")
END = datetime(2026, 10, 31, tzinfo=timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fill(path: Path, users: int, days: int, per_day: int) -> int:
    db = Database(path)
    with db.connect() as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS workspace_users (username TEXT PRIMARY KEY, "
            "display_name TEXT, kind TEXT)"
        )
        c.commit()
    ConversationStore(db, users=None)  # the real schema (and its indexes)
    rng = random.Random(5)
    people = [f"user{i}" for i in range(users)]
    with db.connect() as c:
        c.executemany(
            "INSERT INTO workspace_users VALUES (?, ?, ?)",
            [(p, p, "person") for p in people] + [(r, r, "system") for r in ROBOTS],
        )
        conv = 0
        members, messages = [], []
        start = END - timedelta(days=days)
        for person in people:
            for robot in ROBOTS:
                conv += 1
                members += [(conv, person, stamp(start)), (conv, robot, stamp(start))]
                for _ in range(days * per_day // len(ROBOTS)):
                    at = start + timedelta(seconds=rng.uniform(0, days * 86400))
                    meta = {"kind": "notification", "app": robot, "key": f"k{rng.randrange(500)}"}
                    messages.append(
                        (conv, robot, "**Alarm** text", "[]", json.dumps(meta), stamp(at))
                    )
        for _group in range(max(1, users // 6)):
            conv += 1
            group = rng.sample(people, min(20, users))
            members += [(conv, p, stamp(start)) for p in group]
            for _ in range(days * 4):
                at = start + timedelta(seconds=rng.uniform(0, days * 86400))
                messages.append((conv, rng.choice(group), "chat", "[]", "{}", stamp(at)))
        c.executemany(
            "INSERT INTO conversations (conversation_id, title, created_by, created_at, updated_at) "
            "VALUES (?, '', 'x', ?, ?)",
            [(i, stamp(start), stamp(start)) for i in range(1, conv + 1)],
        )
        c.executemany(
            "INSERT INTO conversation_members (conversation_id, username, joined_at) VALUES (?, ?, ?)",
            members,
        )
        messages.sort(key=lambda m: m[5])
        c.executemany(
            "INSERT INTO conversation_messages (conversation_id, author, text, refs_json, "
            "meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            messages,
        )
        c.commit()
        c.execute("ANALYZE")
    return len(messages)


def timed(store: ConversationStore, people: list[str], since: str) -> dict:
    lat = []
    for person in people:
        t0 = time.perf_counter()
        found = store.notices_for(person, since=since)
        lat.append(time.perf_counter() - t0)
    lat.sort()
    return {"p50_ms": round(statistics.median(lat) * 1000, 2),
            "p95_ms": round(lat[int(len(lat) * 0.95)] * 1000, 2), "found": len(found)}  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=300)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--per-day", type=int, default=5)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "processcraft.sqlite3"
        n = fill(path, args.users, args.days, args.per_day)
        db = Database(path)
        store = ConversationStore(db, users=None)  # runs the schema again: the store's own indexes
        people = [f"user{i}" for i in range(0, args.users, max(1, args.users // 40))]
        since = stamp(END - timedelta(days=7))
        with db.connect() as c:
            plan = [r[3] for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM conversation_messages AS message "
                "JOIN conversation_members AS member ON member.conversation_id = message.conversation_id "
                "AND member.username = 'user1' WHERE message.created_at >= '2026' AND message.author != 'user1' "
                "AND json_extract(message.meta_json, '$.kind') = 'notification'")]  # fmt: skip
        result = {"messages": n, "users": args.users, "plan": plan, **timed(store, people, since)}
        with db.connect() as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result["db_mb"] = round(path.stat().st_size / 1e6, 1)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
