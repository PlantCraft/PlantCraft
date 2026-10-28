"""What a stored alarm says, without the database: its configuration, who answers for it, its
ISA-18.2 status, and the ``Conflict`` a stale change raises. ``alarms.store`` keeps the rows;
the routers read them with these (PlantCraft ``docs/app-standard.md``, section 5)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

ALARM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
KEEP_DAYS = 400
_STORED = {
    "alarm_id",
    "state",
    "acked",
    "acked_at",
    "acked_by",
    "shelved_until",
    "shelved_by",
    "shelve_reason",
    "created_at",
    "created_by",
    "updated_at",
    "updated_by",
}


def slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:40] or "alarm"


def config_of(alarm: dict[str, Any]) -> dict[str, Any]:
    """The configuration part of a stored alarm (what ``AlarmDraft`` validates)."""

    return {key: value for key, value in alarm.items() if key not in _STORED and key != "status"}


def owner_of(alarm: dict[str, Any]) -> str | None:
    """Who answers for the alarm: its owner, else the person who created it."""

    owner = alarm.get("owner")
    if owner:
        return str(owner)
    creator = alarm.get("created_by")
    return f"user:{creator}" if creator else None


def status_of(alarm: dict[str, Any], now: datetime) -> str:
    """The ISA-18.2 state: out_of_service, shelved, unacked, acked, rtn_unacked or normal."""

    if not alarm.get("enabled", True) or not alarm.get("rule_enabled", True):
        return "out_of_service"
    until = alarm.get("shelved_until")
    if until:
        try:
            if datetime.fromisoformat(until) > now:
                return "shelved"
        except ValueError:
            pass
    active = bool((alarm.get("state") or {}).get("active"))
    # A notice needs no acknowledgement: it is active, then normal.
    acked = bool(alarm.get("acked", True)) or alarm.get("creates") == "notice"
    if active:
        return "acked" if acked else "unacked"
    return "normal" if acked else "rtn_unacked"


class Conflict(Exception):
    """The alarm changed since the person opened it."""
