"""A CSV file sent from the Sources page becomes a CSV source the collector reads; CSV sources
read only their folders."""

from __future__ import annotations

from pathlib import Path

CSV = b"time,LAB-101.DENSITY,LAB-101.SULFUR\n2026-10-20T00:00:00Z,0.85,120\n2026-10-20T04:00:00Z,0.86,118\n"


def test_an_admin_sends_a_csv_and_a_source_reads_it(client):
    answer = client.post("/hist/api/sources/files?name=lab analyses.csv", content=CSV)
    assert answer.status_code == 201, answer.text
    found = answer.json()
    assert (found["columns"], found["rows"]) == (2, 2)
    path = Path(found["path"])
    assert path.name == "lab-analyses.csv" and path.read_bytes() == CSV
    source = {
        "id": "lab",
        "name": "Lab",
        "kind": "csv",
        "endpoint": found["path"],
        "options": {"timezone": "UTC"},
    }
    assert client.post("/hist/api/sources", json=source).status_code == 201


def test_a_file_that_is_not_a_wide_csv_is_refused(client):
    for body in (b"", b"just,a,header\n", b"name,value\nfoo,1\nbar,2\n"):
        answer = client.post("/hist/api/sources/files?name=x.csv", content=body)
        assert answer.status_code == 422, (body, answer.text)


def test_csv_sources_read_only_their_folders(client, tmp_path, monkeypatch):
    # Security audit 2026-10-22: a CSV source read any path of the Historian's container, so an
    # administrator could browse /proc/self/environ (the app key, as column names) or the key
    # that encrypts source passwords. Now only HISTCRAFT_CSV_DIRS and <data dir>/files.
    from histcraft.sources.csv_watch import CsvWatcher

    monkeypatch.setenv("HISTCRAFT_CSV_DIRS", str(tmp_path / "csv"))
    monkeypatch.setenv("HISTCRAFT_DATA_DIR", str(tmp_path))
    (tmp_path / "csv").mkdir()
    (tmp_path / "csv" / "lab.csv").write_bytes(CSV)
    (tmp_path / "secret.csv").write_bytes(CSV)
    (tmp_path / "csv" / "link.csv").symlink_to(tmp_path / "secret.csv")
    source = {"id": "lab", "name": "Lab", "kind": "csv", "options": {"timezone": "UTC"}}
    for path in (
        "/proc/self/environ",
        str(tmp_path / "secret.csv"),
        str(tmp_path / "csv" / ".." / "secret.csv"),
        str(tmp_path / "csv" / "link.csv"),
    ):
        refused = client.post("/hist/api/sources", json={**source, "endpoint": path})
        assert refused.status_code == 422, path
        assert "reads only files in" in refused.text
    inside = {**source, "endpoint": str(tmp_path / "csv" / "lab.csv")}
    assert client.post("/hist/api/sources", json=inside).status_code == 201
    sent = client.post("/hist/api/sources/files?name=lab2.csv", content=CSV).json()
    uploaded = {**source, "id": "lab2", "endpoint": sent["path"]}
    assert client.post("/hist/api/sources", json=uploaded).status_code == 201
    # A source saved before the check existed is refused when it is read.
    old = CsvWatcher({"endpoint": "/proc/self/environ", "options": {}})
    try:
        old.browse()
    except PermissionError as error:
        assert "reads only files in" in str(error)
    else:
        raise AssertionError("a CSV outside its folders was read")


def test_a_pattern_never_follows_a_link_out_of_its_folder(tmp_path, monkeypatch):
    from histcraft.sources.csv_watch import CsvWatcher

    monkeypatch.setenv("HISTCRAFT_CSV_DIRS", str(tmp_path / "csv"))
    monkeypatch.setenv("HISTCRAFT_DATA_DIR", str(tmp_path))
    (tmp_path / "csv").mkdir()
    (tmp_path / "csv" / "day1.csv").write_bytes(CSV)
    (tmp_path / "secret.csv").write_bytes(CSV)
    (tmp_path / "csv" / "day2.csv").symlink_to(tmp_path / "secret.csv")
    watcher = CsvWatcher({"endpoint": str(tmp_path / "csv" / "*.csv"), "options": {}})
    assert [path.name for path in watcher.files()] == ["day1.csv"]
