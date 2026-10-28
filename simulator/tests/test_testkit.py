"""The source test kit: the plant it publishes, its CSV files, Modbus words and PI Web API."""

from __future__ import annotations

import base64
import json
import struct
import urllib.error
import urllib.request
from datetime import UTC, datetime

import pytest

from simcraft.testkit import csv_files, modbus, plant
from simcraft.testkit.piwebapi import USER, PiWebApi


@pytest.fixture(scope="module")
def series():
    return plant.history(minutes=3)


def test_the_plant_is_the_same_for_the_same_arguments(series):
    assert plant.history(minutes=3) == series
    assert {tag.rsplit(".", 1)[1] for tag in series} == {"PV", "SP", "OP", "MODE"}
    assert series["FIC-101.MODE"].kind == "text" and series["FIC-101.PV"].kind == "number"
    assert all(item.times == sorted(item.times) for item in series.values())


def test_csv_files_hold_every_layout_and_known_errors(tmp_path, series):
    expected = csv_files.write(tmp_path, series)
    assert json.loads((tmp_path / "expected.json").read_text()) == expected
    names = {"wide-iso.csv", "wide-offset.csv", "wide-epoch.csv", "wide-excel-br.csv", "long.csv"}
    assert names | {"errors.csv"} == set(expected)
    excel = (tmp_path / "wide-excel-br.csv").read_text().splitlines()
    assert excel[0].startswith("time;") and "," in excel[1]
    assert expected["errors.csv"]["error_lines"] == [3, 4]


@pytest.mark.parametrize(
    ("data_type", "order", "words"),
    [
        ("FLOAT32-IEEE", "ABCD", [0x4049, 0x0FDB]),
        ("FLOAT32-IEEE", "CDAB", [0x0FDB, 0x4049]),
        ("FLOAT32-IEEE", "BADC", [0x4940, 0xDB0F]),
        ("FLOAT32-IEEE", "DCBA", [0xDB0F, 0x4940]),
    ],
)
def test_modbus_words_follow_telegraf_byte_orders(data_type, order, words):
    assert modbus.words(3.14159265, data_type, order, 1.0) == words


def test_modbus_64_bit_and_scaled_integers_round_trip(series):
    found = modbus.words(-12.5, "INT16", "AB", 0.1)
    assert struct.unpack(">h", struct.pack(">H", *found))[0] == -125
    pairs = modbus.words(1.5, "FLOAT64-IEEE", "GHEFCDAB", 1.0)
    assert struct.unpack(">d", struct.pack(">4H", *reversed(pairs)))[0] == 1.5
    names = {item["name"] for item in modbus.options()["registers"]}
    assert names == set(modbus.expected(series))


def _get(url: str, user=USER):
    request = urllib.request.Request(url, headers={"X-Requested-With": "XMLHttpRequest"})
    token = base64.b64encode(":".join(user).encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=10) as answer:
        return json.load(answer)


def test_pi_web_api_answers_recorded_values_and_states(series, monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    with PiWebApi(series) as pi:
        point = _get(f"{pi.base_url}/points?path=\\\\PISRV\\FIC-101.MODE")
        assert point["PointType"] == "Digital"
        start, end = series["FIC-101.MODE"].times[0], series["FIC-101.MODE"].times[-1]
        stamps = [datetime.fromtimestamp(ms / 1000, UTC).isoformat() for ms in (start, end)]
        items = _get(
            f"{pi.base_url}/streams/F1DPFIC-101.MODE/recorded?startTime={stamps[0]}&endTime={stamps[1]}".replace(
                "+", "%2B"
            )
        )["Items"]
        assert [item["Value"]["Name"] for item in items] == series["FIC-101.MODE"].values
        pi.fail_next["dataservers"] = 1
        with pytest.raises(urllib.error.HTTPError, match="503"):
            _get(f"{pi.base_url}/dataservers")
        assert _get(f"{pi.base_url}/dataservers")["Items"][0]["Name"] == "pisrv"
        with pytest.raises(urllib.error.HTTPError, match="401"):
            _get(f"{pi.base_url}/dataservers", user=("x", "y"))
