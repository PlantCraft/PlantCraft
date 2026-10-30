"""Asset types: the catalog the admin edits (name, parent, attributes, signal roles, contents).

Platform code knows the concepts; the concrete types are data. A new database
starts with ``plantcraft_sdk.assets.STARTER_TYPES`` (once: a starter type the
admin removed does not come back), and the kinds people added before types
existed (``asset_kinds``) become types under ``equipment``. An asset's ``kind``
is its type id.

Inheritance is resolved when read, so a change to a parent reaches every
child type at once. ``check_value`` is the one place an attribute value is
checked against its data type.
"""

from __future__ import annotations

import math
import re
import time
from datetime import date, datetime
from typing import Any

from plantcraft.db import Store
from plantcraft.i18n import t
from plantcraft_sdk.assets import (
    CORE_TYPES,
    DATA_TYPES,
    resolve_type,
    starter_types,
    subtypes,
    type_path,
)

# How stale another server process's change to the types may be here, at most (seconds).
VERSION_CHECK_SECONDS = 1.0
TYPE_ID = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
ICON = re.compile(r"^[a-z0-9-]{0,40}$")
# Type ids that would clash with a sheet of the plant map.
RESERVED_TYPE_IDS = {
    "sources",
    "assets",
    "signals",
    "loops",
    "relations",
    "readme",
    "fontes",
    "ativos",
    "sinais",
    "malhas",
    "file",
    "format",
}
# Attribute keys that would clash with an asset's own fields in API v1.
RESERVED_KEYS = {
    "id",
    "asset_id",
    "name",
    "kind",
    "kind_label",
    "type",
    "type_path",
    "parent_id",
    "description",
    "origin",
    "signals",
    "relations",
    "attributes",
}
MAX_ATTRIBUTES = 100
MAX_ROLES = 50
MAX_OPTIONS = 200
MAX_TEXT = 2000


class AssetTypeError(ValueError):
    """A type definition or an attribute value outside the rules (the API answers 422)."""


class AssetTypeConflict(AssetTypeError):
    """A type with this id or name already exists (409)."""


def new_type_id(name: str) -> str:
    """``"Heat exchanger"`` -> ``"heat_exchanger"``."""

    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"type_{slug}".rstrip("_")
    return slug[:31].rstrip("_")


class AssetTypeStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS asset_types (
        type_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        icon TEXT NOT NULL DEFAULT '',
        parent_id TEXT,
        attributes_json TEXT NOT NULL DEFAULT '[]',
        roles_json TEXT NOT NULL DEFAULT '[]',
        children_json TEXT NOT NULL DEFAULT '[]',
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );

    -- One row: bumped on every change, so every server process knows when to read the types again.
    CREATE TABLE IF NOT EXISTS asset_type_version (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL
    );

    -- Types placed once (starter types and adopted kinds); a removed one is not placed again.
    CREATE TABLE IF NOT EXISTS asset_type_seeds (
        type_id TEXT PRIMARY KEY,
        seeded_at TEXT NOT NULL
    );
    """

    def __init__(self, db: Any):
        super().__init__(db)
        self._cache: dict[str, dict[str, Any]] | None = None
        # The version the cache was read at: another server process bumps it when it changes
        # a type (``asset_type_version``), and this one reads the types again.
        self._cache_version = -1
        self._checked_at = -float("inf")
        self.seed(starter_types())

    # Placing types once ------------------------------------------------------

    def seed(self, definitions: list[dict[str, Any]]) -> None:
        """Add the definitions never placed before (parents first)."""

        now = self._now()
        with self._lock, self._write() as connection:
            seeded = {row[0] for row in connection.execute("SELECT type_id FROM asset_type_seeds")}
            present = {row[0] for row in connection.execute("SELECT type_id FROM asset_types")}
            position = len(present)
            for item in definitions:
                if item["id"] in seeded:
                    continue
                if item["id"] not in present:
                    connection.execute(
                        """
                        INSERT INTO asset_types (type_id, name, description, icon, parent_id,
                            attributes_json, roles_json, children_json, position, created_at,
                            updated_at, updated_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'platform')
                        """,
                        (
                            item["id"],
                            item["name"],
                            item.get("description", ""),
                            item.get("icon", ""),
                            item.get("parent"),
                            self._json(item.get("attributes") or []),
                            self._json(item.get("roles") or []),
                            self._json(item.get("children") or []),
                            position,
                            now,
                            now,
                        ),
                    )
                    position += 1
                connection.execute(
                    "INSERT OR IGNORE INTO asset_type_seeds (type_id, seeded_at) VALUES (?, ?)",
                    (item["id"], now),
                )
        self._changed()

    def adopt_kinds(self, kinds: list[tuple[str, str]]) -> None:
        """Kinds people added before types existed become types under ``equipment``."""

        self.seed(
            [
                {"id": kind, "name": label, "parent": "equipment", "icon": "box"}
                for kind, label in kinds
            ]
        )

    def _version(self) -> int:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT version FROM asset_type_version").fetchone()
        return int(row[0]) if row else 0

    def _changed(self) -> None:
        """The types changed: drop this process's cache, and every other one's."""

        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO asset_type_version (id, version) VALUES (1, 1) "
                "ON CONFLICT(id) DO UPDATE SET version = version + 1"
            )
        self._cache = None

    # Reading -----------------------------------------------------------------

    def definitions(self) -> dict[str, dict[str, Any]]:
        """Every type as stored (own attributes and roles only), in list order."""

        # The version is asked at most once a second: a request reads the types many times.
        now = time.monotonic()
        if self._cache is None or now - self._checked_at >= VERSION_CHECK_SECONDS:
            version = self._version()
            self._checked_at = now
        else:
            version = self._cache_version
        if self._cache is None or version != self._cache_version:
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM asset_types ORDER BY position, type_id"
                ).fetchall()
            self._cache_version = version
            self._cache = {
                row["type_id"]: {
                    "id": row["type_id"],
                    "name": row["name"],
                    "description": row["description"],
                    "icon": row["icon"],
                    "parent": row["parent_id"],
                    "attributes": self._loads(row["attributes_json"], []),
                    "roles": self._loads(row["roles_json"], []),
                    "children": self._loads(row["children_json"], []),
                    "updated_at": row["updated_at"],
                    "updated_by": row["updated_by"],
                }
                for row in rows
            }
        return self._cache

    def exists(self, type_id: str) -> bool:
        return type_id in self.definitions()

    def name(self, type_id: str) -> str:
        item = self.definitions().get(type_id)
        return item["name"] if item else type_id

    def path(self, type_id: str) -> list[str]:
        return type_path(self.definitions(), type_id)

    def subtypes(self, type_id: str) -> set[str]:
        return subtypes(self.definitions(), type_id) if self.exists(type_id) else set()

    def resolved(self, type_id: str) -> dict[str, Any] | None:
        definitions = self.definitions()
        return resolve_type(definitions, type_id) if type_id in definitions else None

    def all_resolved(self) -> list[dict[str, Any]]:
        definitions = self.definitions()
        return [resolve_type(definitions, type_id) for type_id in definitions]

    def own(self, type_id: str) -> dict[str, Any] | None:
        item = self.definitions().get(type_id)
        return dict(item) if item else None

    # Writing -----------------------------------------------------------------

    def create(self, definition: dict[str, Any], *, actor: str) -> dict[str, Any]:
        type_id = str(definition.get("id") or "").strip() or new_type_id(
            str(definition.get("name") or "")
        )
        if type_id in self.definitions():
            raise AssetTypeConflict(t("An asset type with this id already exists."))
        if not TYPE_ID.match(type_id) or type_id in RESERVED_TYPE_IDS:
            raise AssetTypeError(
                t(
                    "Invalid type id '{id}': lowercase letters, digits and _, starting with a "
                    "letter, up to 31 characters.",
                    id=type_id[:40],
                )
            )
        clean = self._validate(type_id, definition, new=True)
        now = self._now()
        with self._lock, self._write() as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM asset_types"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO asset_types (type_id, name, description, icon, parent_id,
                    attributes_json, roles_json, children_json, position, created_at,
                    updated_at, updated_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    type_id,
                    clean["name"],
                    clean["description"],
                    clean["icon"],
                    clean["parent"],
                    self._json(clean["attributes"]),
                    self._json(clean["roles"]),
                    self._json(clean["children"]),
                    position,
                    now,
                    now,
                    actor,
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO asset_type_seeds (type_id, seeded_at) VALUES (?, ?)",
                (type_id, now),
            )
        self._changed()
        return self.resolved(type_id) or {}

    def update(self, type_id: str, definition: dict[str, Any], *, actor: str) -> dict[str, Any]:
        if type_id not in self.definitions():
            raise KeyError(type_id)
        clean = self._validate(type_id, definition, new=False)
        with self._lock, self._write() as connection:
            connection.execute(
                """
                UPDATE asset_types SET name = ?, description = ?, icon = ?, parent_id = ?,
                    attributes_json = ?, roles_json = ?, children_json = ?, updated_at = ?,
                    updated_by = ?
                WHERE type_id = ?
                """,
                (
                    clean["name"],
                    clean["description"],
                    clean["icon"],
                    clean["parent"],
                    self._json(clean["attributes"]),
                    self._json(clean["roles"]),
                    self._json(clean["children"]),
                    self._now(),
                    actor,
                    type_id,
                ),
            )
        self._changed()
        return self.resolved(type_id) or {}

    def delete(self, type_id: str, *, in_use: int) -> None:
        definitions = self.definitions()
        if type_id not in definitions:
            raise KeyError(type_id)
        if type_id in CORE_TYPES:
            raise AssetTypeError(t("The platform's types cannot be removed."))
        if in_use:
            raise AssetTypeError(
                t("There are still assets of this type; change their type before removing it.")
            )
        if any(item["parent"] == type_id for item in definitions.values()):
            raise AssetTypeError(
                t("Other types inherit from this one; change their parent before removing it.")
            )
        with self._lock, self._write() as connection:
            connection.execute("DELETE FROM asset_types WHERE type_id = ?", (type_id,))
            for item in definitions.values():
                if type_id in item["children"]:
                    connection.execute(
                        "UPDATE asset_types SET children_json = ? WHERE type_id = ?",
                        (
                            self._json([child for child in item["children"] if child != type_id]),
                            item["id"],
                        ),
                    )
        self._changed()

    # Rules -------------------------------------------------------------------

    def _validate(self, type_id: str, definition: dict[str, Any], *, new: bool) -> dict[str, Any]:
        definitions = self.definitions()
        name = _text(definition.get("name"), 60).strip()
        if not name:
            raise AssetTypeError(t("Give the type a name."))
        if any(
            other_id != type_id and other["name"].strip().lower() == name.lower()
            for other_id, other in definitions.items()
        ):
            raise AssetTypeConflict(t("An asset type with this name already exists."))
        icon = _text(definition.get("icon"), 40).strip()
        if not ICON.match(icon):
            raise AssetTypeError(t("Invalid icon name."))
        parent = definition.get("parent") or None
        if parent is not None:
            parent = str(parent)
            if type_id in CORE_TYPES:
                raise AssetTypeError(
                    t(
                        "The platform's own types (plant, unit, area, equipment, loop) have no parent."
                    )
                )
            if parent not in definitions:
                raise AssetTypeError(t("Unknown parent type: {type}.", type=parent[:60]))
            if parent == type_id or type_id in type_path(definitions, parent):
                raise AssetTypeError(
                    t("A type cannot inherit from itself or from its own subtypes.")
                )
        # Keys this type inherits, and keys its subtypes already define.
        inherited_attributes, inherited_roles = set(), set()
        for ancestor in type_path(definitions, parent) if parent else []:
            item = definitions.get(ancestor) or {}
            inherited_attributes |= {entry["key"] for entry in item.get("attributes") or []}
            inherited_roles |= {entry["key"] for entry in item.get("roles") or []}
        below_attributes, below_roles = set(), set()
        if not new:
            for other_id in subtypes(definitions, type_id) - {type_id}:
                item = definitions[other_id]
                below_attributes |= {entry["key"] for entry in item.get("attributes") or []}
                below_roles |= {entry["key"] for entry in item.get("roles") or []}
        attributes = self._attributes(
            definition.get("attributes"), inherited_attributes, below_attributes
        )
        roles = self._roles(definition.get("roles"), inherited_roles, below_roles)
        # One column per attribute and per role in the plant map: their keys never meet.
        attribute_keys = inherited_attributes | below_attributes | {e["key"] for e in attributes}
        role_keys = inherited_roles | below_roles | {e["key"] for e in roles}
        clash = sorted(attribute_keys & role_keys)
        if clash:
            raise AssetTypeError(
                t("{key} is both an attribute and a signal role; use two keys.", key=clash[0])
            )
        children_raw = definition.get("children") or []
        if not isinstance(children_raw, list) or len(children_raw) > 100:
            raise AssetTypeError(t("List up to 100 types that may sit inside this one."))
        children: list[str] = []
        for child in children_raw:
            child = str(child)
            if child != type_id and child not in definitions:
                raise AssetTypeError(t("Unknown type in contents: {type}.", type=child[:60]))
            if child not in children:
                children.append(child)
        return {
            "name": name,
            "description": _text(definition.get("description"), 600).strip(),
            "icon": icon,
            "parent": parent,
            "attributes": attributes,
            "roles": roles,
            "children": children,
        }

    def _attributes(self, raw: Any, inherited: set[str], below: set[str]) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if not isinstance(raw, list) or len(raw) > MAX_ATTRIBUTES:
            raise AssetTypeError(t("A type has up to {count} attributes.", count=MAX_ATTRIBUTES))
        found: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise AssetTypeError(t("Each attribute is an object with key, name and data_type."))
            key = _key(entry.get("key"), found, inherited, below)
            name = _text(entry.get("name"), 60).strip() or key
            data_type = str(entry.get("data_type") or "text")
            if data_type not in DATA_TYPES:
                raise AssetTypeError(
                    t(
                        "Invalid data type for {key}: use {types}.",
                        key=key,
                        types=", ".join(DATA_TYPES),
                    )
                )
            options_raw = entry.get("options") or []
            if not isinstance(options_raw, list) or len(options_raw) > MAX_OPTIONS:
                raise AssetTypeError(t("Up to {count} options per attribute.", count=MAX_OPTIONS))
            options: list[str] = []
            for option in options_raw:
                if not isinstance(option, (str, int, float)) or isinstance(option, bool):
                    raise AssetTypeError(t("Options are short texts."))
                text = str(option).strip()
                if not text or len(text) > 120:
                    raise AssetTypeError(t("Options are short texts."))
                if text not in options:
                    options.append(text)
            if data_type == "choice" and not options:
                raise AssetTypeError(t("The choice attribute {key} needs options.", key=key))
            if data_type != "choice" and options:
                raise AssetTypeError(t("Only choice attributes have options ({key}).", key=key))
            clean = {
                "key": key,
                "name": name,
                "data_type": data_type,
                "unit": _text(entry.get("unit"), 30).strip(),
                "required": _flag(entry.get("required")),
                "default": None,
                "options": options,
            }
            default = entry.get("default")
            if default not in (None, ""):
                if data_type == "asset":
                    raise AssetTypeError(t("Asset references have no default ({key}).", key=key))
                clean["default"] = check_value(clean, default)
            found.append(clean)
        return found

    def _roles(self, raw: Any, inherited: set[str], below: set[str]) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if not isinstance(raw, list) or len(raw) > MAX_ROLES:
            raise AssetTypeError(t("A type has up to {count} signal roles.", count=MAX_ROLES))
        found: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise AssetTypeError(t("Each signal role is an object with key and name."))
            key = _key(entry.get("key"), found, inherited, below)
            found.append(
                {
                    "key": key,
                    "name": _text(entry.get("name"), 60).strip() or key,
                    "unit": _text(entry.get("unit"), 30).strip(),
                    "required": _flag(entry.get("required")),
                }
            )
        return found


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise AssetTypeError(t("Expected a text."))
    text = str(value)
    if len(text) > limit:
        raise AssetTypeError(t("Text too long (at most {count} characters).", count=limit))
    return text


def _flag(value: Any) -> bool:
    if value in (None, "", False, 0):
        return False
    if value in (True, 1):
        return True
    if isinstance(value, str) and value.strip().lower() in {"true", "yes", "sim", "1"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "no", "nao", "não", "0"}:
        return False
    raise AssetTypeError(t("Expected true or false."))


def _key(value: Any, found: list[dict[str, Any]], inherited: set[str], below: set[str]) -> str:
    key = _text(value, 40).strip()
    if not KEY.match(key) or key in RESERVED_KEYS:
        raise AssetTypeError(
            t(
                "Invalid key '{key}': lowercase letters, digits and _, starting with a letter "
                "(not a field of the asset itself).",
                key=key[:40],
            )
        )
    if any(entry["key"] == key for entry in found):
        raise AssetTypeError(t("The key {key} appears twice.", key=key))
    if key in inherited:
        raise AssetTypeError(t("The key {key} is already inherited from a parent type.", key=key))
    if key in below:
        raise AssetTypeError(t("A subtype already uses the key {key}.", key=key))
    return key


def check_value(attribute: dict[str, Any], value: Any, *, asset_exists: Any = None) -> Any:
    """The value as stored for its data type, or ``AssetTypeError`` saying why not.

    ``None`` (or an empty text) clears a value. ``asset_exists`` checks asset references.
    """

    key = attribute["key"]
    data_type = attribute.get("data_type") or "text"
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (dict, list)):
        raise AssetTypeError(t("{key}: expected a single value.", key=key))
    if data_type == "number":
        if isinstance(value, bool):
            raise AssetTypeError(t("{key}: expected a number.", key=key))
        try:
            number = (
                float(str(value).strip().replace(",", "."))
                if isinstance(value, str)
                else float(value)
            )
        except (TypeError, ValueError):
            raise AssetTypeError(t("{key}: expected a number.", key=key)) from None
        if not math.isfinite(number):
            raise AssetTypeError(t("{key}: expected a number.", key=key))
        return int(number) if number.is_integer() and abs(number) < 2**53 else number
    if isinstance(value, bool):
        value = "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if len(text) > MAX_TEXT:
        raise AssetTypeError(t("{key}: at most {count} characters.", key=key, count=MAX_TEXT))
    if data_type == "choice":
        options = attribute.get("options") or []
        match = next((option for option in options if option.lower() == text.lower()), None)
        if match is None:
            raise AssetTypeError(
                t("{key}: use one of {options}.", key=key, options=", ".join(options)[:400])
            )
        return match
    if data_type == "date":
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            raise AssetTypeError(t("{key}: expected a date (YYYY-MM-DD).", key=key)) from None
    if data_type == "asset":
        if len(text) > 200:
            raise AssetTypeError(t("{key}: expected an asset id.", key=key))
        if asset_exists is not None and not asset_exists(text):
            raise AssetTypeError(t("{key}: asset {asset} not found.", key=key, asset=text))
        return text
    return text


__all__ = [
    "AssetTypeConflict",
    "AssetTypeError",
    "AssetTypeStore",
    "check_value",
    "new_type_id",
]
