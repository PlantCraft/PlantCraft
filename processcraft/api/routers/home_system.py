"""HTTP routes: the "System" widget of PlantCraft's Overview (/admin): is the installation healthy?

A few facts read from what the suite watch, the Backups page and the Updates page already keep
(``rt.watch.overview()``, ``rt.operations.overview()``): nothing is measured or asked here. The
disk, the backups and who signed in stay with the administrators, as on the System health page
(``/api/operations/status``); everyone else sees the version and whether the services run.
Times are UTC; the page shows them on the person's clock.
"""

from __future__ import annotations

import shutil
from datetime import datetime, time
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from processcraft.api.deps import CurrentUser, Runtime, is_admin
from processcraft.api.routers.home import _version
from processcraft.api.routers.operations import STATUS_CHECKS
from processcraft.config import plant_timezone
from processcraft.db import utc_text
from processcraft.watch import DISK_LOW_PCT, DISK_OK_PCT

router = APIRouter()

# Backups set aside by a restore are not backups the schedule made.
SET_ASIDE = frozenset({"aside", "returned"})


def _disk(rt: Any, seen: dict[str, Any], checks: dict[str, Any], open_keys: set[str]):
    """Free disk with its state at the suite watch's thresholds: alarm while its disk check is
    bad (under ``DISK_LOW_PCT`` %), warning when the disk fills within a month (its forecast) or
    nears the limit. Without the installer's metrics, the data folder's own disk."""

    disk = (seen.get("metrics") or {}).get("disk") or None
    if not disk:
        try:
            usage = shutil.disk_usage(Path(rt.scenario.storage.sqlite_path).parent)
        except OSError:
            return None
        disk = {
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "free_pct": round(100 * usage.free / usage.total, 1) if usage.total else None,
        }
    free = disk.get("free_pct")
    low = isinstance(free, (int, float)) and free < DISK_LOW_PCT
    near = isinstance(free, (int, float)) and free < DISK_OK_PCT
    if (checks.get("disk") or {}).get("bad") or "disk" in open_keys or low:
        state = "alarm"
    elif (checks.get("disk_trend") or {}).get("bad") or "disk_trend" in open_keys or near:
        state = "warning"
    else:
        state = "ok" if isinstance(free, (int, float)) else "unknown"
    forecast = seen.get("disk_forecast") or {}
    return {
        "free_bytes": disk.get("free_bytes"),
        "free_pct": free,
        "days_left": forecast.get("days_left"),
        "state": state,
    }


def _backup(backups: list[dict[str, Any]], checks: dict[str, Any]) -> dict[str, Any] | None:
    """The newest backup and how it went; a good one older than the watch allows is a warning."""

    made = [item for item in backups if item.get("created_at")]
    made = [item for item in made if item.get("state") not in SET_ASIDE]
    if not made:
        return None
    newest = max(made, key=lambda item: str(item["created_at"]))
    if newest.get("state") == "failed":
        state = "alarm"
    elif newest.get("state") == "ok":
        state = "warning" if (checks.get("backup") or {}).get("bad") else "ok"
    else:
        state = "unknown"
    return {"name": newest.get("name"), "at": newest["created_at"], "state": state}


def _today_start() -> str:
    """Midnight where the plant is, as a UTC time ("today" begins there)."""

    zone = plant_timezone()
    return utc_text(datetime.combine(datetime.now(zone).date(), time.min, tzinfo=zone))


@router.get("/api/home/system")
def system(user: CurrentUser, rt: Runtime) -> dict[str, Any]:
    """The installation at a glance: open problems, services, version and, for administrators,
    the free disk, the last backup and how many people signed in today."""

    seen = rt.watch.overview()
    admin = is_admin(rt, user)
    checks = {item.get("key"): item for item in seen.get("checks") or []}
    incidents = seen.get("open") or []
    open_keys = {str(item.get("check_key") or "") for item in incidents}
    # What the System health page shows this person: everything for an administrator.
    shown = open_keys if admin else {key for key in open_keys if key.startswith(STATUS_CHECKS)}
    services = (seen.get("metrics") or {}).get("services") or []
    running = [
        item for item in services
        if item.get("state") == "running" and item.get("health") != "unhealthy"
    ]  # fmt: skip
    operations = rt.operations.overview()
    release = (operations.get("release") or {}).get("version")
    update = operations.get("update") or None
    body: dict[str, Any] = {
        "admin": admin,
        "watching": bool(seen.get("watching")),
        "open": len(shown),
        "services": {"running": len(running), "total": len(services)} if services else None,
        "version": release or _version(),
        "update": (
            {key: update.get(key) for key in ("from", "to", "state", "at")} if update else None
        ),
    }
    if admin:
        body["disk"] = _disk(rt, seen, checks, open_keys)
        body["backup"] = _backup(operations.get("backups") or [], checks)
        body["signed_in_today"] = rt.workspace.audit.signed_in(_today_start())
    return body
