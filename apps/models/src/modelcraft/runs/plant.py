"""The plant's history for a simulation: the inputs as a CSV for omc and the series to compare.

Read through PlantCraft by whoever asks: a person's token for a simulation started on a page, the
app's service token for a tracking (``runs/tracking.py``). The model's time 0 is the period's
start.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from modelcraft.i18n import t

MAX_PLANT_SECONDS = 31 * 24 * 3600
MAX_PLANT_POINTS = 100_000

# (signals, start, end, step) -> PlantCraft's ``series_many`` answer.
SeriesReader = Callable[[list[str], datetime, datetime, float], dict[str, Any]]


class PlantError(ValueError):
    """The period or a signal cannot feed the simulation (said to the person as it is)."""


def utc(moment: datetime) -> datetime:
    return (
        moment.replace(tzinfo=timezone.utc)
        if moment.tzinfo is None
        else moment.astimezone(timezone.utc)
    )


def _seconds(stamp: str, origin: datetime) -> float | None:
    try:
        return (utc(datetime.fromisoformat(stamp.replace("Z", "+00:00"))) - origin).total_seconds()
    except ValueError:
        return None


def read_plant(
    read: SeriesReader,
    start: datetime,
    end: datetime,
    step: float | None,
    inputs: dict[str, str],
    compare: dict[str, str],
) -> tuple[dict[str, bytes], dict[str, Any], float]:
    """(the inputs CSV for omc, the comparison series, the period's length in seconds)."""

    start, end = utc(start), utc(end)
    duration = (end - start).total_seconds()
    if duration <= 0 or duration > MAX_PLANT_SECONDS:
        raise PlantError(t("The plant period must be from a minute to 31 days long."))
    step = step or max(1.0, duration / 5000)
    if duration / step > MAX_PLANT_POINTS:
        raise PlantError(t("Use a longer step: the period would have more than 100,000 points."))
    signals = list(dict.fromkeys([*inputs.values(), *compare.values()]))
    if not signals:
        return {}, {}, duration
    batch = read(signals, start, end, step)
    if batch.get("errors"):
        first = batch["errors"][0]
        raise PlantError(
            t(
                "Signal {signal} could not be read: {detail}",
                signal=first.get("signal"),
                detail=first.get("detail"),
            )
        )
    found: dict[str, list[tuple[float, float]]] = {}
    for item in batch.get("series") or []:
        points = []
        for stamp, value in zip(item.get("t") or [], item.get("v") or [], strict=False):
            seconds = _seconds(str(stamp), start)
            if seconds is not None and isinstance(value, (int, float)) and math.isfinite(value):
                points.append((seconds, float(value)))
        found[item["signal"]] = points
    extra: dict[str, bytes] = {}
    if inputs:
        for signal in inputs.values():
            if len(found.get(signal) or []) < 1:
                raise PlantError(t("Signal {signal} has no values in this period.", signal=signal))
        times = sorted(
            {0.0, duration, *(s for signal in inputs.values() for s, _ in found[signal])}
        )
        times = [s for s in times if 0 <= s <= duration]
        columns = []
        for signal in inputs.values():
            points = found[signal]
            column, index, last = [], 0, points[0][1]
            for moment in times:
                while index < len(points) and points[index][0] <= moment:
                    last = points[index][1]
                    index += 1
                column.append(last)  # the last value held: what the plant recorded until then
            columns.append(column)
        buffer = io.StringIO()
        buffer.write(",".join(["time", *inputs]) + "\n")
        for row, moment in enumerate(times):
            buffer.write(
                ",".join([repr(moment), *(repr(column[row]) for column in columns)]) + "\n"
            )
        extra["inputs.csv"] = buffer.getvalue().encode()
    series = {
        name: {
            "signal": signal,
            "time": [s for s, _ in found.get(signal, [])],
            "values": [v for _, v in found.get(signal, [])],
        }
        for name, signal in compare.items()
    }
    return extra, series, duration
