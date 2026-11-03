"""PlantCraft's plant: the map of the Simulator, the refinery's name and the signals in use."""

from __future__ import annotations

import urllib.parse
from typing import Any

from .base import Http, SeedError, Suite, log, wait_until

# PlantCraft ---------------------------------------------------------------------------------


def plant_map(admin: Http, suite: Suite) -> None:
    raw = suite.demo_map.read_bytes()
    name = urllib.parse.quote(suite.demo_map.name)
    answer = admin.post(f"/api/map/apply?filename={name}", raw=raw)
    log(f"plant map applied: {_short(answer)}")
    name_the_plant(admin)


# The demo plant, as the asset tree's root shows it (the installation calls it "Plant").
PLANT = {
    "name": "Riverbend Refinery",
    "description": "A demonstration refinery simulated by PlantCraft Simulator: four units and 50 "
    "control loops, with their equipment, transmitters and valves.",
}
PLANT_RECORD = {"location": "Simulated site", "operator": "PlantCraft demo"}


def name_the_plant(admin: Http) -> None:
    """The root of the tree gets the refinery's name (edited by hand, so restarts keep it)."""

    tree = admin.get("/api/assets")
    root = tree.get("root_id") if isinstance(tree, dict) else None
    if not root:
        return
    current = next((item for item in tree["items"] if item["asset_id"] == root), {})
    if current.get("name") != PLANT["name"]:
        admin.patch(f"/api/assets/{urllib.parse.quote(root)}", PLANT)
    try:
        admin.patch(f"/api/assets/{urllib.parse.quote(root)}/attributes", {"values": PLANT_RECORD})
    except SeedError as error:  # an admin removed the attributes from the Plant type
        log(f"plant record skipped: {error}")
    log(f"plant named {PLANT['name']}")


def _short(answer: Any) -> str:
    if isinstance(answer, dict):
        keys = [k for k, v in answer.items() if isinstance(v, (int, str)) and k != "detail"]
        return ", ".join(f"{k}={answer[k]}" for k in keys[:8]) or "ok"
    return "ok"


def archive_signals(admin: Http, suite: Suite) -> None:
    """Every signal of the Simulator read (Historian archives them when it is the data layer)."""

    def tags() -> list[str]:
        page = admin.get("/api/data/sources/plantcraft/signals?limit=1000")
        return [item["tag"] for item in page.get("items", [])]

    found = wait_until("the Simulator's signals", tags, suite.wait)
    answer = admin.post(
        "/api/data/sources/plantcraft/signals/use", {"tags": found, "monitored": True}
    )
    log(f"{len(found)} the Simulator's signals in use ({answer.get('updated')} new)")
