"""A new plant's first step here (``[[contributes.start]]`` in ``app.toml``): PlantCraft sends it
once an administrator applies an import of assets, as that person. The Historian collects the
signals the import bound, from the sources it holds; a signal it collects already is left as it
is, and a source it does not hold is counted, never made up."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from plantcraft_sdk.contributes import StartIn, StartOut

from histcraft.api.deps import EditorUser, RuntimeDep
from histcraft.api.routers.data import ImportedSignal, _add_signals, _describe
from histcraft.catalog.models import PLANT_KINDS, CatalogError
from histcraft.i18n import t

router = APIRouter(prefix="/api/start", tags=["start"])


@router.post("/collect-signals")
def collect_signals(body: StartIn, runtime: RuntimeDep, user: EditorUser) -> dict[str, Any]:
    """Collect the import's signals, each from its own source, with the source's description."""

    by_source: dict[str, list[str]] = {}
    for signal in body.signals:
        tags = by_source.setdefault(signal.source_id, [])
        if signal.tag not in tags:
            tags.append(signal.tag)
    added: list[str] = []
    collected = elsewhere = 0
    for source_id, tags in by_source.items():
        try:
            source = runtime.catalog.source(source_id) if source_id else None
        except CatalogError:
            source = None
        if source is None or source["kind"] not in PLANT_KINDS:
            elsewhere += len(tags)
            continue
        items = [ImportedSignal(tag=tag) for tag in tags]
        _describe(runtime, source_id, items)
        result = _add_signals(runtime, source_id, items)
        added += result["added"]
        collected += len(tags) - len(result["added"])
    if added:
        runtime.audit(user, "points.add", f"{len(added)} points", added[:50])
    summary = t(
        "{added} signals are collected now, {kept} were collected already.",
        added=len(added),
        kept=collected,
    )
    if elsewhere:
        summary += " " + t(
            "{count} signals come from sources the Historian does not hold: add the source in "
            "Sources first.",
            count=elsewhere,
        )
    counts = {"added": len(added), "collected": collected, "elsewhere": elsewhere}
    return StartOut(summary=summary, counts=counts, open="/hist/points").model_dump()
