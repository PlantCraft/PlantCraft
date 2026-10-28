"""What an editor picks cards from: assets (with their signal roles) and signals.

Read with the person's own token, so PlantCraft decides what they can see.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter, Query
from plantcraft_sdk.links import MAX_SUBJECTS
from plantcraft_sdk.refs import asset_ref
from plantcraft_sdk.server.picker import signal_choices

from dashcraft.api.deps import CurrentUser, EditorView, RuntimeDep, guarded
from dashcraft.query.cards import derived_signals

router = APIRouter(prefix="/api", tags=["picker"])
MAX_ASSETS = 500


def _assets(rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    reader = rt.user_reader(user)
    return guarded(lambda: reader.assets(None), service=False)


@router.get("/assets")
def list_assets(
    rt: RuntimeDep,
    user: EditorView,
    kind: str | None = Query(default=None, max_length=60),
    q: str = Query(default="", max_length=120),
) -> list[dict[str, Any]]:
    everything = _assets(rt, user)
    names = {item.get("id"): item.get("name") or item.get("id") for item in everything}
    query = q.strip().lower()
    found = []
    for item in everything:
        if kind and item.get("kind") != kind:
            continue
        text = f"{item.get('id')} {item.get('name')} {names.get(item.get('parent_id')) or ''}"
        if query and query not in text.lower():
            continue
        found.append(
            {
                "id": item.get("id"),
                "name": item.get("name") or item.get("id"),
                "kind": item.get("kind"),
                "parent": names.get(item.get("parent_id")) if item.get("parent_id") else None,
                "signals": item.get("signals") or {},
            }
        )
    found.sort(key=lambda item: (str(item["parent"] or ""), str(item["name"])))
    return found[:MAX_ASSETS]


@router.get("/asset-kinds")
def asset_kinds(rt: RuntimeDep, user: EditorView) -> list[dict[str, Any]]:
    """Asset kinds with how many assets have each, and the signal roles they use."""

    counts: Counter[str] = Counter()
    roles: dict[str, set[str]] = {}
    for item in _assets(rt, user):
        kind = str(item.get("kind") or "")
        counts[kind] += 1
        roles.setdefault(kind, set()).update((item.get("signals") or {}).keys())
    return [
        {"kind": kind, "count": count, "roles": sorted(roles.get(kind) or ())}
        for kind, count in counts.most_common()
    ]


# Everyone: Trends (any person saves their own) searches signals here too.
@router.get("/signals")
def list_signals(
    rt: RuntimeDep,
    user: CurrentUser,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=30, ge=1, le=200),
) -> list[dict[str, Any]]:
    client = rt.user_client(user)
    found = guarded(lambda: client.signals(q.strip() or None), service=False)
    return signal_choices(found, q, limit=limit)


@router.get("/result-kinds")
def result_kinds(
    rt: RuntimeDep,
    user: EditorView,
    asset: str | None = Query(default=None, max_length=300),
    kind: str | None = Query(default=None, max_length=60),
) -> list[dict[str, Any]]:
    """App results published about one asset, or about the assets of one kind: what a card can
    show besides signals (``linkcraft.loop_health``...), with how many assets have each."""

    if asset:
        subjects = [asset_ref(asset)]
    else:
        subjects = [
            asset_ref(str(item["id"]))
            for item in _assets(rt, user)
            if item.get("id") and (not kind or item.get("kind") == kind)
        ][:MAX_SUBJECTS]
    if not subjects:
        return []
    client = rt.user_client(user)
    rows = guarded(lambda: client.results(subjects), service=False)
    counts: Counter[str] = Counter()
    for row in rows:
        counts[f"{row.get('app')}.{row.get('kind')}"] += 1
    # Results whose history an app archives (derived signals): what a trend card can draw.
    # One asset: API v1 filters by subject; many: one listing, kept to those subjects.
    listed = guarded(
        lambda: client.signals(subject=subjects[0]) if asset else client.signals(), service=False
    )
    wanted = set(subjects)
    history: Counter[str] = Counter(
        f"{signal['app']}.{signal['result']}"
        for signal in derived_signals(listed)
        if signal.get("subject") in wanted and (signal.get("kind") or "number") == "number"
    )
    return [
        {"result": name, "count": counts[name], "history": history[name]}
        for name in sorted(set(counts) | set(history))
    ]
