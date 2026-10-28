"""The soak's verdict (ci/bench/soak.py): the checks on the suite's health and on the probes."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "ci" / "bench"


@pytest.fixture(scope="module")
def soak():
    sys.path.insert(0, str(BENCH))
    try:
        spec = importlib.util.spec_from_file_location("soak", BENCH / "soak.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path.remove(str(BENCH))


HOUR = 3600.0


def grid(hours: float, value) -> tuple[list[float], list]:
    times = [i * 300.0 for i in range(int(hours * 12))]
    return times, [value(t) for t in times]


def results(checks: list[dict]) -> dict[tuple[str, str], str]:
    return {(c["subject"], c["check"]): c["result"] for c in checks}


def test_slope_is_per_day_and_ignores_gaps(soak):
    times = [0.0, HOUR, 2 * HOUR, 3 * HOUR]
    assert soak.slope_per_day(times, [100.0, 101.0, math.nan, 103.0]) == pytest.approx(24.0)
    assert soak.slope_per_day(times[:2], [1.0, 2.0]) is None


def test_a_flat_healthy_service_passes(soak):
    series = {
        "system:histcraft.up": grid(72, lambda t: 1.0),
        "system:histcraft.restarts": grid(72, lambda t: 2.0),  # restarts before the soak
        "system:histcraft.mem_mb": grid(72, lambda t: 400.0 + (5 if t < HOUR else 0)),
        "system:linkcraft.queue_wait_min": grid(72, lambda t: 0.5),
        "system:host.disk_free_gb": grid(72, lambda t: 200.0 - t / 86400),
    }
    checks = soak.health_checks(series, HOUR)
    assert soak.verdict(checks) == "PASS", checks
    assert ("host", "disk") in results(checks)


def test_a_restart_a_leak_and_a_stuck_queue_fail(soak):
    series = {
        "system:histcraft.restarts": grid(72, lambda t: 0.0 if t < 30 * HOUR else 1.0),
        "system:linkcraft.mem_mb": grid(72, lambda t: 500.0 + 300 * t / 86400),  # +60 %/day
        "system:modelcraft.mem_mb": grid(72, lambda t: 500.0 + 75 * t / 86400),  # +15 %/day
        "system:linkcraft.queue_wait_min": grid(72, lambda t: 45.0 if t > 60 * HOUR else 1.0),
        "system:dashcraft.up": grid(72, lambda t: 0.0 if t < 2 * HOUR else 1.0),
    }
    found = results(soak.health_checks(series, HOUR))
    assert found[("histcraft", "restarts")] == "FAIL"
    assert found[("linkcraft", "memory")] == "FAIL"
    assert found[("modelcraft", "memory")] == "warn"
    assert found[("linkcraft", "queue wait")] == "FAIL"
    assert found[("dashcraft", "up")] == "FAIL"


def test_a_disk_filling_within_a_month_warns(soak):
    series = {"system:host.disk_free_gb": grid(72, lambda t: 50.0 - 5 * t / 86400)}
    checks = soak.health_checks(series, HOUR)
    assert results(checks)[("host", "disk")] == "warn"
    assert soak.verdict(checks) == "WARN"


def test_probes_fail_on_errors_and_warn_on_stale_values(soak):
    rows = [{"probe": "me", "ok": True, "ms": 20} for _ in range(999)]
    rows += [{"probe": "batch_read", "ok": i % 50, "ms": 300, "error": "502"} for i in range(200)]
    rows += [
        {"probe": "freshness", "ok": True, "age_s": 30.0 if i % 4 else 600.0} for i in range(100)
    ]
    found = results(soak.probe_checks(rows))
    assert found[("probe", "me")] == "ok"
    assert found[("probe", "batch_read")] == "FAIL"  # 2 % failed
    assert found[("probe", "freshness")] == "warn"


def test_the_report_reads_the_probes_and_the_system_signals(soak, tmp_path):
    class FakeSuite:
        def call(self, method, path, body=None, **_):
            if path == "/api/v1/signals":
                return [{"id": "system:histcraft.up"}, {"id": "plant:FIC-101.PV"}], 0.0, 0
            assert body["signals"] == ["system:histcraft.up"] and body["step"] == soak.STEP
            t = ["2026-10-23T20:00:00.000Z", "2026-10-23T20:05:00.000Z"]
            return {"series": [{"signal": "system:histcraft.up", "t": t, "v": [1, 1]}]}, 0.0, 0

    (tmp_path / "probes.jsonl").write_text(json.dumps({"probe": "me", "ok": True, "ms": 9}) + "\n")
    state = {
        "started_at": "2026-10-23T20:00:00Z",
        "until": "2026-10-23T21:00:00Z",
        "hours": 1,
        "machine": {"host": "mini", "cpus": 4, "memory_gib": 48},
        "versions": {},
    }
    text = soak.report(FakeSuite(), tmp_path, state, tmp_path / "results")
    assert text.startswith("# Soak on mini: PASS")
    assert "| histcraft | up | ok | 100.00 % |" in text
    assert json.loads((tmp_path / "report.json").read_text())["verdict"] == "PASS"
    assert (tmp_path / "results" / "mini-20261023-2000-soak.md").exists()
