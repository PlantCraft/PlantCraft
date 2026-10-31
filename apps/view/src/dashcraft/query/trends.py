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
    reader: Reader,
    signals: list[str],
    start: Any,
    end: Any,
    step: int | None,
    *,
    extremes: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    try:
        if extremes:
            batch = reader.client.series_many(signals, start, end, step, extremes=True)
        else:
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


# The extremes the Historian gives per cell for a min or max line (``extremes``).
BAND = {"min": "low", "max": "high"}

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
    reader: Reader,
    groups: dict[int, list[str]],
    start: Any,
    end: Any,
    banded: set[int] | None = None,
) -> tuple[dict[tuple[int, str], dict[str, Any]], dict[tuple[int, str], str]]:
    """Each interval's signals in one batch: answers and failures keyed by (step, signal).
    The intervals in ``banded`` (a min or max line) also ask for each cell's extremes."""

    answers: dict[tuple[int, str], dict[str, Any]] = {}
    failures: dict[tuple[int, str], str] = {}
    for step, signals in groups.items():
        extremes = bool(step) and step in (banded or set())
        found, failed = _read(reader, signals, start, end, step or None, extremes=extremes)
        answers.update({(step, signal): item for signal, item in found.items()})
        failures.update({(step, signal): text for signal, text in failed.items()})
    return answers, failures


# Laboratory results (the Historian's ``laboratory:<analysis>`` signals, 2026-10-31).
LAB_PREFIX = "laboratory:"
# The fields of a sample a trend shows beside its value.
LAB_FIELDS = ("sampled_at", "value", "status", "received_at", "approved_at")


def _is_lab(signal_id: str | None) -> bool:
    return bool(signal_id) and str(signal_id).startswith(LAB_PREFIX)


def _lab_samples(reader: Reader, signal_id: str, start: Any, end: Any) -> list[dict[str, Any]]:
    """A laboratory signal's samples in the period, each with its status and its received and
    approved times; none when the Historian keeps none (the line stays as read)."""

    read = getattr(reader.client, "lab_samples", None)
    if read is None:
        return []
    try:
        found = read(signal_id, start, end)
    except Unauthorized:
        raise
    except PlantCraftError:
        return []
    return [
        {key: sample.get(key) for key in LAB_FIELDS}
        for sample in found
        if sample.get("sampled_at") and sample.get("value") is not None
    ]


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
    plots, start, end, shifted = _read_plots(
        reader, view, start, end, step, may_shift=period.mode == "relative"
    )
    for key in view.compare:
        offset = compare_offset(key, end - start)
        earlier = _read_plots(reader, view, start - offset, end - offset, step, may_shift=False)[0]
        for plot, before in zip(plots, earlier, strict=True):
            plot["lines"].extend(_compared(before["lines"], key, offset))
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


# How a compared period reads after a line's label.
COMPARE_LABELS = {
    "previous": "previous period",
    "1d": "1 day earlier",
    "7d": "1 week earlier",
    "28d": "4 weeks earlier",
}


def compare_offset(key: str, span: timedelta) -> timedelta:
    """How far back a compared period lies: the trend's own length for the previous period."""

    return span if key == "previous" else timedelta(days=int(key.rstrip("d")))


def _compared(lines: list[dict[str, Any]], key: str, offset: timedelta) -> list[dict[str, Any]]:
    """The earlier period's lines moved forward by ``offset`` onto the trend's time axis, each
    named after its period and pointing at its line (``source``) to take its colour. States
    (text signals) and lines that failed are left out."""

    moved = []
    for index, line in enumerate(lines):
        if line.get("error") or line.get("kind") == "text" or not line.get("t"):
            continue
        times = [(_instant(stamp) + offset).isoformat() for stamp in line["t"]]
        item = {key_: value for key_, value in line.items() if key_ != "samples"}
        label = f"{line['label']} · {t(COMPARE_LABELS[key])}"
        moved.append({**item, "t": times, "label": label, "compare": key, "source": index})
    return moved


def _read_plots(
    reader: Reader,
    view: TrendView,
    start: datetime,
    end: datetime,
    step: int,
    *,
    may_shift: bool,
) -> tuple[list[dict[str, Any]], datetime, datetime, bool]:
    """Every plot's lines between ``start`` and ``end``; with ``may_shift``, a period with no
    samples at all moves to end at the newest sample (the returned start, end and True)."""

    def step_of(line: Any) -> int:
        return step if line.step_seconds is None else line.step_seconds

    plots: list[dict[str, Any]] = []
    groups: dict[int, list[str]] = {}
    # Intervals with a min or max line: the Historian gives each cell's extremes beside the
    # means, from its hourly rollups, instead of every raw sample summarised here.
    banded = {step_of(line) for plot in view.plots for line in plot.lines if line.agg in BAND}
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
        answers, failures = _read_groups(reader, groups, start, end, banded)
        if may_shift and not failures and _empty(answers):
            every = sorted({signal for signals in groups.values() for signal in signals})
            anchor = _newest_sample(reader, every)
            if anchor is not None and anchor < end - timedelta(seconds=step or 1):
                moved = _read_groups(reader, groups, anchor - (end - start), anchor, banded)
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
            and BAND.get(spec.agg) not in answers[(step_of(spec), item.signal_id)]
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
                elif own and BAND.get(spec.agg) in answer:
                    line["v"] = list(answer[BAND[spec.agg]])
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
            if line["error"] is None and _is_lab(item.signal_id):
                line["samples"] = _lab_samples(reader, item.signal_id or "", start, end)
                if line["samples"]:
                    # A result belongs to its sampling time: drawn there, never averaged.
                    line["t"] = [sample["sampled_at"] for sample in line["samples"]]
                    line["v"] = [sample.get("value") for sample in line["samples"]]
                    line["agg"] = "recorded"
            lines.append(line)
        plots.append({"title": plot.title, "lines": lines})
    return plots, start, end, shifted
