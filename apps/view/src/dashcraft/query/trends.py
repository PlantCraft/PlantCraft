"""The data of a trend (``dashboards.trends``): every plot's lines over the trend's period."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.client import PlantCraftError, Unauthorized

from dashcraft.dashboards.model import CardItem, window_seconds
from dashcraft.dashboards.trends import TrendView
from dashcraft.i18n import t
from dashcraft.query.cards import Reader, _newest_sample, resolve, trend_step


def _read(
    reader: Reader, signals: list[str], start: Any, end: Any, step: int | None
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    try:
        batch = reader.client.series_many(signals, start, end, step)
    except Unauthorized:
        raise
    except PlantCraftError as exc:
        return {}, {signal: str(exc.detail) for signal in signals}
    answers = {item["signal"]: item for item in batch.get("series") or []}
    failures = {
        item["signal"]: t("Not found in PlantCraft.")
        if item.get("status") == 404
        else str(item.get("detail") or "")
        for item in batch.get("errors") or []
    }
    return answers, failures


# Raw samples one line may bring to be summarised here (min, max, last, first).
MAX_RAW_SAMPLES = 200_000


def _instant(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def summarise(
    t_values: list[str],
    v_values: list[Any],
    start: datetime,
    step: int,
    how: str,
    end: datetime | None = None,
) -> tuple[list[str], list[Any]]:
    """Samples as one value per ``step`` seconds from ``start`` (cells that start before
    ``end``): the last, first, min or max."""

    origin = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    last_cell = None if end is None else int(((end - origin).total_seconds() - 1e-9) // step)
    cells: dict[int, list[float]] = {}
    for stamp, value in zip(t_values, v_values, strict=False):
        if not isinstance(value, int | float) or isinstance(value, bool) or value != value:
            continue
        cell = int((_instant(stamp) - origin).total_seconds() // step)
        if cell < 0 or (last_cell is not None and cell > last_cell):
            continue
        cells.setdefault(cell, []).append(float(value))
    pick = {"last": lambda xs: xs[-1], "first": lambda xs: xs[0], "min": min, "max": max}[how]
    times, values = [], []
    for cell in sorted(cells):
        times.append((origin + timedelta(seconds=cell * step)).isoformat())
        values.append(pick(cells[cell]))
    return times, values


def _empty(answers: dict[Any, dict[str, Any]]) -> bool:
    return not any(any(v is not None for v in item.get("v") or []) for item in answers.values())


def _read_groups(
    reader: Reader, groups: dict[int, list[str]], start: Any, end: Any
) -> tuple[dict[tuple[int, str], dict[str, Any]], dict[tuple[int, str], str]]:
    """Each interval's signals in one batch: answers and failures keyed by (step, signal)."""

    answers: dict[tuple[int, str], dict[str, Any]] = {}
    failures: dict[tuple[int, str], str] = {}
    for step, signals in groups.items():
        found, failed = _read(reader, signals, start, end, step or None)
        answers.update({(step, signal): item for signal, item in found.items()})
        failures.update({(step, signal): text for signal, text in failed.items()})
    return answers, failures


def read_view(reader: Reader, view: TrendView) -> dict[str, Any]:
    """``{plots: [{title, lines}], range}``; a line is a card trend's line (label, unit, t, v).

    Each line reads at its own interval when it has one (``step_seconds``; 0 = as recorded),
    else at the trend's: PV every minute beside SP every hour. A relative period with no
    samples at all moves to end at the newest sample (a recorded file, a source that stopped),
    as a trend card does; ``range.shifted`` says so.
    """

    period = view.period
    if period.mode == "fixed":
        start, end = period.start, period.end
    else:
        end = reader.clock()
        start = end - timedelta(seconds=window_seconds(period.window))
    assert start is not None and end is not None
    seconds = int((end - start).total_seconds())
    step = view.step_seconds if view.step_seconds is not None else trend_step(seconds)

    def step_of(line: Any) -> int:
        return step if line.step_seconds is None else line.step_seconds

    plots: list[dict[str, Any]] = []
    groups: dict[int, list[str]] = {}
    resolved_plots = []
    for plot in view.plots:
        resolved = [
            resolve(reader, CardItem(signal_id=line.signal_id, label=line.label), None)
            for line in plot.lines
        ]
        resolved_plots.append(resolved)
        for spec, item in zip(plot.lines, resolved, strict=True):
            if item.error is None and item.signal_id:
                wanted = groups.setdefault(step_of(spec), [])
                if item.signal_id not in wanted:
                    wanted.append(item.signal_id)

    answers: dict[tuple[int, str], dict[str, Any]] = {}
    failures: dict[tuple[int, str], str] = {}
    shifted = False
    if groups:
        answers, failures = _read_groups(reader, groups, start, end)
        if period.mode == "relative" and not failures and _empty(answers):
            every = sorted({signal for signals in groups.values() for signal in signals})
            anchor = _newest_sample(reader, every)
            if anchor is not None and anchor < end - timedelta(seconds=step or 1):
                moved = _read_groups(reader, groups, anchor - (end - start), anchor)
                if not moved[1]:
                    answers, failures = moved
                    start, end, shifted = anchor - (end - start), anchor, True

    # Lines summarised otherwise than by the mean read the samples and summarise them here.
    raw: dict[str, dict[str, Any]] = {}
    raw_failures: dict[str, str] = {}
    other = sorted(
        {
            item.signal_id
            for plot, resolved in zip(view.plots, resolved_plots, strict=True)
            for spec, item in zip(plot.lines, resolved, strict=True)
            if spec.agg != "mean"
            and step_of(spec)
            and item.meta.get("kind") != "text"
            and (step_of(spec), item.signal_id) in answers
        }
    )
    if other:
        raw, raw_failures = _read(reader, other, start, end, None)

    for plot, resolved in zip(view.plots, resolved_plots, strict=True):
        lines = []
        for spec, item in zip(plot.lines, resolved, strict=True):
            own = step_of(spec)
            key = (own, item.signal_id or "")
            line = {
                **item.base(),
                "t": [],
                "v": [],
                "agg": spec.agg if own else "recorded",
                "step": own,
                "style": spec.style.model_dump(),
                "note": None,
            }
            if line["error"] is None and key in failures:
                line["error"] = failures[key]
            elif line["error"] is None and item.signal_id:
                answer = answers.get(key) or {}
                line["t"], line["v"] = answer.get("t") or [], answer.get("v") or []
                if item.meta.get("kind") == "text":
                    # A state (a mode, a running/stopped flag): its label per interval, drawn
                    # as a band of states under the lines (journey review 2026-10-23).
                    line["agg"] = "last" if own else "recorded"
                elif own and spec.agg != "mean":
                    samples = raw.get(item.signal_id)
                    if samples is None or len(samples.get("t") or []) > MAX_RAW_SAMPLES:
                        line["agg"] = "mean"
                        line["note"] = raw_failures.get(item.signal_id) or t(
                            "Too many samples to summarise here: showing the mean."
                        )
                    else:
                        line["t"], line["v"] = summarise(
                            samples.get("t") or [],
                            samples.get("v") or [],
                            start,
                            own,
                            spec.agg,
                            end,
                        )
            lines.append(line)
        plots.append({"title": plot.title, "lines": lines})
    return {
        "plots": plots,
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": step,
            "shifted": shifted,
        },
        "read_at": reader.clock().isoformat(),
    }
