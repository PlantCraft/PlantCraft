"""The collector against a real OPC UA server (tests/opcua_server.py), end to end."""

from __future__ import annotations

import time

import pytest

from histcraft.archive.query import PointRef, Reader
from histcraft.archive.store import ArchiveStore
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector, CollectorThread
from histcraft.db import Database
from tests.conftest import TEST_DATABASE_URL, database, make_settings, postgres_url
from tests.opcua_server import NAMESPACE, PlantServer

# A real OPC UA server on a local socket: the slow tier (PlantCraft docs/testing.md).
pytestmark = pytest.mark.slow


def wait_for(check, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


@pytest.fixture
def server():
    plant = PlantServer(period=0.1).start()
    yield plant
    plant.stop()


@pytest.fixture
def setup(tmp_path, server):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    catalog.save_source(
        SourceIn(id="plant", name="Test plant", endpoint=server.endpoint, namespace_uri=NAMESPACE),
        create=True,
    )
    catalog.add_points(
        [
            PointIn(
                tag="TI-100.PV",
                source_id="plant",
                address="ns=2;s=TI-100.PV",
                scan_seconds=0.2,
                deviation=0.1,
            ),
            PointIn(
                tag="FIC-101.PV",
                source_id="plant",
                address="ns=2;s=FIC-101.PV",
                scan_seconds=0.2,
                deviation=0.5,
            ),
            PointIn(
                tag="FIC-101.MODE",
                source_id="plant",
                address="ns=2;s=FIC-101.MODE",
                kind="text",
                scan_seconds=0.2,
            ),
            PointIn(tag="BAD", source_id="plant", address="ns=2;s=missing", scan_seconds=0.5),
        ]
    )
    collector = Collector(settings, catalog, archive)
    thread = CollectorThread(collector)
    thread.start()
    yield catalog, archive, collector
    thread.stop()


def ids(catalog):
    return {p["tag"]: p for p in catalog.points()}


def test_collects_compresses_and_reports_status(setup, server):
    catalog, archive, collector = setup
    points = ids(catalog)
    ramp = points["TI-100.PV"]["id"]
    wait_for(lambda: (archive.snapshots([ramp]).get(ramp) or {}).get("reads", 0) >= 20)
    server.set("FIC-101.PV", 60.0)
    server.set("FIC-101.MODE", "MAN")
    time.sleep(1.0)
    snaps = archive.snapshots()
    assert snaps[points["FIC-101.PV"]["id"]]["value"] == 60.0
    assert snaps[points["FIC-101.MODE"]["id"]]["value"] == "MAN"
    assert snaps[points["BAD"]["id"]]["status"] == "bad"
    reader = Reader(archive)
    mode = points["FIC-101.MODE"]
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    _, labels = reader.series(
        PointRef(mode["id"], mode["tag"], "text"), now - timedelta(minutes=5), now, None
    )
    assert labels[0] == "AUTO" and labels[-1] == "MAN"
    # A ramp (with timing jitter) within a 0.1 deviation keeps few values: far fewer archived than read.
    snap = archive.snapshots([ramp])[ramp]
    assert snap["archived"] < snap["reads"] / 3
    state = archive.state()["collector"]
    assert state["sources"]["plant"]["status"] == "connected"


def test_a_lost_server_is_a_gap_and_reconnects(setup, server, tmp_path):
    catalog, archive, collector = setup
    point = ids(catalog)["TI-100.PV"]
    wait_for(lambda: (archive.snapshots([point["id"]]).get(point["id"]) or {}).get("reads", 0) >= 5)
    server.stop()
    wait_for(lambda: archive.snapshots([point["id"]])[point["id"]]["status"] == "disconnected", 30)
    times, values = archive.read(point["id"], 0, 10**13)
    assert any(v != v for v in values)  # a NaN gap marker was archived


def test_browse_and_test_requests_are_answered_by_the_collector(setup):
    catalog, archive, _ = setup
    browse = catalog.add_request("browse", "plant", "admin")
    test = catalog.add_request("test", "plant", "admin")
    result = wait_for(lambda: archive.request_result(browse))
    assert result["status"] == "ok"
    tags = {v["tag"]: v for v in result["result"]["variables"]}
    assert tags["TI-100.PV"]["unit"] == "degC" and tags["TI-100.PV"]["high"] == 200.0
    assert tags["FIC-101.MODE"]["kind"] == "text"
    assert tags["XV-102.OPEN"]["step"] is True
    assert wait_for(lambda: archive.request_result(test))["status"] == "ok"


def test_a_retired_point_keeps_its_archive_until_it_is_purged(setup):
    catalog, archive, collector = setup
    point = ids(catalog)["FIC-101.PV"]
    wait_for(lambda: point["id"] in archive.point_ids())
    catalog.retire_points(["plant:FIC-101.PV"], by="ana")
    wait_for(lambda: point["id"] not in collector.points)
    assert point["id"] in archive.point_ids()
    assert catalog.restore_points([point["id"]])["restored"] == ["plant:FIC-101.PV"]
    wait_for(lambda: point["id"] in collector.points)
    catalog.retire_points(["plant:FIC-101.PV"])
    catalog.purge_retired([point["id"]])
    wait_for(lambda: point["id"] not in archive.point_ids())


def test_configuration_changes_apply_without_restart(setup):
    catalog, archive, collector = setup
    catalog.add_points(
        [PointIn(tag="N5001", source_id="plant", address="ns=2;i=5001", scan_seconds=0.2)]
    )
    point = ids(catalog)["N5001"]
    wait_for(lambda: (archive.snapshots([point["id"]]).get(point["id"]) or {}).get("value") == 1.0)


def test_a_number_point_that_reads_text_becomes_text(setup):
    """A MODE added while its source could not describe it (a number) heals itself."""

    catalog, archive, collector = setup
    catalog.retire_points(["plant:FIC-101.MODE"])
    catalog.add_points(
        [PointIn(tag="MODE", source_id="plant", address="ns=2;s=FIC-101.MODE", scan_seconds=0.2)]
    )
    point = ids(catalog)["MODE"]
    assert point["kind"] == "number"
    state = wait_for(lambda: collector.points.get(point["id"]))
    healed = wait_for(lambda: ids(catalog)["MODE"]["kind"] == "text" and ids(catalog)["MODE"])
    assert healed["step"]
    wait_for(
        lambda: (archive.snapshots([point["id"]]).get(point["id"]) or {}).get("value") == "AUTO"
    )
    assert collector.points[point["id"]] is state  # the scan task keeps feeding the same state
    wait_for(lambda: "AUTO" in archive.read(point["id"], 0, 10**13)[1] or None, 20)
    backfills = [r for r in catalog.requests(0) if r["kind"] == "backfill"]
    assert backfills and backfills[-1]["detail"]["points"] == [point["id"]]


def test_a_stop_is_archived_as_a_gap(tmp_path, server):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    catalog.save_source(SourceIn(id="plant", name="P", endpoint=server.endpoint), create=True)
    catalog.add_points(
        [
            PointIn(
                tag="FIC-101.PV", source_id="plant", address="ns=2;s=FIC-101.PV", scan_seconds=0.2
            )
        ]
    )
    thread = CollectorThread(Collector(settings, catalog, archive))
    thread.start()
    wait_for(lambda: (archive.snapshots().get(1) or {}).get("reads", 0) >= 3)
    thread.stop()
    times, values = archive.read(1, 0, 10**13)
    assert values[0] == 50.0 and values[-1] != values[-1]  # ends with the "no data" marker
    assert archive.snapshots()[1]["status"] == "disconnected"


def test_healthcheck_follows_the_heartbeat(tmp_path, monkeypatch):
    from histcraft.cli import main

    monkeypatch.setenv("HISTCRAFT_DATA_DIR", str(tmp_path))
    if TEST_DATABASE_URL:
        monkeypatch.setenv("HISTCRAFT_DATABASE_URL", postgres_url(tmp_path))
    assert main(["healthcheck"]) == 1
    archive = ArchiveStore(database(tmp_path))
    archive.set_state("collector", {"heartbeat": int(time.time() * 1000)})
    assert main(["healthcheck"]) == 0
    archive.set_state("collector", {"heartbeat": int(time.time() * 1000) - 600_000})
    assert main(["healthcheck"]) == 1


def test_a_long_housekeeping_does_not_hold_the_flushes(tmp_path, server):
    """Compaction takes minutes on a large archive: the flushes go on meanwhile."""

    import threading

    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    catalog.save_source(SourceIn(id="plant", name="P", endpoint=server.endpoint), create=True)
    catalog.add_points(
        [
            PointIn(
                tag="FIC-101.PV", source_id="plant", address="ns=2;s=FIC-101.PV", scan_seconds=0.2
            )
        ]
    )
    collector = Collector(settings, catalog, archive)
    release, started = threading.Event(), threading.Event()

    def slow_housekeeping(*, force=False):
        started.set()
        release.wait(20)
        return {}

    collector.housekeeping = slow_housekeeping
    thread = CollectorThread(collector)
    thread.start()
    try:
        wait_for(started.is_set)
        reads = (archive.snapshots().get(1) or {}).get("reads", 0)
        wait_for(lambda: archive.snapshots()[1]["reads"] >= reads + 3)
    finally:
        release.set()
        thread.stop()


def test_a_calculated_point_follows_its_inputs(setup, server):
    catalog, archive, collector = setup
    catalog.add_points(
        [
            PointIn(
                tag="FIC-101.DOUBLE",
                source_id="calc",
                address="[plant:FIC-101.PV] * 2",
                scan_seconds=0.2,
                deviation=0,
            )
        ]
    )
    point = ids(catalog)["FIC-101.DOUBLE"]["id"]
    server.set("FIC-101.PV", 21.0)
    wait_for(lambda: (archive.snapshots([point]).get(point) or {}).get("value") == 42.0)
    assert archive.snapshots([point])[point]["status"] == "ok"
    # The collector publishes its state on its own beat, maybe after the first value.
    wait_for(
        lambda: (
            (archive.state().get("collector") or {})
            .get("sources", {})
            .get("calc", {})
            .get("status")
            == "connected"
        )
    )


@pytest.fixture
def subscribed(tmp_path, server):
    """The same plant with ``subscribe`` on (H4); every Read the collector makes is counted."""

    from histcraft.collector.opcua import OpcUaReader

    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    catalog.save_source(
        SourceIn(
            id="plant",
            name="Test plant",
            endpoint=server.endpoint,
            namespace_uri=NAMESPACE,
            options={"subscribe": True},
        ),
        create=True,
    )
    catalog.add_points(
        [
            PointIn(
                tag="FIC-101.PV",
                source_id="plant",
                address="ns=2;s=FIC-101.PV",
                scan_seconds=0.2,
                deviation=0.5,
                max_seconds=1,
            ),
            PointIn(
                tag="FIC-101.MODE",
                source_id="plant",
                address="ns=2;s=FIC-101.MODE",
                kind="text",
                scan_seconds=0.2,
            ),
            PointIn(tag="BAD", source_id="plant", address="ns=2;s=missing", scan_seconds=0.5),
        ]
    )
    reads: list[list[str]] = []

    class Counted(OpcUaReader):
        async def read(self, addresses):
            reads.append(list(addresses))
            return await super().read(addresses)

    collector = Collector(
        settings,
        catalog,
        archive,
        reader_factory=lambda source: Counted(source, timeout=settings.opcua_timeout),
    )
    thread = CollectorThread(collector)
    thread.start()
    yield catalog, archive, collector, reads
    thread.stop()


def test_a_subscribed_source_takes_changes_without_reading_each_scan(subscribed, server):
    """H4: the server reports changes; only the address it refused is read on a scan."""

    catalog, archive, collector, reads = subscribed
    points = ids(catalog)
    wait_for(lambda: (collector.source_status.get("plant") or {}).get("reading") == "subscription")
    server.set("FIC-101.PV", 61.5)
    server.set("FIC-101.MODE", "CAS")
    snapshot = lambda tag: archive.snapshots().get(points[tag]["id"]) or {}  # noqa: E731
    wait_for(lambda: snapshot("FIC-101.PV").get("value") == 61.5)
    wait_for(lambda: snapshot("FIC-101.MODE").get("value") == "CAS")
    status = collector.source_status["plant"]
    assert (status["monitored"], status["scanned"]) == (2, 1)
    wait_for(lambda: snapshot("BAD").get("status") == "bad")
    # A value that holds is still taken every scan period (a steady signal is archived at its
    # longest interval), with no Read of it: the only address read is the one refused.
    held = snapshot("FIC-101.MODE").get("reads", 0)
    time.sleep(1.5)
    assert snapshot("FIC-101.MODE").get("reads", 0) >= held + 3
    assert reads and all(addresses == ["ns=2;s=missing"] for addresses in reads)
    times, _ = archive.read(points["FIC-101.PV"]["id"], 0, 10**13)
    assert len(times) >= 2


def test_a_subscribed_source_lost_is_a_gap(subscribed, server):
    catalog, archive, collector, _ = subscribed
    point = ids(catalog)["FIC-101.PV"]
    wait_for(lambda: (collector.source_status.get("plant") or {}).get("reading") == "subscription")
    server.stop()
    wait_for(lambda: archive.snapshots([point["id"]])[point["id"]]["status"] == "disconnected", 30)
