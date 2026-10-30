"""The HTTP API: access per route, the data API in v1 shapes, and the pages' routes."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest
from plantcraft_sdk import apptest
from plantcraft_sdk.contract import series_to_pandas

from histcraft.archive.query import to_ms
from histcraft.catalog.models import PointIn, SourceIn
from histcraft.sources.cache import LATE_MS
from tests.conftest import client_for
from tests.test_query import T0
from tests.test_source_cache import MIN, Historian

MS = to_ms(T0)


@pytest.fixture
def loaded(runtime):
    runtime.catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:4840/"), create=True
    )
    runtime.catalog.add_points(
        [
            PointIn(
                tag="TI-100.PV",
                source_id="plant",
                address="ns=2;s=TI-100.PV",
                unit="degC",
                low=0,
                high=200,
            ),
            PointIn(
                tag="FIC-101.MODE", source_id="plant", address="ns=2;s=FIC-101.MODE", kind="text"
            ),
            PointIn(tag="Area/1/TT", source_id="plant", address="ns=2;s=Area/1/TT"),
        ]
    )
    points = {p["tag"]: p["id"] for p in runtime.catalog.points()}
    runtime.archive.append(
        {
            points["TI-100.PV"]: ("number", [(MS + i * 10_000, float(i)) for i in range(361)]),
            points["FIC-101.MODE"]: ("text", [(MS, "AUTO"), (MS + 1_800_000, "MAN")]),
            points["Area/1/TT"]: ("number", [(MS, 1.0), (MS + 3_600_000, 1.0)]),
        }
    )
    return runtime


def test_health_and_sign_in(client, fake, runtime):
    assert client.get("/hist/healthz").json()["status"] == "ok"
    anonymous = client_for(runtime, fake, None)
    response = anonymous.get("/hist/api/me")
    assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
    assert client_for(runtime, fake, "outsider").get("/hist/api/me").status_code == 403
    me = client.get("/hist/api/me").json()
    assert me["is_admin"] and me["can_edit"]


def test_me_role_shows_an_admin_as_admin(runtime, fake):
    # An admin's app access is "editor" in the token; the user menu shows the level.
    with client_for(runtime, fake, "admin") as admin:
        assert admin.get("/hist/api/me").json()["role"] == "admin"
    with client_for(runtime, fake, "engineer") as engineer:
        assert engineer.get("/hist/api/me").json()["role"] == "editor"


@pytest.fixture
def pc(runtime, fake):
    """PlantCraft calling the data routes with the token it signs for itself."""

    token = fake.token(
        "app:processcraft", aud="histcraft", level="viewer", apps={"histcraft": "editor"}
    )
    client = client_for(runtime, fake, None)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


DATA = "/hist/api/v1/data"


def test_data_signals_in_v1_signal_shape(pc, loaded):
    by_id = {s["id"]: s for s in pc.get(f"{DATA}/signals").json()}
    assert by_id["plant:TI-100.PV"] == {
        "id": "plant:TI-100.PV",
        "name": "TI-100.PV",
        "source": "plant",
        "unit": "degC",
        "description": "",
        "low": 0.0,
        "high": 200.0,
        "kind": "number",
        "mode": "archive",
        "source_kind": "opcua",
        "app": None,
        "subject": None,
        "result": None,
        "retention_days": 400,
        "managed_by": None,
    }
    assert pc.get(f"{DATA}/signals/plant%3AArea%2F1%2FTT").json()["id"] == "plant:Area/1/TT"
    assert pc.get(f"{DATA}/signals/plant:nope").status_code == 404
    # a bare tag finds the one signal that has it
    assert pc.get(f"{DATA}/signals/TI-100.PV").json()["id"] == "plant:TI-100.PV"
    assert pc.get(f"{DATA}/signals/TI-100.PV/value").json()["signal"] == "TI-100.PV"
    assert [s["id"] for s in pc.get(f"{DATA}/signals", params={"q": "mode"}).json()] == [
        "plant:FIC-101.MODE"
    ]


def test_series_recorded_and_on_a_grid(pc, loaded):
    start, end = "2026-10-19T00:00:00Z", "2026-10-19T01:00:00Z"
    url = f"{DATA}/signals/plant:TI-100.PV/series"
    recorded = pc.get(url, params={"start": start, "end": end}).json()
    assert recorded["kind"] == "number" and len(recorded["t"]) == 361
    grid = pc.get(url, params={"start": start, "end": end, "step": 600}).json()
    series = series_to_pandas(grid)
    assert len(series) == 6 and series.iloc[0] == pytest.approx(30.0)
    text = pc.get(
        f"{DATA}/signals/plant:FIC-101.MODE/series",
        params={"start": start, "end": end, "step": 900},
    ).json()
    # a mode is recorded on change: its last label holds to the end (plantcraft-sdk 0.8.3)
    assert text["kind"] == "text" and text["v"] == ["AUTO", "AUTO", "MAN", "MAN"]
    slash = pc.get(
        f"{DATA}/signals/plant:Area%2F1%2FTT/series", params={"start": start, "end": end}
    ).json()
    assert slash["signal"] == "plant:Area/1/TT" and slash["v"] == [1.0, 1.0]


def test_series_batch_answers_known_and_reports_the_rest(pc, loaded):
    body = {
        "signals": ["plant:TI-100.PV", "missing", "plant:TI-100.PV", "plant:FIC-101.MODE"],
        "start": "2026-10-19T00:00:00Z",
        "end": "2026-10-19T01:00:00Z",
        "step": 60,
    }
    answer = pc.post(f"{DATA}/series", json=body).json()
    assert [s["signal"] for s in answer["series"]] == ["plant:TI-100.PV", "plant:FIC-101.MODE"]
    assert answer["errors"] == [
        {"signal": "missing", "status": 404, "detail": "Signal missing not found."}
    ]
    assert pc.post(f"{DATA}/series", json={"signals": []}).status_code == 422
    assert pc.post(f"{DATA}/series", json={"signals": [1]}).status_code == 422


def test_value(pc, loaded):
    url = f"{DATA}/signals/plant:FIC-101.MODE/value"
    assert pc.get(url, params={"agg": "last", "window": "366d"}).json()["value"] == "MAN"
    assert pc.get(url, params={"agg": "mean"}).status_code == 422


def test_only_processcraft_uses_the_data_routes(runtime, fake, pc, loaded, client):
    assert pc.get(f"{DATA}/signals").status_code == 200
    # people (even admins) use the pages; other apps go through PlantCraft
    assert client.get(f"{DATA}/signals").status_code == 403
    other = client_for(runtime, fake, None)
    other.headers["Authorization"] = (
        f"Bearer {fake.token('app:cpmcraft', aud='histcraft', apps={'histcraft': 'editor'})}"
    )
    assert other.get(f"{DATA}/signals").status_code == 403
    # PlantCraft's token does not open the pages' routes
    point = {"points": [{"tag": "x", "source_id": "plant", "address": "ns=2;s=x"}]}
    assert pc.post("/hist/api/points", json=point).status_code == 403


def test_apps_write_derived_series(pc, loaded):
    body = {
        "series": [
            {
                "app": "cpmcraft",
                "signal": "app-cpmcraft:FIC-101.health",
                "name": "FIC-101 health",
                "unit": "%",
                "subject": "asset:fic-101",
                "result": "loop_health",
                "t": ["2026-10-19T00:00:00Z", "2026-10-19T00:10:00Z"],
                "v": [93.5, None],
            },
            {
                "app": "cpmcraft",
                "signal": "app-datacraft:x",
                "t": ["2026-10-19T00:00:00Z"],
                "v": [1],
            },
            {"app": "cpmcraft", "signal": "app-cpmcraft:bad", "t": ["yesterday"], "v": [1]},
        ]
    }
    answer = pc.post(f"{DATA}/derived", json=body).json()
    assert answer["written"] == 2
    assert [(e["signal"], e["status"]) for e in answer["errors"]] == [
        ("app-datacraft:x", 403),
        ("app-cpmcraft:bad", 422),
    ]
    found = pc.get(f"{DATA}/signals", params={"app": "cpmcraft", "subject": "asset:fic-101"}).json()
    assert [(s["id"], s["app"], s["result"], s["unit"]) for s in found] == [
        ("app-cpmcraft:FIC-101.health", "cpmcraft", "loop_health", "%")
    ]
    assert pc.get(f"{DATA}/signals", params={"result": "other"}).json() == []
    series = pc.get(
        f"{DATA}/signals/app-cpmcraft:FIC-101.health/series",
        params={"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T00:20:00Z"},
    ).json()
    assert series["v"][0] == 93.5
    # a second write replaces values at the same times
    body["series"] = [{**body["series"][0], "v": [50.0, 60.0]}]
    assert pc.post(f"{DATA}/derived", json=body).json() == {"written": 2, "errors": []}
    series = pc.get(
        f"{DATA}/signals/app-cpmcraft:FIC-101.health/series",
        params={"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T00:20:00Z"},
    ).json()
    assert series["v"][:2] == [50.0, 60.0]
    sources = {s["id"]: s for s in pc.get(f"{DATA}/sources").json()}
    assert sources["app-cpmcraft"]["kind"] == "derived"


def test_processcraft_writes_the_suite_health(pc, client, loaded, runtime):
    body = {
        "series": [
            {
                "signal": "system:linkcraft.up",
                "name": "Link up",
                "t": ["2026-10-19T00:00:00Z", "2026-10-19T00:01:00Z"],
                "v": [1, 0],
            },
            {"signal": "app-cpmcraft:x", "t": ["2026-10-19T00:00:00Z"], "v": [1]},
            {"signal": "plant:TI-100.PV", "t": ["2026-10-19T00:00:00Z"], "v": [1]},
        ]
    }
    answer = pc.post(f"{DATA}/system", json=body).json()
    assert answer["written"] == 2
    assert [(e["signal"], e["status"]) for e in answer["errors"]] == [
        ("app-cpmcraft:x", 422),
        ("plant:TI-100.PV", 422),
    ]
    sources = {s["id"]: s for s in pc.get(f"{DATA}/sources").json()}
    assert sources["system"]["kind"] == "system" and sources["system"]["name"] == "System"
    assert sources["system"]["retention_days"] == 90
    found = pc.get(f"{DATA}/signals/system:linkcraft.up").json()
    assert found["source_kind"] == "system" and found["app"] is None
    series = pc.get(
        f"{DATA}/signals/system:linkcraft.up/series",
        params={"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T00:02:00Z"},
    ).json()
    assert series["v"][:2] == [1.0, 0.0]
    # Only PlantCraft writes it; nobody adds, edits or collects it as a plant source.
    assert client.post(f"{DATA}/system", json=body).status_code == 403
    reserved = {"id": "system", "name": "Mine", "endpoint": "opc.tcp://127.0.0.1:4840/"}
    assert pc.post(f"{DATA}/sources", json=reserved).status_code == 422
    assert client.post("/hist/api/sources", json=reserved).status_code == 422
    as_kind = {"id": "other", "name": "x", "kind": "system"}
    assert client.post("/hist/api/sources", json=as_kind).status_code == 422
    assert (
        pc.patch(f"{DATA}/signals/system:linkcraft.up", json={"enabled": False}).status_code == 422
    )


def test_a_plant_source_named_system_keeps_its_data(pc, runtime):
    # Before the id was reserved: the health is refused, the plant source untouched.
    with runtime.catalog._connect() as connection:
        connection.execute(
            "INSERT INTO sources (id, name, kind, endpoint, mode, options, enabled, created,"
            " updated) VALUES ('system', 'Old', 'opcua', 'opc.tcp://x/', '', '{}', 1, 0, 0)"
        )
    body = {"series": [{"signal": "system:a.up", "t": ["2026-10-19T00:00:00Z"], "v": [1]}]}
    answer = pc.post(f"{DATA}/system", json=body).json()
    assert answer["written"] == 0 and answer["errors"][0]["status"] == 403


def test_processcraft_manages_sources(pc, loaded, runtime):
    source = {
        "id": "pi",
        "name": "PI",
        "kind": "pi_web_api",
        "endpoint": "https://pi.example/piwebapi",
        "username": "svc",
        "password": "s3cret",
        "options": {"server": "PISRV", "auth_type": "basic"},
        "signals": ["FIC101.PV", {"tag": "FIC101.MODE", "kind": "text"}],
    }
    created = pc.post(f"{DATA}/sources", json=source)
    assert created.status_code == 201
    answer = created.json()
    assert answer["has_password"] and answer["mode"] == "source"
    assert answer["signals_added"]["added"] == ["pi:FIC101.PV", "pi:FIC101.MODE"]
    assert "s3cret" not in created.text and "s3cret" not in str(runtime.catalog.secret("pi"))
    assert runtime.vault.decrypt(runtime.catalog.secret("pi")) == "s3cret"
    assert pc.post(f"{DATA}/sources", json=source).status_code == 409
    added = pc.post(f"{DATA}/sources/pi/signals", json={"signals": ["PIC102.PV"]}).json()
    assert added["added"] == ["pi:PIC102.PV"]
    update = {**source, "name": "PI server", "password": None}
    del update["signals"]
    assert pc.put(f"{DATA}/sources/pi", json=update).json()["name"] == "PI server"
    assert runtime.vault.decrypt(runtime.catalog.secret("pi")) == "s3cret"  # kept
    # A new server or user never gets the stored password: it must be typed again.
    for moved in ({"endpoint": "https://203.0.113.9/piwebapi"}, {"username": "outro"}):
        refused = pc.put(f"{DATA}/sources/pi", json={**update, **moved})
        assert refused.status_code == 422 and "type the password again" in refused.text
        tested = pc.post(f"{DATA}/sources/test", json={**update, **moved})
        assert tested.status_code == 422 and "type the password again" in tested.text
    assert runtime.catalog.source("pi")["endpoint"] == source["endpoint"]
    derived = {"id": "app-x", "name": "x", "kind": "derived"}
    assert pc.post(f"{DATA}/sources", json=derived).status_code == 422
    assert pc.delete(f"{DATA}/sources/pi").status_code == 409  # still has signals


def test_processcraft_hands_its_sources_over(pc, runtime):
    body = {
        "sources": [
            {
                "id": "pi",
                "name": "PI",
                "type": "pi_web_api",
                "base_url": "https://pi.example/piwebapi",
                "server": "PISRV",
                "auth_type": "basic",
                "username": "svc",
                "password": "s3cret",
                "tags": ["FIC101.PV"],
            },
            {"id": "x", "type": "modbus"},
        ]
    }
    answer = pc.post(f"{DATA}/sources/import", json=body).json()
    assert answer["imported"] == ["pi"] and answer["skipped"][0]["id"] == "x"
    assert [s["id"] for s in pc.get(f"{DATA}/signals").json()] == ["pi:FIC101.PV"]
    # importing again updates, and keeps the signal ids
    assert pc.post(f"{DATA}/sources/import", json=body).json()["imported"] == ["pi"]


def test_access_levels_per_route(runtime, fake, loaded):
    viewer = client_for(runtime, fake, "operator")
    engineer = client_for(runtime, fake, "engineer")
    admin = client_for(runtime, fake, "admin")
    point = {"points": [{"tag": "NEW", "source_id": "plant", "address": "ns=2;s=NEW"}]}
    assert viewer.get("/hist/api/points").status_code == 200
    assert viewer.post("/hist/api/points", json=point).status_code == 403
    assert engineer.post("/hist/api/points", json=point).status_code == 201
    assert (
        engineer.patch("/hist/api/points/plant:NEW", json={"deviation": 0.5}).json()["deviation"]
        == 0.5
    )
    gone = {"signals": ["plant:NEW"]}
    assert engineer.post("/hist/api/points/delete", json=gone).status_code == 403
    assert admin.post("/hist/api/points/delete", json=gone).json()["retired"] == 1
    source = {"id": "two", "name": "Two", "endpoint": "opc.tcp://10.0.0.1:4840/"}
    assert engineer.post("/hist/api/sources", json=source).status_code == 403
    assert admin.post("/hist/api/sources", json=source).status_code == 201
    assert admin.post("/hist/api/sources", json=source).status_code == 409
    assert engineer.put("/hist/api/settings", json={"retention_days": 30}).status_code == 403
    assert (
        admin.put("/hist/api/settings", json={"retention_days": 30}).json()["retention_days"] == 30
    )
    assert engineer.post("/hist/api/sources/plant/backfill", json={}).status_code == 403
    queued = admin.post("/hist/api/sources/plant/backfill", json={"hours": 48})
    assert queued.status_code == 202
    request = runtime.catalog.request(queued.json()["request"])
    assert request["kind"] == "backfill" and request["detail"] == {"hours": 48}
    assert admin.post("/hist/api/sources/plant/backfill", json={"hours": 0}).status_code == 422
    assert admin.delete("/hist/api/sources/plant").status_code == 409  # still has points
    assert admin.delete("/hist/api/sources/two").status_code == 204
    # every change a person makes is in PlantCraft's audit log
    actions = [row["action"] for row in fake.audit_log]
    assert "histcraft.points.add" in actions and "histcraft.source.add" in actions


def test_points_carry_status_and_storage(client, loaded):
    points = {p["tag"]: p for p in client.get("/hist/api/points").json()}
    assert points["TI-100.PV"]["stored_values"] == 361
    assert points["TI-100.PV"]["status"] == "waiting"
    overview = client.get("/hist/api/overview").json()
    assert overview["points"] == 3 and overview["archive"]["values"] == 365
    assert overview["collector"]["running"] is False


def test_browse_request_waits_for_the_collector(client, loaded):
    accepted = client.post("/hist/api/sources/plant/browse", json={})
    assert accepted.status_code == 202
    request_id = accepted.json()["request"]
    assert client.get(f"/hist/api/requests/{request_id}").json()["status"] == "pending"
    loaded.archive.finish_request(request_id, "ok", {"variables": []})
    assert client.get(f"/hist/api/requests/{request_id}").json()["status"] == "ok"
    assert client.post("/hist/api/sources/nope/test").status_code == 404


def test_invalid_input_is_rejected_clearly(client, loaded):
    bad_source = {"id": "Bad Id!", "name": "x", "endpoint": "http://x"}
    response = client.post("/hist/api/sources", json=bad_source)
    assert response.status_code == 422
    bad_secret = {"id": "s", "name": "x", "endpoint": "opc.tcp://x", "password_env": "PATH"}
    assert client.post("/hist/api/sources", json=bad_secret).status_code == 422
    assert client.put("/hist/api/settings", json={"unknown": 1}).status_code == 422
    assert client.put("/hist/api/settings", json={"retention_days": -1}).status_code == 422


def test_csv_sources_are_archived_and_browsed_from_their_files(pc, loaded, tmp_path):
    # a CSV source is a file (or folder) another application keeps writing;
    # the collector archives its rows, so its points are in mode archive.
    path = tmp_path / "lab.csv"
    path.write_text(
        "time,DENSITY,GRADE\n"
        "2026-10-19 00:00:00,0.91,A\n"
        "2026-10-19 00:30:00,0.93,B\n"
        "2026-10-19 01:00:00,0.95,B\n",
        encoding="utf-8",
    )
    source = {
        "id": "lab",
        "name": "Lab",
        "kind": "csv",
        "endpoint": str(path),
        "signals": ["DENSITY", {"tag": "GRADE", "kind": "text"}],
    }
    assert pc.post(f"{DATA}/sources", json=source).json()["mode"] == "archive"
    assert loaded.catalog.point("lab:DENSITY")["mode"] == "archive"
    tested = pc.post(f"{DATA}/sources/lab/test").json()["detail"]
    assert (tested["files"], tested["tags"], tested["shape"]) == (1, 2, "wide")
    browsed = pc.post(f"{DATA}/sources/lab/browse", json={}).json()
    assert {v["tag"]: v["kind"] for v in browsed["variables"]} == {
        "DENSITY": "number",
        "GRADE": "text",
    }
    assert pc.post(f"{DATA}/sources/nope/test").status_code == 404
    # settings tested before they are saved
    unsaved = {"id": "lab2", "name": "Lab 2", "kind": "csv", "endpoint": str(path)}
    assert pc.post(f"{DATA}/sources/test", json=unsaved).json()["detail"]["tags"] == 2
    missing = {**unsaved, "endpoint": str(tmp_path / "none.csv")}
    assert pc.post(f"{DATA}/sources/test", json=missing).status_code == 502
    pattern = {**unsaved, "endpoint": str(tmp_path / "*.csv")}
    assert pc.post(f"{DATA}/sources/test", json=pattern).json()["detail"]["files"] == 1
    path.unlink()
    assert pc.post(f"{DATA}/sources/lab/test").status_code == 502


def test_processcraft_stops_using_a_signal(pc, loaded):
    url = f"{DATA}/signals/plant:FIC-101.MODE"
    assert pc.patch(url, json={"enabled": False}).status_code == 200
    assert loaded.catalog.point("plant:FIC-101.MODE")["enabled"] is False
    assert pc.delete(url).status_code == 204
    assert pc.get(url).status_code == 404
    assert pc.delete(url).status_code == 404


def test_every_variable_of_a_source_with_defaults(pc, loaded, tmp_path):
    path = tmp_path / "lab.csv"
    path.write_text("time,DENSITY,GRADE\n2026-10-19 00:00:00,0.91,A\n", encoding="utf-8")
    source = {"id": "lab", "name": "Lab", "kind": "csv", "endpoint": str(path)}
    assert pc.post(f"{DATA}/sources", json=source).status_code == 201
    assert pc.post(f"{DATA}/sources/lab/signals", json={}).status_code == 422
    added = pc.post(f"{DATA}/sources/lab/signals", json={"all": True, "deviation": 0.01}).json()
    assert sorted(added["added"]) == ["lab:DENSITY", "lab:GRADE"]
    density = loaded.catalog.point("lab:DENSITY")
    assert density["deviation"] == 0.01 and density["mode"] == "archive"
    assert loaded.catalog.point("lab:GRADE")["kind"] == "text"
    again = pc.post(f"{DATA}/sources/lab/signals", json={"all": True}).json()
    assert again["added"] == [] and len(again["skipped"]) == 2


def test_signals_given_by_tag_take_their_kind_from_the_source(pc, loaded, tmp_path):
    path = tmp_path / "lab.csv"
    path.write_text("time,DENSITY,GRADE\n2026-10-19 00:00:00,0.91,A\n", encoding="utf-8")
    source = {"id": "lab", "name": "Lab", "kind": "csv", "endpoint": str(path)}
    assert pc.post(f"{DATA}/sources", json=source).status_code == 201
    added = pc.post(f"{DATA}/sources/lab/signals", json={"signals": ["GRADE", "DENSITY"]})
    assert sorted(added.json()["added"]) == ["lab:DENSITY", "lab:GRADE"]
    assert loaded.catalog.point("lab:GRADE")["kind"] == "text"
    assert loaded.catalog.point("lab:DENSITY")["kind"] == "number"


def test_a_batch_reads_the_source_once_before_the_archive_began(pc, loaded):
    loaded.catalog.add_points(
        [
            PointIn(tag="PV", source_id="plant", address="ns=2;s=PV", mode="both"),
            PointIn(tag="MODE", source_id="plant", address="ns=2;s=MODE", kind="text", mode="both"),
        ]
    )
    points = {p["tag"]: p["id"] for p in loaded.catalog.points()}
    # Archived since 00:45 only: before that, the source answers.
    loaded.archive.append(
        {
            points["PV"]: ("number", [(MS + 2_700_000, 0.94)]),
            points["MODE"]: ("text", [(MS + 2_700_000, "C")]),
        }
    )
    stamps = np.array([MS, MS + 1_800_000, MS + 3_000_000], dtype=np.int64)
    calls = []

    class Source:
        def recorded(self, addresses, start_ms, end_ms):
            calls.append(sorted(addresses))
            return {
                "ns=2;s=PV": (stamps, [0.91, 0.93, 9.9]),
                "ns=2;s=MODE": (stamps, ["A", "B", "Z"]),
            }

    loaded.source_history = lambda source_id: Source()
    window = {"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T01:00:00Z"}
    batch = pc.post(f"{DATA}/series", json={"signals": ["plant:PV", "plant:MODE"], **window})
    by_signal = {s["signal"]: s["v"] for s in batch.json()["series"]}
    assert by_signal["plant:PV"] == [0.91, 0.93, 0.94]
    assert by_signal["plant:MODE"] == ["A", "B", "C"]
    assert calls == [["ns=2;s=MODE", "ns=2;s=PV"]]


def test_dashboard_refreshes_of_a_pi_signal_ask_pi_only_for_the_tail(pc, runtime, monkeypatch):
    source = {
        "id": "pi",
        "name": "PI",
        "kind": "pi_web_api",
        "endpoint": "https://pi.example/piwebapi",
        "username": "svc",
        "password": "s3cret",
        "options": {"server": "PISRV", "auth_type": "basic"},
        "signals": ["FIC101.PV"],
    }
    assert pc.post("/hist/api/v1/data/sources", json=source).status_code == 201
    historian = Historian()  # one sample a minute
    monkeypatch.setattr(runtime, "source_history", lambda _source_id: historian)
    url = "/hist/api/v1/data/signals/pi:FIC101.PV/series"
    first = pc.get(url, params={"start": "2026-10-21T00:00:00Z", "end": "2026-10-21T08:00:00Z"})
    later = pc.get(url, params={"start": "2026-10-21T00:01:00Z", "end": "2026-10-21T08:01:00Z"})
    assert first.status_code == later.status_code == 200
    assert len(historian.calls) == 2
    asked = historian.calls[1][2] - historian.calls[1][1]
    assert asked == LATE_MS + MIN  # the tail, not eight hours
    assert later.json()["v"][-1] == first.json()["v"][-1] + 1


def test_the_historian_publishes_overview_widgets(client, loaded, runtime):
    """The Overview's widgets, as app.toml declares them: each answers in its shape and links
    stay under the Historian; the trend is about one point the person picks."""

    listed = client.get("/hist/api/widgets").json()
    assert {item["id"] for item in listed["widgets"] if item["default"]} == {"points"}
    assert apptest.widget_problems(client, "/hist") == []
    points = client.get("/hist/api/widgets/points").json()
    assert points["kind"] == "number" and points["href"] == "/hist/points"
    options = client.get("/hist/api/widgets/trend/options").json()["options"]
    assert options
    trend = client.get("/hist/api/widgets/trend", params={"item": options[-1]["value"]}).json()
    assert trend["kind"] == "series" and options[-1]["label"] in trend["label"]
    assert client.get("/hist/api/widgets/archive").json()["items"]
    # A forecast of centuries is no forecast (the demo said 623046 days).
    runtime.archive.set_state("forecast", {"days_to_full": 623046.0, "free_bytes": 10})
    rows = client.get("/hist/api/widgets/archive").json()["items"]
    assert any(row.get("value") == "Not in sight" for row in rows), rows


def test_a_retired_apps_source_is_marked_and_removed_with_its_points(client, pc, runtime):
    for app in ("cpmcraft", "twincraft"):
        body = {
            "series": [
                {"app": app, "signal": f"app-{app}:x", "t": ["2026-10-19T00:00:00Z"], "v": [1.0]}
            ]
        }
        assert pc.post(f"{DATA}/derived", json=body).json()["written"] == 1
    sources = {s["id"]: s for s in client.get("/hist/api/sources").json()}
    assert sources["app-cpmcraft"]["retired_into"] == "linkcraft"
    assert sources["app-twincraft"]["retired_into"] == "linkcraft"
    # Without with_points a source that has points is refused; with it, both go.
    assert client.delete("/hist/api/sources/app-cpmcraft").status_code == 409
    assert client.delete("/hist/api/sources/app-cpmcraft?with_points=true").status_code == 204
    assert "app-cpmcraft" not in {s["id"] for s in client.get("/hist/api/sources").json()}
    assert not runtime.catalog.points(source_id="app-cpmcraft")
    # Twin's source goes on the next start.
    assert runtime.catalog.drop_retired() == ["app-twincraft"]
    assert runtime.catalog.drop_retired() == []


def test_point_trend_gives_each_cells_lowest_and_highest_value(client, loaded):
    url = "/hist/api/points/plant:TI-100.PV/series"
    window = {"start": T0.isoformat(), "end": (T0 + timedelta(hours=1)).isoformat(), "step": 600}
    plain = client.get(url, params=window).json()
    assert "low" not in plain and len(plain["t"]) == 6
    trend = client.get(url, params={**window, "extremes": "true"}).json()
    # One value every 10 s, worth its index: 60 per 10-minute cell.
    assert trend["low"][:2] == [0.0, 60.0] and trend["high"][:2] == [59.0, 119.0]
    assert len(trend["low"]) == len(trend["t"])
    # No band for text, nor past a week.
    text = "/hist/api/points/plant:FIC-101.MODE/series"
    assert "low" not in client.get(text, params={**window, "extremes": "true"}).json()
    week = {**window, "end": (T0 + timedelta(days=8)).isoformat(), "step": 3600}
    assert "low" not in client.get(url, params={**week, "extremes": "true"}).json()


def test_a_new_plants_first_step_collects_the_signals_it_bound(client, loaded, runtime, fake):
    signals = [
        {"asset_id": "TI-100", "tag": "TI-100.PV", "role": "pv", "source_id": "plant"},
        {"asset_id": "FIC-102", "tag": "FIC-102.PV", "role": "pv", "source_id": "plant"},
        {"asset_id": "FIC-102", "tag": "FIC-102.PV", "role": "pv", "source_id": "plant"},
        {"asset_id": "LIC-1", "tag": "LIC-1.PV", "role": "pv", "source_id": "elsewhere"},
    ]
    done = client.post("/hist/api/start/collect-signals", json={"signals": signals})
    assert done.status_code == 200, done.text
    assert done.json()["counts"] == {"added": 1, "collected": 1, "elsewhere": 1}
    assert done.json()["open"] == "/hist/points"
    tags = {point["tag"] for point in runtime.catalog.points(source_id="plant")}
    assert "FIC-102.PV" in tags and "LIC-1.PV" not in tags
    again = client.post("/hist/api/start/collect-signals", json={"signals": signals}).json()
    assert again["counts"] == {"added": 0, "collected": 2, "elsewhere": 1}
    with client_for(runtime, fake, "operator") as viewer:
        refused = viewer.post("/hist/api/start/collect-signals", json={"signals": signals})
        assert refused.status_code == 403
