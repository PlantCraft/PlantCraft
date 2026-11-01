"""Control loops as assets: a ``loop`` asset with its signals bound by role (pv, sp, op...).

PlantCraft does not analyse loops; it describes them, so the apps of the suite find
them through API v1 (``GET /api/v1/assets``: kind ``loop``, ``signals`` by role).
Analytics reads every loop asset with a ``pv`` signal as a loop to monitor.

Two places describe loops:

- the scenario file (``loops``), placed under their unit and
  area by ``sync_scenario_loops`` (origin ``scenario``);
- the ``loops`` sheet of the plant map (``LoopsSection``, origin ``map``).

The loop's record (loop type, criticality, action, controller and any attribute the admin
adds to the Control loop type) is stored on the asset and read by the apps through API v1.
A scenario loop's ``metadata`` fills the record keys it gives (``RECORD_KEYS``) where the
record has no value yet; the demo scenario gives the Simulator's loops their ``loop_type``.
Analysis settings (protocol, whether a loop takes part in rounds) belong to the app that
analyses loops; the map accepts those columns and says where to set them.
"""

from __future__ import annotations

from typing import Any

from plantcraft.assets import asset_id_for
from plantcraft.assets.types import AssetTypeError
from plantcraft.i18n import t
from plantcraft.industrial_data.registry import PRIMARY
from plantcraft.platform.plantmap import (
    Change,
    Column,
    MapContext,
    changed_values,
    record_values,
    text,
    write_record,
)

ROLES = ("pv", "sp", "op", "mode", "secondary")
ROLE_NAMES = {"pv": "PV", "sp": "SP", "op": "OP", "mode": "Mode", "secondary": "Secondary"}
SCENARIO_ORIGIN = "scenario"
# The origin the monolith's CPM module gave the scenario's loops.
LEGACY_ORIGIN = "cpm"
MAP_ORIGIN = "map"
# Columns of the former loops sheet whose settings now live in Analytics
# (loop_type and criticality are attributes of the loop's record now).
APP_COLUMNS = ("protocol", "function_type", "enabled")
LOOP_TYPE = "loop"
# Keys of a scenario loop's ``metadata`` that fill the loop's record (attributes of the
# Control loop type), when the record has no value for them yet.
RECORD_KEYS = ("loop_type", "criticality", "action", "controller")


def _area_assets(
    root: str, unit: str, area: str, *, unit_is_asset: bool = False
) -> tuple[str, list[dict[str, Any]]]:
    """The unit and area a loop hangs from (created when missing), and the area's id.

    ``unit_is_asset``: ``unit`` is the id of an asset already there or listed in the same map
    (a unit the assets sheet names), which the area then hangs from instead of a new unit.
    """

    created: list[dict[str, Any]] = []
    parent = root
    if unit and unit_is_asset:
        parent = unit
    elif unit:
        parent = asset_id_for(unit)
        created.append({"asset_id": parent, "name": unit, "kind": "unit", "parent_id": root})
    area_name = area or "No area"
    area_id = asset_id_for(f"{unit} {area_name}" if unit else area_name)
    created.append({"asset_id": area_id, "name": area_name, "kind": "area", "parent_id": parent})
    return area_id, created


def _signals(platform: Any, roles: dict[str, str | None]) -> list[dict[str, Any]]:
    """The loop's signals by role, with the unit the source reports (``%`` for an OP)."""

    mapping = platform.scenario.source.mapping
    tag_of = {column: tag for tag, column in mapping.items()}
    try:
        units_of = {item["tag"]: item.get("unit") or "" for item in platform.data.signals()}
    except Exception:  # the source may be offline; units come back on the next sync
        units_of = {}
    names = {
        entry["key"]: entry["name"]
        for entry in (platform.workspace.assets.types.resolved(LOOP_TYPE) or {}).get("roles", [])
    }
    signals = []
    for role in [*ROLES, *(key for key in roles if key not in ROLES)]:
        column = roles.get(role)
        if not (isinstance(column, str) and column):
            continue
        tag = tag_of.get(column, column)
        signals.append(
            {
                "signal_id": tag,
                "role": role,
                "name": ROLE_NAMES.get(role) or names.get(role, role),
                "unit": units_of.get(tag) or ("%" if role == "op" else ""),
            }
        )
    return signals


def sync_scenario_loops(platform: Any) -> int:
    """Unit, area and loop under the installation for every loop of the scenario file."""

    root = platform.root_asset_id
    tree = platform.workspace.assets
    assets: dict[str, dict[str, Any]] = {}
    for loop in platform.scenario.loops:
        # A loop placed on an asset hangs there; else under its unit and area.
        placed = str((loop.metadata or {}).get("asset_id") or "")
        if placed and placed != loop.loop_id and tree.get(placed) is not None:
            area_id = placed
        else:
            area_id, created = _area_assets(root, loop.unit, loop.area)
            for item in created:
                assets.setdefault(item["asset_id"], item)
        assets[loop.loop_id] = {
            "asset_id": loop.loop_id,
            "name": loop.name,
            "kind": "loop",
            "parent_id": area_id,
            "description": loop.service,
            "signals": _signals(platform, loop.signals.model_dump()),
        }
    # Databases from before the split: the scenario's loops were synced by the CPM module.
    tree.adopt(LEGACY_ORIGIN, SCENARIO_ORIGIN)
    synced = tree.sync(SCENARIO_ORIGIN, list(assets.values()))
    _fill_records(platform, platform.scenario.loops)
    return synced


def _fill_records(platform: Any, loops: list[Any]) -> None:
    """The record values a scenario loop gives (``metadata``: loop type, criticality...).

    Only keys the record has no value for: a value someone set on the asset's page or through
    the plant map is theirs and stays. A value the Control loop type does not accept (an
    unknown loop type, a key the admin removed) is skipped; the loop is still placed.
    """

    tree = platform.workspace.assets
    resolved = tree.types.resolved(LOOP_TYPE) or {"attributes": []}
    accepted = {entry["key"] for entry in resolved["attributes"]} & set(RECORD_KEYS)
    stored = tree.stored_attributes([loop.loop_id for loop in loops])
    for loop in loops:
        metadata = loop.metadata if isinstance(loop.metadata, dict) else {}
        current = stored.get(loop.loop_id, {})
        for key in sorted(accepted):
            value = metadata.get(key)
            if value is None or current.get(key) is not None:
                continue
            try:
                changes = tree.set_attributes(
                    loop.loop_id, {key: value}, actor=SCENARIO_ORIGIN, check_refs=False
                )
            except (AssetTypeError, KeyError):
                continue
            platform.record_attribute_changes(loop.loop_id, SCENARIO_ORIGIN, changes)


class LoopsSection:
    """The ``loops`` sheet of the plant map: one row per loop asset, its signals by role."""

    name = "loops"

    def __init__(self, platform: Any = None):
        self.platform = platform

    def _loop_type(self) -> dict[str, Any]:
        """The Control loop type, resolved (its attributes and roles)."""

        resolved = None
        if self.platform is not None:
            resolved = self.platform.workspace.assets.types.resolved(LOOP_TYPE)
        return resolved or {"attributes": [], "roles": []}

    # English texts, translated each time the section is read (a request's language).
    COLUMNS = (
        ("loop_id", "Loop tag (FIC-2001). It is also the id of the loop's asset.", True),
        ("name", "Loop name.", True),
        (
            "asset_id",
            "Asset the loop hangs from in the tree (equipment, area). Empty: unit and area below.",
            False,
        ),
        ("area", "Area the loop belongs to (created when missing).", False),
        ("unit", "Process unit.", False),
        ("service", "Service or short description of the loop.", False),
        ("pv", "Process variable tag.", True),
        ("sp", "Setpoint tag.", False),
        ("op", "Controller output tag (%).", False),
        ("mode", "Mode tag (AUTO, MAN, CAS).", False),
        ("secondary", "Tag of a secondary variable (secondary or neighbouring loop).", False),
    )

    @property
    def label(self) -> str:
        return t("Loops")

    @property
    def columns(self) -> list[Column]:
        from plantcraft.platform.typesheets import attribute_columns, role_columns

        resolved = self._loop_type()
        return [
            *(
                Column(name, t(description), required)
                for name, description, required in self.COLUMNS
            ),
            *attribute_columns(resolved),
            *role_columns(resolved, skip=ROLES),
        ]

    @property
    def example(self) -> list[dict[str, Any]]:
        return [
            {
                "loop_id": "FIC-2001",
                "name": t("Cooling water flow"),
                "asset_id": "B-201A",
                "area": t("Cooling"),
                "unit": "U-200",
                "service": t("Discharge flow of pump B-201A"),
                "pv": "UT.FIC2001.PV",
                "sp": "UT.FIC2001.SP",
                "op": "UT.FIC2001.OP",
                "mode": "UT.FIC2001.MODE",
                "secondary": "",
                "loop_type": "flow",
                "criticality": "high",
                "action": "reverse",
                "controller": "DCS",
            }
        ]

    def plan(self, rows: list[dict[str, Any]], ctx: MapContext) -> list[Change]:
        platform = ctx.platform
        store = platform.workspace.assets
        changes: list[Change] = []
        seen: set[str] = set()
        ignored: set[str] = set()
        resolved = self._loop_type()
        attribute_keys = {entry["key"] for entry in resolved["attributes"]}
        role_keys = [
            *ROLES,
            *(entry["key"] for entry in resolved["roles"] if entry["key"] not in ROLES),
        ]
        for row in rows:
            loop_id, name, pv = text(row, "loop_id"), text(row, "name"), text(row, "pv")
            ignored.update(column for column in APP_COLUMNS if text(row, column))
            if not loop_id or not name or not pv:
                ctx.error(self.name, row, t("Fill in loop_id, name and pv."))
                continue
            if any(char.isspace() for char in loop_id):
                ctx.error(
                    self.name, row, t("The asset_id '{asset}' cannot have spaces.", asset=loop_id)
                )
                continue
            if loop_id in seen:
                ctx.error(
                    self.name, row, t("Loop {loop_id} appears more than once.", loop_id=loop_id)
                )
                continue
            seen.add(loop_id)
            if not ctx.claim(self.name, row, loop_id):
                continue
            values, _unknown, problems = record_values(
                store,
                LOOP_TYPE,
                {key: value for key, value in row.items() if key in attribute_keys},
                ctx,
            )
            if problems:
                for problem in problems:
                    ctx.error(self.name, row, problem)
                continue
            record = changed_values(store, loop_id, values)
            asset_id = text(row, "asset_id")
            if asset_id and not ctx.asset_known(asset_id):
                ctx.warn(
                    self.name,
                    row,
                    t(
                        "Asset {asset_id} does not exist; the loop stays under the unit and area.",
                        asset_id=asset_id,
                    ),
                )
                asset_id = ""
            roles = {role: text(row, role) or None for role in role_keys}
            for tag in roles.values():
                if tag:
                    ctx.check_tag(self.name, row, tag)
            current = store.get(loop_id)
            if current is not None and current["origin"] not in {MAP_ORIGIN, "manual"}:
                # The scenario file owns the loop; the map fills its record only.
                if record:
                    changes.append(
                        Change(
                            "update",
                            loop_id,
                            lambda loop_id=loop_id, record=record: write_record(
                                ctx, loop_id, record
                            ),
                        )
                    )
                else:
                    changes.append(Change("unchanged", loop_id))
                ctx.warn(
                    self.name,
                    row,
                    t(
                        "Loop {loop_id} comes from the scenario file: change its name and signals "
                        "there; only its attributes are taken from the map.",
                        loop_id=loop_id,
                    ),
                )
                continue
            if asset_id:
                parent, parents = asset_id, []
            else:
                unit = text(row, "unit")
                parent, parents = _area_assets(
                    ctx.root,
                    unit,
                    text(row, "area"),
                    unit_is_asset=bool(unit) and ctx.asset_known(unit),
                )
            wanted = {
                "name": name,
                "kind": "loop",
                "parent_id": parent,
                "description": text(row, "service"),
            }
            bindings = [item for item in store.signals(loop_id) if item.get("role") in role_keys]
            bound = {item["role"]: item["signal_id"] for item in bindings}
            # With Historian, a binding must also name the source its tag is read from.
            sourced = not getattr(
                getattr(platform, "datalayer", None), "manages_sources", False
            ) or all(
                item.get("source_id") == ctx.tag_source(item["signal_id"]) for item in bindings
            )
            if (
                current is not None
                and all(current.get(key) == value for key, value in wanted.items())
                and bound == {role: tag for role, tag in roles.items() if tag}
                and sourced
                and not record
            ):
                changes.append(Change("unchanged", loop_id))
                continue

            # A loop someone made by hand stays theirs; the map only updates it.
            origin = (
                "manual" if current is not None and current["origin"] == "manual" else MAP_ORIGIN
            )

            def run(
                loop_id: str = loop_id,
                wanted: dict = wanted,
                parents: list = parents,
                roles: dict = roles,
                origin: str = origin,
                record: dict = record,
            ) -> None:
                for item in parents:
                    if store.get(item["asset_id"]) is None:
                        store.save(item["asset_id"], origin=MAP_ORIGIN, **_fields(item))
                store.save(loop_id, origin=origin, **wanted)
                write_record(ctx, loop_id, record)
                signals = _signals(platform, roles)
                if getattr(getattr(platform, "datalayer", None), "manages_sources", False):
                    # With Historian, a binding keeps the source its tag is read from.
                    for item in signals:
                        item["source_id"] = ctx.tag_source(item["signal_id"])
                store.set_signals(loop_id, signals, origin=MAP_ORIGIN)
                _follow(platform, [tag for tag in roles.values() if tag])

            changes.append(Change("update" if current else "create", loop_id, run))
        if ignored:
            ctx.warn(
                self.name,
                None,
                t(
                    "Loop settings are kept by the app that analyses loops (PlantCraft Analytics) and were "
                    "ignored here: {columns}. Set them in that app.",
                    columns=", ".join(sorted(ignored)),
                ),
            )
        return changes

    def stale(self, rows: list[dict[str, Any]], ctx: MapContext) -> list[Change]:
        listed = {text(row, "loop_id") for row in rows}
        store = ctx.platform.workspace.assets
        return [
            Change(
                "remove", item["asset_id"], lambda asset_id=item["asset_id"]: store.delete(asset_id)
            )
            for item in store.list()
            if item["kind"] == "loop"
            and item["origin"] == MAP_ORIGIN
            and item["asset_id"] not in listed
        ]

    def export(self, ctx: MapContext) -> list[dict[str, Any]]:
        store = ctx.platform.workspace.assets
        items = {item["asset_id"]: item for item in store.list()}
        resolved = self._loop_type()
        role_keys = [
            *ROLES,
            *(entry["key"] for entry in resolved["roles"] if entry["key"] not in ROLES),
        ]
        stored = store.stored_attributes()
        rows = []
        for item in items.values():
            if item["kind"] != "loop" or item["origin"] not in {MAP_ORIGIN, SCENARIO_ORIGIN}:
                continue
            roles = {
                signal["role"]: signal["signal_id"]
                for signal in store.signals(item["asset_id"])
                if signal.get("role") in role_keys
            }
            values = stored.get(item["asset_id"], {})
            parent = items.get(item["parent_id"] or "") or {}
            grandparent = items.get(parent.get("parent_id") or "") or {}
            under_area = parent.get("kind") == "area"
            rows.append(
                {
                    "loop_id": item["asset_id"],
                    "name": item["name"],
                    "asset_id": "" if under_area or not parent else parent["asset_id"],
                    "area": parent.get("name", "") if under_area else "",
                    "unit": grandparent.get("name", "")
                    if under_area and grandparent.get("kind") == "unit"
                    else "",
                    "service": item["description"],
                    **{role: roles.get(role, "") for role in role_keys},
                    **{
                        entry["key"]: ""
                        if values.get(entry["key"]) is None
                        else values[entry["key"]]
                        for entry in resolved["attributes"]
                    },
                }
            )
        return rows


def _fields(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item[key] for key in ("name", "kind", "parent_id") if key in item}


def _follow(platform: Any, tags: list[str]) -> None:
    """A primary-source tag outside the scenario's tag list is read by its own name."""

    sources = platform.sources
    configured = platform.scenario.source
    known = set(configured.tags) | set(configured.mapping.values())
    routes = sources.routes()
    loose = [
        {"tag": tag} for tag in tags if configured.tags and tag not in known and tag not in routes
    ]
    if loose:
        sources.use(PRIMARY, loose, monitored=None)
