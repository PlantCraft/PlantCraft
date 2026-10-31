"""The flood count reads the last minutes of the outbox, not 30 days of it (storage test
2026-10-31: 15 ms -> 0.09 ms a person with 300,000 rows, each notifier cycle asks per person)."""

import json

from plantcraft_sdk.server.store import Database

from alarmcraft.alarms.notices import NoticeStore


def test_the_flood_count_searches_the_window_and_counts_right(tmp_path):
    store = NoticeStore(Database(tmp_path / "alarmcraft.sqlite3"))
    rows = [
        # alarm, at, recipients, status
        ("a1", "2026-10-31T11:55:00+00:00", ["user:x", "user:y"], "sent"),
        ("a1", "2026-10-31T11:57:00+00:00", ["user:x"], "sent"),  # the same alarm again
        ("a2", "2026-10-31T11:58:00+00:00", ["user:x"], "digest"),  # waits for the summary
        ("a3", "2026-10-31T11:59:00+00:00", ["user:y"], "sent"),
        ("a4", "2026-10-30T11:59:00+00:00", ["user:x"], "sent"),  # before the window
    ]
    with store._connect() as connection:
        connection.executemany(
            "INSERT INTO outbox (alarm_id, name, policy_id, event, priority, at, recipients_json,"
            " status) VALUES (?, 'n', 'p', 'raised', 'high', ?, ?, ?)",
            [(a, at, json.dumps(who), status) for a, at, who, status in rows],
        )
        connection.commit()
        plan = " ".join(
            row[3]
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(DISTINCT +alarm_id) FROM outbox,"
                " json_each(outbox.recipients_json) WHERE json_each.value = 'user:x'"
                " AND at >= '2026-10-31T11:50:00+00:00' AND event = 'raised'"
                " AND status NOT IN ('digest', 'chatter', 'dropped')"
            )
        )
    assert "outbox_at" in plan
    assert store.raised_for("user:x", "2026-10-31T11:50:00+00:00") == 1
    assert store.raised_for("user:y", "2026-10-31T11:50:00+00:00") == 2
