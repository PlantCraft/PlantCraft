"""The asset tree: site, unit, area, equipment, loop and the other types, with their signals.

Every asset is an instance of a type (``kind`` is the type id, see
``types.py``): it has a record of attribute values (``asset_attributes``),
signals bound by role (``asset_signals``) and typed relations to other assets
outside the tree (``asset_relations``: controls, measures, feeds, downstream of).

Every module points at assets by id: a loop, a digital twin, an action, a
message or a dashboard card all name the same ``asset_id``. Modules never own
assets; they sync the ones they know about (``origin``) and people can add or
move assets by hand (``origin = "manual"``), which a later sync never undoes.
"""

from __future__ import annotations

import re
from typing import Any

from plantcraft_sdk.assets import RELATION_TYPES, RESULT_TYPE, effective_attributes
from processcraft.assets.types import AssetTypeError, AssetTypeStore, check_value
from processcraft.db import Migration, Store, add_columns
from processcraft.i18n import t

ASSET_KINDS = ("site", "unit", "area", "equipment", "loop")
# English constants; ``kind_label`` reads them in the current language.
KIND_LABELS = {
    "site": "Plant",
    "unit": "Unit",
    "area": "Area",
    "equipment": "Equipment",
    "loop": "Control loop",
}
_ID = re.compile(r"[^A-Za-z0-9_.\-]+")


def asset_id_for(name: str) -> str:
    """A stable id for a name that has none (``"Área 2"`` → ``"area-2"``)."""

    import unicodedata

    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = _ID.sub("-", plain.strip()).strip("-").lower()
    return slug or "asset"


class AssetStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS assets (
        asset_id TEXT PRIMARY KEY,
        parent_id TEXT,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT 'manual',
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_id, position, name);

    CREATE TABLE IF NOT EXISTS asset_signals (
        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        signal_id TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT '',
        name TEXT NOT NULL DEFAULT '',
        unit TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT 'manual',
        PRIMARY KEY (asset_id, signal_id, origin)
    );
    -- source_id (added 2026-10-20): the source the tag (signal_id) is read from, so API v1
    -- names the signal <source id>:<tag>; '' until the platform fills it.

    CREATE INDEX IF NOT EXISTS idx_asset_signals_signal ON asset_signals(signal_id);

    -- Kinds people added before asset types existed; read once into the types.
    CREATE TABLE IF NOT EXISTS asset_kinds (
        kind TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    -- The record of an asset: one value per attribute of its type (master data).
    CREATE TABLE IF NOT EXISTS asset_attributes (
        asset_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        key TEXT NOT NULL,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (asset_id, key)
    );

    -- Typed links outside the tree: FIC-2001 controls FV-2001.
    CREATE TABLE IF NOT EXISTS asset_relations (
        from_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        relation TEXT NOT NULL,
        to_id TEXT NOT NULL REFERENCES assets(asset_id) ON DELETE CASCADE,
        origin TEXT NOT NULL DEFAULT 'manual',
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (from_id, relation, to_id)
    );

    CREATE INDEX IF NOT EXISTS idx_asset_relations_to ON asset_relations(to_id);
    """

    # Bumped on every write, so readers can cache the tree.
    version = 0

    MIGRATIONS = (
        Migration(
            "columns-before-0.5",
            add_columns(
                "asset_signals",
                {
                    "source_id": "TEXT NOT NULL DEFAULT ''",
                },
            ),
        ),
    )

    def __init__(self, db: Any):
        super().__init__(db)
        self.types = AssetTypeStore(db)
        with self._lock, self._write() as connection:
            rows = connection.execute(
                "SELECT kind, label FROM asset_kinds ORDER BY created_at, kind"
            ).fetchall()
        # Kinds added before types existed are types now (once).
        self.types.adopt_kinds([(row["kind"], row["label"]) for row in rows])

    # Kinds (the types, as the tree's filter chips list them) ---------------

    def kinds(self) -> list[dict[str, Any]]:
        """Every type: the platform's own first, then the rest in catalog order."""

        definitions = self.types.definitions()
        ordered = [kind for kind in ASSET_KINDS if kind in definitions] + [
            kind for kind in definitions if kind not in ASSET_KINDS
        ]
        return [
            {
                "kind": kind,
                "label": definitions[kind]["name"],
                "builtin": kind in ASSET_KINDS,
                "parent": definitions[kind]["parent"],
                "icon": definitions[kind]["icon"],
            }
            for kind in ordered
        ]

    def is_kind(self, kind: str) -> bool:
        return self.types.exists(kind)

    def add_kind(self, label: str) -> dict[str, Any]:
        """A type under ``equipment`` from just a name (the tree's quick "+ Type")."""

        label = label.strip()
        try:
            created = self.types.create(
                {"name": label, "parent": "equipment", "icon": "box"}, actor=""
            )
        except AssetTypeError as exc:
            raise ValueError(str(exc)) from exc
        return {"kind": created["id"], "label": created["name"], "builtin": False}

    def remove_kind(self, kind: str) -> None:
        try:
            self.types.delete(kind, in_use=self.counts().get(kind, 0))
        except KeyError:
            return
        except AssetTypeError as exc:
            raise ValueError(str(exc)) from exc

    def depth(self, kind: str) -> int:
        """Where a kind sits from site to loop, by its root type; other roots sit with equipment."""

        root = (self.types.path(kind) or [kind])[0]
        return ASSET_KINDS.index(root) if root in ASSET_KINDS else ASSET_KINDS.index("equipment")

    # Reading ---------------------------------------------------------------

    def get(self, asset_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        return self._item(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM assets ORDER BY position, name").fetchall()
        return [self._item(row) for row in rows]

    def children(self, parent_id: str | None) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            if parent_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM assets
                    WHERE parent_id IS NULL OR parent_id NOT IN (SELECT asset_id FROM assets)
                    ORDER BY position, name
                    """
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM assets WHERE parent_id = ? ORDER BY position, name", (parent_id,)
                ).fetchall()
        return [self._item(row) for row in rows]

    def search(self, text: str, *, limit: int = 20) -> list[dict[str, Any]]:
        pattern = f"%{text.strip()}%"
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM assets
                WHERE asset_id LIKE ? OR name LIKE ? OR description LIKE ?
                ORDER BY CASE WHEN asset_id LIKE ? THEN 0 ELSE 1 END, name
                LIMIT ?
                """,
                (pattern, pattern, pattern, f"{text.strip()}%", limit),
            ).fetchall()
        return [self._item(row) for row in rows]

    def path(self, asset_id: str) -> list[dict[str, Any]]:
        """The asset and its ancestors, root first."""

        by_id = {item["asset_id"]: item for item in self.list()}
        chain: list[dict[str, Any]] = []
        current = by_id.get(asset_id)
        while current is not None and current not in chain:
            chain.append(current)
            current = by_id.get(current["parent_id"]) if current["parent_id"] else None
        return list(reversed(chain))

    def descendants(self, asset_id: str) -> set[str]:
        """The asset and every asset under it."""

        children: dict[str | None, list[str]] = {}
        for item in self.list():
            children.setdefault(item["parent_id"], []).append(item["asset_id"])
        found = {asset_id}
        pending = [asset_id]
        while pending:
            for child in children.get(pending.pop(), []):
                if child not in found:
                    found.add(child)
                    pending.append(child)
        return found

    def signals(self, asset_id: str) -> list[dict[str, Any]]:
        """The asset's signals; when two modules list one, the one with a role wins."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM asset_signals WHERE asset_id = ? ORDER BY role = '', role, signal_id",
                (asset_id,),
            ).fetchall()
        seen: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            current = seen.get(item["signal_id"])
            if current is None:
                seen[item["signal_id"]] = item
            else:
                current["name"] = current["name"] or item["name"]
                current["unit"] = current["unit"] or item["unit"]
        return list(seen.values())

    def signal_roles(self, kind: str) -> dict[str, list[dict[str, str]]]:
        """For every signal, the assets of one kind that use it and with which role."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT s.signal_id, s.asset_id, s.role
                FROM asset_signals s JOIN assets a ON a.asset_id = s.asset_id
                WHERE a.kind = ? AND s.role != ''
                ORDER BY s.signal_id, s.asset_id
                """,
                (kind,),
            ).fetchall()
        roles: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            roles.setdefault(row["signal_id"], []).append(
                {"asset_id": row["asset_id"], "role": row["role"]}
            )
        return roles

    def assets_of_signal(self, signal_id: str) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT asset_id FROM asset_signals WHERE signal_id = ? ORDER BY asset_id",
                (signal_id,),
            ).fetchall()
        return [row["asset_id"] for row in rows]

    def signal_counts(self) -> dict[str, int]:
        """How many distinct signals each asset has."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT asset_id, COUNT(DISTINCT signal_id) AS n FROM asset_signals GROUP BY asset_id"
            ).fetchall()
        return {row["asset_id"]: int(row["n"]) for row in rows}

    def signal_assets(self, signal_ids: list[str] | None = None) -> dict[str, list[dict[str, str]]]:
        """For each signal, the assets that list it (id, name, kind, role, origin)."""

        query = """
            SELECT s.signal_id, s.asset_id, s.role, s.origin, a.name, a.kind
            FROM asset_signals s JOIN assets a ON a.asset_id = s.asset_id
        """
        params: tuple[Any, ...] = ()
        if signal_ids is not None:
            if not signal_ids:
                return {}
            query += f" WHERE s.signal_id IN ({','.join('?' for _ in signal_ids)})"
            params = tuple(signal_ids)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                query + " ORDER BY s.signal_id, s.role = '', s.asset_id", params
            ).fetchall()
        found: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            uses = found.setdefault(row["signal_id"], [])
            if not any(item["asset_id"] == row["asset_id"] for item in uses):
                uses.append(
                    {
                        "asset_id": row["asset_id"],
                        "name": row["name"],
                        "kind": row["kind"],
                        "role": row["role"],
                        "origin": row["origin"],
                    }
                )
        return found

    def counts(self) -> dict[str, int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT kind, COUNT(*) AS n FROM assets GROUP BY kind"
            ).fetchall()
        return {row["kind"]: int(row["n"]) for row in rows}

    # Writing ---------------------------------------------------------------

    def save(
        self,
        asset_id: str,
        *,
        name: str,
        kind: str,
        parent_id: str | None = None,
        description: str = "",
        origin: str = "manual",
        position: int = 0,
    ) -> dict[str, Any]:
        """Create or update one asset.

        A sync never overwrites a hand-made asset, and between two modules the
        more specific kind wins (a loop stays a loop when another module only
        knows the same id as equipment).
        """

        if not self.is_kind(kind):
            raise ValueError(t("Invalid asset type: {kind}.", kind=kind))
        if parent_id == asset_id:
            raise ValueError(t("An asset cannot be its own parent."))
        now = self._now()
        with self._lock, self._write() as connection:
            existing = connection.execute(
                "SELECT origin FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if existing is not None and existing["origin"] != origin and origin != "manual":
                current = connection.execute(
                    "SELECT kind FROM assets WHERE asset_id = ?", (asset_id,)
                ).fetchone()["kind"]
                deeper = self.depth(kind) > self.depth(current)
                if existing["origin"] == "manual" or not deeper:
                    return self.get(asset_id) or {}
            connection.execute(
                """
                INSERT INTO assets (asset_id, parent_id, kind, name, description, origin, position, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    parent_id = excluded.parent_id, kind = excluded.kind, name = excluded.name,
                    description = excluded.description, origin = excluded.origin,
                    position = excluded.position, updated_at = excluded.updated_at
                """,
                (
                    asset_id,
                    parent_id,
                    kind,
                    name.strip() or asset_id,
                    description,
                    origin,
                    position,
                    now,
                    now,
                ),
            )
        type(self).version += 1
        return self.get(asset_id) or {}

    def set_signals(self, asset_id: str, signals: list[dict[str, Any]], *, origin: str) -> None:
        """Replace the signals this origin gave the asset; hand-added ones stay."""

        with self._lock, self._write() as connection:
            connection.execute(
                "DELETE FROM asset_signals WHERE asset_id = ? AND origin = ?", (asset_id, origin)
            )
            connection.executemany(
                """
                INSERT INTO asset_signals (asset_id, signal_id, role, name, unit, origin, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id, signal_id, origin) DO NOTHING
                """,
                [
                    (
                        asset_id,
                        str(item["signal_id"]),
                        str(item.get("role") or ""),
                        str(item.get("name") or ""),
                        str(item.get("unit") or ""),
                        origin,
                        str(item.get("source_id") or ""),
                    )
                    for item in signals
                    if item.get("signal_id")
                ],
            )
        type(self).version += 1

    def bind_signals(
        self, asset_id: str, signals: list[dict[str, Any]], *, origin: str = "manual"
    ) -> None:
        """Add (or update the role, name and unit of) signals on an asset, keeping the others."""

        with self._lock, self._write() as connection:
            connection.executemany(
                """
                INSERT INTO asset_signals (asset_id, signal_id, role, name, unit, origin, source_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id, signal_id, origin) DO UPDATE SET
                    role = excluded.role, name = excluded.name, unit = excluded.unit,
                    source_id = CASE WHEN excluded.source_id = '' THEN asset_signals.source_id
                                ELSE excluded.source_id END
                """,
                [
                    (
                        asset_id,
                        str(item["signal_id"]),
                        str(item.get("role") or ""),
                        str(item.get("name") or ""),
                        str(item.get("unit") or ""),
                        origin,
                        str(item.get("source_id") or ""),
                    )
                    for item in signals
                    if item.get("signal_id")
                ],
            )
        type(self).version += 1

    def unbind_signals(self, pairs: list[tuple[str, str]], *, origin: str = "manual") -> None:
        """Remove ``(asset_id, signal_id)`` bindings one origin made."""

        with self._lock, self._write() as connection:
            connection.executemany(
                "DELETE FROM asset_signals WHERE asset_id = ? AND signal_id = ? AND origin = ?",
                [(asset_id, signal_id, origin) for asset_id, signal_id in pairs],
            )
        type(self).version += 1

    def bound_tags(self) -> list[str]:
        """Every tag bound to an asset (``signal_id`` holds the tag)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT signal_id FROM asset_signals ORDER BY signal_id"
            ).fetchall()
        return [row["signal_id"] for row in rows]

    def binding_sources(self) -> dict[str, str]:
        """Tag → the source its bindings record (one, when they disagree; '' not filled yet)."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT signal_id, MAX(source_id) AS source_id FROM asset_signals GROUP BY signal_id"
            ).fetchall()
        return {row["signal_id"]: row["source_id"] for row in rows}

    def set_binding_sources(self, sources: dict[str, str]) -> int:
        """Record the source each tag is read from on its bindings; returns the rows changed."""

        with self._lock, self._write() as connection:
            changed = 0
            for tag, source_id in sources.items():
                changed += connection.execute(
                    # An app's own series (results) keep their app-<app id> source.
                    "UPDATE asset_signals SET source_id = ? WHERE signal_id = ? AND source_id != ?"
                    " AND source_id NOT LIKE 'app-%'",
                    (source_id, tag, source_id),
                ).rowcount
        if changed:
            type(self).version += 1
        return changed

    def bindings(self, *, origin: str) -> list[dict[str, Any]]:
        """Every signal binding one origin made."""

        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM asset_signals WHERE origin = ? ORDER BY asset_id, signal_id",
                (origin,),
            ).fetchall()
        return [dict(row) for row in rows]

    def sync(self, origin: str, assets: list[dict[str, Any]]) -> int:
        """Bring the assets one origin knows in line with it, parents first.

        Assets of this origin that are no longer listed are removed, unless a
        person moved them under a hand-made asset (then they became manual).
        """

        listed = {item["asset_id"] for item in assets}
        ordered = sorted(assets, key=lambda item: self.depth(item["kind"]))
        for position, item in enumerate(ordered):
            self.save(
                item["asset_id"],
                name=item["name"],
                kind=item["kind"],
                parent_id=item.get("parent_id"),
                description=item.get("description", ""),
                origin=origin,
                position=item.get("position", position),
            )
            if "signals" in item:
                self.set_signals(item["asset_id"], item["signals"], origin=origin)
        with self._lock, self._write() as connection:
            stale = [
                row["asset_id"]
                for row in connection.execute(
                    "SELECT asset_id FROM assets WHERE origin = ?", (origin,)
                )
                if row["asset_id"] not in listed
            ]
            connection.executemany(
                "DELETE FROM assets WHERE asset_id = ?", [(item,) for item in stale]
            )
        type(self).version += 1
        return len(listed)

    # Result assets (what an app records about an asset) ---------------------------

    def sync_results(
        self, app: str, items: list[dict[str, Any]], *, actor: str = ""
    ) -> dict[str, int]:
        """Bring an app's result assets in line with ``items`` (``parse_result_assets``).

        Each one hangs under the asset it is about, which must exist and not be a result
        itself. Its points are its signals (``app-<app id>:<name>``, by role); ``app``,
        ``made_by`` and ``state`` are its record. Results the app no longer lists are
        ended, not removed: their points keep their history until the app removes them.
        ``ValueError`` names the first fault; nothing is written then.
        """

        origin = f"app:{app}"
        source = f"app-{app}"
        listed = {item["id"] for item in items}
        wanted = sorted(listed | {item["parent_id"] for item in items})
        rows = []
        with self._lock, self._connect() as connection:
            for start in range(0, len(wanted), 500):
                chunk = wanted[start : start + 500]
                rows += connection.execute(
                    "SELECT asset_id, kind, origin FROM assets"
                    f" WHERE asset_id IN ({','.join('?' for _ in chunk)})",
                    tuple(chunk),
                ).fetchall()
        known = {row["asset_id"]: row for row in rows}
        for index, item in enumerate(items):
            parent = known.get(item["parent_id"])
            if parent is None:
                raise ValueError(
                    t(
                        "[{index}] parent_id {id} is not an asset.",
                        index=index,
                        id=item["parent_id"],
                    )
                )
            if parent["kind"] == RESULT_TYPE:
                raise ValueError(
                    t(
                        "[{index}] a result hangs under the asset it is about, not under another result.",
                        index=index,
                    )
                )
            mine = known.get(item["id"])
            if mine is not None and (mine["origin"] != origin or mine["kind"] != RESULT_TYPE):
                raise ValueError(
                    t(
                        "[{index}] {id} is an asset the app does not own.",
                        index=index,
                        id=item["id"],
                    )
                )
        now = self._now()
        with self._lock, self._write() as connection:
            for position, item in enumerate(items):
                connection.execute(
                    """
                    INSERT INTO assets (asset_id, parent_id, kind, name, description, origin, position, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        parent_id = excluded.parent_id, name = excluded.name,
                        description = excluded.description, position = excluded.position,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item["id"],
                        item["parent_id"],
                        RESULT_TYPE,
                        item["name"],
                        item["description"],
                        origin,
                        position,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "DELETE FROM asset_signals WHERE asset_id = ? AND origin = ?",
                    (item["id"], origin),
                )
                connection.executemany(
                    """
                    INSERT INTO asset_signals (asset_id, signal_id, role, name, unit, origin, source_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id, signal_id, origin) DO NOTHING
                    """,
                    [
                        (
                            item["id"],
                            point["signal"].partition(":")[2],
                            point["role"],
                            point["name"],
                            point["unit"],
                            origin,
                            source,
                        )
                        for point in item["points"]
                    ],
                )
                record = {"app": app, "made_by": item["made_by"], "state": "active"}
                connection.executemany(
                    """
                    INSERT INTO asset_attributes (asset_id, key, value_json, updated_at, updated_by)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id, key) DO UPDATE SET value_json = excluded.value_json,
                        updated_at = excluded.updated_at, updated_by = excluded.updated_by
                    """,
                    [
                        (item["id"], key, self._json(value), now, actor)
                        for key, value in record.items()
                    ],
                )
            stale = [
                row["asset_id"]
                for row in connection.execute(
                    "SELECT asset_id FROM assets WHERE origin = ? AND kind = ?",
                    (origin, RESULT_TYPE),
                )
                if row["asset_id"] not in listed
            ]
            ended = 0
            for asset_id in stale:
                ended += connection.execute(
                    """
                    INSERT INTO asset_attributes (asset_id, key, value_json, updated_at, updated_by)
                    VALUES (?, 'state', ?, ?, ?)
                    ON CONFLICT(asset_id, key) DO UPDATE SET value_json = excluded.value_json,
                        updated_at = excluded.updated_at, updated_by = excluded.updated_by
                    WHERE asset_attributes.value_json != excluded.value_json
                    """,
                    (asset_id, self._json("ended"), now, actor),
                ).rowcount
        type(self).version += 1
        return {"saved": len(items), "ended": ended}

    def remove_results(self, app: str, ids: list[str]) -> int:
        """Remove result assets of ``app`` (their points stay in the Historian); returns how many."""

        if not ids:
            return 0
        with self._lock, self._write() as connection:
            removed = connection.execute(
                f"DELETE FROM assets WHERE origin = ? AND kind = ? AND asset_id IN ({','.join('?' for _ in ids)})",
                (f"app:{app}", RESULT_TYPE, *ids),
            ).rowcount
        if removed:
            type(self).version += 1
        return removed

    def adopt(self, old_origin: str, new_origin: str) -> int:
        """Hand one origin's assets and signal links to another (a module renamed or moved).

        Returns how many assets changed hands; links the new origin already has are kept.
        """

        with self._lock, self._write() as connection:
            moved = connection.execute(
                "UPDATE assets SET origin = ? WHERE origin = ?", (new_origin, old_origin)
            ).rowcount
            connection.execute(
                "UPDATE OR IGNORE asset_signals SET origin = ? WHERE origin = ?",
                (new_origin, old_origin),
            )
            connection.execute("DELETE FROM asset_signals WHERE origin = ?", (old_origin,))
        type(self).version += 1
        return moved

    def move(self, asset_id: str, parent_id: str | None) -> dict[str, Any]:
        if parent_id is not None and parent_id in self.descendants(asset_id):
            raise ValueError(t("An asset cannot be inside itself."))
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE assets SET parent_id = ?, origin = 'manual', updated_at = ? WHERE asset_id = ?",
                (parent_id, self._now(), asset_id),
            )
        type(self).version += 1
        return self.get(asset_id) or {}

    def delete(self, asset_id: str) -> None:
        """Remove a hand-made asset; its children move up to its parent."""

        asset = self.get(asset_id)
        if asset is None:
            return
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE assets SET parent_id = ? WHERE parent_id = ?",
                (asset["parent_id"], asset_id),
            )
            connection.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
        type(self).version += 1

    # Records (attribute values) -----------------------------------------------

    def stored_attributes(self, asset_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """The stored values per asset (any key, also those its type no longer has)."""

        query = "SELECT asset_id, key, value_json FROM asset_attributes"
        params: tuple[Any, ...] = ()
        if asset_ids is not None:
            if not asset_ids:
                return {}
            query += f" WHERE asset_id IN ({','.join('?' for _ in asset_ids)})"
            params = tuple(asset_ids)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        found: dict[str, dict[str, Any]] = {}
        for row in rows:
            found.setdefault(row["asset_id"], {})[row["key"]] = self._loads(row["value_json"], None)
        return found

    def attributes(self, asset_id: str) -> dict[str, Any]:
        """The asset's values for the attributes of its type (stored, else the default)."""

        asset = self.get(asset_id)
        if asset is None:
            return {}
        return effective_attributes(
            self.types.resolved(asset["kind"]), self.stored_attributes([asset_id]).get(asset_id, {})
        )

    def all_attributes(self) -> dict[str, dict[str, Any]]:
        """``attributes`` for every asset, in two queries."""

        stored = self.stored_attributes()
        resolved = {item["id"]: item for item in self.types.all_resolved()}
        return {
            item["asset_id"]: effective_attributes(
                resolved.get(item["kind"]), stored.get(item["asset_id"], {})
            )
            for item in self.list()
        }

    def set_attributes(
        self, asset_id: str, values: dict[str, Any], *, actor: str, check_refs: bool = True
    ) -> list[dict[str, Any]]:
        """Check and store values (``None`` clears one); returns what changed, key by key.

        Unknown keys, values outside their data type and clearing a required
        attribute raise ``AssetTypeError``; nothing is written then.
        """

        asset = self.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        resolved = self.types.resolved(asset["kind"]) or {"attributes": []}
        by_key = {entry["key"]: entry for entry in resolved["attributes"]}
        current = self.stored_attributes([asset_id]).get(asset_id, {})
        unknown = sorted(key for key in values if key not in by_key)
        if unknown:
            raise AssetTypeError(
                t(
                    "Not an attribute of {type}: {keys}.",
                    type=resolved.get("name") or asset["kind"],
                    keys=", ".join(str(key)[:40] for key in unknown[:10]),
                )
            )
        changes: list[dict[str, Any]] = []
        for key, raw in values.items():
            entry = by_key[key]
            value = check_value(
                entry,
                raw,
                asset_exists=(lambda other: self.get(other) is not None) if check_refs else None,
            )
            if entry.get("data_type") == "asset" and value == asset_id:
                raise AssetTypeError(t("{key}: an asset cannot point at itself.", key=key))
            if value is None and entry.get("required") and entry.get("default") is None:
                raise AssetTypeError(t("{name} is required.", name=entry["name"]))
            if current.get(key) != value:
                changes.append(
                    {"key": key, "name": entry["name"], "from": current.get(key), "to": value}
                )
        if not changes:
            return []
        now = self._now()
        with self._lock, self._write() as connection:
            for change in changes:
                if change["to"] is None:
                    connection.execute(
                        "DELETE FROM asset_attributes WHERE asset_id = ? AND key = ?",
                        (asset_id, change["key"]),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO asset_attributes (asset_id, key, value_json, updated_at, updated_by)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(asset_id, key) DO UPDATE SET value_json = excluded.value_json,
                            updated_at = excluded.updated_at, updated_by = excluded.updated_by
                        """,
                        (asset_id, change["key"], self._json(change["to"]), now, actor),
                    )
        type(self).version += 1
        return changes

    def missing(self, asset_id: str) -> dict[str, list[str]]:
        """Required attributes without a value and required roles without a signal."""

        asset = self.get(asset_id)
        resolved = self.types.resolved(asset["kind"]) if asset else None
        if resolved is None:
            return {"attributes": [], "roles": []}
        values = self.attributes(asset_id)
        bound = {item["role"] for item in self.signals(asset_id) if item.get("role")}
        return {
            "attributes": [
                entry["key"]
                for entry in resolved["attributes"]
                if entry["required"] and values.get(entry["key"]) is None
            ],
            "roles": [
                entry["key"]
                for entry in resolved["roles"]
                if entry["required"] and entry["key"] not in bound
            ],
        }

    # Relations ------------------------------------------------------------------

    def relations(self, asset_id: str | None = None) -> list[dict[str, Any]]:
        """Relations from or to one asset (every relation when ``asset_id`` is None)."""

        query = "SELECT * FROM asset_relations"
        params: tuple[Any, ...] = ()
        if asset_id is not None:
            query += " WHERE from_id = ? OR to_id = ?"
            params = (asset_id, asset_id)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                query + " ORDER BY from_id, relation, to_id", params
            ).fetchall()
        return [dict(row) for row in rows]

    def outgoing(self) -> dict[str, list[dict[str, str]]]:
        """For every asset, its relations to others as API v1 lists them."""

        found: dict[str, list[dict[str, str]]] = {}
        for item in self.relations():
            found.setdefault(item["from_id"], []).append(
                {"type": item["relation"], "to": item["to_id"]}
            )
        return found

    def relate(
        self, from_id: str, relation: str, to_id: str, *, actor: str = "", origin: str = "manual"
    ) -> bool:
        """Add a relation; False when it was already there."""

        if relation not in RELATION_TYPES:
            raise AssetTypeError(
                t("Unknown relation: use {types}.", types=", ".join(RELATION_TYPES))
            )
        if from_id == to_id:
            raise AssetTypeError(t("An asset cannot be related to itself."))
        if self.get(from_id) is None or self.get(to_id) is None:
            raise KeyError(to_id if self.get(from_id) else from_id)
        with self._lock, self._write() as connection:
            added = connection.execute(
                """
                INSERT OR IGNORE INTO asset_relations (from_id, relation, to_id, origin, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (from_id, relation, to_id, origin, self._now(), actor),
            ).rowcount
        type(self).version += 1
        return bool(added)

    def unrelate(self, from_id: str, relation: str, to_id: str) -> bool:
        with self._lock, self._write() as connection:
            removed = connection.execute(
                "DELETE FROM asset_relations WHERE from_id = ? AND relation = ? AND to_id = ?",
                (from_id, relation, to_id),
            ).rowcount
        type(self).version += 1
        return bool(removed)

    def _item(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["kind_label"] = self.types.name(item["kind"])
        return item
