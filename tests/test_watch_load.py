"""Load alerts of the suite watch (plantcraft.watch.load) and the machine's load
(plantcraft.apps.host_usage)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from plantcraft.apps.host_usage import HostSampler, cpu_times, load_pct, memory, nano_cpus
from plantcraft.watch.load import LoadLimits
from tests.test_watch import World


class LoadWorld(World):
    def make(self):
        from plantcraft.watch import SuiteWatch

        self.rates: dict[str, float] = {}
        return SuiteWatch(
            self.db, self.users, self.messages, self.desk, lambda: self.admins,
            queues=lambda: self.queues, error_rates=lambda: self.rates, clock=lambda: self.now,
        )  # fmt: skip

    def load(self, minutes, *, cpu=10.0, mem=20.0, host_cpu=30.0, host_mem=40.0):
        """``minutes`` of ticks (30 s each) with the Historian at ``cpu`` and ``mem``."""

        posted = []
        for _ in range(int(minutes * 2)):
            self.now += timedelta(seconds=30)
            self.services(processcraft="healthy", histcraft="healthy", dashcraft="healthy")
            metrics = self.desk.files["metrics.json"]
            for item in metrics["services"]:
                item.update(cpu_load_pct=5.0, mem_pct=10.0)
                if item["service"] == "histcraft":
                    item.update(cpu_load_pct=cpu, mem_pct=mem)
            metrics["host"] = {"cpus": 8, "cpu_pct": host_cpu, "mem_pct": host_mem}
            posted += self.watch.tick()
        return posted


@pytest.fixture()
def world(tmp_path):
    return LoadWorld(tmp_path)


def test_a_load_held_five_minutes_warns_once_then_says_when_it_is_back(world):
    assert world.load(4.5, cpu=86) == []  # a peak shorter than 5 minutes says nothing
    posted = world.load(0.5, cpu=86)
    assert len(posted) == 1 and posted[0].startswith("🟠")
    assert "histcraft" in posted[0] and "CPU at 86 % (limit 80 %)" in posted[0]
    assert world.load(10, cpu=88) == []  # still high: no repeat
    # Back to 77 %: under 80 but not 5 points under, the incident stays open.
    assert world.load(2, cpu=77) == []
    back = world.load(0.5, cpu=60)
    assert len(back) == 1 and back[0].startswith("✅")
    events = world.watch.store.recent()
    assert [item["check_key"] for item in events] == ["load:histcraft"]


def test_critical_is_its_own_incident_and_the_machine_is_watched(world):
    posted = world.load(5, cpu=97, host_mem=96)
    keys = sorted(item["check_key"] for item in world.watch.store.open_incidents().values())
    assert keys == ["load:histcraft", "load:host", "load_critical:histcraft", "load_critical:host"]
    assert sum(text.startswith("🔴") for text in posted) == 2
    assert any("machine" in text and "memory at 96 %" in text for text in posted)


def test_error_rates_have_two_levels(world):
    world.rates = {"linkcraft": 3.0}
    posted = world.load(5)
    assert len(posted) == 1 and "3.0 errors a minute (limit 2.0)" in posted[0]
    world.rates = {"linkcraft": 12.0}
    posted = world.load(5)
    assert len(posted) == 1 and posted[0].startswith("🔴") and "limit 5.0" in posted[0]


def test_limits_are_kept_validated_and_can_turn_the_alerts_off(world):
    assert world.watch.limits() == LoadLimits()
    changed = world.watch.set_limits({"cpu_warning": 70, "minutes": 2})
    assert changed.cpu_warning == 70 and changed.minutes == 2 and changed.cpu_critical == 95
    assert len(world.load(2, cpu=72)) == 1
    for bad in ({"cpu_warning": 99, "cpu_critical": 90}, {"memory_warning": 5},
                {"minutes": 0}, {"errors_warning": 0}):  # fmt: skip
        with pytest.raises(ValueError):
            world.watch.set_limits(bad)
    world.watch.set_limits({"enabled": False})
    # Off: the open incident ends without a word and nothing new opens.
    assert world.load(6, cpu=99) == []
    assert world.watch.store.open_incidents() == {}


def test_a_backup_holds_the_load_checks_still(world):
    world.desk.running = {"action": "backup", "started_at": world.now.isoformat()}
    assert world.load(6, cpu=99) == []
    assert world.watch.store.open_incidents() == {}


def test_malformed_limits_fall_back_to_the_defaults():
    assert LoadLimits.from_dict("nonsense") == LoadLimits()
    assert LoadLimits.from_dict({"cpu_warning": "high", "enabled": "yes", "x": 1}) == LoadLimits()


# The machine and each container's share of its CPUs --------------------------------------

STAT_1 = "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 1 1 1\n"
STAT_2 = "cpu  200 0 200 1400 200 0 0 0 0 0\n"
MEMINFO = "MemTotal:       16384000 kB\nMemFree:  1000 kB\nMemAvailable:    4096000 kB\n"


def test_proc_readers():
    assert cpu_times(STAT_1) == (1000, 800)
    assert cpu_times("intr 1 2 3") is None and cpu_times("cpu  a b c d") is None
    assert memory(MEMINFO) == {"total_bytes": 16384000 * 1024, "available_bytes": 4096000 * 1024}
    assert memory("MemTotal: 0 kB\nMemAvailable: 0 kB") is None and memory("") is None


def test_the_sampler_measures_cpu_between_two_reads(tmp_path):
    (tmp_path / "stat").write_text(STAT_1)
    (tmp_path / "meminfo").write_text(MEMINFO)
    (tmp_path / "loadavg").write_text("2.50 1.0 0.5 1/100 42\n")
    sampler = HostSampler(tmp_path)
    first = sampler.sample()
    assert first["cpu_pct"] is None and first["mem_pct"] == 75.0 and first["load_1m"] == 2.5
    (tmp_path / "stat").write_text(STAT_2)
    # 1,000 jiffies passed, 800 of them idle or waiting: 20 % busy.
    assert sampler.sample()["cpu_pct"] == 20.0
    assert HostSampler(tmp_path / "missing").sample()["mem_pct"] is None


def test_a_containers_cpu_is_a_share_of_what_it_was_given():
    assert load_pct(400.0, 4.0, 8) == 100.0  # 4 cores busy out of its 4
    assert load_pct(86.0, 1.0, 8) == 86.0
    assert load_pct(200.0, None, 8) == 25.0  # no limit: the machine's 8
    assert load_pct(300.0, 16.0, 4) == 75.0  # a limit above the machine is the machine
    assert load_pct(None, 4.0, 8) is None and load_pct(50.0, None, None) is None
    assert nano_cpus("4000000000") == 4.0 and nano_cpus("0") is None and nano_cpus("?") is None
