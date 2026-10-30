"""The suite's health as signals (plantcraft.watch.recorder): what is written to "System"."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from plantcraft.watch.recorder import HealthRecorder, ServerMetrics, server_urls
from tests.test_watch import FakeDesk

NOW = datetime(2026, 10, 22, 23, 0, tzinfo=timezone.utc)


class Historian:
    """``POST /api/v1/data/system``: keeps what it is sent, or fails while ``down``."""

    def __init__(self):
        self.series: dict[str, dict] = {}
        self.down = False
        self.calls = 0

    def write(self, series):
        self.calls += 1
        if self.down:
            raise RuntimeError("The Historian could not be reached")
        for item in series:
            kept = self.series.setdefault(item["signal"], {**item, "t": [], "v": []})
            kept["t"] += item["t"]
            kept["v"] += item["v"]
        return {"written": sum(len(item["v"]) for item in series), "errors": []}


class World:
    def __init__(self):
        self.now = NOW
        self.desk = FakeDesk()
        self.historian = Historian()
        self.servers = {"processcraft": self.counters(0, 0, 12.5)}
        self.recorder = HealthRecorder(
            self.desk, self.historian.write, lambda: self.servers, clock=lambda: self.now
        )

    @staticmethod
    def counters(errors, warnings, p95):
        return {"logs": {"error": errors, "warning": warnings}, "requests": {"p95_ms": p95}}

    def metrics(self, **services):
        self.desk.files["metrics.json"] = {
            "at": self.now.isoformat(),
            "error": None,
            "disk": {"free_bytes": 50 * 2**30, "free_pct": 25.0},
            "services": [
                {"service": name, "state": state, "health": health, "cpu_pct": 3.5,
                 "mem_bytes": 300 * 2**20, "mem_pct": 15.0, "restarts": 1}
                for name, (state, health) in services.items()
            ],
        }  # fmt: skip

    def tick(self, minutes=1):
        self.now += timedelta(minutes=minutes)
        if "metrics.json" in self.desk.files:
            self.desk.files["metrics.json"]["at"] = self.now.isoformat()
        return self.recorder.tick()

    def values(self, signal):
        return self.historian.series[f"system:{signal}"]["v"]


def test_every_service_disk_and_backup_becomes_a_signal():
    world = World()
    world.metrics(processcraft=("running", "healthy"), linkcraft=("exited", ""),
                  **{"histcraft-db": ("running", "unhealthy")})  # fmt: skip
    world.desk.backups = [
        {"name": "a", "state": "ok", "created_at": (NOW - timedelta(hours=5)).isoformat()},
        {"name": "b", "state": "failed", "created_at": (NOW - timedelta(hours=1)).isoformat()},
    ]
    world.desk.files["drill.json"] = {"state": "ok"}
    assert world.tick() > 0
    assert world.values("processcraft.up") == [1.0]
    assert world.values("linkcraft.up") == [0.0]
    assert world.values("histcraft-db.up") == [0.0]  # running but its health check fails
    assert world.values("processcraft.mem_mb") == [300.0]
    assert world.values("processcraft.cpu_pct") == [3.5]
    assert world.values("processcraft.restarts") == [1.0]
    assert world.values("processcraft.latency_ms") == [12.5]
    assert world.values("host.disk_free_gb") == [50.0]
    assert world.values("host.disk_free_pct") == [25.0]
    assert world.values("backup.age_h") == [5.02]
    assert world.values("backup.ok") == [0.0]  # the newest backup failed
    assert world.values("backup.drill_ok") == [1.0]
    up = world.historian.series["system:processcraft.up"]
    assert (up["name"], up["low"], up["high"]) == ("processcraft up", 0.0, 1.0)
    assert world.historian.series["system:processcraft.mem_mb"]["unit"] == "MB"
    # errors and warnings are rates: nothing until a second reading
    assert "system:processcraft.errors" not in world.historian.series


def test_errors_and_warnings_are_per_minute_and_survive_a_restart():
    world = World()
    world.tick()
    world.servers["processcraft"] = world.counters(10, 4, 20.0)
    world.tick(minutes=2)
    assert world.values("processcraft.errors") == [5.0]
    assert world.values("processcraft.warnings") == [2.0]
    world.servers["processcraft"] = world.counters(3, 0, 20.0)  # restarted: counts from 0
    world.tick()
    assert world.values("processcraft.errors") == [5.0, 3.0]


def test_a_reported_queue_becomes_signals_and_is_kept_for_the_watch():
    world = World()
    queue = {"queued": 120, "running": 4, "workers": 4, "delay_seconds": 1800.0}
    world.servers["linkcraft"] = {**world.counters(0, 0, 8.0), "queue": queue}
    world.tick()
    assert world.values("linkcraft.queue_items") == [120.0]
    assert world.values("linkcraft.queue_wait_min") == [30.0]
    assert world.historian.series["system:linkcraft.queue_wait_min"]["unit"] == "min"
    assert "system:processcraft.queue_items" not in world.historian.series
    assert world.recorder.queues == {"linkcraft": queue}
    del world.servers["linkcraft"]
    world.tick()
    assert world.recorder.queues == {}


def test_values_wait_while_the_historian_is_down_and_go_on_its_return():
    world = World()
    world.metrics(processcraft=("running", "healthy"))
    world.historian.down = True
    for _ in range(3):
        assert world.tick() == 0
    assert world.recorder.last["error"] and world.recorder.last["waiting"] > 0
    world.historian.down = False
    world.tick()
    assert world.values("processcraft.up") == [1.0, 1.0, 1.0, 1.0]
    times = world.historian.series["system:processcraft.up"]["t"]
    assert times == sorted(times) and len(set(times)) == 4
    assert world.recorder.pending == {} and world.recorder.last["error"] is None


def test_at_most_a_day_waits():
    world = World()
    world.historian.down = True
    for _ in range(24 * 60 + 30):
        world.tick()
    assert len(world.recorder.pending["processcraft.latency_ms"]) == 24 * 60


def test_stale_installer_writes_no_made_up_values():
    world = World()
    world.metrics(processcraft=("running", "healthy"))
    world.now += timedelta(minutes=10)
    world.recorder.tick()  # metrics.json is 10 minutes old: the installer stopped
    assert "system:processcraft.up" not in world.historian.series
    assert world.values("processcraft.latency_ms") == [12.5]  # the server itself answered


def test_nothing_to_read_writes_nothing():
    world = World()
    world.servers = {}
    assert world.tick() == 0 and world.historian.calls == 0


def test_server_metrics_with_an_ops_token():
    seen = []

    def answer(request):
        seen.append(request)
        if request.url.host == "linkcraft":
            return httpx.Response(200, json={"requests": {"p95_ms": 8}})
        return httpx.Response(503)

    class Issuer:
        def issue(self, subject, **claims):
            self.claims = {"sub": subject, **claims}
            return "token", 0

    issuer = Issuer()
    reader = ServerMetrics(
        issuer,
        lambda: {"requests": {"p95_ms": 1}},
        urls={"linkcraft": "http://linkcraft:8140/link", "histcraft": "http://histcraft:8100/hist"},
        running=lambda: {"linkcraft", "histcraft"},
        http=httpx.Client(transport=httpx.MockTransport(answer)),
    )
    found = reader()
    assert set(found) == {"processcraft", "linkcraft"}
    assert str(seen[0].url) == "http://linkcraft:8140/link/api/ops/metrics"
    assert seen[0].headers["authorization"] == "Bearer token"
    assert issuer.claims["scope"] == "ops" and issuer.claims["audience"] == "histcraft"
    # a service Docker does not run is not called
    reader.running = lambda: {"histcraft"}
    seen.clear()
    reader()
    assert [request.url.host for request in seen] == ["histcraft"]


def test_server_urls_from_the_environment():
    urls = server_urls("linkcraft=,mine=http://mine:9000/mine/,bad=ftp://x")
    assert "linkcraft" not in urls and urls["mine"] == "http://mine:9000/mine"
    assert "bad" not in urls and urls["histcraft"] == "http://histcraft:8100/hist"
