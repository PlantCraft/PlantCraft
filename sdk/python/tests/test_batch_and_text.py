"""SDK 0.2: batch reads, text signals, the MockTransport fake, recorded ends and audit tags."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import pandas as pd
import pytest

from plantcraft_sdk.client import BadRequest, NotFound, PlantCraftClient
from plantcraft_sdk.contract import (
    MAX_BATCH_SIGNALS,
    iso,
    iso_many,
    parse_times,
    series_to_pandas,
    text_label,
)
from plantcraft_sdk.testing import BASE_URL, FakePlantCraft

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
HOUR = NOW - timedelta(hours=1)


def _mode_fake(**options) -> FakePlantCraft:
    index = pd.date_range(NOW - timedelta(hours=2), NOW - timedelta(minutes=30), freq="10min")
    labels = ["AUTO", "AUTO", "MAN", "MAN", "AUTO", "MAN", "AUTO", "AUTO", "MAN", "AUTO"]
    numbers = pd.Series(np.arange(len(index), dtype=float), index=index)
    return FakePlantCraft(
        series={"fake:FIC-101.MODE": pd.Series(labels, index=index), "fake:FIC-101.PV": numbers},
        **{"now": NOW, **options},
    )


def test_series_many_returns_every_signal_in_order_with_errors_listed():
    fake = FakePlantCraft(now=NOW)
    client = fake.client("engineer")
    fake.requests = 0
    batch = client.series_many(
        ["fake:LIC-102.PV", "NOPE", "fake:FIC-101.PV", "fake:LIC-102.PV"], HOUR, NOW
    )
    assert fake.requests == 1
    assert [item["signal"] for item in batch["series"]] == ["fake:LIC-102.PV", "fake:FIC-101.PV"]
    assert all(set(item) == {"signal", "kind", "t", "v"} for item in batch["series"])
    assert all(item["kind"] == "number" and len(item["t"]) == 361 for item in batch["series"])
    assert batch["errors"] == [{"signal": "NOPE", "status": 404, "detail": "Signal not found."}]
    single = client.series("fake:FIC-101.PV", HOUR, NOW)
    assert batch["series"][1] == single


def test_series_many_pandas_and_frame():
    client = FakePlantCraft(now=NOW).client("engineer")
    columns, errors = client.series_many_pandas(
        ["fake:FIC-101.PV", "fake:FIC-101.SP"], HOUR, NOW, 60
    )
    assert errors == [] and set(columns) == {"fake:FIC-101.PV", "fake:FIC-101.SP"}
    assert (
        len(columns["fake:FIC-101.PV"]) == 60 and str(columns["fake:FIC-101.PV"].index.tz) == "UTC"
    )
    frame = client.series_frame(["fake:FIC-101.PV", "fake:FIC-101.SP"], HOUR, NOW, 300)
    assert list(frame.columns) == ["fake:FIC-101.PV", "fake:FIC-101.SP"] and len(frame) == 12
    with pytest.raises(NotFound):
        client.series_frame(["fake:FIC-101.PV", "NOPE"], HOUR, NOW)


def test_a_full_batch_postpones_signals_and_the_client_asks_again():
    fake = FakePlantCraft(now=NOW)
    fake.batch_points = 400  # one 361-point series per request
    client = fake.client("engineer")
    raw = client._send(
        "POST",
        "/api/v1/series",
        json={
            "signals": ["fake:FIC-101.PV", "fake:FIC-101.SP"],
            "start": iso(HOUR),
            "end": iso(NOW),
        },
    )
    assert [item["signal"] for item in raw["series"]] == ["fake:FIC-101.PV"]
    assert [(item["signal"], item["status"]) for item in raw["errors"]] == [
        ("fake:FIC-101.SP", 413)
    ]
    fake.requests = 0
    batch = client.series_many(["fake:FIC-101.PV", "fake:FIC-101.SP", "fake:FIC-101.OP"], HOUR, NOW)
    assert [item["signal"] for item in batch["series"]] == [
        "fake:FIC-101.PV",
        "fake:FIC-101.SP",
        "fake:FIC-101.OP",
    ]
    assert batch["errors"] == [] and fake.requests == 3


def test_more_than_500_signals_take_several_requests():
    signals = [
        {
            "id": f"T{n}",
            "name": "",
            "source": "fake",
            "unit": "",
            "description": "",
            "low": None,
            "high": None,
        }
        for n in range(MAX_BATCH_SIGNALS + 20)
    ]
    fake = FakePlantCraft(signals=signals, now=NOW)
    client = fake.client("engineer")
    fake.requests = 0
    batch = client.series_many([item["id"] for item in signals], NOW - timedelta(minutes=1), NOW)
    assert len(batch["series"]) == len(signals) and fake.requests == 2


@pytest.mark.parametrize(
    "body",
    [
        {"signals": []},
        {"signals": ["x"] * (MAX_BATCH_SIGNALS + 1)},
        {"signals": [1, 2]},
        {"signals": ["fake:FIC-101.PV"], "step": -1},
        {"signals": ["fake:FIC-101.PV"], "start": "yesterday"},
        {"signals": ["fake:FIC-101.PV"], "step": True},
        ["fake:FIC-101.PV"],
    ],
)
def test_batch_requests_outside_the_contract_are_422(body):
    client = FakePlantCraft(now=NOW).client("engineer")
    with pytest.raises(BadRequest) as error:
        client._send("POST", "/api/v1/series", json=body)
    assert error.value.status_code == 422


def test_a_dead_source_fails_its_signals_not_the_batch():
    fake = FakePlantCraft(now=NOW)
    fake.broken["fake:FIC-101.SP"] = "timeout"
    batch = fake.client("engineer").series_many(["fake:FIC-101.PV", "fake:FIC-101.SP"], HOUR, NOW)
    assert [item["signal"] for item in batch["series"]] == ["fake:FIC-101.PV"]
    assert batch["errors"][0]["status"] == 502 and "timeout" in batch["errors"][0]["detail"]


def test_an_older_processcraft_without_the_batch_route_is_read_one_signal_at_a_time():
    fake = FakePlantCraft(now=NOW)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/api/v1/series":
            return httpx.Response(404, json={"detail": "Not Found"})
        return fake._httpx(request)

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    client = PlantCraftClient(BASE_URL, fake.token("engineer"), http_client=http)
    batch = client.series_many(["fake:FIC-101.PV", "NOPE"], HOUR, NOW)
    assert [item["signal"] for item in batch["series"]] == ["fake:FIC-101.PV"]
    assert batch["errors"][0]["signal"] == "NOPE" and batch["errors"][0]["status"] == 404
    client.series_many(["fake:FIC-101.SP"], HOUR, NOW)
    assert seen.count(("POST", "/api/v1/series")) == 1  # remembered


def test_text_signals_are_labels_with_their_kind():
    fake = _mode_fake()
    client = fake.client("engineer")
    assert client.signal("fake:FIC-101.MODE")["kind"] == "text"
    assert client.signal("fake:FIC-101.PV")["kind"] == "number"
    start = NOW - timedelta(hours=2)
    recorded = client.series("fake:FIC-101.MODE", start, NOW)
    assert recorded["kind"] == "text" and recorded["v"][:3] == ["AUTO", "AUTO", "MAN"]
    assert len(recorded["v"]) == 10
    stepped = client.series("fake:FIC-101.MODE", start - timedelta(minutes=30), NOW, step=1800)
    # The last label of each half hour; none before the file starts.
    assert stepped["v"] == [None, "MAN", "MAN", "MAN", "AUTO"]
    values = series_to_pandas(recorded)
    assert values.dtype == object and values.iloc[2] == "MAN"
    last = client.value("fake:FIC-101.MODE", "last", "1h")
    assert last["value"] == "AUTO" and last["at"] == iso(NOW - timedelta(minutes=30))
    with pytest.raises(BadRequest):
        client.value("fake:FIC-101.MODE", "mean", "1h")
    columns, _ = client.series_many_pandas(["fake:FIC-101.MODE", "fake:FIC-101.PV"], start, NOW)
    assert columns["fake:FIC-101.MODE"].tolist()[-1] == "AUTO"
    assert columns["fake:FIC-101.PV"].dtype == float


def test_a_signal_can_declare_its_kind():
    signals = [
        {
            "id": "M",
            "name": "m",
            "source": "fake",
            "unit": "",
            "description": "",
            "low": None,
            "high": None,
            "kind": "text",
        }
    ]
    client = FakePlantCraft(signals=signals, now=NOW).client()
    assert client.series("M", HOUR, NOW, step=600)["v"] == ["AUTO"] * 6


def test_recorded_series_end_at_their_last_sample_not_at_now():
    """As PlantCraft does for a recorded file (value windows and the default series end)."""

    fake = _mode_fake(now=None)  # "now" is today; the file ended long ago
    client = fake.client("engineer")
    last = client.value("fake:FIC-101.PV", "last", "1h")
    assert last["value"] == 9.0 and last["at"] == iso(NOW - timedelta(minutes=30))
    default = client.series("fake:FIC-101.PV")
    assert default["t"][-1] == iso(NOW - timedelta(minutes=30))
    live = FakePlantCraft(now=NOW).client().value("fake:FIC-101.PV", "last", "1h")
    assert live["at"] == iso(NOW)


def test_the_fake_answers_alike_over_mock_transport_and_asgi():
    fake = _mode_fake()
    mock, asgi = fake.client("engineer"), fake.client("engineer", transport="asgi")
    assert isinstance(fake.http_client(), httpx.Client)
    assert type(fake.http_client()).__module__.startswith("httpx")
    for read in (
        lambda c: c.me(),
        lambda c: c.signals(q="feed"),
        lambda c: c.series("fake:FIC-101.MODE", NOW - timedelta(hours=2), NOW),
        lambda c: c.series_many(["fake:FIC-101.PV", "NOPE"], NOW - timedelta(hours=2), NOW, 600),
        lambda c: c.value("fake:FIC-101.PV", "mean", "2h"),
    ):
        assert read(mock) == read(asgi)
    with pytest.raises(NotFound):
        asgi.signal("NOPE")
    browser = fake.http_client()
    browser.cookies.set("processcraft_session", "engineer")
    renewed = browser.post("/api/v1/auth/token")
    assert renewed.status_code == 200 and "processcraft_token=" in renewed.headers["set-cookie"]


def test_audits_carry_the_app_id_when_the_client_knows_it():
    fake = FakePlantCraft(now=NOW)
    fake.client("engineer").audit("a", "x")
    fake.client("engineer", app="linkcraft").audit("b", "x")
    service = fake.client(None, app="linkcraft", key="test-app-key")
    service.audit("d", "x")
    PlantCraftClient(BASE_URL, service.token(), http_client=fake.http_client()).audit("e", "x")
    fake.client("engineer").with_token(fake.token("operator"), app="linkcraft").audit("f", "x")
    fake.client("engineer").audit("g", "x", app="dashcraft")
    assert [(item["action"], item["app"]) for item in fake.audit_log] == [
        ("a", None),
        ("b", "linkcraft"),
        ("d", "linkcraft"),
        ("e", "linkcraft"),
        ("f", "linkcraft"),
        ("g", "dashcraft"),
    ]


def test_iso_many_and_parse_times_match_the_one_by_one_versions():
    whole = pd.date_range("2026-01-01", periods=5, freq="10s", tz="UTC")
    fractional = pd.DatetimeIndex(["2026-01-01T00:00:00.5Z", "2026-01-01T00:00:01Z"])
    naive = pd.date_range("2026-01-01", periods=3, freq="1h")
    millis = pd.DatetimeIndex(["2026-01-01T00:00:00.123Z", "2026-01-01T00:00:01Z", "NaT"])
    nanos = pd.DatetimeIndex(["2026-01-01T00:00:00.000000001Z"])
    for index in (
        whole,
        fractional,
        naive,
        whole.tz_convert("America/Sao_Paulo"),
        millis[:2],
        nanos,
    ):
        assert iso_many(index) == [iso(stamp) for stamp in index]
        assert (parse_times(iso_many(index)) == pd.to_datetime(index, utc=True)).all()
    assert iso_many([]) == []
    mixed = ["2026-01-01T00:00:00-03:00", "2026-01-01T03:00:00+00:00"]
    assert parse_times(mixed)[0] == parse_times(mixed)[1]


@pytest.mark.parametrize(
    ("value", "label"),
    [
        ("MAN", "MAN"),
        (" auto ", "auto"),
        (1.0, "1"),
        (2.5, "2.5"),
        (np.int64(3), "3"),
        (None, None),
        (float("nan"), None),
        ("", None),
        (True, "True"),
    ],
)
def test_text_labels(value, label):
    assert text_label(value) == label


def test_series_reads_wait_longer_than_other_calls():
    """A busy Historian answers a series late: the client waits for it instead of asking again
    (Analytics rounds failed with "timed out" on the demo, 2026-10-29)."""

    from plantcraft_sdk.client import DEFAULT_TIMEOUT, SERIES_TIMEOUT

    waited: dict[str, float] = {}

    def answer(request: httpx.Request) -> httpx.Response:
        waited[f"{request.method} {request.url.path}"] = request.extensions["timeout"]["read"]
        if request.url.path.endswith("/series") and request.method == "POST":
            return httpx.Response(200, json={"series": [], "errors": []})
        if request.url.path.endswith("/series"):
            return httpx.Response(200, json={"signal": "A", "kind": "number", "t": [], "v": []})
        return httpx.Response(200, json={"id": "A"})

    client = PlantCraftClient(
        BASE_URL, token="t", http_client=httpx.Client(transport=httpx.MockTransport(answer))
    )
    client.series_many(["A", "B"], HOUR, NOW)
    client.series("A", HOUR, NOW)
    client.signal("A")
    assert SERIES_TIMEOUT > 75 > DEFAULT_TIMEOUT
    assert waited["POST /api/v1/series"] == SERIES_TIMEOUT
    assert waited["GET /api/v1/signals/A/series"] == SERIES_TIMEOUT
    assert waited["GET /api/v1/signals/A"] != SERIES_TIMEOUT  # other calls keep the client's
