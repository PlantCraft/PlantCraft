"""The benchmark runs end to end at a small scale."""

from __future__ import annotations

from linkcraft.bench import plant, run


def test_bench_plant_shapes_loops_as_processcraft_assets():
    assets, signals = plant(120)
    loops = [item for item in assets if item["kind"] == "loop"]
    assert len(loops) == 120 and len(signals) == 360
    assert len([item for item in assets if item["kind"] == "area"]) == 3


def test_a_small_bench_round_completes(tmp_path):
    report = run(loops=12, processes=0, latency_ms=0, hours=1, folder=tmp_path, server_processes=1)
    cold, warm = report["rounds"]
    assert cold["loops"] == warm["loops"] == 12
    # Assets, asset types, the newest-sample probes and one batch read for all 36 signals: not
    # one per signal.
    assert 3 <= cold["requests"] - cold["suite_requests"] <= 7
    assert 3 <= warm["requests"] - warm["suite_requests"] <= 7
    # Publishing: the run (started, then done), one results write, one derived series write
    # (health and status of every loop) and the schedule list per round, plus the findings opened as one list of events (the cold round opens them; the
    # warm one finds nothing new).
    assert cold["series_requests"] == warm["series_requests"] == 1
    assert cold["events"] > 1 and cold["event_requests"] == 1
    assert cold["suite_requests"] == cold["event_requests"] + 5
    assert warm["events"] == warm["event_requests"] == 0 and warm["suite_requests"] == 5


def test_the_bench_also_runs_in_process(tmp_path):
    report = run(loops=12, processes=0, latency_ms=0, hours=1, folder=tmp_path, transport="mock")
    assert report["transport"] == "mock" and report["rounds"][0]["loops"] == 12
