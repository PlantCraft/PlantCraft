"""Assets: the one tree every part of the suite points at (see ``store.py`` and ``types.py``)."""

from __future__ import annotations

from processcraft.assets.store import ASSET_KINDS, KIND_LABELS, AssetStore, asset_id_for
from processcraft.assets.types import AssetTypeConflict, AssetTypeError, AssetTypeStore

__all__ = [
    "ASSET_KINDS",
    "KIND_LABELS",
    "AssetStore",
    "AssetTypeConflict",
    "AssetTypeError",
    "AssetTypeStore",
    "asset_id_for",
]
