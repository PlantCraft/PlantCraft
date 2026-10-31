"""The point list as CSV: export, edit, import back (preview first, then apply)."""

from __future__ import annotations

import csv
import io

from histcraft.catalog.models import PointIn, SourceIn


def setup(runtime) -> None:
    runtime.catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:4840/"), create=True
    )
    runtime.catalog.add_points(
        [
            PointIn(tag="TI-100.PV", source_id="plant", address="ns=2;s=TI-100.PV", unit="degC"),
            PointIn(
                tag="FIC-101.PV", source_id="plant", address="ns=2;s=FIC-101.PV", deviation=0.5
            ),
        ]
    )


def rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_an_exported_list_imported_again_changes_nothing(client, runtime):
    setup(runtime)
    exported = client.get("/hist/api/points/export")
    assert exported.status_code == 200
    assert 'filename="historian-points-all.csv"' in exported.headers["content-disposition"]
    listed = {row["tag"]: row for row in rows(exported.text)}
    # Inherited settings are empty cells; a point's own value is written.
    assert listed["TI-100.PV"]["deviation"] == "" and listed["FIC-101.PV"]["deviation"] == "0.5"
    preview = client.post("/hist/api/points/import", content=exported.text).json()
    assert preview["add"] == [] and preview["update"] == [] and preview["errors"] == []
    assert sorted(preview["unchanged"]) == ["plant:FIC-101.PV", "plant:TI-100.PV"]


def test_import_previews_then_adds_and_updates(client, runtime):
    setup(runtime)
    text = (
        "source_id;tag;address;unit;retention_days;deviation\n"
        "plant;TI-100.PV;;K;30;\n"
        'plant;PI-200.PV;"ns=2;s=PI-200.PV";bar;;0,2\n'
    )
    preview = client.post("/hist/api/points/import", content=text).json()
    assert preview["errors"] == [], preview
    assert preview["update"] == ["plant:TI-100.PV"] and preview["add"] == ["plant:PI-200.PV"]
    assert runtime.catalog.find("plant:PI-200.PV") is None  # a preview changes nothing
    done = client.post("/hist/api/points/import?apply=true", content=text).json()
    assert done["added"] == ["plant:PI-200.PV"] and done["updated"] == ["plant:TI-100.PV"]
    updated = runtime.catalog.point("plant:TI-100.PV")
    assert (updated["unit"], updated["own"]["retention_days"]) == ("K", 30)
    added = runtime.catalog.point("plant:PI-200.PV")
    assert (added["address"], added["deviation"]) == ("ns=2;s=PI-200.PV", 0.2)


def test_import_reports_each_bad_line_and_applies_nothing(client, runtime):
    setup(runtime)
    text = (
        "source_id,tag,address,retention_days,enabled\n"
        "nowhere,X,,,\n"
        "plant,TI-100.PV,ns=2;s=OTHER,,\n"
        "plant,A,,many,\n"
        "plant,B,,,maybe\n"
        "plant,C,,,\n"
        "plant,C,,,\n"
    )
    preview = client.post("/hist/api/points/import", content=text).json()
    assert [error["line"] for error in preview["errors"]] == [2, 3, 4, 5, 7]
    refused = client.post("/hist/api/points/import?apply=true", content=text)
    assert refused.status_code == 422
    assert runtime.catalog.find("plant:C") is None


def test_a_file_without_source_or_tag_columns_is_refused(client, runtime):
    preview = client.post("/hist/api/points/import", content="name,unit\nx,y\n").json()
    assert preview["errors"][0]["line"] == 1 and "source_id" in preview["errors"][0]["message"]


def test_an_odd_source_id_gives_a_safe_file_name(client):
    # API fuzzing, 2026-10-31 (D17): control and non-latin characters in the header were a 500.
    answer = client.get("/hist/api/points/export", params={"source_id": "\x84\x16羞\x16+\x02"})
    assert answer.status_code == 200
    assert 'filename="historian-points-' in answer.headers["content-disposition"]
