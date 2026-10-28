"""The point list as a CSV file: export it, edit it in a spreadsheet, import it back.

One row per point. The columns are the point's own configuration: an empty setting cell
(scan, deviation, max interval, retention, mode) means "inherit" from the source or the
general settings, exactly as on the point page, so an exported file imported again changes
nothing. A row whose source and tag exist updates that point; any other row adds one.
``source_id`` and ``tag`` are required; every other column may be left out of the file, and
the points keep what they have for the columns it lacks.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from pydantic import ValidationError

from histcraft.catalog.models import CALC_SOURCE, WRITTEN_KINDS, CatalogError, PointIn, PointPatch
from histcraft.catalog.store import CatalogStore
from histcraft.i18n import t

COLUMNS = (
    "source_id",
    "tag",
    "address",
    "name",
    "description",
    "unit",
    "kind",
    "step",
    "low",
    "high",
    "mode",
    "scan_seconds",
    "deviation",
    "max_seconds",
    "retention_days",
    "enabled",
)
REQUIRED = ("source_id", "tag")
# Settings that inherit when empty (their own value, else None).
INHERITED = ("scan_seconds", "deviation", "max_seconds", "retention_days")
NUMBERS = ("low", "high", "scan_seconds", "deviation", "max_seconds", "retention_days")
BOOLEANS = ("step", "enabled")
MAX_ROWS = 20_000
_TRUE = {"true", "1", "yes", "y", "sim", "s"}
_FALSE = {"false", "0", "no", "n", "não", "nao"}


def to_csv(points: list[dict[str, Any]]) -> str:
    """The points as CSV text (plant points; apps' series are written by their apps)."""

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for point in points:
        if point["source_kind"] in WRITTEN_KINDS:
            continue
        own = point.get("own") or {}
        row = {
            **{key: point.get(key) for key in COLUMNS},
            "mode": point.get("own_mode") or "",
            **{key: own.get(key) for key in INHERITED},
        }
        writer.writerow([_cell(row[key]) for key in COLUMNS])
    return out.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def plan(catalog: CatalogStore, text: str) -> dict[str, Any]:
    """What importing ``text`` would do: ``add``, ``update`` and ``unchanged`` signals,
    ``errors`` per line (nothing is changed); ``changes`` holds what ``apply`` writes."""

    rows, header_errors = _rows(text)
    out: dict[str, Any] = {"add": [], "update": [], "unchanged": [], "errors": header_errors}
    changes: list[tuple[str, Any]] = []
    if header_errors:
        out["changes"] = changes
        return out
    sources = {item["id"]: item for item in catalog.sources()}
    # Calculated points: their source appears with the first one.
    sources.setdefault(CALC_SOURCE, {"id": CALC_SOURCE, "kind": "calc"})
    existing = catalog.find_many(f"{row['source_id']}:{row['tag']}" for _, row in rows)
    seen: set[str] = set()
    for line, row in rows:
        signal = f"{row.get('source_id', '')}:{row.get('tag', '')}"
        try:
            values = _values(row)
            source = sources.get(values["source_id"])
            if source is None:
                raise ValueError(t("unknown source {id}", id=values["source_id"]))
            if source["kind"] in WRITTEN_KINDS:
                raise ValueError(t("written by its app only"))
            if signal in seen:
                raise ValueError(t("this signal is already on an earlier line"))
            seen.add(signal)
            current = existing.get(signal)
            if current is None or current["source_id"] != values["source_id"]:
                # An empty true/false cell takes the default of a new point.
                fields = {k: v for k, v in values.items() if not (k in BOOLEANS and v is None)}
                changes.append(("add", PointIn(**fields)))
                out["add"].append(signal)
                continue
            patch = _patch(current, values)
            if patch is None:
                out["unchanged"].append(signal)
            else:
                changes.append(("update", (signal, patch)))
                out["update"].append(signal)
        except ValidationError as exc:
            out["errors"].append({"line": line, "signal": signal, "message": _first(exc)})
        except ValueError as exc:
            out["errors"].append({"line": line, "signal": signal, "message": str(exc)})
    out["changes"] = changes
    return out


def apply(catalog: CatalogStore, planned: dict[str, Any]) -> dict[str, Any]:
    """Write a ``plan`` (refused while it has errors): the points added and updated."""

    if planned["errors"]:
        raise CatalogError(
            t("Fix the {count} lines with errors first.", count=len(planned["errors"])), 422
        )
    adds = [item for verb, item in planned["changes"] if verb == "add"]
    # The ranges in a points CSV are a person's (D2).
    result = (
        catalog.add_points(adds, range_origin="edited") if adds else {"added": [], "skipped": []}
    )
    updated = []
    for verb, item in planned["changes"]:
        if verb == "update":
            signal, patch = item
            catalog.update_point(signal, patch)
            updated.append(signal)
    return {"added": result["added"], "skipped": result["skipped"], "updated": updated}


def _rows(text: str) -> tuple[list[tuple[int, dict[str, str]]], list[dict[str, Any]]]:
    text = text.lstrip("\ufeff")
    # The header decides the delimiter (Excel in Portuguese writes ";"); node ids hold ";" too,
    # so only the first line is looked at.
    first = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header = [name.strip() for name in reader.fieldnames or []]
    missing = [name for name in REQUIRED if name not in header]
    unknown = [name for name in header if name and name not in COLUMNS]
    errors = []
    if missing:
        errors.append(
            {
                "line": 1,
                "signal": "",
                "message": t("Missing columns: {names}.", names=", ".join(missing)),
            }
        )
    if unknown:
        errors.append(
            {
                "line": 1,
                "signal": "",
                "message": t("Unknown columns: {names}.", names=", ".join(unknown)),
            }
        )
    rows: list[tuple[int, dict[str, str]]] = []
    if errors:
        return rows, errors
    for number, raw in enumerate(reader, start=2):
        row = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key}
        if not any(row.values()):
            continue
        rows.append((number, row))
        if len(rows) > MAX_ROWS:
            return [], [
                {
                    "line": number,
                    "signal": "",
                    "message": t("At most {count} signals per file.", count=MAX_ROWS),
                }
            ]
    return rows, []


def _values(row: dict[str, str]) -> dict[str, Any]:
    """A row's cells as point fields; only the columns the file has."""

    values: dict[str, Any] = {}
    for key, cell in row.items():
        if key in NUMBERS:
            values[key] = _number(key, cell)
        elif key in BOOLEANS:
            values[key] = _boolean(key, cell)
        else:
            values[key] = cell
    if values.get("kind") == "":
        values.pop("kind")
    return values


def _number(key: str, cell: str) -> float | int | None:
    if cell == "":
        return None
    text = cell.replace(",", ".") if cell.count(",") == 1 and "." not in cell else cell
    try:
        number = float(text)
    except ValueError:
        raise ValueError(t("{column} is not a number: {value}", column=key, value=cell)) from None
    return int(number) if key == "retention_days" else number


def _boolean(key: str, cell: str) -> bool | None:
    lowered = cell.lower()
    if lowered == "":
        return None
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(t("{column} is true or false: {value}", column=key, value=cell))


def _patch(current: dict[str, Any], values: dict[str, Any]) -> PointPatch | None:
    """The changes a row makes to an existing point, or None when it changes nothing."""

    calculated = current["source_kind"] == "calc"
    if values.get("address") and values["address"] != current["address"] and not calculated:
        raise ValueError(t("the address of a signal cannot change: remove it and add it again"))
    if values.get("kind") and values["kind"] != current["kind"]:
        raise ValueError(t("the kind of a signal cannot change: remove it and add it again"))
    own = current.get("own") or {}
    now: dict[str, Any] = {
        "name": current["name"],
        "description": current["description"],
        "unit": current["unit"],
        "step": bool(current["step"]),
        "low": current["low"],
        "high": current["high"],
        "mode": current.get("own_mode") or "",
        "enabled": bool(current["enabled"]),
        **{key: own.get(key) for key in INHERITED},
    }
    if calculated and values.get("address"):
        now["address"] = current["address"]  # the formula
    changes = {}
    for key, old in now.items():
        if key not in values:
            continue
        new = values[key]
        if key in BOOLEANS and new is None:
            continue  # an empty true/false cell keeps the point's
        if key == "mode":
            new = new or ""
        if _same(old, new):
            continue
        changes[key] = new
    if not changes:
        return None
    return PointPatch(**changes)


def _same(old: Any, new: Any) -> bool:
    if old is None or new is None:
        return old is None and new is None
    if isinstance(old, int | float) and isinstance(new, int | float):
        return abs(float(old) - float(new)) <= 1e-12 * max(1.0, abs(float(old)))
    return old == new


def _first(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error.get("loc", ()))
    return f"{where}: {error.get('msg', '')}" if where else str(error.get("msg", ""))
