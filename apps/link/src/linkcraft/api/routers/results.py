"""Results: the latest result of every algorithm on every asset it runs on, on one list.

Each row says the same things whatever the algorithm (owner, 2026-10-23: Results are what the
algorithms concluded, nothing specific to loops or signals): the asset and its type, the
algorithm with its version, tags and responsible group, the status in the suite's words (``ok``,
``warning``, ``alarm``, ``unknown``), the headline measure, the limiting finding, when, and where
to open it. Filters: algorithm, tag, asset type, group and status. A new kind of subject adds a
row builder here; the page does not change.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query, Response

from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.api.routers.catalog import _groups
from linkcraft.api.routers.signals import _row as signal_row
from linkcraft.api.scope import sees_loop
from linkcraft.blocks.algorithms import SIGNAL_QUALITY
from linkcraft.catalog.loop_types import algorithm_id
from linkcraft.i18n import t
from linkcraft.loops.suite import SUITE_STATUS
from linkcraft.signals.publish import STATUS as SIGNAL_STATUS

router = APIRouter(prefix="/api")

KINDS = ("signal", "loop", "asset")
KIND_LABELS = {"signal": "Signals", "loop": "Loops", "asset": "Assets"}
STATUSES = ("alarm", "warning", "unknown", "ok")
RANK = {status: index for index, status in enumerate(STATUSES)}
# An algorithm on assets says ok, warning or bad; the suite says alarm for bad.
ASSET_STATUS = {"ok": "ok", "warning": "warning", "bad": "alarm", "alarm": "alarm"}
# The asset types a row can have: a signal, a control loop, or the type of the asset itself.
TYPE_LABELS = {"signal": "Signal", "loop": "Control loop"}


def _algorithms(rt: Any) -> dict[str, dict[str, Any]]:
    """Each algorithm's name, version, tags and responsible group, by id."""

    return {
        item["profile_id"]: {
            "id": item["profile_id"],
            "name": item["name"],
            "version": int(item.get("version") or 1),
            "tags": list(item.get("tags") or []),
            "group_id": str(item.get("group_id") or ""),
        }
        for item in rt.presets.list_profiles()
    }


def _algorithm(algorithms: dict[str, dict[str, Any]], profile_id: str, name: str = "") -> dict:
    found = algorithms.get(profile_id) or {}
    return {
        "id": profile_id,
        "name": found.get("name") or name,
        "version": found.get("version"),
    }


def _meta(algorithms: dict[str, dict[str, Any]], profile_id: str) -> dict[str, Any]:
    found = algorithms.get(profile_id) or {}
    return {"tags": found.get("tags") or [], "group_id": found.get("group_id") or ""}


def signal_label(signal_id: str) -> str:
    """A signal as people name it: ``CPM.Loops.AIC-1006.OP`` reads ``AIC-1006 · OP`` (the tag's
    last two parts when the last is a short role such as PV, SP, OP or MODE); other tags whole,
    without the source."""

    tag = str(signal_id).split(":", 1)[-1]
    parts = tag.rsplit(".", 2)
    if len(parts) >= 2 and parts[-2] and parts[-1].isalnum() and len(parts[-1]) <= 6:
        return f"{parts[-2]} · {parts[-1]}"
    return tag


def _signal_rows(rt: Any) -> Iterable[dict[str, Any]]:
    latest = rt.quality_results.summaries()
    algorithms = _algorithms(rt)
    algorithm = _algorithm(algorithms, SIGNAL_QUALITY, t("Signal quality"))
    meta = _meta(algorithms, SIGNAL_QUALITY)
    for signal in rt.signal_store.list():
        if not signal["enabled"] or signal["missing"]:
            continue
        row = signal_row(signal, latest.get(signal["id"]))
        verdict = row["status"] or "unchecked"
        limiting = row["limiting"]
        yield {
            "kind": "signal",
            "asset_type": "signal",
            "id": row["id"],
            "name": signal_label(row["id"]),
            "caption": row["description"] or row["name"],
            "area": row["source"] or "",
            "status": SIGNAL_STATUS.get(verdict, "unknown"),
            "native_status": verdict,
            "measure": {"label": t("Quality"), "value": row["quality"], "format": "score"},
            "algorithm": algorithm,
            **meta,
            "limiting": limiting or None,
            "finding": row["message"] or "",
            "at": row["checked_at"],
            "path": f"/signals/{quote(row['id'], safe='')}",
        }


def _loop_rows(rt: Any) -> Iterable[dict[str, Any]]:
    algorithms = _algorithms(rt)
    for row in rt.monitor.overview_rows():
        health = row["health"]
        status = SUITE_STATUS.get(row["status"], "unknown") if health is not None else "unknown"
        limiting = row["limiting"] or {}
        yield {
            "kind": "loop",
            "asset_type": "loop",
            "id": row["loop_id"],
            "name": row["loop_id"],
            "caption": row["service"] or row["name"],
            "area": row["area"] or "",
            "status": status,
            "native_status": row["status"],
            "measure": {"label": t("Health"), "value": health, "format": "percent"},
            "algorithm": _algorithm(algorithms, algorithm_id(row["profile_id"])),
            **_meta(algorithms, algorithm_id(row["profile_id"])),
            "limiting": limiting.get("method_id"),
            "finding": limiting.get("finding") or row["state_reason"] or "",
            "at": row["analyzed_at"],
            "path": f"/loops/{quote(row['loop_id'], safe='')}",
        }


def _asset_rows(rt: Any) -> Iterable[dict[str, Any]]:
    """Each algorithm on assets, on each of its assets: its latest run."""

    algorithms = _algorithms(rt)
    kinds = {
        str(item.get("id")): str(item.get("kind") or item.get("type") or "")
        for item in getattr(rt.quality_engine, "assets", None) or []
    }
    for row in rt.asset_runs.list():
        profile_id = row["algorithm_id"]
        if profile_id not in algorithms:
            continue
        status = "unknown" if row.get("error") else ASSET_STATUS.get(row.get("status"), "unknown")
        value = row.get("value")
        yield {
            "kind": "asset",
            "asset_type": kinds.get(row["asset_id"]) or "asset",
            "id": f"{profile_id}:{row['asset_id']}",
            "name": row.get("asset_name") or row["asset_id"],
            "caption": row["asset_id"],
            "area": "",
            "status": status,
            "native_status": row.get("status") or "unknown",
            "measure": {
                "label": t("Score"),
                "value": None if value is None else float(value),
                "format": "score",
            },
            "algorithm": _algorithm(algorithms, profile_id),
            **_meta(algorithms, profile_id),
            "limiting": None,
            "finding": (f"{t('Did not run')}: {row['error']}" if row.get("error") else "")
            or row.get("message")
            or "",
            "at": row.get("analyzed_at"),
            "path": f"/assets/{quote(row['asset_id'], safe='')}",
        }


BUILDERS: dict[str, Callable[[Any], Iterable[dict[str, Any]]]] = {
    "signal": _signal_rows,
    "loop": _loop_rows,
    "asset": _asset_rows,
}


def in_scope(scope: Any, rt: Any, row: dict[str, Any]) -> bool:
    """A row about what the person sees: its signal, its loop, or its asset (the caption)."""

    if scope.everything:
        return True
    if row["kind"] == "signal":
        return scope.signal(row["id"])
    if row["kind"] == "loop":
        return sees_loop(scope, rt, row["id"])
    return scope.asset(row["caption"])


def scoped_rows(rt: Any, scope: Any, kinds: Iterable[str] = KINDS) -> list[dict[str, Any]]:
    return [row for name in kinds for row in BUILDERS[name](rt) if in_scope(scope, rt, row)]


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    value = row["measure"]["value"]
    return (RANK.get(row["status"], 9), value if value is not None else 101, row["kind"], row["id"])


def _type_label(asset_type: str) -> str:
    return t(TYPE_LABELS[asset_type]) if asset_type in TYPE_LABELS else asset_type.capitalize()


def _list(value: str) -> list[str]:
    return [item for item in (part.strip() for part in value.split(",")) if item]


def filtered(
    rt: Any,
    user: Any,
    *,
    kind: str = "",
    status: str = "",
    algorithm: str = "",
    tag: str = "",
    asset_type: str = "",
    group: str = "",
    q: str = "",
) -> dict[str, Any]:
    """Every row, the rows the filters keep (worst first), and per filter how many each choice
    would show with the other filters as they are."""

    groups = _groups(rt, user)
    chosen = {
        "kind": set(_list(kind)) & set(BUILDERS),
        "status": set(_list(status)) & set(RANK),
        "algorithm": set(_list(algorithm)),
        "tag": set(_list(tag)),
        "asset_type": set(_list(asset_type)),
        "group": set(_list(group)),
    }
    needle = q.strip().lower()
    rows = scoped_rows(rt, rt.asset_scope(user))
    for row in rows:
        row["asset_type_label"] = _type_label(row["asset_type"])
        group_id = row.pop("group_id", "")
        row["group"] = (
            {"id": group_id, "name": str((groups.get(group_id) or {}).get("name") or group_id)}
            if group_id
            else None
        )
    if needle:
        rows = [
            row
            for row in rows
            if needle
            in (
                f"{row['id']} {row['name']} {row['caption']} {row['area']} {row['finding']} "
                f"{row['algorithm']['name']} {' '.join(row['tags'])}"
            ).lower()
        ]

    def values(row: dict[str, Any]) -> dict[str, set[str]]:
        return {
            "kind": {row["kind"]},
            "status": {row["status"]},
            "algorithm": {row["algorithm"]["id"]},
            "tag": set(row["tags"]),
            "asset_type": {row["asset_type"]},
            "group": {row["group"]["id"]} if row["group"] else set(),
        }

    def keeps(row: dict[str, Any], skip: str = "") -> bool:
        found = values(row)
        return all(
            not wanted or bool(found[name] & wanted)
            for name, wanted in chosen.items()
            if name != skip
        )

    counts: dict[str, dict[str, int]] = {name: {} for name in chosen}
    labels: dict[str, dict[str, str]] = {name: {} for name in chosen}
    for row in rows:
        found = values(row)
        for name in chosen:
            if not keeps(row, skip=name):
                continue
            for value in found[name]:
                counts[name][value] = counts[name].get(value, 0) + 1
        labels["algorithm"][row["algorithm"]["id"]] = row["algorithm"]["name"]
        labels["asset_type"][row["asset_type"]] = row["asset_type_label"]
        if row["group"]:
            labels["group"][row["group"]["id"]] = row["group"]["name"]
        for tag_name in row["tags"]:
            labels["tag"][tag_name] = tag_name
    shown = sorted((row for row in rows if keeps(row)), key=_key)
    options = {
        name: [
            {"id": value, "label": labels[name].get(value, value), "count": counts[name][value]}
            for value in sorted(counts[name], key=lambda item: labels[name].get(item, item))
        ]
        for name in ("algorithm", "tag", "asset_type", "group")
    }
    return {
        "shown": shown,
        "counts": {
            "kind": {name: counts["kind"].get(name, 0) for name in KINDS},
            "status": {name: counts["status"].get(name, 0) for name in STATUSES},
        },
        "options": options,
        "chosen": chosen,
    }


@router.get("/results")
def results(
    rt: RuntimeDep,
    user: CurrentUser,
    kind: str = "",
    status: str = "",
    algorithm: str = "",
    tag: str = "",
    asset_type: str = "",
    group: str = "",
    q: str = "",
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """The latest result of every algorithm on every asset, worst first. Each filter takes a
    comma list: ``kind`` (signal, loop, asset), ``status``, ``algorithm``, ``tag``,
    ``asset_type`` and ``group``. ``counts`` and ``options`` say how many rows each choice would
    show with the other filters as they are."""

    found = filtered(
        rt,
        user,
        kind=kind,
        status=status,
        algorithm=algorithm,
        tag=tag,
        asset_type=asset_type,
        group=group,
        q=q,
    )
    shown = found["shown"]
    return {
        "total": len(shown),
        "counts": found["counts"],
        "options": found["options"],
        "kinds": [{"id": name, "label": t(KIND_LABELS[name])} for name in KINDS],
        "items": shown[offset : offset + limit],
    }


@router.get("/reports/results.pdf")
def results_report(
    rt: RuntimeDep,
    user: CurrentUser,
    kind: str = "",
    status: str = "",
    algorithm: str = "",
    tag: str = "",
    asset_type: str = "",
    group: str = "",
    q: str = "",
) -> Response:
    """The results the filters keep, as a PDF: counts by status and by algorithm, then every
    result worst first (the weekly report of 0.3, for any filter)."""

    from linkcraft.report.results import results_report_pdf

    found = filtered(
        rt,
        user,
        kind=kind,
        status=status,
        algorithm=algorithm,
        tag=tag,
        asset_type=asset_type,
        group=group,
        q=q,
    )
    names = {
        name: [
            next((item["label"] for item in found["options"][name] if item["id"] == value), value)
            for value in sorted(found["chosen"][name])
        ]
        for name in ("algorithm", "tag", "asset_type", "group")
    }
    content, stamp = results_report_pdf(
        found["shown"],
        filters={
            "status": sorted(found["chosen"]["status"]),
            **names,
            "q": q.strip(),
        },
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="results-{stamp}.pdf"'},
    )
