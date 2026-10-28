"""Removing a point retires it: the archive stays, restorable, for RETIRED_DAYS (catalog)."""

from __future__ import annotations

from histcraft.catalog.models import RETIRED_DAYS, PointIn, SourceIn
from histcraft.catalog.store import CatalogStore
from histcraft.db import Database
from tests.conftest import make_settings


def catalog_with_points(tmp_path):
    settings = make_settings(tmp_path)
    catalog = CatalogStore(Database(settings.config_target))
    catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:1/"), create=True
    )
    catalog.add_points(
        [
            PointIn(tag="TI-1", source_id="plant", address="ns=2;s=TI-1", unit="°C"),
            PointIn(tag="TI-2", source_id="plant", address="ns=2;s=TI-2"),
        ]
    )
    return catalog


def test_retire_lists_restores_and_purges(tmp_path):
    catalog = catalog_with_points(tmp_path)
    first = {p["tag"]: p for p in catalog.points()}["TI-1"]
    assert catalog.retire_points(["plant:TI-1", "plant:missing"], by="ana") == [first["id"]]
    assert [p["tag"] for p in catalog.points()] == ["TI-2"]
    assert catalog.find("plant:TI-1") is None
    (retired,) = catalog.retired()
    assert retired["signal"] == "plant:TI-1" and retired["unit"] == "°C"
    assert retired["retired_by"] == "ana"
    assert retired["purge_ms"] - retired["retired_ms"] == RETIRED_DAYS * 86_400_000
    assert catalog.retired_ids() == {first["id"]}

    result = catalog.restore_points([first["id"], 999])
    assert result["restored"] == ["plant:TI-1"] and result["refused"][0]["id"] == 999
    back = catalog.find("plant:TI-1")
    assert back["id"] == first["id"] and back["unit"] == "°C" and back["address"] == "ns=2;s=TI-1"
    assert catalog.retired() == []

    catalog.retire_points(["plant:TI-1"])
    assert catalog.purge_retired(older_than_ms=0) == []
    assert catalog.purge_retired([first["id"]]) == [first["id"]]
    assert catalog.retired() == [] and catalog.find("plant:TI-1") is None


def test_a_point_that_took_the_tag_blocks_the_restore(tmp_path):
    catalog = catalog_with_points(tmp_path)
    old = catalog.find("plant:TI-1")
    catalog.retire_points(["plant:TI-1"])
    catalog.add_points([PointIn(tag="TI-1", source_id="plant", address="ns=2;s=TI-1b")])
    refused = catalog.restore_points([old["id"]])["refused"]
    assert refused and "TI-1" in refused[0]["reason"]
    assert catalog.retired_ids() == {old["id"]}


def test_the_admin_routes_retire_restore_and_purge_with_the_typed_count(runtime, fake):
    from tests.conftest import client_for

    admin = client_for(runtime, fake, "admin")
    engineer = client_for(runtime, fake, "engineer")
    runtime.catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:1/"), create=True
    )
    runtime.catalog.add_points([PointIn(tag="TI-9", source_id="plant", address="ns=2;s=TI-9")])
    assert admin.post("/hist/api/points/delete", json={"signals": ["plant:TI-9"]}).json() == {
        "removed": 1,
        "retired": 1,
        "days": RETIRED_DAYS,
    }
    assert engineer.get("/hist/api/points/retired").status_code == 403
    (item,) = admin.get("/hist/api/points/retired").json()["points"]
    assert item["signal"] == "plant:TI-9"
    assert admin.post("/hist/api/points/restore", json={"ids": [item["id"]]}).json()[
        "restored"
    ] == ["plant:TI-9"]
    admin.post("/hist/api/points/delete", json={"signals": ["plant:TI-9"]})
    wrong = admin.post("/hist/api/points/purge", json={"ids": [item["id"]], "confirm": "2"})
    assert wrong.status_code == 422
    done = admin.post("/hist/api/points/purge", json={"ids": [item["id"]], "confirm": "1"})
    assert done.json() == {"purged": 1}
    assert admin.get("/hist/api/points/retired").json()["points"] == []
