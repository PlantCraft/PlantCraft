"""The Overview's values stored per hour (from the archive's per-hour counts, never a read of
the values) and its map of every enabled signal by source, coloured by its collection."""

from __future__ import annotations

from plantcraft_sdk import apptest
from plantcraft_sdk.asset_scope import forget

from histcraft.archive.store import HOUR_MS, now_ms
from histcraft.catalog.models import PointIn, SourceIn
from tests.test_asset_scope import HIDDEN, SEEN, limited

MIN = 60_000


def _plant(runtime, source: str, tags: str, *, enabled: bool = True) -> dict[str, int]:
    runtime.catalog.save_source(
        SourceIn(id=source, name=source.upper(), endpoint=f"opc.tcp://{source}:4840/",
                 enabled=enabled),
        create=True,
    )  # fmt: skip
    runtime.catalog.add_points(
        [PointIn(tag=tag, source_id=source, address=f"ns=2;s={tag}") for tag in tags.split()]
    )
    return {point["tag"]: int(point["id"]) for point in runtime.catalog.points()}


def test_an_empty_historian_says_so_in_both_widgets(client):
    assert apptest.widget_problems(client, "/hist") == []
    stored = client.get("/hist/api/widgets/stored").json()
    assert stored["kind"] == "columns" and stored["step"] == "hour"
    assert stored["value"] == 0 and len(stored["buckets"]) == 24
    assert stored["empty"] and stored["href"] == "/hist/settings"
    tiles = client.get("/hist/api/widgets/source-map").json()
    assert tiles["kind"] == "tiles" and tiles["groups"] == [] and tiles["empty"]


def test_values_stored_count_per_hour_of_the_last_day(client, runtime):
    points = _plant(runtime, "plant", "A B")
    hour = now_ms() // HOUR_MS * HOUR_MS
    runtime.archive.append(
        {
            points["A"]: ("number", [(hour - 3 * HOUR_MS + i * MIN, float(i)) for i in range(30)]),
            points["B"]: ("number", [(hour + i * 1000, 1.0) for i in range(5)]),
        }
    )
    # Two days ago is outside the 24 h.
    runtime.archive.append({points["B"]: ("number", [(hour - 48 * HOUR_MS, 2.0)])})
    stored = client.get("/hist/api/widgets/stored").json()
    buckets = dict(stored["buckets"])
    assert stored["buckets"][0][0] == hour - 23 * HOUR_MS and stored["buckets"][-1][0] == hour
    assert buckets[hour - 3 * HOUR_MS] == [30] and buckets[hour] == [5]
    assert stored["value"] == 35 and "24 h" in stored["label"]


def test_the_source_map_colours_each_enabled_signal_by_its_collection(client, runtime):
    now = now_ms()
    _plant(runtime, "north", "N1 N2 N3 N4 N5")
    _plant(runtime, "south", "S1", enabled=False)
    _plant(runtime, "east", "E1")
    runtime.catalog.add_points(
        [PointIn(tag="OFF", source_id="north", address="ns=2;s=OFF", enabled=False)]
    )
    points = {point["tag"]: int(point["id"]) for point in runtime.catalog.points()}
    runtime.archive.put_snapshots(
        [
            {"point": points["N1"], "ts": now - 1000, "value": 1.0, "status": "ok"},
            {"point": points["N2"], "ts": now - 30 * MIN, "value": 1.0, "status": "ok"},
            {"point": points["N3"], "ts": now - 1000, "value": 1.0, "status": "bad"},
            {"point": points["N4"], "ts": now - 1000, "value": 1.0, "status": "uncertain"},
            {"point": points["E1"], "ts": now - 1000, "value": 1.0, "status": "ok"},
        ]
    )
    answer = client.get("/hist/api/widgets/source-map").json()
    groups = {group["label"]: group for group in answer["groups"]}
    # The worst first, a disabled source last.
    assert list(groups) == ["north", "east", "south"] and answer["value"] == 7
    assert groups["north"]["href"] == "/hist/sources/north"
    north = {tile["label"]: tile for tile in groups["north"]["tiles"]}
    assert "OFF" not in north  # a disabled signal has no square
    assert {tag: tile["state"] for tag, tile in north.items()} == {
        "N1": "ok", "N2": "warning", "N3": "alarm", "N4": "warning", "N5": "alarm",
    }  # fmt: skip
    assert "30 min" in north["N2"]["detail"] and north["N5"]["detail"] == "Waiting"
    assert north["N1"]["href"] == "/hist/points/north%3AN1"
    [south] = groups["south"]["tiles"]
    assert south["state"] == "unknown" and south["detail"] == "Source disabled"


def test_the_archive_keeps_to_whether_the_disk_holds(client):
    archive = client.get("/hist/api/widgets/archive").json()
    assert archive["kind"] == "list"
    labels = [row["label"] for row in archive["items"]]
    assert labels == ["On disk", "Disk full in", "Values archived"]
    assert archive["items"][0]["detail"].startswith("Grows ")


def test_the_collector_is_a_list_like_the_cards_beside_it(client):
    collector = client.get("/hist/api/widgets/collector").json()
    # No big number and no badge of its own: a row for the collector, one for its sources.
    assert collector["kind"] == "list" and "title" not in collector
    running, sources = collector["items"]
    assert running["label"] in ("Running", "Stopped") and "values/s" in running["value"]
    assert sources["label"] == "Sources connected" and " / " in sources["value"]


def test_both_widgets_keep_to_the_persons_part_of_the_plant(runtime, fake):
    forget()
    points = _plant(runtime, "fake", "FIC-101.PV LIC-102.PV")
    hour = now_ms() // HOUR_MS * HOUR_MS
    runtime.archive.append(
        {
            points["FIC-101.PV"]: ("number", [(hour + i * 1000, 1.0) for i in range(3)]),
            points["LIC-102.PV"]: ("number", [(hour + i * 1000, 1.0) for i in range(7)]),
        }
    )
    client = limited(runtime, fake)
    assert client.get("/hist/api/widgets/stored").json()["value"] == 3
    tiles = client.get("/hist/api/widgets/source-map").json()
    [group] = tiles["groups"]
    assert [tile["label"] for tile in group["tiles"]] == [SEEN.split(":")[1]]
    assert HIDDEN.split(":")[1] not in str(tiles)
    forget()
