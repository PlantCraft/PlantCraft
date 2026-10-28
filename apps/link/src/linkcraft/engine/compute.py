"""Process pool for the CPU-heavy part of an analysis (the Python methods).

Python runs one thread at a time, so analysing thousands of loops in threads
uses a single core. The monitor and the job runner read data in threads and
hand each subject's computation to this pool, which spreads it over every core.

``LINKCRAFT_PROCESSES`` sets the number of worker processes; ``0`` runs the
computation in the calling thread (tests, small installations).
``LINKCRAFT_TASK_TIMEOUT_SECONDS`` bounds how long a caller waits for a
task (default 300; ``0`` waits forever); ``LINKCRAFT_TASK_MEMORY_MB`` how much memory each
worker process may take beyond its start (default 4096; ``0`` no limit).
"""

from __future__ import annotations

import itertools
import logging
import multiprocessing
import os
import threading
import time
from collections.abc import Callable, Collection, Iterator
from concurrent.futures import (
    CancelledError,
    Future,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
)
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)


def default_processes() -> int:
    configured = os.environ.get("LINKCRAFT_PROCESSES", "").strip()
    if configured.isdigit():
        return int(configured)
    cores = os.cpu_count() or 1
    # Leave one core for the web server and the reading threads.
    return 0 if cores <= 2 else min(cores - 1, 16)


# After this many broken pools in a row (no task finished in between) the work
# stays in threads: the processes cannot start.
MAX_BREAKS = 3
DEFAULT_TASK_TIMEOUT_SECONDS = 300.0
DEFAULT_TASK_MEMORY_MB = 4096.0


def task_timeout() -> float | None:
    configured = os.environ.get("LINKCRAFT_TASK_TIMEOUT_SECONDS", "").strip()
    try:
        seconds = float(configured) if configured else DEFAULT_TASK_TIMEOUT_SECONDS
    except ValueError:
        seconds = DEFAULT_TASK_TIMEOUT_SECONDS
    return seconds if seconds > 0 else None


# In a worker process: the shared slot where it writes the task it is running,
# so after a crash the server knows which tasks were running (the suspects)
# and which were only queued (innocent, run again freely).
_RUNNING: Any = None
_SLOT = 0


def task_memory_mb() -> float:
    """How much memory one worker may take beyond what it started with (``0``: no limit)."""

    configured = os.environ.get("LINKCRAFT_TASK_MEMORY_MB", "").strip()
    try:
        return max(0.0, float(configured)) if configured else DEFAULT_TASK_MEMORY_MB
    except ValueError:
        return DEFAULT_TASK_MEMORY_MB


def _limit_memory(megabytes: float) -> None:
    """A task that takes too much memory fails alone (``MemoryError``), never the machine."""

    if not megabytes:
        return
    try:
        import resource

        with open("/proc/self/status", encoding="ascii") as status:
            used = next(
                (int(line.split()[1]) * 1024 for line in status if line.startswith("VmSize:")), 0
            )
        if used:
            limit = int(used + megabytes * 1024 * 1024)
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):  # not Linux: the timeout still applies
        LOGGER.info("Analysis workers run without a memory limit on this system.")


def _worker_init(running: Any, counter: Any, memory_mb: float = 0.0) -> None:
    global _RUNNING, _SLOT
    with counter.get_lock():
        _SLOT = counter.value % len(running)
        counter.value += 1
    _RUNNING = running
    _limit_memory(memory_mb)


def _tracked(task: tuple[int, Callable[[Any], Any], Any]) -> Any:
    token, function, argument = task
    _RUNNING[_SLOT] = token
    try:
        return function(argument)
    finally:
        _RUNNING[_SLOT] = 0


class ComputePool:
    def __init__(self, processes: int | None = None):
        self.processes = default_processes() if processes is None else max(0, processes)
        self._pool: ProcessPoolExecutor | None = None
        self._running: Any = None
        self._generation = 0
        self._breaks = 0
        self.disabled = False
        self._closed = False
        self._tokens = itertools.count(1)
        self._lock = threading.Lock()
        self._fallback = ThreadPoolExecutor(
            max_workers=max(2, self.processes), thread_name_prefix="compute-fallback"
        )

    def _executor(self) -> tuple[ProcessPoolExecutor, int, Any]:
        with self._lock:
            if self._pool is None:
                # "spawn": a forked child would inherit locks held by server threads.
                context = multiprocessing.get_context("spawn")
                self._running = context.Array("q", self.processes, lock=False)
                self._pool = ProcessPoolExecutor(
                    max_workers=self.processes,
                    mp_context=context,
                    initializer=_worker_init,
                    initargs=(self._running, context.Value("i", 0), task_memory_mb()),
                )
                self._generation += 1
            return self._pool, self._generation, self._running

    def submit(self, function: Callable[[Any], Any], argument: Any) -> Future:
        """Run ``function(argument)`` in a worker process (inline when processes is 0).

        If the pool breaks (a worker killed, out of memory) the next tasks get
        a new pool. Tasks that were only queued run there again; a task that
        was running gets one more try and fails if it breaks that pool too.
        It never runs in the server process, which a task that kills its
        worker would kill. After ``MAX_BREAKS`` broken pools in a row the
        processes are given up and new tasks run in threads.
        """

        if self.processes == 0:
            future: Future = Future()
            self._inline(future, function, argument)
            return future
        if self.disabled:
            return self._fallback.submit(function, argument)
        proxy: Future = Future()
        self._dispatch(proxy, function, argument, retry=True)
        return proxy

    def _dispatch(
        self, proxy: Future, function: Callable[[Any], Any], argument: Any, *, retry: bool
    ) -> None:
        if proxy.done():  # the caller gave up on it
            return
        if self.disabled:
            # Only tasks that never ran get here: they cannot be what broke the pools.
            self._fallback.submit(self._inline, proxy, function, argument)
            return
        token = next(self._tokens)
        generation = self._generation
        try:
            pool, generation, running = self._executor()
            inner = pool.submit(_tracked, (token, function, argument))
        except (BrokenProcessPool, RuntimeError):
            # The pool broke (or was retired) before this task reached it.
            self._broken(generation)
            self._fallback.submit(self._dispatch, proxy, function, argument, retry=retry)
            return

        def relay(done: Future) -> None:
            # Runs in the pool's management thread, which holds the pool's
            # shutdown lock: anything that shuts a pool down goes to a thread.
            if proxy.done():
                return
            try:
                proxy.set_result(done.result())
                self._breaks = 0
            except CancelledError:
                # Never started (its pool was retired): safe to run elsewhere.
                if self._closed:
                    proxy.cancel()
                else:
                    self._fallback.submit(self._dispatch, proxy, function, argument, retry=retry)
            except BrokenProcessPool as exc:
                suspect = token in running[:]
                if suspect and not retry:
                    self._fallback.submit(self._broken, generation)
                    proxy.set_exception(exc)
                else:
                    self._fallback.submit(
                        self._retry, generation, proxy, function, argument, retry and not suspect
                    )
            except BaseException as exc:  # the caller reads it from the future
                proxy.set_exception(exc)

        inner.add_done_callback(relay)

    def _retry(
        self,
        generation: int,
        proxy: Future,
        function: Callable[[Any], Any],
        argument: Any,
        innocent: bool,
    ) -> None:
        self._broken(generation)
        if self._closed or (self.disabled and not innocent):
            proxy.set_exception(BrokenProcessPool(t("The analysis process was terminated")))
        else:
            self._dispatch(proxy, function, argument, retry=innocent)

    def call(self, function: Callable[[Any], Any], argument: Any) -> Any:
        timeout = task_timeout()
        future = self.submit(function, argument)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            self._retire(timeout)
            raise TimeoutError(
                t("The analysis ran past {seconds} s without finishing", seconds=f"{timeout:.0f}")
            ) from None

    def as_completed(
        self, futures: Collection[Future], timeout: float | None = None
    ) -> Iterator[tuple[Future, BaseException | None]]:
        """Yield each future with its error (``None`` on success) as it finishes.

        A hung task (a user method that never returns) must not stall a round:
        when no task finishes for ``timeout`` seconds (default
        ``task_timeout()``) the ones left are yielded with a ``TimeoutError``
        and the pool is retired, so its stuck workers do not hold later rounds.
        """

        timeout = task_timeout() if timeout is None else timeout
        pending = set(futures)
        while pending:
            progressed = False
            try:
                for future in as_completed(pending, timeout=timeout):
                    pending.discard(future)
                    progressed = True
                    try:
                        error = future.exception()
                    except CancelledError as exc:
                        error = exc
                    yield future, error
            except TimeoutError:
                if not progressed:
                    break
        if pending:
            LOGGER.error(
                "%d analyses ran past %.0f s without finishing; renewing the pool",
                len(pending),
                timeout,
            )
            self._retire(timeout)
            for future in pending:
                future.cancel()
                yield (
                    future,
                    TimeoutError(
                        t(
                            "The analysis ran past {seconds} s without finishing",
                            seconds=f"{timeout:.0f}",
                        )
                    ),
                )

    @staticmethod
    def _inline(future: Future, function: Callable[[Any], Any], argument: Any) -> None:
        try:
            future.set_result(function(argument))
        except BaseException as exc:
            future.set_exception(exc)

    def _broken(self, generation: int) -> None:
        """Drop the broken pool once, however many of its tasks report it."""

        with self._lock:
            if generation != self._generation or self._pool is None:
                return
            pool, self._pool = self._pool, None
            self._breaks += 1
            self.disabled = self._breaks >= MAX_BREAKS
        if self.disabled:
            LOGGER.error(
                "The process pool broke %d times; analyses continue in threads, more slowly",
                self._breaks,
            )
        else:
            LOGGER.warning("Process pool broke; renewing it and retrying the affected tasks")
        pool.shutdown(wait=False, cancel_futures=True)

    def _retire(self, grace: float | None) -> None:
        """Replace a pool whose workers are stuck; they are killed after ``grace`` seconds.

        Its queued tasks move to the new pool; the running ones get ``grace``
        seconds to finish before their processes are terminated.
        """

        with self._lock:
            pool, self._pool = self._pool, None
        if pool is None:
            return
        # Read before shutdown, which forgets them (there is no public way to kill workers).
        processes = list((getattr(pool, "_processes", None) or {}).values())

        def stop() -> None:
            pool.shutdown(wait=False, cancel_futures=True)
            time.sleep(grace or 0)
            for process in processes:
                if process.is_alive():
                    process.terminate()

        threading.Thread(target=stop, name="compute-retire", daemon=True).start()

    def _reset(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        self._closed = True
        self._reset()
        self._fallback.shutdown(wait=False, cancel_futures=True)
