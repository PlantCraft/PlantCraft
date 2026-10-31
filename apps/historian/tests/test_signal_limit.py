"""MAX_SIGNALS of the installation file (PLANTCRAFT_MAX_SIGNALS, docs/installation-file.md): the
Historian records at most that many points; the rest are skipped with the reason."""

from __future__ import annotations

from histcraft.catalog.models import PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from tests.conftest import database


def _catalog(tmp_path) -> CatalogStore:
    catalog = CatalogStore(database(tmp_path, "catalog"))
    catalog.save_source(SourceIn(id="ua", name="UA", endpoint="opc.tcp://plant:4840"), create=True)
    return catalog


def _points(*tags: str) -> list[PointIn]:
    return [PointIn(tag=tag, source_id="ua", address=tag) for tag in tags]


def test_points_past_the_installation_limit_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANTCRAFT_MAX_SIGNALS", "3")
    catalog = _catalog(tmp_path)
    first = catalog.add_points(_points("A", "B"))
    assert first["added"] == ["ua:A", "ua:B"]
    second = catalog.add_points(_points("C", "D", "E"))
    assert second["added"] == ["ua:C"]
    assert [item["tag"] for item in second["skipped"]] == ["D", "E"]
    assert "limit of 3 signals" in second["skipped"][0]["reason"]


def test_no_limit_without_the_setting(tmp_path, monkeypatch):
    monkeypatch.delenv("PLANTCRAFT_MAX_SIGNALS", raising=False)
    catalog = _catalog(tmp_path)
    assert len(catalog.add_points(_points(*[f"T{i}" for i in range(20)]))["added"]) == 20
