"""The binary answer of ``POST /api/v1/series`` (``plantcraft_sdk.wire``) and the client's use."""

from __future__ import annotations

import httpx
import numpy as np
import pandas as pd
import pytest

from plantcraft_sdk import wire
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.contract import series_to_pandas

TIMES = np.array([1_760_000_000_000, 1_760_000_000_250, 1_760_000_001_000], dtype=np.int64)


def answer() -> bytes:
    writer = wire.BinaryWriter()
    writer.numbers("plant:A", "number", TIMES, np.array([1.5, np.nan, -2.0]))
    writer.labels("plant:MODE", "text", TIMES[:2], ["AUTO", None])
    writer.numbers("plant:EMPTY", "number", np.zeros(0, np.int64), np.zeros(0))
    writer.numbers("plant:B", "number", TIMES[:1], np.array([7.0]), {"run_at": None})
    return writer.body(
        [{"signal": "missing", "status": 404, "detail": "Signal missing not found."}]
    )


def test_a_binary_answer_reads_back():
    series, errors = wire.read_binary(answer())
    assert [item["signal"] for item in series] == [
        "plant:A",
        "plant:MODE",
        "plant:EMPTY",
        "plant:B",
    ]
    assert errors[0]["status"] == 404
    assert np.array_equal(series[0]["t"], TIMES)
    assert np.array_equal(series[0]["v"], [1.5, np.nan, -2.0], equal_nan=True)
    assert series[1]["v"] == ["AUTO", None] and series[3]["run_at"] is None
    assert len(series[2]["t"]) == 0


def test_binary_and_json_give_the_same_pandas():
    series, _ = wire.read_binary(answer())
    as_json = {
        "signal": "plant:A",
        "kind": "number",
        "t": [
            "2025-10-09T08:53:20+00:00",
            "2025-10-09T08:53:20.250000+00:00",
            "2025-10-09T08:53:21+00:00",
        ],
        "v": [1.5, None, -2.0],
    }
    pd.testing.assert_series_equal(wire.binary_to_pandas(series[0]), series_to_pandas(as_json))
    text = wire.binary_to_pandas(series[1])
    assert text.dtype == object and list(text) == ["AUTO", None]


@pytest.mark.parametrize("bad", [b"", b"JSON", b"PCS1\xff\xff\x00\x00{}", answer()[:-8]])
def test_broken_answers_are_refused(bad):
    with pytest.raises(wire.WireError):
        wire.read_binary(bad)


def test_the_client_asks_for_it_only_when_the_historian_writes_it():
    seen: list[str] = []

    def historian(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/reads"):
            return httpx.Response(200, json={"api": 1, "formats": ["pcs1"]})
        seen.append(request.headers["accept"])
        if wire.MEDIA_TYPE in request.headers["accept"]:
            return httpx.Response(200, content=answer(), headers={"content-type": wire.MEDIA_TYPE})
        return httpx.Response(200, json={"series": [], "errors": []})

    http = httpx.Client(transport=httpx.MockTransport(historian))
    client = PlantCraftClient(
        "http://pc.test", "token", http_client=http, historian_url="http://h.test/hist"
    )
    columns, errors = client.series_many_pandas(
        ["plant:A", "plant:MODE", "plant:EMPTY", "plant:B", "missing"]
    )
    assert list(columns) == ["plant:A", "plant:MODE", "plant:EMPTY", "plant:B"]
    assert columns["plant:A"].index.tz is not None and errors[0]["signal"] == "missing"
    # series_many (lists of ISO texts for its callers) keeps JSON
    client.series_many(["plant:A"])
    client.binary_reads = False
    client.series_many_pandas(["plant:A"])
    assert [wire.MEDIA_TYPE in item for item in seen] == [True, False, False]


def test_quality_is_asked_for_only_when_wanted_and_kept_on_the_pandas_series():
    bodies: list[bytes] = []
    changes = [{"t": "2025-10-09T08:53:20.250000+00:00", "quality": "uncertain"}]

    def historian(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/reads"):
            return httpx.Response(200, json={"api": 1, "formats": ["pcs1"]})
        bodies.append(request.content)
        writer = wire.BinaryWriter()
        extra = {"quality": changes} if b'"quality"' in request.content else None
        writer.numbers("plant:A", "number", TIMES, np.array([1.5, np.nan, -2.0]), extra)
        return httpx.Response(
            200, content=writer.body([]), headers={"content-type": wire.MEDIA_TYPE}
        )

    http = httpx.Client(transport=httpx.MockTransport(historian))
    client = PlantCraftClient(
        "http://pc.test", "token", http_client=http, historian_url="http://h.test/hist"
    )
    plain, _ = client.series_many_pandas(["plant:A"])
    checked, _ = client.series_many_pandas(["plant:A"], quality=True)
    assert b"quality" not in bodies[0] and b'"quality":true' in bodies[1].replace(b" ", b"")
    assert "quality" not in plain["plant:A"].attrs
    assert checked["plant:A"].attrs["quality"] == changes
    as_json = {"signal": "plant:A", "t": [], "v": [], "quality": changes}
    assert series_to_pandas(as_json).attrs["quality"] == changes


def test_a_grid_read_can_bring_each_steps_extremes():
    from datetime import datetime, timedelta, timezone

    from plantcraft_sdk.testing import FakePlantCraft

    fake = FakePlantCraft()
    client = fake.client()
    signal = next(item["id"] for item in client.signals() if item.get("kind") == "number")
    end = datetime(2026, 10, 30, tzinfo=timezone.utc)
    start = end - timedelta(hours=2)
    plain = client.series_many([signal], start, end, 600)["series"][0]
    banded = client.series_many([signal], start, end, 600, extremes=True)["series"][0]
    assert "low" not in plain and banded["v"] == plain["v"]
    assert len(banded["low"]) == len(banded["high"]) == len(banded["t"]) == 12
    assert all(lo <= mean <= hi for lo, mean, hi in zip(banded["low"], banded["v"], banded["high"]))
    # Without a step there is nothing to band.
    raw = client.series_many([signal], start, start + timedelta(minutes=5), extremes=True)
    assert "low" not in raw["series"][0]
