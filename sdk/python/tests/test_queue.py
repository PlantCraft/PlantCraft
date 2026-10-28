"""The queue's numbers: samples kept, the history in buckets, the answer's format."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from plantcraft_sdk.server.queue import (
    FORMAT,
    CpuMeter,
    QueueMetrics,
    QueueNow,
    QueueSampler,
    memory_mb,
    queue_answer,
)
from plantcraft_sdk.server.store import Database


def _at(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


@pytest.fixture
def metrics(tmp_path):
    return QueueMetrics(Database(tmp_path / "app.sqlite3"))


def test_history_buckets_keep_the_peaks_and_sum_the_items_done(metrics):
    end = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    for minute, (queued, done, average) in enumerate(
        [(1000, 0, None), (600, 400, 2.0), (0, 600, 4.0)]
    ):
        metrics.record(
            QueueNow(
                queued=queued,
                running=8,
                workers=8,
                busy=8,
                done=done,
                delay_seconds=60.0 * minute,
                average_seconds=average,
                at=_at(end - timedelta(minutes=3 - minute)),
            )
        )
    whole = metrics.history("1h", points=1, end=end)
    assert len(whole) == 1
    assert whole[0]["queued"] == 1000 and whole[0]["done"] == 1000
    assert whole[0]["delay_seconds"] == 120.0
    assert whole[0]["average_seconds"] == pytest.approx((400 * 2 + 600 * 4) / 1000)
    assert len(metrics.history("1h", points=240, end=end)) == 3
    with pytest.raises(ValueError):
        metrics.history("2y")


def test_old_samples_are_pruned(metrics):
    metrics.record(QueueNow(at=_at(datetime.now(UTC) - timedelta(days=31))))
    metrics.record(QueueNow())
    assert metrics.prune() == 1


def test_the_sampler_asks_since_the_last_sample_and_survives_a_failure(metrics):
    asked = []

    def now(since):
        asked.append(since)
        if len(asked) == 2:
            raise RuntimeError("the queue table is locked")
        return QueueNow(
            queued=len(asked), at=_at(datetime.now(UTC) - timedelta(seconds=10 - len(asked)))
        )

    sampler = QueueSampler(metrics, now)
    assert sampler.sample().queued == 1
    assert sampler.sample() is None
    assert sampler.sample().queued == 3
    assert asked[1] >= asked[0]
    answer = queue_answer(QueueNow(queued=3), metrics, "1h")
    assert answer["format"] == FORMAT
    assert answer["now"]["queued"] == 3
    assert [point["queued"] for point in answer["history"]][-1] == 3


@pytest.mark.skipif(not os.path.exists("/proc/self/stat"), reason="needs /proc")
def test_memory_and_cpu_of_this_process():
    assert memory_mb() > 1
    meter = CpuMeter()
    assert meter.read() is None
    sum(range(200_000))
    assert meter.read() >= 0
