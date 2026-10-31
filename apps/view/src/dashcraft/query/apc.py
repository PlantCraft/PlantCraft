"""A multivariable controller (APC) panel, read only (V10 of the 0.6 gaps, 2026-10-31).

A third-party APC (Pavilion8, DMC3, Profit Controller, an MPC of one's own) is described in the
asset model, with the names the suite agreed on for every app that reads it (Analytics' APC
health and active constraint cost read the same ones):

- an asset of kind ``apc`` ("Multivariable controller"), with the roles ``on`` (1: on and
  controlling) and ``mode``, and the attributes ``vendor`` and ``cost_unit``;
- under it, assets of kind ``apc_mv`` (manipulated variables) and ``apc_cv`` (controlled
  variables), each with the roles ``value``, ``lo``, ``hi``, ``target`` (the steady-state
  target), ``status`` (1: in service) and ``shadow_price`` (the cost of its constraint per unit,
  when the APC exports it), and the optional attribute ``limit_band`` (engineering units).

The panel shows each variable's value, limits and target now, and its value and target over
the panel's window (its horizon), and marks the variables at a limit: the target (else the
value) within ``limit_band`` of ``lo`` or ``hi`` (1 % of ``hi - lo`` by default). View never
writes to the controller.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from plantcraft_sdk.client import PlantCraftError

from dashcraft.dashboards.model import window_seconds
from dashcraft.i18n import t

APC_KIND = "apc"
MV_KIND = "apc_mv"
CV_KIND = "apc_cv"
VARIABLE_ROLES = ("value", "lo", "hi", "target", "status", "shadow_price")
CONTROLLER_ROLES = ("on", "mode")
# The horizon's lines: the value and the target; points per line.
HORIZON_ROLES = ("value", "target")
HORIZON_POINTS = 120
MAX_VARIABLES = 40
DEFAULT_BAND = 0.01


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def at_limit(variable: dict[str, Any], band: float | None = None) -> str | None:
    """``lo`` or ``hi`` when the variable's target (else its value) is within ``band`` of that
    limit; None inside the limits or without both of them."""

    lo, hi = _number(variable.get("lo")), _number(variable.get("hi"))
    point = _number(variable.get("target"))
    if point is None:
        point = _number(variable.get("value"))
    if lo is None or hi is None or point is None or hi <= lo:
        return None
    width = band if band is not None and band >= 0 else DEFAULT_BAND * (hi - lo)
    if point <= lo + width:
        return "lo"
    if point >= hi - width:
        return "hi"
    return None


def _band(asset: dict[str, Any]) -> float | None:
    return _number((asset.get("attributes") or {}).get("limit_band"))


def read_apc(reader: Any, asset_id: str, window: str) -> dict[str, Any]:
    """The controller now and over ``window``: ``{controller, variables, at_limits, error}``.

    ``variables`` are its MVs then its CVs, by name; each has its value, limits, target,
    status, shadow price and unit now, ``at_limit`` (lo, hi or None), and ``t``/``value_line``
    /``target_line`` over the window. A signal that cannot be read is left empty."""

    try:
        apc = reader.asset(asset_id)
    except PlantCraftError as exc:
        return {"error": t("The controller cannot be read: {detail}", detail=exc.detail)}
    if not apc or apc.get("kind") != APC_KIND:
        return {"error": t("{asset} is not a multivariable controller.", asset=asset_id)}
    children: list[tuple[str, dict[str, Any]]] = []
    for kind, label in ((MV_KIND, "mv"), (CV_KIND, "cv")):
        found = [a for a in reader.assets(kind) or [] if a.get("parent_id") == apc.get("id")]
        found.sort(key=lambda a: str(a.get("name") or a.get("id")))
        children.extend((label, a) for a in found)
    children = children[:MAX_VARIABLES]

    apc_signals = apc.get("signals") or {}
    wanted = [apc_signals[r] for r in CONTROLLER_ROLES if apc_signals.get(r)]
    for _, child in children:
        signals = child.get("signals") or {}
        wanted.extend(signals[r] for r in VARIABLE_ROLES if signals.get(r))
    wanted = list(dict.fromkeys(wanted))
    seconds = window_seconds(window)
    now = reader.recent(wanted, seconds) if wanted else {}

    def latest(signals: dict[str, str], role: str) -> Any:
        found = now.get(signals.get(role) or "")
        return found["value"] if found else None

    lines = [
        (child.get("signals") or {}).get(role)
        for _, child in children
        for role in HORIZON_ROLES
        if (child.get("signals") or {}).get(role)
    ]
    series: dict[str, dict[str, Any]] = {}
    end = reader.clock()
    if lines:
        step = max(1, seconds // HORIZON_POINTS)
        try:
            batch = reader.series(lines, end - timedelta(seconds=seconds), end, step)
        except PlantCraftError:
            batch = {}
        series = {str(item.get("signal")): item for item in batch.get("series") or []}

    variables = []
    for label, child in children:
        signals = child.get("signals") or {}
        item: dict[str, Any] = {
            "id": child.get("id"),
            "name": str(child.get("name") or child.get("id")),
            "type": label,
            "description": str((child.get("attributes") or {}).get("description") or ""),
            "unit": str((child.get("attributes") or {}).get("unit") or ""),
            **{role: latest(signals, role) for role in VARIABLE_ROLES},
            "missing": [role for role in ("value", "lo", "hi") if not signals.get(role)],
        }
        status = _number(item["status"])
        item["in_service"] = None if status is None else status >= 0.5
        item["at_limit"] = at_limit(item, _band(child))
        value_series = series.get(signals.get("value") or "") or {}
        target_series = series.get(signals.get("target") or "") or {}
        item["t"] = value_series.get("t") or target_series.get("t") or []
        item["value_line"] = value_series.get("v") or []
        item["target_t"] = target_series.get("t") or []
        item["target_line"] = target_series.get("v") or []
        variables.append(item)

    on = _number(latest(apc_signals, "on"))
    attributes = apc.get("attributes") or {}
    return {
        "controller": {
            "id": apc.get("id"),
            "name": str(apc.get("name") or apc.get("id")),
            "on": None if on is None else on >= 0.5,
            "mode": latest(apc_signals, "mode"),
            "vendor": str(attributes.get("vendor") or ""),
            "cost_unit": str(attributes.get("cost_unit") or ""),
        },
        "variables": variables,
        "counts": {
            "mv": sum(v["type"] == "mv" for v in variables),
            "cv": sum(v["type"] == "cv" for v in variables),
            "in_service": sum(v["in_service"] is True for v in variables),
            "at_limits": sum(bool(v["at_limit"]) for v in variables),
        },
        "error": None,
    }
