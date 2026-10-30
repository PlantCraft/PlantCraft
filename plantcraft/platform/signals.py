"""Signal ids of API v1: ``<source id>:<tag>`` (``docs/app-standard.md``, decision D2).

Inside PlantCraft a signal is still its tag: each tag is read from the one
source that owns it (``SourceRegistry.source_of``: its route, else the
scenario's source, ``PRIMARY``). Toward the apps a signal is named with that
source, ``scenario:FIC-101.PV`` or ``pi:Unit 2\\FIC 101.PV``, so two sources
may one day hold the same tag without their ids colliding.

``SignalCatalog`` is every signal PlantCraft knows, by id, and how an id given
by an app finds its signal: the id itself, or (until API v1 is frozen) a bare
tag that exactly one source has. A bare tag held by two sources finds nothing
and the error names both ids.

``rename_signal_refs`` is the one-time rename of the ``signal:<tag>`` subjects
and references stored before the change (results, runs and events).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from plantcraft.i18n import t
from plantcraft.industrial_data.registry import PRIMARY
from plantcraft_sdk.contract import kind_of
from plantcraft_sdk.derived import derived_signal, split_derived

logger = logging.getLogger(__name__)

# Recorded in the workspace once the stored references carry their source.
RENAME_MIGRATION = "signal-ids-with-source"


def signal_id(source_id: str, tag: str) -> str:
    """The API v1 id of ``tag`` read from ``source_id``."""

    return f"{source_id}:{tag}"


class AmbiguousSignal(LookupError):
    """A bare tag that more than one source has."""

    def __init__(self, tag: str, ids: list[str]):
        self.tag = tag
        self.ids = ids
        super().__init__(tag)

    def detail(self) -> str:
        return t(
            "Signal not found: {tag} is in more than one source; use {ids}.",
            tag=self.tag,
            ids=", ".join(self.ids),
        )


@dataclass
class SignalCatalog:
    """Every signal PlantCraft knows (API v1 shape, by id), with the tag each id reads."""

    signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    _by_tag: dict[str, list[str]] = field(default_factory=dict)
    _ordered: list[dict[str, Any]] | None = None

    def add(self, item: dict[str, Any], tag: str) -> None:
        self._ordered = None
        self.signals[item["id"]] = item
        self.tags[item["id"]] = tag
        ids = self._by_tag.setdefault(tag, [])
        if item["id"] not in ids:
            ids.append(item["id"])

    def __contains__(self, signal_id: object) -> bool:
        return signal_id in self.signals

    def ordered(self) -> list[dict[str, Any]]:
        """Every signal by id (sorted once per catalog)."""

        if self._ordered is None:
            self._ordered = [self.signals[key] for key in sorted(self.signals)]
        return self._ordered

    def find(self, given: str) -> str | None:
        """The id ``given`` names: itself, or the one id of a bare tag; ``None`` when unknown.

        Raises ``AmbiguousSignal`` for a bare tag that two sources have.
        """

        if given in self.signals:
            return given
        ids = self._by_tag.get(given, [])
        if len(ids) > 1:
            raise AmbiguousSignal(given, sorted(ids))
        return ids[0] if ids else None

    def lookup(self, given: str) -> tuple[str | None, str]:
        """``(id, "")`` for a known signal, else ``(None, reason worded for people)``."""

        try:
            found = self.find(given)
        except AmbiguousSignal as exc:
            return None, exc.detail()
        return (found, "") if found else (None, t("Signal not found."))


def _signal(
    source_id: str,
    tag: str,
    *,
    name: str = "",
    unit: str = "",
    description: str = "",
    kind: str = "number",
    source_kind: str | None = None,
) -> dict[str, Any]:
    return {
        "id": signal_id(source_id, tag),
        "name": name or tag,
        "source": source_id,
        "unit": unit or "",
        "description": description or "",
        # Engineering limits are not kept by PlantCraft yet.
        "low": None,
        "high": None,
        # "text" when the source records labels (controller modes), else "number".
        "kind": kind,
        # The source's type (opcua, pi_web_api, csv, derived): a CSV file's signal is sampled
        # (laboratory analyses, manual entries) and the apps judge it by its own rules.
        "source_kind": source_kind,
    }


def signal_catalog(platform: Any) -> SignalCatalog:
    """The signals PlantCraft knows: the scenario source's, routed ones and those on assets."""

    sources = platform.sources
    # Tag → added source, read once (``source_of`` per tag reads the registry each time).
    foreign = sources.foreign_routes()
    by_tag: dict[str, dict[str, Any]] = {}
    try:
        browsed = platform.data.signals()
    except Exception:  # an unreachable source must not hide the other signals
        browsed = []
    for item in browsed:
        by_tag[item["tag"]] = {
            "name": item["name"],
            "unit": item["unit"],
            "description": item["description"],
            "kind": kind_of(item.get("data_type")),
        }
    for tag in platform.scenario.source.tags:
        by_tag.setdefault(tag, {})
    added_kinds: dict[str, dict[str, str]] = {}
    for item in sources.routed_signals():
        base = by_tag.get(item["tag"], {})
        kind = base.get("kind", "number")
        owner = foreign.get(item["tag"], PRIMARY)
        if owner != PRIMARY:
            # Kinds come from the source the tag is read from (a mode is text), browsed once.
            if owner not in added_kinds:
                added_kinds[owner] = sources.signal_kinds(owner)
            kind = added_kinds[owner].get(item["tag"], "number")
        by_tag[item["tag"]] = {
            "name": item["name"] or base.get("name", ""),
            "unit": item["unit"] or base.get("unit", ""),
            "description": base.get("description", ""),
            "kind": kind,
        }
    for tag in platform.workspace.assets.signal_assets():
        by_tag.setdefault(tag, {})
    try:
        types = {item["source_id"]: item.get("type") for item in sources.list()}
    except Exception:  # the type is a hint; an unreadable registry must not hide the signals
        types = {}
    catalog = SignalCatalog()
    for tag, fields in by_tag.items():
        owner = foreign.get(tag, PRIMARY)
        catalog.add(_signal(owner, tag, **fields, source_kind=types.get(owner)), tag)
    # Derived series apps published here (no HistCraft): ``app-<app id>:<name>``.
    derived = getattr(platform, "derived", None)
    for row in derived.signals() if derived is not None else []:
        name = (split_derived(row["signal_id"]) or ("", row["signal_id"]))[1]
        item = derived_signal(
            row["signal_id"],
            app=row["app"],
            name=row["name"],
            unit=row["unit"],
            kind=row["kind"],
            subject=row["subject"],
            result=row["result"],
            description=row["description"],
            managed_by=row.get("managed_by") or "",
            retention_days=row.get("retention_days"),
        )
        catalog.add(item, name)
    return catalog


def sync_binding_sources(platform: Any) -> int:
    """Each asset signal binding records the source its tag is read from; returns rows changed."""

    if getattr(getattr(platform, "datalayer", None), "manages_sources", False):
        # With HistCraft, each binding keeps the source it was bound from.
        return 0
    store = platform.workspace.assets
    tags = store.bound_tags()
    foreign = platform.sources.foreign_routes()
    return store.set_binding_sources({tag: foreign.get(tag, PRIMARY) for tag in tags})


def _renamed(ref: str, sources: Any, known: set[str]) -> str | None:
    """``signal:<source>:<tag>`` for a stored ``signal:<tag>``; ``None`` when already named."""

    if not ref.startswith("signal:"):
        return None
    rest = ref[len("signal:") :]
    head, sep, tail = rest.partition(":")
    if sep and tail and head in known:
        return None
    return f"signal:{signal_id(sources.source_of(rest), rest)}"


def rename_signal_refs(platform: Any) -> dict[str, int] | None:
    """Once per installation: stored ``signal:<tag>`` subjects and refs gain their source.

    Results (and their history), runs' subjects and events (subjects and refs)
    are renamed through their stores; nothing is deleted. Returns the counts, or
    ``None`` when it already ran.
    """

    workspace = platform.workspace
    if workspace.migrated(RENAME_MIGRATION):
        return None
    sources = platform.sources
    known = {PRIMARY, *(row["source_id"] for row in sources.store.sources())}
    stored = set(workspace.results.signal_subjects()) | set(workspace.events.signal_refs())
    mapping = {
        ref: new for ref in sorted(stored) if (new := _renamed(ref, sources, known)) is not None
    }
    counts = {
        "refs": len(mapping),
        **workspace.results.rename_subjects(mapping),
        **workspace.events.rename_refs(mapping),
    }
    workspace.record_migration(RENAME_MIGRATION, counts)
    if mapping:
        logger.info("Signal references renamed with their source: %s", counts)
    return counts


__all__ = [
    "RENAME_MIGRATION",
    "AmbiguousSignal",
    "SignalCatalog",
    "rename_signal_refs",
    "signal_catalog",
    "signal_id",
    "sync_binding_sources",
]
