"""CSV sources: a file, or a pattern of files in one folder, that another application keeps
writing (a LIMS export, a data logger, a daily file).

Every ``check_minutes`` the collector looks at the files again; a file that is new or changed
(time or size) is read whole with the import's reader (``sources.csv_table``: wide or long,
``,`` or ``;``, any time format) and only the values after the newest one archived for each point
are kept. The files are only read: never moved, renamed or changed.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

import numpy as np

from histcraft.config import csv_path_allowed, csv_pattern_allowed, outside_csv_folders
from histcraft.i18n import t
from histcraft.sources.csv_table import Series, read_table

# Files a check reads at most (the newest), and files Browse looks at.
MAX_FILES = 500
BROWSE_FILES = 5


class CsvWatcher:
    def __init__(self, source: dict[str, Any]):
        self.source = source
        self.pattern = str(source.get("endpoint") or "")
        self.timezone = str((source.get("options") or {}).get("timezone") or "UTC")
        self.seen: dict[str, tuple[int, int]] = {}
        self.skipped = 0

    def files(self) -> list[Path]:
        """The files the source reads, oldest first (by modification time)."""

        if not csv_pattern_allowed(self.pattern):
            raise PermissionError(outside_csv_folders())
        path = Path(self.pattern).expanduser()
        if any(ch in path.name for ch in "*?["):
            if not path.parent.is_dir():
                raise FileNotFoundError(t("Folder not found: {path}", path=path.parent))
            found = [Path(name) for name in glob.glob(str(path)) if Path(name).is_file()]
        else:
            if not path.parent.is_dir():
                raise FileNotFoundError(t("Folder not found: {path}", path=path.parent))
            if not path.is_file():
                raise FileNotFoundError(t("Data file not found: {path}", path=path))
            found = [path]
        # A link out of the CSV folders is never followed (security audit 2026-10-22).
        found = [item for item in found if csv_path_allowed(item)]
        found.sort(key=lambda item: item.stat().st_mtime_ns)
        return found[-MAX_FILES:]

    async def connect(self) -> None:
        self.files()

    async def close(self) -> None:
        return None

    def check(self) -> dict[str, Series]:
        """The values of every new or changed file, merged by tag in time order."""

        merged: dict[str, list[Series]] = {}
        self.skipped = 0
        for path in self.files():
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if self.seen.get(str(path)) == signature:
                continue
            table = read_table(path.read_bytes(), self.timezone)
            self.skipped += sum(int(problem["count"]) for problem in table.errors)
            self.seen[str(path)] = signature
            for tag, series in table.series.items():
                merged.setdefault(tag, []).append(series)
        return {tag: _join(tag, parts) for tag, parts in merged.items()}

    def browse(self) -> dict[str, Any]:
        tags: dict[str, Series] = {}
        for path in self.files()[-BROWSE_FILES:]:
            tags.update(read_table(path.read_bytes(), self.timezone).series)
        variables = [
            {
                "address": tag,
                "tag": tag,
                "name": tag,
                "path": tag,
                "kind": series.kind,
                "step": series.kind == "text",
                "unit": "",
                "description": "",
                "low": None,
                "high": None,
            }
            for tag, series in sorted(tags.items())
        ]
        return {"variables": variables, "truncated": False, "limit": len(variables)}

    def test(self) -> dict[str, Any]:
        files = self.files()
        if not files:
            return {"files": 0, "detail": t("No file matches {pattern} yet.", pattern=self.pattern)}
        newest = files[-1]
        table = read_table(newest.read_bytes(), self.timezone)
        return {
            "files": len(files),
            "newest": newest.name,
            "tags": len(table.series),
            "shape": table.shape,
            "errors": table.errors[:5],
        }


def _join(tag: str, parts: list[Series]) -> Series:
    if len(parts) == 1:
        return parts[0]
    times = np.concatenate([part.times for part in parts])
    values = [value for part in parts for value in part.values]
    order = np.argsort(times, kind="stable")
    times = times[order]
    values = [values[i] for i in order]
    last = np.r_[times[1:] != times[:-1], True]
    keep = np.flatnonzero(last)
    qualities = sorted(q for part in parts for q in part.qualities)
    return Series(tag, parts[-1].kind, times[keep], [values[i] for i in keep], qualities)
