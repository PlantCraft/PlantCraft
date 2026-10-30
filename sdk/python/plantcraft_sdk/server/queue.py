"""An app's work queue as numbers: what it holds now and how that went over time.

Every app that queues work (Link's executions, Models' simulations) shows its queue the same way:
the numbers of now (queued, running, done and failed in the last hour, how
long the oldest item has waited, the workers) and the same numbers over 24 hours, 7 days and
30 days. The app says what its queue holds now (``QueueNow``); ``QueueSampler`` asks it every
15 seconds and ``QueueMetrics`` keeps each sample 30 days, in the app's own database. The
interface draws both with ``QueuePanel`` from ``@plantcraft/ui``; ``queue_answer`` is the JSON
an app's ``GET /api/queue`` gives it::

    {"format": "plantcraft-queue/1",
     "now": {"at": ..., "queued": 12, "running": 4, ...},
     "history": [{"at": ..., "queued": 12, "running": 4, "done": 30, ...}, ...]}
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from plantcraft_sdk.server.store import Store

LOGGER = logging.getLogger(__name__)

FORMAT = "plantcraft-queue/1"
SAMPLE_SECONDS = 15.0
KEEP_DAYS = 30.0
# The windows the panel offers, as seconds, and how many points each history is cut into.
WINDOWS = {"1h": 3600, "24h": 86_400, "7d": 7 * 86_400, "30d": 30 * 86_400}
HISTORY_POINTS = 240


@dataclass
class QueueNow:
    """What a queue holds at one moment.

    ``done``, ``failed`` and ``cancelled`` count the items finished since the moment the sampler
    asked about (the previous sample); the ``_hour`` counts the last hour, for the panel.
    ``delay_seconds`` is how long the oldest item due has waited to start (0 with nothing
    waiting). ``average_seconds`` is the mean run time of the items done since that moment.
    """

    queued: int = 0
    running: int = 0
    workers: int = 0
    busy: int = 0
    done: int = 0
    failed: int = 0
    cancelled: int = 0
    done_hour: int = 0
    failed_hour: int = 0
    cancelled_hour: int = 0
    skipped_hour: int = 0
    delay_seconds: float = 0.0
    average_seconds: float | None = None
    cpu_percent: float | None = None
    memory_mb: float | None = None
    at: str = field(default_factory=lambda: _stamp(datetime.now(UTC)))

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class QueueMetrics(Store):
    """One row per sample, ``KEEP_DAYS`` days."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS queue_metrics (
        at TEXT PRIMARY KEY,
        queued INTEGER NOT NULL,
        running INTEGER NOT NULL,
        workers INTEGER NOT NULL,
        busy INTEGER NOT NULL,
        done INTEGER NOT NULL,
        failed INTEGER NOT NULL,
        cancelled INTEGER NOT NULL DEFAULT 0,
        delay_seconds REAL NOT NULL,
        average_seconds REAL,
        cpu_percent REAL,
        memory_mb REAL
    );
    """

    def record(self, now: QueueNow) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO queue_metrics (at, queued, running, workers, busy, done, failed, "
                "cancelled, delay_seconds, average_seconds, cpu_percent, memory_mb) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now.at,
                    now.queued,
                    now.running,
                    now.workers,
                    now.busy,
                    now.done,
                    now.failed,
                    now.cancelled,
                    now.delay_seconds,
                    now.average_seconds,
                    now.cpu_percent,
                    now.memory_mb,
                ),
            )

    def history(
        self, window: str = "24h", *, points: int = HISTORY_POINTS, end: datetime | None = None
    ) -> list[dict[str, Any]]:
        """The samples of the last ``window`` in at most ``points`` buckets: the highest queue,
        running and delay of each bucket, the items done, failed and cancelled summed, the mean run time
        weighted by the items done."""

        seconds = WINDOWS.get(window)
        if seconds is None:
            raise ValueError(f"window must be one of {', '.join(WINDOWS)}")
        stop = end or datetime.now(UTC)
        start = stop - timedelta(seconds=seconds)
        bucket = max(SAMPLE_SECONDS, seconds / max(1, points))
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM queue_metrics WHERE at >= ? AND at <= ? ORDER BY at",
                (_stamp(start), _stamp(stop)),
            ).fetchall()
        buckets: dict[int, dict[str, Any]] = {}
        for row in rows:
            index = int((_parse(row["at"]) - start).total_seconds() // bucket)
            found = buckets.get(index)
            if found is None:
                found = buckets[index] = {
                    "at": _stamp(start + timedelta(seconds=index * bucket)),
                    "queued": 0,
                    "running": 0,
                    "workers": 0,
                    "done": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "delay_seconds": 0.0,
                    "_time": 0.0,
                    "_timed": 0,
                }
            found["queued"] = max(found["queued"], row["queued"])
            found["running"] = max(found["running"], row["running"])
            found["workers"] = max(found["workers"], row["workers"])
            found["done"] += row["done"]
            found["failed"] += row["failed"]
            found["cancelled"] += row["cancelled"]
            found["delay_seconds"] = max(found["delay_seconds"], row["delay_seconds"])
            if row["average_seconds"] is not None and row["done"]:
                found["_time"] += row["average_seconds"] * row["done"]
                found["_timed"] += row["done"]
        answer = []
        for index in sorted(buckets):
            found = buckets[index]
            timed = found.pop("_timed")
            total = found.pop("_time")
            found["average_seconds"] = round(total / timed, 3) if timed else None
            answer.append(found)
        return answer

    def prune(self, *, days: float = KEEP_DAYS) -> int:
        cut = _stamp(datetime.now(UTC) - timedelta(days=days))
        with self._lock, self._connect() as connection:
            return connection.execute("DELETE FROM queue_metrics WHERE at < ?", (cut,)).rowcount


def memory_mb(pids: list[int] | None = None) -> float | None:
    """Resident memory (MB) of these processes (this one when none are given), from /proc;
    ``None`` where /proc is missing."""

    total = 0.0
    found = False
    for pid in pids or [os.getpid()]:
        try:
            with open(f"/proc/{pid}/status", encoding="ascii") as status:
                for line in status:
                    if line.startswith("VmRSS:"):
                        total += int(line.split()[1]) / 1024
                        found = True
                        break
        except (OSError, ValueError):
            continue
    return round(total, 1) if found else None


class CpuMeter:
    """CPU use of a set of processes between two readings, in percent of one core."""

    def __init__(self) -> None:
        self._last: tuple[float, float] | None = None

    @staticmethod
    def _ticks(pids: list[int]) -> float | None:
        total = 0
        found = False
        for pid in pids:
            try:
                with open(f"/proc/{pid}/stat", encoding="ascii") as stat:
                    fields = stat.read().rsplit(")", 1)[1].split()
                total += int(fields[11]) + int(fields[12])
                found = True
            except (OSError, ValueError, IndexError):
                continue
        return total / os.sysconf("SC_CLK_TCK") if found else None

    def read(self, pids: list[int] | None = None) -> float | None:
        seconds = self._ticks(pids or [os.getpid()])
        if seconds is None:
            return None
        moment = datetime.now(UTC).timestamp()
        last, self._last = self._last, (moment, seconds)
        if last is None or moment <= last[0]:
            return None
        return round(max(0.0, (seconds - last[1]) / (moment - last[0]) * 100), 1)


class QueueSampler:
    """Asks the app what its queue holds every ``seconds`` and keeps it.

    ``now(since)`` gets the moment of the previous sample, for the items finished since. Once
    an hour the samples older than ``KEEP_DAYS`` go. A failing ``now`` is logged and the
    sampler goes on.
    """

    def __init__(
        self,
        metrics: QueueMetrics,
        now: Callable[[datetime], QueueNow],
        *,
        seconds: float = SAMPLE_SECONDS,
    ):
        self.metrics = metrics
        self.now = now
        self.seconds = seconds
        self.last = datetime.now(UTC)
        self._pruned = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sample(self) -> QueueNow | None:
        since, self.last = self.last, datetime.now(UTC)
        try:
            found = self.now(since)
            self.metrics.record(found)
        except Exception:
            LOGGER.exception("The queue sample failed")
            return None
        moment = self.last.timestamp()
        if moment - self._pruned > 3600:
            self._pruned = moment
            try:
                self.metrics.prune()
            except Exception:
                LOGGER.exception("Pruning the queue samples failed")
        return found

    def _loop(self) -> None:
        while not self._stop.wait(self.seconds):
            self.sample()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="queue-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)


def queue_answer(now: QueueNow, metrics: QueueMetrics, window: str = "24h") -> dict[str, Any]:
    """The body of an app's ``GET /api/queue?window=``: now and the history of the window."""

    return {
        "format": FORMAT,
        "window": window,
        "sample_seconds": SAMPLE_SECONDS,
        "now": now.as_dict(),
        "history": metrics.history(window),
    }
