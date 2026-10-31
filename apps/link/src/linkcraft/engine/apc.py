"""A third-party multivariable controller (APC/MPC), read only: its health (A16) and the cost
of each constraint it holds active (A17).

PlantCraft describes the controller with three asset types (``plantcraft_sdk.assets``):
``apc`` (the controller: role ``on``), and inside it ``apc_mv`` (what it moves) and ``apc_cv``
(what it holds), both with the roles ``value``, ``lo``, ``hi``, ``target``, ``status`` and
``shadow_price``. View's MV/CV widget reads the same names. Nothing here writes to the plant.

Every signal is held at its last sample (sample-and-hold, as a historian keeps a compressed
signal) on one regular grid of ``step`` seconds, and every share is a share of that grid's time:

- **On**: the time the controller's ``on`` signal is 1 (``>= 0.5``), of the time it is known.
- **In service**: for each variable, the time its ``status`` is 1 while the controller is on (a
  variable with no ``status`` counts as in service). The controller's figure is the mean over its
  MVs: an MV out of service is freedom the controller does not have.
- **At a limit**: a variable is at its low (high) limit when its steady-state ``target`` (its
  ``value`` when the vendor gives no target) is within ``limit_band`` of ``lo`` (``hi``); the band
  is the variable's own attribute, else 1 % of ``hi - lo``. Counted while the controller is on and
  the variable in service. A CV at a limit is the controller doing its job (pushing the plant
  against its constraints); it is the information an engineer reads, not a fault.
- **Constraint cost**: an active limit with a ``shadow_price`` (the vendor's marginal value of the
  limit: how much the objective improves, in the controller's ``cost_unit``, per unit the limit
  moves) is priced at its mean absolute shadow price while active. ``worth_1pct`` is what moving
  that limit by 1 % of the variable's range would be worth, the figure to rank constraints by.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

# The SDK's type ids (``plantcraft_sdk.assets.APC_*_TYPE``), here too so an installation whose
# admin made the types by hand, before the SDK had them, reads the same.
APC_TYPE = "apc"
APC_MV_TYPE = "apc_mv"
APC_CV_TYPE = "apc_cv"
ROLES = ("value", "lo", "hi", "target", "status", "shadow_price")
# The band that counts as "at a limit" when a variable has none: this share of hi - lo.
DEFAULT_BAND = 0.01
# A controller reads as in alarm (warning) when on less than this share of the time, or its MVs
# are in service less than it.
ALARM_SHARE = 50.0
WARNING_SHARE = 90.0
# At most this many grid points per read: the step grows with the window.
MAX_POINTS = 4000
MIN_STEP = 60.0


@dataclass
class Variable:
    id: str
    name: str
    kind: str  # "mv" or "cv"
    signals: dict[str, str]
    limit_band: float | None = None


@dataclass
class Controller:
    id: str
    name: str
    parent_id: str | None
    vendor: str
    cost_unit: str
    signals: dict[str, str]
    variables: list[Variable] = field(default_factory=list)

    def signal_ids(self) -> list[str]:
        found = [self.signals.get("on"), self.signals.get("mode")]
        for variable in self.variables:
            found += [variable.signals.get(role) for role in ROLES]
        return list(dict.fromkeys(item for item in found if item))


def _is(asset: dict[str, Any], type_id: str) -> bool:
    return type_id in (asset.get("type_path") or [asset.get("kind")])


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def controllers(assets: list[dict[str, Any]]) -> list[Controller]:
    """The plant's multivariable controllers, each with the MVs and CVs inside it (by name)."""

    found: dict[str, Controller] = {}
    for asset in assets:
        if _is(asset, APC_TYPE):
            attributes = asset.get("attributes") or {}
            found[asset["id"]] = Controller(
                id=asset["id"],
                name=asset.get("name") or asset["id"],
                parent_id=asset.get("parent_id"),
                vendor=str(attributes.get("vendor") or ""),
                cost_unit=str(attributes.get("cost_unit") or ""),
                signals=dict(asset.get("signals") or {}),
            )
    for asset in assets:
        kind = "mv" if _is(asset, APC_MV_TYPE) else "cv" if _is(asset, APC_CV_TYPE) else None
        owner = found.get(asset.get("parent_id") or "")
        if kind is None or owner is None:
            continue
        owner.variables.append(
            Variable(
                id=asset["id"],
                name=asset.get("name") or asset["id"],
                kind=kind,
                signals=dict(asset.get("signals") or {}),
                limit_band=_number((asset.get("attributes") or {}).get("limit_band")),
            )
        )
    for item in found.values():
        item.variables.sort(key=lambda variable: (variable.kind != "mv", variable.name.lower()))
    return sorted(found.values(), key=lambda item: item.name.lower())


def step_for(seconds: float) -> float:
    return max(MIN_STEP, math.ceil(seconds / MAX_POINTS / MIN_STEP) * MIN_STEP)


def grid(
    series: dict[str, pd.Series], start: pd.Timestamp, end: pd.Timestamp, step: float
) -> pd.DataFrame:
    """Every series held at its last sample on one grid of ``step`` seconds in ``[start, end)``."""

    index = pd.date_range(start, end, freq=pd.Timedelta(seconds=step), inclusive="left")
    columns: dict[str, pd.Series] = {}
    for signal_id, values in series.items():
        values = pd.to_numeric(values, errors="coerce").dropna().sort_index()
        values = values[~values.index.duplicated(keep="last")]
        if values.empty or index.empty:
            columns[signal_id] = pd.Series(float("nan"), index=index)
            continue
        columns[signal_id] = values.reindex(index, method="ffill")
    return pd.DataFrame(columns, index=index)


def _column(frame: pd.DataFrame, signal_id: str | None) -> pd.Series | None:
    if not signal_id or signal_id not in frame:
        return None
    return frame[signal_id]


def _share(part: pd.Series, whole: pd.Series) -> float | None:
    """The share (%) of ``whole``'s True points where ``part`` is also True."""

    total = int(whole.sum())
    return None if total == 0 else round(100.0 * int((part & whole).sum()) / total, 1)


def _last(values: pd.Series | None) -> float | None:
    if values is None:
        return None
    found = values.dropna()
    return None if found.empty else round(float(found.iloc[-1]), 6)


def _flag(values: pd.Series | None, index: pd.Index, default: bool) -> pd.Series:
    """A 0/1 signal as True/False; unknown points read as ``default``."""

    if values is None:
        return pd.Series(default, index=index)
    return (values >= 0.5).where(values.notna(), default).astype(bool)


@dataclass
class _Limits:
    at_lo: pd.Series
    at_hi: pd.Series
    span: float | None


def _limits(variable: Variable, frame: pd.DataFrame) -> _Limits:
    index = frame.index
    reference = _column(frame, variable.signals.get("target"))
    value = _column(frame, variable.signals.get("value"))
    if reference is None or reference.isna().all():
        reference = value
    lo = _column(frame, variable.signals.get("lo"))
    hi = _column(frame, variable.signals.get("hi"))
    span_series = (hi - lo) if lo is not None and hi is not None else None
    span = None
    if span_series is not None and span_series.notna().any():
        span = float(span_series.abs().median())
    if variable.limit_band is not None:
        band: pd.Series | float = variable.limit_band
    elif span_series is not None:
        band = (span_series.abs() * DEFAULT_BAND).fillna(0.0)
    else:
        # One limit only: 1 % of its own size.
        only = lo if lo is not None else hi
        band = (only.abs() * DEFAULT_BAND).fillna(0.0) if only is not None else 0.0
    false = pd.Series(False, index=index)
    if reference is None:
        return _Limits(false, false, span)
    at_lo = (reference <= lo + band).fillna(False) if lo is not None else false
    at_hi = (reference >= hi - band).fillna(False) if hi is not None else false
    return _Limits(at_lo.astype(bool), at_hi.astype(bool) & ~at_lo.astype(bool), span)


def _state(on: float | None, in_service: float | None) -> str | None:
    known = [value for value in (on, in_service) if value is not None]
    if not known:
        return None
    worst = min(known)
    return "alarm" if worst < ALARM_SHARE else "warning" if worst < WARNING_SHARE else "ok"


def assess(controller: Controller, frame: pd.DataFrame, step: float) -> dict[str, Any]:
    """The controller's health over the frame's window (A16) and its active constraints with
    their cost (A17)."""

    index = frame.index
    on_values = _column(frame, controller.signals.get("on"))
    known = on_values.notna() if on_values is not None else pd.Series(False, index=index)
    on = _flag(on_values, index, False) & known
    on_share = _share(on, known)
    hours = step / 3600.0
    variables: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    for variable in controller.variables:
        in_service = _flag(_column(frame, variable.signals.get("status")), index, True)
        active = on & in_service
        limits = _limits(variable, frame)
        now_lo, now_hi = bool(limits.at_lo.iloc[-1:].any()), bool(limits.at_hi.iloc[-1:].any())
        now_service = bool(in_service.iloc[-1:].all()) if len(index) else False
        row = {
            "id": variable.id,
            "name": variable.name,
            "kind": variable.kind,
            "signals": variable.signals,
            "value": _last(_column(frame, variable.signals.get("value"))),
            "lo": _last(_column(frame, variable.signals.get("lo"))),
            "hi": _last(_column(frame, variable.signals.get("hi"))),
            "target": _last(_column(frame, variable.signals.get("target"))),
            "shadow_price": _last(_column(frame, variable.signals.get("shadow_price"))),
            "in_service": now_service,
            "at": ("lo" if now_lo else "hi" if now_hi else None) if now_service else None,
            "in_service_pct": _share(in_service, on),
            "at_limit_pct": _share(limits.at_lo | limits.at_hi, active),
            "at_lo_pct": _share(limits.at_lo, active),
            "at_hi_pct": _share(limits.at_hi, active),
        }
        variables.append(row)
        price = _column(frame, variable.signals.get("shadow_price"))
        for side, mask in (("lo", limits.at_lo & active), ("hi", limits.at_hi & active)):
            points = int(mask.sum())
            if not points:
                continue
            cost = None
            if price is not None and price[mask].notna().any():
                cost = round(float(price[mask].abs().mean()), 6)
            worth = (
                round(cost * DEFAULT_BAND * limits.span, 6)
                if cost is not None and limits.span
                else None
            )
            constraints.append(
                {
                    "variable_id": variable.id,
                    "name": variable.name,
                    "kind": variable.kind,
                    "side": side,
                    "hours": round(points * hours, 2),
                    "share_pct": _share(mask, on),
                    "active_now": row["at"] == side and bool(on.iloc[-1:].all()),
                    "shadow_price": cost,
                    "worth_1pct": worth,
                }
            )
    constraints.sort(
        key=lambda item: (
            item["worth_1pct"] is None,
            -(item["worth_1pct"] or 0.0),
            -item["hours"],
            item["name"],
        )
    )
    mvs = [row for row in variables if row["kind"] == "mv"]
    cvs = [row for row in variables if row["kind"] == "cv"]
    service = [row["in_service_pct"] for row in mvs if row["in_service_pct"] is not None]
    mv_service = round(sum(service) / len(service), 1) if service else None
    at_limit = [row["at_limit_pct"] for row in cvs if row["at_limit_pct"] is not None]
    return {
        "id": controller.id,
        "name": controller.name,
        "parent_id": controller.parent_id,
        "vendor": controller.vendor,
        "cost_unit": controller.cost_unit,
        "summary": {
            "on_now": bool(on.iloc[-1:].all()) if len(index) else False,
            "on_pct": on_share,
            "mvs": len(mvs),
            "mvs_in_service": sum(1 for row in mvs if row["in_service"]),
            "mv_in_service_pct": mv_service,
            "cvs": len(cvs),
            "cvs_at_limit": sum(1 for row in cvs if row["at"]),
            "cv_at_limit_pct": round(sum(at_limit) / len(at_limit), 1) if at_limit else None,
            "constraints_active": sum(1 for item in constraints if item["active_now"]),
            "state": _state(on_share, mv_service),
        },
        "variables": variables,
        "constraints": constraints,
    }


__all__ = ["Controller", "Variable", "assess", "controllers", "grid", "step_for"]
