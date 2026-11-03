"""Analytics: loops with their criticality, the monitors with replayed results and the model
examples."""

from __future__ import annotations

from .base import CRITICALITY, SURGE_LEVELS, Http, Suite, _items, log, wait_until
from .historian import BACKFILL_HOURS

# Analytics ------------------------------------------------------------------------------------


def linkcraft(link: Http, suite: Suite) -> None:
    link.post("/api/loops/sync")
    loops = wait_until(
        "Analytics' loops",
        lambda: [item for item in _items(link.get("/api/loops"), "loops")],
        suite.wait,
    )
    log(f"Analytics: {len(loops)} loops")
    for loop_id, criticality in CRITICALITY.items():
        link.patch(f"/api/loops/{loop_id}", {"criticality": criticality}, ok=(404, 422))
    for loop_id in SURGE_LEVELS:
        link.patch(f"/api/loops/{loop_id}", {"profile_id": "surge_drum"}, ok=(404, 422))
    link.post("/api/round", ok=(409,))
    link.post("/api/signal-quality/run", ok=(409,))
    log("Analytics: Control loop performance and Signal quality started")
    # The archive's past as if Analytics had been watching: hourly rounds (each loop's health trend)
    # and every schedule's past runs. In the background; moments already there are skipped.
    status, answer = link.call(
        "POST",
        "/api/history/replay",
        {"hours": BACKFILL_HOURS, "step_minutes": 60},
        ok=(404, 405),
    )
    if status == 202:
        log(f"Analytics: replaying the last {BACKFILL_HOURS} hours of rounds and schedules")


# Analytics' model examples ------------------------------------------------------------------


def link_models(link: Http, suite: Suite) -> None:
    """The plant's model examples in Analytics (Furnaces, FIC-1001 and LIC-1010 process), calibrated
    on the archive's last hours, and run once now so their results are there at once."""

    examples = wait_until(
        "the plant's loops in Analytics",
        lambda: link.get("/api/models/examples"),
        suite.wait,
    )
    if any(not item.get("exists") for item in examples):
        created = link.post("/api/models/examples")
        waiting = [item["name"] for item in created if not item.get("calibrated")]
        log(
            f"Analytics: {len(created)} model examples"
            + (f" (not calibrated yet: {', '.join(waiting)})" if waiting else "")
        )
    for item in examples:
        link.post(f"/api/algorithms/{item['algorithm_id']}/run", ok=(404, 409, 502))
