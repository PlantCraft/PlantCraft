"""The events PlantCraft itself writes, declared like an app's (``plantcraft_sdk.events``).

``GET /api/v1/events/catalog`` answers this first, then each app's. The activity events
(an asset changed, an action was created) are what the asset page draws as its timeline;
the ``processcraft.*`` ones are the suite watch's incidents (``processcraft.watch``), written as
events so Alarms can judge them with everything else.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.events import EventSpec

PLATFORM_APP = "processcraft"
# An app went over its hourly budget of events (``PLANTCRAFT_EVENT_HOURLY_LIMIT``).
FLOOD_KIND = f"{PLATFORM_APP}.events.flood"

# Kinds written before apps declared catalogs carry no app prefix; they keep their names.
ACTIVITY: list[dict[str, Any]] = [
    {"name": "asset.attributes_changed", "title": "Asset record changed", "category": "user"},
    {"name": "asset.relation_added", "title": "Asset relation added", "category": "user"},
    {"name": "asset.relation_removed", "title": "Asset relation removed", "category": "user"},
    {"name": "asset.signal_bound", "title": "Signal bound to an asset", "category": "user"},
    {"name": "asset.signal_unbound", "title": "Signal unbound from an asset", "category": "user"},
    {"name": "assets.imported", "title": "Assets imported", "category": "user"},
    {"name": "map.imported", "title": "Plant map imported", "category": "user"},
    {"name": "action.created", "title": "Action created", "category": "user"},
    {"name": "action.status_changed", "title": "Action status changed", "category": "user"},
]

# The suite watch's checks (processcraft.watch), each an interval: start when the watch opens
# the incident, end when it closes. The watch already tells the administrators in "Suite
# health" (it speaks even when Alarms is the app down), so these rules are suggested, off: an
# administrator who wants them as alarms too switches them on in Alarms.
WATCH_EVENTS: dict[str, str] = {
    "service": "service.down",
    "queue": "queue.stuck",
    "disk": "disk.low",
    "disk_trend": "disk.filling",
    "backup": "backup.missing",
    "drill": "drill.failed",
    "installer": "installer.silent",
    "docker": "docker.down",
    "cert": "certificate.expiring",
}


def _watch(name: str, title: str, description: str, severity: str, minutes: int = 5) -> dict:
    return {
        "name": name,
        "title": title,
        "description": description,
        "severity": severity,
        "phase": "interval",
        "payload": {"check": "The watch's check", "detail": "What the watch saw"},
        "rule": {"when": "open", "minutes": minutes, "priority": "high", "notify": "admins"},
    }


SYSTEM: list[dict[str, Any]] = [
    _watch(
        "service.down",
        "Service down",
        "A service of the suite (an app, the Historian's collector) stopped, restarts or "
        "fails its health check; ends when it is healthy again.",
        "critical",
    ),
    _watch(
        "queue.stuck",
        "Work queue not draining",
        "An app's queue (Link's executions, Models' simulations) has waited over 30 minutes.",
        "warning",
    ),
    _watch("disk.low", "Disk almost full", "Under 10 % of the disk is free.", "critical", 1),
    _watch(
        "disk.filling",
        "Disk fills within 30 days",
        "At the rate of the last 7 days the disk fills in under 30 days.",
        "warning",
        60,
    ),
    _watch(
        "backup.missing",
        "No recent backup",
        "The last good backup is over 26 hours old.",
        "critical",
        1,
    ),
    _watch("drill.failed", "Restore drill failed", "The last restore drill failed.", "warning", 1),
    _watch(
        "installer.silent",
        "Installer silent",
        "The installer stopped writing the suite's status for 3 minutes.",
        "critical",
    ),
    _watch(
        "docker.down", "Docker not answering", "Docker does not answer the installer.", "critical"
    ),
    _watch(
        "certificate.expiring",
        "Certificate expiring",
        "A certificate of the suite (HTTPS, the Historian's OPC UA) expires in under 30 days or "
        "has expired; ends when it is renewed.",
        "warning",
        1,
    ),
    {
        "name": "events.flood",
        "title": "An app wrote too many events",
        "description": "An app wrote over its hourly budget of events (1,000 by default); the "
        "rest of the hour was refused. Apps publish when something changes, never to repeat "
        "that it is still the same.",
        "severity": "warning",
        "payload": {"app": "The app", "limit": "Events allowed per hour"},
    },
    {
        "name": "update.finished",
        "title": "Update finished",
        "description": "The suite was updated, rolled back, or an update failed and went back; "
        "severity ok, info or critical.",
        "severity": "info",
        "payload": {"state": "ok, returned or rolled-back", "version": "The version"},
    },
]


def platform_specs() -> list[EventSpec]:
    """PlantCraft's declared events: the activity ones by their bare names, the system ones as
    ``processcraft.<name>``."""

    specs = [EventSpec.model_validate({"severity": "info", **item}) for item in ACTIVITY]
    specs += [EventSpec.model_validate({"category": "system", **item}) for item in SYSTEM]
    return specs


def platform_catalog() -> list[dict[str, Any]]:
    """The catalog entries as ``GET /api/v1/events/catalog`` lists them (``kind`` added)."""

    activity = {item["name"] for item in ACTIVITY}
    out = []
    for spec in platform_specs():
        body = spec.model_dump(mode="json", exclude_none=True)
        kind = spec.name if spec.name in activity else f"{PLATFORM_APP}.{spec.name}"
        out.append({"kind": kind, **body})
    return out


__all__ = ["FLOOD_KIND", "PLATFORM_APP", "WATCH_EVENTS", "platform_catalog", "platform_specs"]
