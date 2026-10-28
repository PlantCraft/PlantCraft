"""OPC UA: the Simulator itself (``simcraft serve``) collected live and read back in history."""

from __future__ import annotations

import time

import pytest
from simcraft.contracts import NAMESPACE_URI
from simcraft.server import OpcUaPlantServer
from simcraft.testkit.background import Background

from histcraft.catalog.models import PointIn, SourceIn
from histcraft.sources.history import open_source
from sources_check.conftest import free_port, wait

pytestmark = pytest.mark.slow
TAGS = {"FIC-101.PV": (0, 1000), "FIC-101.OP": (0, 100), "PIC-102.PV": (0, 250)}


def test_the_simulator_is_browsed_collected_and_read_back(historian, tmp_path):
    endpoint = f"opc.tcp://127.0.0.1:{free_port()}/plantcraft/"
    server = OpcUaPlantServer(
        endpoint=endpoint,
        history_db=tmp_path / "history.sqlite3",
        history_hours=0.05,
        sample_seconds=1.0,
    )
    with Background(server.start, server.stop, timeout=60):
        source = SourceIn(
            id="sim", name="Simulator", endpoint=endpoint, namespace_uri=NAMESPACE_URI
        )
        points = [
            PointIn(
                tag=tag,
                source_id="sim",
                address=f"ns=2;s=Plant.ControlLoops.{tag}",
                scan_seconds=0.5,
            )
            for tag in [*TAGS, "FIC-101.MODE"]
        ]
        historian.add(source, points)
        reader = open_source(historian.catalog.source("sim"), "")
        found = reader.browse("Plant.ControlLoops.FIC-101", limit=200)["variables"]
        assert {"FIC-101.PV", "FIC-101.MODE"} <= {
            item["tag"].rsplit("ControlLoops.", 1)[-1] for item in found
        }
        historian.thread.start()
        for tag, (low, high) in TAGS.items():
            value = wait(lambda t=tag: historian.snapshot(f"sim:{t}"), what=f"sim:{tag}")
            assert low <= value <= high, (tag, value)
        mode = wait(lambda: historian.snapshot("sim:FIC-101.MODE"), what="sim:FIC-101.MODE")
        assert mode in {"AUTO", "MAN", "CAS", "REMOTE"}
        now = int(time.time() * 1000)
        history = reader.recorded(["ns=2;s=Plant.ControlLoops.FIC-101.PV"], now - 120_000, now)
        times, values = next(iter(history.values()))
        assert len(times) >= 2 and list(times) == sorted(times)
        assert all(0 <= value <= 1000 for value in values)
