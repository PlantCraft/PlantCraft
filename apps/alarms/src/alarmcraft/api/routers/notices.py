"""Notifications: the silences that hold notifications back, what was sent to whom (and what the
limit per person held back), and the platform's people and groups for owners and recipients.
Who hears about an alarm is set in its rule (``notify``)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from alarmcraft.alarms.model import DISCIPLINES, PRIORITIES
from alarmcraft.alarms.notices import SilenceDraft
from alarmcraft.api.deps import CurrentUser, EditorUser, RuntimeDep
from alarmcraft.api.runtime import Runtime
from alarmcraft.api.scope import of_seen
from alarmcraft.i18n import t

router = APIRouter(prefix="/api", tags=["notifications"])


def _names(rt: Runtime, ids: list[str]) -> list[dict[str, Any]]:
    assets = rt.tree.assets()
    return [{"id": item, "name": (assets.get(item) or {}).get("name") or item} for item in ids]


def _silence(rt: Runtime, silence: dict[str, Any]) -> dict[str, Any]:
    now = rt.clock().isoformat()
    return {
        **silence,
        "areas_named": _names(rt, silence.get("areas") or []),
        "active": silence["starts_at"] <= now < silence["ends_at"],
    }


@router.get("/directory")
def directory(rt: RuntimeDep, _user: CurrentUser) -> dict[str, Any]:
    """The platform's people and groups (owners and recipients), the disciplines and priorities."""

    return {
        "people": rt.directory.people(),
        "groups": rt.directory.groups(),
        "disciplines": [{"id": key, "label": t(label)} for key, label in DISCIPLINES.items()],
        "priorities": [{"id": key, "label": t(label)} for key, label in PRIORITIES.items()],
    }


@router.get("/silences")
def silences(rt: RuntimeDep, _user: CurrentUser) -> list[dict[str, Any]]:
    """The silences in force and those of the last week."""

    return [_silence(rt, item) for item in rt.notices.silences(rt.clock(), include_ended=True)]


@router.get("/sent")
def sent(rt: RuntimeDep, user: CurrentUser) -> dict[str, Any]:
    """What went to whom (the outbox, newest first), and who reached the limit in the last hour."""

    names = {f"rule:{rule['rule_id']}": rule["name"] for rule in rt.rules.list()}
    rows = of_seen(rt.asset_scope(user), rt.alarms.list(), rt.notices.recent(300))
    for row in rows:
        row["rule_id"] = row["policy_id"][5:] if row["policy_id"].startswith("rule:") else None
        row["rule_name"] = names.get(row["policy_id"])
    since = (rt.clock() - timedelta(hours=1)).isoformat()
    return {
        "outbox": rows,
        "limited": rt.notices.limited(since),
        "limit_per_hour": rt.philosophy.get().per_person_hour,
        "inhibited": rt.notifier.inhibited,
        "error": rt.notifier.last_error,
        "service_key": rt.has_service_key,
    }


@router.post("/silences", status_code=201)
def add_silence(body: SilenceDraft, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    silence = rt.notices.add_silence(body, now=rt.clock(), by=user.username)
    rt.audit(
        user,
        "silence.created",
        str(silence["silence_id"]),
        {"until": silence["ends_at"], "reason": silence["reason"]},
    )
    return _silence(rt, silence)


@router.post("/silences/{silence_id}/end")
def end_silence(silence_id: int, rt: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    if silence_id < 1 or silence_id > 2**62:
        raise HTTPException(404, t("Silence not found."))
    ended = rt.notices.end_silence(silence_id, now=rt.clock(), by=user.username)
    if ended is None:
        raise HTTPException(404, t("Silence not found."))
    if ended.pop("changed"):
        rt.audit(user, "silence.ended", str(silence_id))
    return _silence(rt, ended)
