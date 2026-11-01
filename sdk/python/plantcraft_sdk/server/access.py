"""Request dependencies every app route uses: the runtime, the signed-in person, an editor, and
``guarded`` reads of PlantCraft.

::

    ACCESS = Access("Twin")
    CurrentUser = ACCESS.CurrentUser   # any person with access to the app
    EditorUser = ACCESS.EditorUser     # an editor (or admin) of the app

The app's runtime is ``request.app.state.runtime`` and must have a ``verifier``
(``plantcraft_sdk.auth.TokenVerifier``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import Depends, HTTPException, Request

from plantcraft_sdk.auth import User
from plantcraft_sdk.client import PlantCraftError, Unauthorized
from plantcraft_sdk.i18n import t
from plantcraft_sdk.server import demo_slots

T = TypeVar("T")


def runtime(request: Request) -> Any:
    """The app's runtime (``app.state.runtime``)."""

    return request.app.state.runtime


def current_user(request: Request) -> User:
    """The person (or service) the request's PlantCraft token names; 401/403 otherwise."""

    return request.app.state.runtime.verifier.dependency(request)


CurrentUser = Annotated[User, Depends(current_user)]


class Access:
    """The access checks of one app; ``label`` is its short name in messages ("Twin").

    ``demo_copy``: an isolated public demo visit saves, into its own copy of the app's data
    (``plantcraft_sdk.server.demo_slots``); the app has checked that nothing it saves leaves that
    copy (files on disk, other services)."""

    def __init__(self, label: str, *, demo_copy: bool = False):
        self.label = label
        self.demo_copy = demo_copy
        self.CurrentUser = CurrentUser
        self.EditorUser = Annotated[User, Depends(self.editor)]

    def editor(self, user: Annotated[User, Depends(current_user)]) -> User:
        if not user.can_edit and user.demo is not None and self.demo_copy and demo_slots.editable():
            # An isolated visit: what it saves stays in its own copy, deleted after the visit.
            return user
        if not user.can_edit and user.demo is not None:
            # A public demo shows its editors; saving is what it refuses.
            raise HTTPException(
                status_code=403,
                detail=t("This is a public demo: you can try everything, but nothing is saved."),
            )
        if not user.can_edit:
            raise HTTPException(
                status_code=403, detail=t("Your access to {app} is read-only.", app=self.label)
            )
        return user

    def guarded(self, read: Callable[[], T], *, service: bool) -> T:
        """Run a PlantCraft read; map its failures to answers a browser can act on.

        A refused *service* token is the app key's problem, not the person's: it is a 503 naming
        the fix, never a 401 that would send the person to sign in.
        """

        try:
            return read()
        except Unauthorized as exc:
            if service:
                raise HTTPException(
                    status_code=503,
                    detail=t(
                        "PlantCraft refused the app key of {app}. An admin creates a new one "
                        "in PlantCraft and sets PLANTCRAFT_APP_KEY for {app}.",
                        app=self.label,
                    ),
                ) from exc
            raise HTTPException(status_code=401, detail=str(exc.detail)) from exc
        except PlantCraftError as exc:
            status = exc.status_code if exc.status_code in (403, 404, 422) else 502
            raise HTTPException(status_code=status, detail=str(exc.detail)) from exc
