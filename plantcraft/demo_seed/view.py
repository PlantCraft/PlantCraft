"""View's dashboards: Plant overview (public link), Control room and Loop detail."""

from __future__ import annotations

from typing import Any

from .base import STICTION_LOOPS, Http, _ident, _items, log

# View ------------------------------------------------------------------------------------


def _kpi(card_id: str, title: str, loop_id: str) -> dict[str, Any]:
    """A loop's health (0-100) on a dial: red under 50, amber under 75."""

    return {
        "card_id": card_id,
        "title": title,
        "kind": "gauge",
        "items": [{"asset_id": loop_id, "result": "linkcraft.loop_health", "label": loop_id}],
        "agg": "last",
        "window": "1d",
        "gauge_min": 0,
        "gauge_max": 100,
        "thresholds": {"low_alarm": 50, "low_warn": 75},
        "decimals": 0,
        "width": 3,
        # View draws a dial at least 2 rows high (a card of 1 row is a number).
        "height": 2,
    }


def _scatter(card_id: str, title: str, loop_id: str) -> dict[str, Any]:
    """PV against OP: a sticky valve draws flat steps, a healthy loop a cloud along a line."""

    return {
        "card_id": card_id,
        "title": title,
        "kind": "scatter",
        "items": [
            {"asset_id": loop_id, "role": "op", "label": "OP"},
            {"asset_id": loop_id, "role": "pv", "label": "PV"},
        ],
        "window": "12h",
        "width": 6,
        "height": 2,
    }


def _note(card_id: str, text: str, width: int = 12) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "title": "",
        "kind": "text",
        "items": [],
        "text": text,
        "width": width,
    }


def _trend(card_id: str, title: str, loop_id: str, width: int = 6) -> dict[str, Any]:
    return {
        "card_id": card_id,
        "title": title,
        "kind": "trend",
        "items": [
            {"asset_id": loop_id, "role": "pv", "label": "PV"},
            {"asset_id": loop_id, "role": "sp", "label": "SP"},
            {"asset_id": loop_id, "role": "op", "label": "OP"},
        ],
        "agg": "mean",
        "window": "12h",
        "width": width,
        "height": 2,
    }


OVERVIEW = {
    "name": "Plant overview",
    "description": (
        "Demo: the health Analytics gives the loops with a problem, and their trends. "
        "FIC-1003 has a sticky valve, PIC-1202 oscillates, TIC-1209 drifts."
    ),
    "context_kind": "",
    "refresh_seconds": 60,
    "cards": [
        _note(
            "about",
            "Loop health from Analytics (0-100; red under 50, amber under 75) and the trends behind "
            "it. FIC-1003 has a sticky valve, PIC-1202 oscillates, TIC-1209 drifts; FIC-1001 "
            "is healthy, for comparison. Open a trend in full screen with its corner button.",
        ),
        _kpi("h1003", "Recycle flow FIC-1003", "FIC-1003"),
        _kpi("h1202", "Hydrotreater pressure PIC-1202", "PIC-1202"),
        _kpi("h1209", "Furnace outlet TIC-1209", "TIC-1209"),
        _kpi("h1001", "Feed flow FIC-1001 (healthy)", "FIC-1001"),
        _trend("t1003", "FIC-1003: the sticky valve's stick-slip", "FIC-1003"),
        _trend("t1202", "PIC-1202: oscillation from aggressive tuning", "PIC-1202"),
        _trend("t1209", "TIC-1209: slow sensor drift", "TIC-1209"),
        _trend("t1001", "FIC-1001: a healthy loop, for comparison", "FIC-1001"),
    ],
}


def _result_kpi(card_id: str, title: str, loop_id: str, result: str) -> dict[str, Any]:
    return {**_kpi(card_id, title, loop_id), "items": [{"asset_id": loop_id, "result": result}]}


# The area of the furnace loops (the plant map), where Analytics' Furnaces model algorithm runs, and
# the result kind of its "Model deviation" output.
FURNACE_AREA = "u-100-furnaces"
MODEL_DEVIATION = "linkcraft.out_model_deviation"

# View's folders: Operation for everyone, Control loops for its group (round 6, 2026-10-23; named
# Instrumentation until 2026-10-25, when the owner asked for Platform, Control loops and General).
OPERATION = {
    "name": "Operation",
    "description": "Screens for the control room and the shift; everyone sees them.",
    "viewers": [],
    "editors": [],
}
INSTRUMENTATION = {
    "name": "Control loops",
    "description": "Loop and valve diagnostics; only the Instrumentation and control group sees them.",
    "viewers": ["group:instrumentation"],
    "editors": [],
}


def _on(page: str, cards: Any) -> list[dict[str, Any]]:
    return [{**card, "page_id": page} for card in cards]


CONTROL_ROOM = {
    "name": "Control room",
    "description": (
        "Demo of a dashboard with pages: in full screen it turns from Overview to Loops to Valves "
        "every minute, without the toolbar (kiosk)."
    ),
    "context_kind": "",
    "refresh_seconds": 60,
    "pages": [
        {"page_id": "overview", "name": "Overview"},
        {"page_id": "loops", "name": "Loops"},
        {"page_id": "valves", "name": "Valves"},
    ],
    "page_seconds": 60,
    "tags": ["control room", "Unit 100"],
    "shared_cursor": True,
    "kiosk": True,
    "cards": [
        *_on(
            "overview",
            [
                _note(
                    "about",
                    "Three pages that turn every minute in full screen (Config › Time). Hovering "
                    "a trend marks the same moment on the others (Config › Display).",
                ),
                _kpi("h1003", "FIC-1003 recycle flow", "FIC-1003"),
                _kpi("h1202", "PIC-1202 hydrotreater pressure", "PIC-1202"),
                _kpi("h1209", "TIC-1209 furnace outlet", "TIC-1209"),
                _result_kpi("ffur", "Furnaces against the model", FURNACE_AREA, MODEL_DEVIATION),
            ],
        ),
        *_on(
            "loops",
            [
                _trend("t1003", "FIC-1003: stick-slip of a sticky valve", "FIC-1003"),
                _trend("t1202", "PIC-1202: oscillation from aggressive tuning", "PIC-1202"),
                _trend("t1209", "TIC-1209: slow sensor drift", "TIC-1209"),
                _trend("t1104", "TIC-1104: a cyclic disturbance", "TIC-1104"),
            ],
        ),
        *_on(
            "valves",
            [
                *(_kpi(f"v{loop[-4:]}", loop, loop) for loop in STICTION_LOOPS),
                *(
                    _scatter(f"vs{loop[-4:]}", f"{loop}: PV against OP", loop)
                    for loop in STICTION_LOOPS
                ),
            ],
        ),
    ],
}
LOOP_DETAIL = "Loop detail"


def _folders(dash: Http) -> dict[str, str]:
    """Operation and Control loops, by name: their ids."""

    ids = {item["name"]: item["folder_id"] for item in dash.get("/api/folders") or []}
    for folder in (OPERATION, INSTRUMENTATION):
        if folder["name"] not in ids:
            ids[folder["name"]] = dash.post("/api/folders", folder)["folder_id"]
            log(f"View: folder '{folder['name']}'")
    return ids


def dashcraft(dash: Http) -> None:
    """Three example dashboards ("só uns 3 exemplos"): Plant overview with a
    public link, Control room (three pages turning in kiosk mode) and Loop detail, from View's
    own template."""

    folders = _folders(dash)
    operation, instrumentation = folders["Operation"], folders[INSTRUMENTATION["name"]]
    kept = {item.get("name"): item for item in _items(dash.get("/api/dashboards"), "dashboards")}
    overview = kept.get(OVERVIEW["name"])
    if overview is None:
        overview = dash.post("/api/dashboards", {**OVERVIEW, "folder_id": operation})
        log("View: dashboard 'Plant overview'")
    if CONTROL_ROOM["name"] not in kept:
        dash.post("/api/dashboards", {**CONTROL_ROOM, "folder_id": operation})
        log("View: dashboard 'Control room' (three pages)")
    if LOOP_DETAIL not in kept:
        templates = dash.get("/api/templates") or []
        template = next(
            (item for item in templates if item.get("template_id") == "loop-detail"), None
        )
        if template:
            dash.post("/api/dashboards", {**template["draft"], "folder_id": instrumentation})
            log("View: dashboard 'Loop detail' from its template")
    shares = _items(dash.get(f"/api/dashboards/{_ident(overview)}/shares", ok=(503,)), "shares")
    if not shares:
        status, answer = dash.call(
            "POST",
            f"/api/dashboards/{_ident(overview)}/shares",
            {"label": "Public demo"},
            ok=(503,),
        )
        if status < 300:
            log(f"View: public link {answer.get('path')}")
