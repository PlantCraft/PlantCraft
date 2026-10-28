"""A schedule's time zone as saved and as its clock (owner, 2026-10-25): ``local`` is the
installation's zone, read from PlantCraft (``PlantCraftClient.installation_time_zone()``,
cached a minute there), so a schedule saved on "Local time" follows the installation when its zone
changes; ``UTC``, ``Etc/GMT+3`` (UTC−3) and a city's IANA name are themselves. Written once, in
the SDK (``plantcraft_sdk.utc``); Link's code imports it from here."""

from __future__ import annotations

from plantcraft_sdk.utc import (
    LOCAL,
    installation_zone,
    local_text,
    use_installation_zone,
    zone_of,
)

__all__ = ["LOCAL", "installation_zone", "local_text", "use_installation_zone", "zone_of"]
