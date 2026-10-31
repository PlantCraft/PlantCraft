"""The PlantCraft kernel: one installation's scenario, stores, sources and asset tree.

``Platform`` holds what the central app serves to people and, through API v1,
to the apps of the suite: the scenario, the workspace (users, assets, events,
audit, app keys), the data sources with their history cache and the root of
the asset tree. Apps (Analytics, ...) run in their own containers and never
reach this object; they read it through ``/api/v1``.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from plantcraft.assets import asset_id_for
from plantcraft.config import DashboardScenario
from plantcraft.industrial_data.cache import build_cached_source
from plantcraft.industrial_data.derived import DerivedSeriesStore
from plantcraft.industrial_data.registry import SourceRegistry
from plantcraft.industrial_data.service import IndustrialData
from plantcraft.platform.workspace import Workspace
from plantcraft.refs import RefResolvers

logger = logging.getLogger(__name__)

# How long one signal catalog answers every request (another worker's change shows after it).
CATALOG_SECONDS = 2.0


@dataclass
class Platform:
    scenario: DashboardScenario
    workspace: Workspace
    source: Any
    data: IndustrialData
    root_asset_id: str
    sources: SourceRegistry
    refs: RefResolvers = field(default_factory=RefResolvers)
    # Derived series apps publish, when there is no Historian (``platform.datalayer``).
    derived: DerivedSeriesStore | None = None
    # Where signals and series are read: local, or Historian (``platform/datalayer``).
    datalayer: Any = None
    # The last signal catalog built: (what it was built from, when, the catalog).
    _catalog: tuple[tuple[Any, ...], float, Any] | None = field(default=None, repr=False)
    _catalog_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, scenario: DashboardScenario, *, issuer: Any = None) -> Platform:
        """``issuer`` signs PlantCraft's own tokens; with ``HISTCRAFT_URL`` set, reads go to
        Historian with them."""

        workspace = Workspace(scenario.storage.sqlite_path)
        # Reads go through the registry's router: each tag from the source that owns it.
        sources = SourceRegistry(
            workspace.db, scenario.source, build_cached_source(scenario.source, workspace.db)
        )
        # The installation itself is the root of the asset tree.
        root = asset_id_for(scenario.name)
        workspace.assets.save(
            root,
            name=scenario.display_name or scenario.name,
            kind="site",
            description=scenario.description,
            origin="platform",
        )
        platform = cls(
            scenario=scenario,
            workspace=workspace,
            source=sources.router,
            data=sources.primary_data,
            root_asset_id=root,
            sources=sources,
            derived=DerivedSeriesStore(workspace.db),
        )
        from plantcraft.platform.datalayer import build_datalayer

        platform.datalayer = build_datalayer(platform, issuer)
        platform._register_refs()
        platform._name_signals_with_source()
        return platform

    def _name_signals_with_source(self) -> None:
        """Signal ids carry their source (D2): bindings record it, stored refs are renamed once."""

        from plantcraft.platform.signals import rename_signal_refs, sync_binding_sources

        sync_binding_sources(self)
        rename_signal_refs(self)

    def signal_catalog(self) -> Any:
        """Every signal PlantCraft knows, by API v1 id (``platform.signals.SignalCatalog``)."""

        from plantcraft.platform.signals import signal_catalog

        # Built once for every request of the next CATALOG_SECONDS (scale review E14: each
        # list of 50,000 signals built it again); a write in this process to what it is built
        # from (routes, assets, derived series) builds it again at once.
        key = (
            self.sources.store.writes,
            type(self.workspace.assets).version,
            getattr(self.derived, "version", None),
        )
        with self._catalog_lock:
            cached = self._catalog
            now = time.monotonic()
            if cached is not None and cached[0] == key and now - cached[1] < CATALOG_SECONDS:
                return cached[2]
            catalog = signal_catalog(self)
            self._catalog = (key, now, catalog)
            return catalog

    def _register_refs(self) -> None:
        """The kinds the central app owns: assets, people and actions."""

        workspace = self.workspace

        def asset(asset_id: str) -> dict[str, Any] | None:
            item = workspace.assets.get(asset_id)
            if item is None:
                return None
            return {
                "title": item["name"],
                "href": f"/assets/{asset_id}",
                "status": None,
                "asset_kind": item["kind"],
            }

        def user(username: str) -> dict[str, Any] | None:
            item = workspace.users.get_user(username)
            if item is None:
                return None
            return {
                "title": item["display_name"],
                "href": f"/people/{username}",
                "status": None,
                "role": item.get("role"),
            }

        def group(group_id: str) -> dict[str, Any] | None:
            item = workspace.groups.get(group_id)
            if item is None:
                return None
            return {
                "title": item["name"],
                "href": f"/groups/{group_id}",
                "status": None,
                "group_kind": item["kind"],
            }

        def action(action_id: str) -> dict[str, Any] | None:
            item = workspace.actions.headline(int(action_id)) if action_id.isdigit() else None
            if item is None:
                return None
            return {
                "title": f"AC-{action_id} · {item['title']}",
                "href": f"/actions/{action_id}",
                "status": item["status"],
            }

        def run(item_id: str) -> dict[str, Any] | None:
            # run:<app>/<run id>, as the apps publish them (API v1 runs).
            app, _, run_id = item_id.partition("/")
            found = workspace.results.run(app, run_id) if run_id else None
            if found is None:
                return explained(f"run:{item_id}")
            return {
                "title": found["name"] or run_id,
                "href": found["url"],
                "status": found["status"],
                "app": app,
            }

        def explained(ref: str) -> dict[str, Any] | None:
            # Anything an app wrote a text about (algorithm:linkcraft/loop_health).
            found = workspace.knowledge.get(ref)
            if found is None:
                return None
            return {
                "title": found["title"],
                "href": found["url"],
                "status": None,
                "app": found["app"],
            }

        for kind, resolver in (
            ("asset", asset),
            ("user", user),
            ("group", group),
            ("action", action),
            ("run", run),
        ):
            self.refs.register(kind, resolver, owner="platform")
        self.refs.fallback = explained

    def sync_assets(self) -> None:
        """The scenario's loops in the asset tree (again after a map import or a source change)."""

        from plantcraft.platform.loops import sync_scenario_loops
        from plantcraft.platform.signals import sync_binding_sources

        try:
            sync_scenario_loops(self)
        except Exception:  # an offline source must not stop the start
            logger.exception("Placing the scenario's loops in the asset tree failed")
        # Routes may have moved a tag to another source: its bindings follow.
        sync_binding_sources(self)

    def data_end(self) -> Any:
        """Where "now" is for the data: the clock, or a recorded file's last sample."""

        import pandas as pd

        if self.scenario.source.type == "csv":
            last = getattr(self.source, "last_time", None)
            found = last() if callable(last) else None
            if found is not None:
                return found
            frame = self.source.read_window(1, self.scenario.analysis.resample_seconds)
            if not frame.empty:
                return frame.index.max()
        return pd.Timestamp.now(tz=self.scenario.source.timezone).tz_localize(None)

    def monitored_tags(self) -> list[str]:
        """Tags people added to the platform from any source, beyond the scenario's own list."""

        return self.sources.monitored_tags()

    def publish(self, kind: str, subject: str, **fields: Any) -> dict[str, Any]:
        return self.workspace.events.publish(kind, subject, **fields)

    def record_asset_change(
        self,
        kind: str,
        asset_id: str,
        actor: str,
        summary: str,
        payload: dict[str, Any],
        refs: list[str] | tuple[str, ...] = (),
    ) -> None:
        """One change to an asset in its history (who, when, what) and in the audit log."""

        self.workspace.audit.record(actor, kind, f"asset:{asset_id}", payload)
        try:
            self.publish(
                kind,
                f"asset:{asset_id}",
                source="platform",
                actor=actor,
                summary=summary[:600],
                payload=payload,
                refs=list(refs),
            )
        except ValueError:  # an id that is not a valid reference keeps its audit row only
            logger.info("Asset %s has no timeline; change kept in the audit log", asset_id)

    def record_attribute_changes(
        self, asset_id: str, actor: str, changes: list[dict[str, Any]]
    ) -> None:
        """The record of an asset changed: one history entry listing every value."""

        if not changes:
            return
        from plantcraft.i18n import t

        shown = "; ".join(
            f"{item['name']}: {_show(item['from'])} → {_show(item['to'])}" for item in changes
        )
        self.record_asset_change(
            "asset.attributes_changed",
            asset_id,
            actor,
            t("Record changed: {changes}", changes=shown),
            {"changes": changes},
        )


def _show(value: Any) -> str:
    return "—" if value is None else str(value)


__all__ = ["Platform", "Workspace"]
