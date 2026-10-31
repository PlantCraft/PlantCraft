"""What the Historian has open now (histcraft.conditions), in GET /api/ops/metrics for
PlantCraft's monitor, which writes them as histcraft.* events."""

from __future__ import annotations

from plantcraft_sdk.server import ops

from histcraft.archive.store import now_ms
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.conditions import open_conditions
from histcraft.meta import FILES

MIN = 60_000


def _plant(runtime, *sources: str) -> dict[str, int]:
    for source in sources:
        runtime.catalog.save_source(
            SourceIn(id=source, name=source.upper(), endpoint=f"opc.tcp://{source}:4840/"),
            create=True,
        )
        runtime.catalog.add_points(
            [PointIn(tag=f"{source}-{n}", source_id=source, address=f"ns=2;s={n}") for n in "ab"]
        )
    return {point["tag"]: int(point["id"]) for point in runtime.catalog.points()}


def _collector(runtime, now, **sources):
    runtime.archive.set_state(
        "collector",
        {"heartbeat": now, "started": now - 60 * MIN,
         "sources": {key: {"status": value, "detail": "refused", "since": now} for key, value in
                     sources.items()}},
    )  # fmt: skip


def _keys(runtime, now):
    return [(item.name, item.key) for item in open_conditions(runtime.catalog, runtime.archive,
                                                              now=now)]  # fmt: skip


def test_no_collector_ever_ran_says_nothing(runtime):
    _plant(runtime, "plant")
    assert open_conditions(runtime.catalog, runtime.archive) == []


def test_a_stalled_collector_is_the_one_condition(runtime):
    now = now_ms()
    _plant(runtime, "plant")
    _collector(runtime, now - 5 * MIN, plant="disconnected")
    [stalled] = open_conditions(runtime.catalog, runtime.archive, now=now)
    assert (stalled.name, stalled.key) == ("collector.stalled", "collector")
    assert "5 min" in stalled.summary


def test_a_source_down_is_one_condition_and_its_points_are_not_named(runtime):
    now = now_ms()
    points = _plant(runtime, "north", "south")
    _collector(runtime, now, north="disconnected", south="connected")
    runtime.archive.put_snapshots(
        [
            {"point": points["north-a"], "ts": now - 60 * MIN, "value": 1.0, "status": "disconnected"},
            {"point": points["south-a"], "ts": now - 20 * MIN, "value": 1.0, "status": "ok"},
            {"point": points["south-b"], "ts": now - 1000, "value": 2.0, "status": "bad",
             "detail": "BadSensorFailure"},
        ]
    )  # fmt: skip
    found = open_conditions(runtime.catalog, runtime.archive, now=now)
    assert [(item.name, item.key) for item in found] == [
        ("source.disconnected", "source:north"),
        ("point.no_data", f"point:{points['south-a']}"),  # the oldest first
        ("point.no_data", f"point:{points['south-b']}"),
    ]
    assert found[0].subject == "source:north" and "refused" in found[0].summary
    assert found[1].subject == "signal:south:south-a" and "20 min" in found[1].summary
    assert "BadSensorFailure" in found[2].summary
    # A point fresh enough and one never read yet are fine.
    runtime.archive.put_snapshots(
        [{"point": points["south-a"], "ts": now - 1000, "value": 1.0, "status": "ok"}]
    )
    assert _keys(runtime, now)[1:] == [("point.no_data", f"point:{points['south-b']}")]


def test_the_conditions_ride_on_the_metrics_with_the_catalog(runtime):
    now = now_ms()
    _plant(runtime, "plant")
    _collector(runtime, now, plant="disconnected")
    runtime.start()
    try:
        runtime.send_event_catalog(FILES.manifest())
        answer = ops.metrics("histcraft", "0.1.0")
        assert [item["key"] for item in answer["conditions"]] == ["source:plant"]
        names = [spec["name"] for spec in answer["events"]]
        assert names == [
            "collector.stalled",
            "source.disconnected",
            "point.no_data",
            "archive.disk_low",
            "annotation.added",  # an instant, posted by the signal's page
        ]
    finally:
        runtime.shutdown()
        ops.report_catalog(None)
    assert "conditions" not in ops.metrics("histcraft", "0.1.0")


def test_a_disk_that_fills_within_90_days_is_a_condition(runtime):
    now = now_ms()
    _plant(runtime, "plant")
    _collector(runtime, now, plant="connected")
    runtime.archive.set_state("forecast", {"days_to_full": 400.0, "free_bytes": 10})
    assert _keys(runtime, now) == []
    runtime.archive.set_state(
        "forecast", {"days_to_full": 42.4, "free_bytes": 10, "bytes_per_day": 1}
    )
    [low] = open_conditions(runtime.catalog, runtime.archive, now=now)
    assert (low.name, low.key) == ("archive.disk_low", "disk")
    assert "42 days" in low.summary
    # No free space known, or a growth that stops before the disk fills: nothing.
    runtime.archive.set_state("forecast", {"days_to_full": None})
    assert _keys(runtime, now) == []


def test_signals_an_app_writes_are_never_late(runtime):
    # An algorithm's version is written once per version: 57 "No data from the plant" alerts
    # on a fresh demo came from Analytics' own signals (visual sweep, 2026-10-26).
    now = now_ms()
    points = _plant(runtime, "plant")
    written = runtime.catalog.derived(
        "linkcraft", [{"signal": "app-linkcraft:algorithm.flow_loop.version"}]
    )
    _collector(runtime, now, plant="connected")
    runtime.archive.put_snapshots(
        [
            {"point": int(written["app-linkcraft:algorithm.flow_loop.version"]["id"]),
             "ts": now - 60 * MIN, "value": 3.0, "status": "ok"},
            {"point": points["plant-a"], "ts": now - 60 * MIN, "value": 1.0, "status": "ok"},
        ]
    )  # fmt: skip
    assert _keys(runtime, now) == [("point.no_data", f"point:{points['plant-a']}")]
