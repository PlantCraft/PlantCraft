"""Running an FMU, always in a separate process.

An FMU is native code: a crash, an endless loop or a leak in it must never take the server
down. Every simulation runs in a worker process of ``SimulationPool`` (started with ``spawn``,
replaced after ``TASKS_PER_WORKER`` runs); a run that takes longer than the timeout or kills its
worker is a failed run with a sentence that says so, and the pool starts fresh workers.
"""

from __future__ import annotations

import contextlib
import ctypes
import io
import logging
import multiprocessing
import os
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any

import numpy as np

from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)
TASKS_PER_WORKER = 200


class SimulationError(RuntimeError):
    """A simulation that did not finish, with a sentence a person can act on."""


@dataclass
class Simulation:
    """One run: ``inputs`` and the result share ``times`` (seconds from the start)."""

    fmu: str
    times: np.ndarray
    inputs: dict[str, np.ndarray]
    outputs: list[str]
    start_values: dict[str, float]
    step: float


def run_simulation(job: Simulation) -> dict[str, np.ndarray]:
    """Simulate ``job`` (in a worker process) and return each output at ``job.times``."""

    from fmpy import simulate_fmu

    # FMPy prints warnings (an input left at its start value) to stdout and the FMU's C
    # runtime prints solver settings to the process's stdout: keep the log clean.
    with _STDOUT_LOCK, _silent_stdout(), contextlib.redirect_stdout(io.StringIO()):
        return _simulate(simulate_fmu, job)


_STDOUT_LOCK = threading.Lock()


def _flush_c_stdout() -> None:
    """Flush the C library's buffer, so the FMU's lines land in the null device."""

    try:
        ctypes.CDLL(None).fflush(None)
    except (OSError, AttributeError):
        pass


@contextlib.contextmanager
def _silent_stdout() -> Iterator[None]:
    """Point file descriptor 1 at the null device while an FMU runs (its C code prints)."""

    try:
        sys.stdout.flush()
        saved = os.dup(1)
    except (OSError, ValueError):
        yield
        return
    try:
        with open(os.devnull, "wb") as null:
            os.dup2(null.fileno(), 1)
        yield
    finally:
        _flush_c_stdout()
        os.dup2(saved, 1)
        os.close(saved)


def _simulate(simulate_fmu: Any, job: Simulation) -> dict[str, np.ndarray]:
    times = np.asarray(job.times, dtype=float)
    stop = float(times[-1]) if len(times) else 0.0
    signals = None
    if job.inputs:
        names = list(job.inputs)
        signals = np.zeros(len(times), dtype=[("time", float)] + [(name, float) for name in names])
        signals["time"] = times
        for name in names:
            signals[name] = np.asarray(job.inputs[name], dtype=float)
    result = simulate_fmu(
        job.fmu,
        start_time=float(times[0]) if len(times) else 0.0,
        stop_time=stop,
        output_interval=job.step,
        step_size=job.step,
        start_values=dict(job.start_values),
        input=signals,
        output=list(job.outputs),
        validate=False,
        logger=_quiet,
    )
    stamps = np.asarray(result["time"], dtype=float)
    answer = {}
    for name in job.outputs:
        values = np.asarray(result[name], dtype=float)
        # FMPy may record an extra point at an event; read the model at the asked times.
        answer[name] = (
            np.interp(times, stamps, values) if len(stamps) else np.full(len(times), np.nan)
        )
    return answer


def _quiet(*_args: Any) -> None:
    """The FMU's own log (solver statistics): not kept."""


class SimulationPool:
    """Worker processes that run FMUs; ``run`` blocks until the result or the timeout."""

    def __init__(self, workers: int = 2, timeout: float = 60.0, target: Any = None):
        # ``target`` runs a job in the worker (``run_simulation``; tests give a module function).
        self.target = target or run_simulation
        self.workers = max(1, int(workers))
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None
        self.crashes = 0

    def _executor(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=self.workers,
                    mp_context=multiprocessing.get_context("spawn"),
                    max_tasks_per_child=TASKS_PER_WORKER,
                )
            return self._pool

    def _reset(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is None:
            return
        for process in list((getattr(pool, "_processes", None) or {}).values()):
            if process.is_alive():
                process.kill()
        pool.shutdown(wait=False, cancel_futures=True)

    def run(self, job: Simulation) -> dict[str, np.ndarray]:
        try:
            future = self._executor().submit(self.target, job)
            return future.result(timeout=self.timeout)
        except FutureTimeout as exc:
            self._reset()
            raise SimulationError(
                t(
                    "The model did not finish in {seconds} s and was stopped.",
                    seconds=f"{self.timeout:g}",
                )
            ) from exc
        except BrokenProcessPool as exc:
            self.crashes += 1
            self._reset()
            raise SimulationError(
                t("The model crashed while running (its native code stopped the worker).")
            ) from exc
        except Exception as exc:  # noqa: BLE001 - whatever the FMU or FMPy raised
            raise SimulationError(
                t("The model failed: {error}", error=str(exc)[:300] or type(exc).__name__)
            ) from exc

    def shutdown(self) -> None:
        self._reset()


class InlinePool:
    """Runs simulations in this process: for tests and the command line only."""

    timeout = 0.0
    crashes = 0

    def run(self, job: Simulation) -> dict[str, Any]:
        try:
            return run_simulation(job)
        except Exception as exc:  # noqa: BLE001
            raise SimulationError(t("The model failed: {error}", error=str(exc)[:300])) from exc

    def shutdown(self) -> None:
        return None
