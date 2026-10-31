"""How many values the Historian builds into answers at once: long reads in memory, bounded.

A series answer lives in Python as lists (a time text and a number per value, about 110 bytes
each) and then as JSON; one raw day of 20 fast signals is over a million values, about 220 MB
built the plain way. Several such reads at once took the Historian past its memory limit
(2 GiB on the Mac mini, 2026-10-27), and the container restarted. Two things keep it bounded:

- ``EncodedBatch`` turns each series into JSON as soon as it is read, so a batch keeps one
  series' lists at a time and the rest as compact text (about 45 bytes a value);
- ``ReadBudget`` lets the reads in flight build at most ``HISTCRAFT_READ_VALUES`` values
  together (default 4 million, about 200 MB of answers); a read past it waits for the others,
  and after ``HISTCRAFT_QUERY_TIMEOUT`` answers 503, which the SDK's client asks again. A
  single read larger than the whole budget still runs, alone.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException
from fastapi.responses import Response
from plantcraft_sdk.contract import BatchBuilder
from plantcraft_sdk.wire import MEDIA_TYPE, BinaryWriter, read_binary

from histcraft.i18n import t

DEFAULT_VALUES = 4_000_000


def json_bytes(item: Any) -> bytes:
    """JSON as Starlette's JSONResponse writes it."""

    return json.dumps(
        item, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
    ).encode("utf-8")


class ReadBudget:
    """Values the answers in flight may hold together; ``hold`` waits for room."""

    def __init__(self, values: int = DEFAULT_VALUES, wait_seconds: float = 30.0):
        self.values = max(1, int(values))
        self.wait_seconds = wait_seconds
        self.taken = 0
        self._room = threading.Condition()

    @contextmanager
    def hold(self) -> Iterator[Ticket]:
        ticket = Ticket(self)
        try:
            yield ticket
        finally:
            ticket.release()

    def _take(self, wanted: int) -> int:
        wanted = min(max(0, int(wanted)), self.values)
        if not wanted:
            return 0
        with self._room:
            if not self._room.wait_for(
                lambda: self.taken + wanted <= self.values, timeout=self.wait_seconds
            ):
                raise HTTPException(
                    503,
                    t("The Historian is busy with other long reads: try again in a moment."),
                    headers={"Retry-After": "5"},
                )
            self.taken += wanted
            return wanted

    def _give_back(self, count: int) -> None:
        if count:
            with self._room:
                self.taken -= count
                self._room.notify_all()


class Ticket:
    """One read's share of the budget, given back when the read is answered."""

    def __init__(self, budget: ReadBudget):
        self.budget = budget
        self.count = 0

    def take(self, values: int) -> None:
        self.count += self.budget._take(values)

    def release(self) -> None:
        self.budget._give_back(self.count)
        self.count = 0


class EncodedBatch(BatchBuilder):
    """``BatchBuilder`` whose series are JSON as soon as they are added (``response``)."""

    binary = False

    def __init__(self) -> None:
        super().__init__()
        self.encoded: list[bytes] = []

    def add(
        self,
        signal: str,
        kind: str,
        stamps: list[str],
        values: list[Any],
        extra: dict[str, Any] | None = None,
    ) -> None:
        # BatchBuilder's rule: the first series always, then none past the points budget.
        if self.full or (self.encoded and self.points + len(stamps) > self.budget):
            self.full = True
            self.postpone(signal)
            return
        self.points += len(stamps)
        item = {"signal": signal, "kind": kind, "t": stamps, "v": values, **(extra or {})}
        self.encoded.append(json_bytes(item))

    def payload(self) -> dict[str, Any]:
        """As a dict (tests, small answers): the series read back from their JSON."""

        return {"series": [json.loads(part) for part in self.encoded], "errors": self.errors}

    def response(self, more_errors: list[dict[str, Any]] | None = None) -> Response:
        errors = json_bytes(self.errors + (more_errors or []))
        body = b"".join([b'{"series":[', b",".join(self.encoded), b'],"errors":', errors, b"}"])
        self.encoded = []
        return Response(body, media_type="application/json")


class BinaryBatch(BatchBuilder):
    """``BatchBuilder`` whose answer is the binary format (``plantcraft_sdk.wire``): each
    series' arrays as they were read, no ISO text and no JSON per value."""

    binary = True

    def __init__(self) -> None:
        super().__init__()
        self.writer = BinaryWriter()

    def _room(self, signal: str, count: int) -> bool:
        if self.full or (self.writer.items and self.points + count > self.budget):
            self.full = True
            self.postpone(signal)
            return False
        self.points += count
        return True

    def add(
        self,
        signal: str,
        kind: str,
        stamps: Any,
        values: Any,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self._room(signal, len(stamps)):
            return
        if len(stamps) and isinstance(stamps[0], str):  # a run's times, as stored
            parsed = pd.to_datetime(list(stamps), utc=True, format="ISO8601")
            times = parsed.as_unit("ms").asi8
        else:
            times = np.asarray(stamps, dtype=np.int64)
        if kind == "number" and isinstance(values, np.ndarray):
            self.writer.numbers(signal, kind, times, values, extra)
        else:
            self.writer.labels(signal, kind, times, list(values), extra)

    def payload(self) -> dict[str, Any]:
        series, errors = read_binary(self.writer.body(self.errors))
        return {"series": series, "errors": errors}

    def response(self, more_errors: list[dict[str, Any]] | None = None) -> Response:
        body = self.writer.body(self.errors + (more_errors or []))
        self.writer = BinaryWriter()
        return Response(body, media_type=MEDIA_TYPE)
