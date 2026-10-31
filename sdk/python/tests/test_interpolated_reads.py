"""H5: the client asks for interpolated grids and summaries, and the contract checks their
options as PlantCraft and the Historian do."""

from __future__ import annotations

import json

import httpx
import pytest

from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.contract import (
    SAMPLINGS,
    TOTAL_PER,
    ContractError,
    sampling_options,
    total_per,
)


def _client(seen: list[httpx.Request]) -> PlantCraftClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/summary"):
            return httpx.Response(200, json={"signal": "p:FI-1", "count": 3, "total": 45.0})
        if request.method == "POST":
            return httpx.Response(200, json={"series": [], "errors": []})
        return httpx.Response(200, json={"signal": "p:FI-1", "kind": "number", "t": [], "v": []})

    return PlantCraftClient(
        "http://x.test",
        "token",
        backoff=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_the_client_sends_sampling_and_max_gap_only_when_asked():
    seen: list[httpx.Request] = []
    client = _client(seen)
    client.series("p:FI-1", "2026-10-19T00:00:00Z", None, 60, sampling="interpolated", max_gap=600)
    params = dict(seen[-1].url.params)
    assert params["sampling"] == "interpolated" and params["max_gap"] == "600"
    client.series("p:FI-1", None, None, 60)
    assert "sampling" not in seen[-1].url.params
    client.series_many(["p:FI-1"], None, None, 60, sampling="interpolated", max_gap=30)
    body = json.loads(seen[-1].content)
    assert body["sampling"] == "interpolated" and body["max_gap"] == 30


def test_the_client_reads_a_summary():
    seen: list[httpx.Request] = []
    answer = _client(seen).summary("p:FI-1", "2026-10-19T00:00:00Z", per="min")
    assert answer["total"] == 45.0
    assert seen[-1].url.path == "/api/v1/signals/p:FI-1/summary"
    assert dict(seen[-1].url.params)["per"] == "min"


def test_sampling_options_and_total_units():
    assert SAMPLINGS == ("average", "interpolated")
    assert sampling_options(None, None, None) == ("average", None)
    assert sampling_options("Interpolated", 60, 300) == ("interpolated", 300)
    for bad in (
        ("interpolated", None, None),  # no step
        ("nearest", 60, None),
        ("average", 60, 300),  # max_gap is for interpolated reads
        ("interpolated", 60, 0),
        ("interpolated", 60, float("nan")),
    ):
        with pytest.raises(ContractError):
            sampling_options(*bad)
    assert total_per(None) == ("h", 3600.0) and total_per("d") == ("d", TOTAL_PER["d"])
    with pytest.raises(ContractError):
        total_per("week")
