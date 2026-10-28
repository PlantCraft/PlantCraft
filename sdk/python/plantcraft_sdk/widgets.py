"""An app's Overview widgets: declared once in ``app.toml``, served in the suite's shapes.

The widgets are declared in ``[[contributes.widgets]]`` (``plantcraft_sdk.contributes``):
PlantCraft keeps them in its registry, and the app serves (PlantCraft ``docs/widgets.md``)::

    GET <prefix>api/widgets                  catalog(manifest, t): the declared widgets, titled
    GET <prefix>api/widgets/<id>             one widget's data, in one of the shapes below
    GET <prefix>api/widgets/<id>?item=<v>    a widget with ``pick``: the data of the thing picked
    GET <prefix>api/widgets/<id>/options     a widget with ``pick``: options([...])

The shapes are built here so every app answers the same; the browser draws them on the app's
own Overview and on Desk's Today alike, and nothing of the app runs inside the platform::

    number(3, label="in alarm", state="alarm", href=f"{root}/results")
    items([item("FIC-101", detail="Oscillating", state="alarm", href=...)], href=..., empty=...)
    split([part("Alarm", 2, "alarm"), part("OK", 40, "ok")], label="results")
    series([(ms, value), ...], value=41.2, unit="°C", label="last hour")
    facts("Night round", [fact("Assets", 12), fact("In alarm", 1, "alarm")], state="ok")
    bars([bar("PIC-1202 pressure high", 50, detail="98 % of the load", state="alarm")], unit="")
    columns([(ms, [3, 1])], stacks=[stack("High", "alarm"), stack("Low", "warning")], target=6)
    tiles([group("Area 100", [tile("FIC-101", "alarm", href=...)])], label="loops")

A status (``state``) is one of the suite's (``alarm``, ``warning``, ``ok``, ``unknown`` ...);
``href`` is a path on the same host (anything else is not drawn as a link).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

WIDGETS_VERSION = 1
MAX_ITEMS = 20
MAX_PARTS = 8
MAX_FACTS = 8
MAX_POINTS = 500
MAX_OPTIONS = 500
MAX_BARS = 10
MAX_STACKS = 6
MAX_BUCKETS = 200
MAX_TILES = 1500


def declared(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The ``[[contributes.widgets]]`` tables of a parsed ``app.toml``."""

    contributes = manifest.get("contributes") or {}
    return [dict(item) for item in contributes.get("widgets") or [] if isinstance(item, Mapping)]


def ids(manifest: Mapping[str, Any]) -> set[str]:
    return {str(item.get("id")) for item in declared(manifest)}


def catalog(manifest: Mapping[str, Any], t: Callable[[str], str] = str) -> dict[str, Any]:
    """The body of ``GET <prefix>api/widgets``: every declared widget, its title and description
    in the person's language (``t``)."""

    widgets = []
    for item in declared(manifest):
        entry: dict[str, Any] = {
            "id": item["id"],
            "title": t(item["title"]),
            "description": t(item["description"]) if item.get("description") else "",
            "size": item.get("size", "m"),
            "kind": item.get("kind", "list"),
            "default": bool(item.get("default", False)),
        }
        if item.get("sizes"):
            entry["sizes"] = [{"w": size["w"], "h": size["h"]} for size in item["sizes"]]
        if item.get("pick"):
            entry["pick"] = t(item["pick"])
        if item.get("multiple") or item.get("pick"):
            entry["multiple"] = True
        widgets.append(entry)
    return {"version": WIDGETS_VERSION, "widgets": widgets}


def _clean(data: dict[str, Any], keep: tuple[str, ...] = ()) -> dict[str, Any]:
    """``data`` without its empty optional fields; the ``keep`` ones stay, even None."""

    return {key: value for key, value in data.items() if value is not None or key in keep}


def _finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def number(
    value: float | int | str | None,
    *,
    unit: str | None = None,
    label: str | None = None,
    state: str | None = None,
    href: str | None = None,
) -> dict[str, Any]:
    return _clean(
        {
            "kind": "number",
            "value": _finite(value),
            "unit": unit,
            "label": label,
            "state": state,
            "href": href,
        },
        keep=("value",),
    )


def item(
    label: str,
    *,
    detail: str | None = None,
    value: float | int | str | None = None,
    state: str | None = None,
    href: str | None = None,
) -> dict[str, Any]:
    return {
        "label": label,
        "detail": detail or None,
        "value": _finite(value),
        "state": state,
        "href": href,
    }


def items(
    rows: Iterable[Mapping[str, Any]], *, href: str | None = None, empty: str | None = None
) -> dict[str, Any]:
    return _clean(
        {
            "kind": "list",
            "items": [dict(row) for row in list(rows)[:MAX_ITEMS]],
            "href": href,
            "empty": empty,
        }
    )


def part(
    label: str, value: int | float, state: str | None = None, href: str | None = None
) -> dict[str, Any]:
    return _clean({"label": label, "value": value, "state": state, "href": href})


def split(
    parts: Iterable[Mapping[str, Any]],
    *,
    total: int | float | None = None,
    label: str | None = None,
    href: str | None = None,
    empty: str | None = None,
) -> dict[str, Any]:
    return _clean(
        {
            "kind": "split",
            "total": total,
            "label": label,
            "parts": [dict(entry) for entry in list(parts)[:MAX_PARTS]],
            "href": href,
            "empty": empty,
        }
    )


def series(
    points: Iterable[tuple[float, float | None]],
    *,
    value: float | int | str | None = None,
    unit: str | None = None,
    label: str | None = None,
    state: str | None = None,
    href: str | None = None,
    empty: str | None = None,
) -> dict[str, Any]:
    """``points`` are ``(time in ms, value)``, oldest first; a None (or NaN) value is a gap. A
    long series is thinned to ``MAX_POINTS`` evenly spaced points."""

    rows = [(float(at), _finite(None if v is None else float(v))) for at, v in points]
    if len(rows) > MAX_POINTS:
        step = len(rows) / MAX_POINTS
        rows = [rows[int(index * step)] for index in range(MAX_POINTS - 1)] + [rows[-1]]
    return _clean(
        {
            "kind": "series",
            "value": _finite(value),
            "unit": unit,
            "label": label,
            "state": state,
            "points": [[at, v] for at, v in rows],
            "href": href,
            "empty": empty,
        }
    )


def fact(
    label: str, value: Any, state: str | None = None, detail: str | None = None
) -> dict[str, Any]:
    """One labelled value; ``detail`` says what it means (shown on hover)."""

    return _clean(
        {"label": label, "value": _finite(value), "state": state, "detail": detail},
        keep=("value",),
    )


def facts(
    title: str | None,
    rows: Iterable[Mapping[str, Any]],
    *,
    status: str | None = None,
    detail: str | None = None,
    state: str | None = None,
    href: str | None = None,
    empty: str | None = None,
) -> dict[str, Any]:
    """One thing: its name (``title``), its status in words (``status``) and colour (``state``),
    a line about it (``detail``) and up to ``MAX_FACTS`` labelled values."""

    return _clean(
        {
            "kind": "facts",
            "title": title,
            "status": status,
            "detail": detail,
            "state": state,
            "facts": [dict(row) for row in list(rows)[:MAX_FACTS]],
            "href": href,
            "empty": empty,
        }
    )


def bar(
    label: str,
    value: float | int | None,
    *,
    detail: str | None = None,
    state: str | None = None,
    href: str | None = None,
) -> dict[str, Any]:
    return _clean(
        {
            "label": label,
            "value": _finite(value),
            "detail": detail or None,
            "state": state,
            "href": href,
        },
        keep=("value",),
    )


def bars(
    rows: Iterable[Mapping[str, Any]],
    *,
    label: str | None = None,
    unit: str | None = None,
    max: float | int | None = None,  # noqa: A002 - the field's name in the shape
    target: float | int | None = None,
    target_label: str | None = None,
    href: str | None = None,
    empty: str | None = None,
) -> dict[str, Any]:
    """A ranking (longest first, as given): up to ``MAX_BARS`` bars, each as long as its value
    against the longest, ``max`` or ``target``; a ``target`` draws a dashed line."""

    return _clean(
        {
            "kind": "bars",
            "label": label,
            "unit": unit,
            "bars": [dict(row) for row in list(rows)[:MAX_BARS]],
            "max": _finite(max),
            "target": _finite(target),
            "target_label": target_label,
            "href": href,
            "empty": empty,
        }
    )


def stack(label: str, state: str | None = None) -> dict[str, Any]:
    return _clean({"label": label, "state": state})


def columns(
    buckets: Iterable[tuple[float, Iterable[float | int | None] | float | int | None]],
    *,
    stacks: Iterable[Mapping[str, Any]] | None = None,
    step: str | None = None,
    value: float | int | str | None = None,
    unit: str | None = None,
    label: str | None = None,
    state: str | None = None,
    target: float | int | None = None,
    target_label: str | None = None,
    href: str | None = None,
    empty: str | None = None,
) -> dict[str, Any]:
    """A count per hour or day (``step``): ``buckets`` are ``(start in ms, values)``, oldest
    first, one value per stack (bottom first; a single number is one plain stack). The last
    ``MAX_BUCKETS`` are kept; ``target`` draws a dashed line at its height."""

    rows: list[list[Any]] = []
    for at, values in buckets:
        if values is None or isinstance(values, int | float):
            values = [values]
        rows.append(
            [float(at), [_finite(None if v is None else float(v)) for v in values][:MAX_STACKS]]
        )
    return _clean(
        {
            "kind": "columns",
            "value": _finite(value),
            "unit": unit,
            "label": label,
            "state": state,
            "stacks": [dict(entry) for entry in list(stacks)[:MAX_STACKS]] if stacks else None,
            "buckets": rows[-MAX_BUCKETS:],
            "step": step,
            "target": _finite(target),
            "target_label": target_label,
            "href": href,
            "empty": empty,
        }
    )


def tile(
    label: str, state: str | None = None, *, detail: str | None = None, href: str | None = None
) -> dict[str, Any]:
    return _clean({"label": label, "state": state, "detail": detail or None, "href": href})


def group(
    label: str | None, rows: Iterable[Mapping[str, Any]], *, href: str | None = None
) -> dict[str, Any]:
    return _clean({"label": label, "tiles": [dict(row) for row in rows], "href": href})


def tiles(
    groups: Iterable[Mapping[str, Any]],
    *,
    value: float | int | str | None = None,
    label: str | None = None,
    href: str | None = None,
    empty: str | None = None,
) -> dict[str, Any]:
    """A status map: one square per thing, in groups (an area, a source). At most ``MAX_TILES``
    squares are sent; ``more`` says how many were left out."""

    kept: list[dict[str, Any]] = []
    room, more = MAX_TILES, 0
    for entry in groups:
        squares = list(entry.get("tiles") or [])
        if room <= 0:
            more += len(squares)
            continue
        more += max(0, len(squares) - room)
        kept.append({**dict(entry), "tiles": [dict(row) for row in squares[:room]]})
        room -= min(room, len(squares))
    return _clean(
        {
            "kind": "tiles",
            "value": _finite(value),
            "label": label,
            "groups": kept,
            "more": more or None,
            "href": href,
            "empty": empty,
        }
    )


def ago(when: Any, t: Callable[..., str], now: datetime | None = None) -> str | None:
    """``when`` (an ISO instant, a datetime or ms since 1970) from now, in words: "5 min ago",
    "in 2 h"; None when there is no time (or it cannot be read)."""

    if when in (None, ""):
        return None
    try:
        if isinstance(when, int | float):
            moment = datetime.fromtimestamp(float(when) / 1000, UTC)
        elif isinstance(when, datetime):
            moment = when
        else:
            moment = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    seconds = ((now or datetime.now(UTC)) - moment).total_seconds()
    later, seconds = seconds < 0, abs(seconds)
    if seconds < 60:
        return t("just now")
    for size, unit in ((86400, "d"), (3600, "h"), (60, "min")):
        if seconds >= size:
            n = int(seconds // size)
            return (
                t("in {n} {unit}", n=n, unit=unit) if later else t("{n} {unit} ago", n=n, unit=unit)
            )
    return None


def option(value: str, label: str, detail: str | None = None) -> dict[str, Any]:
    return _clean({"value": value, "label": label, "detail": detail or None})


def options(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The body of ``GET <prefix>api/widgets/<id>/options``."""

    return {"options": [dict(row) for row in list(rows)[:MAX_OPTIONS]]}


__all__ = [
    "MAX_BARS",
    "MAX_BUCKETS",
    "MAX_FACTS",
    "MAX_ITEMS",
    "MAX_OPTIONS",
    "MAX_PARTS",
    "MAX_POINTS",
    "MAX_STACKS",
    "MAX_TILES",
    "WIDGETS_VERSION",
    "ago",
    "bar",
    "bars",
    "catalog",
    "columns",
    "declared",
    "fact",
    "facts",
    "group",
    "ids",
    "item",
    "items",
    "number",
    "option",
    "options",
    "part",
    "series",
    "split",
    "stack",
    "tile",
    "tiles",
]
