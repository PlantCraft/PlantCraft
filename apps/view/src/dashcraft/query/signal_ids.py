"""Cards saved with bare tags (``FIC-101.PV``) move to API v1's signal ids (``scenario:FIC-101.PV``).

PlantCraft still reads a bare tag that exactly one source has until API v1 is frozen (D2), so
old cards keep working meanwhile; this renames them for good. Ids are taken as PlantCraft
lists them, never built from a tag.
"""

from __future__ import annotations

import logging
from typing import Any

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.refs import split_signal_id

from dashcraft.dashboards.store import DashboardStore

LOGGER = logging.getLogger(__name__)


def signal_renames(stored: set[str], signals: list[dict[str, Any]]) -> dict[str, str]:
    """``{bare tag: id}`` for the stored ids that are no signal's id but one signal's tag."""

    ids = {signal["id"] for signal in signals}
    by_tag: dict[str, list[str]] = {}
    for signal_id in ids:
        by_tag.setdefault(split_signal_id(signal_id)[1], []).append(signal_id)
    renames = {}
    for old in stored - ids:
        found = by_tag.get(old, [])
        if len(found) == 1:
            renames[old] = found[0]
    return renames


def migrate_signal_ids(store: DashboardStore, client: Any) -> dict[str, Any]:
    """Rename the bare tags of saved cards; ``{"renamed": {...}, "dashboards": n}``."""

    stored = store.signal_ids()
    if not stored:
        return {"renamed": {}, "dashboards": 0}
    try:
        signals = client.signals()
    except PlantCraftError as exc:
        LOGGER.warning("Signal ids of saved cards not checked: %s", exc)
        return {"renamed": {}, "dashboards": 0, "error": str(exc)}
    renames = signal_renames(stored, signals)
    changed = store.rename_signals(renames) if renames else 0
    if renames:
        LOGGER.info("Renamed %d signal ids on %d dashboards", len(renames), changed)
    return {"renamed": renames, "dashboards": changed}
