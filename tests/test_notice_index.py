"""The notification feed reads only notifications, through their index (storage test 2026-10-31).

``ConversationStore.notices_for`` filters by a field inside ``meta_json``; without the partial
index ``idx_conversation_notices`` it read every message of the person's conversations on each
feed load (9.7 ms with a year of history, 0.27 ms with it, ``ci/bench/storage/json_index_bench.py``).
"""

import json

from plantcraft.db import Database
from plantcraft.messages import ConversationStore


def _store(tmp_path):
    db = Database(tmp_path / "processcraft.sqlite3")
    with db.connect() as connection:
        connection.execute(
            "CREATE TABLE workspace_users (username TEXT PRIMARY KEY, display_name TEXT, kind TEXT)"
        )
        connection.commit()
    return db, ConversationStore(db, users=None)


def test_the_feed_query_uses_the_notification_index(tmp_path):
    db, store = _store(tmp_path)
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO conversations VALUES (1, '', 'x', '2026-10-01T00:00:00.000Z', "
            "'2026-10-01T00:00:00.000Z', NULL)"
        )
        connection.executemany(
            "INSERT INTO conversation_members (conversation_id, username, joined_at) VALUES (1, ?, ?)",
            [("ana", "2026-10-01T00:00:00.000Z"), ("alarmcraft", "2026-10-01T00:00:00.000Z")],
        )
        connection.executemany(
            "INSERT INTO conversation_messages (conversation_id, author, text, meta_json, created_at) "
            "VALUES (1, ?, ?, ?, ?)",
            [
                (
                    "alarmcraft",
                    "**High** level",
                    json.dumps({"kind": "notification"}),
                    "2026-10-30T10:00:00.000Z",
                ),
                (
                    "alarmcraft",
                    "old",
                    json.dumps({"kind": "notification"}),
                    "2026-01-01T10:00:00.000Z",
                ),
                ("alarmcraft", "a chat line", "{}", "2026-10-30T11:00:00.000Z"),
            ],
        )
        connection.commit()
        names = {row[1] for row in connection.execute("PRAGMA index_list(conversation_messages)")}
        plan = " ".join(
            row[3]
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT message.message_id FROM conversation_messages AS message "
                "JOIN conversation_members AS member ON member.conversation_id = message.conversation_id "
                "AND member.username = 'ana' WHERE message.created_at >= '2026-10-24' "
                "AND message.author != 'ana' AND json_extract(message.meta_json, '$.kind') = 'notification'"
            )
        )
    assert "idx_conversation_notices" in names
    assert "idx_conversation_notices" in plan
    found = store.notices_for("ana", since="2026-10-24T00:00:00.000Z")
    assert [item["text"] for item in found] == ["**High** level"]
