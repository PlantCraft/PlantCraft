"""The events StarterCraft writes, by the names its ``app.toml`` declares (``[[publishes.events]]``),
through ``EventCatalog``: a name or a payload field the manifest does not declare is refused here,
before PlantCraft sees it. One function per event."""

from __future__ import annotations

import logging
from typing import Any

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.events import EventCatalog

from starter.i18n import t
from starter.meta import manifest

LOGGER = logging.getLogger(__name__)


def note_written(client: Any, note: dict[str, Any], asset_name: str) -> None:
    """``starter.note.written``; never fails the request that wrote the note."""

    if client is None:
        return
    try:
        event = EventCatalog.from_manifest(manifest()).event(
            "note.written",
            f"asset:{note['asset_id']}",
            summary=t("Note on {asset}", asset=asset_name),
            payload={"note": note["note_id"]},
        )
        client.post_events([event])
    except (PlantCraftError, ValueError) as exc:
        LOGGER.warning("Event note.written not written: %s", exc)
