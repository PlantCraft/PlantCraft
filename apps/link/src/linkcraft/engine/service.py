"""Link's engine: the schedules, the queue and its workers, in a process of their own.

Everything Link runs is an execution, a row of ``analysis_jobs`` (``engine.jobs``): an
algorithm on a loop, a round (every loop, or Signal quality on every signal), an algorithm on an
asset, or the past replayed. The schedules queue them when due (``Scheduler``), a person queues
them from a page, and the workers (``Dispatcher``) run them, highest priority first: a person's
request, then the schedules, then a replay.

The engine runs apart from the pages (``LINKCRAFT_ENGINE``, ``engine.process``): a long round or
a thousand executions at midnight never slow the interface down. The interface only writes to
the queue and reads it back. Every 15 s the engine writes what the queue holds
(``plantcraft_sdk.server.queue``), kept 30 days, for the Executions page's charts.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.server.memory import release
from plantcraft_sdk.server.queue import (
    SAMPLE_SECONDS,
    CpuMeter,
    QueueMetrics,
    QueueNow,
    QueueSampler,
    memory_mb,
)
from plantcraft_sdk.utc import utc_iso

from linkcraft.engine.dispatcher import Dispatcher, RetryLater, retryable, unreachable
from linkcraft.engine.scheduler import Scheduler
from linkcraft.engine.suite_compute import priority
from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)
PROGRESS_SECONDS = 2.0


def child_pids(parent: int) -> list[int]:
    """The processes started by ``parent`` (the compute and simulation workers), from /proc."""

    found = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii") as stat:
                fields = stat.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if fields and len(fields) > 1 and fields[1] == str(parent):
            found.append(int(entry))
    return found


class Engine:
    """The scheduler, the workers and the queue's samples, around one ``Runtime``."""

    def __init__(self, runtime: Any, *, slots: int | None = None):
        self.rt = runtime
        self.jobs = runtime.jobs
        self.dispatcher = Dispatcher(self.jobs, self.execute, slots=slots)
        self.scheduler = Scheduler(
            jobs=self.jobs,
            tick=runtime.tick,
            queued=self.dispatcher.wake,
            interval_seconds=60,
            poll_seconds=2,
            resolve_subjects=runtime.schedule_subjects,
        )
        self.metrics = QueueMetrics(runtime.db)
        self.sampler = QueueSampler(self.metrics, self.queue_now)
        self._cpu = CpuMeter()
        self.started = False

    # Running -----------------------------------------------------------------------------

    def start(self, *, scheduler: bool = True) -> None:
        if self.started:
            return
        self.started = True
        for job_id in self.jobs.requeue_interrupted():
            # What the stopped process sent the compute workers has no one waiting for it: the
            # job sends its tasks again (the same run), behind them unless they go.
            self.rt.cancel_compute(job_id)
        self.dispatcher.start()
        self.sampler.start()
        if scheduler:
            self.scheduler.start()

    def ensure_workers(self) -> None:
        """Work was queued in this process: its workers run it even with no scheduler."""

        if not self.dispatcher.running:
            self.dispatcher.start()
        self.dispatcher.wake()

    def stop(self) -> None:
        self.scheduler.stop()
        self.sampler.stop()
        self.dispatcher.stop()
        self.started = False

    # The queue's numbers -----------------------------------------------------------------

    def queue_now(self, since: datetime) -> QueueNow:
        counts = self.jobs.queue_counts(utc_iso(since))
        pids = [os.getpid(), *child_pids(os.getpid())]
        return QueueNow(
            **counts,
            workers=self.dispatcher.slots,
            busy=counts["running"],
            cpu_percent=self._cpu.read(pids),
            memory_mb=memory_mb(pids),
        )

    def live(self) -> QueueNow:
        """What the queue holds now, read from the database wherever the engine runs: the
        processor and memory are the engine's last sample when it runs in another process."""

        if self.started:
            return self.queue_now(datetime.now(UTC) - timedelta(seconds=SAMPLE_SECONDS))
        counts = self.jobs.queue_counts(
            (datetime.now(UTC) - timedelta(seconds=SAMPLE_SECONDS)).isoformat(timespec="seconds")
        )
        last = next((row for row in reversed(self.metrics.history("1h")) if row.get("workers")), {})
        return QueueNow(
            **counts,
            workers=int(last.get("workers") or self.dispatcher.slots),
            busy=counts["running"],
            cpu_percent=last.get("cpu_percent"),
            memory_mb=last.get("memory_mb"),
        )

    # One execution ------------------------------------------------------------------------

    def execute(self, job: dict[str, Any]) -> Any:
        try:
            found = self._execute(job)
        finally:
            if (job.get("work") or "loop") != "loop":
                # A round frees thousands of loops' data at once: give it back now, not at the
                # next peak (one loop's execution waits for the engine's minute, process.py).
                release()
        try:
            self.rt.events.after(job["job_id"])
        except Exception:  # an event not said is no reason to fail the execution
            LOGGER.warning("The events of %s were not published", job["job_id"], exc_info=True)
        return found

    def _execute(self, job: dict[str, Any]) -> Any:
        work = job.get("work") or "loop"
        # On the suite's compute workers, a replay waits behind the live work, and cancelling the
        # execution cancels its tasks there too (the run is the execution).
        with priority("backfill" if work == "replay" else "run", run=job["job_id"]):
            return self._dispatch(job, work)

    def _dispatch(self, job: dict[str, Any], work: str) -> Any:
        self.rt.sync_catalog()
        if work == "loop":
            return self.rt.monitor.execute_job(job["job_id"], claimed=True, retry=True)
        if work == "round":
            return self._round(job)
        if work == "asset":
            return self._asset(job)
        if work == "replay":
            return self._replay(job)
        self.jobs.fail_job(job["job_id"], t("Unknown work: {work}.", work=work))
        return None

    def _with_progress(self, job: dict[str, Any], read: Any, work: Any) -> Any:
        """Run ``work`` while writing ``read()`` (done, total) to the execution every 2 s."""

        stop = threading.Event()

        def report() -> None:
            while not stop.wait(PROGRESS_SECONDS):
                try:
                    done, total = read()
                    if total:
                        self.jobs.set_progress(job["job_id"], done, total)
                except Exception:  # progress is a courtesy; the work goes on
                    LOGGER.debug("Progress of %s not written", job["job_id"], exc_info=True)

        reporter = threading.Thread(
            target=report, name=f"progress-{job['job_id'][:8]}", daemon=True
        )
        reporter.start()
        try:
            return work()
        finally:
            stop.set()
            reporter.join(timeout=PROGRESS_SECONDS + 1)

    def _round(self, job: dict[str, Any]) -> dict[str, Any]:
        schedule = self.jobs.get_schedule(job.get("schedule_id") or "") or {}
        if not schedule:
            self.jobs.fail_job(job["job_id"], t("Monitor not found."))
            return {}
        trigger = "manual" if job.get("kind") in {"manual", "test"} else "schedule"
        signals = self.rt.is_signal_round(schedule)

        def read() -> tuple[int, int]:
            progress = self.rt.quality_engine.progress if signals else self.rt.monitor.progress
            return int(progress.get("done") or 0), int(progress.get("total") or 0)

        summary = self._with_progress(
            job,
            read,
            lambda: self.rt.run_scheduled_round(schedule, trigger, job.get("created_by") or ""),
        )
        self.jobs.record_round(schedule["schedule_id"], summary or {})
        status = summary.get("status") if summary else "error"
        done, total = read()
        subjects = int(summary.get("subjects") or 0) if summary else 0
        self.jobs.set_progress(job["job_id"], subjects or done, subjects or total)
        clean = {key: value for key, value in (summary or {}).items() if key != "header"}
        error = str((summary or {}).get("error") or "")
        if status not in {"ok", "partial"} and unreachable(error):
            # The plant's data did not answer (the Historian restarting, 0.6.0 load test C6):
            # the queue tries the round again in 30 s, then 2 min, as for one loop's run.
            raise RetryLater(error)
        if status in {"ok", "partial"}:
            self.jobs.finish(job["job_id"], "completed", summary=clean)
        else:
            self.jobs.finish(
                job["job_id"],
                "failed",
                summary=clean,
                error=str((summary or {}).get("error") or status),
            )
        return summary or {}

    def _asset(self, job: dict[str, Any]) -> dict[str, Any]:
        profile = self.rt.presets.get_profile(job.get("profile_id") or "")
        if profile is None:
            self.jobs.fail_job(job["job_id"], t("Algorithm not found."))
            return {}
        schedule = self.jobs.get_schedule(job.get("schedule_id") or "") or {}
        found = self.rt.assets.run_one(
            profile,
            job["loop_id"],
            interval_minutes=schedule.get("interval_minutes"),
            schedule=self.rt.recording(schedule, profile),
            # The monitor's own parameter values go on top of the algorithm's.
            node_parameters=(schedule.get("method_config") or {}).get("node_parameters"),
            # A schedule's runs read only what is new since the last one (the loops' cache).
            cached=bool(job.get("schedule_id")),
        )
        summary = found.get("summary") or {}
        if found.get("error"):
            # No data yet is worth another try for a schedule (its retries), not for a person
            # waiting on Run now.
            error = found["error"]
            if unreachable(error) or (job.get("schedule_id") and retryable(error)):
                raise RetryLater(error)
            self.jobs.finish(job["job_id"], "failed", summary=summary, error=found["error"])
        else:
            self.jobs.finish(job["job_id"], "completed", summary=summary)
        return found

    def _replay(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = job.get("payload") or {}
        replay = self.rt.replay

        def read() -> tuple[int, int]:
            state = replay.state
            return (
                int(state.get("rounds") or 0) + int(state.get("runs") or 0),
                int(state.get("total_rounds") or 0) + int(state.get("total_runs") or 0),
            )

        try:
            state = self._with_progress(
                job,
                read,
                lambda: replay.replay(
                    float(payload.get("hours") or 48),
                    float(payload.get("step_minutes") or 60),
                    payload.get("schedule_id") or None,
                ),
            )
        except Exception as exc:  # the execution says why; the live work goes on
            LOGGER.exception("History replay failed")
            state = {**replay.state, "running": False, "error": f"{type(exc).__name__}: {exc}"}
        if state.get("error"):
            self.jobs.finish(
                job["job_id"], "failed", summary=dict(state), error=str(state["error"])
            )
        else:
            self.jobs.finish(job["job_id"], "completed", summary=dict(state))
        return state
