"""The schedules: when one is due, its occurrence goes into the queue.

Every recurring piece of work is a row in ``analysis_schedules``, and every one is handled the
same way (owner, 2026-10-23: no special rounds): at each occurrence ``materialize_occurrence``
queues its executions (one per subject, or one round over all of them), each skipped when the
subject's previous one has not ended, and the next occurrence is set. The workers
(``engine.dispatcher``) run them. ``tick`` is called every ``interval_seconds`` for light
periodic work (pruning the history, the algorithms' cycles kept as schedules).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from linkcraft.engine.jobs import JobStore, schedule_work

LOGGER = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        *,
        jobs: JobStore,
        tick: Callable[[], Any],
        queued: Callable[[], Any],
        interval_seconds: float,
        poll_seconds: float = 5,
        resolve_subjects: Callable[[dict[str, Any]], list[str]] | None = None,
    ):
        self.jobs = jobs
        self.tick = tick
        self.queued = queued
        self.resolve_subjects = resolve_subjects
        self.interval_seconds = max(1, int(interval_seconds))
        self.poll_seconds = poll_seconds
        self.running = False
        self.next_run_at: str | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="linkcraft-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)

    def run_due_schedules(self, now: datetime | None = None) -> list[str]:
        """Queue every due occurrence; the ids of the executions queued."""

        started: list[str] = []
        for schedule in self.jobs.due_schedules(now):
            subjects = None
            if schedule_work(schedule) != "round" and schedule.get("selector") is not None:
                if self.resolve_subjects is None:
                    continue
                try:
                    subjects = self.resolve_subjects(schedule)
                except Exception:
                    LOGGER.exception(
                        "Selecting subjects for schedule %s failed", schedule["schedule_id"]
                    )
                    continue
            started.extend(self.jobs.materialize_occurrence(schedule["schedule_id"], subjects, now))
        if started:
            self.queued()
        return started

    def _loop(self) -> None:
        next_tick = datetime.now(UTC)
        while self.running:
            now = datetime.now(UTC)
            if now >= next_tick:
                try:
                    self.tick()
                except Exception:  # keep the scheduler alive across bad cycles
                    LOGGER.exception("Scheduled periodic work failed")
                next_tick = datetime.now(UTC) + timedelta(seconds=self.interval_seconds)
            try:
                self.run_due_schedules()
            except Exception:
                LOGGER.exception("Queuing the due schedules failed")
            schedule_times = [
                item["next_run_at"]
                for item in self.jobs.list_schedules(enabled_only=True)
                if item.get("next_run_at")
            ]
            self.next_run_at = min(schedule_times) if schedule_times else None
            if self._stop_event.wait(self.poll_seconds) or not self.running:
                break
        self.next_run_at = None
