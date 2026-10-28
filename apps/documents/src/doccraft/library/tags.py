"""The plant's tags in a text: instrument and equipment tags in the ISA-5.1 style (``FIC-1003``,
``FV-1003``, ``P-1003``, ``TK-1001``), kept only when PlantCraft's asset tree or signals know them,
so a page number or a date never becomes a link."""

from __future__ import annotations

import re
from collections.abc import Iterable

TAG = re.compile(r"\b([A-Z]{1,5})[-_ ]?(\d{2,5}[A-Z]?)\b")


def candidates(text: str) -> set[str]:
    return {f"{letters}-{number}" for letters, number in TAG.findall(text)}


def normal(tag: str) -> str:
    match = TAG.fullmatch(tag.strip().upper())
    return f"{match.group(1)}-{match.group(2)}" if match else tag.strip().upper()


def known(text: str, ids: dict[str, str]) -> list[str]:
    """The asset ids of the tags in ``text``; ``ids`` maps a normalised tag to an asset id."""

    found = []
    for tag in sorted(candidates(text)):
        asset = ids.get(tag)
        if asset and asset not in found:
            found.append(asset)
    return found


def index(asset_ids: Iterable[str]) -> dict[str, str]:
    """Normalised tag -> asset id, for the ids that look like tags (``FIC-1003``, ``U-200``)."""

    found: dict[str, str] = {}
    for asset in asset_ids:
        if TAG.fullmatch(asset.upper()):
            found[normal(asset)] = asset
    return found
