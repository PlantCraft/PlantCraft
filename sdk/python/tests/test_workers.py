"""Several server processes for one app (``plantcraft_sdk.server.workers``)."""

from __future__ import annotations

import threading

from plantcraft_sdk.server.store import journal_mode
from plantcraft_sdk.server.workers import Leader, available_cpus, worker_count


def test_available_cpus_reads_the_container_limit(tmp_path):
    (tmp_path / "cpu.max").write_text("150000 100000\n")
    assert available_cpus(tmp_path) == 2  # 1.5 CPUs: two processes still help
    (tmp_path / "cpu.max").write_text("max 100000\n")
    assert available_cpus(tmp_path) >= 1  # no limit: the CPUs it may run on
    v1 = tmp_path / "v1"
    (v1 / "cpu").mkdir(parents=True)
    (v1 / "cpu" / "cpu.cfs_quota_us").write_text("300000\n")
    (v1 / "cpu" / "cpu.cfs_period_us").write_text("100000\n")
    assert available_cpus(v1) == 3


def test_worker_count_from_the_setting_or_auto(tmp_path, monkeypatch):
    journal_mode.cache_clear()
    monkeypatch.setenv("PLANTCRAFT_SQLITE_JOURNAL", "wal")
    assert worker_count("APP_WORKERS", {"APP_WORKERS": "3"}) == 3
    assert worker_count("APP_WORKERS", {"APP_WORKERS": "99"}) == 8
    assert worker_count("APP_WORKERS", {"APP_WORKERS": "0"}) == 1
    assert worker_count("APP_WORKERS", {"APP_WORKERS": "many"}, auto=2) == 2
    assert worker_count("APP_WORKERS", {}, auto=2) == 2
    assert worker_count("APP_WORKERS", {"APP_WORKERS": "4"}, folder=tmp_path) == 4
    journal_mode.cache_clear()
    # A Docker Desktop bind mount (or a share): locks do not hold between processes there.
    monkeypatch.setenv("PLANTCRAFT_SQLITE_JOURNAL", "truncate")
    assert worker_count("APP_WORKERS", {"APP_WORKERS": "4"}, folder=tmp_path) == 1
    journal_mode.cache_clear()


def test_one_leader_at_a_time(tmp_path):
    first, second = Leader(tmp_path), Leader(tmp_path)
    assert first.acquire() and first.held
    assert not second.acquire()
    first.release()
    assert second.wait(threading.Event()) and second.held
    second.release()
