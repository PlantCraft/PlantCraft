"""Run an asyncio server of the kit in a thread of its own, for a check written as plain code."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, Self


class Background:
    """``with Background(start, stop):`` runs ``await start()`` in a thread's event loop and
    ``await stop()`` on exit. ``call(coroutine factory)`` runs one more coroutine there."""

    def __init__(
        self,
        start: Callable[[], Awaitable[Any]],
        stop: Callable[[], Awaitable[Any]],
        *,
        timeout: float = 20.0,
    ):
        self._start, self._stop, self._timeout = start, stop, timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)

    def call(self, factory: Callable[[], Awaitable[Any]]) -> Any:
        future = asyncio.run_coroutine_threadsafe(factory(), self._loop)
        return future.result(self._timeout)

    def __enter__(self) -> Self:
        self._thread.start()
        self.call(self._start)
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            self.call(self._stop)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(self._timeout)
            self._loop.close()
