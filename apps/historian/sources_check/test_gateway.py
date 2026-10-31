"""MQTT, Modbus TCP and SQL through the suite's Telegraf, as in the suite: the collector writes
the gateway's configuration, Telegraf pushes to the collector, Browse lists what arrived and the
points added from it archive what the kit published."""

from __future__ import annotations

import pytest
from simcraft.testkit import modbus, mqtt, sql
from simcraft.testkit.background import Background

from histcraft.catalog.models import PointIn, SourceIn
from histcraft.collector.gateway import variable
from sources_check.conftest import free_port, rebuilt, wait

pytestmark = pytest.mark.slow


def browse_and_add(historian, source_id: str, count: int) -> dict[str, dict]:
    """Wait until the gateway sent ``count`` series of the source, add a point for each as
    Browse suggests, and return the variables by tag."""

    collector = historian.thread.collector
    kind = historian.catalog.source(source_id)["kind"]
    wait(
        lambda: len(collector.seen.get(source_id, {})) >= count,
        timeout=60,
        what=lambda: (
            f"{count} series from {source_id}, got "
            f"{sorted(collector.seen.get(source_id, {}))}\n{historian.gateway_log()[-3000:]}"
        ),
    )
    found = {}
    for address, seen in dict(collector.seen[source_id]).items():
        item = variable(kind, address, seen)
        found[item["tag"]] = item
    historian.catalog.add_points(
        [
            PointIn(tag=tag, source_id=source_id, address=item["address"], deviation=0)
            for tag, item in found.items()
        ]
    )
    return found


def test_mqtt_values_and_json_reach_their_points(historian, telegraf, series):
    port = free_port()
    broker = mqtt.MqttPlant(series, port=port, qos=1, period=0.5)
    expected = mqtt.expected(series)
    with Background(broker.start, broker.stop):
        for source_id, data_format, topics in (
            ("broker-value", "value", ["plant/value/#"]),
            ("broker-json", "json", ["plant/json/+", "plant/nested/+"]),
        ):
            historian.add(
                SourceIn(
                    id=source_id,
                    name=source_id,
                    kind="mqtt",
                    endpoint=broker.url,
                    options={"topics": topics, "qos": 1, "data_format": data_format},
                ),
                [],
            )
        historian.thread.start()
        historian.start_gateway(telegraf)
        values = browse_and_add(historian, "broker-value", 9)
        json_ = browse_and_add(historian, "broker-json", 18)
        assert set(values) | set(json_) == set(expected)
        for tag, value in expected.items():
            source = "broker-value" if tag.startswith("plant.value.") else "broker-json"
            wait(
                lambda s=source, t=tag, v=value: historian.snapshot(f"{s}:{t}") == pytest.approx(v),
                what=f"{source}:{tag} = {value}",
            )
        assert historian.status("broker-value")["status"] == "connected"


def test_modbus_registers_in_every_layout_read_back(historian, telegraf, series):
    port = free_port()
    device = modbus.ModbusPlant(series, port=port)
    expected = modbus.expected(series)
    with Background(device.start, device.stop):
        historian.add(
            SourceIn(
                id="plc",
                name="PLC",
                kind="modbus",
                endpoint=device.url,
                default_scan_seconds=1,
                options=modbus.options(),
            ),
            [],
        )
        historian.thread.start()
        historian.start_gateway(telegraf)
        found = browse_and_add(historian, "plc", len(expected))
        assert set(found) == set(expected)
        for tag, value in expected.items():
            wait(
                lambda t=tag, v=value: historian.snapshot(f"plc:{t}") == pytest.approx(v, rel=1e-9),
                what=f"plc:{tag} = {value} (now {historian.snapshot(f'plc:{tag}')})",
            )


def test_sql_wide_long_and_naive_tables_archive_the_plant(historian, telegraf, postgres, series):
    sql.write(postgres, series)
    expected = sql.expected(series)
    # Every sample is rebuilt from the archive below, so the archive must keep every change: no
    # exception or compression deviation (the defaults are PI-like, 0.1 % and 0.2 %).
    historian.catalog.update_settings(
        {"default_deviation_percent": 0, "default_exception_percent": 0}
    )
    for table, options in sql.SOURCES.items():
        historian.add(
            SourceIn(
                id=table.replace("_", "-"),
                name=table,
                kind="sql",
                endpoint=postgres,
                default_scan_seconds=1,
                options={"driver": "postgres", **options},
            ),
            [],
        )
    historian.thread.start()
    historian.start_gateway(telegraf)
    for table, wanted in expected.items():
        source_id = table.replace("_", "-")
        found = browse_and_add(historian, source_id, len(wanted))
        assert set(found) == set(wanted), table
        for tag, samples in wanted.items():
            signal = f"{source_id}:{tag}"
            # The newest value is the snapshot; the archive holds what the compressor closed.
            wait(
                lambda s=signal, v=samples[-1][1]: historian.snapshot(s) == pytest.approx(v),
                what=lambda s=signal: f"{s}: snapshot {historian.snapshot(s)}",
            )
            times, values = historian.archived(signal)
            # Telegraf sends a long table's scan in batches of 1000 rows: a point added between
            # two batches archives from the second one on, and the archive only moves forward,
            # so the next scans' older rows are dropped. Compare what the archive spans.
            inside = [(t, v) for t, v in samples if times[0] <= t <= times[-1]]
            assert inside, (signal, len(samples))
            again = rebuilt(times, values, [t for t, _ in inside], step=False)
            assert again == pytest.approx([v for _, v in inside], rel=1e-9), signal


def test_values_read_while_the_collector_is_away_arrive_after_a_gateway_restart(
    historian, telegraf, series
):
    # Store and forward (H3): the collector stops, the gateway keeps reading into its disk
    # buffer, is killed and started again, and every second read meanwhile reaches the
    # collector once it is back, in order.
    import time

    from histcraft.collector.service import Collector, CollectorThread

    port = free_port()
    device = modbus.ModbusPlant(series, port=port)
    with Background(device.start, device.stop):
        historian.add(
            SourceIn(
                id="plc",
                name="PLC",
                kind="modbus",
                endpoint=device.url,
                default_scan_seconds=1,
                options=modbus.options(),
            ),
            [],
        )
        historian.thread.start()
        historian.start_gateway(telegraf)
        browse_and_add(historian, "plc", len(modbus.expected(series)))
        historian.thread.stop()
        away_from = int(time.time() * 1000)
        time.sleep(6)
        assert historian.gateway is not None
        historian.gateway.kill()  # no clean shutdown: only the disk keeps what it read
        historian.gateway.wait(10)
        historian.start_gateway(telegraf)
        time.sleep(4)
        away_until = int(time.time() * 1000)
        collector = Collector(historian.settings, historian.catalog, historian.archive)
        times: list[int] = []
        taken = collector.ingest

        def recording(metrics):
            times.extend(m.at_ms for m in metrics if m.tags.get("histcraft_source") == "plc")
            return taken(metrics)

        collector.ingest = recording  # type: ignore[method-assign]
        historian.thread = CollectorThread(collector)
        historian.thread.start()
        inside = lambda: sorted({at // 1000 for at in times if away_from < at < away_until})  # noqa: E731
        # At one read a second, at least 8 of the 10 seconds away (the first may fall before).
        wait(
            lambda: len(inside()) >= 8,
            timeout=60,
            what=lambda: f"reads while away: {inside()}\n{historian.gateway_log()[-3000:]}",
        )
        assert "buffer" in (historian.data_dir / "gateway" / "telegraf.conf").read_text()
