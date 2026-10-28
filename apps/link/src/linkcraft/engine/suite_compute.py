"""The suite's compute workers for Analytics (PlantCraft docs/compute.md, plan D1-D10).

With ``LINKCRAFT_COMPUTE=suite`` the analyses and the code people write in blocks do not run in
this container, which holds the app key, but on PlantCraft's compute workers: in an executor of
this app's own image with no network and no secret, on this machine or another.

``SuitePool`` takes the place of ``ComputePool``: what a round hands it (one loop's analysis, a
chunk of signals to judge) waits a moment to travel with others (up to ``BATCH`` per task, D6)
and goes to PlantCraft as one compute task; each future gets its own answer. Only the functions
named in ``CALLS`` run on a worker, and only plain data crosses (``linkcraft.engine.wire``).
``priority`` sets the queue's order for what is sent inside it (the editor's Test first, the
replays last) and the run it belongs to (cancelled together). Where a task runs (the
algorithm's environment and size, PlantCraft docs/compute.md) comes from the ``compute`` of
what is sent (a loop's analysis carries its algorithm's), else from ``placement``. The blocks' side, and the
executor's handler, are ``linkcraft.api.compute``.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import functools
import json
import logging
import threading
import time
from collections.abc import Callable, Collection, Iterator
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures import as_completed as futures_completed
from typing import Any

from linkcraft.engine.compute import task_timeout
from linkcraft.engine.wire import decode, encode
from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)

# The functions a compute task may call, by name: nothing else is imported on the worker.
CALLS = {
    "linkcraft.loops.analysis:analyze_loop_task": "loop",
    "linkcraft.signals.engine:_assess_many": "signals",
    "linkcraft.api.compute:run_block_code": "code",
}
BATCH = 25
# What travels as one task whatever ``BATCH`` says: a chunk of signals already carries many
# (the signal checks size their chunks by ``processes``), so each goes to a slot of its own.
ALONE = frozenset({"signals"})
# The most one task carries (its job.json, unpacked): under the 64 MB a worker takes by default
# (PLANTCRAFT_COMPUTE_MAX_MB); a larger batch goes as several tasks.
MAX_TASK_BYTES = 48 * 1024 * 1024
LINGER_SECONDS = 0.05
# Tasks packed and sent at once: packing (JSON, gzip) takes a tenth of a second a task of 25
# signals, and one thread at a time held the workers back.
SENDERS = 4
ANSWERS = "answers.json"

_PRIORITY: contextvars.ContextVar[str] = contextvars.ContextVar("compute_priority", default="run")
_RUN: contextvars.ContextVar[str | None] = contextvars.ContextVar("compute_run", default=None)
DEFAULT_PLACEMENT = ("standard", "small")
_PLACEMENT: contextvars.ContextVar[tuple[str, str]] = contextvars.ContextVar(
    "compute_placement", default=DEFAULT_PLACEMENT
)


@contextlib.contextmanager
def placement(compute: dict[str, Any] | None) -> Iterator[None]:
    """What is sent to the workers in this block runs in this environment, on a machine of this
    size (``{"environment", "size"}``, an algorithm's ``compute``)."""

    token = _PLACEMENT.set(_placement_of(compute) or DEFAULT_PLACEMENT)
    try:
        yield
    finally:
        _PLACEMENT.reset(token)


def _placement_of(compute: Any) -> tuple[str, str] | None:  # noqa: ANN401
    if not isinstance(compute, dict):
        return None
    return (
        str(compute.get("environment") or DEFAULT_PLACEMENT[0]),
        str(compute.get("size") or DEFAULT_PLACEMENT[1]),
    )


@contextlib.contextmanager
def priority(name: str, run: str | None = None) -> Iterator[None]:
    """What is sent to the workers in this block goes with this priority (``interactive``,
    ``run``, ``backfill``) and run (cancelled together from the suite's Queue)."""

    token = _PRIORITY.set(name)
    run_token = _RUN.set(run) if run is not None else None
    try:
        yield
    finally:
        _PRIORITY.reset(token)
        if run_token is not None:
            _RUN.reset(run_token)


def interactive(function: Callable[..., Any]) -> Callable[..., Any]:
    """A route whose work someone waits for on the screen (the editor's Test): first in the
    workers' queue."""

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        with priority("interactive"):
            return function(*args, **kwargs)

    return wrapper


def call_name(function: Callable[[Any], Any]) -> str:
    name = f"{function.__module__}:{function.__qualname__}"
    if name not in CALLS:
        raise ValueError(f"{name} does not run on the suite's compute workers")
    return name


class ComputeTaskError(RuntimeError):
    """What a compute task answered instead of a value."""


@dataclasses.dataclass
class _Item:
    future: Future
    argument: Any
    added: float


class SuitePool:
    """``ComputePool``'s interface over the suite's compute workers."""

    def __init__(
        self,
        compute: Any,  # noqa: ANN401 - plantcraft_sdk.compute.ComputeClient
        *,
        processes: int = 8,
        batch: int = BATCH,
        linger: float = LINGER_SECONDS,
        timeout_seconds: float | None = None,
        extras: Callable[[list[Any]], dict[str, Any]] | None = None,
        max_task_bytes: int = MAX_TASK_BYTES,
    ):
        self.compute = compute
        self.max_task_bytes = max_task_bytes
        # What a task carries besides its items (the site's block versions its diagrams use).
        self.extras = extras
        # How many tasks run at once (callers size their chunks by it).
        self.processes = max(1, processes)
        # Chunks per process the callers cut (``ComputePool`` takes 4 to even out its
        # processes; here each chunk is a task, and a task costs a trip to PlantCraft).
        self.chunks_per_process = 1
        # Batches a caller keeps out at once: the next goes while the last answers come back.
        self.in_flight = 2
        self.batch = max(1, batch)
        self.linger = linger
        self.timeout_seconds = timeout_seconds
        self.disabled = False
        self._lock = threading.Lock()
        # (call, priority, run, environment, size) -> what waits to travel together.
        self._pending: dict[tuple[str, str, str | None, str, str], list[_Item]] = {}
        self._sent: dict[str, list[_Item]] = {}
        self._work = threading.Event()
        self._stop = threading.Event()
        self._senders = ThreadPoolExecutor(SENDERS, thread_name_prefix="compute-pack")
        self._threads = [
            threading.Thread(target=self._sender, name="compute-send", daemon=True),
            threading.Thread(target=self._receiver, name="compute-receive", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    # The caller's side ------------------------------------------------------------------------

    def submit(self, function: Callable[[Any], Any], argument: Any) -> Future:  # noqa: ANN401
        future: Future = Future()
        try:
            item = _Item(future, encode(argument), time.monotonic())
            where = (
                _placement_of(argument.get("compute")) if isinstance(argument, dict) else None
            ) or _PLACEMENT.get()
            key = (call_name(function), _PRIORITY.get(), _RUN.get(), *where)
        except Exception as exc:  # noqa: BLE001 - the caller reads it from the future
            future.set_exception(exc)
            return future
        with self._lock:
            self._pending.setdefault(key, []).append(item)
            full = len(self._pending[key]) >= self._batch_of(key[0])
        if full:
            self._work.set()
        return future

    def call(self, function: Callable[[Any], Any], argument: Any) -> Any:  # noqa: ANN401
        timeout = task_timeout()
        future = self.submit(function, argument)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            future.cancel()
            raise TimeoutError(
                t("The analysis ran past {seconds} s without finishing", seconds=f"{timeout:.0f}")
            ) from None

    def as_completed(
        self, futures: Collection[Future], timeout: float | None = None
    ) -> Iterator[tuple[Future, BaseException | None]]:
        """As ``ComputePool.as_completed``: when nothing finishes for ``timeout`` seconds, the
        rest are cancelled (on the workers too) and yielded with a ``TimeoutError``."""

        timeout = task_timeout() if timeout is None else timeout
        pending = set(futures)
        while pending:
            progressed = False
            try:
                for future in futures_completed(pending, timeout=timeout):
                    pending.discard(future)
                    progressed = True
                    try:
                        error = future.exception()
                    except CancelledError as exc:
                        error = exc
                    yield future, error
            except FutureTimeout:
                if not progressed:
                    break
        for future in pending:
            future.cancel()
            yield (
                future,
                TimeoutError(
                    t(
                        "The analysis ran past {seconds} s without finishing",
                        seconds=f"{timeout or 0:.0f}",
                    )
                ),
            )

    def cancel_run(self, run: str) -> None:
        """What a run (an execution) still has here or on the workers stops."""

        with self._lock:
            for key, items in list(self._pending.items()):
                if key[2] == run:
                    for item in items:
                        item.future.cancel()
        self.compute.cancel_run(run)

    def shutdown(self) -> None:
        self._stop.set()
        self._work.set()
        self._senders.shutdown(wait=False)
        with self._lock:
            sent = list(self._sent)
            waiting = [item for items in self._pending.values() for item in items]
            waiting += [item for items in self._sent.values() for item in items]
            self._pending.clear()
            self._sent.clear()
        for task_id in sent:
            with contextlib.suppress(Exception):
                self.compute.cancel(task_id)
        for item in waiting:
            item.future.cancel()

    # To PlantCraft and back -------------------------------------------------------------------

    def _batch_of(self, call: str) -> int:
        return 1 if CALLS.get(call) in ALONE else self.batch

    def _ready(self) -> list[tuple[tuple[str, str, str | None, str, str], list[_Item]]]:
        now = time.monotonic()
        batches = []
        with self._lock:
            for key, items in list(self._pending.items()):
                live = [item for item in items if not item.future.cancelled()]
                if not live:
                    del self._pending[key]
                    continue
                size = self._batch_of(key[0])
                if len(live) < size and now - live[0].added < self.linger:
                    self._pending[key] = live
                    continue
                # Every full batch goes now; a part batch only once it has lingered.
                cut = max(size, len(live) // size * size)
                batches += [(key, live[start : start + size]) for start in range(0, cut, size)]
                rest = live[cut:]
                if rest:
                    self._pending[key] = rest
                else:
                    del self._pending[key]
        return batches

    def _send(self, key: tuple[str, str, str | None, str, str], items: list[_Item]) -> None:
        name, level, run, environment, size = key
        if self._stop.is_set():
            for item in items:
                item.future.cancel()
            return
        job = {"call": name, "items": [item.argument for item in items]}
        if self.extras is not None:
            job.update(self.extras([item.argument for item in items]))
        text = json.dumps(job, separators=(",", ":"))
        if len(text) > self.max_task_bytes:
            # Too much for one task (1000 loops of a long window): halves, until each fits.
            if len(items) > 1:
                half = len(items) // 2
                self._send(key, items[:half])
                self._send(key, items[half:])
                return
            if not items[0].future.done():
                items[0].future.set_exception(
                    ComputeTaskError(
                        t(
                            "The data of one analysis is larger than a compute task takes"
                            " ({size} MB of {limit} MB): shorten its window.",
                            size=f"{len(text) / 1048576:.0f}",
                            limit=f"{self.max_task_bytes / 1048576:.0f}",
                        )
                    )
                )
            return
        try:
            task_id = self.compute.submit(
                {"job.json": text},
                kind=CALLS[name],
                priority=level,
                run=run,
                timeout_seconds=self.timeout_seconds,
                environment=environment,
                size=size,
            )
        except Exception as exc:  # noqa: BLE001 - each waiting caller gets the reason
            for item in items:
                if not item.future.done():
                    item.future.set_exception(
                        ComputeTaskError(
                            t(
                                "PlantCraft's compute queue did not take the work: {error}",
                                error=exc,
                            )
                        )
                    )
            return
        with self._lock:
            stopped = self._stop.is_set()
            if not stopped:
                self._sent[task_id] = items
        if stopped:  # shut down while it was sent
            with contextlib.suppress(Exception):
                self.compute.cancel(task_id)
            for item in items:
                item.future.cancel()

    def _sender(self) -> None:
        while not self._stop.is_set():
            self._work.wait(self.linger)
            self._work.clear()
            for key, items in self._ready():
                self._senders.submit(self._send, key, items)

    def _settle(self, task: dict[str, Any]) -> None:
        task_id = str(task["id"])
        with self._lock:
            items = self._sent.pop(task_id, None)
        if items is None:
            return
        try:
            answer = self.compute.answer(task)
            answers = json.loads(answer.files.get(ANSWERS, b"[]")) if answer.ok else []
        except Exception as exc:  # noqa: BLE001
            answer, answers = None, []
            reason = f"{type(exc).__name__}: {exc}"
        else:
            reason = answer.error or answer.status
        for index, item in enumerate(items):
            if item.future.done():
                continue
            given = answers[index] if index < len(answers) else None
            if not given:
                item.future.set_exception(ComputeTaskError(reason or "no answer"))
            elif given.get("ok"):
                try:
                    item.future.set_result(decode(given.get("value")))
                except Exception as exc:  # noqa: BLE001
                    item.future.set_exception(exc)
            else:
                item.future.set_exception(ComputeTaskError(str(given.get("error") or "")))

    def _receiver(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                abandoned = [
                    task_id
                    for task_id, items in self._sent.items()
                    if all(item.future.cancelled() for item in items)
                ]
                for task_id in abandoned:
                    del self._sent[task_id]
                ids = list(self._sent)
            for task_id in abandoned:
                with contextlib.suppress(Exception):
                    self.compute.cancel(task_id)
            if not ids:
                self._stop.wait(self.linger)
                continue
            try:
                tasks = self.compute.wait(ids, 5.0)
            except Exception as exc:  # noqa: BLE001 - PlantCraft restarting: try again
                LOGGER.warning("compute: %s", exc)
                self._stop.wait(2.0)
                continue
            for task in tasks:
                if task.get("status") in ("done", "failed", "cancelled"):
                    self._settle(task)


__all__ = [
    "ANSWERS",
    "BATCH",
    "CALLS",
    "ComputeTaskError",
    "SuitePool",
    "call_name",
    "interactive",
    "placement",
    "priority",
]
