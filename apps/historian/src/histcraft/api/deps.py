"""Request dependencies: the runtime, the verified user and the access checks.

Every route needs a valid PlantCraft token with access to ``histcraft``
(``plantcraft_sdk.server.access``). Viewers (and PlantCraft itself, reading data for the
apps) read; editors add, change and remove points; admins also manage sources and settings.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException
from plantcraft_sdk.asset_scope import AssetScope
from plantcraft_sdk.auth import User
from plantcraft_sdk.server.access import CurrentUser, current_user, runtime

from histcraft.api.runtime import Runtime
from histcraft.db import read_timeout
from histcraft.i18n import t

RuntimeDep = Annotated[Runtime, Depends(runtime)]


def editor(user: CurrentUser) -> User:
    # PlantCraft's own service token reads for the apps; it never writes here.
    if not user.can_edit or user.is_service:
        raise HTTPException(status_code=403, detail=t("Your access to Historian is read-only."))
    return user


def admin(user: Annotated[User, Depends(editor)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail=t("Only administrators can do this."))
    return user


Route = TypeVar("Route", bound=Callable[..., Any])


def time_limited(route: Route) -> Route:
    """A read route whose database statements stop after ``HISTCRAFT_QUERY_TIMEOUT`` (504):
    a single huge read (a notebook, a script, the assistant) never holds the database."""

    signature = inspect.signature(route)

    @wraps(route)
    def limited(*args: Any, **kwargs: Any) -> Any:
        runtime: Runtime = signature.bind_partial(*args, **kwargs).arguments["runtime"]
        with read_timeout(runtime.settings.query_timeout):
            return route(*args, **kwargs)

    return limited  # type: ignore[return-value]


def asset_scope(user: CurrentUser, runtime: RuntimeDep) -> AssetScope:
    """The part of the plant the caller sees (PlantCraft's token claim ``assets``)."""

    return runtime.asset_scope(user)


def in_scope(scope: AssetScope, signal_id: str) -> None:
    """404 for a signal outside the caller's part of the plant, as for one that is not here."""

    if not scope.signal(signal_id):
        raise HTTPException(status_code=404, detail=t("Signal {id} not found.", id=signal_id))


EditorUser = Annotated[User, Depends(editor)]
AdminUser = Annotated[User, Depends(admin)]
Scope = Annotated[AssetScope, Depends(asset_scope)]

__all__ = [
    "AdminUser",
    "CurrentUser",
    "EditorUser",
    "RuntimeDep",
    "Scope",
    "current_user",
    "in_scope",
    "time_limited",
]
