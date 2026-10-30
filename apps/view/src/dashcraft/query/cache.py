"""A small time-to-live cache: one read of plant data serves every viewer for a few seconds.

A wall screen and twenty open browsers on the same dashboard cost PlantCraft
one read per card per ``ttl`` seconds, not one per browser. Failures are not
cached: the next viewer asks again.

Expired entries leave as soon as any value is stored, not only when the count is over
``max_entries``: a diagram's window of series is megabytes, and thousands of them kept past
their few seconds filled the container's memory until the kernel stopped it (public demo,
2026-10-29).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any

MAX_ENTRIES = 4096


class TtlCache:
    def __init__(self, ttl: float, max_entries: int = MAX_ENTRIES, clock=time.monotonic):
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        # One load per key at a time: twenty browsers opening the same diagram together wait for
        # the first one's read instead of each asking PlantCraft (and holding a copy) at once.
        self._loading: dict[Hashable, threading.Lock] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable, load: Callable[[], Any]) -> Any:
        if self.ttl <= 0:
            return load()
        found, value = self._fresh(key)
        if found:
            return value
        with self._lock:
            loading = self._loading.setdefault(key, threading.Lock())
        with loading:
            found, value = self._fresh(key)
            if found:
                return value
            with self._lock:
                self.misses += 1
            try:
                value = load()
                self._store(key, value)
            finally:
                with self._lock:
                    self._loading.pop(key, None)
        return value

    def _fresh(self, key: Hashable) -> tuple[bool, Any]:
        now = self._clock()
        with self._lock:
            entry = self._items.get(key)
            if entry is not None and entry[0] > now:
                self._items.move_to_end(key)
                self.hits += 1
                return True, entry[1]
        return False, None

    def _store(self, key: Hashable, value: Any) -> None:
        with self._lock:
            now = self._clock()
            for stale in [item for item, (until, _) in self._items.items() if until <= now]:
                del self._items[stale]
            self._items[key] = (now + self.ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
