"""FMUs run in worker processes: a slow or crashing model never takes the server down."""

from __future__ import annotations

import os
import time

import numpy as np
import pytest

from linkcraft.models.builtin import builtin_folder
from linkcraft.models.simulate import Simulation, SimulationError, SimulationPool, run_simulation

LOOP = str(builtin_folder() / "PlantCraftTwin.LoopProcess.fmu")


def _job(**changes):
    times = np.arange(0.0, 1800.0 + 5.0, 5.0)
    values = {
        "fmu": LOOP,
        "times": times,
        "inputs": {"u": np.where(times >= 300.0, 60.0, 50.0), "d": np.full(len(times), 50.0)},
        "outputs": ["y"],
        "start_values": {"K": 0.5, "tau": 100.0, "theta": 20.0, "y0": 40.0, "y_start": 40.0},
        "step": 5.0,
    }
    values.update(changes)
    return Simulation(**values)


def sleepy(job):
    time.sleep(30)


def crashing(job):
    os._exit(3)


def test_the_loop_model_answers_like_first_order_plus_dead_time():
    result = run_simulation(_job())
    times = np.arange(0.0, 1805.0, 5.0)
    expected = 40.0 + 0.5 * 10.0 * (1.0 - np.exp(-np.clip(times - 320.0, 0, None) / 100.0))
    assert np.max(np.abs(result["y"] - expected)) < 0.15
    assert result["y"][-1] == pytest.approx(45.0, abs=0.01)


def test_a_worker_process_runs_the_model():
    pool = SimulationPool(workers=1, timeout=60)
    try:
        assert pool.run(_job())["y"][-1] == pytest.approx(45.0, abs=0.01)
    finally:
        pool.shutdown()


def test_a_model_that_never_ends_is_stopped_and_the_pool_recovers():
    pool = SimulationPool(workers=1, timeout=1, target=sleepy)
    try:
        with pytest.raises(SimulationError, match="did not finish"):
            pool.run(_job())
        pool.target = run_simulation
        assert pool.run(_job())["y"][-1] == pytest.approx(45.0, abs=0.01)
    finally:
        pool.shutdown()


def test_a_model_that_kills_its_worker_is_a_failed_run():
    pool = SimulationPool(workers=1, timeout=30, target=crashing)
    try:
        with pytest.raises(SimulationError, match="crashed"):
            pool.run(_job())
        assert pool.crashes == 1
        pool.target = run_simulation
        assert pool.run(_job())["y"][-1] == pytest.approx(45.0, abs=0.01)
    finally:
        pool.shutdown()


def test_a_broken_file_is_a_failed_run_with_words(tmp_path):
    broken = tmp_path / "broken.fmu"
    broken.write_bytes(b"not a zip")
    pool = SimulationPool(workers=1, timeout=30)
    try:
        with pytest.raises(SimulationError, match="failed"):
            pool.run(_job(fmu=str(broken)))
    finally:
        pool.shutdown()
