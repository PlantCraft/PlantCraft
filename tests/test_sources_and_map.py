"""Added data sources, reads routed to the source that owns a tag, and the plant map file."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from processcraft.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "senha-que-nao-pode-vazar"


@pytest.fixture()
def second_csv(tmp_path) -> Path:
    """A second recorded source with other tags over the same period as the demo file."""

    demo = pd.read_csv(ROOT / "demo" / "data" / "FIC-101.csv", index_col=0, parse_dates=True)
    frame = pd.DataFrame(
        {
            "B201.Vazao": demo["pv"] * 2,
            "B201.SP": demo["sp"] * 2,
            "B201.Saida": demo["op"],
            "B201.Pressao": demo["neighbor_pv"] / 10,
        },
        index=demo.index,
    )
    frame.index.name = "timestamp"
    path = tmp_path / "utilidades.csv"
    frame.to_csv(path)
    return path


@pytest.fixture()
def client(tmp_path, monkeypatch):
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["storage"]["sqlite_path"] = str(tmp_path / "workspace.sqlite3")
    scenario["source"]["path"] = str(ROOT / scenario["source"]["path"])
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario))
    monkeypatch.setenv("PLANTCRAFT_SCENARIO", str(path))
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.setenv("PLANTCRAFT_PREWARM_HISTORY", "false")
    monkeypatch.delenv("PLANTCRAFT_BASIC_AUTH_ENABLED", raising=False)
    with TestClient(create_app()) as test_client:
        yield test_client


def _add_csv(client, path: Path, name: str = "Utilidades") -> dict:
    response = client.post(
        "/api/data/sources", json={"name": name, "type": "csv", "settings": {"path": str(path)}}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_sources_crud_never_returns_a_password(client, tmp_path):
    sources = client.get("/api/data/sources").json()
    assert [item["source_id"] for item in sources] == ["scenario"]
    assert sources[0]["read_only"] is True

    # Testing a connection does not save it.
    bad = client.post("/api/data/sources/test", json={"type": "opcua", "settings": {}}).json()
    assert bad["ok"] is False and "endpoint_url" in bad["message"]
    assert len(client.get("/api/data/sources").json()) == 1

    created = client.post(
        "/api/data/sources",
        json={
            "name": "OPC UA Utilidades",
            "type": "opcua",
            "settings": {
                "endpoint_url": "opc.tcp://10.0.0.15:4840/u/",
                "auth_type": "basic",
                "username": "leitor",
            },
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201, created.text
    source = created.json()
    assert source["source_id"] == "opc-ua-utilidades" and source["has_password"] is True
    assert (
        client.post(
            "/api/data/sources",
            json={"name": "OPC UA Utilidades", "type": "csv", "settings": {"path": "x"}},
        ).status_code
        == 409
    )

    # Editing without a password keeps the stored one.
    updated = client.put(
        f"/api/data/sources/{source['source_id']}",
        json={
            "name": "OPC UA Utilidades",
            "type": "opcua",
            "settings": {**source["settings"], "timeout_seconds": 5},
        },
    ).json()
    assert updated["has_password"] is True and updated["settings"]["timeout_seconds"] == 5
    # A new server or user never gets the saved password: it must be typed again.
    url = f"/api/data/sources/{source['source_id']}"
    elsewhere = {**updated["settings"], "endpoint_url": "opc.tcp://203.0.113.9:4840/"}
    moved = client.put(url, json={"name": "x", "type": "opcua", "settings": elsewhere})
    assert moved.status_code == 422 and "type the password again" in moved.text
    tried = client.post(
        "/api/data/sources/test",
        json={"type": "opcua", "settings": elsewhere, "source_id": source["source_id"]},
    ).json()
    assert tried["ok"] is False and "type the password again" in tried["message"]
    other_user = {**updated["settings"], "username": "outro"}
    assert (
        client.put(url, json={"name": "x", "type": "opcua", "settings": other_user}).status_code
        == 422
    )
    for text in (
        json.dumps(client.get("/api/data/sources").json()),
        json.dumps(updated),
        client.get("/api/map/export.json").text,
    ):
        assert PASSWORD not in text
    # Stored encrypted, not in plain text.
    database = (tmp_path / "workspace.sqlite3").read_bytes()
    assert PASSWORD.encode() not in database
    registry = client.app.state.runtime.platform.sources
    assert registry.data(source["source_id"]).config.secret() == PASSWORD

    assert (
        client.put(
            "/api/data/sources/scenario",
            json={"name": "x", "type": "csv", "settings": {"path": "x"}},
        ).status_code
        == 422
    )
    assert client.delete("/api/data/sources/scenario").status_code == 422
    assert client.delete(f"/api/data/sources/{source['source_id']}").status_code == 200
    assert len(client.get("/api/data/sources").json()) == 1


def test_a_tag_of_an_added_source_is_read_from_it(client, second_csv):
    source = _add_csv(client, second_csv)
    status = client.get(f"/api/data/sources/{source['source_id']}/status").json()
    assert status["ok"] is True

    page = client.get(
        f"/api/data/sources/{source['source_id']}/signals", params={"limit": 2}
    ).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    assert all(item["monitored"] is False and item["assets"] == [] for item in page["items"])

    # Browsing reads straight from the source, before the tag is used.
    browsed = client.get(
        "/api/data/history", params={"tag": "B201.Vazao", "hours": 1, "source": source["source_id"]}
    ).json()
    assert len(browsed["series"]["B201.Vazao"]) > 10

    used = client.post(
        f"/api/data/sources/{source['source_id']}/signals/use",
        json={"tags": ["B201.Vazao", "B201.Pressao"]},
    )
    assert used.status_code == 200
    rt = client.app.state.runtime
    assert rt.platform.sources.source_of("B201.Vazao") == source["source_id"]
    # The platform's reads now mix both sources in one frame.
    end = rt.platform.data_end()
    frame = rt.source.read_range(end - pd.Timedelta(hours=1), end, 30, tags=["pv", "B201.Vazao"])
    assert {"pv", "B201.Vazao"} <= set(frame.columns)
    value = client.get(
        "/api/signals/B201.Vazao/value", params={"agg": "mean", "window": "1h"}
    ).json()
    assert value["value"] == pytest.approx(100, rel=0.05)
    # Apps see the added signal through API v1.
    token = client.post("/api/v1/auth/token").json()["token"]
    listed = client.get("/api/v1/signals", headers={"Authorization": f"Bearer {token}"}).json()
    added = source["source_id"]
    assert {f"{added}:B201.Vazao", f"{added}:B201.Pressao"} <= {item["id"] for item in listed}
    assert {item["source"] for item in listed if item["id"].startswith(f"{added}:")} == {added}
    page = client.get(
        f"/api/data/sources/{source['source_id']}/signals", params={"q": "vazao"}
    ).json()
    assert page["items"][0]["monitored"] is True

    # Bound to an asset with a role.
    asset = client.post("/api/assets", json={"name": "Bomba B-201", "kind": "equipment"}).json()
    bound = client.post(
        f"/api/data/sources/{source['source_id']}/signals/bind",
        json={"tags": ["B201.Pressao"], "asset_id": asset["asset_id"], "role": "pressao"},
    )
    assert bound.status_code == 200
    signals = client.get(f"/api/assets/{asset['asset_id']}/signals").json()
    assert signals[0]["signal_id"] == "B201.Pressao" and signals[0]["role"] == "pressao"
    assert signals[0]["source_id"] == added
    page = client.get(
        f"/api/data/sources/{source['source_id']}/signals", params={"q": "pressao"}
    ).json()
    assert page["items"][0]["assets"][0]["asset_id"] == asset["asset_id"]


def _map(second_csv: Path) -> dict:
    return {
        "format": "processcraft-map",
        "sources": [
            {
                "source_id": "utilidades",
                "name": "Utilidades",
                "type": "csv",
                "path": str(second_csv),
            }
        ],
        "assets": [
            {"asset_id": "U-200", "name": "Unidade 200", "kind": "unit"},
            {"asset_id": "B-201", "name": "Bomba B-201", "kind": "equipment", "parent_id": "U-200"},
        ],
        "signals": [
            {
                "tag": "B201.Vazao",
                "source_id": "utilidades",
                "name": "Vazão",
                "unit": "m³/h",
                "asset_id": "B-201",
                "role": "vazao",
            },
            {"tag": "B201.SP", "source_id": "utilidades", "name": "SP de vazão", "unit": "m³/h"},
            {"tag": "B201.Saida", "source_id": "utilidades", "name": "Saída", "unit": "%"},
        ],
        "loops": [
            {
                "loop_id": "FIC-2001",
                "name": "Vazão da bomba B-201",
                "asset_id": "B-201",
                "area": "Resfriamento",
                "pv": "B201.Vazao",
                "sp": "B201.SP",
                "op": "B201.Saida",
                "protocol": "general",
                "criticality": "high",
            }
        ],
    }


def _preview(client, payload: dict, name: str = "mapa.json", **params) -> dict:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response = client.post("/api/map/preview", params={"filename": name, **params}, content=content)
    assert response.status_code == 200, response.text
    return response.json()


def _apply(client, payload, name: str = "mapa.json", **params) -> dict:
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response = client.post("/api/map/apply", params={"filename": name, **params}, content=content)
    assert response.status_code == 200, response.text
    return response.json()


def _counts(report: dict) -> dict:
    return {
        item["name"]: {key: item[key] for key in ("create", "update", "unchanged", "remove")}
        for item in report["sections"]
    }


def test_import_reports_errors_per_sheet_and_line(client, second_csv):
    payload = _map(second_csv)
    payload["assets"].append({"asset_id": "X 1", "name": "Com espaço", "kind": "equipment"})
    payload["assets"].append({"asset_id": "T-1", "name": "Tanque", "kind": "tanque"})
    payload["assets"].append(
        {"asset_id": "T-2", "name": "Tanque 2", "kind": "equipment", "parent_id": "NAO-EXISTE"}
    )
    payload["signals"].append({"tag": "B201.Inexistente", "source_id": "utilidades"})
    payload["signals"].append({"tag": "Z.1", "source_id": "fonte-fantasma"})
    payload["loops"].append({"loop_id": "LIC-1", "name": "Nível"})
    report = _preview(client, payload)
    assert report["can_apply"] is False
    found = {(item["sheet"], item["line"], item["level"]) for item in report["issues"]}
    assert ("assets", 3, "error") in found  # space in asset_id
    assert ("assets", 4, "error") in found  # unknown kind
    assert ("assets", 5, "warning") in found  # unknown parent
    assert ("signals", 5, "error") in found  # unknown source
    assert ("loops", 2, "error") in found  # no pv
    assert any(
        item["sheet"] == "signals"
        and item["level"] == "warning"
        and "B201.Inexistente" in item["message"]
        for item in report["issues"]
    )
    # Nothing is applied while there are errors.
    result = _apply(client, payload)
    assert result["applied"] is False
    assert client.app.state.runtime.workspace.assets.get("U-200") is None

    broken = client.post("/api/map/preview", params={"filename": "mapa.json"}, content=b"{nope")
    assert broken.status_code == 422 and "JSON" in broken.json()["detail"]
    assert (
        client.post("/api/map/preview", params={"filename": "mapa.txt"}, content=b"x").status_code
        == 422
    )


def test_import_is_idempotent_and_loops_become_loop_assets(client, second_csv):
    payload = _map(second_csv)
    preview = _preview(client, payload)
    assert preview["can_apply"] is True, preview["issues"]
    assert _counts(preview)["loops"]["create"] == 1
    # Analysis settings stay with the app that analyses loops; the preview says so.
    # Criticality is an attribute of the loop's record now, so it is not in that warning.
    assert any(
        item["sheet"] == "loops"
        and "protocol" in item["message"]
        and "criticality" not in item["message"]
        and "PlantCraft Analytics" in item["message"]
        for item in preview["issues"]
    )
    first = _apply(client, payload)
    assert first["applied"] is True
    counts = _counts(first)
    assert (
        counts["sources"]["create"] == 1
        and counts["assets"]["create"] == 2
        and counts["signals"]["create"] == 3
    )

    rt = client.app.state.runtime
    # The loop is a loop asset placed on its equipment, with its signals by role:
    # what CPMCraft reads through API v1.
    assert rt.workspace.assets.get("FIC-2001")["kind"] == "loop"
    assert rt.workspace.assets.get("FIC-2001")["parent_id"] == "B-201"
    assert rt.workspace.assets.get("B-201")["parent_id"] == "U-200"
    token = client.post("/api/v1/auth/token").json()["token"]
    loop = client.get(
        "/api/v1/assets/FIC-2001", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert loop["kind"] == "loop"
    # Bare tags in the map bind; API v1 names each with its source (<source id>:<tag>).
    assert loop["signals"] == {
        "pv": "utilidades:B201.Vazao",
        "sp": "utilidades:B201.SP",
        "op": "utilidades:B201.Saida",
    }
    assert loop["attributes"]["criticality"] == "high" and loop["type_path"] == ["loop"]

    again = _apply(client, payload)
    assert all(
        item["create"] == item["update"] == item["remove"] == 0 for item in again["sections"]
    ), again["sections"]
    assert again["changes"] == []

    # Nothing outside the file is removed unless asked.
    smaller = {**payload, "loops": [], "signals": payload["signals"][:1]}
    kept = _apply(client, smaller)
    assert all(item["remove"] == 0 for item in kept["sections"])
    assert rt.workspace.assets.get("FIC-2001") is not None
    pruned = _preview(client, smaller, prune="true")
    assert _counts(pruned)["loops"]["remove"] == 1
    assert _counts(pruned)["signals"]["remove"] == 2
    _apply(client, smaller, prune="true")
    assert rt.workspace.assets.get("FIC-2001") is None
    # The scenario's own loop is never removed by a map.
    assert rt.workspace.assets.get("FIC-101")["kind"] == "loop"


def test_export_reimports_without_changes_as_json_and_excel(client, second_csv):
    _apply(client, _map(second_csv))
    exported = client.get("/api/map/export.json")
    assert exported.status_code == 200
    payload = exported.json()
    assert {"sources", "assets", "signals", "loops"} <= set(payload)
    assert payload["sources"][0]["source_id"] == "scenario"
    assert {row["loop_id"] for row in payload["loops"]} == {"FIC-101", "FIC-2001"}
    report = _preview(client, payload)
    assert report["can_apply"] and report["changes"] == [], report["changes"]

    workbook = client.get("/api/map/export.xlsx")
    assert workbook.headers["content-type"].startswith("application/vnd.openxmlformats")
    sheets = pd.read_excel(io.BytesIO(workbook.content), sheet_name=None)
    assert {"Readme", "sources", "assets", "signals", "loops"} <= set(sheets)
    report = _preview(client, workbook.content, name="mapa.xlsx")
    assert report["can_apply"] and report["changes"] == [], report["changes"]


def test_templates_download_and_a_csv_holds_one_sheet(client):
    template = client.get("/api/map/template.json").json()
    assert template["loops"][0]["loop_id"] == "FIC-2001"
    sheets = pd.read_excel(
        io.BytesIO(client.get("/api/map/template.xlsx").content), sheet_name=None
    )
    readme = sheets["Readme"].to_string()
    assert "password_env" in readme and "secondary" in readme
    names = [item["name"] for item in client.get("/api/map/format").json()]
    assert (
        names.index("assets") < names.index("pump") < names.index("signals") < names.index("loops")
    )
    assert names[-1] == "relations" and "site" not in names and "loop" not in names

    csv = "asset_id,name,kind,parent_id\nU-300,Unidade 300,unit,\nE-1,Trocador,equipment,U-300\n"
    report = _preview(client, csv.encode(), name="ativos.csv")
    assert _counts(report)["assets"]["create"] == 2
    assert (
        client.post(
            "/api/map/preview", params={"filename": "outra.csv"}, content=csv.encode()
        ).status_code
        == 422
    )


def test_asset_attributes_are_stored_and_unknown_ones_reported(client):
    payload = {
        "assets": [
            {
                "asset_id": "M-1",
                "name": "Motor",
                "kind": "equipment",
                "attributes": {"potencia_kw": 75, "manufacturer": "ACME"},
            }
        ]
    }
    report = _preview(client, payload)
    assert report["can_apply"] is True
    assert any(
        "potencia_kw" in item["message"] and item["level"] == "warning" for item in report["issues"]
    )
    _apply(client, payload)
    store = client.app.state.runtime.workspace.assets
    assert store.attributes("M-1") == {"manufacturer": "ACME"}
    csv = "asset_id,name,kind,fabricante,model\nM-2,Motor 2,equipment,WEG,W22\n"
    report = _preview(client, csv.encode(), name="assets.csv")
    assert any("fabricante" in item["message"] for item in report["issues"])
    bad = {"assets": [{**payload["assets"][0], "attributes": {"criticality": "extreme"}}]}
    report = _preview(client, bad)
    assert report["can_apply"] is False
    assert any("criticality" in item["message"] for item in report["issues"])


def test_the_plant_map_prompt_carries_the_format_and_no_source(client, second_csv):
    """Copy as prompt on the import page: format, example and types; never a source or path."""

    _add_csv(client, second_csv, name="Utilidades B")
    answer = client.get("/api/prompts/plant-map").json()
    text = answer["text"]
    assert answer["title"] == "Plant map import" and answer["omitted"] == []
    assert '"format": "processcraft-map"' in text
    assert "## Question" in text and "Build the plant map" in text
    labels = [part["label"] for part in answer["parts"]]
    assert labels == [
        "File format: every section and column",
        "Example file",
        "Asset types of this installation",
    ]
    assert '"loops"' in text and '"signals"' in text and '"kind": "equipment"' in text
    for leak in ("Utilidades B", str(second_csv), "endpoint_url", "password_env", PASSWORD):
        assert leak not in text, leak
    review = client.get("/api/prompts/plant-map", params={"question": "review"}).json()
    assert "Review this plant map file" in review["text"]
    # A question outside the presets falls back to the default one.
    other = client.get("/api/prompts/plant-map", params={"question": "anything"}).json()
    assert "Build the plant map" in other["text"]
