"""The catalog of every block, and the checks an algorithm passes before it runs."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from plantcraft_sdk.blocks import Block, Plan, compile_diagram, describe_block, label_of

from linkcraft.blocks import (
    checks,
    conditions,
    equipment,
    estimators,
    inputs,
    logic,
    methods,
    models,
    outputs,
    reconciliation,
    site,
    stats,
    transforms,
)
from linkcraft.blocks.base import LIBRARIES
from linkcraft.blocks.files import split_pinned
from linkcraft.catalog.registry import gate_method_ids
from linkcraft.i18n import t
from linkcraft.models.builtin import builtin_models

GATE_ID = methods.GATE_ID
HEALTH_ID = "output.loop_health"
SIGNAL_OUTPUT_ID = "output.signal_quality"


class Catalog(dict[str, Block]):
    """The blocks by id. A version of a site block this process has not loaded yet is read from
    the blocks folder on first use (``blocks.site``), so worker processes run what the server
    saved."""

    def __missing__(self, block_id: str) -> Block:
        found = site.load(block_id) if isinstance(block_id, str) else None
        if found is None:
            raise KeyError(block_id)
        self[block_id] = found
        return found

    def get(self, block_id: Any, default: Any = None) -> Any:  # noqa: ANN401
        try:
            return self[block_id]
        except KeyError:
            return default

    def __contains__(self, block_id: object) -> bool:
        return self.get(block_id) is not None


CATALOG: Catalog = Catalog(
    (block.spec.block_id, block)
    for block in (
        *inputs.BLOCKS,
        *methods.BLOCKS[:1],
        *checks.BLOCKS,
        *transforms.BLOCKS,
        *estimators.BLOCKS,
        *reconciliation.BLOCKS,
        *stats.BLOCKS,
        *equipment.BLOCKS,
        *methods.BLOCKS[1:],
        *models.BLOCKS,
        *conditions.BLOCKS,
        *logic.BLOCKS,
        *outputs.BLOCKS,
    )
)
# The blocks Link ships (the others are site blocks and models).
BUILTIN_IDS = frozenset(CATALOG)
# Every site block's current version, by block id (``custom.ua_drift`` -> ``custom.ua_drift.v3``),
# kept by ``blocks.store``.
CURRENT: dict[str, str] = {}


def register_models(published: list[dict[str, Any]]) -> list[str]:
    """Put one block per published model in the catalog, and take out the models removed.

    Called at start and whenever a model is published, renamed or deleted, so the palette, the
    check and every run see the same blocks. Returns the ids of the model blocks now listed.
    """

    wanted: dict[str, Block] = {}
    for model in published:
        block = models.model_block(model)
        wanted[block.spec.block_id] = block
    for block_id in [key for key in CATALOG if key.startswith(models.PREFIX)]:
        if block_id not in wanted:
            del CATALOG[block_id]
    CATALOG.update(wanted)
    return sorted(wanted)


# The shipped models are in the catalog from the start (a store adds the ones people publish).
register_models(builtin_models())


def method_of(block_id: str) -> str | None:
    """The method a CPM block runs (``cpm.stiction_screening`` -> ``stiction_screening``)."""

    return block_id.removeprefix("cpm.") if block_id.startswith("cpm.") else None


def node_for_method(method_id: str) -> str:
    """The block a method id of the old protocols becomes."""

    if method_id in gate_method_ids():
        return GATE_ID
    return methods.block_id(method_id)


Layers = Mapping[str, Mapping[str, Any]]


def _layer(layers: Layers | None, block: str) -> dict[str, Any]:
    """What a layer keyed by method id says about one block's parameters."""

    found: dict[str, Any] = {}
    if not layers:
        return found
    if block == GATE_ID:
        for method_id in gate_method_ids():
            found.update(layers.get(method_id) or {})
    elif method_of(block):
        found.update(layers.get(str(method_of(block))) or {})
    return found


def _overridden(
    diagram: Mapping[str, Any], overrides: Layers | None, defaults: Layers | None
) -> dict[str, Any]:
    """The diagram with each method's parameters layered: ``defaults`` < diagram < ``overrides``.

    ``defaults`` are the site's method defaults and the loop type's; ``overrides`` the loop's
    own and a run's (``loops.store.effective_method_config``). All are keyed by method id.
    """

    found = copy.deepcopy(dict(diagram))
    if not overrides and not defaults:
        return found
    for node in found.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        block = str(node.get("block") or "")
        below, above = _layer(defaults, block), _layer(overrides, block)
        if below or above:
            node["parameters"] = {**below, **dict(node.get("parameters") or {}), **above}
    return found


def compile_algorithm(
    diagram: Mapping[str, Any],
    overrides: Layers | None = None,
    catalog: Mapping[str, Block] = CATALOG,
    *,
    defaults: Layers | None = None,
) -> Plan:
    """Check an algorithm's diagram for Link: the SDK's checks plus Link's own rules."""

    sinks: Callable[[Block], bool] = lambda block: block.spec.library == "output"  # noqa: E731
    plan = compile_diagram(_overridden(diagram, overrides, defaults), catalog, sinks=sinks)
    if any(plan.recorded.values()):
        # Recording a port is an output of its own.
        plan.errors = [item for item in plan.errors if "has no output:" not in item]
    health = [node_id for node_id, node in plan.nodes.items() if node.get("block") == HEALTH_ID]
    for node_id in health[1:]:
        message = t("An algorithm has one Loop health block.")
        plan.errors.append(message)
        plan.node_errors.setdefault(node_id, []).append(message)
    names: dict[str, str] = {}
    for node_id, node in plan.nodes.items():
        if node.get("block") != "output.result":
            continue
        name = str((node.get("parameters") or {}).get("name") or "").strip()
        key = outputs.output_key(name)
        label = label_of(node, catalog)
        if not key:
            message = t("{block}: give it a name.", block=label)
        elif key in names:
            message = t("Two outputs are called {name}; give each its own name.", name=name)
        else:
            names[key] = node_id
            continue
        plan.errors.append(message)
        plan.node_errors.setdefault(node_id, []).append(message)
    return plan


def listed(block_id: str) -> bool:
    """Whether the palette lists a block: a site block's current version only, no draft."""

    if block_id.startswith(f"{site.DRAFT_LIBRARY}."):
        return False
    pinned = split_pinned(block_id)
    if pinned is None:
        # A block Link ships that the site has edited is listed by the site's current version.
        return block_id not in CURRENT
    return CURRENT.get(pinned[0]) == block_id


def catalog_items(translate: Callable[..., str] = t) -> list[dict[str, Any]]:
    """Every block as the editor's palette and inspector read it."""

    return [
        describe_block(block.spec, translate)
        for block_id, block in list(CATALOG.items())
        if listed(block_id)
    ]


def libraries(
    translate: Callable[..., str] = t, site: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Link's libraries in the palette's order, with the ones made on this site (``site``,
    ``BlockStore.libraries``) before Outputs; a block in a library no longer listed there keeps
    one under its id."""

    counts: dict[str, int] = {}
    for block_id, block in list(CATALOG.items()):
        if listed(block_id):
            counts[block.spec.library] = counts.get(block.spec.library, 0) + 1
    shipped = [
        {
            "library": key,
            "name": translate(item["name"]),
            "description": translate(item["description"]),
            "count": counts.get(key, 0),
            "site": False,
        }
        for key, item in LIBRARIES.items()
    ]
    made = {
        str(item["library"]): {
            "library": str(item["library"]),
            "name": str(item.get("name") or item["library"]),
            "description": str(item.get("description") or ""),
            "count": counts.get(str(item["library"]), 0),
            "site": True,
        }
        for item in site or []
    }
    for key, count in counts.items():
        if key not in LIBRARIES and key not in made:
            made[key] = {
                "library": key,
                "name": key,
                "description": "",
                "count": count,
                "site": True,
            }
    *first, last = shipped
    return (
        [*first, *made.values(), last]
        if last["library"] == "output"
        else [*shipped, *made.values()]
    )
