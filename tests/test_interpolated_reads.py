"""H5 in API v1: interpolated reads (``sampling``, ``max_gap``) and ``GET .../summary`` are
forwarded to the Historian as asked, and refused clearly where the data layer has none."""
# ruff: noqa: F811 (the fixture "world" of tests/test_apps_api.py, imported to share it)

from __future__ import annotations

import json
from urllib.parse import quote

import httpx

from plantcraft.platform.datalayer.histcraft import HistCraftDataLayer
from tests.test_apps_api import sign_in
from tests.test_apps_api import world as api_world  # noqa: F401


class _Issuer:
    def issue(self, *_args, **_kwargs):
        return "token", 4_102_444_800.0


def _layer(seen: list[httpx.Request]) -> HistCraftDataLayer:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/summary"):
            return httpx.Response(200, json={"signal": "plant:FI-1", "count": 3, "total": 45.0})
        if request.method == "POST":
            return httpx.Response(200, json={"series": [], "errors": []})
        return httpx.Response(
            200, json={"signal": "plant:FI-1", "kind": "number", "t": [], "v": []}
        )

    client = httpx.Client(transport=httpx.MockTransport(answer))
    return HistCraftDataLayer("http://hist/hist", _Issuer(), http_client=client)


def test_the_historian_layer_forwards_sampling_max_gap_and_summary():
    seen: list[httpx.Request] = []
    layer = _layer(seen)
    assert layer.interpolates
    layer.series(
        "plant:FI-1", "2026-10-19T00:00:00Z", None, 60, sampling="interpolated", max_gap=600
    )
    params = dict(seen[-1].url.params)
    assert params["sampling"] == "interpolated" and params["max_gap"] == "600"
    layer.series("plant:FI-1", None, None, 60)
    assert "sampling" not in seen[-1].url.params and "max_gap" not in seen[-1].url.params
    layer.series_batch(["plant:FI-1"], None, None, 60, sampling="interpolated", max_gap=30.0)
    body = json.loads(seen[-1].content)
    assert body["sampling"] == "interpolated" and body["max_gap"] == 30.0
    layer.series_batch(["plant:FI-1"], None, None, 60)
    assert "sampling" not in json.loads(seen[-1].content)
    found = layer.summary("plant:FI-1", "2026-10-19T00:00:00Z", "2026-10-19T01:00:00Z", "min")
    assert found["total"] == 45.0
    assert seen[-1].url.path == "/hist/api/v1/data/signals/plant:FI-1/summary"
    assert dict(seen[-1].url.params)["per"] == "min"


def test_api_v1_refuses_interpolated_reads_and_summaries_without_the_historian(api_world):
    client = sign_in(api_world.client())
    signal = quote(client.get("/api/v1/signals").json()[0]["id"], safe="")
    series = f"/api/v1/signals/{signal}/series"
    assert client.get(series, params={"step": 60, "sampling": "average"}).status_code == 200
    refused = client.get(series, params={"step": 60, "sampling": "interpolated"})
    assert refused.status_code == 422 and "Historian" in refused.json()["detail"]
    assert client.get(series, params={"step": 60, "sampling": "nearest"}).status_code == 422
    assert client.get(series, params={"step": 60, "max_gap": 60}).status_code == 422
    batch = client.post(
        "/api/v1/series", json={"signals": [signal], "step": 60, "sampling": "interpolated"}
    )
    assert batch.status_code == 422
    summary = client.get(f"/api/v1/signals/{signal}/summary")
    assert summary.status_code == 422 and "Historian" in summary.json()["detail"]


def test_api_v1_hands_interpolated_reads_and_summaries_to_the_historian(api_world, monkeypatch):
    client = sign_in(api_world.client())
    rt = client.app.state.runtime
    signal = client.get("/api/v1/signals").json()[0]["id"]
    asked: dict[str, object] = {}

    def series(signal_id, start, end, step, **options):
        asked["series"] = (signal_id, step, options)
        return {"signal": signal_id, "kind": "number", "t": [], "v": []}

    def summary(signal_id, start, end, per):
        asked["summary"] = (signal_id, start, per)
        return {"signal": signal_id, "count": 0}

    monkeypatch.setattr(rt.datalayer, "interpolates", True, raising=False)
    monkeypatch.setattr(rt.datalayer, "series", series)
    monkeypatch.setattr(rt.datalayer, "series_raw", None, raising=False)
    monkeypatch.setattr(rt.datalayer, "summary", summary, raising=False)
    path = f"/api/v1/signals/{quote(signal, safe='')}"
    answer = client.get(
        f"{path}/series", params={"step": 60, "sampling": "interpolated", "max_gap": 300}
    )
    assert answer.status_code == 200, answer.text
    assert asked["series"][2]["sampling"] == "interpolated"
    assert asked["series"][2]["max_gap"] == 300.0
    found = client.get(f"{path}/summary", params={"start": "2026-10-19T00:00:00Z", "per": "d"})
    assert found.status_code == 200 and asked["summary"] == (signal, "2026-10-19T00:00:00Z", "d")
