"""Backfill: a source's own history copied into the archive, up to where archiving began."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.backfill import WINDOW_MS, backfill
from histcraft.collector.service import Collector
from histcraft.db import Database
from tests.conftest import database, make_settings
from tests.opcua_history_server import NAMESPACE, HistoryServer
from tests.test_query import MS

# A real OPC UA server on a local socket: the slow tier (PlantCraft docs/testing.md).
pytestmark = pytest.mark.slow

HOUR = 3600 * 1000


class History:
    """A source keeping one value a minute of a ramp and a mode, for any window asked."""

    def __init__(self):
        self.calls = []

    def recorded(self, addresses, start_ms, end_ms):
        self.calls.append((tuple(addresses), start_ms, end_ms))
        # The value just before the window comes too, as OPC UA HistoryRead answers.
        times = np.arange(start_ms - start_ms % 60_000 - 60_000, end_ms + 1, 60_000)
        out = {}
        for address in addresses:
            if address == "PV":
                out[address] = (times, (times - MS) / 60_000.0)
            elif address == "MODE":
                out[address] = (times, ["AUTO" if (t - MS) < 6 * HOUR else "MAN" for t in times])
            else:
                out[address] = "BadNodeIdUnknown"
        return out


POINTS = [
    {"id": 1, "signal": "plant:PV", "address": "PV", "kind": "number"},
    {"id": 2, "signal": "plant:MODE", "address": "MODE", "kind": "text"},
    {"id": 3, "signal": "plant:GONE", "address": "GONE", "kind": "number"},
]


def test_the_archive_gets_the_source_history_before_its_first_value(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    # Archived since 10 h after MS only.
    archive.append({1: ("number", [(MS + 10 * HOUR, -1.0)])})
    history = History()
    result = backfill(history, archive, POINTS, MS, MS + 12 * HOUR)
    times, values = archive.read(1, MS, MS + 12 * HOUR)
    # One value a minute from MS to the first archived value, then the archive's own.
    assert len(times) == 10 * 60 + 1
    assert values[0] == 0.0 and values[-2] == 599.0 and values[-1] == -1.0
    assert np.all(np.diff(times) > 0)
    mode_times, labels = archive.read(2, MS, MS + 12 * HOUR)
    assert labels[0] == "AUTO" and labels[-1] == "MAN" and len(mode_times) == 12 * 60
    assert result["signals"] == 2 and result["failed"] == 1
    assert result["errors"] == {"plant:GONE": "BadNodeIdUnknown"}
    # Windows of a few hours, all three signals in each read
    assert all(end - start <= WINDOW_MS for _, start, end in history.calls)
    assert len(history.calls) == 2


def test_a_second_backfill_adds_only_what_is_older(tmp_path):
    archive = ArchiveStore(database(tmp_path))
    backfill(History(), archive, POINTS[:1], MS + HOUR, MS + 2 * HOUR)
    again = backfill(History(), archive, POINTS[:1], MS, MS + 2 * HOUR)
    times, _ = archive.read(1, MS, MS + 2 * HOUR)
    assert again["values"] == 60
    assert len(times) == 120 and len(set(times.tolist())) == 120


def test_the_collector_answers_a_backfill_request_from_opcua_history(tmp_path):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    archive = ArchiveStore(Database(settings.archive_target))
    with HistoryServer(minutes=10, sample_seconds=30) as server:
        catalog.save_source(
            SourceIn(id="ua", name="UA", endpoint=server.endpoint, namespace_uri=NAMESPACE),
            create=True,
        )
        catalog.add_points(
            [
                PointIn(tag="FIC-101.PV", source_id="ua", address="FIC-101.PV"),
                PointIn(tag="FIC-101.MODE", source_id="ua", address="FIC-101.MODE", kind="text"),
            ]
        )
        collector = Collector(settings, catalog, archive)
        request = catalog.add_request("backfill", "ua", "admin", {"hours": 1})

        async def answer():
            await collector.answer_requests()
            await asyncio.gather(*collector._backfills.values())

        asyncio.run(answer())
    answer = archive.request_result(request)
    assert answer["status"] == "ok", answer
    assert answer["result"]["signals"] == 2 and answer["result"]["failed"] == 0
    points = {p["tag"]: p["id"] for p in catalog.points()}
    times, values = archive.read(points["FIC-101.PV"], 0, 10**13)
    # The stored ten minutes (the server also historizes its variables' starting value, 0.0).
    assert len(times) >= 20 and all(48 <= v <= 52 for v in values[:20])
    _, labels = archive.read(points["FIC-101.MODE"], 0, 10**13)
    assert set(labels) == {"AUTO", "MAN"}
