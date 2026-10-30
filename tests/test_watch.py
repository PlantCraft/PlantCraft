"""The suite watch (plantcraft.watch): incidents from the installer's status, told in Messages."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from plantcraft.auth.users import UserStore
from plantcraft.db import Database
from plantcraft.messages import ConversationStore
from plantcraft.watch import SYSTEM_USER, SuiteWatch

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


class FakeDesk:
    """What OperationsDesk reads from data/installer/status, held in memory."""

    def __init__(self):
        self.files: dict[str, object] = {}
        self.backups: list[dict] = []
        self.running = None
        self.enabled = True

    def read(self, name):
        return self.files.get(name)

    def overview(self):
        return {
            "running": self.running,
            "backups": self.backups,
            "drill": self.files.get("drill.json"),
            "schedule": {"enabled": self.enabled},
        }


class World:
    def __init__(self, tmp_path):
        self.now = NOW
        db = Database(tmp_path / "w.sqlite3")
        self.db = db
        self.users = UserStore(db)
        self.users.upsert_user("ana", "Ana", "Operations")
        self.users.upsert_user("bia", "Bia", "Process")
        self.messages = ConversationStore(db, self.users)
        self.desk = FakeDesk()
        self.admins = ["ana"]
        self.queues = {}
        self.backup(hours_ago=2)
        self.services(processcraft="healthy", histcraft="healthy", dashcraft="healthy")
        self.watch = self.make()

    def make(self):
        return SuiteWatch(
            self.db, self.users, self.messages, self.desk, lambda: self.admins,
            queues=lambda: self.queues, clock=lambda: self.now,
        )  # fmt: skip

    def backup(self, hours_ago):
        at = (self.now - timedelta(hours=hours_ago)).isoformat()
        self.desk.backups = [{"name": "b", "state": "ok", "created_at": at}]

    def services(self, free_pct=50.0, **health):
        services = []
        for name, value in health.items():
            state = value if value in {"exited", "created", "restarting"} else "running"
            services.append({"service": name, "state": state, "exit_code": 1,
                             "health": value if state == "running" else "", "restarts": 0})  # fmt: skip
        self.desk.files["metrics.json"] = {
            "at": self.now.isoformat(),
            "services": services,
            "disk": {"free_pct": free_pct, "free_bytes": 40 * 2**30},
            "error": None,
        }

    def ticks(self, count=1, seconds=30, **health):
        posted = []
        for _ in range(count):
            self.now += timedelta(seconds=seconds)
            if health:
                self.services(**health)
            else:
                self.desk.files["metrics.json"]["at"] = self.now.isoformat()
            posted += self.watch.tick()
        return posted

    def conversation(self):
        conversation_id = self.watch.store.get("conversation_id")
        return [m["text"] for m in self.messages.messages(conversation_id, limit=50)]


@pytest.fixture()
def world(tmp_path):
    return World(tmp_path)


def test_a_service_down_for_three_ticks_opens_one_incident_and_its_recovery(world):
    assert world.ticks(3) == []
    down = {"processcraft": "healthy", "histcraft": "exited", "dashcraft": "healthy"}
    assert world.ticks(2, **down) == []  # two bad ticks: not yet
    posted = world.ticks(1, **down)
    assert len(posted) == 1 and "histcraft" in posted[0] and "exited" in posted[0]
    assert world.ticks(5, **down) == []  # still down: no repeat
    back = world.ticks(1, processcraft="healthy", histcraft="healthy", dashcraft="healthy")
    assert len(back) == 1 and "histcraft" in back[0] and "3 min" in back[0]
    assert world.watch.overview()["open"] == []
    assert world.conversation() == [*posted, *back]
    conversation = world.messages.get(world.watch.store.get("conversation_id"))
    assert {m["username"] for m in conversation["members"]} == {SYSTEM_USER, "ana"}
    assert world.users.get_user(SYSTEM_USER)["kind"] == "system"


def test_a_flapping_service_is_told_at_most_every_ten_minutes(world):
    up = {"processcraft": "healthy", "histcraft": "healthy", "dashcraft": "healthy"}
    down = {**up, "dashcraft": "unhealthy"}
    assert len(world.ticks(3, **down)) == 1
    assert len(world.ticks(1, **up)) == 1
    # Down again two minutes later: recorded, not posted, and so is its recovery.
    assert world.ticks(3, **down) == []
    assert world.ticks(1, **up) == []
    assert len(world.watch.store.recent()) == 2
    world.now += timedelta(minutes=10)
    assert len(world.ticks(3, **down)) == 1


def test_a_restart_does_not_repeat_or_forget_an_incident(world):
    down = {"processcraft": "healthy", "histcraft": "exited", "dashcraft": "healthy"}
    assert len(world.ticks(3, **down)) == 1
    world.watch = world.make()  # PlantCraft restarted
    assert world.ticks(4, **down) == []
    assert (
        len(world.ticks(1, processcraft="healthy", histcraft="healthy", dashcraft="healthy")) == 1
    )


def test_a_slow_start_and_a_crash_loop(world):
    starting = {"processcraft": "healthy", "histcraft": "starting", "dashcraft": "healthy"}
    assert world.ticks(9, **starting) == []
    assert "still starting" in world.ticks(1, **starting)[0]
    world.ticks(1, processcraft="healthy", histcraft="healthy", dashcraft="healthy")
    world.now += timedelta(minutes=15)
    posted = []
    for restarts in (1, 2, 3):
        world.services(processcraft="healthy", histcraft="healthy", dashcraft="healthy")
        world.desk.files["metrics.json"]["services"][2]["restarts"] = restarts
        world.now += timedelta(seconds=30)
        world.desk.files["metrics.json"]["at"] = world.now.isoformat()
        posted += world.watch.tick()
    assert len(posted) == 1 and "restarted 3 times" in posted[0] and "dashcraft" in posted[0]


def test_operations_hold_the_services_still(world):
    world.desk.running = {"action": "backup", "started_at": world.now.isoformat()}
    assert world.ticks(5, processcraft="healthy", histcraft="exited", dashcraft="healthy") == []
    world.desk.running = None
    assert len(world.ticks(3, processcraft="healthy", histcraft="exited", dashcraft="healthy")) == 1


def test_a_silent_installer_is_told_and_holds_the_services(world):
    world.ticks(1)
    world.now += timedelta(minutes=4)
    posted = [*world.watch.tick(), *world.watch.tick(), *world.watch.tick()]
    assert len(posted) == 1 and "installer" in posted[0].lower()
    assert world.watch.overview()["held"] is True


def test_low_disk_old_backups_and_a_failed_drill(world):
    posted = world.ticks(1, free_pct=8.0, processcraft="healthy")
    assert len(posted) == 1 and "8.0 % free" in posted[0]
    # Hysteresis: 11 % is not yet back.
    assert world.ticks(1, free_pct=11.0, processcraft="healthy") == []
    assert len(world.ticks(1, free_pct=13.0, processcraft="healthy")) == 1
    world.backup(hours_ago=27)
    posted = world.ticks(1, processcraft="healthy")
    assert len(posted) == 1 and "27 h" in posted[0]
    world.desk.files["drill.json"] = {"state": "failed", "problems": ["histcraft never healthy"]}
    posted = world.ticks(1, processcraft="healthy")
    assert len(posted) == 1 and "histcraft never healthy" in posted[0]


def test_no_backup_yet_waits_twenty_six_hours_from_the_first_look(world):
    world.desk.backups = []
    assert world.ticks(1) == []
    world.now += timedelta(hours=26, minutes=1)
    assert "no good backup" in world.ticks(1)[0]


def test_updates_are_announced_once_and_old_ones_not_at_all(world):
    world.desk.files["update.json"] = {
        "at": world.now.isoformat(), "state": "returned", "from": "0.2.0", "to": "0.3.0",
        "message": "processcraft never healthy",
    }  # fmt: skip
    posted = world.ticks(1)
    assert len(posted) == 1 and "0.3.0" in posted[0] and "0.2.0" in posted[0]
    assert world.ticks(2) == []
    world.desk.files["update.json"] = {"at": (world.now - timedelta(days=3)).isoformat(),
                                       "state": "ok", "to": "0.1.0"}  # fmt: skip
    assert world.ticks(1) == []


def test_new_admins_join_the_conversation_and_nobody_to_tell_still_records(world):
    world.admins = []
    world.ticks(1, free_pct=5.0, processcraft="healthy")
    assert len(world.watch.overview()["open"]) == 1
    assert world.watch.store.get("conversation_id") is None
    world.admins = ["ana"]
    world.ticks(1, free_pct=50.0, processcraft="healthy")  # not told, so no recovery either
    world.ticks(1, free_pct=5.0, processcraft="healthy")
    world.admins = ["ana", "bia"]
    world.ticks(1, free_pct=50.0, processcraft="healthy")
    conversation = world.messages.get(world.watch.store.get("conversation_id"))
    assert {m["username"] for m in conversation["members"]} == {SYSTEM_USER, "ana", "bia"}


def test_nothing_is_watched_without_an_installer(tmp_path):
    world = World(tmp_path)
    world.desk.files.clear()
    world.desk.backups = []
    assert world.watch.tick() == []
    assert world.watch.overview()["watching"] is False


def test_an_uninstalled_app_ends_its_incident_quietly(world):
    assert len(world.ticks(3, processcraft="healthy", dashcraft="exited")) == 1
    assert world.ticks(1, processcraft="healthy") == []
    assert world.watch.overview()["open"] == []


def test_the_disk_forecast_warns_a_month_before_it_fills(world):
    from plantcraft.watch import disk_forecast

    gib = 2**30
    free = 40 * gib
    posted = []
    # A day and a half at 2 GiB lost a day: 40 GiB last 20 days, under the 30-day warning.
    for _ in range(37):
        world.now += timedelta(hours=1)
        free -= gib // 12
        world.services(processcraft="healthy")
        world.desk.files["metrics.json"]["disk"]["free_bytes"] = free
        posted += world.watch.tick()
    assert any("Disk forecast" in text and "fills in about" in text for text in posted)
    forecast = world.watch.overview()["disk_forecast"]
    assert round(forecast["bytes_per_day"] / gib) == 2 and 15 < forecast["days_left"] < 20
    # A disk that stops shrinking is back to normal.
    for _ in range(24 * 7):
        world.now += timedelta(hours=1)
        world.services(processcraft="healthy")
        world.desk.files["metrics.json"]["disk"]["free_bytes"] = free
        world.watch.tick()
    assert "disk_trend" not in world.watch.store.open_incidents()
    assert disk_forecast([["2026-10-21T00:00:00+00:00", 1]], 1) is None


def test_a_queue_that_does_not_drain_is_told_and_its_recovery(world):
    world.queues = {"linkcraft": {"queued": 40, "running": 4, "workers": 4, "delay_seconds": 600}}
    assert world.ticks(3) == []  # waiting 10 min: the queue still drains
    world.queues["linkcraft"].update(queued=900, delay_seconds=45 * 60)
    assert world.ticks(1) == []  # one tick: not yet
    posted = world.ticks(1)
    assert len(posted) == 1 and "Queue of linkcraft" in posted[0]
    assert "900 items waiting, the oldest for 45 min; 4 running on 4 workers" in posted[0]
    assert world.ticks(3) == []  # still stuck: no repeat
    world.queues["linkcraft"].update(queued=0, delay_seconds=0)
    back = world.ticks(1)
    assert len(back) == 1 and "Queue of linkcraft is back to normal" in back[0]


def test_a_queue_holds_still_during_operations_and_goes_with_its_app(world):
    world.queues = {"modelcraft": {"queued": 5, "running": 0, "workers": 0, "delay_seconds": 7200}}
    world.desk.running = {"action": "backup", "started_at": world.now.isoformat()}
    assert world.ticks(3) == []
    world.desk.running = None
    assert len(world.ticks(2)) == 1
    world.queues = {}
    assert world.ticks(1) == []
    assert world.watch.overview()["open"] == []


def test_a_broken_queue_reader_leaves_the_other_checks(world):
    def broken():
        raise RuntimeError("recorder gone")

    world.queues = None
    world.watch.queues = broken
    down = {"processcraft": "exited", "histcraft": "healthy", "dashcraft": "healthy"}
    assert len(world.ticks(3, **down)) == 1


def test_every_worker_shows_what_the_ticking_watch_saw(world):
    # several PlantCraft workers: only one watch ticks, any of them serves the Operations page
    world.ticks(1)
    other = world.make()
    seen = other.overview()
    assert seen["watching"] is True and seen["at"].startswith("2026-10-21T12:00:30")
    assert {item["key"] for item in seen["checks"]} >= {"installer", "docker"}


def test_each_incident_is_an_event_of_the_platform(tmp_path):
    from plantcraft.events import EventStore
    from plantcraft.events.catalog import platform_catalog

    world = World(tmp_path)
    world.events = EventStore(world.db)
    world.watch = SuiteWatch(
        world.db, world.users, world.messages, world.desk, lambda: world.admins,
        queues=lambda: world.queues, events=world.events, clock=lambda: world.now,
    )  # fmt: skip
    down = {"processcraft": "healthy", "histcraft": "exited", "dashcraft": "healthy"}
    world.ticks(3, **down)
    world.ticks(1, processcraft="healthy", histcraft="healthy", dashcraft="healthy")
    events = world.events.listing(kind="processcraft.service.down")
    assert [(e["phase"], e["severity"], e["key"]) for e in events] == [
        ("start", "critical", "service:histcraft"),
        ("end", "ok", "service:histcraft"),
    ]
    assert events[0]["subject"] == "app:processcraft" and events[0]["category"] == "system"
    # Every kind the watch writes is in the platform's catalog.
    declared = {item["kind"] for item in platform_catalog()}
    assert "processcraft.service.down" in declared and "processcraft.update.finished" in declared


def test_compute_tasks_with_no_worker_are_told_once_and_their_recovery(world):
    waiting = [{"app": "linkcraft", "version": "0.5.0", "queued": 12, "oldest_queued_at": "x"}]
    world.watch.compute = lambda: waiting
    posted = world.ticks(1)
    assert len(posted) == 1 and "Compute for linkcraft" in posted[0]
    assert (
        "12 tasks wait and no compute worker online runs them (version 0.5.0, environment "
        "standard, size small)" in posted[0]
    )
    assert world.ticks(2) == []  # still waiting: no repeat
    waiting.clear()
    back = world.ticks(1)
    assert len(back) == 1 and "Compute for linkcraft is back to normal" in back[0]
