"""Who sees and who changes a folder's documents: the same rule as View's folders.

An empty list means everyone: everyone with access to Documents sees, every Documents editor
changes. Editors of a folder always see it, administrators see and change every folder, and
only Documents editors ever change anything. Documents outside every folder are in General,
everyone's. Groups live in PlantCraft; a folder keeps only their ids.

A person who sees only part of the plant (PlantCraft's token claim ``assets``, its
docs/asset-scope.md) sees a document about assets (those a person linked or confirmed) only when
one of them is in that part; a document about no asset is everyone's.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from plantcraft_sdk.asset_scope import EVERYTHING, AssetScope


def _matches(entries: Iterable[str], username: str, groups: set[str]) -> bool:
    for entry in entries:
        kind, _, name = entry.partition(":")
        if (kind == "user" and name == username) or (kind == "group" and name in groups):
            return True
    return False


@dataclass
class Permissions:
    username: str
    admin: bool
    editor: bool
    groups: set[str]
    folders: dict[str, dict[str, Any]] = field(default_factory=dict)
    scope: AssetScope = EVERYTHING

    def folder(self, folder_id: str | None) -> dict[str, Any] | None:
        return self.folders.get(folder_id or "")

    def _gone(self, folder_id: str | None) -> bool:
        # A folder that no longer exists keeps its documents for administrators only: they
        # were someone's restricted ones, not General's (the same rule as View's folders,
        # platform review I1, 2026-10-27).
        return bool(folder_id) and folder_id not in self.folders

    def edits_folder(self, folder_id: str | None) -> bool:
        if not self.editor:
            return False
        if self._gone(folder_id):
            return self.admin
        folder = self.folder(folder_id)
        if self.admin or folder is None or not folder.get("editors"):
            return True
        return _matches(folder["editors"], self.username, self.groups)

    def sees_folder(self, folder_id: str | None) -> bool:
        if self._gone(folder_id):
            return self.admin
        folder = self.folder(folder_id)
        if self.admin or folder is None or not folder.get("viewers"):
            return True
        if _matches(folder["viewers"], self.username, self.groups):
            return True
        return bool(folder.get("editors")) and self.edits_folder(folder_id)

    def visible_folders(self) -> set[str]:
        """The folder ids this person sees, General ("") included."""

        return {""} | {fid for fid in self.folders if self.sees_folder(fid)}

    def about(self, assets: Iterable[dict[str, Any]]) -> bool:
        """Whether the plant part allows a document linked to ``assets`` (``document_assets``
        rows): one about no confirmed asset, or about one the person sees."""

        return about(self.scope, assets)

    def sees_doc(self, doc: dict[str, Any]) -> bool:
        return self.sees_folder(doc.get("folder_id")) and self.about(doc.get("assets") or [])

    def docs(self, docs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Of documents read for the visible folders, those the plant part allows."""

        docs = list(docs)
        if self.scope.everything:
            return docs
        return [doc for doc in docs if self.about(doc.get("assets") or [])]


def about(scope: AssetScope, assets: Iterable[dict[str, Any]]) -> bool:
    if scope.everything:
        return True
    confirmed = [item["asset_id"] for item in assets if item.get("source") != "suggested"]
    return not confirmed or any(scope.asset(asset) for asset in confirmed)
