"""Request dependencies: the runtime, the verified user, access checks and safe reads.

Every route needs a PlantCraft token with access to ``alarmcraft``
(``plantcraft_sdk.server.access``). Viewers see the alarm summary, the journal and performance;
editors acknowledge and shelve alarms and create, change and delete them.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from plantcraft_sdk.server.access import Access, CurrentUser, runtime

from alarmcraft.api.runtime import Runtime
from alarmcraft.i18n import t

ACCESS = Access("Alarms")
RuntimeDep = Annotated[Runtime, Depends(runtime)]
EditorUser = ACCESS.EditorUser
guarded = ACCESS.guarded

__all__ = ["CurrentUser", "EditorUser", "RuntimeDep", "guarded"]


def alarm_or_404(rt: Runtime, alarm_id: str, user: Any = None) -> dict[str, Any]:
    """The alarm; with ``user``, only one on the part of the plant they see."""

    from alarmcraft.api.scope import sees_alarm

    found = rt.alarms.get(alarm_id) if len(alarm_id) <= 63 else None
    if found is not None and user is not None and not sees_alarm(rt.asset_scope(user), found):
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail=t("Alarm not found."))
    return found
