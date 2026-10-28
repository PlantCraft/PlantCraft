"""Loops from PlantCraft's asset catalog.

``GET /api/v1/assets`` lists every asset (read once, so parents resolve). An asset is a control
loop when its ``type_path`` (type ids from the root type to its own) contains the loop type id
(``"loop"``, ``LINKCRAFT_LOOP_ASSET_KIND``), so a ``cascade_loop`` that derives from ``loop`` is
one too; a PlantCraft without ``type_path`` is read by ``kind`` as before.

From each loop asset LinkCraft takes:

- ``signals`` by role (``pv``, ``sp``, ``op``, ``mode``, ``secondary``);
- ``attributes``: ``description`` (service), ``loop_type``, ``criticality``, ``action`` and
  ``controller`` (``AssetRecord``); ``loop_type`` and ``criticality`` give the loop's starting
  algorithm, parameters and weight (``catalog/loop_types.py``);
- ``relations`` (``controls``, ``measures``, ``feeds``, ``downstream_of``), kept for display;
- the parent asset's name as the area and the grandparent's as the unit.

Required roles come from the type definitions (``GET /api/v1/asset-types``) along the asset's
type path, and are ``pv`` and ``op`` when PlantCraft does not serve them. A loop asset without
a signal for a required role is still synced, as an incomplete record: listed with the roles
missing, never analysed, until someone binds them on the asset's page in PlantCraft.

Every field is read defensively: a payload with missing fields, wrong types or a cycle in its
parents is synced as far as it makes sense, never a crash.
"""

from __future__ import annotations

import logging
from typing import Any

from plantcraft_sdk.client import NotFound, PlantCraftClient, PlantCraftError
from pydantic import ValidationError

from linkcraft.catalog.loop_types import (
    DEFAULT_CRITICALITY,
    default_profile,
    known_criticality,
)
from linkcraft.config import ROLES, AssetRecord, LoopConfig, LoopSignals

logger = logging.getLogger(__name__)

# Roles LinkCraft needs on a control loop when PlantCraft does not say which are required.
FALLBACK_REQUIRED_ROLES = ("pv", "op")
MAX_ID = 120
MAX_NAME = 200
MAX_TEXT = 500
# The most asset types read from one payload (a tree walked without recursion).
MAX_TYPES = 10_000


def _text(value: Any, limit: int = MAX_TEXT) -> str | None:
    """A non-empty string (trimmed and cut to ``limit``), else ``None``."""

    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def type_path(asset: dict[str, Any]) -> list[str]:
    """The asset's type ids from the root type to its own; ``[kind]`` on an older PlantCraft."""

    raw = asset.get("type_path")
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        path = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
        if path:
            return path
    kind = _text(asset.get("kind"))
    return [kind] if kind else []


def is_loop(asset: Any, loop_type_id: str = "loop") -> bool:
    return isinstance(asset, dict) and loop_type_id in type_path(asset)


def _role_name(item: Any) -> tuple[str | None, bool]:
    """(role, required) from one role entry of a type definition."""

    if isinstance(item, str):
        return item.strip().lower() or None, False
    if isinstance(item, dict):
        name = _text(item.get("role") or item.get("key") or item.get("id"))
        return (name.lower() if name else None), item.get("required") is True
    return None, False


def required_roles_by_type(asset_types: Any) -> dict[str, set[str]]:
    """Required signal roles of each type id, from ``GET /api/v1/asset-types``.

    The payload lists every type with its roles, inherited ones included
    (``[{"key": "pv", "required": true}, ...]``); ``children`` names the types that may sit inside
    it (ids). Nested type objects in ``children`` are read too. Also accepted: ``role`` for ``key``, names, a role map
    (``{"pv": {"required": true}}``) and a ``required_roles`` list; anything else is ignored.
    """

    found: dict[str, set[str]] = {}
    if isinstance(asset_types, dict):
        asset_types = asset_types.get("types") or asset_types.get("items") or []
    if not isinstance(asset_types, list):
        return found
    # Nested types in ``children`` are walked without recursion (hostile depth).
    pending = list(asset_types)
    seen = 0
    while pending and seen < MAX_TYPES:
        item = pending.pop()
        seen += 1
        if not isinstance(item, dict):
            continue
        children = item.get("children")
        if isinstance(children, list):
            pending.extend(children)
        type_id = _text(item.get("id") or item.get("type_id"))
        if not type_id:
            continue
        required: set[str] = set()
        roles = item.get("roles") or item.get("signal_roles")
        if isinstance(roles, dict):
            for name, spec in roles.items():
                if isinstance(name, str) and isinstance(spec, dict) and spec.get("required"):
                    required.add(name.strip().lower())
        elif isinstance(roles, list):
            for role in roles:
                name, is_required = _role_name(role)
                if name and is_required:
                    required.add(name)
        listed = item.get("required_roles")
        if isinstance(listed, list):
            required |= {name for name in (_role_name(role)[0] for role in listed) if name}
        found[type_id] = required
    return found


def _required_roles(path: list[str], by_type: dict[str, set[str]] | None) -> tuple[list[str], str]:
    known = [type_id for type_id in path if by_type and type_id in by_type]
    if not known:
        return list(FALLBACK_REQUIRED_ROLES), "fallback"
    roles = {"pv"}  # LinkCraft never analyses a loop without a PV
    for type_id in known:
        roles |= by_type[type_id]  # type: ignore[index]
    ordered = [role for role in ROLES if role in roles]
    return ordered + sorted(roles - set(ROLES)), "asset_types"


def _relations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    relations = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        kind, target = _text(item.get("type"), 40), _text(item.get("to"), MAX_ID)
        if kind and target:
            relations.append({"type": kind, "to": target})
    return relations


def _place(asset: dict[str, Any], names: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Area (parent's name) and unit (grandparent's name); a parent cycle stops at the asset."""

    own = str(asset.get("id"))
    parent = names.get(str(asset.get("parent_id") or "")) or {}
    if str(parent.get("id")) == own:
        parent = {}
    grandparent = names.get(str(parent.get("parent_id") or "")) or {}
    if str(grandparent.get("id")) in {own, str(parent.get("id"))}:
        grandparent = {}
    return (
        _text(parent.get("name"), MAX_NAME) or "No area",
        _text(grandparent.get("name"), MAX_NAME) or "",
    )


def loop_from_asset(
    asset: Any,
    names: dict[str, dict[str, Any]],
    by_type: dict[str, set[str]] | None = None,
) -> LoopConfig | None:
    """The loop an asset describes, or ``None`` when it cannot be one (no usable id).

    An asset without a signal for a required role is returned as an incomplete record.
    """

    if not isinstance(asset, dict):
        return None
    loop_id = _text(asset.get("id"), MAX_ID + 1)
    if not loop_id or len(loop_id) > MAX_ID:
        return None
    signals = {
        role: value.strip()
        for role, value in _dict(asset.get("signals")).items()
        if role in ROLES and isinstance(value, str) and value.strip()
    }
    attributes = _dict(asset.get("attributes"))
    path = type_path(asset)
    required, roles_source = _required_roles(path, by_type)
    record = AssetRecord(
        type_id=path[-1] if path else "loop",
        type_path=path,
        loop_type=_text(attributes.get("loop_type"), 80),
        criticality=_text(attributes.get("criticality"), 80),
        action=_text(attributes.get("action"), 80),
        controller=_text(attributes.get("controller"), 80),
        relations=_relations(asset.get("relations")),
        required_roles=required,
        missing_roles=[role for role in required if not signals.get(role)],
        roles_source=roles_source,
    )
    area, unit = _place(asset, names)
    try:
        return LoopConfig(
            loop_id=loop_id,
            name=_text(asset.get("name"), MAX_NAME) or loop_id,
            area=area,
            unit=unit,
            service=_text(attributes.get("description")) or "",
            signals=LoopSignals(**signals),
            profile_id=default_profile(record.loop_type),
            metadata={
                "asset_id": loop_id,
                "criticality": known_criticality(record.criticality) or DEFAULT_CRITICALITY,
            },
            asset_record=record,
        )
    except ValidationError:
        logger.warning("Asset %s could not be read as a loop", loop_id, exc_info=True)
        return None


def asset_types(client: Any) -> Any:
    """``GET /api/v1/asset-types``, or ``None`` when this PlantCraft does not serve it."""

    reader = getattr(client, "asset_types", None)
    if not callable(reader):  # no app key: no service client
        return None
    try:
        return reader()
    except (PlantCraftError, AttributeError, TypeError, ValueError) as exc:
        logger.info("Asset types not available, required roles default to PV and OP: %s", exc)
        return None


def loops_from_processcraft(client: PlantCraftClient, kind: str = "loop") -> list[LoopConfig]:
    """Every loop asset PlantCraft knows, as LinkCraft loops (incomplete ones included)."""

    everything = client.assets()
    if not isinstance(everything, list):
        everything = []
    assets = [item for item in everything if isinstance(item, dict)]
    names = {str(item.get("id")): item for item in assets}
    loop_assets = [asset for asset in assets if is_loop(asset, kind)]
    types = asset_types(client) if loop_assets else None
    by_type = required_roles_by_type(types) if types is not None else None
    loops: dict[str, LoopConfig] = {}
    for asset in loop_assets:
        loop = loop_from_asset(asset, names, by_type)
        if loop is not None and loop.loop_id not in loops:
            loops[loop.loop_id] = loop
    return list(loops.values())


def rename_signal_ids(store: Any, client: Any) -> dict[str, int]:
    """Loops defined here keep their signals by the id PlantCraft answers for them.

    Signal ids became ``<source id>:<tag>`` in API v1 (D2); a loop saved earlier names bare
    tags. Each signal of a loop not checked yet is looked up (``GET /api/v1/signals/{id}``
    still answers a bare tag one source has) and stored by the ``id`` of the answer; ids are
    never built from a tag. A loop is checked once: an unknown signal (404) is kept as it is
    (its reads fail with PlantCraft's reason), while a failed lookup is tried again next sync.
    """

    reader = getattr(client, "signal", None)
    counts = {"checked": 0, "renamed": 0}
    if not callable(reader):
        return counts
    for loop in store.unchecked_signal_loops():
        renamed: dict[str, str] = {}
        try:
            for role, signal_id in loop.signals.model_dump().items():
                if not signal_id:
                    continue
                try:
                    answered = reader(signal_id)
                except NotFound:
                    logger.warning("Loop %s: PlantCraft has no signal %s", loop.loop_id, signal_id)
                    continue
                new_id = answered.get("id") if isinstance(answered, dict) else None
                if isinstance(new_id, str) and new_id.strip() and new_id != signal_id:
                    renamed[role] = new_id
        except PlantCraftError as exc:
            logger.info("Signal ids of loop %s not checked yet: %s", loop.loop_id, exc)
            continue
        store.rename_signals(loop.loop_id, renamed)
        counts["checked"] += 1
        counts["renamed"] += bool(renamed)
    return counts
