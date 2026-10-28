"""Request dependencies: the runtime, the verified user, access checks and safe reads.

Every route needs a PlantCraft token with access to ``doccraft``
(``plantcraft_sdk.server.access``). Viewers read and search the documents of the folders they
see; editors send and change them in the folders they edit.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from plantcraft_sdk.auth import User
from plantcraft_sdk.server.access import Access, CurrentUser, runtime

from doccraft.api.runtime import Runtime
from doccraft.i18n import t

ACCESS = Access("Documents")
RuntimeDep = Annotated[Runtime, Depends(runtime)]
EditorUser = ACCESS.EditorUser
guarded = ACCESS.guarded

__all__ = ["CurrentUser", "EditorUser", "RuntimeDep", "guarded"]


def document_or_404(rt: Runtime, doc_id: str, user: User) -> dict[str, Any]:
    """A document the person may see; else "not found", so a closed folder says nothing."""

    found = rt.store.document(doc_id) if len(doc_id) <= 40 else None
    if found is not None and not rt.permissions(user).sees_doc(found):
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Document not found."))
    return found


def editable_or_403(rt: Runtime, doc_id: str, user: User) -> dict[str, Any]:
    found = document_or_404(rt, doc_id, user)
    if not rt.permissions(user).edits_folder(found["folder_id"]):
        raise HTTPException(
            status_code=403, detail=t("Only the editors of its folder change this document.")
        )
    return found
