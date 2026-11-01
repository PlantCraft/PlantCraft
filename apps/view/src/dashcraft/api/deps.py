"""Request dependencies: the runtime, the verified user, access checks and safe reads.

Every route but the public-link ones needs a PlantCraft token with access to
``dashcraft`` (``plantcraft_sdk.server.access``). Viewers open dashboards; editors
create, change, share and delete them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from plantcraft_sdk.asset_scope import limited
from plantcraft_sdk.auth import User
from plantcraft_sdk.server.access import Access, CurrentUser, runtime

from dashcraft.api.runtime import Runtime
from dashcraft.dashboards.folders import may_edit, may_see
from dashcraft.i18n import t

ACCESS = Access("Dashboards", demo_copy=True)
RuntimeDep = Annotated[Runtime, Depends(runtime)]
EditorUser = ACCESS.EditorUser
guarded = ACCESS.guarded


def editor_view(user: CurrentUser) -> User:
    """An editor, or a public demo visit: the visitor is shown the editors (``plantcraft_sdk.
    server.demo``), so the reads they make (pickers, templates, previews, versions) answer
    while every save stays refused by ``EditorUser``."""

    if user.demo is not None:
        return user
    return ACCESS.editor(user)


EditorView = Annotated[User, Depends(editor_view)]

__all__ = ["CurrentUser", "EditorUser", "EditorView", "RuntimeDep", "guarded"]


@dataclass
class Permissions:
    """What one person may see and change, folder by folder (``dashboards.folders``)."""

    username: str
    admin: bool
    editor: bool
    groups: set[str] = field(default_factory=set)
    folders: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _who(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "groups": self.groups,
            "admin": self.admin,
            "editor": self.editor,
        }

    def folder(self, folder_id: str | None) -> dict[str, Any] | None:
        """The folder, or None for General (and for a folder that no longer exists)."""

        return self.folders.get(folder_id or "")

    def _gone(self, folder_id: str | None) -> bool:
        # A folder that no longer exists keeps its dashboards for administrators only: they
        # were someone's restricted ones, not General's (the same rule as Documents' folders,
        # platform review I1, 2026-10-27).
        return bool(folder_id) and folder_id not in self.folders

    def sees_folder(self, folder_id: str | None) -> bool:
        if self._gone(folder_id):
            return self.admin
        return may_see(self.folder(folder_id), **self._who())

    def edits_folder(self, folder_id: str | None) -> bool:
        if self._gone(folder_id):
            return self.admin and self.editor
        return may_edit(self.folder(folder_id), **self._who())

    def sees(self, dashboard: dict[str, Any]) -> bool:
        return self.sees_folder(dashboard.get("folder_id"))

    def edits(self, dashboard: dict[str, Any]) -> bool:
        return not dashboard.get("builtin") and self.edits_folder(dashboard.get("folder_id"))


def whole_plant(user: User) -> None:
    """403 for a person who sees only part of the plant (PlantCraft's token claim ``assets``):
    a public link or a scheduled send reads with View's own token, past that part."""

    if limited(user):
        raise HTTPException(
            status_code=403,
            detail=t(
                "You see only part of the plant: public links and scheduled sends are set up "
                "by someone who sees all of it."
            ),
        )


def everyone_sees(rt: Runtime, folder_id: str | None) -> bool:
    """Whether everyone with access to View sees what ``folder_id`` files (General, or a folder
    naming no viewers): all a public link may show of an object it does not open itself."""

    if not folder_id:
        return True
    folder = rt.folders.get(folder_id)
    return folder is not None and not folder.get("viewers")


def permissions(rt: Runtime, user: User) -> Permissions:
    folders = {item["folder_id"]: item for item in rt.folders.list()}
    restricted = any(item.get("viewers") or item.get("editors") for item in folders.values())
    return Permissions(
        username=user.username,
        admin=user.is_admin,
        editor=user.can_edit,
        # Groups are read only when some folder names who may see or edit it.
        groups=rt.groups_of(user) if restricted and not user.is_admin else set(),
        folders=folders,
    )


def dashboard_or_404(rt: Runtime, dashboard_id: str, user: User | None = None) -> dict[str, Any]:
    """A dashboard by id; with ``user``, only one they may see (else "not found", so a folder
    kept for others does not even say what it holds)."""

    found = rt.dashboards.get(dashboard_id) if len(dashboard_id) <= 40 else None
    if found is not None and user is not None and not permissions(rt, user).sees(found):
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Dashboard not found."))
    return found


def editable_or_403(rt: Runtime, dashboard_id: str, user: User) -> dict[str, Any]:
    """A dashboard the person may change: seen, not kept by the suite, its folder editable."""

    found = dashboard_or_404(rt, dashboard_id, user)
    if found.get("builtin"):
        raise HTTPException(
            status_code=409, detail=t("This dashboard is kept by the suite: copy it to change it.")
        )
    if not permissions(rt, user).edits(found):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of its folder change this dashboard.")
        )
    return found
