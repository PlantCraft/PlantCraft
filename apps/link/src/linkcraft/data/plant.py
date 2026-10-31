"""Plant data, read only through PlantCraft API v1 (``plantcraft_sdk.client``).

Analytics never opens a historian or an OPC UA connection: every sample comes
from ``POST /api/v1/series`` (many signals per request, ``series_many``). This
module turns those series into the wide, time-indexed frame (naive UTC, one
column per signal id) that ``frames.build_loop_frame`` resamples for the
methods, as the monolith's data sources did.

Recorded values are asked for first, because the data quality gate needs the
samples as the source stored them (resampling hides gaps and frozen values).
A signal whose window holds more than the contract allows (200,000 points, a
422 for that signal) is asked again as one mean per resampling step.

Mode signals reach the methods as text: a ``"kind": "text"`` signal keeps its
labels (``"AUTO"``, ``"MAN"``); a numeric mode becomes ``"1"``/``"0"``.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from plantcraft_sdk.client import PlantCraftClient, PlantCraftError, error_for
from plantcraft_sdk.contract import SeriesError

from linkcraft.data.cache import RawCache, enabled_by_default, read_incremental

LOGGER = logging.getLogger(__name__)
# Batch requests in flight at once for one batch of loops, and the fewest signals one carries.
READ_THREADS = 4
MIN_SIGNALS_PER_REQUEST = 40
# A 422 for one signal of a batch: too many recorded values, ask for one mean per step.
TOO_MANY_POINTS = 422


def _naive_utc(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    return index


def mode_text(values: pd.Series) -> pd.Series:
    """A mode signal as labels: 1.0 -> "1", 0.0 -> "0", text kept (the manual-mode methods read text)."""

    def label(value: Any) -> Any:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        if isinstance(value, str):
            return value.strip() or None
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)

    return values.map(label).astype(object)


def utc_timestamp(value: Any) -> pd.Timestamp:
    """Any instant as a naive UTC ``Timestamp`` (naive input is taken as UTC)."""

    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def iso_utc(value: Any) -> str:
    return utc_timestamp(value).tz_localize("UTC").isoformat()


def _reason(error: SeriesError) -> str:
    return str(error_for(int(error["status"]), error.get("detail")))


def wide_frame(columns: dict[str, pd.Series]) -> pd.DataFrame:
    """``pd.concat(columns, axis=1).sort_index()`` of series on naive, unique, sorted times,
    built as one block: about 10x faster on 200 signals of a raw day, which have almost no
    time in common (the frame is mostly NaN, and concat aligns them pair by pair)."""

    stamps = np.unique(np.concatenate([values.index.asi8 for values in columns.values()]))
    index = pd.DatetimeIndex(stamps.view("datetime64[ns]"))
    numbers = [key for key, values in columns.items() if values.dtype != object]
    block = np.full((len(stamps), len(numbers)), np.nan, order="F")
    for position, key in enumerate(numbers):
        values = columns[key]
        block[np.searchsorted(stamps, values.index.asi8), position] = values.to_numpy(dtype=float)
    frame = pd.DataFrame(block, index=index, columns=numbers, copy=False)
    if len(numbers) == len(columns):
        return frame
    for key, values in columns.items():
        if values.dtype == object:
            labels = np.full(len(stamps), np.nan, dtype=object)
            labels[np.searchsorted(stamps, values.index.asi8)] = values.to_numpy()
            frame[key] = labels
    return frame[list(columns)]


class Signals(dict[str, pd.Series]):
    """Series read together, by signal id (``PlantData.read_signals``)."""

    def __init__(self, series: dict[str, pd.Series], failed_tags: list[tuple[str, str]]):
        super().__init__(series)
        self.failed_tags = failed_tags

    def frame(self, signal_ids: Iterable[str]) -> pd.DataFrame:
        """These signals as ``read_range`` returns them: their own times only, one column each.

        A signal that was not read is left out; ``attrs["failed_tags"]`` lists every failure
        of the read.
        """

        shaped = {key: self[key] for key in dict.fromkeys(signal_ids) if key in self}
        frame = wide_frame(shaped) if shaped else pd.DataFrame(index=pd.DatetimeIndex([]))
        frame.attrs["failed_tags"] = self.failed_tags
        return frame


class PlantData:
    """Reads loops' signals through one ``PlantCraftClient`` (thread-safe)."""

    def __init__(
        self,
        client: PlantCraftClient,
        *,
        threads: int = READ_THREADS,
        cache: RawCache | None | bool = True,
    ):
        self.client = client
        self.threads = max(1, threads)
        # The rounds' reads ask only for what is new since the last one (``data.cache``).
        if cache is True:
            cache = RawCache() if enabled_by_default() else None
        self.cache: RawCache | None = cache or None

    def with_client(self, client: PlantCraftClient) -> PlantData:
        # A person's reads (a run, a chart) are their own: never served from the rounds' cache.
        return PlantData(client, threads=self.threads, cache=False)

    def _chunks(self, names: list[str]) -> list[list[str]]:
        """The signals split over at most ``threads`` requests of at least 40 signals each."""

        count = max(1, min(self.threads, len(names) // MIN_SIGNALS_PER_REQUEST))
        size = math.ceil(len(names) / count)
        return [names[offset : offset + size] for offset in range(0, len(names), size)]

    def _read(
        self, names: list[str], start: pd.Timestamp, end: pd.Timestamp, step: float
    ) -> tuple[dict[str, pd.Series], list[SeriesError]]:
        if self.cache is None:
            return self._read_whole(names, start, end, step)
        return read_incremental(
            self.cache,
            names,
            start,
            end,
            lambda group, begin, finish: self._read_whole(group, begin, finish, step),
        )

    def _read_whole(
        self,
        names: list[str],
        start: pd.Timestamp,
        end: pd.Timestamp,
        step: float,
    ) -> tuple[dict[str, pd.Series], list[SeriesError]]:
        start_at = start.tz_localize("UTC").to_pydatetime()
        end_at = end.tz_localize("UTC").to_pydatetime()
        columns, errors = self.client.series_many_pandas(names, start_at, end_at)
        crowded = [item["signal"] for item in errors if item["status"] == TOO_MANY_POINTS]
        if crowded:
            # Too many recorded values in the window: one mean per step instead.
            means, again = self.client.series_many_pandas(crowded, start_at, end_at, step=step)
            for values in means.values():
                values.attrs["means"] = True
            columns.update(means)
            errors = [item for item in errors if item["status"] != TOO_MANY_POINTS] + again
        return columns, errors

    def read_range(
        self,
        start: Any,
        end: Any,
        sample_seconds: float,
        *,
        tags: Iterable[str],
        text_signals: Iterable[str] = (),
    ) -> pd.DataFrame:
        """Recorded samples of ``tags`` in ``[start, end]``, one column per signal id.

        A signal PlantCraft does not know (404) or cannot read is left out
        and listed in ``frame.attrs["failed_tags"]`` as ``(signal id, reason)``;
        the batch fails (raises) only when every signal failed because
        PlantCraft or its data source could not answer. ``text_signals``
        (mode roles) come back as labels whatever their kind.
        """

        signals = self.read_signals(
            start, end, sample_seconds, tags=tags, text_signals=text_signals
        )
        return signals.frame(list(signals))

    def read_signals(
        self,
        start: Any,
        end: Any,
        sample_seconds: float,
        *,
        tags: Iterable[str],
        text_signals: Iterable[str] = (),
    ) -> Signals:
        """What ``read_range`` reads, one series per signal id and no frame yet.

        A round reads 50 loops at once; their raw samples share almost no time, so one frame
        of all of them is mostly empty (98% on a raw day). ``Signals.frame`` builds one
        loop's frame from its own signals instead.
        """

        start_at, end_at = utc_timestamp(start), utc_timestamp(end)
        names = list(dict.fromkeys(tag for tag in tags if tag))
        text = set(text_signals)
        columns: dict[str, pd.Series] = {}
        errors: list[SeriesError] = []
        chunks = self._chunks(names) if names else []
        if len(chunks) == 1:
            found = [self._read(chunks[0], start_at, end_at, sample_seconds)]
        elif chunks:
            with ThreadPoolExecutor(len(chunks)) as pool:
                found = list(
                    pool.map(
                        lambda part: self._read(part, start_at, end_at, sample_seconds), chunks
                    )
                )
        else:
            found = []
        for part_columns, part_errors in found:
            columns.update(part_columns)
            errors.extend(part_errors)
        down = [item for item in errors if int(item["status"]) >= 500]
        if names and down and len(down) == len(names):
            raise error_for(int(down[0]["status"]), down[0].get("detail"))
        failed = [(item["signal"], _reason(item)) for item in errors]
        shaped: dict[str, pd.Series] = {}
        for signal_id in names:
            values = columns.get(signal_id)
            if values is None:
                continue
            values = values.copy()
            values.index = _naive_utc(pd.DatetimeIndex(values.index))
            values = values.dropna()
            # One time twice (overlapping archive chunks) would fail the whole batch's frame.
            values = values[~values.index.duplicated(keep="last")]
            if signal_id in text or values.dtype == object:
                values = mode_text(values)
            shaped[signal_id] = values
        return Signals(shaped, failed)

    def data_end(self, signal_ids: Iterable[str], window_minutes: int) -> pd.Timestamp:
        """Where the newest data is: now for a live source, the last sample of a recorded one."""

        now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None)
        found: list[pd.Timestamp] = []
        for signal_id in list(dict.fromkeys(signal_ids))[:3]:
            try:
                answer = self.client.value(signal_id, "last", f"{max(1, int(window_minutes))}m")
            except PlantCraftError as exc:
                LOGGER.info("No latest value for %s: %s", signal_id, exc)
                continue
            if answer.get("at"):
                try:
                    found.append(utc_timestamp(answer["at"]))
                except (TypeError, ValueError):
                    continue
        return min(max(found), now) if found else now
