"""Plant map sheets built from the asset types: one sheet per type, and the relations.

A type's sheet (``pump``, ``control_valve``, ``instrument``...) has the asset's
own columns (``asset_id``, ``name``, ``parent_id``, ``description``), one column
per attribute of the type (inherited ones included) and one per signal role,
holding the tag of the signal that fills it. Control loops keep their
``loops`` sheet (``loops.py``), which gets the loop type's attribute columns;
the plant itself is the root of every map and has no sheet.

The ``relations`` sheet links assets outside the tree: ``FIC-2001 controls
FV-2001``.
"""

from __future__ import annotations

from typing import Any

from plantcraft.i18n import t
from plantcraft.platform.plantmap import (
    Change,
    Column,
    MapContext,
    _tree_order,
    changed_values,
    record_values,
    text,
    write_record,
)
from plantcraft_sdk.assets import LOOP_TYPE, RELATION_TYPES

MAP_ORIGIN = "map"
# The template's rows; any other type starts with an empty sheet.
EXAMPLES: dict[str, list[dict[str, Any]]] = {
    "unit": [{"asset_id": "U-200", "name": "Unit 200 · Utilities", "unit_code": "U-200"}],
    "pump": [
        {
            "asset_id": "B-201A",
            "name": "Cooling water pump A",
            "parent_id": "U-200",
            "description": "Centrifugal pump, 120 m³/h",
            "criticality": "high",
            "pump_type": "centrifugal",
            "rated_flow": 120,
            "power": 75,
            "flow": "UT.B201A.Flow",
        }
    ],
    "control_valve": [
        {
            "asset_id": "FV-2001",
            "name": "Cooling water flow valve",
            "parent_id": "U-200",
            "characteristic": "equal percentage",
            "actuator": "pneumatic",
            "cv": 45,
        }
    ],
    "instrument": [
        {
            "asset_id": "FT-2001",
            "name": "Cooling water flow transmitter",
            "parent_id": "B-201A",
            "measured_variable": "flow",
            "range_min": 0,
            "range_max": 200,
            "range_unit": "m³/h",
        }
    ],
}


def attribute_columns(resolved: dict[str, Any]) -> list[Column]:
    columns = []
    for entry in resolved["attributes"]:
        kind = {
            "text": t("text"),
            "number": t("number"),
            "choice": t("one of: {options}", options=" | ".join(entry["options"])),
            "date": t("date, YYYY-MM-DD"),
            "asset": t("id of another asset"),
        }.get(entry["data_type"], entry["data_type"])
        unit = f", {entry['unit']}" if entry["unit"] else ""
        columns.append(Column(entry["key"], f"{entry['name']} ({kind}{unit}).", entry["required"]))
    return columns


def role_columns(resolved: dict[str, Any], skip: set[str] | tuple[str, ...] = ()) -> list[Column]:
    return [
        Column(
            entry["key"],
            t("Tag of the signal for the role {role}.", role=entry["name"])
            + (f" ({entry['unit']})" if entry["unit"] else ""),
            entry["required"],
        )
        for entry in resolved["roles"]
        if entry["key"] not in skip
    ]


def role_signals(platform: Any, resolved: dict[str, Any], tags: dict[str, str]) -> list[dict]:
    """Bindings for the roles a row fills, named after the role, with the source's unit."""

    try:
        units = {item["tag"]: item.get("unit") or "" for item in platform.data.signals()}
    except Exception:  # an offline source: units come back with the next import
        units = {}
    return [
        {
            "signal_id": tags[entry["key"]],
            "role": entry["key"],
            "name": entry["name"],
            "unit": units.get(tags[entry["key"]]) or entry["unit"],
        }
        for entry in resolved["roles"]
        if tags.get(entry["key"])
    ]


class TypeSection:
    """The sheet of one asset type: one row per asset, a column per attribute and per role."""

    BASE = (
        ("asset_id", "Asset id, the tag as written in the plant (FV-2001, B-201A).", True),
        ("name", "Name shown in the asset tree.", True),
        ("parent_id", "Parent asset. Empty: right under the plant.", False),
        ("description", "Free description.", False),
    )

    def __init__(self, platform: Any, type_id: str):
        self.platform = platform
        self.name = type_id

    @property
    def resolved(self) -> dict[str, Any]:
        return self.platform.workspace.assets.types.resolved(self.name) or {
            "name": self.name,
            "attributes": [],
            "roles": [],
        }

    @property
    def label(self) -> str:
        return self.resolved["name"]

    @property
    def columns(self) -> list[Column]:
        resolved = self.resolved
        return [
            *(Column(name, t(description), required) for name, description, required in self.BASE),
            *attribute_columns(resolved),
            *role_columns(resolved),
        ]

    @property
    def example(self) -> list[dict[str, Any]]:
        return [dict(row) for row in EXAMPLES.get(self.name, [])]

    def plan(self, rows: list[dict[str, Any]], ctx: MapContext) -> list[Change]:
        platform = ctx.platform
        store = platform.workspace.assets
        resolved = self.resolved
        attribute_keys = {entry["key"] for entry in resolved["attributes"]}
        role_keys = [entry["key"] for entry in resolved["roles"]]
        own = {name for name, _description, _required in self.BASE} | {"_line"}
        bound_by_map: dict[str, dict[str, str]] = {}
        for item in store.bindings(origin=MAP_ORIGIN):
            bound_by_map.setdefault(item["asset_id"], {})[item["role"]] = item["signal_id"]
        changes: list[Change] = []
        ignored: set[str] = set()
        for row in rows:
            asset_id, name = text(row, "asset_id"), text(row, "name")
            if not asset_id or not name:
                ctx.error(self.name, row, t("Enter asset_id and name."))
                continue
            if any(char.isspace() for char in asset_id):
                ctx.error(
                    self.name, row, t("The asset_id '{asset}' cannot have spaces.", asset=asset_id)
                )
                continue
            if asset_id == ctx.root:
                ctx.error(
                    self.name,
                    row,
                    t(
                        "{asset} is the plant, the root of the tree; it has no sheet.",
                        asset=asset_id,
                    ),
                )
                continue
            if not ctx.claim(self.name, row, asset_id):
                continue
            given = {key: value for key, value in row.items() if key in attribute_keys}
            ignored.update(
                key
                for key in row
                if key not in own and key not in attribute_keys and key not in role_keys
            )
            values, _unknown, problems = record_values(store, self.name, given, ctx)
            if problems:
                for problem in problems:
                    ctx.error(self.name, row, problem)
                continue
            tags = {key: text(row, key) for key in role_keys if text(row, key)}
            for tag in tags.values():
                ctx.check_tag(self.name, row, tag)
            parent = text(row, "parent_id") or ctx.root
            if parent != ctx.root and not ctx.asset_known(parent):
                ctx.warn(
                    self.name,
                    row,
                    t(
                        "Parent asset {parent} does not exist; {asset} goes under the site.",
                        parent=parent,
                        asset=asset_id,
                    ),
                )
                parent = ctx.root
            if parent == asset_id:
                ctx.error(self.name, row, t("An asset cannot be its own parent."))
                continue
            current = store.get(asset_id)
            record = changed_values(store, asset_id, values)
            wanted = {
                "name": name,
                "kind": self.name,
                "parent_id": parent,
                "description": text(row, "description"),
            }
            same_asset = current is not None and all(
                current.get(key) == value for key, value in wanted.items()
            )
            same_roles = bound_by_map.get(asset_id, {}) == tags
            if current is not None and current["origin"] not in {"manual", MAP_ORIGIN}:
                # The scenario file owns this asset; the map only fills its record.
                if not (same_asset and same_roles):
                    ctx.warn(
                        self.name,
                        row,
                        t(
                            "{asset} comes from the scenario file: only its attributes are taken "
                            "from the map.",
                            asset=asset_id,
                        ),
                    )
                if record:
                    changes.append(
                        Change(
                            "update",
                            asset_id,
                            lambda asset_id=asset_id, record=record: write_record(
                                ctx, asset_id, record
                            ),
                        )
                    )
                else:
                    changes.append(Change("unchanged", asset_id))
                continue
            if same_asset and same_roles and not record:
                changes.append(Change("unchanged", asset_id))
                continue

            def run(
                asset_id: str = asset_id,
                wanted: dict = wanted,
                current: dict | None = current,
                record: dict = record,
                tags: dict = tags,
            ) -> None:
                store.save(
                    asset_id, origin="manual", position=(current or {}).get("position", 0), **wanted
                )
                write_record(ctx, asset_id, record)
                store.set_signals(
                    asset_id, role_signals(platform, resolved, tags), origin=MAP_ORIGIN
                )
                from plantcraft.platform.loops import _follow

                _follow(platform, list(tags.values()))

            changes.append(Change("update" if current else "create", asset_id, run))
        if ignored:
            ctx.warn(
                self.name,
                None,
                t(
                    "Columns that are not attributes or signal roles of {type}, ignored: {columns}.",
                    type=resolved["name"],
                    columns=", ".join(sorted(str(item)[:40] for item in ignored)[:30]),
                ),
            )
        return changes

    def stale(self, rows: list[dict[str, Any]], ctx: MapContext) -> list[Change]:
        listed = ctx.listed_assets()
        store = ctx.platform.workspace.assets
        return [
            Change(
                "remove", item["asset_id"], lambda asset_id=item["asset_id"]: store.delete(asset_id)
            )
            for item in store.list()
            if item["kind"] == self.name
            and item["origin"] in {"manual", MAP_ORIGIN}
            and item["asset_id"] != ctx.root
            and item["asset_id"] not in listed
        ]

    def export(self, ctx: MapContext) -> list[dict[str, Any]]:
        store = ctx.platform.workspace.assets
        resolved = self.resolved
        items = [
            item
            for item in _tree_order(store.list(), ctx.root)
            if item["kind"] == self.name and item["asset_id"] != ctx.root
        ]
        stored = store.stored_attributes([item["asset_id"] for item in items])
        bound: dict[str, dict[str, str]] = {}
        for binding in store.bindings(origin=MAP_ORIGIN):
            bound.setdefault(binding["asset_id"], {})[binding["role"]] = binding["signal_id"]
        rows = []
        for item in items:
            values = stored.get(item["asset_id"], {})
            row = {
                "asset_id": item["asset_id"],
                "name": item["name"],
                "parent_id": "" if item["parent_id"] == ctx.root else item["parent_id"] or "",
                "description": item["description"],
            }
            row.update(
                {entry["key"]: values.get(entry["key"], "") for entry in resolved["attributes"]}
            )
            row.update(
                {
                    entry["key"]: bound.get(item["asset_id"], {}).get(entry["key"], "")
                    for entry in resolved["roles"]
                }
            )
            rows.append({key: "" if value is None else value for key, value in row.items()})
        return rows


def type_sections(platform: Any) -> list[TypeSection]:
    """A sheet for every type but the plant (the root) and control loops (the loops sheet),
    ordered from the top of the tree down."""

    store = platform.workspace.assets
    definitions = store.types.definitions()
    ids = [type_id for type_id in definitions if type_id not in {"site", LOOP_TYPE}]
    ids.sort(key=lambda type_id: (store.depth(type_id), len(store.types.path(type_id))))
    return [TypeSection(platform, type_id) for type_id in ids]


class RelationsSection:
    """Typed links between assets, outside the tree."""

    name = "relations"
    COLUMNS = (
        ("from_id", "The asset the relation starts from (FIC-2001).", True),
        ("type", "controls, measures, feeds or downstream_of.", True),
        ("to_id", "The asset it points at (FV-2001).", True),
    )
    example = [
        {"from_id": "FIC-2001", "type": "controls", "to_id": "FV-2001"},
        {"from_id": "FT-2001", "type": "measures", "to_id": "B-201A"},
    ]

    @property
    def label(self) -> str:
        return t("Relations")

    @property
    def columns(self) -> list[Column]:
        return [
            Column(name, t(description), required) for name, description, required in self.COLUMNS
        ]

    def plan(self, rows: list[dict[str, Any]], ctx: MapContext) -> list[Change]:
        store = ctx.platform.workspace.assets
        current = {(item["from_id"], item["relation"], item["to_id"]) for item in store.relations()}
        seen: set[tuple[str, str, str]] = set()
        changes: list[Change] = []
        for row in rows:
            from_id, kind, to_id = (
                text(row, "from_id"),
                text(row, "type").lower(),
                text(row, "to_id"),
            )
            kind = kind.replace(" ", "_")
            if not from_id or not kind or not to_id:
                ctx.error(self.name, row, t("Fill in from_id, type and to_id."))
                continue
            if kind not in RELATION_TYPES:
                ctx.error(
                    self.name,
                    row,
                    t(
                        "Invalid relation type: '{type}'. Use {types}.",
                        type=kind[:40],
                        types=", ".join(RELATION_TYPES),
                    ),
                )
                continue
            if from_id == to_id:
                ctx.error(self.name, row, t("An asset cannot be related to itself."))
                continue
            missing = [item for item in (from_id, to_id) if not ctx.asset_known(item, loops=True)]
            if missing:
                ctx.error(
                    self.name,
                    row,
                    t(
                        "Asset {asset} does not exist and is not in the file.",
                        asset=missing[0][:120],
                    ),
                )
                continue
            key = (from_id, kind, to_id)
            if key in seen:
                ctx.error(self.name, row, t("This relation appears more than once."))
                continue
            seen.add(key)
            label = f"{from_id} {kind} {to_id}"
            if key in current:
                changes.append(Change("unchanged", label))
                continue

            def run(key: tuple[str, str, str] = key) -> None:
                if store.get(key[0]) is None or store.get(key[2]) is None:
                    return  # its asset was not imported (a loop from the scenario file, say)
                store.relate(*key, actor=ctx.actor, origin=MAP_ORIGIN)
                ctx.platform.record_asset_change(
                    "asset.relation_added",
                    key[0],
                    ctx.actor,
                    t(
                        "{relation} {asset}",
                        relation=t(RELATION_TYPES[key[1]][0]),
                        asset=key[2],
                    ),
                    {"type": key[1], "to": key[2]},
                    [f"asset:{key[2]}"],
                )

            changes.append(Change("create", label, run))
        return changes

    def stale(self, rows: list[dict[str, Any]], ctx: MapContext) -> list[Change]:
        listed = {
            (text(row, "from_id"), text(row, "type").lower().replace(" ", "_"), text(row, "to_id"))
            for row in rows
        }
        store = ctx.platform.workspace.assets
        return [
            Change(
                "remove",
                f"{item['from_id']} {item['relation']} {item['to_id']}",
                lambda item=item: store.unrelate(item["from_id"], item["relation"], item["to_id"]),
            )
            for item in store.relations()
            if (item["from_id"], item["relation"], item["to_id"]) not in listed
        ]

    def export(self, ctx: MapContext) -> list[dict[str, Any]]:
        return [
            {"from_id": item["from_id"], "type": item["relation"], "to_id": item["to_id"]}
            for item in ctx.platform.workspace.assets.relations()
        ]
