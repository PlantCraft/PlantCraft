"""Third-party multivariable controllers (APC), read only: health (A16) and the cost of each
active constraint (A17), from the controller's own signals (``engine.apc``).

The controllers and their MVs and CVs are the assets of types ``apc``, ``apc_mv`` and ``apc_cv``
that the person sees; their signals are read as that person. Nothing is written to the plant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from plantcraft_sdk.client import PlantCraftError

from linkcraft.api.deps import CurrentUser, RuntimeDep
from linkcraft.data.samples import SignalReader, iso_utc, naive_utc
from linkcraft.engine.apc import Controller, assess, controllers, grid, step_for
from linkcraft.i18n import t

router = APIRouter(prefix="/api")

# How far before the window a signal's last sample is looked for: a historian keeps a limit
# that did not move as one old sample, and the window holds that value.
LOOKBACK = pd.Timedelta(days=1)


def read_controllers(
    reader: SignalReader,
    found: list[Controller],
    days: float,
    until: datetime | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp, list[dict[str, Any]]]:
    """Each controller assessed over the ``days`` before ``until`` (the newest data)."""

    wanted = [signal for item in found for signal in item.signal_ids()]
    end = naive_utc(until) if until is not None else reader.data_end(wanted)
    start = end - pd.Timedelta(days=days)
    step = step_for((end - start).total_seconds())
    samples = reader.read(wanted, start - LOOKBACK, end, fallback_step=step)
    rows = []
    for item in found:
        series = {
            signal: samples.series[signal]
            for signal in item.signal_ids()
            if signal in samples.series
        }
        row = assess(item, grid(series, start, end, step), step)
        row["failed"] = sorted(signal for signal in item.signal_ids() if signal in samples.failed)
        rows.append(row)
    return start, end, rows


def _controllers(reader: SignalReader) -> list[Controller]:
    try:
        return controllers(reader.assets())
    except PlantCraftError as exc:
        raise HTTPException(status_code=502, detail=str(exc.detail)) from exc


def apc_rows(user: Any, rt: Any, days: float, until: datetime | None = None) -> dict[str, Any]:
    reader = rt.user_signal_reader(user)
    found = _controllers(reader)
    if not found:
        return {"since": None, "until": None, "controllers": []}
    start, end, rows = read_controllers(reader, found, days, until)
    return {"since": iso_utc(start), "until": iso_utc(end), "controllers": rows}


@router.get("/apc")
def apc_list(
    user: CurrentUser,
    rt: RuntimeDep,
    days: float = Query(default=1, gt=0, le=31),
    until: datetime | None = None,
) -> dict[str, Any]:
    """Every multivariable controller the person sees: on, MVs in service, CVs at a limit."""

    answer = apc_rows(user, rt, days, until)
    for row in answer["controllers"]:
        # The list carries the figures; one controller's page carries its variables.
        row.pop("variables")
        row["constraints"] = row["constraints"][:5]
    return answer


@router.get("/apc/{controller_id}")
def apc_one(
    controller_id: str,
    user: CurrentUser,
    rt: RuntimeDep,
    days: float = Query(default=1, gt=0, le=31),
    until: datetime | None = None,
) -> dict[str, Any]:
    """One controller: its figures, each MV and CV, and its active constraints by cost."""

    reader = rt.user_signal_reader(user)
    found = [item for item in _controllers(reader) if item.id == controller_id]
    if not found:
        raise HTTPException(status_code=404, detail=t("Controller not found."))
    start, end, rows = read_controllers(reader, found, days, until)
    return {"since": iso_utc(start), "until": iso_utc(end), **rows[0]}
