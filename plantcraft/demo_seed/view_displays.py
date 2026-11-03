"""View's process display "Riverbend plant" and the saved trends."""

from __future__ import annotations

import json
from typing import Any

from .base import Http, Suite, _items, log
from .view import _folders

# View's process display (2026-10-27): the whole plant on one page, every loop of the map drawn
# exactly once (deploy/demo/diagrams/*.json) --------------------------------------------------------

DIAGRAMS_FOLDER = "diagrams"
# The eight one-page diagrams earlier seeds made, now parts of "Riverbend plant".
OLD_DIAGRAMS = (
    "Riverbend Refinery",
    "Crude feed, preheat and furnace",
    "Atmospheric column",
    "Hydrotreater reactor loop",
    "Reaction and separation",
    "Amine treating and sulfur recovery",
    "Steam, cooling water and gases",
    "Effluent treatment and slop",
)


def _diagram_specs(suite: Suite) -> list[dict[str, Any]]:
    """The demo's process displays, one file each."""

    folder = suite.demo_map.parent / DIAGRAMS_FOLDER
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))]


# View's saved trends (well-named ones a visitor opens, not a test).
def _loop_lines(tag: str, *roles: str) -> list[dict[str, Any]]:
    return [
        {"signal_id": f"plantcraft:CPM.Loops.{tag}.{role}", "label": f"{tag} {role}"}
        for role in roles
    ]


VIEW_TRENDS: list[dict[str, Any]] = [
    {
        "name": "FIC-1003 sticky valve, last 12 h",
        "description": "Flow against setpoint over the valve output: the saw-tooth of stiction.",
        "plots": [
            {"title": "Recycle flow", "lines": _loop_lines("FIC-1003", "PV", "SP")},
            {"title": "Valve output", "lines": _loop_lines("FIC-1003", "OP")},
        ],
        "period": {"mode": "relative", "window": "12h"},
    },
    {
        "name": "PIC-1202 pressure oscillation",
        "description": "The 12-minute cycle behind the high-pressure alarm at every peak.",
        "plots": [
            {"title": "Pressure", "lines": _loop_lines("PIC-1202", "PV", "SP")},
            {"title": "Output", "lines": _loop_lines("PIC-1202", "OP")},
        ],
        "period": {"mode": "relative", "window": "6h"},
    },
    {
        "name": "Furnace outlets: TIC-1209 against TIC-1104",
        "description": "TIC-1209 drifts up while the twin furnace holds: a sensor, not the process.",
        "plots": [
            {
                "title": "Outlet temperatures",
                "lines": _loop_lines("TIC-1209", "PV") + _loop_lines("TIC-1104", "PV"),
            }
        ],
        "period": {"mode": "relative", "window": "24h"},
    },
]


TEST_TREND_NAMES = {"test", "teste", "new trend"}
RENAMED_TEST_TREND = "Control loop analysis"


def view_trends(dash: Http) -> None:
    """View's saved trends; run again, it adds only the missing ones."""

    listed = _items(dash.get("/api/trends"), "trends")
    # A test trend left on the demo gets a name a visitor understands.
    for item in listed:
        if str(item.get("name") or "").strip().lower() in TEST_TREND_NAMES:
            dash.put(f"/api/trends/{item['trend_id']}", {**item, "name": RENAMED_TEST_TREND})
            item["name"] = RENAMED_TEST_TREND
    kept = {item.get("name") for item in listed}
    for trend in VIEW_TRENDS:
        if trend["name"] not in kept:
            dash.post("/api/trends", {**trend, "step_seconds": None})
    log(f"View: {len(VIEW_TRENDS)} saved trends")


def view_diagrams(dash: Http, suite: Suite) -> None:
    """The process display of Riverbend Refinery in the Operation folder: the whole plant on one
    page, with the loops' values, health and mode on them. Created once (by name); the paged
    display and the one-page diagrams of earlier seeds give way to it."""

    status, listed = dash.call("GET", "/api/diagrams", ok=(404,))
    if status == 404:
        return
    specs = _diagram_specs(suite)
    if not specs:
        return
    operation = _folders(dash)["Operation"]
    kept = {item.get("name"): item for item in listed or []}
    for spec in specs:
        old = kept.get(spec["name"])
        if old is None:
            dash.post("/api/diagrams", {**spec, "folder_id": operation})
            log(f"View: process display '{spec['name']}'")
            continue
        # The paged demo display of earlier seeds becomes the one-page plant (2026-10-27); a
        # display someone redrew (no longer tagged demo, or already one page) is left alone.
        _, stored = dash.call("GET", f"/api/diagrams/{old['diagram_id']}", ok=(404,))
        if not stored or "demo" not in (stored.get("tags") or []):
            continue
        paged = len(stored.get("pages") or []) > len(spec.get("pages") or [])
        # The one-page display of 2026-10-27 had no parts: it gets the tabs (2026-10-28).
        partless = bool(spec.get("parts")) and not stored.get("parts")
        if not paged and not partless:
            continue
        dash.call(
            "PUT",
            f"/api/diagrams/{old['diagram_id']}",
            {
                **spec,
                "folder_id": stored.get("folder_id", operation),
                "base_updated_at": stored.get("updated_at"),
            },
            ok=(409,),
        )
        log(f"View: process display '{spec['name']}' redrawn on one page, with its parts")
    for item in listed or []:
        if item.get("name") in OLD_DIAGRAMS and "demo" in (item.get("tags") or []):
            dash.call("DELETE", f"/api/diagrams/{item['diagram_id']}", ok=(404,))
            log(f"View: old diagram '{item['name']}' replaced by its page")
