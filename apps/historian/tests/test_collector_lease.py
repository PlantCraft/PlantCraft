"""One collector per archive: a second one waits as a standby and takes over (collector.lease)."""

from __future__ import annotations

import asyncio
import time

import pytest

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.store import CatalogStore
from histcraft.collector import service
from histcraft.collector.lease import Lease, lease_for
from histcraft.collector.service import Collector, CollectorThread
from histcraft.db import Database
from tests.conftest import TEST_DATABASE_URL, database, make_settings


def wait_for(check, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def collector(tmp_path) -> Collector:
    settings = make_settings(tmp_path)
    return Collector(
        settings,
        CatalogStore(Database(settings.config_target)),
        ArchiveStore(Database(settings.archive_target)),
    )


def counting_flushes(item: Collector) -> list[int]:
    calls: list[int] = []
    flush = item.flush

    def counted() -> int:
        calls.append(1)
        return flush()

    item.flush = counted
    return calls


def test_the_lease_is_held_by_one_holder_at_a_time(tmp_path):
    archive = database(tmp_path)
    first, second = lease_for(archive), lease_for(archive)
    assert first.acquire()
    assert first.alive()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    assert not first.acquire()
    second.release()


def test_a_second_collector_waits_and_takes_over(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "LEASE_RETRY_SECONDS", 0.1)
    active, standby = collector(tmp_path), collector(tmp_path)
    active_flushes, standby_flushes = counting_flushes(active), counting_flushes(standby)
    first, second = CollectorThread(active), CollectorThread(standby)
    first.start()
    try:
        wait_for(lambda: len(active_flushes) >= 2)
        second.start()
        time.sleep(1.0)
        # The standby never wrote while the first one held the archive.
        assert standby_flushes == []
        first.stop()
        wait_for(lambda: len(standby_flushes) >= 2)
    finally:
        first.stop()
        second.stop()


def test_a_lost_lease_stops_collection(tmp_path):
    class Dropped(Lease):
        def __init__(self):
            self.released = False

        def acquire(self) -> bool:
            return True

        def alive(self) -> bool:
            return False

        def release(self) -> None:
            self.released = True

    item = collector(tmp_path)
    item.lease = Dropped()
    assert asyncio.run(asyncio.wait_for(item.run(), 10)) is False
    assert item.lease.released


@pytest.mark.skipif(bool(TEST_DATABASE_URL), reason="SQLite files only")
def test_housekeeping_is_refused_while_a_collector_runs(tmp_path, monkeypatch, capsys):
    from histcraft.cli import main

    monkeypatch.setenv("HISTCRAFT_DATA_DIR", str(tmp_path))
    running = lease_for(Database(tmp_path / "archive.sqlite3"))
    assert running.acquire()
    try:
        assert main(["housekeeping"]) == 1
        assert "collector is running" in capsys.readouterr().out
    finally:
        running.release()
    assert main(["housekeeping"]) == 0
