"""Raw samples of signals for the signal quality checks, read only through PlantCraft API v1.

LinkCraft never opens a historian or an OPC UA connection. (The loop methods read a regular
grid instead, ``data.plant``.) Samples come from
``POST /api/v1/series`` without ``step``: the values as the source recorded
them, because resampling hides exactly what the checks look for (gaps, frozen
values, spikes). A signal whose window holds more than the contract allows
(200,000 points, a 422 for that signal) is read again as one mean per step and
flagged ``resampled``, so the checks that need raw samples know.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from plantcraft_sdk.client import PlantCraftClient, PlantCraftError, error_for
from plantcraft_sdk.derived import split_derived

LOGGER = logging.getLogger(__name__)
TOO_MANY_POINTS = 422
# Signals per batch request (the contract allows 500; smaller batches stream better).
BATCH = 200


# Sources that are not the plant's live measurements: the suite's own health (written by PlantCraft)
# and a CSV file imported once (its data ends where the file ends, so it is always "stale").
NOT_MEASURED = frozenset({"system", "import"})


def is_derived(signal: dict[str, Any]) -> bool:
    return bool(signal.get("app")) or split_derived(str(signal.get("id") or "")) is not None


def is_measured(signal: dict[str, Any]) -> bool:
    """A live measurement of the plant: what Signal quality judges."""

    return not is_derived(signal) and signal.get("source_kind") not in NOT_MEASURED


def naive_utc(value: Any) -> pd.Timestamp:
    """Any instant as a naive UTC ``Timestamp`` (naive input is taken as UTC)."""

    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def iso_utc(value: Any) -> str:
    return naive_utc(value).tz_localize("UTC").isoformat()


def _naive_index(values: pd.Series) -> pd.Series:
    values = values.copy()
    index = pd.DatetimeIndex(values.index)
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    values.index = index
    return values


@dataclass
class Samples:
    """One read: samples per signal id, the ones read as means, and the failures."""

    series: dict[str, pd.Series] = field(default_factory=dict)
    resampled: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)


class SignalReader:
    """Reads signals through one ``PlantCraftClient`` (the app's, or a person's)."""

    def __init__(self, client: PlantCraftClient):
        self.client = client

    def signals(self) -> list[dict[str, Any]]:
        """The plant's measured signals: derived ones (series apps computed, such as LinkCraft's
        own quality scores), the suite's health and one-time imports are not live plant data and
        are never checked."""

        return [item for item in self.client.signals() if is_measured(item)]

    def assets(self) -> list[dict[str, Any]]:
        return list(self.client.assets())

    def asset(self, asset_id: str) -> dict[str, Any]:
        return dict(self.client.asset(asset_id))

    def signal(self, signal_id: str) -> dict[str, Any]:
        return dict(self.client.signal(signal_id))

    def read(
        self,
        signal_ids: Iterable[str],
        start: Any,
        end: Any,
        *,
        fallback_step: float = 60.0,
        step: float | None = None,
    ) -> Samples:
        """Recorded samples of every signal in ``[start, end]`` (naive UTC index); with ``step``,
        means over ``step`` seconds instead."""

        names = list(dict.fromkeys(item for item in signal_ids if item))
        found = Samples()
        start_at = naive_utc(start).tz_localize("UTC").to_pydatetime()
        end_at = naive_utc(end).tz_localize("UTC").to_pydatetime()
        for offset in range(0, len(names), BATCH):
            chunk = names[offset : offset + BATCH]
            columns, errors = self.client.series_many_pandas(chunk, start_at, end_at, step=step)
            if step:
                found.resampled.update(columns)
            crowded = [item["signal"] for item in errors if item["status"] == TOO_MANY_POINTS]
            if crowded:
                means, again = self.client.series_many_pandas(
                    crowded, start_at, end_at, step=fallback_step
                )
                columns.update(means)
                found.resampled.update(means)
                errors = [item for item in errors if item["status"] != TOO_MANY_POINTS] + again
            down = [item for item in errors if int(item["status"]) >= 500]
            if down and len(down) == len(chunk):
                raise error_for(int(down[0]["status"]), down[0].get("detail"))
            for item in errors:
                found.failed[item["signal"]] = str(
                    error_for(int(item["status"]), item.get("detail"))
                )
            for signal_id, values in columns.items():
                found.series[signal_id] = _naive_index(values).dropna()
        return found

    def data_end(self, signal_ids: Iterable[str]) -> pd.Timestamp:
        """Where the newest data is: now for a live plant, the last sample of a recorded one.

        The newest of a few signals' last samples, never later than now: one live
        signal is enough to judge every other one's freshness against the clock.
        """

        now = naive_utc(datetime.now(timezone.utc))
        found: list[pd.Timestamp] = []
        for signal_id in list(dict.fromkeys(signal_ids))[:5]:
            try:
                answer = self.client.value(signal_id, "last", "7d")
            except PlantCraftError as exc:
                LOGGER.info("No latest value for %s: %s", signal_id, exc)
                continue
            if answer.get("at"):
                try:
                    found.append(naive_utc(answer["at"]))
                except (TypeError, ValueError):
                    continue
        return min(max(found), now) if found else now


def thin(values: pd.Series, limit: int) -> pd.Series:
    """At most about ``limit`` points, keeping each slice's minimum and maximum (spikes stay)."""

    if len(values) <= limit or limit < 4:
        return values
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().all():
        return values.iloc[:: math.ceil(len(values) / limit)]
    slices = max(1, limit // 2)
    slot = (pd.RangeIndex(len(values)) * slices // len(values)).to_numpy()
    keep: set[int] = set()
    grouped = pd.Series(numeric.to_numpy()).groupby(slot)
    for positions in (grouped.idxmin(), grouped.idxmax()):
        keep.update(int(item) for item in positions.dropna())
    return values.iloc[sorted(keep)]
