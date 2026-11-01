"""Sparkplug B sources (H10, docs/gaps.md G10): payloads decoded, metrics learnt from births,
deaths marked, points added by themselves, and never a message published.

The source check (``sources_check/test_sparkplug.py``) runs the same against a real broker.
"""

from __future__ import annotations

import ast
import asyncio
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.models import SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector
from histcraft.sparkplug import READ_TYPES, Births, decode, parse_topic, topics
from tests.conftest import database, make_settings
from tests.sparkplug_payloads import metric, payload

ROOT = Path(__file__).resolve().parents[1]
NODE = "spBv1.0/plant/{kind}/edge1"
DEVICE = "spBv1.0/plant/{kind}/edge1/pump7"
T0 = 1_761_955_200_000  # 2025-11-01T00:00:00Z


def nbirth(seq: int = 0, bd_seq: int = 0) -> bytes:
    return payload(
        [
            metric("bdSeq", bd_seq, 8),
            metric("Node Control/Rebirth", False, 11),
            metric("Line/Speed", 12.5, 10, alias=1, props={"engUnit": "m/min"}),
            metric("Line/Running", True, 11, alias=2),
            metric("Line/Count", -3, 3, alias=3),
            metric("Line/Recipe", "A-17", 12, alias=4),
        ],
        seq=seq,
        timestamp=T0,
    )


def dbirth(seq: int) -> bytes:
    return payload(
        [
            metric("Flow", 40.0, 9, alias=10, props={"engUnit": "m3/h"}),
            metric(
                "Motor",
                None,
                19,
                members=[metric("Current", 7.5, 10), metric("Trips", 2, 7)],
            ),
        ],
        seq=seq,
        timestamp=T0,
    )


def test_every_data_type_decodes_as_its_value():
    data = payload(
        [
            metric("i8", -5, 1),
            metric("i16", -300, 2),
            metric("i32", -70000, 3),
            metric("i64", -(2**40), 4),
            metric("u32", 2**32 - 1, 7),
            metric("f", 1.5, 9),
            metric("d", 2.25, 10),
            metric("b", True, 11),
            metric("s", "auto", 12),
            metric("t", T0, 13),
            metric("n", None, 10),
            metric("q", 1.0, 10, props={"Quality": 64, "engUnit": "bar"}),
        ],
        seq=7,
        timestamp=T0,
    )
    found = decode(data)
    assert (found.seq, found.timestamp) == (7, T0)
    values = {item.name: item.value for item in found.metrics}
    assert values == {
        "i8": -5,
        "i16": -300,
        "i32": -70000,
        "i64": -(2**40),
        "u32": 2**32 - 1,
        "f": 1.5,
        "d": 2.25,
        "b": True,
        "s": "auto",
        "t": T0,
        "n": None,
        "q": 1.0,
    }
    assert found.metrics[-1].properties == {"Quality": 64, "engUnit": "bar"}
    # An Int8 sent widened to one byte only (some edge nodes) reads the same.
    assert decode(payload([metric("x", 0xFB, 1)])).metrics[0].value == -5


def test_junk_is_not_a_payload():
    births = Births()
    assert births.take(NODE.format(kind="NDATA"), b"\xff\xff\xff", T0) == []
    assert births.take(NODE.format(kind="NDATA"), b"\x0a\x05ab", T0) == []
    assert births.unreadable == 2


def test_only_births_data_and_deaths_are_read():
    assert topics() == [f"spBv1.0/+/{kind}/#" for kind in READ_TYPES]
    assert topics("plant")[0] == "spBv1.0/plant/NBIRTH/#"
    assert not {"NCMD", "DCMD", "STATE"} & set(READ_TYPES)
    for topic in (
        "spBv1.0/plant/NCMD/edge1",
        "spBv1.0/plant/DCMD/edge1/pump7",
        "spBv1.0/STATE/host",
        "spBv1.0/plant/NDATA/edge1/pump7",  # a node message with a device
        "spBv1.0/plant/DDATA/edge1",  # a device message without one
        "plant/value/x",
    ):
        assert parse_topic(topic) is None, topic


def test_births_name_the_aliases_data_uses():
    births = Births()
    born = births.take(NODE.format(kind="NBIRTH"), nbirth(), T0)
    assert {item.address: item.value for item in born} == {
        "plant/edge1/Line/Speed": 12.5,
        "plant/edge1/Line/Running": True,
        "plant/edge1/Line/Count": -3,
        "plant/edge1/Line/Recipe": "A-17",
    }
    births.take(DEVICE.format(kind="DBIRTH"), dbirth(1), T0)
    data = payload(
        [metric(None, 13.0, 10, alias=1, timestamp=T0 + 1000)], seq=2, timestamp=T0 + 1000
    )
    assert [
        (v.address, v.value, v.at_ms) for v in births.take(NODE.format(kind="NDATA"), data, T0)
    ] == [("plant/edge1/Line/Speed", 13.0, T0 + 1000)]
    device = payload([metric(None, 41.5, 9, alias=10)], seq=3, timestamp=T0 + 2000)
    taken = births.take(DEVICE.format(kind="DDATA"), device, T0)
    assert [(v.address, v.value, v.at_ms) for v in taken] == [
        ("plant/edge1/pump7/Flow", 41.5, T0 + 2000)
    ]
    variables = {item["tag"]: item for item in births.variables()}
    assert set(variables) == {
        "plant.edge1.Line.Speed",
        "plant.edge1.Line.Running",
        "plant.edge1.Line.Count",
        "plant.edge1.Line.Recipe",
        "plant.edge1.pump7.Flow",
        "plant.edge1.pump7.Motor.Current",
        "plant.edge1.pump7.Motor.Trips",
    }
    assert variables["plant.edge1.Line.Speed"]["unit"] == "m/min"
    assert [variables[f"plant.edge1.Line.{n}"]["kind"] for n in ("Running", "Count", "Recipe")] == [
        "boolean",
        "integer",
        "text",
    ]
    assert variables["plant.edge1.pump7.Flow"]["value"] == 41.5
    assert births.summary()["sequence_gaps"] == 0


def test_a_death_makes_the_values_stale_and_an_old_will_is_ignored():
    births = Births()
    births.take(NODE.format(kind="NBIRTH"), nbirth(bd_seq=4), T0)
    births.take(DEVICE.format(kind="DBIRTH"), dbirth(1), T0)
    gone = births.take(DEVICE.format(kind="DDEATH"), payload([], seq=2), T0 + 5)
    assert {v.address for v in gone} == {
        "plant/edge1/pump7/Flow",
        "plant/edge1/pump7/Motor/Current",
        "plant/edge1/pump7/Motor/Trips",
    }
    assert all(not v.good and v.quality == "bad" for v in gone)
    # The will of the session before (bdSeq 3) arrives late: the node is alive.
    old = payload([metric("bdSeq", 3, 8)])
    assert births.take(NODE.format(kind="NDEATH"), old, T0 + 6) == []
    dead = births.take(NODE.format(kind="NDEATH"), payload([metric("bdSeq", 4, 8)]), T0 + 7)
    assert {v.address for v in dead} >= {"plant/edge1/Line/Speed", "plant/edge1/pump7/Flow"}
    assert not any(item["online"] for item in births.variables())


def test_lost_messages_and_unknown_aliases_are_counted_never_asked_for():
    births = Births()
    # Historian connected after the birth: data by alias is unknown, data by name is read.
    data = payload([metric(None, 1.0, 10, alias=1), metric("Line/Speed", 2.0, 10)], seq=5)
    assert [v.address for v in births.take(NODE.format(kind="NDATA"), data, T0)] == [
        "plant/edge1/Line/Speed"
    ]
    assert births.unknown_aliases == 1
    births.take(NODE.format(kind="NDATA"), payload([], seq=9), T0)
    assert births.sequence_gaps == 1
    # Sequence numbers wrap at 255.
    births.take(NODE.format(kind="NBIRTH"), nbirth(seq=255), T0)
    births.take(NODE.format(kind="NDATA"), payload([], seq=0), T0)
    assert births.sequence_gaps == 1


def test_the_quality_property_and_null_values():
    births = Births()
    data = payload(
        [
            metric("a", 1.0, 10, props={"Quality": 192}),
            metric("b", 2.0, 10, props={"Quality": 64}),
            metric("c", 3.0, 10, props={"Quality": 0}),
            metric("d", None, 10),
        ]
    )
    found = {
        v.address.rsplit("/", 1)[1]: v for v in births.take(NODE.format(kind="NDATA"), data, T0)
    }
    assert (found["a"].good, found["a"].quality) == (True, "good")
    assert (found["b"].good, found["b"].quality, found["b"].value) == (True, "uncertain", 2.0)
    assert (found["c"].good, found["c"].value) == (False, None)
    assert (found["d"].good, found["d"].detail) == (False, "null")


def test_a_source_is_checked():
    good = SourceIn(id="edge", name="Edge", kind="sparkplug", endpoint="tcp://broker:1883")
    assert good.options == {"group_id": "", "qos": 1, "add_on_birth": True}
    assert good.mode == "archive"
    for endpoint, options in (
        ("http://broker", {}),
        ("tcp://broker", {"group_id": "plant/#"}),
        ("tcp://broker", {"qos": 2}),
        ("tcp://broker", {"topics": ["x"]}),
    ):
        with pytest.raises(ValidationError):
            SourceIn(id="edge", name="Edge", kind="sparkplug", endpoint=endpoint, options=options)


def test_the_listener_never_publishes():
    """Read only (AGENTS.md): no publish, will, STATE or command in the MQTT client's module."""

    path = ROOT / "src" / "histcraft" / "collector" / "sparkplug.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"publish", "will_set", "reconnect_delay_set"}
    assert "subscribe" in called
    docstrings = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr)}
    texts = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }
    assert not any(word in text for text in texts for word in ("NCMD", "DCMD", "STATE"))


class FakeListener:
    """A broker connection that hands the collector the messages a test gives it."""

    def __init__(self, inbox):
        self.inbox, self.dropped, self.connected, self.failure = inbox, 0, True, ""

    async def connect(self):
        return None

    def messages(self):
        out, self.inbox[:] = list(self.inbox), []
        return out

    async def close(self):
        return None


def test_points_are_added_from_births_and_archive_what_follows(tmp_path):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(database(tmp_path, "config"))
    archive = ArchiveStore(database(tmp_path))
    catalog.save_source(
        SourceIn(id="edge", name="Edge", kind="sparkplug", endpoint="tcp://broker:1883"),
        create=True,
    )
    inbox = []
    collector = Collector(settings, catalog, archive, reader_factory=lambda _s: FakeListener(inbox))

    async def run():
        collector.reload()
        await collector._sync_tasks()
        inbox.append((NODE.format(kind="NBIRTH"), nbirth(), T0))
        inbox.append((DEVICE.format(kind="DBIRTH"), dbirth(1), T0))
        for _ in range(50):
            await asyncio.sleep(0.05)
            if collector.reload():
                await collector._sync_tasks()
            if len(collector.points) == 7 and all(s.last for s in collector.points.values()):
                break
        inbox.append(
            (
                DEVICE.format(kind="DDATA"),
                payload([metric(None, 44.0, 9, alias=10)], seq=2, timestamp=T0 + 1000),
                T0,
            )
        )
        inbox.append((DEVICE.format(kind="DDEATH"), payload([], seq=3), T0 + 2000))
        await asyncio.sleep(0.5)
        collector.flush(settle=True)
        for task in collector._tasks.values():
            task.cancel()

    asyncio.run(run())
    points = {p["tag"]: p for p in catalog.points() if p["source_id"] == "edge"}
    assert len(points) == 7
    flow = points["plant.edge1.pump7.Flow"]
    assert (flow["kind"], flow["unit"], flow["address"]) == (
        "number",
        "m3/h",
        "plant/edge1/pump7/Flow",
    )
    assert points["plant.edge1.Line.Running"]["kind"] == "boolean"
    assert points["plant.edge1.Line.Recipe"]["kind"] == "text"
    times, values = archive.read(int(flow["id"]), 0, 2**62)
    assert list(times[:2]) == [T0, T0 + 1000] and list(values[:2]) == [40.0, 44.0]
    assert math.isnan(values[-1])  # the death: a gap
    quality = archive.qualities(int(flow["id"]), 0, 2**62)
    assert quality[-1][1] == "bad"
    status = collector.source_status["edge"]
    assert (status["status"], status["nodes"], status["devices"]) == ("connected", 1, 1)
