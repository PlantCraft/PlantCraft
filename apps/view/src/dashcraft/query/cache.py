"""A small time-to-live cache: one read of plant data serves every viewer for a few seconds.

A wall screen and twenty open browsers on the same dashboard cost PlantCraft
one read per card per ``ttl`` seconds, not one per browser. Failures are not
cached: the next viewer asks again.
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
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable, load: Callable[[], Any]) -> Any:
        if self.ttl <= 0:
            return load()
        now = self._clock()
        with self._lock:
            entry = self._items.get(key)
            if entry is not None and entry[0] > now:
                self._items.move_to_end(key)
                self.hits += 1
                return entry[1]
            self.misses += 1
        value = load()
        with self._lock:
            self._items[key] = (now + self.ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
