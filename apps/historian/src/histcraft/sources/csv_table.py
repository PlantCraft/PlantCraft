"""A CSV file read as time series, with a report of what is in it and what is wrong.

One reader for the CSV import (Import & export) and the CSV source (a file or folder another
application keeps writing). It accepts the two shapes plant data comes in:

- **wide**: the first column is the time, then one column per tag (a PI extractor's export, a
  spreadsheet); empty cells mean no value at that time.
- **long**: one value per line, with a time, a tag and a value column, and an optional quality
  column (``good``, ``uncertain``, ``substituted`` or ``bad``); the header names them
  (``time``/``timestamp``, ``tag``/``name``/``point``, ``value``, ``quality``).

The separator (``,`` ``;`` tab ``|``) and the decimal mark (``1.5`` or ``1,5``, the second only
with ``;`` or tab) are detected. Times are ISO 8601 with an offset (taken as written), without
one (local times in ``timezone``) or epoch seconds or milliseconds; everything is returned as
UTC epoch milliseconds.

Everything detected can be set instead (:class:`ReadOptions`, the import form): separator,
decimal mark, lines before the header, layout, which column holds the time (and its format,
day/month order), the tag, value and quality columns, and a prefix for the tags. An Excel
workbook (``.xlsx``) is read the same way, one sheet at a time. ``Table.detected`` answers what
was used, so a form starts filled in, and ``Table.preview`` the first lines as read.

Nothing here raises on a bad file: :func:`read_table` always answers a :class:`Table` whose
``errors`` say, with line numbers, what keeps the file from being imported, and whose
``warnings`` say what is imported in a way the person may not expect.
"""

from __future__ import annotations

import csv
import io
import re
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from histcraft.i18n import t

# Cells that mean "no value" in exports (left empty in the archive, never an error).
EMPTY = {"", "na", "n/a", "#n/a", "nan", "null", "none", "-", "--"}
QUALITIES = ("good", "uncertain", "substituted", "bad")
TIME_NAMES = ("time", "timestamp", "datetime", "date", "ts", "t")
TAG_NAMES = ("tag", "tagname", "name", "point", "signal")
VALUE_NAMES = ("value", "val", "v")
QUALITY_NAMES = ("quality", "status", "q")
# Lines listed per problem (the count is always complete).
SHOWN = 20
# A time more than a day ahead of now is reported (a clock or time zone mistake, usually).
FUTURE_MS = 86_400_000
_NUMBER = re.compile(r"^[+-]?(\d+([.]\d*)?|[.]\d+)([eE][+-]?\d+)?$")
_EPOCH = re.compile(r"^\d{9,13}([.]\d+)?$")
_OFFSET = re.compile(r"(Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)
_SLASHED = re.compile(r"^(\d{1,2})/(\d{1,2})/\d{2,4}")
# Lines of the file the import form shows as read.
PREVIEW_LINES = 10
EXCEL_SUFFIXES = (".xlsx", ".xlsm")


class ReadOptions(BaseModel):
    """How to read a file; empty (or ``auto``) means detected. Saved with an import."""

    delimiter: str = Field(default="", pattern=r"^(|,|;|\t|\|)$")
    decimal: str = Field(default="", pattern=r"^(|\.|,)$")
    # Lines above the header (a title, an export's notes).
    skip_rows: int = Field(default=0, ge=0, le=1000)
    shape: str = Field(default="auto", pattern=r"^(auto|wide|long)$")
    # Header names; the time column of a wide file is the first one unless named.
    time_column: str = Field(default="", max_length=200)
    # ``epoch_s``, ``epoch_ms`` or a strftime pattern such as ``%d/%m/%Y %H:%M``; empty: detected.
    time_format: str = Field(default="", max_length=60)
    day_first: str = Field(default="auto", pattern=r"^(auto|day|month)$")
    tag_column: str = Field(default="", max_length=200)
    value_column: str = Field(default="", max_length=200)
    quality_column: str = Field(default="", max_length=200)
    # Put before every tag of the file (``LAB.`` makes ``Viscosity`` ``LAB.Viscosity``).
    tag_prefix: str = Field(default="", max_length=100)
    # Excel: the sheet; empty, the first.
    sheet: str = Field(default="", max_length=100)


def utc_ms(index: pd.DatetimeIndex, timezone: str) -> np.ndarray:
    """Epoch milliseconds (UTC) of ``index``: naive times are local times in ``timezone``.

    A local time the clock skips (spring forward) moves forward; one it repeats (fall
    back) is taken in order when the file allows it, else becomes ``NaT``.
    """

    if index.tz is None:
        try:
            index = index.tz_localize(timezone, ambiguous="infer", nonexistent="shift_forward")
        except Exception:  # ambiguous times the order cannot settle
            index = index.tz_localize(timezone, ambiguous="NaT", nonexistent="shift_forward")
    index = index.tz_convert("UTC")
    stamps = index.as_unit("ns").asi8 // 1_000_000
    return np.where(index.isna(), np.iinfo(np.int64).min, stamps).astype(np.int64)


@dataclass
class Series:
    """One tag's values, in time order, one per time (the last line wins)."""

    tag: str
    kind: str  # number or text
    times: np.ndarray  # UTC epoch ms
    values: list[Any]
    # Changes of quality (ms, quality), long files with a quality column only.
    qualities: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class Table:
    shape: str = ""  # wide or long
    delimiter: str = ","
    decimal: str = "."
    times: str = ""  # offset, local or epoch
    rows: int = 0
    # The options as used (every detected one filled in), the columns and Excel's sheets.
    detected: dict[str, Any] = field(default_factory=dict)
    # The first lines as read: the header, the cells, and each line's time in UTC (or None).
    preview: dict[str, Any] = field(default_factory=dict)
    series: dict[str, Series] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def values(self) -> int:
        return sum(len(item.times) for item in self.series.values())

    @property
    def start_ms(self) -> int | None:
        firsts = [int(item.times[0]) for item in self.series.values() if len(item.times)]
        return min(firsts) if firsts else None

    @property
    def end_ms(self) -> int | None:
        lasts = [int(item.times[-1]) for item in self.series.values() if len(item.times)]
        return max(lasts) if lasts else None

    def report(self) -> dict[str, Any]:
        """What a page shows before the import is confirmed."""

        return {
            "shape": self.shape,
            "delimiter": self.delimiter,
            "decimal": self.decimal,
            "times": self.times,
            "rows": self.rows,
            "values": self.values,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "tags": [
                {"tag": item.tag, "kind": item.kind, "values": len(item.times)}
                for item in self.series.values()
            ],
            "errors": self.errors,
            "warnings": self.warnings,
            "options": self.detected,
            "preview": self.preview,
        }


def _problem(target: list[dict[str, Any]], message: str, lines: list[int]) -> None:
    target.append({"message": message, "count": len(lines), "lines": lines[:SHOWN]})


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:50])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _fields(text: str, delimiter: str) -> list[int]:
    lines = [line for line in text.splitlines()[:50] if line.strip()]
    return [len(row) for row in csv.reader(lines, delimiter=delimiter)]


def _layout(text: str, delimiter: str) -> tuple[str, int]:
    """The separator (when not given) and the title lines above the header, if any.

    A report often starts with a line or two of its own ("Lab report", the plant's name). The
    separator is the one that splits most lines into the same number (two or more) of fields;
    lines above the first one with that many fields are skipped."""

    candidates = [delimiter] if delimiter else [_delimiter(text), ",", ";", "\t", "|"]
    best, best_count, best_seen = candidates[0], 0, 0
    for candidate in dict.fromkeys(candidates):
        counts = _fields(text, candidate)
        wide = [count for count in counts if count >= 2]
        if not wide:
            continue
        count = max(set(wide), key=wide.count)
        if wide.count(count) > best_seen:
            best, best_count, best_seen = candidate, count, wide.count(count)
    skip = 0
    for line in text.splitlines()[:20]:
        if not line.strip() or _fields(line, best)[0] < best_count:
            skip += 1
            continue
        break
    return best, skip if skip < 20 else 0


def _decimal(frame: pd.DataFrame, delimiter: str) -> str:
    """``,`` when the separator allows it and the cells look like ``1,5``; else ``.``."""

    if delimiter == ",":
        return "."
    cells = frame.iloc[:200, 1:].to_numpy().ravel().tolist()
    comma = sum(bool(re.match(r"^[+-]?\d+,\d+$", str(cell).strip())) for cell in cells)
    dot = sum(bool(re.match(r"^[+-]?\d+\.\d+$", str(cell).strip())) for cell in cells)
    return "," if comma > dot else "."


def _number(cell: str, decimal: str) -> float | None:
    text = cell.strip()
    if decimal == ",":
        text = text.replace(".", "").replace(",", ".") if "," in text else text
    return float(text) if _NUMBER.match(text) else None


def _times(raw: list[str], timezone: str, dayfirst: bool, fmt: str = "") -> tuple[np.ndarray, str]:
    """UTC epoch ms of each cell (int64 min where unreadable) and how they were written:
    ``epoch``, ``offset`` (each with its offset), ``local`` (in ``timezone``) or ``mixed``.
    ``fmt``: ``epoch_s``, ``epoch_ms`` or a strftime pattern instead of detecting."""

    bad = np.iinfo(np.int64).min
    cells = [cell.strip() for cell in raw]
    filled = [cell for cell in cells if cell]
    epoch = fmt in ("epoch_s", "epoch_ms") or (
        not fmt and filled and all(_EPOCH.match(cell) for cell in filled)
    )
    if epoch:
        numbers = np.array([_float(cell) for cell in cells])
        if fmt:
            scale = 1 if fmt == "epoch_ms" else 1000
        else:
            scale = 1 if np.nanmax(numbers) > 1e11 else 1000
        out = np.where(np.isnan(numbers), bad, numbers * scale)
        return out.astype(np.int64), "epoch"
    if fmt:
        aware = "%z" in fmt or "%Z" in fmt
        parsed = pd.DatetimeIndex(
            pd.to_datetime(pd.Index(cells), errors="coerce", format=fmt, utc=aware)
        )
        return (_utc(parsed) if aware else utc_ms(parsed, timezone)), (
            "offset" if aware else "local"
        )
    out = np.full(len(cells), bad, dtype=np.int64)
    aware = np.array([bool(_OFFSET.search(cell)) for cell in cells], dtype=bool)
    slashed = np.array([bool(_SLASHED.match(cell)) for cell in cells], dtype=bool)
    # Day/month order applies to slashed dates only (pandas would turn 2026-10-01 into January).
    for group, local, first in (
        (aware & ~slashed, False, False),
        (aware & slashed, False, dayfirst),
        (~aware & ~slashed, True, False),
        (~aware & slashed, True, dayfirst),
    ):
        if not group.any():
            continue
        chosen = [cells[i] for i in np.flatnonzero(group)]
        parsed = pd.DatetimeIndex(
            pd.to_datetime(
                pd.Index(chosen), errors="coerce", format="mixed", dayfirst=first, utc=not local
            )
        )
        out[group] = utc_ms(parsed, timezone) if local else _utc(parsed)
    kinds = {"offset" if flag else "local" for flag in aware[[bool(c) for c in cells]]}
    return out, kinds.pop() if len(kinds) == 1 else "mixed"


def _float(cell: str) -> float:
    try:
        return float(cell) if cell else np.nan
    except ValueError:
        return np.nan


def _utc(index: pd.DatetimeIndex) -> np.ndarray:
    stamps = index.as_unit("ns").asi8 // 1_000_000
    return np.where(index.isna(), np.iinfo(np.int64).min, stamps).astype(np.int64)


def _dayfirst(raw: list[str], decimal: str) -> bool:
    """Whether dates like 01/10/2026 are day/month: a first part above 12 settles it, else
    the decimal comma (a Brazilian or European export) does."""

    for cell in raw:
        match = _SLASHED.match(cell.strip())
        if match and int(match.group(1)) > 12:
            return True
        if match and int(match.group(2)) > 12:
            return False
    return decimal == ","


def _header(columns: list[str], names: tuple[str, ...]) -> int | None:
    lowered = [str(column).strip().lower() for column in columns]
    return next((lowered.index(name) for name in names if name in lowered), None)


def _excel(data: bytes, options: ReadOptions, table: Table) -> str | None:
    """An Excel sheet as CSV text (cells as written), or None with the error noted."""

    try:
        book = pd.ExcelFile(io.BytesIO(data), engine="openpyxl")
    except Exception as exc:  # noqa: BLE001 - any unreadable file is the sender's to fix
        _problem(
            table.errors, t("Not an Excel workbook the Historian reads: {error}", error=exc), []
        )
        return None
    sheets = [str(name) for name in book.sheet_names]
    table.detected["sheets"] = sheets
    sheet = options.sheet or (sheets[0] if sheets else "")
    if sheet not in sheets:
        _problem(table.errors, t("The workbook has no sheet {name}.", name=sheet), [])
        return None
    table.detected["sheet"] = sheet
    frame = book.parse(sheet, header=None, dtype=str, keep_default_na=False)
    # Times Excel stored as dates come back as 2026-10-24 08:00:00 (pandas' own text).
    return frame.to_csv(index=False, header=False)


def read_table(
    data: bytes,
    timezone: str = "UTC",
    *,
    options: ReadOptions | None = None,
    file_name: str = "",
    now_ms: int | None = None,
) -> Table:
    """Read ``data`` (a CSV file's bytes, or an Excel workbook's when ``file_name`` ends in
    .xlsx); never raises on a bad file (see the module)."""

    options = options or ReadOptions()
    table = Table()
    excel = file_name.lower().endswith(EXCEL_SUFFIXES)
    table.detected = {"format": "excel" if excel else "csv", **options.model_dump()}
    if excel:
        text = _excel(data, options, table)
        if text is None:
            return table
        delimiter = ","
    else:
        text = _decode(data)
        delimiter = ""
    skip_rows = options.skip_rows
    if skip_rows:
        text = "\n".join(text.splitlines()[skip_rows:])
    if not text.strip():
        _problem(table.errors, t("The file is empty."), [])
        return table
    table.delimiter, titles = _layout(text, delimiter or options.delimiter)
    if titles:
        # Lines above the header that cannot be part of the table are skipped too.
        text = "\n".join(text.splitlines()[titles:])
        skip_rows += titles
    table.detected["skip_rows"] = skip_rows
    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=table.delimiter,
            dtype=str,
            keep_default_na=False,
            skipinitialspace=True,
        )
    except Exception as exc:  # noqa: BLE001 - any unreadable file is the sender's to fix
        _problem(table.errors, t("Not a CSV file the Historian reads: {error}", error=exc), [])
        return table
    # The header as written (pandas renames a repeated name to name.1).
    header = next(csv.reader(io.StringIO(text), delimiter=table.delimiter), [])
    columns = [str(column).strip() for column in header][: len(frame.columns)]
    if len(columns) != len(frame.columns):
        columns = [str(column).strip() for column in frame.columns]
    table.detected.update(delimiter=table.delimiter, columns=columns)
    if len(columns) < 2 or frame.empty:
        _problem(
            table.errors,
            t("The file needs a time column and at least one value column, with lines below."),
            [],
        )
        return table
    table.rows = len(frame)
    table.decimal = "." if excel else options.decimal or _decimal(frame, table.delimiter)
    table.detected["decimal"] = table.decimal
    # Line numbers as a spreadsheet shows them: the header is line 1 (after the skipped lines).
    lines = np.arange(2, len(frame) + 2) + skip_rows

    def named(name: str, guesses: tuple[str, ...]) -> int | None:
        if not name:
            return _header(columns, guesses)
        if name not in columns:
            _problem(table.errors, t("The file has no column {name}.", name=name), [])
            return None
        return columns.index(name)

    at = named(options.time_column, TIME_NAMES)
    tag = named(options.tag_column, TAG_NAMES)
    value = named(options.value_column, VALUE_NAMES)
    quality = named(options.quality_column, QUALITY_NAMES)
    if table.errors:
        return table
    long = options.shape == "long" or (options.shape == "auto" and None not in (at, tag, value))
    if long and None in (at, tag, value):
        _problem(table.errors, t("A long file needs a time, a tag and a value column."), [])
        return table
    if long:
        table.shape = "long"
        _long(table, frame, lines, at, tag, value, quality, timezone, options)
        table.detected.update(
            tag_column=columns[tag],
            value_column=columns[value],
            quality_column=columns[quality] if quality is not None else "",
        )
    else:
        table.shape = "wide"
        at = 0 if at is None or not options.time_column else at
        _wide(table, frame, columns, lines, timezone, options, at)
        table.detected.update(tag_column="", value_column="", quality_column="")
    table.detected.update(shape=table.shape, time_column=columns[at])
    if options.tag_prefix:
        table.series = {
            f"{options.tag_prefix}{name}": Series(
                f"{options.tag_prefix}{name}", item.kind, item.times, item.values, item.qualities
            )
            for name, item in table.series.items()
        }
    if not table.errors and not table.series:
        _problem(table.errors, t("The file holds no values."), [])
    _preview(table, frame, columns, at, timezone, options)
    _future(table, now_ms if now_ms is not None else int(time.time() * 1000))
    return table


def _preview(
    table: Table,
    frame: pd.DataFrame,
    columns: list[str],
    at: int,
    timezone: str,
    options: ReadOptions,
) -> None:
    head = frame.head(PREVIEW_LINES)
    stamps, _ = _times(
        head.iloc[:, at].tolist(),
        timezone,
        table.detected.get("day_first") == "day",
        options.time_format,
    )
    table.preview = {
        "columns": columns,
        "rows": head.to_numpy().tolist(),
        "times": [
            None
            if ms == np.iinfo(np.int64).min
            else pd.Timestamp(int(ms), unit="ms", tz="UTC").isoformat()
            for ms in stamps.tolist()
        ],
    }


def _stamped(
    table: Table,
    frame: pd.DataFrame,
    column: int,
    lines: np.ndarray,
    timezone: str,
    options: ReadOptions,
) -> np.ndarray:
    raw = frame.iloc[:, column].tolist()
    if options.day_first == "auto":
        dayfirst = _dayfirst(raw, table.decimal)
    else:
        dayfirst = options.day_first == "day"
    stamps, table.times = _times(raw, timezone, dayfirst, options.time_format)
    slashed = not options.time_format and any(
        _SLASHED.match(str(cell).strip()) for cell in raw[:200]
    )
    table.detected["day_first"] = ("day" if dayfirst else "month") if slashed else options.day_first
    if slashed and options.day_first == "auto":
        _problem(
            table.warnings,
            t(
                "Dates such as 01/10/2026 are read as {order}.",
                order=t("day/month") if dayfirst else t("month/day"),
            ),
            [],
        )
    bad = stamps == np.iinfo(np.int64).min
    if bad.all():
        _problem(
            table.errors,
            t(
                "No time in column {column} could be read: use ISO 8601 (2026-10-24 08:00:00,"
                " with or without an offset) or epoch seconds.",
                column=frame.columns[column],
            ),
            [],
        )
    elif bad.any():
        _problem(table.errors, t("Times that could not be read"), lines[bad].tolist())
    return stamps


def _cells(
    table: Table, tag: str, raw: list[str], lines: np.ndarray
) -> tuple[str, list[Any], np.ndarray]:
    """A column's kind, its values (None where empty) and which cells hold a value.

    A column whose filled cells are all numbers is a number column, and one whose cells are
    mostly text is a text column; a number column with some text cells is an error, listed.
    """

    empty = np.array([cell.strip().lower() in EMPTY for cell in raw], dtype=bool)
    numbers = [None if gone else _number(cell, table.decimal) for cell, gone in zip(raw, empty)]
    wrong = np.array([n is None for n in numbers], dtype=bool) & ~empty
    filled = int((~empty).sum())
    if filled and wrong.sum() * 2 > filled:  # mostly text: a text point (a lab remark, a state)
        return "text", [None if gone else cell.strip() for cell, gone in zip(raw, empty)], ~empty
    if wrong.any():
        _problem(
            table.errors,
            t("Values in {tag} that are not numbers", tag=tag),
            lines[wrong].tolist(),
        )
    return "number", numbers, ~empty & ~wrong


def _series(
    table: Table, tag: str, kind: str, stamps: np.ndarray, values: list[Any], lines: np.ndarray
) -> Series | None:
    if not len(stamps):
        return None
    order = np.argsort(stamps, kind="stable")
    stamps, lines = stamps[order], lines[order]
    values = [values[i] for i in order]
    # Two lines at one time: the last one in the file wins, and the person is told.
    last = np.r_[stamps[1:] != stamps[:-1], True]
    if not last.all():
        _problem(
            table.warnings,
            t("{tag}: lines at a time already given (the last one is kept)", tag=tag),
            lines[~last].tolist(),
        )
    keep = np.flatnonzero(last)
    return Series(tag, kind, stamps[keep], [values[i] for i in keep])


def _wide(
    table: Table,
    frame: pd.DataFrame,
    columns: list[str],
    lines: np.ndarray,
    timezone: str,
    options: ReadOptions,
    at: int = 0,
) -> None:
    stamps = _stamped(table, frame, at, lines, timezone, options)
    readable = stamps != np.iinfo(np.int64).min
    seen: set[str] = set()
    for index, tag in enumerate(columns):
        if index == at:
            continue
        if not tag or tag.lower().startswith("unnamed:"):
            _problem(table.errors, t("Column {n} has no name in the header.", n=index + 1), [1])
            continue
        if tag in seen:
            _problem(table.errors, t("Column {tag} appears twice.", tag=tag), [1])
            continue
        seen.add(tag)
        kind, values, kept = _cells(table, tag, frame.iloc[:, index].tolist(), lines)
        keep = kept & readable
        found = _series(
            table, tag, kind, stamps[keep], [v for v, k in zip(values, keep) if k], lines[keep]
        )
        if found:
            table.series[tag] = found


def _long(
    table: Table,
    frame: pd.DataFrame,
    lines: np.ndarray,
    at: int,
    tag: int,
    value: int,
    quality: int | None,
    timezone: str,
    options: ReadOptions,
) -> None:
    stamps = _stamped(table, frame, at, lines, timezone, options)
    readable = stamps != np.iinfo(np.int64).min
    tags = np.array([cell.strip() for cell in frame.iloc[:, tag].tolist()], dtype=object)
    no_tag = tags == ""
    if no_tag.any():
        _problem(table.errors, t("Lines without a tag"), lines[no_tag].tolist())
    raw = frame.iloc[:, value].tolist()
    marks = (
        [cell.strip().lower() for cell in frame.iloc[:, quality].tolist()]
        if quality is not None
        else None
    )
    if marks is not None:
        unknown = np.array([mark not in ("", *QUALITIES) for mark in marks], dtype=bool)
        if unknown.any():
            _problem(
                table.errors,
                t("Qualities other than {names}", names=", ".join(QUALITIES)),
                lines[unknown].tolist(),
            )
    for name in dict.fromkeys(tags[~no_tag].tolist()):
        rows = np.flatnonzero(tags == name)
        kind, values, kept = _cells(table, name, [raw[i] for i in rows], lines[rows])
        keep = kept & readable[rows]
        chosen = rows[keep]
        found = _series(
            table,
            name,
            kind,
            stamps[chosen],
            [v for v, k in zip(values, keep) if k],
            lines[chosen],
        )
        if not found:
            continue
        if marks is not None:
            by_time = {int(stamps[i]): marks[i] or "good" for i in chosen}
            previous = "good"
            for ms in found.times.tolist():
                mark = by_time.get(int(ms), "good")
                if mark != previous:
                    found.qualities.append((int(ms), mark))
                    previous = mark
        table.series[name] = found


def _future(table: Table, now: int) -> None:
    ahead = [
        item.tag
        for item in table.series.values()
        if len(item.times) and int(item.times[-1]) > now + FUTURE_MS
    ]
    if ahead:
        _problem(
            table.warnings,
            t(
                "Times more than a day ahead in {count} tags (check the time zone): {tags}",
                count=len(ahead),
                tags=", ".join(ahead[:5]),
            ),
            [],
        )
