"""The gateway (Telegraf): line protocol in, sources' options checked, its configuration out."""

from __future__ import annotations

import gzip
import tomllib

import pytest
from fastapi.testclient import TestClient

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector import line_protocol
from histcraft.collector.gateway import INPUTS, gateway_token, render, variable, write_config
from histcraft.collector.ingest import ingest_app
from histcraft.collector.service import Collector
from tests.conftest import database, make_settings

MQTT = SourceIn(
    id="broker",
    name="Broker",
    kind="mqtt",
    endpoint="tcp://broker:1883",
    username="historian",
    options={"topics": "plant/#, utilities/+/flow", "qos": 1},
)
MODBUS = SourceIn(
    id="plc",
    name="PLC",
    kind="modbus",
    endpoint="tcp://10.0.0.5:502",
    default_scan_seconds=2,
    options={
        "slave_id": 3,
        "registers": [
            {
                "name": "FT-101",
                "type": "holding_register",
                "address": 10,
                "data_type": "FLOAT32-IEEE",
            },
            {"name": "LT-7", "type": "input_register", "address": 0, "scale": 0.1},
            {"name": "XV-1", "type": "coil", "address": 4},
        ],
    },
)
SQL = SourceIn(
    id="lims",
    name="LIMS",
    kind="sql",
    endpoint="postgres://reader:{password}@lims:5432/lab",
    options={
        "query": "SELECT sample_time, tag, result FROM results WHERE status = 'final'",
        "time_column": "sample_time",
        "tag_columns": ["tag"],
    },
)


def test_line_protocol_reads_what_telegraf_writes():
    text = (
        "# a comment\n"
        "modbus,name=plc,type=holding_register,slave_id=3 FT-101=12.5,LT-7=3i 1700000000000000000\n"
        'mqtt_consumer,topic=plant/FT\\ 1 value=1e3,ok=true,mode="AU\\"TO"\n'
        "bad line\n"
    )
    metrics, errors = line_protocol.parse(text)
    assert len(metrics) == 2 and len(errors) == 1
    modbus, mqtt = metrics
    assert modbus.fields == {"FT-101": 12.5, "LT-7": 3}
    assert modbus.at_ms == 1_700_000_000_000
    assert modbus.series() == "modbus,name=plc,slave_id=3,type=holding_register"
    assert mqtt.tags == {"topic": "plant/FT 1"}
    assert mqtt.fields == {"value": 1000.0, "ok": True, "mode": 'AU"TO'}
    assert mqtt.at_ms is None
    assert "mqtt_consumer,topic=plant/FT\\ 1 value" in mqtt.addresses()
    assert line_protocol.parse("m v=1 1700000000", "s")[0][0].at_ms == 1_700_000_000_000


@pytest.mark.parametrize(
    "line",
    ["m", "m v", "m v=", "m,t v=1", "m v=abc", 'm v="open', "m v=1 later", "m v=nan"],
)
def test_line_protocol_refuses_broken_lines(line):
    with pytest.raises(line_protocol.LineError):
        line_protocol.parse_line(line)


def test_gateway_sources_take_only_what_reads():
    assert MQTT.options["topics"] == ["plant/#", "utilities/+/flow"] and MQTT.mode == "archive"
    assert MODBUS.options["registers"][0]["byte_order"] == "ABCD"
    assert MODBUS.options["registers"][1]["data_type"] == "INT16"
    for query in (
        "DELETE FROM results",
        "SELECT 1; DROP TABLE results",
        "WITH x AS (DELETE FROM r RETURNING *) SELECT * FROM x",
        "SELECT * INTO copy FROM results",
    ):
        with pytest.raises(ValueError, match="only reads"):
            SourceIn(id="x", name="x", kind="sql", endpoint="dsn", options={"query": query})
    # A keyword inside a string is text, not a statement.
    SourceIn(
        id="x", name="x", kind="sql", endpoint="dsn", options={"query": "SELECT 'delete' AS a"}
    )
    with pytest.raises(ValueError, match="byte order"):
        SourceIn(
            id="x",
            name="x",
            kind="modbus",
            endpoint="tcp://plc:502",
            options={
                "registers": [{"name": "A", "address": 0, "data_type": "INT32", "byte_order": "AB"}]
            },
        )
    with pytest.raises(ValueError, match="tcp://"):
        SourceIn(id="x", name="x", kind="mqtt", endpoint="http://b", options={"topics": ["a"]})


def sources(catalog):
    return catalog.sources()


def test_the_configuration_holds_only_the_allowed_plugins(tmp_path):
    settings = make_settings(tmp_path, ingest_port=8186)
    catalog = CatalogStore(database(tmp_path, "config"))
    for source in (MQTT, MODBUS, SQL):
        catalog.save_source(source, create=True)
    text = render(settings, catalog.sources(), lambda source: 'se"cret', 10.0)
    config = tomllib.loads(text)
    assert set(config["inputs"]) == {"internal", *INPUTS.values()}
    assert list(config["outputs"]) == ["influxdb_v2"]
    assert config["outputs"]["influxdb_v2"][0]["token"] == gateway_token(tmp_path)
    mqtt = config["inputs"]["mqtt_consumer"][0]
    assert mqtt["topics"] == ["plant/#", "utilities/+/flow"] and mqtt["password"] == 'se"cret'
    assert mqtt["tags"] == {"histcraft_source": "broker"}
    modbus = config["inputs"]["modbus"][0]
    assert modbus["interval"] == "2s" and modbus["slave_id"] == 3
    assert modbus["holding_registers"][0]["address"] == [10, 11]
    assert modbus["coils"] == [{"name": "XV-1", "address": [4]}]
    sql = config["inputs"]["sql"][0]
    assert sql["dsn"] == 'postgres://reader:se"cret@lims:5432/lab' and sql["driver"] == "pgx"
    assert sql["tags"] == {"histcraft_source": "lims"}
    assert sql["query"][0]["tag_columns_include"] == ["tag"]
    path = tmp_path / "gateway" / "telegraf.conf"
    write_config(settings, catalog.sources(), lambda source: "", "")
    assert path.stat().st_mode & 0o777 == 0o600


def test_pushed_values_reach_their_points_and_browse(tmp_path):
    settings = make_settings(tmp_path, ingest_port=8186)
    catalog = CatalogStore(database(tmp_path, "config"))
    catalog.save_source(MODBUS, create=True)
    address = line_protocol.address(
        "modbus", {"name": "plc", "slave_id": "3", "type": "holding_register"}, "FT-101"
    )
    catalog.add_points([PointIn(tag="FT-101", source_id="plc", address=address, deviation=0)])
    collector = Collector(settings, catalog, ArchiveStore(database(tmp_path)))
    collector.reload()
    client = TestClient(ingest_app(collector, gateway_token(tmp_path)))
    body = "\n".join(
        f"modbus,histcraft_source=plc,name=plc,type=holding_register,slave_id=3 FT-101={v},LT-7=4i "
        f"{(1_700_000_000 + i) * 10**9}"
        for i, v in enumerate([1.0, 2.0, 3.0])
    )
    assert client.post("/api/v2/write", content=body).status_code == 401
    headers = {"Authorization": f"Token {gateway_token(tmp_path)}"}
    zipped = gzip.compress(body.encode())
    answer = client.post(
        "/api/v2/write", content=zipped, headers={**headers, "Content-Encoding": "gzip"}
    )
    assert answer.status_code == 204
    state = next(iter(collector.points.values()))
    assert state.reads == 3 and state.last == (1_700_000_002_000, 3.0)
    # Older values than the archive's newest are dropped; an unknown source is ignored.
    client.post(
        "/api/v2/write", content=body + "\nmodbus,histcraft_source=nope x=1", headers=headers
    )
    assert state.reads == 3
    collector.check_gateway()
    assert collector.source_status["plc"]["status"] == "connected"
    status, browsed = collector._answer_gateway(catalog.source("plc"), {"kind": "browse"})
    assert status == "ok"
    assert sorted(item["tag"] for item in browsed["variables"]) == ["FT-101", "LT-7"]
    assert client.post("/api/v2/write", content="garbage", headers=headers).status_code == 400


def test_browsed_series_get_readable_tags():
    seen = {
        "measurement": "mqtt_consumer",
        "tags": {"topic": "plant/area1/FT-101"},
        "field": "value",
        "value": 1.0,
    }
    assert variable("mqtt", "a", seen)["tag"] == "plant.area1.FT-101"
    seen = {"measurement": "sql", "tags": {"tag": "LAB-1"}, "field": "result", "value": "OK"}
    item = variable("sql", "a", seen)
    assert item["tag"] == "LAB-1.result" and item["kind"] == "text"


@pytest.mark.slow
def test_the_collector_listens_for_the_gateway(tmp_path):
    import socket
    import time

    import httpx

    from histcraft.collector.service import CollectorThread

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    settings = make_settings(tmp_path, ingest_port=port)
    catalog = CatalogStore(database(tmp_path, "config"))
    catalog.save_source(MQTT, create=True)
    address = line_protocol.address("mqtt_consumer", {"topic": "plant/FT-1"}, "value")
    catalog.add_points([PointIn(tag="plant.FT-1", source_id="broker", address=address)])
    archive = ArchiveStore(database(tmp_path))
    thread = CollectorThread(Collector(settings, catalog, archive))
    thread.start()
    try:
        headers = {"Authorization": f"Token {gateway_token(tmp_path)}"}
        deadline = time.monotonic() + 15
        while True:
            try:
                answer = httpx.post(
                    f"http://127.0.0.1:{port}/api/v2/write?precision=ms",
                    content="mqtt_consumer,topic=plant/FT-1,histcraft_source=broker value=7.5",
                    headers=headers,
                )
                break
            except httpx.TransportError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        assert answer.status_code == 204
        point = catalog.point("broker:plant.FT-1")["id"]
        while (archive.snapshots([point]).get(point) or {}).get("value") != 7.5:
            assert time.monotonic() < deadline
            time.sleep(0.2)
        config = (tmp_path / "gateway" / "telegraf.conf").read_text()
        assert '"broker"' in config and "mqtt_consumer" in config
    finally:
        thread.stop()


def test_64_bit_registers_name_all_eight_bytes_as_telegraf_does():
    # Found by the source test kit (2026-10-24): Telegraf refuses "ABCD" for four registers.
    from histcraft.catalog.gateway import check

    registers = [
        {"name": "F64", "address": 0, "data_type": "FLOAT64-IEEE", "byte_order": "CDAB"},
        {"name": "I64", "address": 4, "data_type": "INT64"},
        {"name": "F32", "address": 8, "data_type": "FLOAT32-IEEE", "byte_order": "CDAB"},
    ]
    found = check("modbus", "tcp://plc:502", {"registers": registers})["registers"]
    assert [item["byte_order"] for item in found] == ["GHEFCDAB", "ABCDEFGH", "CDAB"]
    with pytest.raises(ValueError, match="byte order"):
        check("modbus", "tcp://plc:502", {"registers": [{**registers[0], "byte_order": "AB"}]})


def test_integer_registers_with_a_fractional_scale_keep_their_decimals(tmp_path):
    # Found by the source test kit: Telegraf multiplies an INT16 by 0.1 into an integer.
    registers = [
        {"name": "LT", "address": 0, "data_type": "INT16", "scale": 0.1},
        {"name": "FT", "address": 1, "data_type": "UINT32", "scale": 0.01},
        {"name": "PT", "address": 3, "data_type": "INT16", "scale": 2},
    ]
    source = SourceIn(**{**MODBUS.model_dump(), "options": {"registers": registers}})
    settings = make_settings(tmp_path)
    text = render(settings, [{**source.model_dump(), "enabled": True}], lambda _: "", 10)
    assert 'name = "LT", byte_order = "AB", data_type = "FIXED", scale = 0.1' in text
    assert 'name = "FT", byte_order = "ABCD", data_type = "UFIXED", scale = 0.01' in text
    assert 'name = "PT", byte_order = "AB", data_type = "INT16", scale = 2.0' in text
    with pytest.raises(ValueError, match="whole-number scale"):
        one_byte = [{"name": "B", "address": 0, "data_type": "INT8L", "scale": 0.5}]
        SourceIn(**{**MODBUS.model_dump(), "options": {"registers": one_byte}})
