"""The site's blocks and their versions (``blocks.files``), and their place in the catalog.

``site_blocks`` holds one row per block (its id, who made it, who answers for it, its tags and
its current version); ``site_block_versions`` one row per saved version, immutable, with the
whole block file. Saving puts the version in the catalog (``register``) and its file in the
blocks folder, where worker processes read it (``blocks.site``).
"""

from __future__ import annotations

import json
from typing import Any

from linkcraft.blocks import site
from linkcraft.blocks.base import LIBRARIES
from linkcraft.blocks.catalog import BUILTIN_IDS, CATALOG, CURRENT
from linkcraft.blocks.files import (
    CLOSED_LIBRARIES,
    BlockFile,
    pinned_id,
    read_file,
    slug,
    split_pinned,
)
from linkcraft.db import Store
from linkcraft.i18n import t


class BlockStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS site_blocks (
        block_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        library TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        origin TEXT NOT NULL DEFAULT 'user',
        author TEXT NOT NULL DEFAULT '',
        author_name TEXT NOT NULL DEFAULT '',
        owner TEXT NOT NULL DEFAULT '',
        owner_name TEXT NOT NULL DEFAULT '',
        current INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS site_block_versions (
        block_id TEXT NOT NULL,
        number INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        contract TEXT NOT NULL,
        file_json TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '',
        author_name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        PRIMARY KEY (block_id, number)
    );
    CREATE TABLE IF NOT EXISTS site_libraries (
        library TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        author_name TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    """

    def libraries(self) -> list[dict[str, Any]]:
        """The libraries made on this site (round 10), by name: the Blocks page lists them after
        Link's, and New block puts a block in one."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT library, name, description, author_name, created_at FROM site_libraries "
                "ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_library(self, name: str, description: str, user: Any) -> dict[str, Any]:  # noqa: ANN401
        """A new library from its name; its id is the name in lower case, made free if taken."""

        name = " ".join(str(name or "").split())[:80]
        if not name:
            raise ValueError(t("A library has a name."))
        base = slug(name)[:36].rstrip("_")
        if len(base) < 2:
            base = f"{base}_lib"
        with self._lock, self._connect() as connection:
            taken = {row[0] for row in connection.execute("SELECT library FROM site_libraries")}
            taken |= set(LIBRARIES) | set(CLOSED_LIBRARIES)
            names = {
                str(row[0]).lower() for row in connection.execute("SELECT name FROM site_libraries")
            } | {str(item["name"]).lower() for item in LIBRARIES.values()}
            if name.lower() in names:
                raise ValueError(t("A library named {name} already exists.", name=name))
            library, number = base, 2
            while library in taken:
                library, number = f"{base}_{number}", number + 1
            row = {
                "library": library,
                "name": name,
                "description": " ".join(str(description or "").split())[:300],
                "author": getattr(user, "username", "") or "",
                "author_name": getattr(user, "name", "") or getattr(user, "username", "") or "",
                "created_at": self._now(),
            }
            connection.execute(
                "INSERT INTO site_libraries (library, name, description, author, author_name, "
                "created_at) VALUES (:library, :name, :description, :author, :author_name, "
                ":created_at)",
                row,
            )
        return {
            key: row[key] for key in ("library", "name", "description", "author_name", "created_at")
        }

    def _block(self, row: Any) -> dict[str, Any]:
        return self._row_with_json(row, {"tags": ("tags_json", [])})

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM site_blocks ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._block(row) for row in rows]

    def get(self, block_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM site_blocks WHERE block_id = ?", (block_id,)
            ).fetchone()
        return self._block(row) if row else None

    def versions(self, block_id: str) -> list[dict[str, Any]]:
        """Every version of a block, newest first, without the file."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT block_id, number, name, description, contract, author, author_name, "
                "created_at FROM site_block_versions WHERE block_id = ? ORDER BY number DESC",
                (block_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def file(self, block_id: str, number: int | None = None) -> BlockFile | None:
        """A version's block file (the current one when ``number`` is ``None``)."""

        found = self.get(block_id)
        if found is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT file_json FROM site_block_versions WHERE block_id = ? AND number = ?",
                (block_id, int(number or found["current"])),
            ).fetchone()
        return read_file(row["file_json"]) if row else None

    def _stamped(
        self,
        file: BlockFile,
        block: dict[str, Any],
        number: int,
        version: dict[str, str],
        user: Any,
    ) -> BlockFile:
        data = file.model_dump(mode="json")
        data.update(
            block_id=block["block_id"],
            tags=list(block["tags"]),
            author=block["author"],
            owner=block["owner"],
            version={
                "number": number,
                "name": version.get("name") or "",
                "description": version.get("description") or "",
            },
        )
        stamped = read_file(data)
        stamped.version.number = number
        return stamped

    def create(
        self,
        file: BlockFile,
        user: Any,
        *,
        version_name: str = "",
        version_description: str = "",
        shipped: bool = False,
    ) -> dict[str, Any]:
        """A new block from ``file``: its version 1. The id is the file's, made free if taken.

        ``shipped``: the site's first version of a block Link ships, under the same id. Link's
        own is version 1 (``dq.spikes``, which the algorithms already using it keep), so the
        site's starts at 2 (``dq.spikes.v2``)."""

        wanted = file.family()
        first = 2 if shipped else 1
        now = self._now()
        with self._lock, self._connect() as connection:
            block_id, number = wanted, 2
            if shipped:
                if (
                    wanted not in BUILTIN_IDS
                    or connection.execute(
                        "SELECT 1 FROM site_blocks WHERE block_id = ?", (wanted,)
                    ).fetchone()
                ):
                    raise ValueError(t("This block already has versions on this site."))
            while not shipped and (
                block_id in BUILTIN_IDS
                or connection.execute(
                    "SELECT 1 FROM site_blocks WHERE block_id = ?", (block_id,)
                ).fetchone()
            ):
                block_id, number = f"{wanted[:56]}_{number}", number + 1
            username = getattr(user, "username", "") or ""
            name = getattr(user, "name", "") or username
            block = {
                "block_id": block_id,
                "tags": file.tags,
                "author": file.author or username,
                "owner": file.owner or username,
            }
            stamped = self._stamped(
                file,
                block,
                first,
                {"name": version_name or t("First version"), "description": version_description},
                user,
            )
            connection.execute(
                "INSERT INTO site_blocks (block_id, name, library, tags_json, origin, author, author_name, "
                "owner, owner_name, current, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    block_id,
                    stamped.name,
                    stamped.library,
                    self._json(stamped.tags),
                    stamped.origin,
                    stamped.author,
                    name if stamped.author == username else stamped.author,
                    stamped.owner,
                    name if stamped.owner == username else stamped.owner,
                    first,
                    now,
                    now,
                ),
            )
            self._insert_version(connection, stamped, username, name, now)
        self.register_one(block_id, first, stamped)
        CURRENT[block_id] = pinned_id(block_id, first)
        return self.get(block_id) or {}

    def _insert_version(
        self, connection: Any, file: BlockFile, username: str, name: str, now: str
    ) -> None:
        connection.execute(
            "INSERT INTO site_block_versions (block_id, number, name, description, contract, file_json, "
            "author, author_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file.block_id,
                file.version.number,
                file.version.name,
                file.version.description,
                file.contract(),
                json.dumps(file.model_dump(mode="json"), ensure_ascii=False),
                username,
                name,
                now,
            ),
        )

    def add_version(
        self, block_id: str, file: BlockFile, user: Any, *, name: str, description: str = ""
    ) -> dict[str, Any]:
        """Save ``file`` as the block's next version; it becomes the current one."""

        found = self.get(block_id)
        if found is None:
            raise KeyError(block_id)
        if file.library != found["library"]:
            raise ValueError(
                t(
                    "A new version stays in the block's library ({library}).",
                    library=found["library"],
                )
            )
        username = getattr(user, "username", "") or ""
        person = getattr(user, "name", "") or username
        now = self._now()
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(number) AS last FROM site_block_versions WHERE block_id = ?",
                (block_id,),
            ).fetchone()
            number = int(row["last"] or 0) + 1
            block = {**found, "tags": file.tags or found["tags"]}
            stamped = self._stamped(
                file, block, number, {"name": name, "description": description}, user
            )
            self._insert_version(connection, stamped, username, person, now)
            connection.execute(
                "UPDATE site_blocks SET name = ?, tags_json = ?, current = ?, updated_at = ? WHERE block_id = ?",
                (stamped.name, self._json(stamped.tags), number, now, block_id),
            )
        self.register_one(block_id, number, stamped)
        CURRENT[block_id] = pinned_id(block_id, number)
        return {
            "block_id": block_id,
            "number": number,
            "contract_changed": stamped.contract() != self._contract(block_id, found["current"]),
        }

    def select(self, block_id: str, number: int) -> dict[str, Any] | None:
        """Make version ``number`` the one in use: what the palette, a new algorithm and the
        block's page take. The algorithms already using the block keep the version they pin.

        Version 1 of a block Link ships is Link's own: the catalog then lists the shipped one."""

        found = self.get(block_id)
        if found is None:
            return None
        shipped = block_id in BUILTIN_IDS and number == 1
        with self._lock, self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM site_block_versions WHERE block_id = ? AND number = ?",
                (block_id, number),
            ).fetchone()
            if not exists and not shipped:
                raise ValueError(t("Version not found."))
            connection.execute(
                "UPDATE site_blocks SET current = ?, updated_at = ? WHERE block_id = ?",
                (number, self._now(), block_id),
            )
        if shipped:
            CURRENT.pop(block_id, None)
        else:
            CURRENT[block_id] = pinned_id(block_id, number)
        return self.get(block_id)

    def _contract(self, block_id: str, number: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT contract FROM site_block_versions WHERE block_id = ? AND number = ?",
                (block_id, number),
            ).fetchone()
        return str(row["contract"]) if row else ""

    def update(
        self,
        block_id: str,
        *,
        owner: str | None = None,
        owner_name: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Who answers for a block and its tags: not part of a version."""

        found = self.get(block_id)
        if found is None:
            return None
        fields: dict[str, Any] = {}
        if owner is not None:
            fields["owner"] = owner.strip()[:120]
            fields["owner_name"] = (owner_name or owner).strip()[:120]
        if tags is not None:
            fields["tags_json"] = self._json(
                list(dict.fromkeys(tag.strip().lower()[:40] for tag in tags if tag.strip()))[:20]
            )
        if not fields:
            return found
        fields["updated_at"] = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE site_blocks SET {', '.join(f'{key} = ?' for key in fields)} WHERE block_id = ?",  # noqa: S608 - fixed column names
                (*fields.values(), block_id),
            )
        return self.get(block_id)

    def delete(self, block_id: str) -> bool:
        with self._lock, self._connect() as connection:
            gone = connection.execute(
                "DELETE FROM site_blocks WHERE block_id = ?", (block_id,)
            ).rowcount
            connection.execute("DELETE FROM site_block_versions WHERE block_id = ?", (block_id,))
        CURRENT.pop(block_id, None)
        for key in [key for key in CATALOG if (split_pinned(key) or ("",))[0] == block_id]:
            del CATALOG[key]
        return bool(gone)

    def register_one(self, block_id: str, number: int, file: BlockFile) -> None:
        pinned = pinned_id(block_id, number)
        site.write(pinned, file)
        CATALOG[pinned] = site.code_block(file, pinned)

    def register(self) -> list[str]:
        """Every version of every site block in the catalog (at start): the pinned ids."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT v.block_id, v.number, v.file_json, b.current FROM site_block_versions v "
                "JOIN site_blocks b ON b.block_id = v.block_id"
            ).fetchall()
        CURRENT.clear()
        for key in [
            key for key in CATALOG if split_pinned(key) or key.startswith(f"{site.DRAFT_LIBRARY}.")
        ]:
            del CATALOG[key]
        found = []
        for row in rows:
            try:
                file = read_file(row["file_json"])
            except ValueError:
                continue
            self.register_one(row["block_id"], int(row["number"]), file)
            found.append(pinned_id(row["block_id"], int(row["number"])))
            if int(row["number"]) == int(row["current"]):
                CURRENT[row["block_id"]] = pinned_id(row["block_id"], int(row["number"]))
        return sorted(found)

    def signature(self) -> tuple[Any, ...]:
        """What changes whenever a block or a version is saved or removed (``sync``)."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT (SELECT COUNT(*) FROM site_block_versions), "
                "(SELECT COUNT(*) FROM site_blocks), (SELECT MAX(updated_at) FROM site_blocks)"
            ).fetchone()
        return tuple(row)

    def sync(self) -> list[str]:
        """Add to this process's catalog the versions saved by another one (the engine runs in
        its own process): only adds and moves ``CURRENT``, so a run going on never misses a block."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT v.block_id, v.number, v.file_json, b.current FROM site_block_versions v "
                "JOIN site_blocks b ON b.block_id = v.block_id"
            ).fetchall()
        added = []
        # A block whose version in use is Link's own (no row of its own): the shipped one.
        for block_id in {row["block_id"] for row in rows} - {
            row["block_id"] for row in rows if int(row["number"]) == int(row["current"])
        }:
            CURRENT.pop(block_id, None)
        for row in rows:
            pinned = pinned_id(row["block_id"], int(row["number"]))
            if pinned not in CATALOG:
                try:
                    file = read_file(row["file_json"])
                except ValueError:
                    continue
                self.register_one(row["block_id"], int(row["number"]), file)
                added.append(pinned)
            if int(row["number"]) == int(row["current"]):
                CURRENT[row["block_id"]] = pinned
        return sorted(added)


__all__ = ["BlockStore"]
