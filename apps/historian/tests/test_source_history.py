"""History read from plant sources through ``open_source`` (``histcraft.sources``).

PI Web API runs against a local stand-in (``tests/pi_fake.py``), OPC UA Historical Access
against an in-memory server (``tests/opcua_history_server.py``), CSV against a temporary
file. Times go in and come out as UTC epoch milliseconds.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from histcraft.sources.config import from_source
from histcraft.sources.history import open_source
from tests.opcua_history_server import NAMESPACE, HistoryServer
from tests.pi_fake import USER, FakePi, demo_tags

# A real OPC UA server on a local socket: the slow tier (PlantCraft docs/testing.md).
pytestmark = pytest.mark.slow

# One synthetic archive for every PI test (building it takes a while).
PI_TAGS = demo_tags()


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("all_proxy", raising=False)


def _ms(stamp: pd.Timestamp) -> int:
    return int(stamp.value // 1_000_000)


def _last_hours(hours: float) -> tuple[int, int]:
    """A window starting half a second after a whole second: stand-in events fall on whole
    seconds, so none sits exactly at start and every read has a value before start."""

    end = pd.Timestamp.now(tz="UTC").floor("s")
    return _ms(end - pd.Timedelta(hours=hours)) + 500, _ms(end)


def _pi_row(pi: FakePi, **options) -> dict:
    return {
        "id": "pi",
        "name": "Plant PI",
        "kind": "pi_web_api",
        "endpoint": pi.base_url,
        "namespace_uri": "",
        "username": USER[0],
        "options": {
            "server": "pisrv",
            "auth_type": "basic",
            "timeout_seconds": 30,
            "timezone": "America/New_York",
            **options,
        },
    }


@pytest.fixture
def pi():
    with FakePi(tags=PI_TAGS) as fake:
        yield fake


# --- PI Web API ---------------------------------------------------------------------------


def test_pi_recorded_events_numbers_labels_and_the_value_before_start(pi):
    source = open_source(_pi_row(pi), USER[1])
    start, end = _last_hours(6)
    out = source.recorded(["FIC101.PV", "FIC101.SP", "FIC101.MODE"], start, end)

    times, values = out["FIC101.PV"]
    assert times.dtype == np.int64 and values.dtype == np.float64
    assert np.all(np.diff(times) > 0)
    assert len(times) > 500
    # The plant's time zone plays no part: every event is inside the window (or just before).
    expected = [_ms(stamp) for stamp, _, _ in pi.tags["FIC101.PV"] if start <= _ms(stamp) <= end]
    assert list(times[1:]) == expected
    assert times[0] < start  # the last value before start, at its own time

    sp_times, sp_values = out["FIC101.SP"]
    assert sp_times[0] < start and set(sp_values) <= {50.0, 55.0}

    # MODE did not change in the window: only the value before start, as text.
    mode_times, mode_values = out["FIC101.MODE"]
    assert isinstance(mode_values, list)
    assert mode_values == ["AUTO"] and mode_times[0] < start


def test_pi_bad_values_and_system_states_are_gaps(pi):
    source = open_source(_pi_row(pi), USER[1])
    start, end = _last_hours(96)
    times, values = source.recorded(["PIC102.PV"], start, end)["PIC102.PV"]
    assert values.dtype == np.float64
    assert np.isnan(values).sum() > 100
    assert np.isfinite(values).sum() > 1000


def test_pi_recorded_pages_past_the_per_call_limit():
    with FakePi(tags=PI_TAGS, max_items=200) as pi:
        source = open_source(_pi_row(pi, page_size=200), USER[1])
        start, end = _last_hours(12)
        times, _ = source.recorded(["FIC101.PV"], start, end)["FIC101.PV"]
        inside = [s for s, _, _ in pi.tags["FIC101.PV"] if start <= _ms(s) <= end]
        assert len(times) == len(inside) + 1 > 2000
        assert pi.calls["recorded"] >= len(inside) // 200


def test_pi_transient_errors_are_retried_and_persistent_ones_named(pi):
    pi.fail_next["recorded"] = 2
    source = open_source(_pi_row(pi), USER[1])
    start, end = _last_hours(1)
    times, _ = source.recorded(["FIC101.PV"], start, end)["FIC101.PV"]
    assert len(times) > 10
    assert pi.calls["recorded"] == 3

    pi.fail_next["recorded"] = 10
    flaky = open_source(_pi_row(pi, retries=1), USER[1])
    out = flaky.recorded(["FIC101.PV"], start, end)
    assert isinstance(out["FIC101.PV"], str) and "503" in out["FIC101.PV"]


def test_pi_missing_tag_does_not_sink_the_others(pi):
    source = open_source(_pi_row(pi), USER[1])
    start, end = _last_hours(1)
    out = source.recorded(["FIC101.PV", "XYZ999"], start, end)
    assert not isinstance(out["FIC101.PV"], str)
    assert "tag XYZ999 does not exist on server pisrv" in out["XYZ999"]


def test_pi_basic_authentication_and_test(pi):
    answer = open_source(_pi_row(pi), USER[1]).test()
    assert answer["server"].upper() == "PISRV"
    assert answer["user"] == f"EXAMPLE\\{USER[0]}"
    with pytest.raises(Exception, match="refused the basic authentication.*Negotiate"):
        open_source(_pi_row(pi), "wrong").test()
    with pytest.raises(Exception, match="does not appear in PI Web API"):
        open_source(_pi_row(pi, server="other"), USER[1]).test()


def test_pi_browse_lists_points_by_name_filter(pi):
    source = open_source(_pi_row(pi), USER[1])
    found = source.browse("FIC101")
    by_tag = {v["tag"]: v for v in found["variables"]}
    assert set(by_tag) == {"FIC101.PV", "FIC101.SP", "FIC101.OP", "FIC101.MODE"}
    assert found["truncated"] is False
    assert by_tag["FIC101.PV"]["unit"] == "m3/h"
    assert by_tag["FIC101.PV"]["address"] == "FIC101.PV"
    assert by_tag["FIC101.MODE"]["kind"] == "text" and by_tag["FIC101.MODE"]["step"]
    assert by_tag["FIC101.SP"]["step"] and not by_tag["FIC101.PV"]["step"]
    # The range is PI's Zero to Zero + Span (D2); none for a digital point.
    assert (by_tag["FIC101.PV"]["low"], by_tag["FIC101.PV"]["high"]) == (0.0, 200.0)
    assert by_tag["FIC101.MODE"]["low"] is None
    cut = source.browse(None, limit=2)
    assert len(cut["variables"]) == 2 and cut["truncated"] is True and cut["limit"] == 2


def test_pi_client_only_reads(pi):
    source = open_source(_pi_row(pi), USER[1])
    start, end = _last_hours(1)
    source.recorded(["FIC101.PV", "FIC101.MODE"], start, end)
    source.browse("PIC")
    source.test()
    assert set(pi.methods) == {"GET"}


def test_pi_check_walks_every_step_and_names_what_to_fix(pi, tmp_path):
    from histcraft.sources.pi_check import FAIL, OK, run_check

    report = run_check(_pi_row(pi), USER[1], ["FIC101.PV", "FIC101.SP", "XYZ999"], hours=6)
    steps = {check.step: check for check in report.checks}
    assert steps["DNS"].status == OK
    assert steps["Network"].status == OK
    assert "PISRV" in steps["PI Web API"].detail.upper()
    assert USER[0] in steps["User"].detail
    assert steps["Tags"].status == FAIL
    rows = {row["tag"]: row for row in report.tags}
    assert rows["FIC101.PV"]["status"] == OK
    assert "does not exist" in rows["XYZ999"]["note"]
    assert report.failed
    assert report.markdown().startswith("# PI diagnosis · Plant PI")
    assert "Tags with problems:" in report.text()


def test_source_rows_map_onto_adapter_settings():
    opcua = {"id": "u", "kind": "opcua", "endpoint": "opc.tcp://h:4840", "options": {}}
    assert from_source(opcua, "").auth_type == "anonymous"
    assert from_source({**opcua, "username": "reader"}, "pw").auth_type == "basic"
    assert from_source({**opcua, "username": "reader"}, "pw").secret() == "pw"
    with pytest.raises(ValueError):
        open_source({"id": "d", "kind": "derived", "endpoint": "", "options": {}}, "")


# --- CSV ------------------------------------------------------------------------------------


def test_csv_read_browse_and_test(tmp_path):
    path = tmp_path / "plant.csv"
    # Naive times are local times in the source's zone (UTC-3 here).
    path.write_text(
        "time,FIC-101.PV,FIC-101.MODE\n"
        "2026-01-01 09:00:00,10.0,AUTO\n"
        "2026-01-01 09:00:30,,\n"
        "2026-01-01 09:01:00,11.5,MAN\n"
        "2026-01-01 09:01:30,12.0,\n"
        "2026-01-01 09:02:00,12.5,AUTO\n",
        encoding="utf-8",
    )
    row = {
        "id": "f",
        "kind": "csv",
        "endpoint": str(path),
        "options": {"timezone": "Etc/GMT+3"},
    }
    source = open_source(row, "")
    base = _ms(pd.Timestamp("2026-01-01 12:00:00", tz="UTC"))
    out = source.recorded(["FIC-101.PV", "FIC-101.MODE", "nope"], base + 45_000, base + 90_000)
    times, values = out["FIC-101.PV"]
    # The row at 30 s is empty: the value before start is the one at 0 s.
    assert list(times) == [base, base + 60_000, base + 90_000]
    assert list(values) == [10.0, 11.5, 12.0]
    # Empty cells are no value at that time (a sparse file), for text as for numbers.
    mode_times, modes = out["FIC-101.MODE"]
    assert list(mode_times) == [base, base + 60_000]
    assert modes == ["AUTO", "MAN"]
    assert "no column nope" in out["nope"]

    found = source.browse()
    kinds = {v["tag"]: v["kind"] for v in found["variables"]}
    assert kinds == {"FIC-101.PV": "number", "FIC-101.MODE": "text"}
    assert source.test()["tags"] == 2

    missing = open_source({**row, "endpoint": str(tmp_path / "gone.csv")}, "")
    assert "not found" in missing.recorded(["FIC-101.PV"], base, base + 1)["FIC-101.PV"]
    with pytest.raises(FileNotFoundError):
        missing.test()


# --- OPC UA Historical Access ----------------------------------------------------------------


@pytest.fixture(scope="module")
def history_server():
    with HistoryServer(minutes=10, sample_seconds=30) as server:
        yield server


def _opcua_row(server: HistoryServer) -> dict:
    return {
        "id": "ua",
        "kind": "opcua",
        "endpoint": server.endpoint,
        "namespace_uri": NAMESPACE,
        "username": "",
        "options": {"timeout_seconds": 30, "timezone": "America/New_York"},
    }


def test_opcua_history_read(history_server):
    source = open_source(_opcua_row(history_server), "")
    stamps = [_ms(pd.Timestamp(s)) for s in history_server.stamps]
    start, end = stamps[5] + 1, stamps[15]
    out = source.recorded(["FIC-101.PV", "FIC-101.MODE", "TI-100.PV", "NOPE.PV"], start, end)

    times, values = out["FIC-101.PV"]
    assert list(times) == stamps[5:16]  # the value before start at its own time
    assert values.dtype == np.float64 and np.isfinite(values).all()

    mode_times, modes = out["FIC-101.MODE"]
    assert list(mode_times) == stamps[5:16]
    assert set(modes) == {"AUTO", "MAN"}

    # Bad quality is a gap, never a value.
    _, temperatures = out["TI-100.PV"]
    assert np.isnan(temperatures).any() and np.isfinite(temperatures).any()

    assert isinstance(out["NOPE.PV"], str)


def test_opcua_history_reads_whole_node_ids_as_the_collector_does(history_server):
    # Points added from the collector's Browse hold ns=<i>;s=<tag>; history took only <tag>
    # (found by the source test kit, 2026-10-24), so backfill and mode both read nothing.
    source = open_source(_opcua_row(history_server), "")
    stamps = [_ms(pd.Timestamp(s)) for s in history_server.stamps]
    bare = source.recorded(["FIC-101.PV"], stamps[5] + 1, stamps[15])["FIC-101.PV"]
    found = source.recorded(["ns=2;s=FIC-101.PV"], stamps[5] + 1, stamps[15])
    times, values = found["ns=2;s=FIC-101.PV"]
    assert list(times) == list(bare[0]) and list(values) == list(bare[1])


def test_opcua_browse_and_test(history_server):
    source = open_source(_opcua_row(history_server), "")
    found = source.browse()
    by_tag = {v["tag"]: v for v in found["variables"]}
    assert set(by_tag) == {"FIC-101.PV", "FIC-101.SP", "FIC-101.MODE", "TI-100.PV"}
    pv = by_tag["FIC-101.PV"]
    assert pv["address"] == "FIC-101.PV"
    assert pv["path"] == "Unit100/FIC-101/PV"
    assert pv["unit"] == "m3/h" and pv["description"] == "Feed flow"
    assert by_tag["FIC-101.MODE"]["kind"] == "text" and by_tag["FIC-101.MODE"]["step"]
    assert source.browse("Unit100/TI-100")["variables"][0]["tag"] == "TI-100.PV"
    cut = source.browse(limit=1)
    assert len(cut["variables"]) == 1 and cut["truncated"]

    answer = source.test()
    assert answer["namespace_index"] >= 1

    wrong = open_source({**_opcua_row(history_server), "namespace_uri": "urn:nope"}, "")
    with pytest.raises(ValueError, match="urn:nope"):
        wrong.test()
