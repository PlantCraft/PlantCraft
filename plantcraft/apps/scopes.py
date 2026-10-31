"""What each app's token may do in API v1: its ``[permissions]``, held to every route.

Where an app's permissions come from (scale review E4):

- **An app installed from a package** (the Apps page, the catalog, ``install.sh --add``): the
  permissions of its signed manifest, the list the administrator saw before the install.
- **An external app** (registered by its address): the permissions the administrator granted
  when registering it, even none (``manifest.permissions_granted``); one registered before
  PlantCraft 0.5 granted nothing yet, so it is held to what it declares itself, and is
  unrestricted until it does.
- **A suite app** (in the suite's own bundle, ``PLANTCRAFT_APPS``): the permissions of the
  ``app.toml`` inside its image, which the signed ``release.json`` of the installed bundle pins
  (``plantcraft.apps.release``, security audit 2026-10-26). What the app declares when it
  starts (``PUT /api/v1/contributions``) may only narrow them: a suite app cannot grant itself
  more. Where no bundle pins them (a development checkout), what it declares; unrestricted until
  it sends them (an app before SDK 0.42).

``PLANTCRAFT_APP_PERMISSIONS=audit`` only logs what would be refused (to try a new app).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from plantcraft_sdk.scopes import PERMISSIONS, required

LOGGER = logging.getLogger(__name__)
PACKAGED = {"package", "catalog"}
CACHE_SECONDS = 10.0


def _mode() -> str:
    return (os.environ.get("PLANTCRAFT_APP_PERMISSIONS") or "enforce").strip().lower()


def enforcing() -> bool:
    return _mode() != "audit"


def strict() -> bool:
    """An app with no permissions known is held to none (default: not held until it declares)."""

    return _mode() == "strict"


class AppScopes:
    """Each app's granted permissions (``read.signals`` …), or None for an app not held yet."""

    def __init__(
        self,
        installed: Any,
        contributions: Any,
        pinned: Callable[[], Any] | None = None,
    ):
        self.installed = installed
        self.contributions = contributions
        # {app id: [permission, …]} of the installed release (release.json), or None.
        self.pinned = pinned or (lambda: None)
        self._cache: dict[str, tuple[float, set[str] | None]] = {}

    def granted(self, app_id: str) -> set[str] | None:
        now = time.monotonic()
        cached = self._cache.get(app_id)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        found = self._granted(app_id)
        self._cache[app_id] = (now, found)
        return found

    def forget(self, app_id: str | None = None) -> None:
        if app_id is None:
            self._cache.clear()
        else:
            self._cache.pop(app_id, None)

    def _granted(self, app_id: str) -> set[str] | None:
        row = self.installed.get(app_id)
        if row is not None and row.get("origin") in PACKAGED:
            return _known(row.get("permissions"))
        if row is not None and row.get("origin") == "external":
            granted = (row.get("manifest") or {}).get("permissions_granted")
            if granted or row.get("permissions"):
                return _known(row.get("permissions"))
        declared = (self.contributions.get(app_id) or {}).get("permissions")
        pins = self._pins().get(app_id)
        if pins is not None:
            return _known(pins) if declared is None else _known(pins) & _known(declared)
        return None if declared is None else _known(declared)

    def _pins(self) -> dict[str, Any]:
        try:
            found = self.pinned()
        except Exception:  # an unreadable status file pins nothing
            LOGGER.warning("App permissions: the release's pinned permissions cannot be read")
            return {}
        return found if isinstance(found, dict) else {}

    def refusal(
        self, app_id: str, method: str, route: str, key_scopes: list[str] | None = None
    ) -> str | None:
        """Why the app's token may not use this route, or None when it may. ``key_scopes``: the
        scopes of the key the token came from (None: the key holds all of the app's)."""

        known, scope = required(method, route)
        if not known:
            reason = f"{method} {route} is not open to an app's token"
        elif scope is None:
            return None
        else:
            granted = self.granted(app_id)
            if granted is None and strict():
                granted = set()
            if granted is not None and scope not in granted:
                reason = f"{app_id} did not ask for {scope} in its app.toml [permissions]"
            elif key_scopes is not None and scope not in _known(key_scopes):
                reason = f"this key of {app_id} does not hold {scope}"
            else:
                return None
        if not enforcing():
            LOGGER.warning("App permissions (audit only): %s", reason)
            return None
        return reason


def _known(items: Any) -> set[str]:
    return {str(item) for item in items or [] if str(item) in PERMISSIONS}


__all__ = ["AppScopes", "enforcing", "strict"]
