"""CSV: every sample file of the kit read right, as a source watched and as an import."""

from __future__ import annotations

import json

import pytest
from simcraft.testkit import csv_files

from histcraft.catalog.models import PointIn, SourceIn
from histcraft.sources.csv_table import read_table
from sources_check.conftest import rebuilt, wait

pytestmark = pytest.mark.slow


@pytest.fixture
def samples(tmp_path, series, monkeypatch):
    folder = tmp_path / "kit"
    expected = csv_files.write(folder, series)
    monkeypatch.setenv("HISTCRAFT_CSV_DIRS", str(folder))
    return folder, expected


def test_every_sample_file_reads_as_the_plant(samples, series):
    folder, expected = samples
    for name, about in expected.items():
        table = read_table((folder / name).read_bytes(), about.get("timezone", "UTC"))
        if name == "errors.csv":
            assert sorted(line for e in table.errors for line in e["lines"]) == about["error_lines"]
            continue
        assert not table.errors, (name, table.errors)
        assert table.shape == about["shape"], name
        assert sorted(table.series) == sorted(about["tags"]), name
        for tag in about["tags"]:
            read, published = table.series[tag], series[tag]
            assert list(read.times) == published.times, (name, tag)
            if published.kind == "text":
                assert list(read.values) == published.values, (name, tag)
            else:
                assert list(read.values) == pytest.approx(published.values, rel=1e-12), (name, tag)
    long = read_table((folder / "long.csv").read_bytes())
    want = expected["long.csv"]["qualities"]["FIC-101.PV"]
    changes = [[stamp, quality] for stamp, quality in long.series["FIC-101.PV"].qualities]
    # Quality changes only, from good (a value without one counts as good).
    kept = [b for a, b in zip([[0, "good"], *want], want, strict=False) if a[1] != b[1]]
    assert changes == kept


def test_a_csv_source_archives_a_folder_of_files(historian, samples, series):
    folder, _ = samples
    tags = ["FIC-101.PV", "FIC-101.SP", "PIC-102.OP"]
    historian.add(
        SourceIn(
            id="lims",
            name="LIMS",
            kind="csv",
            endpoint=str(folder / "wide-*.csv"),
            options={"timezone": "UTC", "check_minutes": 0.5},
        ),
        [PointIn(tag=tag, source_id="lims", deviation=0, step=tag.endswith(".SP")) for tag in tags],
    )
    historian.thread.start()
    for tag in tags:
        published = series[tag]
        times, values = wait(
            lambda tag=tag: (
                (got := historian.archived(f"lims:{tag}"))
                and len(got[0])
                and got[0][-1] == series[tag].times[-1]
                and got
            ),
            what=f"lims:{tag}",
        )
        again = rebuilt(times, values, published.times, step=tag.endswith(".SP"))
        assert again == pytest.approx(published.values, rel=1e-9), tag
    status = historian.status("lims")
    assert status["status"] == "connected" and status["files"] == 4


def test_an_import_writes_the_long_file_with_its_qualities(historian, samples, series):
    from plantcraft_sdk.testing import FakePlantCraft

    from histcraft.api.runtime import Runtime
    from tests.conftest import USERS, client_for

    folder, expected = samples
    historian.thread.start()
    fake = FakePlantCraft(users=USERS)
    runtime = Runtime(
        historian.settings, verifier=fake.verifier("histcraft"), http_client=fake.http_client()
    )
    with client_for(runtime, fake) as client:
        checked = client.post(
            "/hist/api/imports/check?name=long.csv&timezone=UTC",
            content=(folder / "long.csv").read_bytes(),
        ).json()
        assert checked["ok"], json.dumps(checked["report"])[:500]
        item = client.post("/hist/api/imports", json={"token": checked["token"], "name": "Kit"})
        assert item.status_code in (200, 201), item.text
        source = item.json()["id"]
        done = wait(
            lambda: next(
                (
                    i
                    for i in client.get("/hist/api/imports").json()
                    if i["id"] == source and i["status"] == "done"
                ),
                None,
            ),
            what="the import",
        )
    assert done["points"] == len(expected["long.csv"]["tags"])
    times, values = historian.archived(f"{source}:FIC-101.OP")
    assert list(times) == series["FIC-101.OP"].times
    assert list(values) == pytest.approx(series["FIC-101.OP"].values, rel=1e-12)
    times, values = historian.archived(f"{source}:FIC-101.MODE")
    assert set(values) == set(series["FIC-101.MODE"].values)
    point = historian.point(f"{source}:FIC-101.PV")
    qualities = [quality for _, quality in historian.archive.qualities(point, 0, 2**62)]
    assert "bad" in qualities and "uncertain" in qualities
    runtime.shutdown()
