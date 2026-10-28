"""Folders a site makes for an app's own objects (Link round 9 D14, Models round 9 M5).

Every app that lists objects people make (Link's blocks, algorithms and schedules; Models'
models, blocks and studies) keeps them in folders the same way, so this lives once here:

- ``FolderStore``: ``folders`` holds one row per folder (its kind, its name, who made it) and
  ``folder_items`` where each object sits, with who put it there and when. An object is put in
  a folder when it is made and moved only by a deliberate Move to folder, so nothing wanders.
- ``folders_router``: ``GET /api/folders/<kind>`` lists the kind's folders and where each object
  sits; editors make, rename and delete (empty) folders, and
  ``PUT /api/folders/<kind>/items/<id>`` moves one object (``""`` takes it out).

The app says which kinds it has and whether an object exists (``exists``); the interface is
``@plantcraft/ui``'s ``FolderColumn``, ``FolderField`` and ``FolderPlaceLine``.
"""

# No ``from __future__ import annotations``: FastAPI reads the route functions' annotations, and
# the editor dependency is the app's own object, known only when the router is made.

import re
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from plantcraft_sdk.i18n import t
from plantcraft_sdk.server.access import CurrentUser, runtime
from plantcraft_sdk.server.store import Store


class FolderStore(Store):
    """The site's folders for an app's ``kinds`` of objects."""

    KINDS: tuple[str, ...] = ()
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS folders (
        folder_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS folders_kind_name ON folders (kind, name COLLATE NOCASE);
    CREATE TABLE IF NOT EXISTS folder_items (
        kind TEXT NOT NULL,
        item_id TEXT NOT NULL,
        folder_id TEXT NOT NULL REFERENCES folders (folder_id) ON DELETE CASCADE,
        moved_by TEXT NOT NULL DEFAULT '',
        moved_at TEXT NOT NULL,
        PRIMARY KEY (kind, item_id)
    );
    """

    def __init__(self, db: Any, kinds: tuple[str, ...] | None = None):
        super().__init__(db)
        if kinds is not None:
            self.KINDS = tuple(kinds)

    def list(self, kind: str) -> list[dict[str, Any]]:
        """The kind's folders by name, each with how many objects it holds."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT f.*, (SELECT COUNT(*) FROM folder_items i WHERE i.folder_id = f.folder_id)"
                " AS count FROM folders f WHERE f.kind = ? ORDER BY f.name COLLATE NOCASE",
                (kind,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, folder_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM folders WHERE folder_id = ?", (folder_id,)
            ).fetchone()
        return dict(row) if row else None

    def create(self, kind: str, name: str, *, by: str) -> dict[str, Any]:
        name = name.strip()
        if kind not in self.KINDS:
            raise ValueError(t("Unknown kind of folder: {kind}.", kind=kind))
        if not name:
            raise ValueError(t("Give the folder a name."))
        if any(item["name"].lower() == name.lower() for item in self.list(kind)):
            raise ValueError(t("There is already a folder named {name}.", name=name))
        folder_id = uuid.uuid4().hex[:12]
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO folders (folder_id, kind, name, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (folder_id, kind, name, by, self._now()),
            )
        return {**(self.get(folder_id) or {}), "count": 0}

    def rename(self, folder_id: str, name: str) -> dict[str, Any]:
        found = self.get(folder_id)
        name = name.strip()
        if found is None:
            raise KeyError(folder_id)
        if not name:
            raise ValueError(t("Give the folder a name."))
        if any(
            item["name"].lower() == name.lower() and item["folder_id"] != folder_id
            for item in self.list(found["kind"])
        ):
            raise ValueError(t("There is already a folder named {name}.", name=name))
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE folders SET name = ? WHERE folder_id = ?", (name, folder_id))
        return self.get(folder_id) or {}

    def delete(self, folder_id: str) -> None:
        """Delete an empty folder (a full one says so: its objects are moved out first)."""

        with self._lock, self._connect() as connection:
            held = connection.execute(
                "SELECT COUNT(*) FROM folder_items WHERE folder_id = ?", (folder_id,)
            ).fetchone()[0]
            if held:
                raise ValueError(t("Move what is in the folder out of it first."))
            connection.execute("DELETE FROM folders WHERE folder_id = ?", (folder_id,))

    def items(self, kind: str) -> dict[str, dict[str, Any]]:
        """Where each object of the kind sits: item id -> folder id, who moved it and when."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT item_id, folder_id, moved_by, moved_at FROM folder_items WHERE kind = ?",
                (kind,),
            ).fetchall()
        return {row["item_id"]: dict(row) for row in rows}

    def place(self, kind: str, item_id: str) -> dict[str, Any] | None:
        return self.items(kind).get(item_id)

    def move(self, kind: str, item_id: str, folder_id: str, *, by: str) -> dict[str, Any] | None:
        """Put an object in a folder of its kind (``""`` takes it out of any); where it is now."""

        with self._lock, self._connect() as connection:
            if not folder_id:
                connection.execute(
                    "DELETE FROM folder_items WHERE kind = ? AND item_id = ?", (kind, item_id)
                )
                return None
            folder = self.get(folder_id)
            if folder is None or folder["kind"] != kind:
                raise ValueError(t("No such folder for this kind of object."))
            connection.execute(
                "INSERT INTO folder_items (kind, item_id, folder_id, moved_by, moved_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (kind, item_id) DO UPDATE SET "
                "folder_id = excluded.folder_id, moved_by = excluded.moved_by, "
                "moved_at = excluded.moved_at",
                (kind, item_id, folder_id, by, self._now()),
            )
        return self.place(kind, item_id)

    def forget(self, kind: str, item_id: str) -> None:
        """An object deleted leaves its folder."""

        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM folder_items WHERE kind = ? AND item_id = ?", (kind, item_id)
            )


class FolderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class MovePayload(BaseModel):
    folder_id: str = Field(default="", max_length=40)


def folders_router(
    kinds: tuple[str, ...],
    *,
    editor: Any,
    exists: Callable[[Any, str, str], bool],
    store: Callable[[Any], FolderStore] = lambda rt: rt.folders,
    prefix: str = "/api/folders",
) -> APIRouter:
    """The folders' routes for an app: ``editor`` is its editors' dependency
    (``Access.EditorUser``), ``exists(runtime, kind, item_id)`` whether an object may be moved
    (an app's shipped objects stay out of folders), ``store(runtime)`` its ``FolderStore``."""

    router = APIRouter(prefix=prefix)
    kind_path = Annotated[str, Path(pattern="^(" + "|".join(map(re.escape, kinds)) + ")$")]

    def by(user: Any) -> str:
        return getattr(user, "name", "") or getattr(user, "username", "")

    def audit(request: Request, user: Any, action: str, subject: str, detail: Any) -> None:
        runtime(request).audit(user, action, subject, detail)

    @router.get("/{kind}")
    def folders(kind: kind_path, user: CurrentUser, request: Request) -> dict[str, Any]:
        """The kind's folders by name, with their counts, and where each object sits."""

        found = store(runtime(request))
        return {"folders": found.list(kind), "items": found.items(kind)}

    @router.post("/{kind}", status_code=201)
    def create_folder(
        kind: kind_path, payload: FolderPayload, user: editor, request: Request
    ) -> dict[str, Any]:
        try:
            made = store(runtime(request)).create(kind, payload.name, by=by(user))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        audit(request, user, "folder.created", f"folder:{made['folder_id']}", {"kind": kind})
        return made

    @router.patch("/{kind}/{folder_id}")
    def rename_folder(
        kind: kind_path, folder_id: str, payload: FolderPayload, user: editor, request: Request
    ) -> dict[str, Any]:
        found = store(runtime(request))
        folder = found.get(folder_id)
        if folder is None or folder["kind"] != kind:
            raise HTTPException(status_code=404, detail=t("Folder not found."))
        try:
            return found.rename(folder_id, payload.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/{kind}/{folder_id}", status_code=204)
    def delete_folder(kind: kind_path, folder_id: str, user: editor, request: Request) -> None:
        found = store(runtime(request))
        folder = found.get(folder_id)
        if folder is None or folder["kind"] != kind:
            raise HTTPException(status_code=404, detail=t("Folder not found."))
        try:
            found.delete(folder_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit(request, user, "folder.deleted", f"folder:{folder_id}", {"kind": kind})

    @router.put("/{kind}/items/{item_id:path}")
    def move(
        kind: kind_path, item_id: str, payload: MovePayload, user: editor, request: Request
    ) -> dict[str, Any]:
        """Move one object to a folder (``""``: out of any); where it sits now."""

        rt = runtime(request)
        if not exists(rt, kind, item_id):
            raise HTTPException(status_code=404, detail=t("Nothing to move: {id}.", id=item_id))
        try:
            place = store(rt).move(kind, item_id, payload.folder_id, by=by(user))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        audit(
            request,
            user,
            "folder.moved",
            f"{kind}:{item_id}",
            {"folder_id": payload.folder_id or None},
        )
        return {"kind": kind, "item_id": item_id, "place": place}

    return router


__all__ = ["FolderPayload", "FolderStore", "MovePayload", "folders_router"]
