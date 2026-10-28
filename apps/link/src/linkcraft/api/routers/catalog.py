"""Blocks, algorithms (block diagrams) and the methods' site defaults.

An algorithm is a diagram of blocks (``linkcraft.blocks``) saved with its documentation, its
author, who answers for it, its tags, its version and the user group that may edit it (the other
editors read it). The ones Link ships are read-only: people duplicate one and change the copy.
"""

from __future__ import annotations

import inspect
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from plantcraft_sdk.blocks import check_algorithm
from pydantic import ValidationError

from linkcraft.api.deps import AdminUser, CurrentUser, EditorUser, RuntimeDep
from linkcraft.api.schemas import (
    AlgorithmMetaPayload,
    AlgorithmPayload,
    CalibratePayload,
    DiagramPayload,
    MethodDefaultsPayload,
    RepeatedRemovePayload,
    TestPayload,
)
from linkcraft.assets.calibrate import calibrate_on_asset
from linkcraft.assets.run import AssetTiming, run_on_asset, timing_of, window_end
from linkcraft.assets.twins import repeated_twins
from linkcraft.blocks import compile_algorithm, node_for_method
from linkcraft.blocks.algorithms import SIGNAL_QUALITY
from linkcraft.blocks.checks import block_id as check_block_id
from linkcraft.blocks.convert import diagram_of
from linkcraft.blocks.models import LIBRARY as MODEL_LIBRARY
from linkcraft.blocks.stored import compute_placement, method_config
from linkcraft.catalog.labels import METHOD_LABELS, parameter_schema
from linkcraft.catalog.loop_types import ALGORITHM_OF_PROTOCOL
from linkcraft.catalog.loop_types import algorithm_id as current_id
from linkcraft.catalog.registry import (
    gate_method_ids,
    get_method_module,
    get_method_spec,
    group_catalog,
    list_method_specs,
    method_group,
)
from linkcraft.catalog.signal_checks import CHECKS as SIGNAL_CHECKS
from linkcraft.catalog.signal_checks import GROUP as SIGNAL_GROUP
from linkcraft.catalog.signal_checks import GROUP_ID as SIGNAL_GROUP_ID
from linkcraft.engine.suite_compute import interactive, placement
from linkcraft.i18n import t
from linkcraft.knowledge import DOC_FIELDS, algorithm_item, generated_docs

router = APIRouter()
# How long "Run now" on an algorithm on assets waits for its executions before it answers.
RUN_WAIT_SECONDS = 120
# How long the platform's user groups are kept before they are asked again.
GROUPS_SECONDS = 60.0
PACKAGE_DIR = Path(__file__).resolve().parents[2]


@router.get("/api/method-groups")
def method_groups(_user: CurrentUser) -> list[dict[str, Any]]:
    """The signal checks (Data quality) first, then the loop gate and the loop methods."""

    signal = {
        **SIGNAL_GROUP,
        "name": t(SIGNAL_GROUP["name"]),
        "description": t(SIGNAL_GROUP["description"]),
        "method_count": len(SIGNAL_CHECKS),
    }
    return [signal, *group_catalog()]


def _signal_check_items(rt: Any) -> list[dict[str, Any]]:
    """The signal checks as the Methods page lists them; their defaults are the algorithm's."""

    configured = rt.quality_settings.get().check_parameters
    items = []
    for check_id, block in SIGNAL_CHECKS.items():
        metadata = block.metadata.model_dump(mode="json")
        items.append(
            {
                "method_id": check_id,
                "block_id": check_block_id(check_id),
                "application": SIGNAL_GROUP_ID,
                "gate": False,
                "applies_to": "signal",
                "name": t(metadata["name"]),
                "label": t(metadata["name"]),
                "version": metadata.get("version", "1.0.0"),
                "maturity": metadata["maturity"],
                "description": t(metadata.get("description", "")),
                "required_signals": ["signal"],
                "references": metadata.get("references", []),
                "assumptions": [t(item) for item in metadata.get("assumptions", [])],
                "limitations": [t(item) for item in metadata.get("limitations", [])],
                "formula": metadata.get("implemented_formula"),
                "parameters": parameter_schema(block.parameter_schema),
                "configured_defaults": configured.get(check_id, {}),
                "ports": [],
                "custom": False,
            }
        )
    return items


@router.get("/api/methods")
def methods(_user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    configured_defaults = rt.presets.list_method_defaults()
    items = []
    for spec in list_method_specs():
        metadata = spec.metadata.model_dump(mode="json")
        items.append(
            {
                "method_id": spec.method_id,
                "application": method_group(spec.method_id),
                "gate": spec.method_id in gate_method_ids(),
                "name": metadata["name"],
                "label": METHOD_LABELS.get(spec.method_id, metadata["name"]),
                "version": spec.version,
                "maturity": metadata["maturity"],
                "description": metadata.get("description", ""),
                "required_signals": metadata.get("required_signals", []),
                "references": metadata.get("references", []),
                "assumptions": metadata.get("assumptions", []),
                "limitations": metadata.get("limitations", []),
                "formula": metadata.get("implemented_formula"),
                "parameters": parameter_schema(spec.parameter_schema),
                "configured_defaults": configured_defaults.get(spec.method_id, {}),
                "block_id": node_for_method(spec.method_id),
                "custom": False,
                "applies_to": "loop",
            }
        )
    return [*_signal_check_items(rt), *items]


@router.put("/api/methods/{method_id}/defaults")
def save_method_defaults(
    method_id: str, payload: MethodDefaultsPayload, user: AdminUser, rt: RuntimeDep
) -> dict[str, Any]:
    if method_id in SIGNAL_CHECKS:  # a signal check: the Signal quality algorithm's defaults
        block = SIGNAL_CHECKS[method_id]
        try:
            validated = block.parameter_schema.model_validate(payload.parameters)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
        parameters = validated.model_dump(mode="json")
        settings = rt.quality_settings.get()
        stored = {**settings.check_parameters, method_id: parameters}
        rt.quality_settings.save(
            settings.model_copy(update={"check_parameters": stored}), user.username
        )
        version = rt.presets.add_defaults_version(
            method_id, parameters, payload.description, actor=user.username
        )
        rt.audit(user, "method_defaults.saved", f"method:{method_id}", parameters)
        return {"method_id": method_id, "configured_defaults": parameters, "version": version}
    try:
        spec = get_method_spec(method_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Method not found.")) from exc
    try:
        validated = spec.parameter_schema.model_validate(payload.parameters)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
    parameters = validated.model_dump(mode="json")
    rt.presets.save_method_defaults(method_id, parameters, actor=user.username)
    version = rt.presets.add_defaults_version(
        method_id, parameters, payload.description, actor=user.username
    )
    rt.audit(user, "method_defaults.saved", f"method:{method_id}", parameters)
    return {"method_id": method_id, "configured_defaults": parameters, "version": version}


def _known_method(method_id: str) -> None:
    if method_id in SIGNAL_CHECKS:
        return
    try:
        get_method_spec(method_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Method not found.")) from exc


@router.get("/api/methods/{method_id}/defaults/versions")
def method_defaults_versions(
    method_id: str, _user: CurrentUser, rt: RuntimeDep
) -> list[dict[str, Any]]:
    """Each save of the defaults, newest (in use) first: what changed, who and when."""

    _known_method(method_id)
    return rt.presets.defaults_versions(method_id)


@router.delete("/api/methods/{method_id}/defaults/versions/{number}")
def delete_method_defaults_version(
    method_id: str, number: int, user: AdminUser, rt: RuntimeDep
) -> dict[str, Any]:
    """Delete one saved version of the defaults; the one in use stays."""

    _known_method(method_id)
    try:
        removed = rt.presets.delete_defaults_version(method_id, number)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=t("Version not found."))
    rt.audit(user, "method_defaults.version_deleted", f"method:{method_id}", {"number": number})
    return {"method_id": method_id, "deleted": number}


@router.get("/api/methods/{method_id}/source")
def method_source(method_id: str, _user: CurrentUser) -> dict[str, Any]:
    """The method's code, as shipped (read-only: LinkCraft has no method studio yet)."""

    try:
        module = (
            sys.modules[SIGNAL_CHECKS[method_id].__module__]
            if method_id in SIGNAL_CHECKS
            else get_method_module(method_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=t("Method not found.")) from exc
    source_path = getattr(module, "source_file", None) or inspect.getsourcefile(module)
    path = Path(source_path) if source_path else None
    if path is not None and PACKAGE_DIR in path.resolve().parents:
        source = path.read_text(encoding="utf-8")
    else:
        source = inspect.getsource(module.run)
    return {
        "method_id": method_id,
        "filename": path.name if path else f"{method_id}.py",
        "source": source,
        "editable": False,
    }


# Algorithms -----------------------------------------------------------------------------


def _groups(rt: Any, user: Any) -> dict[str, dict[str, Any]]:
    """The platform's user groups by id, kept a minute (empty when it cannot be reached)."""

    kept = getattr(rt, "_algorithm_groups", None)
    now = time.monotonic()
    if kept is not None and now - kept[0] < GROUPS_SECONDS:
        return kept[1]
    try:
        found = {str(item["id"]): dict(item) for item in rt.user_client(user).groups()}
    except Exception:  # noqa: BLE001 - nobody is locked out when the platform is away
        found = kept[1] if kept is not None else {}
    rt._algorithm_groups = (now, found)
    return found


def _group_people(group: dict[str, Any], groups: dict[str, dict[str, Any]]) -> set[str]:
    """Who may work in a group's things: its members and the coordinators above it."""

    people = set(group.get("members") or [])
    seen: set[str] = set()
    current: dict[str, Any] | None = group
    while current is not None and str(current.get("id")) not in seen:
        seen.add(str(current.get("id")))
        if current.get("coordinator"):
            people.add(str(current["coordinator"]))
        parent = current.get("parent_id")
        current = groups.get(str(parent)) if parent else None
    return people


def may_edit(user: Any, profile: dict[str, Any], groups: dict[str, dict[str, Any]]) -> bool:
    """An editor changes a person's algorithm unless it belongs to a group they are not in (an
    admin and the one who answers for it always may); Link's own are read-only."""

    if profile.get("system") or not getattr(user, "can_edit", False):
        return False
    group_id = str(profile.get("group_id") or "")
    if not group_id or user.is_admin or profile.get("owner") == user.username:
        return True
    group = groups.get(group_id)
    return group is None or user.username in _group_people(group, groups)


def _algorithm(
    profile: dict[str, Any],
    *,
    user: Any = None,
    groups: dict[str, dict[str, Any]] | None = None,
    used: int | None = None,
) -> dict[str, Any]:
    """An algorithm as the editor reads it: its diagram checked, its docs completed, who made it
    and answers for it, its tags, version and group, and whether this user may change it."""

    config = profile.get("method_config") or {}
    diagram = diagram_of(config)
    plan = compile_algorithm(diagram)
    written = config.get("docs") if isinstance(config.get("docs"), dict) else {}
    groups = groups or {}
    group_id = str(profile.get("group_id") or "")
    return {
        "algorithm_id": profile["profile_id"],
        "name": profile["name"],
        "description": profile.get("description") or "",
        "system": bool(profile.get("system")),
        "subject_kind": config.get("subject_kind") or "loop",
        "diagram": diagram,
        "check": plan.report(),
        "docs": {key: str(written.get(key) or "") for key in DOC_FIELDS},
        "docs_generated": generated_docs(
            str(profile.get("name") or ""), str(profile.get("description") or ""), plan
        ),
        "method_ids": config.get("method_ids") or [],
        "timing": timing_of(config).model_dump(),
        "assets": list(config.get("assets") or []),
        # Where its work runs on the suite's compute workers (environment, size).
        "compute": compute_placement(config.get("compute")),
        # The 0.2 protocol ids a loop or schedule may still name, which open this algorithm.
        "aliases": sorted(
            old for old, new in ALGORITHM_OF_PROTOCOL.items() if new == profile["profile_id"]
        ),
        "author": profile.get("author") or "",
        "owner": profile.get("owner") or "",
        "owner_name": profile.get("owner_name") or profile.get("owner") or "",
        "tags": list(profile.get("tags") or []),
        "group": (
            {"id": group_id, "name": str((groups.get(group_id) or {}).get("name") or group_id)}
            if group_id
            else None
        ),
        "version": int(profile.get("version") or 1),
        "used_by": used,
        "editable": may_edit(user, profile, groups) if user is not None else False,
        "created_at": profile.get("created_at"),
        "updated_at": profile.get("updated_at"),
    }


def _uses(rt: Any) -> Counter[str]:
    """How many subjects each algorithm works on: its loops, its assets, every active signal."""

    counts: Counter[str] = Counter(
        current_id(loop.profile_id) for loop in rt.loops.list_loops() if loop.enabled
    )
    for profile in rt.presets.list_profiles():
        config = profile.get("method_config") or {}
        if (config.get("subject_kind") or "loop") == "asset":
            counts[profile["profile_id"]] = len(config.get("assets") or [])
    counts[SIGNAL_QUALITY] = sum(
        1 for row in rt.signal_store.list() if row["enabled"] and not row["missing"]
    )
    return counts


def _get(rt: Any, algorithm_id: str) -> dict[str, Any]:
    found = rt.presets.get_profile(algorithm_id)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Algorithm not found."))
    return found


@router.get("/api/user-groups")
def user_groups(user: CurrentUser, rt: RuntimeDep) -> list[dict[str, str]]:
    """The platform's user groups an algorithm can be given to, by name."""

    found = [
        {"id": group_id, "name": str(group.get("name") or group_id)}
        for group_id, group in _groups(rt, user).items()
    ]
    return sorted(found, key=lambda item: item["name"].lower())


@router.get("/api/algorithms")
def algorithms(user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    groups = _groups(rt, user)
    uses = _uses(rt)
    return [
        _algorithm(profile, user=user, groups=groups, used=uses.get(profile["profile_id"], 0))
        for profile in rt.presets.list_profiles()
    ]


def _repeated(rt: Any) -> list[dict[str, Any]]:
    schedules = rt.jobs.list_schedules()
    return [
        {
            "algorithm_id": profile["profile_id"],
            "name": profile.get("name") or profile["profile_id"],
            "same_as": {"algorithm_id": same["profile_id"], "name": same.get("name") or ""},
            "schedules": [
                {"schedule_id": item["schedule_id"], "name": item.get("name") or ""}
                for item in schedules
                if item.get("profile_id") == profile["profile_id"]
            ],
        }
        for profile, same in repeated_twins(rt.presets.list_profiles())
    ]


@router.get("/api/algorithms/repeated")
def repeated(_user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """Algorithms copied from Twin that repeat another of the site's (the demo's examples)."""

    return _repeated(rt)


@router.post("/api/algorithms/repeated/remove")
def remove_repeated(
    payload: RepeatedRemovePayload, user: AdminUser, rt: RuntimeDep
) -> dict[str, Any]:
    """Delete the repeated algorithms named, with their schedules (only ones still repeated)."""

    found = {item["algorithm_id"]: item for item in _repeated(rt)}
    removed = []
    for algorithm_id in payload.algorithm_ids:
        item = found.get(algorithm_id)
        if item is None:
            continue
        if any(loop.profile_id == algorithm_id for loop in rt.loops.list_loops()):
            raise HTTPException(
                status_code=409, detail=t("A loop uses {name}: change it first.", name=item["name"])
            )
        for schedule in item["schedules"]:
            rt.jobs.delete_schedule(schedule["schedule_id"])
        rt.presets.delete_profile(algorithm_id)
        rt.asset_runs.forget(algorithm_id)
        rt.audit(
            user,
            "algorithm.deleted",
            f"algorithm:{algorithm_id}",
            {"repeats": item["same_as"]["algorithm_id"], "schedules": len(item["schedules"])},
        )
        removed.append(algorithm_id)
    if removed:
        rt.publish_schedules()
    return {"removed": removed}


@router.get("/api/algorithms/{algorithm_id}")
def algorithm(algorithm_id: str, user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    profile = _get(rt, current_id(algorithm_id))
    used = _uses(rt).get(profile["profile_id"], 0)
    return _algorithm(profile, user=user, groups=_groups(rt, user), used=used)


@router.get("/api/algorithms/{algorithm_id}/versions")
def algorithm_versions(
    algorithm_id: str, _user: CurrentUser, rt: RuntimeDep
) -> list[dict[str, Any]]:
    """Every saved version, newest first: its number, name, description, when and who."""

    profile = _get(rt, current_id(algorithm_id))
    current = int(profile.get("version") or 1)
    return [
        {
            "version": int(row["version"]),
            "name": row["name"],
            "description": row.get("description") or "",
            "saved_at": row.get("saved_at"),
            "saved_by": row.get("saved_by") or "",
            "version_name": row.get("version_name") or "",
            "version_note": row.get("version_note") or "",
            "current": int(row["version"]) == current,
        }
        for row in rt.presets.list_versions(profile["profile_id"])
    ]


@router.get("/api/algorithms/{algorithm_id}/versions/{version}")
def algorithm_version(
    algorithm_id: str, version: int, user: CurrentUser, rt: RuntimeDep
) -> dict[str, Any]:
    """One version as it was saved, read as the algorithm (its diagram, docs and check)."""

    profile = _get(rt, current_id(algorithm_id))
    found = rt.presets.get_version(profile["profile_id"], version)
    if found is None:
        raise HTTPException(status_code=404, detail=t("Version not found."))
    old = {
        **profile,
        "name": found["name"],
        "description": found.get("description") or "",
        "method_config": found.get("method_config") or {},
        "version": int(found["version"]),
        "updated_at": found.get("saved_at"),
    }
    answer = _algorithm(old, user=user, groups=_groups(rt, user))
    answer["editable"] = False  # an older version is read; a change saves a new one
    return answer


@router.patch("/api/algorithms/{algorithm_id}")
def update_algorithm(
    algorithm_id: str, payload: AlgorithmMetaPayload, user: EditorUser, rt: RuntimeDep
) -> dict[str, Any]:
    """Who answers for a person's algorithm, its tags and its group (not a new version)."""

    existing = _get(rt, algorithm_id)
    groups = _groups(rt, user)
    if not may_edit(user, existing, groups):
        raise HTTPException(status_code=403, detail=_read_only(existing, groups))
    if payload.group_id and payload.group_id not in groups and groups:
        raise HTTPException(status_code=422, detail=t("Group not found."))
    rt.presets.update_meta(
        algorithm_id,
        owner=payload.owner,
        owner_name=payload.owner_name,
        tags=payload.tags,
        group_id=payload.group_id,
    )
    rt.audit(
        user,
        "algorithm.updated",
        f"algorithm:{algorithm_id}",
        payload.model_dump(exclude_none=True),
    )
    return _algorithm(_get(rt, algorithm_id), user=user, groups=groups)


def _read_only(profile: dict[str, Any], groups: dict[str, dict[str, Any]]) -> str:
    if profile.get("system"):
        return t("Analytics' algorithms are read-only: duplicate it and change the copy.")
    group = groups.get(str(profile.get("group_id") or "")) or {}
    return t(
        "Only the group {group} edits this algorithm; duplicate it to change a copy.",
        group=group.get("name") or profile.get("group_id"),
    )


@router.get("/api/algorithms/{algorithm_id}/markdown")
def algorithm_text(algorithm_id: str, _user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """The algorithm as the assistant reads it (the editor's "copy for an assistant")."""

    item = algorithm_item(_get(rt, current_id(algorithm_id)), rt.root_path)
    return {"ref": item["ref"], "markdown": item["text"]}


@router.post("/api/algorithms/check")
def algorithm_check(payload: DiagramPayload, _user: CurrentUser) -> dict[str, Any]:
    return compile_algorithm(payload.diagram).report()


@router.post("/api/algorithms/docs")
def algorithm_generated_docs(payload: DiagramPayload, _user: CurrentUser) -> dict[str, str]:
    """The documentation the diagram gives, for the fields people left empty."""

    return generated_docs(payload.name, payload.description, compile_algorithm(payload.diagram))


@router.get("/api/compute/offer")
def compute_offer(_user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """Where an algorithm may run: the environments and sizes of the suite's compute workers."""

    return rt.compute_offer()


@router.post("/api/algorithms/test")
@interactive
def algorithm_test(payload: TestPayload, user: CurrentUser, rt: RuntimeDep) -> dict[str, Any]:
    """Run a diagram on one loop's recent data, without saving anything.

    The answer carries what every wire carried (``trace``), for the editor to show.
    """

    report = compile_algorithm(payload.diagram).report()
    if not report["valid"]:
        return {"check": report}
    with placement(payload.compute.model_dump() if payload.compute else None):
        return _algorithm_test(payload, report, user, rt)


def _algorithm_test(
    payload: TestPayload, report: dict[str, Any], user: Any, rt: Any
) -> dict[str, Any]:
    if payload.asset_id:
        return {"check": report, **_test_on_asset(payload, user, rt)}
    loop_id = payload.loop_id or next((loop.loop_id for loop in rt.monitor.loops), None)
    if not loop_id:
        raise HTTPException(status_code=404, detail=t("No loop configured."))
    try:
        found = rt.monitor.preview(
            loop_id,
            payload.diagram,
            lookback_minutes=payload.lookback_minutes,
            plant=rt.user_plant(user),
            start=payload.start if payload.end else None,
            end=payload.end if payload.start else None,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # PlantCraft unreachable or refusing: say so, never a 500
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"check": report, **found}


@router.post("/api/algorithms/calibrate")
def algorithm_calibrate(
    payload: CalibratePayload, user: EditorUser, rt: RuntimeDep
) -> dict[str, Any]:
    """Calibrate a Deviation (T²) block of a diagram (saved or not) on one asset over a period
    of normal operation, as the user. Nothing is saved: the editor puts the answer's
    ``calibration`` in the block's parameters and people save the algorithm."""

    report = compile_algorithm(payload.diagram).report()
    if not report["valid"]:
        raise HTTPException(status_code=422, detail=" ".join(report.get("errors") or []))
    try:
        return calibrate_on_asset(
            payload.diagram,
            payload.node_id,
            payload.asset_id,
            client=rt.user_client(user),
            start=_utc(payload.start),
            end=_utc(payload.end),
            timing=payload.timing or AssetTiming(),
            models=rt.model_runtime(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # PlantCraft unreachable or refusing: say so, never a 500
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _utc(moment: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(moment)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def _test_on_asset(payload: TestPayload, user: Any, rt: Any) -> dict[str, Any]:
    """A test of an algorithm on assets: one run on the asset's window ending now, as the user."""

    timing = payload.timing or AssetTiming()
    moment = pd.Timestamp(payload.end) if payload.end else pd.Timestamp.now(tz="UTC")
    end = window_end(moment, timing.step_seconds)
    try:
        found = run_on_asset(
            payload.diagram,
            str(payload.asset_id),
            client=rt.user_client(user),
            start=end - pd.Timedelta(seconds=timing.window_seconds),
            end=end,
            step=timing.step_seconds,
            models=rt.model_runtime(),
            algorithm_id="test",
            with_trace=True,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # PlantCraft unreachable or refusing: say so, never a 500
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    summary = found["summary"]
    return {
        "asset_id": found["asset"]["id"],
        "asset_name": found["asset"]["name"],
        "summary": {
            key: summary.get(key) for key in ("outputs", "blocks", "verdict", "signals", "window")
        },
        "trace": found.get("trace") or {},
    }


def _subject_problems(subject_kind: str, plan: Any) -> list[str]:
    """What an algorithm's subject forbids: a loop health off loops, models off assets."""

    problems = []
    if subject_kind != "loop" and plan.blocks_of("output.loop_health"):
        problems.append(t("Only an algorithm on loops has a Loop health block."))
    models = [
        node_id
        for node_id, node in plan.nodes.items()
        if str(node.get("block") or "").startswith(f"{MODEL_LIBRARY}.")
    ]
    if subject_kind != "asset" and models:
        problems.append(t("Model blocks run in algorithms on assets."))
    return problems


@router.put("/api/algorithms/{algorithm_id}")
def save_algorithm(
    algorithm_id: str, payload: AlgorithmPayload, user: EditorUser, rt: RuntimeDep
) -> dict[str, Any]:
    if algorithm_id != payload.algorithm_id:
        raise HTTPException(status_code=422, detail=t("Mismatched identifier."))
    existing = rt.presets.get_profile(algorithm_id)
    if existing and (existing.get("system") or existing["profile_id"] != algorithm_id):
        raise HTTPException(
            status_code=409,
            detail=t("Analytics' algorithms are read-only: duplicate it and change the copy."),
        )
    groups = _groups(rt, user)
    if existing and not may_edit(user, existing, groups):
        raise HTTPException(status_code=403, detail=_read_only(existing, groups))
    plan = compile_algorithm(payload.diagram)
    if plan.errors:
        raise HTTPException(status_code=422, detail=" ".join(plan.errors))
    problems = _subject_problems(payload.subject_kind, plan)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    docs = payload.docs.model_dump()
    assets = list(dict.fromkeys(item.strip() for item in payload.assets if item.strip()))
    config = method_config(
        payload.diagram,
        docs,
        payload.subject_kind,
        timing=payload.timing.model_dump(),
        assets=assets,
        compute=payload.compute.model_dump(),
    )
    before = (existing or {}).get("method_config") or {}
    rt.presets.save_profile(
        profile_id=algorithm_id,
        name=payload.name,
        description=payload.description,
        method_config=config,
        author=user.name or user.username,
        owner=None if existing else user.username,
        owner_name=None if existing else (user.name or user.username),
        tags=payload.tags,
        group_id=payload.group_id,
        version_name=payload.version_name.strip(),
        version_note=payload.version_note.strip(),
    )
    rt.audit(
        user,
        "algorithm.saved",
        f"algorithm:{algorithm_id}",
        {"method_ids": config["method_ids"], "blocks": len(plan.nodes)},
    )
    saved = rt.presets.get_profile(algorithm_id)
    if payload.subject_kind == "asset":
        # Assets taken out lose their runs; a changed diagram starts its blocks' memory afresh.
        rt.asset_runs.forget(algorithm_id, set(assets))
        if before.get("diagram") != config["diagram"]:
            rt.asset_runs.reset_states(algorithm_id)
    else:
        rt.asset_runs.forget(algorithm_id)
    _refresh_schedules(rt, algorithm_id, saved)
    rt.publish_algorithms([saved])
    found = _algorithm(saved, user=user, groups=groups)
    # What people have not written yet (the generated text stands in); saving never waits.
    found["docs_problems"] = check_algorithm(payload.name, docs)
    return found


@router.delete("/api/algorithms/{algorithm_id}", status_code=204)
def delete_algorithm(algorithm_id: str, user: EditorUser, rt: RuntimeDep) -> None:
    existing = _get(rt, algorithm_id)
    if existing.get("system") or algorithm_id == SIGNAL_QUALITY:
        raise HTTPException(status_code=409, detail=t("Analytics' algorithms cannot be deleted."))
    groups = _groups(rt, user)
    if not may_edit(user, existing, groups):
        raise HTTPException(status_code=403, detail=_read_only(existing, groups))
    used = [loop.loop_id for loop in rt.loops.list_loops() if loop.profile_id == algorithm_id]
    scheduled = [
        item["schedule_id"]
        for item in rt.jobs.list_schedules()
        if item.get("profile_id") == algorithm_id
    ]
    if used or scheduled:
        raise HTTPException(
            status_code=409,
            detail=t(
                "In use by {loops} loops and {schedules} monitors: change them first.",
                loops=len(used),
                schedules=len(scheduled),
            ),
        )
    rt.presets.delete_profile(algorithm_id)
    rt.asset_runs.forget(algorithm_id)
    rt.folders.forget("algorithm", algorithm_id)
    rt.audit(user, "algorithm.deleted", f"algorithm:{algorithm_id}", {})


@router.get("/api/algorithms/{algorithm_id}/runs")
def algorithm_runs(algorithm_id: str, _user: CurrentUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """The latest run of an algorithm on assets on each of its assets."""

    _get(rt, algorithm_id)
    return [asset_run_row(row) for row in rt.asset_runs.list(algorithm_id)]


@router.post("/api/algorithms/{algorithm_id}/run")
def run_algorithm_now(algorithm_id: str, user: EditorUser, rt: RuntimeDep) -> list[dict[str, Any]]:
    """Run an algorithm on assets on every one of its assets now, and publish."""

    profile = _get(rt, algorithm_id)
    if (profile.get("method_config") or {}).get("subject_kind") != "asset":
        raise HTTPException(status_code=409, detail=t("Only an algorithm on assets runs here."))
    job_ids = rt.queue_asset_runs(profile, user=user.username)
    rt.wait_for(job_ids, RUN_WAIT_SECONDS)
    rt.audit(user, "algorithm.run", f"algorithm:{algorithm_id}", {"assets": len(job_ids)})
    assets = set((profile.get("method_config") or {}).get("assets") or [])
    return [
        asset_run_row(row) for row in rt.asset_runs.list(algorithm_id) if row["asset_id"] in assets
    ]


def asset_run_row(row: dict[str, Any]) -> dict[str, Any]:
    """One algorithm's latest run on one asset, as the pages read it (no blocks' memory)."""

    summary = row.get("summary") or {}
    return {
        "algorithm_id": row["algorithm_id"],
        "asset_id": row["asset_id"],
        "asset_name": row.get("asset_name") or row["asset_id"],
        "status": row.get("status") or "unknown",
        "value": row.get("value"),
        "message": row.get("message") or "",
        "error": row.get("error"),
        "analyzed_at": row.get("analyzed_at"),
        "window_end": row.get("window_end"),
        "outputs": summary.get("outputs") or [],
        "blocks": summary.get("blocks") or {},
    }


def _refresh_schedules(rt: Any, profile_id: str, profile: dict[str, Any]) -> None:
    """The algorithm's schedules run the diagram as saved now, not as it was when scheduled."""

    changed = False
    for schedule in rt.jobs.list_schedules():
        if schedule.get("profile_id") != profile_id or schedule.get("kind") == "round":
            continue
        loop = rt.loops.get_loop(schedule["loop_id"]) if schedule.get("selector") is None else None
        config = (
            rt.loops.effective_method_config(loop, profile_id=profile_id)
            if loop is not None
            else {**(profile.get("method_config") or {}), "profile_id": profile_id}
        )
        rt.jobs.update_schedule(schedule["schedule_id"], method_config=config)
        changed = True
    if changed:
        rt.publish_schedules()
