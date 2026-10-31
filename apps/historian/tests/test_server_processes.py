"""The Historian in several server processes (``HISTCRAFT_WORKERS``, 0.6.0 load tests)."""

from __future__ import annotations

import time

from histcraft.api.runtime import Runtime
from histcraft.config import Settings
from tests.conftest import make_settings


def _sampling(runtime: Runtime) -> bool:
    thread = runtime.queue_sampler._thread
    return thread is not None and thread.is_alive()


def test_one_process_samples_the_queue_and_another_takes_over(tmp_path, fake, monkeypatch):
    monkeypatch.setattr("plantcraft_sdk.server.workers.LEADER_RETRY_SECONDS", 0.1)
    runtimes = [
        Runtime(
            make_settings(tmp_path),
            verifier=fake.verifier("histcraft"),
            http_client=fake.http_client(),
        )
        for _ in range(2)
    ]
    first, second = runtimes
    try:
        first.start()
        second.start()
        assert _sampling(first) and not _sampling(second)
        first.shutdown()
        deadline = time.monotonic() + 5
        while not _sampling(second) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _sampling(second)
    finally:
        for runtime in runtimes:
            runtime.shutdown()


def test_each_process_holds_its_part_of_the_read_budget(monkeypatch):
    monkeypatch.setenv("HISTCRAFT_READ_VALUES", "4000000")
    monkeypatch.setenv("HISTCRAFT_SERVER_PROCESSES", "2")
    assert Settings.from_environment().read_values == 2_000_000
    monkeypatch.delenv("HISTCRAFT_SERVER_PROCESSES")
    assert Settings.from_environment().read_values == 4_000_000
