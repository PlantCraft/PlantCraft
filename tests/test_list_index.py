"""Side tables of JSON lists (plantcraft.db.list_index): runs and texts found by subject.

``ResultStore.runs(subject=...)`` and ``KnowledgeStore.about(ref)`` read ``app_run_subjects``
and ``app_knowledge_subjects`` instead of parsing every row's ``subjects_json`` (storage test
2026-10-31: 246 ms -> 3.3 ms for an asset's runs among 200,000). Triggers keep the side tables
whatever writes the rows; these tests hold them to the column.
"""

import sqlite3

from plantcraft.db import Database
from plantcraft.knowledge import KnowledgeStore
from plantcraft.results import ResultStore

NOW = "2026-10-31T00:00:00.000Z"
OLD = "2026-01-01T00:00:00.000Z"


def _run(run_id, subjects, app="linkcraft"):
    return {"app": app, "id": run_id, "name": run_id, "status": "done", "trigger": "manual",
            "started_at": NOW, "finished_at": None, "subjects": subjects, "summary": "",
            "url": None}  # fmt: skip


def _side(db, table):
    with db.connect() as connection:
        return sorted(tuple(row) for row in connection.execute(f"SELECT * FROM {table}"))


def _expected(db):
    """What the side table must hold: every text item of every run's list, once."""

    with db.connect() as connection:
        return sorted(
            tuple(row)
            for row in connection.execute(
                "SELECT DISTINCT value, app_id, run_id FROM app_runs, json_each("
                "CASE WHEN json_valid(subjects_json) AND json_type(subjects_json) = 'array' "
                "THEN subjects_json ELSE '[]' END) WHERE json_each.type = 'text'"
            )
        )


def _ids(runs):
    return sorted(run["id"] for run in runs)


def test_runs_by_subject_follow_inserts_upserts_renames_and_pruning(tmp_path):
    db = Database(tmp_path / "p.sqlite3")
    store = ResultStore(db)
    store.put_runs(
        [_run("r1", ["asset:a", "asset:b"]), _run("r2", ["asset:b", "asset:b"]), _run("r3", [])],
        now=NOW, cutoff=OLD,
    )  # fmt: skip
    assert _ids(store.runs(subject="asset:b")) == ["r1", "r2"]
    assert _side(db, "app_run_subjects") == _expected(db)

    # The same run written again with other subjects (an upsert).
    store.put_runs([_run("r1", ["signal:opc:c"])], now=NOW, cutoff=OLD)
    assert _ids(store.runs(subject="asset:b")) == ["r2"]
    assert _ids(store.runs(subject="signal:opc:c")) == ["r1"]
    assert _side(db, "app_run_subjects") == _expected(db)

    store.rename_subjects({"signal:opc:c": "signal:opc:d"})  # a signal renamed in its source
    assert store.runs(subject="signal:opc:c") == []
    assert _ids(store.runs(subject="signal:opc:d")) == ["r1"]
    assert _side(db, "app_run_subjects") == _expected(db)

    # Runs not updated since the cutoff are dropped, and their subjects with them.
    store.put_runs(
        [_run("r9", ["asset:z"])], now="2026-12-31T00:00:00.000Z", cutoff="2026-12-01T00:00:00.000Z"
    )
    assert _ids(store.runs(subject="asset:z")) == ["r9"]
    assert store.runs(subject="asset:b") == []
    assert _side(db, "app_run_subjects") == _expected(db) == [("asset:z", "linkcraft", "r9")]


def test_a_broken_list_indexes_nothing_and_breaks_nothing(tmp_path):
    db = Database(tmp_path / "p.sqlite3")
    store = ResultStore(db)
    store.put_runs([_run("r1", ["asset:a"])], now=NOW, cutoff=OLD)
    with db.connect() as connection:
        connection.execute("UPDATE app_runs SET subjects_json = 'not json' WHERE run_id = 'r1'")
        connection.execute(
            "INSERT INTO app_runs (app_id, run_id, status, trigger, subjects_json, updated_at) "
            "VALUES ('x', 'r2', 'done', 'manual', '{\"a\": \"asset:a\"}', ?)",
            (NOW,),
        )
        connection.execute(
            "UPDATE app_runs SET subjects_json = '[1, \"asset:q\"]' WHERE run_id = 'r2'"
        )
        connection.commit()
    assert store.runs(subject="asset:a") == []
    assert _ids(store.runs(subject="asset:q")) == ["r2"]
    assert _side(db, "app_run_subjects") == _expected(db)


def test_a_database_from_before_fills_its_side_table_once(tmp_path):
    path = tmp_path / "p.sqlite3"
    db = Database(path)
    ResultStore(db).put_runs(
        [_run("r1", ["asset:a"]), _run("r2", ["asset:a", "asset:b"])], now=NOW, cutoff=OLD
    )
    # As a 0.5 database: no side table, no triggers, the step not run.
    with sqlite3.connect(path) as connection:
        for trigger in ("insert", "update", "delete"):
            connection.execute(f"DROP TRIGGER app_run_subjects_{trigger}")
        connection.execute("DROP TABLE app_run_subjects")
        connection.execute(
            "DELETE FROM sdk_migrations WHERE name = 'ResultStore:app_run_subjects-fill'"
        )
    store = ResultStore(Database(path))
    assert _ids(store.runs(subject="asset:a")) == ["r1", "r2"]
    assert _side(store.db, "app_run_subjects") == _expected(store.db)


def test_texts_about_a_reference_follow_their_subjects(tmp_path):
    db = Database(tmp_path / "p.sqlite3")
    store = KnowledgeStore(db)
    text = {"app": "linkcraft", "kind": "loop", "title": "t", "text": "x"}
    store.put(
        [{**text, "ref": "loop:1", "subjects": ["asset:a"]}, {**text, "ref": "asset:a", "subjects": []}],
        now=NOW, cutoff=OLD,
    )  # fmt: skip
    assert [item["ref"] for item in store.about("asset:a")] == ["asset:a", "loop:1"]
    store.put([{**text, "ref": "loop:1", "subjects": ["asset:b"]}], now=NOW, cutoff=OLD)
    assert [item["ref"] for item in store.about("asset:a")] == ["asset:a"]
    assert [item["ref"] for item in store.about("asset:b")] == ["loop:1"]
    store.delete("linkcraft", ["loop:1"])
    assert store.about("asset:b") == []
    assert _side(db, "app_knowledge_subjects") == []
