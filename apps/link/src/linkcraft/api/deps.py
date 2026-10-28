"""Request dependencies: the runtime, the verified user and the access checks.

Every route needs a valid PlantCraft token with access to ``linkcraft``
(``plantcraft_sdk.server.access``). Viewers read; editors change loops, algorithms,
runs and schedules; admins (PlantCraft level ``admin``) also change the
monitoring round and method defaults.
"""

from __future__ import annotations

from typing import Annotated, Any

import pandas as pd
from fastapi import Depends, HTTPException
from plantcraft_sdk.auth import User
from plantcraft_sdk.server.access import Access, CurrentUser, runtime

from linkcraft.api.runtime import Runtime
from linkcraft.i18n import t

ACCESS = Access("Link")
RuntimeDep = Annotated[Runtime, Depends(runtime)]
EditorUser = ACCESS.EditorUser


def admin(user: CurrentUser) -> User:
    if not (user.can_edit and user.is_admin):
        raise HTTPException(status_code=403, detail=t("Only administrators can do this."))
    return user


AdminUser = Annotated[User, Depends(admin)]


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def frame_rows(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    """Loop samples as plot rows, thinned evenly to at most ``limit`` points."""

    if frame is None or frame.empty:
        return []
    if len(frame) > limit:
        frame = frame.iloc[:: max(1, len(frame) // limit + 1)]
    columns = [
        column
        for column in ("timestamp", "pv", "sp", "op", "mode", "secondary")
        if column in frame.columns
    ]
    return [
        {column: clean_value(row[column]) for column in columns}
        for row in frame[columns].to_dict("records")
    ]
