"""Plant data through PlantCraft API v1: the ``PlantReader`` the engine reads with."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

import pandas as pd
from plantcraft_sdk.client import NotFound, PlantCraftError

from alarmcraft.i18n import t

ASSET_SECONDS = 60.0


class ApiReader:
    """Reads assets and series with one PlantCraft client (the app's or a person's).

    Assets are cached for a minute: a role rewired in PlantCraft reaches alarms within it.
    """

    def __init__(self, client: Any, *, cache: dict | None = None):
        self.client = client
        self._assets: dict[str, tuple[float, dict]] = {} if cache is None else cache
        self._lock = threading.Lock()

    def asset(self, asset_id: str) -> dict:
        now = time.monotonic()
        with self._lock:
            found = self._assets.get(asset_id)
            if found and now - found[0] < ASSET_SECONDS:
                return found[1]
        try:
            asset = self.client.asset(asset_id)
        except NotFound as exc:
            raise LookupError(t("Asset {asset} is not in PlantCraft.", asset=asset_id)) from exc
        except PlantCraftError as exc:
            raise LookupError(
                t("PlantCraft did not answer for asset {asset}: {why}", asset=asset_id, why=exc)
            ) from exc
        with self._lock:
            self._assets[asset_id] = (now, asset)
        return asset

    def read(
        self, signal_ids: list[str], start: datetime, end: datetime, step: float
    ) -> tuple[dict[str, pd.Series], dict[str, str]]:
        try:
            columns, errors = self.client.series_many_pandas(signal_ids, start, end, step)
        except PlantCraftError as exc:
            return {}, {signal: str(exc.detail or exc) for signal in signal_ids}
        return columns, {item["signal"]: str(item.get("detail") or "") for item in errors}


class AssetTree:
    """The whole asset tree, read once a minute: an alarm's area and the chain of assets above it.

    The area shown for an alarm is the alarm's own ``area`` when a person set one, else the top
    of its branch: the root asset, or the root's child when the root is the site itself.
    """

    def __init__(self, client: Any | None, *, cache: dict | None = None):
        self.client = client
        self._cache: dict = {} if cache is None else cache
        self._lock = threading.Lock()

    def assets(self) -> dict[str, dict]:
        now = time.monotonic()
        with self._lock:
            found = self._cache.get("tree")
            if found and now - found[0] < ASSET_SECONDS:
                return found[1]
        if self.client is None:
            return {}
        try:
            everything = {str(item.get("id")): item for item in self.client.assets()}
        except PlantCraftError:
            return found[1] if found else {}
        with self._lock:
            self._cache["tree"] = (now, everything)
        return everything

    def chain(self, asset_id: str | None) -> list[dict]:
        """The assets from the root down to ``asset_id`` (empty when it is unknown)."""

        assets = self.assets()
        found: list[dict] = []
        current = asset_id
        while current and current in assets and len(found) < 50:
            item = assets[current]
            if any(step is item for step in found):
                break
            found.append(item)
            current = item.get("parent_id")
        return list(reversed(found))

    def area_of(self, alarm: dict[str, Any]) -> tuple[list[str], dict | None]:
        """The chain of asset ids policies match on, and the area to show."""

        if alarm.get("area"):
            chain = self.chain(alarm["area"])
            return [str(item.get("id")) for item in chain], (chain[-1] if chain else None)
        chain = self.chain(alarm.get("asset_id"))
        ids = [str(item.get("id")) for item in chain]
        if not chain:
            return ids, None
        top = chain[0]
        if top.get("kind") == "site" and len(chain) > 1:
            top = chain[1]
        return ids, top


class Directory:
    """The platform's people and groups, read once a minute (owners, recipients, "My alarms")."""

    def __init__(self, client: Any | None, *, cache: dict | None = None):
        self.client = client
        self._cache: dict = {} if cache is None else cache
        self._lock = threading.Lock()

    def _read(self, name: str) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            found = self._cache.get(name)
            if found and now - found[0] < ASSET_SECONDS:
                return found[1]
        if self.client is None:
            return []
        try:
            items = list(getattr(self.client, name)())
        except PlantCraftError:
            # An older PlantCraft without people and groups: the alarms still work.
            return found[1] if found else []
        with self._lock:
            self._cache[name] = (now, items)
        return items

    def people(self) -> list[dict]:
        return self._read("people")

    def groups(self) -> list[dict]:
        return self._read("groups")

    def members(self) -> dict[str, list[str]]:
        return {str(group["id"]): list(group.get("members") or []) for group in self.groups()}


class Executions:
    """The suite's executions (PlantCraft ``GET /api/v1/schedules``, each with the assets it
    runs on), read once a minute: a rule over a Link execution covers its assets."""

    def __init__(self, client: Any | None, *, cache: dict | None = None):
        self.client = client
        self._cache: dict = {} if cache is None else cache
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            found = self._cache.get("schedules")
            if found and now - found[0] < ASSET_SECONDS:
                return found[1]
        if self.client is None:
            return []
        try:
            items = [dict(item) for item in self.client.schedules()]
        except PlantCraftError:
            return found[1] if found else []
        with self._lock:
            self._cache["schedules"] = (now, items)
        return items
