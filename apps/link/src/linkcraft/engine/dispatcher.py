"""The queue's workers: take the next execution due and run it, a few at a time.

Each execution is a row of ``analysis_jobs`` (``JobStore``). A worker takes the next one with
``claim_next`` (highest priority first, then the one waiting longest), so two workers, or two
processes, never run the same one. ``run(job)`` does the work; it raises ``RetryLater`` when
the plant's data could not be read, and the execution waits in the queue for its next try
(``RETRY_SECONDS``) until ``attempts`` reach ``max_attempts``, then fails with the reason. An
execution of a schedule follows the schedule's retries instead (``retry``: on or off, how many
more tries, how far apart, and whether to give up when the schedule's next occurrence comes
first).
"""

from __future__ import annotations

import logging
import os
import platform
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from linkcraft.engine.jobs import JobStore
from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)
# Waits before the second and the third try of an execution whose data could not be read.
RETRY_SECONDS = (30.0, 120.0)
IDLE_SECONDS = 2.0


def schedule_tries(schedule: dict[str, Any]) -> int | None:
    """How many tries a schedule gives each execution (its retries plus the first), or None when
    the queue's own retries apply (a round, or a schedule saved before retries)."""

    retry = schedule.get("retry")
    if not retry or schedule.get("kind") == "round":
        return None
    return 1 + int(retry.get("count") or 0) if retry.get("enabled") else 1


class RetryLater(RuntimeError):
    """The work could not start for now (the plant's data did not answer): try again later."""


def unreachable(reason: str) -> bool:
    """A failure of reading the plant (worth another try) rather than of the algorithm."""

    text = reason.lower()
    return any(
        word in text
        for word in ("timed out", "timeout", "connection", "unreachable", "503", "502", "504")
    )


def retryable(reason: str) -> bool:
    """Worth another try: the plant did not answer, or it had no data yet. An error of the
    algorithm itself (its code, its diagram) is not."""

    text = reason.lower()
    return unreachable(reason) or any(
        words in text for words in ("no data", "the window is empty", "returned no data")
    )


def default_slots() -> int:
    configured = os.environ.get("LINKCRAFT_WORKERS", "").strip()
    if configured.isdigit() and int(configured) > 0:
        return int(configured)
    return max(2, min(8, (os.cpu_count() or 2)))


class Dispatcher:
    def __init__(
        self,
        jobs: JobStore,
        run: Callable[[dict[str, Any]], Any],
        *,
        slots: int | None = None,
        max_attempts: int = len(RETRY_SECONDS) + 1,
        name: str = "",
    ):
        self.jobs = jobs
        self.run = run
        self.slots = slots or default_slots()
        self.max_attempts = max_attempts
        self.name = name or f"{platform.node()}:{os.getpid()}"
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._busy = 0
        self._guard = threading.Lock()

    @property
    def busy(self) -> int:
        with self._guard:
            return self._busy

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._loop, name=f"execution-{index + 1}", daemon=True)
            for index in range(self.slots)
        ]
        for thread in self._threads:
            thread.start()

    def wake(self) -> None:
        """Something was queued: look now instead of at the next idle check."""

        self._wake.set()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=timeout / max(1, len(self._threads)))

    def run_next(self) -> bool:
        """Take one execution and run it here; ``False`` when nothing is due."""

        job = self.jobs.claim_next(self.name)
        if job is None:
            return False
        with self._guard:
            self._busy += 1
        try:
            self._execute(job)
        finally:
            with self._guard:
                self._busy -= 1
        return True

    def drain(self, limit: int = 100_000) -> int:
        """Run everything due, here and now, one after the other (tests and the command line)."""

        count = 0
        while count < limit and self.run_next():
            count += 1
        return count

    def _execute(self, job: dict[str, Any]) -> None:
        try:
            self.run(job)
        except RetryLater as exc:
            attempts = int(job.get("attempts") or 1)
            reason = str(exc) or type(exc).__name__
            most, wait, before = self._policy(job)
            due = datetime.now(UTC) + timedelta(seconds=wait(attempts))
            if attempts >= most:
                LOGGER.warning(
                    "Execution %s failed after %d tries: %s", job["job_id"], attempts, reason
                )
                self.jobs.fail_job(job["job_id"], reason)
                return
            if before is not None and due >= before:
                self.jobs.fail_job(
                    job["job_id"],
                    t(
                        "{reason} (not tried again: the monitor's next occurrence comes first)",
                        reason=reason,
                    ),
                )
                return
            stamp = due.isoformat(timespec="seconds")
            LOGGER.info("Execution %s tried again at %s: %s", job["job_id"], stamp, reason)
            self.jobs.requeue_later(job["job_id"], stamp, reason)
        except Exception as exc:  # one execution never stops the worker
            LOGGER.exception("Execution %s failed", job["job_id"])
            current = self.jobs.get_job(job["job_id"]) or {}
            if current.get("status") == "running":
                self.jobs.fail_job(job["job_id"], f"{type(exc).__name__}: {exc}")

    def _policy(self, job: dict[str, Any]) -> tuple[int, Callable[[int], float], datetime | None]:
        """How many tries an execution gets, the wait before the next, and the moment it gives up
        by (its schedule's next occurrence), from its schedule's retries or the queue's own."""

        schedule = self.jobs.get_schedule(job["schedule_id"]) if job.get("schedule_id") else None
        tries = schedule_tries(schedule or {})
        if tries is None:
            return (
                self.max_attempts,
                lambda attempt: RETRY_SECONDS[min(attempt, len(RETRY_SECONDS)) - 1],
                None,
            )
        retry = (schedule or {})["retry"]
        if tries == 1:
            return 1, lambda _attempt: 0.0, None
        before = None
        following = (schedule or {}).get("next_run_at")
        if retry.get("abort_on_next") and following:
            before = datetime.fromisoformat(following)
            if before.tzinfo is None:
                before = before.replace(tzinfo=UTC)
        minutes = float(retry.get("wait_minutes") or 5)
        return tries, lambda _attempt: minutes * 60, before

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_next()
            except Exception:  # the database busy, say: wait and look again
                LOGGER.exception("Taking the next execution failed")
                worked = False
            if worked:
                continue
            self._wake.wait(IDLE_SECONDS)
            # The workers share one wake: once stopping it stays set, or a worker that cleared it
            # would leave the others waiting out their idle check before they see the stop.
            if not self._stop.is_set():
                self._wake.clear()
