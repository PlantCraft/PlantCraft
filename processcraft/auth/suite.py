"""The apps of the suite installed beside PlantCraft, and who may open them.

``PLANTCRAFT_APPS`` lists them as ``id=url`` pairs separated by commas,
optionally with a version: ``linkcraft=/link/@0.2.0,dashcraft=/dash/``. The ids
are the family's machine ids (``linkcraft``...). A person's applications list
may name an app by that id or by an id it had before (``cpm`` for ``linkcraft``),
so existing access keeps working.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from processcraft.auth.access import Access

LOGGER = logging.getLogger(__name__)
_ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")

APP_NAMES = {
    "processcraft": "PlantCraft",
    "linkcraft": "PlantCraft Analytics",
    "dashcraft": "PlantCraft View",
    "simcraft": "PlantCraft Simulator",
    "alarmcraft": "PlantCraft Alarms",
    "histcraft": "PlantCraft Historian",
    "modelcraft": "PlantCraft Models",
    "doccraft": "PlantCraft Documents",
}
# Suite app -> the ids it had before (the PlantCraft module it grew from, or the app it was
# renamed or merged from): people's access may still name them.
FORMER_IDS: dict[str, tuple[str, ...]] = {
    "linkcraft": ("cpmcraft", "cpm", "datacraft", "data_quality", "twincraft"),
    "dashcraft": ("trendcraft", "dashboards"),
    "simcraft": ("simulator",),
}


@dataclass(frozen=True)
class SuiteApp:
    id: str
    name: str
    url: str
    version: str | None = None
    # The asset types it works on (``[requires] asset_types`` of its app.toml); None when
    # PlantCraft has not seen its manifest (listed in PLANTCRAFT_APPS, or external).
    asset_types: tuple[str, ...] | None = None


def parse_apps(text: str | None) -> list[SuiteApp]:
    """``id=url[@version]`` entries separated by commas; malformed ones are skipped with a warning."""

    apps: dict[str, SuiteApp] = {}
    for entry in (text or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        app_id, _, target = entry.partition("=")
        app_id, target = app_id.strip().lower(), target.strip()
        url, version = target, None
        if "@" in target.rsplit("/", 1)[-1]:
            url, _, version = target.rpartition("@")
        if not _ID.match(app_id) or not (
            url.startswith("/") or url.startswith(("http://", "https://"))
        ):
            LOGGER.warning("PLANTCRAFT_APPS: ignoring %r (expected id=/url/).", entry)
            continue
        apps[app_id] = SuiteApp(app_id, APP_NAMES.get(app_id, app_id), url, version or None)
    return list(apps.values())


def suite_apps() -> list[SuiteApp]:
    return parse_apps(os.environ.get("PLANTCRAFT_APPS"))


def allows(access: Access, app_id: str) -> bool:
    return access.allows(app_id) or any(
        access.allows(former) for former in FORMER_IDS.get(app_id, ())
    )


def app_access(access: Access | None, apps: list[SuiteApp] | None = None) -> dict[str, str]:
    """``{app id: "editor" | "viewer"}`` for the apps this person may open, each with its role."""

    if access is None or not access.at_least("viewer"):
        return {}
    return {
        app.id: _role(access, app.id)
        for app in (suite_apps() if apps is None else apps)
        if allows(access, app.id)
    }


def _role(access: Access, app_id: str) -> str:
    """The person's role in the app; a role set under a former id still counts."""

    if not any(key == app_id for key, _ in access.app_roles):
        for former in FORMER_IDS.get(app_id, ()):
            if any(key == former for key, _ in access.app_roles):
                return access.app_role(former)
    return access.app_role(app_id)
