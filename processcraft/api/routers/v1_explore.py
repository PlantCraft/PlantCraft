"""API v1: the Explorer, one way to find any value or event of the suite (Alarms round 11).

A person goes into the plant as into folders, asset by asset, and finds on each asset everything
the suite has about it, whatever app wrote it: its signals (by role), the series apps computed
about it (Link's health, an algorithm's outputs), the events that named it (open conditions
first) and its children. Or types a few words and lands on the value. Every app's pickers draw
the same Explorer (``@plantcraft/ui`` ``Explorer``) through the app's own route, with the
person's token, so a person finds only what they may read. Nothing here reads a series: a
value's preview is ``GET /signals/{id}/value``. The answers are ``plantcraft_sdk.explore``'s,
shared with ``FakePlantCraft``.

``GET /api/v1/explore`` (no ``asset``): the plant's top assets. ``?asset=<id>``: that asset's
contents. ``?q=<words>``: assets, signals and series matching, each with its path.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from plantcraft_sdk import explore as answers
from processcraft.api.deps import Runtime
from processcraft.api.identity import V1Reader, V1Scope
from processcraft.api.routers.v1 import RESULT_TYPE, _answer, _assets, _scoped
from processcraft.api.routers.v1_links import utc_text_now
from processcraft.auth.suite import suite_apps
from processcraft.events.catalog import platform_catalog
from processcraft.i18n import t

router = APIRouter(prefix="/api/v1")

# Events about an asset are counted from this many days back.
EVENT_DAYS = 30


def _titles(rt: Any) -> dict[str, str]:
    """Event kind -> its title in the catalogs."""

    titles = {item["kind"]: item.get("title") or item["kind"] for item in platform_catalog()}
    for app, catalog in rt.workspace.events.catalogs().items():
        for spec in catalog["events"]:
            titles[f"{app}.{spec['name']}"] = spec.get("title") or spec["name"]
    return titles


def _signals(scope: Any, rt: Any) -> list[dict[str, Any]]:
    found = _answer(rt.datalayer.signals, "")
    return found if scope.everything else [item for item in found if scope.signal_item(item)]


@router.get("/explore")
def explore(
    _caller: V1Reader,
    rt: Runtime,
    scope: V1Scope,
    asset: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str, Query(max_length=120)] = "",
) -> dict[str, Any]:
    """The plant's top assets, one asset's contents, or what matches ``q`` (module docstring)."""

    # Only the part of the plant the caller sees (docs/asset-scope.md).
    assets = [item for item in _scoped(scope, _assets(rt)) if item["kind"] != RESULT_TYPE]
    apps = {item.id: item.name for item in suite_apps()}
    if q.strip():
        signals = _signals(scope, rt)
        return {"hits": answers.search(assets, signals, q, apps=apps)}
    if not asset:
        return answers.top(assets)
    found = next((item for item in assets if item["id"] == asset), None)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    titles = _titles(rt)
    since = utc_text_now(minutes=-EVENT_DAYS * 24 * 60)
    events = [
        {**item, "title": titles.get(item["kind"], item["kind"])}
        for item in rt.workspace.events.about(f"asset:{asset}", since=since)
    ]
    signals = _signals(scope, rt)
    return answers.asset_contents(found, assets, signals, events=events, apps=apps)


__all__ = ["router"]
