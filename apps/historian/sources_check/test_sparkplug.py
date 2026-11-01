"""Sparkplug B against a real MQTT broker (Mosquitto when installed, else amqtt): Historian's
collector subscribes, learns the metrics from the births, adds a point for each, archives the
data that follows and marks the death, and publishes nothing (H10)."""

from __future__ import annotations

import pytest
from simcraft.testkit import sparkplug
from simcraft.testkit.background import Background

from histcraft.catalog.models import SourceIn
from sources_check.conftest import free_port, wait

pytestmark = pytest.mark.slow
GROUP = sparkplug.GROUP


def test_births_add_the_points_and_the_data_and_death_follow(historian, series):
    port = free_port()
    edge = sparkplug.SparkplugPlant(series, port=port)
    expected = sparkplug.expected(series)
    with Background(edge.start, edge.stop) as kit:
        historian.add(
            SourceIn(
                id="edge",
                name="Edge",
                kind="sparkplug",
                endpoint=edge.url,
                options={"group_id": GROUP, "qos": 1, "add_on_birth": True},
            ),
            [],
        )
        historian.thread.start()
        wait(lambda: historian.status("edge").get("status") == "connected", what="connected")
        kit.call(edge.birth)
        # Every metric of the device's birth is a point now (and the node's uptime).
        wait(
            lambda: len(historian.catalog.points()) >= len(expected) + 1,
            what=lambda: f"points from births, got {len(historian.catalog.points())}",
        )
        points = {item["tag"]: item for item in historian.catalog.points()}
        assert set(expected) <= set(points)
        assert not any("Control" in tag or "bdSeq" in tag for tag in points)
        for tag, item in series.items():
            point = points[f"{GROUP}.edge1.unit100.{tag}"]
            assert point["kind"] == ("text" if item.kind == "text" else "number")
            assert point["unit"] == item.unit
        kit.call(edge.data)
        for tag, value in expected.items():
            wait(
                lambda t=tag, v=value: (
                    historian.snapshot(f"edge:{t}") == pytest.approx(v)
                    if isinstance(v, float)
                    else historian.snapshot(f"edge:{t}") == v
                ),
                what=lambda t=tag, v=value: f"{t} = {v} (now {historian.snapshot(f'edge:{t}')})",
            )
        status = historian.status("edge")
        assert (status["nodes"], status["devices"], status["sequence_gaps"]) == (1, 1, 0)
        kit.call(edge.death)
        collector = historian.thread.collector
        signal = f"edge:{next(iter(expected))}"
        wait(
            lambda: collector.points[historian.point(signal)].status == "bad",
            what="the death marks the values bad",
        )
        # Historian only listened: every message on the broker was the edge node's.
        assert edge.published and all(
            topic.split("/")[2] in ("NBIRTH", "DBIRTH", "DDATA", "NDEATH")
            for topic in edge.published
        ), edge.published
        print(f"broker: {edge.broker_name}")
