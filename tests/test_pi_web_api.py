"""PI Web API source against a local stand-in server (tests/pi_fake.py)."""

from __future__ import annotations

import socket

import pandas as pd
import pytest

from processcraft.config import DataSourceConfig, LoopConfig
from processcraft.db import Database
from processcraft.industrial_data.cache import HistoryCache, build_cached_source
from processcraft.industrial_data.pi_web_api import (
    PiError,
    PiWebApiSource,
    make_web_id,
    normalize_value,
)
from processcraft.industrial_data.sources import build_loop_frame
from tests.pi_fake import FakePi

TAGS = ["FIC4241004", "FIC4241004S", "FIC4241004O", "FIC4241004M", "PIC4241048"]
MAPPING = {"FIC4241004": "Feed.FPV", "FIC4241004S": "Feed.FSP", "FIC4241004M": "Feed.MODE"}


@pytest.fixture
def pi(monkeypatch):
    monkeypatch.setenv("PI_TEST_PASSWORD", "segredo")
    with FakePi() as fake:
        yield fake


def _config(pi: FakePi, **overrides) -> DataSourceConfig:
    values = {
        "type": "pi_web_api",
        "server": "pi-archive-01",
        "base_url": pi.base_url,
        "auth_type": "basic",
        "username": "svc_processcraft",
        "password_env": "PI_TEST_PASSWORD",
        "timezone": "America/Sao_Paulo",
        "timeout_seconds": 5,
        "tags": TAGS,
        "mapping": MAPPING,
    }
    values.update(overrides)
    return DataSourceConfig(**values)


def _last_hours(hours: float) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None).floor("s")
    return end - pd.Timedelta(hours=hours), end


def test_recorded_read_keeps_events_labels_and_step_boundary(pi):
    source = PiWebApiSource(_config(pi))
    start, end = _last_hours(6)
    frame = source.read_range(start, end, 5)

    assert source.failed_tags == []
    assert {"Feed.FPV", "Feed.FSP", "FIC4241004O", "Feed.MODE", "PIC4241048"} <= set(frame.columns)
    # Naive times are plant time: the frame covers the asked window, not one shifted by UTC.
    assert frame.index.min() == start
    assert frame.index.max() <= end
    # SP and MODE change rarely; their last value before the window is placed at its start.
    assert frame["Feed.FSP"].loc[start] in {50.0, 55.0}
    assert frame["Feed.MODE"].dropna().isin({"AUTO", "MAN"}).all()
    # Recorded means irregular events, not a grid.
    assert frame["Feed.FPV"].dropna().index.to_series().diff().nunique() > 3


def test_bad_values_and_system_states_become_gaps(pi):
    source = PiWebApiSource(_config(pi, tags=["PIC4241048"]))
    start, end = _last_hours(96)
    values = source.read_range(start, end, 5)["PIC4241048"]
    assert values.isna().sum() > 100
    assert not values.astype(str).str.contains("Bad Input").any()
    assert normalize_value({"Name": "I/O Timeout", "Value": 246, "IsSystem": True}) is None
    assert normalize_value({"Name": "MAN", "Value": 0, "IsSystem": False}) == "MAN"
    assert normalize_value(float("nan")) is None
    assert normalize_value(12.5, good=False) is None


def test_recorded_pages_past_the_per_call_limit(monkeypatch):
    monkeypatch.setenv("PI_TEST_PASSWORD", "segredo")
    with FakePi(max_items=200) as pi:
        source = PiWebApiSource(_config(pi, page_size=200, tags=["FIC4241004"]))
        start, end = _last_hours(12)
        values = source.read_range(start, end, 5, include_boundary=False)["Feed.FPV"]
        expected = [
            stamp
            for stamp, _, _ in pi.tags["FIC4241004"]
            if source._utc(start) <= stamp <= source._utc(end)
        ]
        assert len(values) == len(expected) > 2000
        assert pi.calls["recorded"] >= len(expected) // 200


def test_transient_errors_are_retried(pi):
    pi.fail_next["recorded"] = 2
    source = PiWebApiSource(_config(pi, tags=["FIC4241004"]))
    start, end = _last_hours(1)
    frame = source.read_range(start, end, 5, include_boundary=False)
    assert not frame.empty
    assert pi.calls["recorded"] == 3


def test_persistent_errors_name_the_status(pi):
    pi.fail_next["recorded"] = 10
    source = PiWebApiSource(_config(pi, tags=["FIC4241004"], retries=1))
    start, end = _last_hours(1)
    with pytest.raises(RuntimeError, match="503"):
        source.read_range(start, end, 5, include_boundary=False)


def test_refused_path_web_id_falls_back_to_point_lookup_once(monkeypatch):
    monkeypatch.setenv("PI_TEST_PASSWORD", "segredo")
    with FakePi(path_web_ids=False) as pi:
        source = PiWebApiSource(_config(pi))
        start, end = _last_hours(2)
        source.read_range(start, end, 5)
        assert source.failed_tags == []
        assert pi.calls["points"] == len(TAGS)
        source.read_range(start, end, 5)
        assert pi.calls["points"] == len(TAGS)


def test_missing_tag_is_reported_without_sinking_the_others(pi):
    source = PiWebApiSource(_config(pi, tags=["FIC4241004", "XYZ999"]))
    start, end = _last_hours(1)
    frame = source.read_range(start, end, 5)
    assert "Feed.FPV" in frame.columns
    assert source.failed_tags[0][0] == "XYZ999"
    assert "tag XYZ999 does not exist on server pi-archive-01" in source.failed_tags[0][1]


def test_interpolated_mode_is_regular_and_chunked(monkeypatch):
    monkeypatch.setenv("PI_TEST_PASSWORD", "segredo")
    with FakePi(max_items=150) as pi:
        source = PiWebApiSource(
            _config(pi, read_mode="interpolated", page_size=150, tags=["FIC4241004"])
        )
        start, end = _last_hours(6)
        values = source.read_range(start, end, 60)["Feed.FPV"]
        assert values.index.to_series().diff().dropna().eq(pd.Timedelta(seconds=60)).all()
        assert len(values) == 6 * 60 + 1
        assert pi.calls["interpolated"] >= 3


def test_connection_message_names_server_and_user(pi):
    message = PiWebApiSource(_config(pi)).test_connection()
    assert "PI-ARCHIVE-01" in message.upper()
    assert "EXAMPLE\\svc_processcraft" in message


def test_wrong_server_and_wrong_password_are_explained(pi, monkeypatch):
    with pytest.raises(PiError, match="does not appear in PI Web API"):
        PiWebApiSource(_config(pi, server="outro")).test_connection()
    monkeypatch.setenv("PI_TEST_PASSWORD", "errada")
    with pytest.raises(PiError, match="refused the basic authentication.*Negotiate"):
        PiWebApiSource(_config(pi)).test_connection()


def test_unreachable_host_is_explained():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = DataSourceConfig(
        type="pi_web_api",
        server="pi-archive-01",
        base_url=f"http://127.0.0.1:{port}/piwebapi",
        auth_type="basic",
        username="svc",
        password_env="HOME",
        retries=0,
        tags=["X"],
    )
    with pytest.raises(PiError, match="No connection to 127.0.0.1"):
        PiWebApiSource(config).test_connection()


def test_signals_carry_unit_description_and_type(pi):
    signals = {s.tag: s for s in PiWebApiSource(_config(pi)).list_signals()}
    assert signals["FIC4241004"].unit == "m3/h"
    assert signals["FIC4241004"].description == "Descrição de FIC4241004"
    assert signals["FIC4241004M"].data_type == "text"


def test_cached_pi_source_feeds_a_loop_frame(pi, tmp_path):
    config = _config(pi)
    source = build_cached_source(config, Database(tmp_path / "cache.sqlite"))
    assert isinstance(source.cache, HistoryCache)
    start, end = _last_hours(4)
    source.read_range(start, end, 5)
    calls = pi.calls["recorded"]
    raw = source.read_range(start + pd.Timedelta(hours=1), end, 5)
    assert pi.calls["recorded"] == calls  # served from the cache
    loop = LoopConfig(
        loop_id="FIC-4241004",
        name="Vazão de carga",
        signals={"pv": "Feed.FPV", "sp": "Feed.FSP", "op": "FIC4241004O", "mode": "Feed.MODE"},
    )
    frame = build_loop_frame(raw, loop, 5)
    assert len(frame) > 500
    assert frame[["pv", "sp", "op"]].notna().mean().min() > 0.99
    assert set(frame["mode"].dropna()) <= {"AUTO", "MAN"}


def test_path_web_id_convention():
    assert make_web_id("pi-archive-01", "PIC4241048") == make_web_id("PI-ARCHIVE-01", "pic4241048")
    assert make_web_id("pi-archive-01", "PIC4241048").startswith("P1DP")


def _scenario(pi: FakePi, tmp_path):
    import json

    from processcraft.config import load_scenario

    data = {
        "name": "pi_teste",
        "display_name": "PI de teste",
        "source": _config(pi).model_dump(),
        "storage": {"sqlite_path": str(tmp_path / "w.sqlite")},
        "loops": [
            {
                "loop_id": "FIC-4241004",
                "name": "Vazão de carga",
                "signals": {
                    "pv": "Feed.FPV",
                    "sp": "Feed.FSP",
                    "op": "FIC4241004O",
                    "mode": "Feed.MODE",
                },
            },
            {"loop_id": "PIC-9999", "name": "Sem tag", "signals": {"pv": "PIC9999"}},
        ],
    }
    path = tmp_path / "pi.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path, load_scenario(path, project_root=tmp_path)


def test_pi_check_walks_every_step_and_names_what_to_fix(pi, tmp_path):
    from processcraft.industrial_data.pi_check import FAIL, OK, run_check

    _, scenario = _scenario(pi, tmp_path)
    report = run_check(scenario, hours=6)
    steps = {check.step: check for check in report.checks}
    assert steps["DNS"].status == OK
    assert steps["Network"].status == OK
    assert "PI-ARCHIVE-01" in steps["PI Web API"].detail.upper()
    assert "svc_processcraft" in steps["User"].detail
    assert steps["Tags"].status == OK, report.text()
    loops = {row["loop"]: row for row in report.loops}
    assert loops["FIC-4241004"]["status"] == OK
    assert loops["FIC-4241004"]["pv"] == "100%"
    assert loops["PIC-9999"]["status"] == FAIL
    assert "PV PIC9999" in loops["PIC-9999"]["note"]
    assert report.failed
    assert "## Loops" in report.markdown()


def test_pi_check_cli_writes_report_and_fails_on_missing_tag(pi, tmp_path, capsys):
    from processcraft.cli import main

    path, _ = _scenario(pi, tmp_path)
    out = tmp_path / "relatorio.md"
    code = main(["pi", "check", "--scenario", str(path), "--hours", "2", "--report", str(out)])
    assert code == 1
    assert "Loops with problems:" in capsys.readouterr().out
    assert out.read_text(encoding="utf-8").startswith("# PI diagnosis · PI de teste")
