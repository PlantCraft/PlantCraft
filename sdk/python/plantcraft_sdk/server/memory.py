"""Give the memory a long process has freed back to the system.

A Python process that builds and drops large structures (an Analytics round over 2,000 loops, a
batch read of 8,000 signals) frees them, but glibc's allocator keeps the freed pages inside its
heaps, spread over one arena per thread, for the next allocation. The resident size then climbs
round after round toward the largest peak any thread has seen and stays there: it looks like a
leak, and the container's limit counts it. Measured at plant scale (2,050 loops, 2026-10-27), one
``malloc_trim`` gave back 22 % of the Analytics engine (1,115 to 873 MB) and 41 % of PlantCraft's
four API workers (1,044 to 617 MB).

- ``release()``: ``malloc_trim(0)`` once (glibc only; ``False`` elsewhere: macOS, musl, Windows).
  Call it after a large piece of work.
- ``Releaser``: a daemon thread that calls it every ``seconds`` (60 by default) while the process
  runs. Every app server ``web.mount`` starts runs one, and so does PlantCraft's.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys
import threading
from functools import lru_cache
from typing import Any

LOGGER = logging.getLogger(__name__)
RELEASE_SECONDS = 60.0


@lru_cache(maxsize=1)
def _trim() -> Any:  # noqa: ANN401 - a ctypes function, or None
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        trim = libc.malloc_trim
    except (OSError, AttributeError):  # musl has no malloc_trim
        return None
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int
    return trim


def release() -> bool:
    """Give the freed heap pages back to the system; ``False`` where the allocator cannot."""

    trim = _trim()
    if trim is None:
        return False
    try:
        trim(0)
    except Exception:  # noqa: BLE001 - never worth failing the caller
        LOGGER.debug("malloc_trim failed", exc_info=True)
        return False
    return True


class Releaser:
    """``release()`` every ``seconds`` in a daemon thread, until ``stop()``."""

    def __init__(self, seconds: float = RELEASE_SECONDS):
        self.seconds = seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> Releaser:
        if self._thread is None and _trim() is not None:
            self._thread = threading.Thread(target=self._run, name="memory-release", daemon=True)
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.seconds):
            release()


__all__ = ["RELEASE_SECONDS", "Releaser", "release"]
