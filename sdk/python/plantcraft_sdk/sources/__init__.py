"""What PlantCraft's own data sources and Historian's source adapters share (written once).

``SignalInfo`` is one signal a source lists, ``NO_VALUE`` starts a per-tag error that only says
the tag had nothing new, and ``asset_from_tag`` groups tags under the asset they belong to.
``plantcraft_sdk.sources.pi_web_api`` is the PI Web API client both read PI through (it needs
``requests``: the ``pi`` extra).
"""

from __future__ import annotations

from dataclasses import dataclass

# Start of a per-tag error that only says the tag had nothing new (quiet in the logs).
NO_VALUE = "no value"


@dataclass(frozen=True)
class SignalInfo:
    tag: str
    name: str
    asset: str
    unit: str = ""
    description: str = ""
    data_type: str = "number"
    step: bool = False
    path: str = ""


def asset_from_tag(tag: str) -> str:
    """Group tags like ``FIC-101.PV`` or ``FIC101_PV`` under ``FIC-101``."""

    for separator in (".", ":", "/"):
        if separator in tag:
            return tag.rsplit(separator, 1)[0]
    return tag


__all__ = ["NO_VALUE", "SignalInfo", "asset_from_tag"]
