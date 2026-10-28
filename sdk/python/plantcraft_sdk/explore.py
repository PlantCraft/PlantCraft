"""The Explorer's answers (API v1 ``GET /api/v1/explore``), written once for PlantCraft and
``FakePlantCraft``: the plant as folders, each asset with its signals, the series apps
computed about it and the events that named it, and a search that lands on a value with its
path (Alarms round 11).

Pure functions over API v1 shapes: ``assets`` as ``GET /api/v1/assets`` lists them (result
assets left out), ``signals`` as ``GET /api/v1/signals`` (derived ones carry ``app`` and
``subject``)::

    contents = asset_contents(asset, assets, signals, events=...)   # one asset, opened
    hits = search(assets, signals, "FIC-1001 health")                # words to values
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["MAX_HITS", "asset_contents", "children", "path", "search", "top"]

MAX_HITS = 40


def _brief(item: Mapping[str, Any]) -> dict[str, Any]:
    return {"id": item["id"], "name": item.get("name") or item["id"], "kind": item.get("kind")}


def path(
    item: Mapping[str, Any] | None, by_id: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The asset's ancestors and itself, from the top: ``[{"id", "name"}]``."""

    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    while item is not None and item["id"] not in seen:
        seen.add(item["id"])
        chain.append({"id": item["id"], "name": item.get("name") or item["id"]})
        item = by_id.get(item.get("parent_id") or "")
    return chain[::-1]


def children(assets: list[Mapping[str, Any]], parent: str | None) -> list[dict[str, Any]]:
    """The assets right under ``parent`` (None: the plant's top), by name, each with how many
    children and signal roles it has."""

    counts: dict[str, int] = {}
    for item in assets:
        if item.get("parent_id"):
            counts[item["parent_id"]] = counts.get(item["parent_id"], 0) + 1
    rows = [
        {
            **_brief(item),
            "children": counts.get(item["id"], 0),
            "roles": len(item.get("signals") or {}),
        }
        for item in assets
        if (item.get("parent_id") or None) == parent
    ]
    return sorted(rows, key=lambda row: str(row["name"]).lower())


def top(assets: list[Mapping[str, Any]]) -> dict[str, Any]:
    """The answer without an asset: the plant's top assets."""

    return {"asset": None, "path": [], "children": children(assets, None)}


def _output(item: Mapping[str, Any], apps: Mapping[str, str]) -> dict[str, Any]:
    app = str(item.get("app") or "")
    return {
        "id": item["id"],
        "name": item.get("name") or item["id"],
        "unit": item.get("unit") or "",
        "app": app,
        "app_name": apps.get(app, app),
        "result": item.get("result") or "",
        "kind": item.get("kind") or "number",
    }


def asset_contents(
    asset: Mapping[str, Any],
    assets: list[Mapping[str, Any]],
    signals: Iterable[Mapping[str, Any]],
    *,
    events: list[dict[str, Any]] | None = None,
    apps: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One asset opened: its path, children, signals by role, the series apps computed about
    it (``outputs``) and ``events`` (as ``EventStore.about`` counts them, open ones first)."""

    apps = apps or {}
    by_id = {item["id"]: item for item in assets}
    known = {item["id"]: item for item in signals}
    subject = f"asset:{asset['id']}"
    roles = [
        {
            "role": role,
            "id": signal_id,
            "name": (known.get(signal_id) or {}).get("name") or signal_id,
            "unit": (known.get(signal_id) or {}).get("unit") or "",
            "kind": (known.get(signal_id) or {}).get("kind") or "number",
        }
        for role, signal_id in sorted((asset.get("signals") or {}).items())
    ]
    outputs = [_output(item, apps) for item in known.values() if item.get("subject") == subject]
    found = sorted(events or [], key=lambda item: str(item.get("last_at") or ""), reverse=True)
    found.sort(key=lambda item: -int(item.get("open") or 0))
    return {
        "asset": {**_brief(asset), "type_path": list(asset.get("type_path") or [])},
        "path": path(asset, by_id),
        "children": children(assets, asset["id"]),
        "signals": roles,
        "outputs": sorted(outputs, key=lambda row: (row["app"], str(row["name"]).lower())),
        "events": found,
    }


def search(
    assets: list[Mapping[str, Any]],
    signals: Iterable[Mapping[str, Any]],
    q: str,
    *,
    apps: Mapping[str, str] | None = None,
    limit: int = MAX_HITS,
) -> list[dict[str, Any]]:
    """Assets, then plant signals, then the series apps computed, whose words (with their path
    and role) hold every word of ``q`` (``FIC-1001 health``), each with its asset path."""

    apps = apps or {}
    words = [word for word in q.lower().split() if word]
    if not words:
        return []
    by_id = {item["id"]: item for item in assets}
    holder: dict[str, tuple[Mapping[str, Any], str]] = {}
    for item in assets:
        for role, signal_id in (item.get("signals") or {}).items():
            holder.setdefault(signal_id, (item, role))

    def matches(*texts: str) -> bool:
        text = " ".join(texts).lower()
        return all(word in text for word in words)

    hits: list[dict[str, Any]] = []
    for item in assets:
        chain = path(item, by_id)
        if matches(item["id"], *(step["name"] for step in chain)):
            hits.append({"type": "asset", **_brief(item), "path": chain[:-1]})
    for item in signals:
        subject = str(item.get("subject") or "")
        name = str(item.get("name") or "")
        if subject.startswith("asset:"):
            chain = path(by_id.get(subject.removeprefix("asset:")), by_id)
            if matches(item["id"], name, *(step["name"] for step in chain)):
                hits.append({"type": "output", **_output(item, apps), "path": chain})
            continue
        if item.get("app"):
            continue
        owner, role = holder.get(item["id"], (None, ""))
        chain = path(owner, by_id)
        if matches(item["id"], name, role, *(step["name"] for step in chain)):
            hits.append(
                {
                    "type": "signal",
                    "id": item["id"],
                    "name": name or item["id"],
                    "unit": item.get("unit") or "",
                    "kind": item.get("kind") or "number",
                    "role": role,
                    "path": chain,
                }
            )
    order = {"asset": 0, "signal": 1, "output": 2}
    hits.sort(key=lambda hit: (order[hit["type"]], len(hit["path"]), str(hit["name"]).lower()))
    return hits[:limit]
