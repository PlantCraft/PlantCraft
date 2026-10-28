"""Sample CSV files of the plant, in every layout Historian reads, and one with errors.

Each file holds the same series (:func:`.plant.history`), so a reader that gets them all right
reads the same values from every file. ``write`` returns, per file, what a reader should find.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .plant import Series, numbers

LOCAL_ZONE = "America/Sao_Paulo"
# A stretch of FIC-101.PV the long file marks bad, and one it marks uncertain (index of sample).
BAD_SAMPLES = range(5, 8)
UNCERTAIN_SAMPLES = range(12, 14)


def _grid(series: dict[str, Series]) -> list[int]:
    return sorted({stamp for item in series.values() for stamp in item.times})


def _cells(series: dict[str, Series], stamps: list[int]) -> dict[str, dict[int, float | str]]:
    return {tag: dict(zip(item.times, item.values, strict=True)) for tag, item in series.items()}


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wide(
    path: Path,
    series: dict[str, Series],
    when,
    *,
    sep: str = ",",
    number=repr,
) -> None:
    stamps = _grid(series)
    cells = _cells(series, stamps)
    lines = [sep.join(["time", *series])]
    for stamp in stamps:
        row = [when(stamp)]
        for tag in series:
            value = cells[tag].get(stamp)
            row.append(
                "" if value is None else str(value) if isinstance(value, str) else number(value)
            )
        lines.append(sep.join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write(folder: Path, series: dict[str, Series]) -> dict[str, Any]:
    """Write the sample files into ``folder``; what each holds, also kept as ``expected.json``."""

    folder.mkdir(parents=True, exist_ok=True)
    local = ZoneInfo(LOCAL_ZONE)
    plus3 = timezone(timedelta(hours=3))
    wide = numbers(series)
    expected: dict[str, Any] = {}

    _wide(folder / "wide-iso.csv", series, _iso)
    expected["wide-iso.csv"] = {"shape": "wide", "timezone": "UTC", "tags": list(series)}

    _wide(
        folder / "wide-offset.csv",
        wide,
        lambda ms: datetime.fromtimestamp(ms / 1000, plus3).isoformat(),
    )
    expected["wide-offset.csv"] = {"shape": "wide", "timezone": "UTC", "tags": list(wide)}

    _wide(folder / "wide-epoch.csv", wide, lambda ms: str(ms // 1000))
    expected["wide-epoch.csv"] = {"shape": "wide", "timezone": "UTC", "tags": list(wide)}

    # Brazilian Excel: ; between cells, decimal comma, dd/mm/yyyy in local time.
    _wide(
        folder / "wide-excel-br.csv",
        wide,
        lambda ms: datetime.fromtimestamp(ms / 1000, local).strftime("%d/%m/%Y %H:%M:%S"),
        sep=";",
        number=lambda value: repr(value).replace(".", ","),
    )
    expected["wide-excel-br.csv"] = {"shape": "wide", "timezone": LOCAL_ZONE, "tags": list(wide)}

    lines = ["time,tag,value,quality"]
    qualities: dict[str, list[list[Any]]] = {}
    for tag, item in series.items():
        for index, (stamp, value) in enumerate(zip(item.times, item.values, strict=True)):
            quality = "good"
            if tag == "FIC-101.PV" and index in BAD_SAMPLES:
                quality = "bad"
            elif tag == "FIC-101.PV" and index in UNCERTAIN_SAMPLES:
                quality = "uncertain"
            lines.append(
                f"{_iso(stamp)},{tag},{value if isinstance(value, str) else repr(value)},{quality}"
            )
            qualities.setdefault(tag, []).append([stamp, quality])
    (folder / "long.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    expected["long.csv"] = {
        "shape": "long",
        "timezone": "UTC",
        "tags": list(series),
        "qualities": {"FIC-101.PV": qualities["FIC-101.PV"]},
    }

    # Deliberate errors, each on a known line (1 is the header).
    first = _grid(wide)[0]
    bad = [
        "time,FIC-101.PV,FIC-101.SP",
        f"{_iso(first)},550.1,550",
        "yesterday at noon,550.2,550",
        f"{_iso(first + 10_000)},5x0.3,550",
        f"{_iso(first + 20_000)},550.4,550",
    ]
    (folder / "errors.csv").write_text("\n".join(bad) + "\n", encoding="utf-8")
    expected["errors.csv"] = {"error_lines": [3, 4]}

    (folder / "expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    return expected
