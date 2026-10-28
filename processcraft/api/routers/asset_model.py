"""HTTP routes: asset types (admins), and each asset's record, relations and signals by role.

Only admins edit types. Editors fill the record (attribute values), the
relations and the signal roles of an asset; every change lands in the asset's
history (who and when) and in the audit log. The apps read the same model
through API v1 (``type_path``, ``attributes``, ``relations``, ``/asset-types``).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

from plantcraft_sdk.assets import DATA_TYPES, RELATION_TYPES
from plantcraft_sdk.refs import split_signal_id
from processcraft.api.deps import AdminUser, CurrentUser, Runtime
from processcraft.assets import AssetTypeConflict, AssetTypeError
from processcraft.i18n import t
from processcraft.platform.signals import AmbiguousSignal

router = APIRouter()

Short = Annotated[str, StringConstraints(max_length=120)]
TypeRef = Annotated[str, StringConstraints(min_length=1, max_length=64)]
Scalar = Annotated[str, StringConstraints(max_length=2000)] | float | int | bool | None
MAX_VALUES = 200


class AttributeDefinition(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=60)
    data_type: str = Field(default="text", max_length=10)
    unit: str = Field(default="", max_length=30)
    required: bool = False
    default: Scalar = None
    options: list[Short] = Field(default_factory=list, max_length=200)


class RoleDefinition(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=60)
    unit: str = Field(default="", max_length=30)
    required: bool = False


class AssetTypePayload(BaseModel):
    id: str | None = Field(default=None, max_length=31)
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=600)
    icon: str = Field(default="", max_length=40)
    parent: str | None = Field(default=None, max_length=64)
    attributes: list[AttributeDefinition] = Field(default_factory=list, max_length=100)
    roles: list[RoleDefinition] = Field(default_factory=list, max_length=50)
    children: list[TypeRef] = Field(default_factory=list, max_length=100)


class AttributeValues(BaseModel):
    values: dict[Annotated[str, StringConstraints(min_length=1, max_length=40)], Scalar]


class RelationPayload(BaseModel):
    type: str = Field(min_length=1, max_length=30)
    to: str = Field(min_length=1, max_length=200)


class SignalRolePayload(BaseModel):
    signal_id: str = Field(min_length=1, max_length=300)
    role: str = Field(default="", max_length=40)


def _store(rt: Any) -> Any:
    return rt.workspace.assets


def _require_asset(rt: Any, asset_id: str) -> dict[str, Any]:
    asset = _store(rt).get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    return asset


def _history(
    rt: Any, kind: str, asset_id: str, user: str, summary: str, payload: dict, refs: list[str]
) -> None:
    rt.platform.record_asset_change(kind, asset_id, user, summary, payload, refs)


# Types ------------------------------------------------------------------------------


def _type_view(rt: Any, resolved: dict[str, Any], counts: dict[str, int]) -> dict[str, Any]:
    """A resolved type with where each attribute and role comes from and how many assets use it."""

    types = _store(rt).types
    definitions = types.definitions()
    origin_of: dict[tuple[str, str], str] = {}
    for ancestor in resolved["path"]:
        own = definitions.get(ancestor) or {}
        for entry in own.get("attributes") or []:
            origin_of.setdefault(("attribute", entry["key"]), ancestor)
        for entry in own.get("roles") or []:
            origin_of.setdefault(("role", entry["key"]), ancestor)
    below = types.subtypes(resolved["id"])
    own = definitions.get(resolved["id"]) or {}
    return {
        **resolved,
        "attributes": [
            {**entry, "from": origin_of.get(("attribute", entry["key"]), resolved["id"])}
            for entry in resolved["attributes"]
        ],
        "roles": [
            {**entry, "from": origin_of.get(("role", entry["key"]), resolved["id"])}
            for entry in resolved["roles"]
        ],
        "own_children": list(own.get("children") or []),
        "builtin": resolved["id"] in {"site", "unit", "area", "equipment", "loop"},
        "count": counts.get(resolved["id"], 0),
        "total": sum(counts.get(item, 0) for item in below),
        "updated_at": own.get("updated_at"),
        "updated_by": own.get("updated_by"),
    }


@router.get("/api/asset-types")
def asset_types(_user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The type catalog with inheritance resolved, the data types and the relations."""

    store = _store(rt)
    counts = store.counts()
    return {
        "types": [_type_view(rt, item, counts) for item in store.types.all_resolved()],
        "data_types": list(DATA_TYPES),
        "relations": [
            {"id": key, "label": t(label), "inverse": t(inverse)}
            for key, (label, inverse) in RELATION_TYPES.items()
        ],
    }


def _require_type(rt: Any, type_id: str) -> dict[str, Any]:
    resolved = _store(rt).types.resolved(type_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail=t("Asset type not found."))
    return resolved


@router.get("/api/asset-types/{type_id}")
def asset_type(type_id: str, _user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    return _type_view(rt, _require_type(rt, type_id), _store(rt).counts())


def _definition(payload: AssetTypePayload) -> dict[str, Any]:
    return payload.model_dump()


@router.post("/api/asset-types", status_code=201)
def create_asset_type(payload: AssetTypePayload, user: AdminUser, rt: Runtime) -> dict[str, Any]:
    try:
        created = _store(rt).types.create(_definition(payload), actor=user)
    except AssetTypeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AssetTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        user, "asset_type.create", f"asset_type:{created['id']}", payload.model_dump()
    )
    type(_store(rt)).version += 1
    return _type_view(rt, created, _store(rt).counts())


@router.put("/api/asset-types/{type_id}")
def update_asset_type(
    type_id: str, payload: AssetTypePayload, user: AdminUser, rt: Runtime
) -> dict[str, Any]:
    _require_type(rt, type_id)
    before = _store(rt).types.own(type_id)
    try:
        updated = _store(rt).types.update(type_id, _definition(payload), actor=user)
    except AssetTypeConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AssetTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(
        user,
        "asset_type.update",
        f"asset_type:{type_id}",
        {"before": before, "after": payload.model_dump(exclude={"id"})},
    )
    type(_store(rt)).version += 1
    return _type_view(rt, updated, _store(rt).counts())


@router.delete("/api/asset-types/{type_id}", status_code=204)
def delete_asset_type(type_id: str, user: AdminUser, rt: Runtime) -> None:
    _require_type(rt, type_id)
    store = _store(rt)
    try:
        store.types.delete(type_id, in_use=store.counts().get(type_id, 0))
    except AssetTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.workspace.audit.record(user, "asset_type.delete", f"asset_type:{type_id}")
    type(store).version += 1


# One asset's record --------------------------------------------------------------------


@router.patch("/api/assets/{asset_id}/attributes")
def set_attributes(
    asset_id: str, payload: AttributeValues, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    """Fill or change attribute values (``null`` clears one); each change goes to the history."""

    _require_asset(rt, asset_id)
    if len(payload.values) > MAX_VALUES:
        raise HTTPException(status_code=422, detail=t("Too many values in one request."))
    store = _store(rt)
    try:
        changes = store.set_attributes(asset_id, payload.values, actor=user)
    except AssetTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rt.platform.record_attribute_changes(asset_id, user, changes)
    return {
        "attributes": store.attributes(asset_id),
        "changes": changes,
        "missing": store.missing(asset_id),
    }


def relations_view(rt: Any, asset_id: str, scope: Any = None) -> dict[str, list[dict[str, Any]]]:
    """The asset's relations both ways; with ``scope``, only to assets the person sees."""

    store = _store(rt)
    names = {item["asset_id"]: item for item in store.list()}

    def other(item_id: str) -> dict[str, Any]:
        found = names.get(item_id) or {}
        return {
            "asset_id": item_id,
            "name": found.get("name", item_id),
            "kind": found.get("kind", ""),
            "kind_label": found.get("kind_label", ""),
        }

    outgoing, incoming = [], []
    for item in store.relations(asset_id):
        if scope is not None and not (scope.asset(item["from_id"]) and scope.asset(item["to_id"])):
            continue
        label, inverse = RELATION_TYPES.get(item["relation"], (item["relation"], item["relation"]))
        row = {
            "type": item["relation"],
            "origin": item["origin"],
            "created_at": item["created_at"],
            "created_by": item["created_by"],
        }
        if item["from_id"] == asset_id:
            outgoing.append({**row, "label": t(label), "asset": other(item["to_id"])})
        if item["to_id"] == asset_id:
            incoming.append({**row, "label": t(inverse), "asset": other(item["from_id"])})
    return {"outgoing": outgoing, "incoming": incoming}


@router.post("/api/assets/{asset_id}/relations", status_code=201)
def add_relation(
    asset_id: str, payload: RelationPayload, user: CurrentUser, rt: Runtime
) -> dict[str, Any]:
    _require_asset(rt, asset_id)
    target = _store(rt).get(payload.to)
    if target is None or not rt.asset_scope(user).asset(payload.to):
        raise HTTPException(status_code=404, detail=t("Asset not found."))
    try:
        added = _store(rt).relate(asset_id, payload.type, payload.to, actor=user)
    except AssetTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if added:
        label = RELATION_TYPES[payload.type][0]
        _history(
            rt,
            "asset.relation_added",
            asset_id,
            user,
            t("{relation} {asset}", relation=t(label), asset=target["name"]),
            {"type": payload.type, "to": payload.to},
            [f"asset:{payload.to}"],
        )
    return relations_view(rt, asset_id)


@router.delete("/api/assets/{asset_id}/relations", status_code=204)
def remove_relation(
    asset_id: str,
    user: CurrentUser,
    rt: Runtime,
    type: Annotated[str, Query(min_length=1, max_length=30)],
    to: Annotated[str, Query(min_length=1, max_length=200)],
) -> None:
    _require_asset(rt, asset_id)
    if _store(rt).unrelate(asset_id, type, to):
        label = RELATION_TYPES.get(type, (type, type))[0]
        _history(
            rt,
            "asset.relation_removed",
            asset_id,
            user,
            t("No longer {relation} {asset}", relation=t(label).lower(), asset=to),
            {"type": type, "to": to},
            [f"asset:{to}"],
        )


def _signal_tag(rt: Any, given: str) -> tuple[str, str]:
    """``(source id, tag)`` of a signal id or tag; a tag no source lists yet stays as typed."""

    catalog = rt.platform.signal_catalog()
    found = catalog.find(given)
    if found is not None:
        return catalog.signals[found]["source"], catalog.tags[found]
    source_id, tag = split_signal_id(given)
    if source_id is not None and rt.platform.sources.known(source_id):
        return source_id, tag
    return rt.platform.sources.source_of(given), given


@router.post("/api/assets/{asset_id}/signals", status_code=201)
def bind_signal(
    asset_id: str, payload: SignalRolePayload, user: CurrentUser, rt: Runtime
) -> list[dict[str, Any]]:
    """Fill a signal role of the asset (or place a signal on it without a role)."""

    asset = _require_asset(rt, asset_id)
    store = _store(rt)
    resolved = store.types.resolved(asset["kind"]) or {"roles": []}
    roles = {entry["key"]: entry for entry in resolved["roles"]}
    role = payload.role.strip()
    if role and role not in roles:
        raise HTTPException(
            status_code=422,
            detail=t(
                "Not a signal role of {type}: use {roles}.",
                type=resolved.get("name") or asset["kind"],
                roles=", ".join(roles) or "—",
            ),
        )
    given = payload.signal_id.strip()
    if not given:
        raise HTTPException(status_code=422, detail=t("Enter the signal."))
    if not rt.asset_scope(user).signal(given):
        # Binding a tag would bring it into the person's scope: only signals they already see.
        raise HTTPException(status_code=404, detail=t("Signal not found."))
    # The API v1 id (scenario:FIC-101.PV) or a tag; the binding keeps the tag and its source.
    try:
        source_id, signal_id = _signal_tag(rt, given)
    except AmbiguousSignal as exc:
        raise HTTPException(status_code=422, detail=exc.detail()) from exc
    if role:
        # One signal per role and origin: binding again replaces the previous one.
        replaced = [
            (asset_id, item["signal_id"])
            for item in store.bindings(origin="manual")
            if item["asset_id"] == asset_id and item["role"] == role
        ]
        store.unbind_signals(replaced)
    store.bind_signals(
        asset_id,
        [
            {
                "signal_id": signal_id,
                "role": role,
                "name": roles.get(role, {}).get("name", ""),
                "source_id": source_id,
            }
        ],
    )
    _history(
        rt,
        "asset.signal_bound",
        asset_id,
        user,
        t(
            "Signal {signal} bound as {role}",
            signal=signal_id,
            role=roles.get(role, {}).get("name") or "—",
        ),
        {"signal_id": signal_id, "role": role},
        [f"signal:{source_id}:{signal_id}"],
    )
    return store.signals(asset_id)


@router.delete("/api/assets/{asset_id}/signals", status_code=204)
def unbind_signal(
    asset_id: str,
    user: CurrentUser,
    rt: Runtime,
    signal_id: Annotated[str, Query(min_length=1, max_length=300)],
) -> None:
    """Remove a signal placed by hand (signals from the scenario or a map stay there)."""

    _require_asset(rt, asset_id)
    store = _store(rt)
    manual = [item for item in store.bindings(origin="manual") if item["asset_id"] == asset_id]
    if not any(item["signal_id"] == signal_id for item in manual):
        # The API v1 id of a bound tag (scenario:FIC-101.PV) names that binding too.
        signal_id = next(
            (
                item["signal_id"]
                for item in manual
                if item["source_id"] and signal_id == f"{item['source_id']}:{item['signal_id']}"
            ),
            signal_id,
        )
    if not any(item["signal_id"] == signal_id for item in manual):
        raise HTTPException(
            status_code=422,
            detail=t(
                "Only signals bound by hand can be removed here; the others come from a file."
            ),
        )
    store.unbind_signals([(asset_id, signal_id)])
    _history(
        rt,
        "asset.signal_unbound",
        asset_id,
        user,
        t("Signal {signal} removed", signal=signal_id),
        {"signal_id": signal_id},
        [],
    )
