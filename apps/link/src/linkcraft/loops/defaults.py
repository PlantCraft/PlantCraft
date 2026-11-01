"""Where a loop's CPM settings come from, without the database: the asset record's defaults
and, for the interface, whether each setting was set here, comes from the asset or is Link's
default (PlantCraft ``docs/app-standard.md``, section 5)."""

from __future__ import annotations

from linkcraft.catalog.loop_types import (
    DEFAULT_CRITICALITY,
    GENERIC_PROFILE,
    default_profile,
    known_criticality,
    known_loop_type,
)
from linkcraft.config import LoopConfig

# Settings that start from the asset record and that a person can take over here.
OWNABLE = ("profile_id", "criticality")
# What every loop started with before the asset catalog (rows without an asset record).
PRE_CATALOG_DEFAULTS = {"profile_id": GENERIC_PROFILE, "criticality": DEFAULT_CRITICALITY}


def record_defaults(loop: LoopConfig) -> dict[str, str]:
    """Algorithm and criticality as the asset record (or the lack of one) makes them."""

    record = loop.asset_record
    return {
        "profile_id": default_profile(record.loop_type if record else None),
        "criticality": known_criticality(record.criticality if record else None)
        or DEFAULT_CRITICALITY,
    }


def _setting(loop: LoopConfig, key: str) -> str:
    if key == "criticality":
        return str((loop.metadata or {}).get("criticality") or DEFAULT_CRITICALITY)
    return str(loop.profile_id or GENERIC_PROFILE)


def setting_sources(loop: LoopConfig, origin: str) -> dict[str, str]:
    """Where each CPM setting of a loop comes from, for the interface.

    ``here``: a person set it in Analytics; ``asset``: derived from PlantCraft's asset record
    (its loop type or criticality); ``default``: Analytics' default (the record says nothing
    Analytics knows).
    """

    record = loop.asset_record
    known = {
        "profile_id": bool(record and known_loop_type(record.loop_type)),
        "criticality": bool(record and known_criticality(record.criticality)),
    }
    sources = {}
    for key in OWNABLE:
        if origin != "processcraft" or key in loop.set_here:
            sources[key] = "here"
        else:
            sources[key] = "asset" if known[key] else "default"
    sources["method_parameters"] = (
        "here"
        if loop.method_parameters
        else "asset"
        if record and known_loop_type(record.loop_type)
        else "default"
    )
    return sources
