"""Freed memory goes back to the system: release() gives back what glibc keeps in its heaps."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from plantcraft_sdk.server import memory

GLIBC = sys.platform.startswith("linux") and memory._trim() is not None

# A thread builds 200 MB of 2 kB blocks and keeps one in twenty: the heap is full of holes that
# free() alone does not give back (the Analytics engine's rounds, in small).
FRAGMENTED_HEAP = textwrap.dedent(
    """
    import gc, threading
    from plantcraft_sdk.server.memory import release

    def anon_mb():
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("RssAnon:"):
                    return int(line.split()[1]) / 1024

    kept = []

    def work():
        blocks = [bytes(2048) for _ in range(100_000)]
        kept.extend(blocks[::20])

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    gc.collect()
    before = anon_mb()
    assert release()
    print(before, anon_mb())
    """
)


@pytest.mark.skipif(not GLIBC, reason="malloc_trim is glibc's")
def test_release_gives_a_fragmented_heap_back():
    found = subprocess.run(
        [sys.executable, "-c", FRAGMENTED_HEAP],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(memory.__file__).parents[2])},
    )
    before, after = (float(value) for value in found.stdout.split())
    assert before > 150
    assert after < before / 2, (before, after)


def test_release_says_when_the_allocator_cannot(monkeypatch):
    monkeypatch.setattr(memory, "_trim", lambda: None)
    assert memory.release() is False
    assert memory.Releaser(0.01).start()._thread is None


@pytest.mark.skipif(not GLIBC, reason="malloc_trim is glibc's")
def test_releaser_calls_release_until_stopped(monkeypatch):
    calls = threading.Event()
    monkeypatch.setattr(memory, "release", lambda: calls.set() or True)
    releaser = memory.Releaser(0.01).start()
    assert calls.wait(2)
    releaser.stop()
    assert releaser._thread is None
