"""The simulation queue: hands queued runs to the Modelica runner, a few at a time.

Runs wait in the database (``status = 'queued'``), so the queue survives a restart. One thread
picks the next work: the oldest run of the highest priority (a quick simulation goes ahead of a
sweep) and, for a sweep, up to ``batch`` more runs of the same study, which the runner builds
once and simulates one after the other. At most ``workers`` jobs are with the runner at once.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from modelcraft.runs.store import RunStore

LOGGER = logging.getLogger(__name__)


class Dispatcher:
    def __init__(
        self,
        runs: RunStore,
        execute: Callable[[list[dict[str, Any]]], None],
        *,
        workers: int = 2,
        batch: int = 10,
    ):
        self.runs = runs
        self.execute = execute
        self.workers = max(1, workers)
        self.batch = max(1, batch)
        self.active: set[str] = set()
        self._jobs = 0
        self._wake = threading.Condition()
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="modelcraft-run"
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="modelcraft-queue", daemon=True)
            self._thread.start()

    def wake(self) -> None:
        """New runs are queued (or a worker is free): look again now."""

        self.start()
        with self._wake:
            self._wake.notify_all()

    def busy(self) -> int:
        with self._wake:
            return self._jobs

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._wake:
                if self._jobs >= self.workers:
                    self._wake.wait(1.0)
                    continue
                try:
                    batch = self.runs.next_batch(self.batch, self.active)
                except Exception:  # noqa: BLE001 - the queue keeps going
                    LOGGER.exception("The queue could not read the next runs")
                    batch = []
                if not batch:
                    self._wake.wait(2.0)
                    continue
                self._jobs += 1
                self.active.update(run["id"] for run in batch)
            self._pool.submit(self._run, batch)

    def _run(self, batch: list[dict[str, Any]]) -> None:
        try:
            self.execute(batch)
        except Exception:  # noqa: BLE001 - a job never stops the queue
            LOGGER.exception("Runs %s failed in the queue", [run["id"] for run in batch])
        finally:
            with self._wake:
                self._jobs -= 1
                self.active.difference_update(run["id"] for run in batch)
                self._wake.notify_all()

    def shutdown(self) -> None:
        self._stop.set()
        with self._wake:
            self._wake.notify_all()
        self._pool.shutdown(wait=False, cancel_futures=True)
