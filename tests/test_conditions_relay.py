"""The conditions an app without an app key reports in its metrics (the Historian), written as
that app's events by the monitor (plantcraft.events.conditions)."""

from __future__ import annotations

from plantcraft.db import Database
from plantcraft.events import EventStore
from plantcraft.events.conditions import ConditionRelay
from plantcraft.watch.recorder import HealthRecorder
from tests.test_health_signals import NOW
from tests.test_watch import FakeDesk

CATALOG = [
    {"name": "source.disconnected", "title": "Source disconnected", "severity": "critical",
     "category": "data", "phase": "interval"},
    {"name": "point.bad", "title": "Point without good values", "severity": "warning",
     "category": "data", "phase": "interval"},
    {"name": "archive.compacted", "title": "Archive compacted"},
]  # fmt: skip


def _relay(tmp_path):
    db = Database(tmp_path / "platform.sqlite3")
    events = EventStore(db)
    return ConditionRelay(db, events), events, db


def _metrics(*conditions, catalog=CATALOG):
    answer = {"app": "histcraft", "conditions": list(conditions)}
    if catalog is not None:
        answer["events"] = catalog
    return {"histcraft": answer}


def _written(events):
    return [
        (item["kind"], item["phase"], item["key"], item["severity"], item["subject"])
        for item in events.listing(limit=50)
    ]


def test_a_condition_starts_when_reported_and_ends_when_gone(tmp_path):
    relay, events, _ = _relay(tmp_path)
    down = {"name": "source.disconnected", "key": "source:opc-1", "subject": "source:opc-1",
            "summary": "opc-1: connection refused"}  # fmt: skip
    assert relay.apply(_metrics(down)) == {"opened": 1, "closed": 0}
    # The catalog is the app's: Alarms offers its events in rules.
    assert [spec["name"] for spec in events.catalog("histcraft")] == [
        "source.disconnected",
        "point.bad",
        "archive.compacted",
    ]
    assert relay.apply(_metrics(down)) == {"opened": 0, "closed": 0}  # still open: once
    assert relay.apply(_metrics()) == {"opened": 0, "closed": 1}
    assert _written(events) == [
        ("histcraft.source.disconnected", "start", "source:opc-1", "critical", "source:opc-1"),
        ("histcraft.source.disconnected", "end", "source:opc-1", "ok", "source:opc-1"),
    ]
    first = events.listing(limit=5)[0]
    assert first["summary"] == "opc-1: connection refused" and first["category"] == "data"
    assert first["source"] == "histcraft"


def test_an_app_that_did_not_answer_keeps_its_conditions(tmp_path):
    relay, events, db = _relay(tmp_path)
    bad = {"name": "point.bad", "key": "point:7", "severity": "critical"}
    relay.apply(_metrics(bad))
    assert relay.apply({}) == {"opened": 0, "closed": 0}
    # Metrics without "conditions" (the app could not read them): nothing closes either.
    assert relay.apply({"histcraft": {"app": "histcraft", "events": CATALOG}})["closed"] == 0
    # A restart: the stored conditions are still open, no second start.
    again = ConditionRelay(db, events)
    assert again.apply(_metrics(bad)) == {"opened": 0, "closed": 0}
    assert list(again.open_conditions("histcraft")) == ["point:7"]
    assert [item[1:4] for item in _written(events)] == [("start", "point:7", "critical")]


def test_an_undeclared_or_instant_condition_is_left_out(tmp_path):
    relay, events, _ = _relay(tmp_path)
    answer = _metrics(
        {"name": "collector.typo", "key": "x"},
        {"name": "archive.compacted", "key": "y"},
        {"name": "point.bad", "key": "point:1", "subject": "not a ref"},
    )
    assert relay.apply(answer) == {"opened": 1, "closed": 0}
    [(kind, _, key, severity, subject)] = _written(events)
    assert (kind, key, severity, subject) == ("histcraft.point.bad", "point:1", "warning",
                                              "app:histcraft")  # fmt: skip


def test_the_recorder_hands_the_apps_conditions_each_minute(tmp_path):
    relay, events, _ = _relay(tmp_path)
    servers = {"processcraft": {"logs": {}, "requests": {}}}
    servers.update(_metrics({"name": "point.bad", "key": "point:3"}))
    recorder = HealthRecorder(
        FakeDesk(), lambda series: {"written": 0}, lambda: servers, clock=lambda: NOW,
        conditions=relay.apply,
    )  # fmt: skip
    recorder.tick()
    assert list(recorder.reported) == ["histcraft"]
    assert [item[2] for item in _written(events)] == ["point:3"]


def test_what_a_keyless_app_adds_reaches_the_registry(tmp_path):
    from plantcraft.apps.contributions import ContributionStore

    db = Database(tmp_path / "platform.sqlite3")
    registry = ContributionStore(db)
    relay = ConditionRelay(db, EventStore(db), registry)
    body = {
        "app": "histcraft",
        "version": "0.4.0",
        "contributes": {"widgets": [{"id": "sources", "title": "Sources"}], "hologram": []},
        "series": [],
    }
    relay.apply({"histcraft": {"app": "histcraft", "contributions": body}})
    stored = registry.get("histcraft")
    assert stored["version"] == "0.4.0" and stored["unknown"] == ["hologram"]
    assert stored["contributes"]["widgets"][0]["id"] == "sources"
    # A refused body leaves what was there.
    relay.apply({"histcraft": {"contributions": {"contributes": {"widgets": "x"}}}})
    assert registry.get("histcraft")["contributes"]["widgets"][0]["id"] == "sources"


class FakeNotifications:
    def __init__(self):
        self.sent: list[dict] = []
        self.resolved: list[tuple] = []

    def notify(self, app_id, app_name, **fields):
        self.sent.append({"app": app_id, "name": app_name, **fields})
        return {"delivered": [], "email_queued": 0, "unknown": []}

    def resolve(self, app_id, key, note=""):
        self.resolved.append((app_id, key, note))
        return {"key": key}


def test_the_owners_of_a_failing_source_are_told_with_an_email_and_settled_after(tmp_path):
    db = Database(tmp_path / "platform.sqlite3")
    events = EventStore(db)
    told = FakeNotifications()
    relay = ConditionRelay(
        db, events, notifications=lambda: told, app_names=lambda: {"histcraft": "Historian"}
    )
    down = {"name": "source.disconnected", "key": "source:opc-1", "subject": "source:opc-1",
            "summary": "Source OPC 1 disconnected: refused",
            "payload": {"source": "opc-1", "owners": ["group:automation", "User:Ana", "admins"],
                        "contact": "Automation team,\n ext. 4321"}}  # fmt: skip
    relay.apply(_metrics(down))
    [sent] = told.sent
    assert sent["app"] == "histcraft" and sent["name"] == "Historian"
    # Only user:/group: references, and an email beside the message in Messages.
    assert sent["recipients"] == ["group:automation", "user:ana"]
    assert sent["email"] is True and sent["priority"] == "critical"
    assert sent["key"] == "condition:source:opc-1" and sent["url"] == "/hist/sources/opc-1"
    assert "Automation team, ext. 4321" in sent["text"] and sent["refs"] == ["source:opc-1"]
    relay.apply(_metrics(down))
    assert len(told.sent) == 1  # once while it lasts
    # A restart keeps who was told: the end settles it.
    again = ConditionRelay(db, events, notifications=lambda: told)
    again.apply(_metrics())
    [(app, key, note)] = told.resolved
    assert (app, key) == ("histcraft", "condition:source:opc-1") and "Back to normal" in note


def test_a_condition_without_owners_tells_nobody(tmp_path):
    db = Database(tmp_path / "platform.sqlite3")
    told = FakeNotifications()
    relay = ConditionRelay(db, EventStore(db), notifications=lambda: told)
    relay.apply(_metrics({"name": "point.bad", "key": "point:7", "payload": {"owners": []}}))
    relay.apply(_metrics())
    assert told.sent == [] and told.resolved == []
