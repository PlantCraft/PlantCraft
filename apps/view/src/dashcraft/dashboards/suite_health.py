"""The dashboard "Suite health": the suite watching itself, kept by View, read-only.

PlantCraft writes the suite's health every minute to the Historian's source ``system``
("System"): ``system:<service>.up``, ``.latency_ms``, ``.cpu_pct``, ``.mem_mb``, ``.errors``...,
``system:host.disk_free_pct``, ``system:backup.age_h``... (PlantCraft ``docs/operations.md``,
section 4). When those signals exist, View keeps one dashboard over them (``builtin`` =
``suite-health``): created on the first look, its cards redrawn when the services change.
Nobody edits or deletes it; a copy is an ordinary dashboard.

``build`` is a pure function over the signal ids; ``ensure`` reads them with View's service
token and saves the dashboard.
"""

from __future__ import annotations

import logging
from typing import Any

from dashcraft.dashboards.model import MAX_ITEMS, DashboardPayload
from dashcraft.i18n import t

LOGGER = logging.getLogger(__name__)

BUILTIN = "suite-health"
SOURCE = "system"
# Containers that are no server of their own come after the apps in every card.
_LAST = ("proxy", "installer", "histcraft-db")


def _services(signals: set[str], suffix: str) -> list[str]:
    found = {
        signal[len(SOURCE) + 1 : -len(suffix) - 1]
        for signal in signals
        if signal.startswith(f"{SOURCE}:") and signal.endswith(f".{suffix}")
    }
    found.discard("host")
    found.discard("backup")
    return sorted(found, key=lambda name: (name in _LAST, name != "processcraft", name))


def _items(signals: set[str], suffix: str) -> list[dict[str, Any]]:
    return [
        {"signal_id": f"{SOURCE}:{name}.{suffix}", "label": name}
        for name in _services(signals, suffix)[:MAX_ITEMS]
    ]


def _one(card_id: str, title: str, signal: str, **options: Any) -> dict[str, Any]:
    return {"card_id": card_id, "title": title, "items": [{"signal_id": signal}], **options}


def build(signals: set[str]) -> dict[str, Any] | None:
    """The dashboard over the ``system:*`` signals there are; None when there are none."""

    signals = {signal for signal in signals if signal.startswith(f"{SOURCE}:")}
    if not signals:
        return None
    cards: list[dict[str, Any]] = []
    if f"{SOURCE}:host.disk_free_pct" in signals:
        cards.append(
            _one("disk", t("Free disk"), f"{SOURCE}:host.disk_free_pct", kind="gauge",
                 gauge_min=0, gauge_max=100, decimals=0, width=3, height=2,
                 thresholds={"low_alarm": 10, "low_warn": 20})
        )  # fmt: skip
    if f"{SOURCE}:backup.age_h" in signals:
        cards.append(
            _one("backup-age", t("Last good backup (hours ago)"), f"{SOURCE}:backup.age_h",
                 kind="spark", window="7d", decimals=1, width=3, height=2,
                 thresholds={"high_warn": 26, "high_alarm": 50})
        )  # fmt: skip
    if f"{SOURCE}:backup.ok" in signals:
        cards.append(
            _one("backup-ok", t("Last backup good (1 yes, 0 no)"), f"{SOURCE}:backup.ok",
                 kind="kpi", window="7d", decimals=0, width=3, height=1,
                 thresholds={"low_alarm": 0.5})
        )  # fmt: skip
    if f"{SOURCE}:backup.drill_ok" in signals:
        cards.append(
            _one("drill-ok", t("Last restore drill passed (1 yes, 0 no)"),
                 f"{SOURCE}:backup.drill_ok", kind="kpi", window="30d", decimals=0, width=3,
                 height=1, thresholds={"low_alarm": 0.5})
        )  # fmt: skip
    charts = (
        ("up", "table", t("Services up (1 running and healthy, 0 not)"), "1h", 6),
        ("up", "trend", t("Services up, last 24 h"), "24h", 6),
        ("latency_ms", "trend", t("Response time p95 (ms)"), "24h", 6),
        ("errors", "trend", t("Errors logged per minute"), "24h", 6),
        ("cpu_pct", "trend", t("CPU (%)"), "24h", 6),
        ("mem_mb", "trend", t("Memory (MB)"), "24h", 6),
        ("restarts", "table", t("Restarts"), "24h", 6),
        ("warnings", "trend", t("Warnings logged per minute"), "24h", 6),
    )
    for suffix, kind, title, window, width in charts:
        items = _items(signals, suffix)
        if items:
            cards.append(
                {"card_id": f"{kind}-{suffix}".replace("_", "-"), "title": title, "kind": kind,
                 "items": items, "window": window, "agg": "last", "width": width, "height": 4}
            )  # fmt: skip
    if f"{SOURCE}:host.disk_free_gb" in signals:
        cards.append(
            _one("disk-trend", t("Free disk (GB), last 30 days"), f"{SOURCE}:host.disk_free_gb",
                 kind="trend", window="30d", width=6, height=4)
        )  # fmt: skip
    cards.append(
        {
            "card_id": "note",
            "title": t("About this dashboard"),
            "kind": "text",
            "items": [],
            "text": t(
                "PlantCraft writes these values every minute to the Historian's source "
                "System, kept 90 days. The administrators also get a message from System when "
                "a service stops, the disk fills or a backup is missing, even when the "
                "Historian or View is the one down.\n\nThis dashboard is kept by the suite: "
                "copy it to change it."
            ),
            "width": 6,
            "height": 4,
        }
    )
    return DashboardPayload.model_validate(
        {
            "name": t("Suite health"),
            "description": t(
                "Every service of the suite: up, response time, errors, CPU and memory; the "
                "free disk and the backups."
            ),
            "refresh_seconds": 60,
            "cards": cards,
        }
    ).stored()


# What View asks API v1 for (``q`` matches the tag): every suffix the dashboard draws.
QUERIES = (".up", ".latency_ms", ".errors", ".warnings", ".cpu_pct", ".mem_mb", ".restarts",
           "host.disk_free", "backup.")  # fmt: skip


# The folder View keeps its own dashboards in (owner, 2026-10-25): the platform's next to the
# plant's, so a new installation shows that dashboards live in folders.
PLATFORM_FOLDER = {
    "name": "Platform",
    "description": "The suite's own dashboards, kept by View: how the suite itself is doing.",
    "viewers": [],
    "editors": [],
}


def _folder_id(folders: Any, current: dict[str, Any] | None) -> str:
    """Where the dashboard lives: the folder it is in (an administrator may have renamed it),
    else the Platform folder, made when missing; General without a folder store."""

    if folders is None:
        return ""
    kept = (current or {}).get("folder_id") or ""
    if kept and folders.get(kept) is not None:
        return kept
    found = folders.by_name(PLATFORM_FOLDER["name"]) or folders.create(PLATFORM_FOLDER, None)
    return found.get("folder_id") or ""


def ensure(store: Any, client: Any, folders: Any = None) -> dict[str, Any] | None:
    """Creates or redraws the dashboard when the ``system`` signals changed; the dashboard,
    or None while the source does not exist. PlantCraft or the Historian down: the
    dashboard stays as it is."""

    signals: set[str] = set()
    try:
        for query in QUERIES:
            signals.update(
                str(item.get("id"))
                for item in client.signals(query)
                if isinstance(item, dict) and str(item.get("id") or "").startswith(f"{SOURCE}:")
            )
    except Exception as exc:  # noqa: BLE001 - try again on the next look
        LOGGER.info("Suite health: signals not read: %s", exc)
        return store.builtin(BUILTIN)
    draft = build(signals)
    current = store.builtin(BUILTIN)
    if draft is None:
        return current
    draft = {**draft, "folder_id": _folder_id(folders, current)}
    if current is None:
        return store.create(draft, None, builtin=BUILTIN)
    if (
        current.get("cards") != draft["cards"]
        or current.get("name") != draft["name"]
        or (current.get("folder_id") or "") != draft["folder_id"]
    ):
        return store.update(current["dashboard_id"], draft, None)
    return current
