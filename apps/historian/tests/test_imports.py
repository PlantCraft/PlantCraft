"""CSV imports (owner, 2026-10-24): checked before anything is written, written once by the
collector, the file deleted, kept until the import is deleted, and deleted with all its data."""

from __future__ import annotations

import io
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

from histcraft.collector import imports
from histcraft.collector.service import Collector

CSV = (
    b"time,LAB-101.DENSITY,LAB-101.GRADE\n"
    b"2020-01-01 00:00,0.85,A\n"
    b"2020-01-01 04:00,0.86,B\n"
    b"2020-01-01 08:00,0.87,B\n"
)


def check(client, data=CSV, name="lab 2020.csv", zone="UTC"):
    answer = client.post(f"/hist/api/imports/check?name={name}&timezone={zone}", content=data)
    assert answer.status_code == 200, answer.text
    return answer.json()


def collect(runtime) -> list[dict]:
    return [
        imports.write_import(path, runtime.catalog, runtime.archive)
        for path in imports.waiting(runtime.settings.data_dir)
    ]


def test_a_file_is_checked_imported_and_deleted_with_its_data(client, runtime):
    checked = check(client)
    assert checked["ok"] and checked["token"]
    report = checked["report"]
    assert (report["shape"], report["rows"], report["values"]) == ("wide", 3, 6)
    assert {item["tag"]: item["kind"] for item in report["tags"]} == {
        "LAB-101.DENSITY": "number",
        "LAB-101.GRADE": "text",
    }
    # Nothing is written by a check.
    assert not [s for s in runtime.catalog.sources() if s["kind"] == "import"]

    made = client.post("/hist/api/imports", json={"token": checked["token"]})
    assert made.status_code == 201, made.text
    item = made.json()
    assert (item["id"], item["status"], item["points"]) == ("import-1", "writing", 2)
    assert item["file_name"] == "lab 2020.csv"

    written = collect(runtime)
    assert [(item["status"], item["values"]) for item in written] == [("done", 6)]
    listed = client.get("/hist/api/imports").json()
    assert listed[0]["status"] == "done" and listed[0]["written"] == 6
    # The file is gone: only the values are kept.
    assert not list((Path(runtime.settings.data_dir) / "imports").rglob("*.csv"))
    series = client.get(
        "/hist/api/points/import-1:LAB-101.DENSITY/series",
        params={"start": "2019-12-31T23:00:00Z", "end": "2020-01-01T09:00:00Z"},
    ).json()
    assert series["v"][-1] == 0.87

    # Old data is kept past the general retention (400 days), until the import is deleted.
    collector = Collector(runtime.settings, runtime.catalog, runtime.archive)
    collector.housekeeping(force=True)
    point = runtime.catalog.point("import-1:LAB-101.DENSITY")
    assert runtime.archive.span(int(point["id"])) is not None

    assert client.delete("/hist/api/imports/import-1").json()["points"] == 2
    assert client.get("/hist/api/imports").json() == []
    collector.reload()
    assert runtime.archive.span(int(point["id"])) is None


def test_a_file_with_errors_cannot_be_imported(client):
    checked = check(client, b"time,A\n2026-10-01 08:00,1\nnot a time,2\n")
    assert not checked["ok"] and not checked["token"]
    assert checked["report"]["errors"][0]["lines"] == [3]
    refused = client.post("/hist/api/imports", json={"token": "0" * 32})
    assert refused.status_code == 410


def test_the_same_file_twice_is_reported(client, runtime):
    client.post("/hist/api/imports", json={"token": check(client)["token"]})
    again = check(client)["report"]["warnings"]
    assert "imported before (import-1)" in again[0]["message"]


def test_an_import_deleted_before_it_was_written_leaves_nothing(client, runtime):
    client.post("/hist/api/imports", json={"token": check(client)["token"]})
    client.delete("/hist/api/imports/import-1")
    assert collect(runtime) == []
    assert not list((Path(runtime.settings.data_dir) / "imports").glob("import-*"))


def test_operators_cannot_import(runtime, fake):
    from tests.conftest import client_for

    with client_for(runtime, fake, "operator") as client:
        answer = client.post("/hist/api/imports/check?name=x.csv", content=CSV)
        assert answer.status_code == 403
        assert client.get("/hist/api/imports").status_code == 200


def test_an_unknown_time_zone_is_refused(client):
    answer = client.post("/hist/api/imports/check?name=x.csv&timezone=Mars/Base", content=CSV)
    assert answer.status_code == 422


def test_a_check_answers_what_it_detected_and_takes_options(client):
    data = (
        b"Exported from LIMS\n"
        b"sample date;Viscosity;Density\n"
        b"24/10/2026 08:00;412,5;0,85\n"
        b"24/10/2026 12:00;415,0;0,86\n"
    )
    # Detected as it stands: the title line above the header is skipped, day first is guessed.
    found = check(client, data, name="lims.csv")
    assert found["ok"], found["report"]["errors"]
    assert (found["report"]["options"]["skip_rows"], found["report"]["options"]["delimiter"]) == (
        1,
        ";",
    )
    options = json.dumps({"skip_rows": 1, "time_format": "%d/%m/%Y %H:%M", "tag_prefix": "LAB."})
    answer = client.post(
        "/hist/api/imports/check",
        params={"name": "lims.csv", "timezone": "America/Sao_Paulo", "options": options},
        content=data,
    ).json()
    assert answer["ok"], answer["report"]["errors"]
    used = answer["report"]["options"]
    assert (used["delimiter"], used["decimal"], used["shape"]) == (";", ",", "wide")
    assert used["time_column"] == "sample date"
    assert used["columns"] == ["sample date", "Viscosity", "Density"]
    assert [tag["tag"] for tag in answer["report"]["tags"]] == ["LAB.Viscosity", "LAB.Density"]
    preview = answer["report"]["preview"]
    assert preview["rows"][0] == ["24/10/2026 08:00", "412,5", "0,85"]
    assert preview["times"][0] == "2026-10-24T11:00:00+00:00"
    bad = client.post(
        "/hist/api/imports/check",
        params={"name": "x.csv", "options": json.dumps({"shape": "tall"})},
        content=data,
    )
    assert bad.status_code == 422


def test_an_excel_sheet_is_read_like_a_csv(client, runtime):
    from openpyxl import Workbook

    book = Workbook()
    book.active.title = "Notes"
    sheet = book.create_sheet("Data")
    sheet.append(["time", "FI-101.PV"])
    sheet.append([datetime(2026, 10, 1, 8, 0), 52.4])  # noqa: DTZ001 (Excel keeps wall-clock times)
    sheet.append([datetime(2026, 10, 1, 8, 1), 52.9])  # noqa: DTZ001
    buffer = io.BytesIO()
    book.save(buffer)
    first = client.post(
        "/hist/api/imports/check", params={"name": "plant.xlsx"}, content=buffer.getvalue()
    ).json()
    assert not first["ok"] and first["report"]["options"]["sheets"] == ["Notes", "Data"]
    answer = client.post(
        "/hist/api/imports/check",
        params={"name": "plant.xlsx", "options": json.dumps({"sheet": "Data"})},
        content=buffer.getvalue(),
    ).json()
    assert answer["ok"], answer["report"]["errors"]
    assert answer["report"]["values"] == 2
    assert answer["report"]["preview"]["times"][1] == "2026-10-01T08:01:00+00:00"
    made = client.post("/hist/api/imports", json={"token": answer["token"]}).json()
    assert [item["status"] for item in collect(runtime)] == ["done"]
    assert made["read"]["sheet"] == "Data"


def test_the_next_file_joins_the_import_read_the_same_way(client, runtime):
    made = client.post("/hist/api/imports", json={"token": check(client)["token"]}).json()
    collect(runtime)
    later = (
        b"time,LAB-101.DENSITY,LAB-102.DENSITY\n"
        b"2020-01-01 08:00,0.90,1.10\n"
        b"2020-01-02 00:00,0.88,1.12\n"
    )
    checked = check(client, later, name="lab 2020-01-02.csv")
    added = client.post("/hist/api/imports", json={"token": checked["token"], "into": made["id"]})
    assert added.status_code == 201, added.text
    item = added.json()
    assert item["id"] == made["id"] and item["points"] == 3
    assert [run["file_name"] for run in item["runs"]] == ["lab 2020-01-02.csv", "lab 2020.csv"]
    assert item["values"] == 10
    collect(runtime)
    series = client.get(
        "/hist/api/points/import-1:LAB-101.DENSITY/series",
        params={"start": "2019-12-31T23:00:00Z", "end": "2020-01-02T01:00:00Z"},
    ).json()
    # 08:00 was in both files: the newer value replaced the older one.
    assert series["v"] == [0.85, 0.86, 0.90, 0.88]
    # A text column that became numbers is refused before anything is written.
    clash = check(client, b"time,LAB-101.GRADE\n2020-01-03 00:00,4\n", name="grade.csv")
    refused = client.post("/hist/api/imports", json={"token": clash["token"], "into": "import-1"})
    assert refused.status_code == 409


def test_examples_of_each_layout_import(client):
    for shape in ("wide", "long"):
        example = client.get(f"/hist/api/imports/example/{shape}.csv")
        assert example.status_code == 200
        assert check(client, example.content, name=f"{shape}.csv")["report"]["shape"] == shape
    assert client.get("/hist/api/imports/example/tall.csv").status_code == 404


def test_one_tag_in_two_imports_exports_as_two_columns(client, runtime):
    # The same lab tags imported twice (two files, two imports): neither column is lost.
    for data in (CSV, CSV.replace(b"0.8", b"0.9")):
        token = check(client, data)["token"]
        assert client.post("/hist/api/imports", json={"token": token}).status_code == 201
    collect(runtime)
    choice = {
        "signals": ["import-1:LAB-101.DENSITY", "import-2:LAB-101.DENSITY"],
        "assets": [],
        "start": "2019-12-31T23:00:00Z",
        "end": "2020-01-01T09:00:00Z",
        "step_seconds": None,
        "anonymize": False,
    }
    answer = client.post("/hist/api/export", json=choice)
    assert answer.status_code == 200, answer.text
    series = zipfile.ZipFile(io.BytesIO(answer.content)).read("series.csv").decode()
    header, *lines = series.splitlines()
    assert header == "time,import-1:LAB-101.DENSITY,import-2:LAB-101.DENSITY"
    assert lines[-1].endswith(",0.87,0.97")


# The suite's work queue and imports that repeat from a folder (owner, 2026-10-26): a heavy
# file shows its progress in the Queue; a saved import reads each new file of a folder, the
# same way, into the same signals.


def make(client, data=CSV):
    made = client.post("/hist/api/imports", json={"token": check(client, data)["token"]})
    assert made.status_code == 201, made.text
    return made.json()


def series(client, signal):
    return client.get(
        f"/hist/api/points/{signal}/series",
        params={"start": "2019-12-31T00:00:00Z", "end": "2020-01-10T00:00:00Z"},
    ).json()


def test_the_queue_lists_an_import_waiting_then_done(client, runtime):
    empty = client.get("/hist/api/queue?window=1h").json()
    assert empty["format"] == "plantcraft-queue/1"
    assert empty["url"] == "imports" and empty["items"] == []
    assert empty["now"]["queued"] == 0

    make(client)
    waiting = client.get("/hist/api/queue?window=1h").json()
    assert waiting["now"]["queued"] == 1 and waiting["now"]["running"] == 0
    [item] = waiting["items"]
    assert (item["id"], item["status"], item["by"]) == ("import-1", "queued", "admin")
    assert item["cancel"]["href"] == "/hist/api/imports/import-1/cancel"
    assert item["url"] == "/hist/sources/import-1"

    collect(runtime)
    done = client.get("/hist/api/queue?window=1h").json()
    [item] = done["items"]
    assert (item["status"], item["progress"]) == ("done", 1.0)
    assert item["started_at"] and item["finished_at"] and "cancel" not in item
    assert done["now"]["queued"] == 0 and done["now"]["done_hour"] == 1
    # The sampler keeps the numbers for the panel's history.
    runtime.queue_metrics.record(runtime.queue_now())
    assert runtime.queue_metrics.history("1h")


def test_progress_is_saved_while_a_file_is_written(client, runtime, monkeypatch):
    make(client)
    seen = []
    write = runtime.archive.set_state

    def spy(key, value):
        if key == "import:import-1":
            seen.append(dict(value))
            if value.get("status") == "running" and value.get("total"):
                item = client.get("/hist/api/imports").json()[0]
                assert item["status"] == "writing" and item["step"]
                queued = client.get("/hist/api/queue").json()["items"][0]
                assert queued["status"] == "running" and queued["step"]
        write(key, value)

    monkeypatch.setattr(imports, "PROGRESS_SECONDS", 0.0)
    monkeypatch.setattr(runtime.archive, "set_state", spy)
    collect(runtime)
    steps = [(item["status"], item.get("done"), item.get("total")) for item in seen]
    assert steps[0][0] == "running" and steps[-1][0] == "done"
    assert ("running", 0, 2) in steps and ("running", 2, 2) in steps


def test_a_waiting_file_is_cancelled(client, runtime):
    made = make(client)
    assert client.post(f"/hist/api/imports/{made['id']}/cancel").json()["deleted"] is True
    assert client.get("/hist/api/imports").json() == []
    assert collect(runtime) == []

    # The next file of an import: only that file leaves the list.
    made = make(client)
    collect(runtime)
    later = check(client, b"time,LAB-101.DENSITY\n2020-01-02 00:00,0.9\n", name="next.csv")
    client.post("/hist/api/imports", json={"token": later["token"], "into": made["id"]})
    answer = client.post(f"/hist/api/imports/{made['id']}/cancel")
    assert answer.json()["deleted"] is False
    item = client.get("/hist/api/imports").json()[0]
    assert [run["file_name"] for run in item["runs"]] == ["lab 2020.csv"]
    assert (item["status"], item["values"]) == ("done", 6)
    # Nothing waits any more.
    assert client.post(f"/hist/api/imports/{made['id']}/cancel").status_code == 409


def test_an_import_repeats_from_a_folder(client, runtime, tmp_path):
    made = make(client)
    collect(runtime)
    folder = tmp_path / "lab"
    folder.mkdir()
    (folder / "2020-01-02.csv").write_bytes(
        b"time,LAB-101.DENSITY,LAB-103.DENSITY\n2020-01-02 00:00,0.91,1.3\n"
    )
    pattern = str(folder / "*.csv")
    answer = client.put(
        f"/hist/api/imports/{made['id']}/repeat",
        json={"pattern": pattern, "check_minutes": 1440},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["found"] == 1
    assert answer.json()["repeat"]["pattern"] == pattern

    [source] = imports.repeating(runtime.catalog)
    assert imports.due(source, runtime.archive)
    state = imports.check_folder(source, runtime.catalog, runtime.archive)
    assert state["written"] == 1 and state["detail"] == ""
    # New tags became signals; values joined the import's signals.
    assert series(client, "import-1:LAB-101.DENSITY")["v"][-1] == 0.91
    assert series(client, "import-1:LAB-103.DENSITY")["v"] == [1.3]
    item = client.get("/hist/api/imports").json()[0]
    assert item["runs"][0]["file_name"] == "2020-01-02.csv" and item["runs"][0]["folder"]
    assert item["points"] == 3 and item["repeat"]["files"] == 1

    # Not due again before a day; a file unchanged is not read again.
    source = imports.repeating(runtime.catalog)[0]
    assert not imports.due(source, runtime.archive)
    assert imports.check_folder(source, runtime.catalog, runtime.archive)["written"] == 0

    # A new file and a changed one are read; a file with errors is reported, not written.
    (folder / "2020-01-03.csv").write_bytes(b"time,LAB-101.DENSITY\n2020-01-03 00:00,0.92\n")
    (folder / "bad.csv").write_bytes(b"time,LAB-101.DENSITY\nnot a time,1\n")
    changed = folder / "2020-01-02.csv"
    changed.write_bytes(b"time,LAB-101.DENSITY\n2020-01-02 00:00,0.95\n")
    os.utime(changed, ns=(changed.stat().st_atime_ns, changed.stat().st_mtime_ns + 10**9))
    state = imports.check_folder(source, runtime.catalog, runtime.archive)
    assert state["written"] == 2 and "bad.csv" in state["detail"]
    assert series(client, "import-1:LAB-101.DENSITY")["v"][-2:] == [0.95, 0.92]
    # The folder's files are only read.
    assert sorted(path.name for path in folder.iterdir()) == [
        "2020-01-02.csv",
        "2020-01-03.csv",
        "bad.csv",
    ]

    # Stopping keeps the values.
    stop = client.put(f"/hist/api/imports/{made['id']}/repeat", json={"pattern": ""})
    assert stop.json()["repeat"] == {} and imports.repeating(runtime.catalog) == []
    assert series(client, "import-1:LAB-103.DENSITY")["v"] == [1.3]


def test_a_repeat_reads_only_inside_the_csv_folders(client, runtime, tmp_path):
    made = make(client)
    outside = client.put(f"/hist/api/imports/{made['id']}/repeat", json={"pattern": "/etc/*.csv"})
    assert outside.status_code == 422
    missing = client.put(
        f"/hist/api/imports/{made['id']}/repeat", json={"pattern": str(tmp_path / "no/*.csv")}
    )
    assert missing.status_code == 422
    assert client.put("/hist/api/imports/import-9/repeat", json={"pattern": ""}).status_code == 404
