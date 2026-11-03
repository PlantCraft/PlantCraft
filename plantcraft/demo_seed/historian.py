"""Historian: the Simulator's last 48 hours archived, the lab's analyses (a CSV source), a
finished test run imported and the calculated signals."""

from __future__ import annotations

import time
from typing import Any

from .base import Http, SeedError, Suite, _items, log, wait_until

# Historian ------------------------------------------------------------------------------------

# The Simulator simulates 48 hours before it starts; copying them takes a minute or two.
BACKFILL_HOURS = 48
BACKFILL_WAIT = 900.0
SOURCE_FIELDS = (
    "id",
    "name",
    "kind",
    "endpoint",
    "namespace_uri",
    "username",
    "password_env",
    "enabled",
    "options",
    "retention_days",
    "default_scan_seconds",
    "default_deviation_percent",
    "default_max_seconds",
)


def histcraft(hist: Http, suite: Suite) -> None:
    """The Simulator's 48 simulated hours before the demo started copied from its own OPC UA
    history into Historian's archive (a backfill), so every app has a history on the first visit
    and reads it from the archive. A Historian without backfill reads them from the source
    (mode ``both``)."""

    def source() -> dict[str, Any] | None:
        listed = _items(hist.get("/api/sources"), "sources")
        found = next((item for item in listed if item.get("id") == "plantcraft"), None)
        return found if found and found.get("points") else None

    found = wait_until("The Simulator's signals in Historian", source, suite.wait)
    began = time.monotonic()
    status, queued = hist.call(
        "POST", "/api/sources/plantcraft/backfill", {"hours": BACKFILL_HOURS}, ok=(404, 405)
    )
    answer: dict[str, Any] = {}
    if status == 202:
        request = queued["request"]

        def finished() -> dict[str, Any] | None:
            got = hist.get(f"/api/requests/{request}")
            return got if got.get("status") != "pending" else None

        try:
            answer = wait_until(
                "Historian's backfill of the Simulator", finished, max(suite.wait, BACKFILL_WAIT)
            )
        except SeedError as error:
            answer = {"result": {"detail": str(error)}}
    body = {key: found[key] for key in SOURCE_FIELDS if key in found}
    if answer.get("status") == "ok":
        if found.get("mode") == "both":
            hist.put("/api/sources/plantcraft", {**body, "mode": "", "password": None})
        result = answer.get("result") or {}
        log(
            f"Historian: {result.get('values', 0)} values of the Simulator's last {BACKFILL_HOURS} "
            f"hours archived ({result.get('signals', 0)} signals) in "
            f"{time.monotonic() - began:.0f} s"
        )
        return
    if found.get("mode") != "both":
        hist.put("/api/sources/plantcraft", {**body, "mode": "both", "password": None})
    detail = (answer.get("result") or {}).get("detail") or "no backfill in this Historian"
    log(f"Historian: the Simulator's history read from the source ({detail})")


# The lab's analyses: a second type of source (a CSV file) beside the Simulator's OPC UA server.
LAB_SOURCE = "lab"
LAB_DAYS = 30
LAB_EVERY_HOURS = 4
# Tag, name, unit, nominal value, spread (one sigma), slow drift over the month.
LAB_TAGS = (
    ("LAB-U100.CRUDE.BSW", "Crude to the unit, water and sediment", "% vol", 0.35, 0.08, 0.1),
    ("LAB-U100.DIESEL.SULFUR", "Diesel S10, sulfur", "mg/kg", 7.2, 0.9, 1.5),
    ("LAB-U100.DIESEL.DENSITY", "Diesel S10, density at 20 °C", "kg/m³", 836.0, 1.8, 2.0),
    ("LAB-U100.DIESEL.FLASH", "Diesel S10, flash point", "°C", 46.0, 1.2, -1.0),
    ("LAB-U100.NAPHTHA.RVP", "Light naphtha, Reid vapour pressure", "kPa", 62.0, 2.5, 3.0),
)


def lab_csv(now: float | None = None) -> bytes:
    """The lab's analyses of the last month, one sample every four hours, as the LIMS exports
    them: a wide CSV, the time in UTC first, one column per analysis. Simulated like the plant
    (a fixed seed: the same month always gives the same values); an analysis is now and then
    skipped, as in a real lab."""

    import math
    import random

    rng = random.Random(20261022)
    step = LAB_EVERY_HOURS * 3600
    end = int((now if now is not None else time.time()) // step * step)
    start = end - LAB_DAYS * 86400
    lines = ["time," + ",".join(tag for tag, *_ in LAB_TAGS)]
    for stamp in range(start + step, end + 1, step):
        share = (stamp - start) / (end - start)
        cells = []
        for _tag, _name, _unit, nominal, spread, drift in LAB_TAGS:
            value = nominal + drift * share + spread * rng.gauss(0, 1)
            value += 0.5 * spread * math.sin(2 * math.pi * stamp / 86400)
            cells.append("" if rng.random() < 0.04 else f"{value:.4g}")
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))
        lines.append(when + "," + ",".join(cells))
    return ("\n".join(lines) + "\n").encode()


IMPORT_FILE = "pilot-test-run-2026-09.csv"
# Tag and nominal value of the pilot unit's test run, a one-off file kept as an import.
IMPORT_TAGS = (
    ("PILOT.TI-201", 182.0),
    ("PILOT.PI-202", 4.6),
    ("PILOT.FI-203", 12.5),
)


def import_csv() -> bytes:
    """Six hours of a past test run, one row a minute, the same values every time."""

    import calendar
    import math
    import random

    rng = random.Random(20260915)
    start = calendar.timegm((2026, 9, 15, 8, 0, 0))
    lines = ["time," + ",".join(tag for tag, _ in IMPORT_TAGS)]
    for minute in range(6 * 60):
        cells = [
            f"{nominal * (1 + 0.04 * math.sin(minute / 45)) + 0.01 * nominal * rng.gauss(0, 1):.4g}"
            for _tag, nominal in IMPORT_TAGS
        ]
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + 60 * minute))
        lines.append(when + "," + ",".join(cells))
    return ("\n".join(lines) + "\n").encode()


def histcraft_import(hist: Http) -> None:
    """A finished test run's CSV, imported once as an example of Import & export. A Historian
    without imports skips it."""

    status, listed = hist.call("GET", "/api/imports", ok=(404,))
    if status == 404:
        log("Historian: no imports in this version, the example import is skipped")
        return
    if any(item.get("file_name") == IMPORT_FILE for item in listed or []):
        return
    checked = hist.post(
        # The file's times carry their offset (Z): the zone only names naive ones.
        f"/api/imports/check?name={IMPORT_FILE}&timezone=UTC",
        raw=import_csv(),
        content_type="text/csv",
    )
    if not checked.get("ok"):
        raise SeedError(f"Historian: the example import has errors: {checked.get('report')}")
    done = hist.post(
        "/api/imports", {"token": checked["token"], "name": "Pilot unit test run (Sep 2026)"}
    )
    log(f"Historian: example import {done['id']} ({checked['report'].get('values', 0)} values)")


def histcraft_lab(hist: Http) -> None:
    """The lab's CSV sent to Historian (the same file name refreshes it) and read as the source
    ``lab``, with its five analyses as points. A Historian without file upload skips it."""

    status, sent = hist.call(
        "POST",
        "/api/sources/files?name=lab-analyses.csv",
        raw=lab_csv(),
        content_type="text/csv",
        ok=(404, 405),
    )
    if status != 201:
        log("Historian: no file upload in this version, the lab's CSV is skipped")
        return
    listed = _items(hist.get("/api/sources"), "sources")
    if not any(item.get("id") == LAB_SOURCE for item in listed):
        hist.post(
            "/api/sources",
            {
                "id": LAB_SOURCE,
                "name": "Laboratory (LIMS export)",
                "kind": "csv",
                "endpoint": sent["path"],
                "options": {"timezone": "UTC"},
                "mode": "",
                "password": None,
                "enabled": True,
            },
        )
    points = [
        {
            "tag": tag,
            "source_id": LAB_SOURCE,
            "address": tag,
            "name": name,
            "description": name,
            "unit": unit,
            "kind": "number",
        }
        for tag, name, unit, *_ in LAB_TAGS
    ]
    added = hist.post("/api/points", {"points": points})
    log(
        f"Historian: the lab's CSV ({sent.get('rows', 0)} samples), "
        f"{len(added.get('added') or [])} new analyses"
    )


# Calculated signals (Historian's source ``calc``): one of each kind a person makes, a sum, a
# deviation from setpoint, a unit conversion and a totalizer, on the Simulator's archived tags.
# Tag, formula, unit, description.
CALC_SIGNALS = (
    (
        "U100.FEED.TOTAL",
        "[plantcraft:CPM.Loops.FIC-1001.PV] + [plantcraft:CPM.Loops.FIC-1007.PV]",
        "m³/h",
        "Total feed to the unit: feed flow plus charge flow",
    ),
    (
        "TIC-1209.DEV",
        "[plantcraft:CPM.Loops.TIC-1209.PV] - [plantcraft:CPM.Loops.TIC-1209.SP]",
        "°C",
        "Furnace outlet temperature, deviation from its setpoint (it drifts)",
    ),
    (
        "FIC-1210.KGH",
        "[plantcraft:CPM.Loops.FIC-1210.PV] * 0.8",
        "kg/h",
        "Fuel gas, mass flow (0.8 kg/Nm³)",
    ),
    (
        "FIC-1001.TODAY",
        'total([plantcraft:CPM.Loops.FIC-1001.PV], per="h", reset="day")',
        "m³",
        "Feed flow, total since midnight (UTC)",
    ),
)


def histcraft_calc(hist: Http) -> None:
    """The example calculated signals, added once (a signal that is there is skipped). A
    Historian without calculated signals, or without one of the inputs, skips them."""

    body = {
        "points": [
            {
                "source_id": "calc",
                "tag": tag,
                "address": formula,
                "unit": unit,
                "description": description,
                "name": description,
            }
            for tag, formula, unit, description in CALC_SIGNALS
        ]
    }
    status, done = hist.call("POST", "/api/points", body, ok=(400, 404, 422))
    if status not in (200, 201):
        log(
            f"Historian: no calculated signals in this version ({status}), the examples are skipped"
        )
        return
    skipped = [item for item in done.get("skipped") or [] if "exist" not in str(item).lower()]
    log(
        f"Historian: {len(done.get('added') or [])} example calculated signals"
        + (f", skipped {skipped}" if skipped else "")
    )
