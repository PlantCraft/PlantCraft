"""Every route answers junk with a 4xx and a message, never a 500 (AGENTS.md, "Bad data never crashes")."""

from __future__ import annotations

import pytest

from histcraft.archive import codec
from histcraft.archive.compression import Compressor
from tests.test_api import loaded  # noqa: F401 - fixture

JUNK = [
    "",
    " ",
    "%00",
    "x" * 5000,
    "../../etc/passwd",
    "1e309",
    "-1",
    "NaN",
    "null",
    "💥",
    "2026-13-45",
]


@pytest.mark.parametrize("junk", JUNK)
def test_data_routes_never_fail_on_junk(client, loaded, junk):  # noqa: F811
    for params in (
        {"start": junk},
        {"end": junk},
        {"step": junk},
        {"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T01:00:00Z", "step": junk},
    ):
        response = client.get("/hist/api/data/points/TI-100.PV/series", params=params)
        assert response.status_code < 500, (params, response.text)
    for params in ({"agg": junk}, {"window": junk}):
        response = client.get("/hist/api/data/points/TI-100.PV/value", params=params)
        assert response.status_code < 500, (params, response.text)
    response = client.get(f"/hist/api/data/points/{junk}/series")
    assert response.status_code < 500
    assert client.get(f"/hist/api/points/{junk}").status_code < 500
    source = {"id": "junk", "name": "Junk", "endpoint": "opc.tcp://127.0.0.1:1"}
    for key in ("retention_days", "default_scan_seconds", "default_deviation_percent"):
        response = client.post("/hist/api/sources", json={**source, key: junk})
        assert response.status_code < 500, (key, response.text)
    response = client.post("/hist/api/data/series", json={"signals": [junk], "step": 1})
    assert response.status_code < 500


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "x",
        {"points": "x"},
        {"points": [{}]},
        {"points": [{"tag": "\n", "source_id": "plant", "address": "a"}]},
        {"points": [{"tag": "a", "source_id": "plant", "address": "a", "scan_seconds": 0}]},
        {"points": [{"tag": "a", "source_id": "plant", "address": "a", "deviation": -1}]},
    ],
)
def test_point_routes_never_fail_on_junk(client, loaded, body):  # noqa: F811
    assert client.post("/hist/api/points", json=body).status_code < 500
    assert client.patch("/hist/api/points/TI-100.PV", json=body).status_code < 500
    assert client.post("/hist/api/points/delete", json=body).status_code < 500
    assert client.post("/hist/api/sources", json=body).status_code < 500
    assert client.put("/hist/api/settings", json=body).status_code < 500


def test_unknown_point_from_another_source_is_skipped(client, loaded):  # noqa: F811
    answer = client.post(
        "/hist/api/points", json={"points": [{"tag": "a", "source_id": "nope", "address": "a"}]}
    ).json()
    assert answer["added"] == [] and answer["skipped"][0]["reason"] == "unknown source"


def test_requests_route_with_junk_ids(client):
    for junk in ("x", "-1", "99999999999999999999"):
        assert client.get(f"/hist/api/requests/{junk}").status_code < 500


@pytest.mark.parametrize("value", [None, "", "x", float("nan"), [], {}, True, 1e308, -1e308])
def test_compressor_takes_anything(value):
    for kind in ("number", "text"):
        compressor = Compressor(kind=kind)
        compressor.feed(0, 1.0)
        compressor.feed(1000, value)
        compressor.feed(2000, 2.0)


def test_codec_refuses_garbage_cleanly():
    for blob in (b"\x10", b"\x10" + b"\x00" * 50, b"\x11\x78\x9c"):
        with pytest.raises(codec.CodecError):
            codec.decode(blob)
