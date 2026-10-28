"""Settings in three levels, the most specific wins (app standard, D8): general, source, point."""

from __future__ import annotations

import pytest

from histcraft.archive.store import ArchiveStore, now_ms
from histcraft.catalog.models import PointIn, PointPatch, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.collector.service import Collector
from histcraft.db import Database
from tests.conftest import make_settings

DAY_MS = 86_400_000


def _catalog(tmp_path):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    return settings, catalog


def _source(catalog, source_id="plant", **overrides):
    return catalog.save_source(
        SourceIn(id=source_id, name=source_id, endpoint="opc.tcp://127.0.0.1:4999", **overrides),
        create=True,
    )


def test_general_settings_apply_when_nothing_else_is_set(tmp_path):
    _, catalog = _catalog(tmp_path)
    _source(catalog)
    catalog.add_points([PointIn(tag="TI-1", source_id="plant", low=0, high=200)])
    point = catalog.point("plant:TI-1")
    assert point["retention_days"] == 400
    assert point["scan_seconds"] == 1.0
    assert point["deviation"] == 0.4  # 0.2 % of a 200 span (D1)
    assert point["exception"] == 0.2  # 0.1 %
    assert point["max_seconds"] == 600.0
    assert set(point["origins"].values()) == {"general"}
    assert point["own"] == dict.fromkeys(point["own"])  # all None
    # The general settings change: the point follows them.
    catalog.update_settings({"retention_days": 90, "default_deviation_percent": 1})
    point = catalog.point("plant:TI-1")
    assert (point["retention_days"], point["deviation"]) == (90, 2.0)


def test_source_retention_beats_general_and_point_beats_source(tmp_path):
    _, catalog = _catalog(tmp_path)
    source = _source(catalog, retention_days=30, default_scan_seconds=5)
    assert (source["retention_days"], source["default_scan_seconds"]) == (30, 5.0)
    assert source["default_max_seconds"] is None
    catalog.add_points(
        [
            PointIn(tag="A", source_id="plant"),
            PointIn(tag="B", source_id="plant", retention_days=7, scan_seconds=0.5),
        ]
    )
    a, b = catalog.point("plant:A"), catalog.point("plant:B")
    assert (a["retention_days"], a["origins"]["retention_days"]) == (30, "source")
    assert (a["scan_seconds"], a["origins"]["scan_seconds"]) == (5.0, "source")
    assert a["origins"]["max_seconds"] == "general"
    assert (b["retention_days"], b["origins"]["retention_days"]) == (7, "point")
    assert (b["scan_seconds"], b["origins"]["scan_seconds"]) == (0.5, "point")
    assert b["own"]["retention_days"] == 7


def test_patch_sets_and_clears_a_point_override(tmp_path):
    _, catalog = _catalog(tmp_path)
    _source(catalog, default_max_seconds=600)
    catalog.add_points([PointIn(tag="A", source_id="plant")])
    point = catalog.update_point("plant:A", PointPatch(max_seconds=60, retention_days=5))
    assert (point["max_seconds"], point["origins"]["max_seconds"]) == (60.0, "point")
    assert point["origins"]["retention_days"] == "point"
    point = catalog.update_point("plant:A", PointPatch(max_seconds=None, retention_days=None))
    assert (point["max_seconds"], point["origins"]["max_seconds"]) == (600.0, "source")
    assert (point["retention_days"], point["origins"]["retention_days"]) == (400, "general")


def test_source_update_keeps_overrides_it_does_not_send(tmp_path):
    _, catalog = _catalog(tmp_path)
    _source(catalog, retention_days=30)
    same = SourceIn(id="plant", name="Renamed", endpoint="opc.tcp://127.0.0.1:4999")
    assert catalog.save_source(same, create=False)["retention_days"] == 30
    cleared = SourceIn(
        id="plant", name="Renamed", endpoint="opc.tcp://127.0.0.1:4999", retention_days=None
    )
    assert catalog.save_source(cleared, create=False)["retention_days"] is None


def test_collector_housekeeping_uses_the_source_retention(tmp_path, monkeypatch):
    settings, catalog = _catalog(tmp_path)
    archive = ArchiveStore(Database(settings.archive_target))
    _source(catalog, "short", retention_days=10)
    _source(catalog, "long")
    catalog.add_points(
        [
            PointIn(tag="A", source_id="short"),
            PointIn(tag="B", source_id="short", retention_days=3),
            PointIn(tag="C", source_id="long"),
        ]
    )
    seen: dict[int, int] = {}
    monkeypatch.setattr(archive, "prune", lambda cutoffs: seen.update(cutoffs) or 0)
    before = now_ms()
    Collector(settings, catalog, archive).housekeeping(force=True)
    days = {
        tag: round((before - seen[catalog.point(signal)["id"]]) / DAY_MS)
        for tag, signal in (("A", "short:A"), ("B", "short:B"), ("C", "long:C"))
    }
    assert days == {"A": 10, "B": 3, "C": 400}


def test_api_carries_source_settings_and_point_origins(client):
    source = {
        "id": "plant",
        "name": "Plant",
        "kind": "opcua",
        "endpoint": "opc.tcp://127.0.0.1:4999",
        "retention_days": 60,
    }
    created = client.post("/hist/api/sources", json=source)
    assert created.status_code == 201, created.text
    assert created.json()["retention_days"] == 60
    updated = client.put("/hist/api/sources/plant", json={**source, "default_scan_seconds": 2})
    assert updated.json()["default_scan_seconds"] == 2.0
    assert updated.json()["retention_days"] == 60
    listed = next(item for item in client.get("/hist/api/sources").json() if item["id"] == "plant")
    assert listed["default_scan_seconds"] == 2.0
    client.post("/hist/api/points", json={"points": [{"tag": "TI-1", "source_id": "plant"}]})
    point = client.get("/hist/api/points/plant:TI-1").json()
    assert point["retention_days"] == 60
    assert point["origins"] == {
        "retention_days": "source",
        "scan_seconds": "source",
        "deviation": "general",
        "max_seconds": "general",
        "exception": "general",
    }
    assert client.get("/hist/api/points/plant:nope").status_code == 404
    bad = client.put("/hist/api/sources/plant", json={**source, "retention_days": -3})
    assert bad.status_code == 422


def test_points_added_from_browse_without_a_range_get_the_default_compression(tmp_path):
    # OPC UA servers seldom publish EURange: Browse adds points with no low/high and no
    # deviation. They take the general (or the source's) share, of the value instead of a span.
    _, catalog = _catalog(tmp_path)
    _source(catalog)
    _source(catalog, "tight", default_deviation_percent=0.5)
    catalog.add_points(
        [
            PointIn(tag="FIC-101.PV", source_id="plant", address="ns=2;s=FIC-101.PV"),
            PointIn(tag="FIC-101.PV", source_id="tight"),
            PointIn(tag="RANGED", source_id="plant", low=0, high=200),
            PointIn(tag="OWN", source_id="plant", deviation=0.3),
            PointIn(tag="RUNNING", source_id="plant", step=True),
            PointIn(tag="MODE", source_id="plant", kind="text"),
        ]
    )
    browsed = catalog.point("plant:FIC-101.PV")
    assert browsed["origins"]["deviation"] == "general"
    assert (browsed["deviation"], browsed["deviation_percent"]) == (0.0, 0.2)
    assert catalog.point("tight:FIC-101.PV")["deviation_percent"] == 0.5
    ranged = catalog.point("plant:RANGED")
    assert (ranged["deviation"], ranged["deviation_percent"]) == (0.4, None)
    own = catalog.point("plant:OWN")
    assert (own["deviation"], own["deviation_percent"]) == (0.3, None)
    assert catalog.point("plant:RUNNING")["deviation_percent"] is None
    assert catalog.point("plant:MODE")["deviation_percent"] is None
    # Giving the point a range later switches it to the share of the span.
    point = catalog.update_point("plant:FIC-101.PV", PointPatch(low=0, high=50))
    assert (point["deviation"], point["deviation_percent"]) == (0.1, None)


def test_collector_compresses_a_point_without_a_range_to_a_share_of_its_value(tmp_path):
    from histcraft.collector.service import _compressor

    _, catalog = _catalog(tmp_path)
    _source(catalog)
    catalog.add_points([PointIn(tag="FIC-101.PV", source_id="plant")])
    compressor = _compressor(catalog.point("plant:FIC-101.PV"))
    times = [i * 1000 for i in range(600)]
    # A flow near 100 with 0.01 of noise: within 0.1 % of the value (0.1), so lines.
    values = [100.0 + 0.01 * ((i * 7) % 5 - 2) + i * 0.001 for i in range(600)]
    archived = []
    for at, value in zip(times, values, strict=True):
        archived += compressor.feed(at, value)
    assert compressor.tolerance() > 0.09
    assert len(archived) < len(values) / 10


def test_a_steady_signal_is_archived_at_least_every_ten_minutes():
    """Apps read a longer interval as a gap (Link's availability check: 10 min), so a constant
    setpoint archived with the default settings must not look like hours without data."""

    from histcraft.archive.compression import Compressor
    from histcraft.catalog.models import DEFAULT_SETTINGS

    compressor = Compressor(deviation=0.1, max_seconds=DEFAULT_SETTINGS["default_max_seconds"])
    kept = []
    for second in range(0, 3 * 3600, 5):
        kept += [at for at, _ in compressor.feed(second * 1000, 50.0)]
    gaps = [b - a for a, b in zip(kept, kept[1:], strict=False)]
    assert gaps and max(gaps) <= 600_000


def test_profiles_set_the_compression(tmp_path):
    _, catalog = _catalog(tmp_path)
    _source(catalog)
    catalog.add_points(
        [
            PointIn(tag="FINE", source_id="plant", low=0, high=100, profile="fine"),
            PointIn(tag="RAW", source_id="plant", low=0, high=100, profile="none"),
            PointIn(tag="OWN", source_id="plant", low=0, high=100, deviation=1.0, exception=0.5),
        ]
    )
    fine, raw, own = (catalog.point(f"plant:{tag}") for tag in ("FINE", "RAW", "OWN"))
    assert (fine["exception"], fine["deviation"], fine["origins"]["deviation"]) == (
        0.05,
        0.1,
        "profile",
    )
    assert (raw["exception"], raw["deviation"]) == (0.0, 0.0)
    assert (own["exception"], own["deviation"], own["origins"]["exception"]) == (0.5, 1.0, "point")
    # Back to the standard profile: the general settings again.
    back = catalog.update_point("plant:FINE", PointPatch(profile=""))
    assert (back["profile"], back["deviation"], back["exception"]) == ("", 0.2, 0.1)
    with pytest.raises(ValueError):
        PointPatch(profile="coarse")
