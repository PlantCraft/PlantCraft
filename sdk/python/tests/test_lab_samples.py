"""A laboratory signal's samples come from the Historian (``lab_samples``)."""

from __future__ import annotations

import httpx

from plantcraft_sdk.client import PlantCraftClient

SAMPLE = {"sampled_at": "2026-10-31T06:00:00.000Z", "value": 412.0, "status": "entered"}


def _client(handler, historian: str | None = "http://hist.test/hist") -> PlantCraftClient:
    return PlantCraftClient(
        "http://x.test",
        "token",
        backoff=0,
        historian_url=historian or "",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_samples_are_read_from_the_historian_with_the_window():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json={"signal": "laboratory:VISC-101", "samples": [SAMPLE]})

    client = _client(handler)
    client._historian_serves = lambda historian: True  # what /api/v1/reads answers
    found = client.lab_samples("laboratory:VISC-101", "2026-10-30T00:00:00Z", None)
    assert found == [SAMPLE]
    url = seen[-1]
    assert url.host == "hist.test" and url.raw_path.startswith(
        b"/hist/api/v1/lab/laboratory%3AVISC-101"
    )
    assert url.params.get("start") == "2026-10-30T00:00:00Z" and "end" not in url.params


def test_no_historian_or_an_unknown_signal_gives_no_samples():
    def missing(request):
        return httpx.Response(404, json={"detail": "not found"})

    assert _client(missing, historian=None).lab_samples("laboratory:X") == []
    client = _client(missing)
    client._historian_serves = lambda historian: True
    assert client.lab_samples("laboratory:X") == []
