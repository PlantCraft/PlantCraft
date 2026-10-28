"""The API v1 client against the fake, plus retries, renewals and errors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
import pytest

from plantcraft_sdk.client import (
    BadRequest,
    Forbidden,
    NotFound,
    PlantCraftClient,
    Unauthorized,
    Unavailable,
)
from plantcraft_sdk.testing import FakePlantCraft

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def fake():
    return FakePlantCraft(now=NOW)


def test_every_endpoint(fake):
    client = fake.client("engineer")
    assert client.keys()[0]["kty"] == "OKP"
    assert client.me() == {
        "username": "engineer",
        "name": "Process Engineer",
        "level": "editor",
        "apps": {"linkcraft": "editor"},
        "notebooks_url": None,
    }
    assert client.apps() == [
        {
            "id": "linkcraft",
            "name": "PlantCraft Analytics",
            "url": "/link/",
            "access": "editor",
            "version": "0.1.0",
        }
    ]
    loops = client.assets(kind="loop")
    assert {item["id"] for item in loops} == {"fic-101", "lic-102"}
    assert client.asset("fic-101")["signals"]["pv"] == "fake:FIC-101.PV"
    assert [item["id"] for item in client.signals(q="drum")] == [
        "fake:LIC-102.PV",
        "fake:LIC-102.SP",
        "fake:LIC-102.OP",
    ]
    assert client.signal("fake:FIC-101.PV")["unit"] == "m3/h"
    series = client.series("fake:FIC-101.PV", NOW - timedelta(minutes=10), NOW)
    assert series["signal"] == "fake:FIC-101.PV" and len(series["t"]) == len(series["v"]) == 61
    regular = client.series_pandas("fake:FIC-101.PV", NOW - timedelta(hours=1), NOW, step=60)
    assert len(regular) == 60 and str(regular.index.tz) == "UTC"
    frame = client.series_frame(
        ["fake:FIC-101.PV", "fake:FIC-101.SP"], NOW - timedelta(hours=1), NOW, 300
    )
    assert list(frame.columns) == ["fake:FIC-101.PV", "fake:FIC-101.SP"] and len(frame) == 12
    value = client.value("fake:FIC-101.SP", agg="mean", window="2h")
    assert (
        value["agg"] == "mean"
        and value["window"] == "2h"
        and value["value"] == pytest.approx(52.5, abs=0.1)
    )
    assert client.audit("protocol.edit", "loop:fic-101", {"field": "gain"}) == {"id": 1}
    assert fake.audit_log[0]["username"] == "engineer"


def _pi(tag: str) -> dict:
    return {
        "id": f"pi:{tag}",
        "name": tag,
        "source": "pi",
        "unit": "",
        "description": "",
        "low": None,
        "high": None,
    }


def test_signal_ids_name_their_source_and_bare_tags_still_read(fake):
    client = fake.client()
    assert {item["source"] for item in client.signals()} == {"fake"}
    # Until API v1 is frozen, a bare tag one source has names its signal; the answer
    # echoes the id as asked.
    assert client.signal("FIC-101.PV")["id"] == "fake:FIC-101.PV"
    window = (NOW - timedelta(minutes=10), NOW)
    assert (
        client.series("FIC-101.PV", *window)["v"] == client.series("fake:FIC-101.PV", *window)["v"]
    )
    batch = client.series_many(["FIC-101.PV", "fake:FIC-101.SP"], *window)
    assert [item["signal"] for item in batch["series"]] == ["FIC-101.PV", "fake:FIC-101.SP"]
    with pytest.raises(NotFound):
        client.signal("other:FIC-101.PV")


def test_a_bare_tag_two_sources_have_is_a_404_naming_both():
    fake = FakePlantCraft(signals=[_pi("FIC-1.PV"), {**_pi("FIC-1.PV"), "id": "opc:FIC-1.PV"}])
    client = fake.client()
    with pytest.raises(NotFound) as caught:
        client.signal("FIC-1.PV")
    assert "opc:FIC-1.PV" in str(caught.value) and "pi:FIC-1.PV" in str(caught.value)
    batch = client.series_many(["FIC-1.PV"], NOW - timedelta(minutes=10), NOW)
    assert batch["errors"][0]["status"] == 404 and "pi:FIC-1.PV" in batch["errors"][0]["detail"]
    assert client.signal("pi:FIC-1.PV")["source"] == "pi"


def test_pi_tags_with_spaces_and_backslashes_are_encoded_in_urls():
    tag = r"Unit 2\FIC 101/PV"
    fake = FakePlantCraft(
        signals=[_pi(tag)],
        series={
            tag: pd.Series([1.0, 3.0], index=pd.to_datetime([NOW - timedelta(minutes=2), NOW]))
        },
        now=NOW,
    )
    client = fake.client()
    assert client.signal(f"pi:{tag}")["id"] == f"pi:{tag}"
    assert client.value(f"pi:{tag}", "max", "1h")["value"] == 3.0


def test_signal_ids_with_slashes_are_encoded():
    fake = FakePlantCraft(
        signals=[
            {
                "id": "Area/FIC-1.PV",
                "name": "x",
                "source": "fake",
                "unit": "",
                "description": "",
                "low": None,
                "high": None,
            }
        ],
        series={
            "Area/FIC-1.PV": pd.Series(
                [1.0, 2.0],
                index=pd.to_datetime([NOW - timedelta(minutes=2), NOW - timedelta(minutes=1)]),
            )
        },
        now=NOW,
    )
    client = fake.client()
    assert client.signal("Area/FIC-1.PV")["id"] == "Area/FIC-1.PV"
    assert client.series("Area/FIC-1.PV", NOW - timedelta(hours=1), NOW)["v"] == [1.0, 2.0]
    assert client.value("Area/FIC-1.PV", "max", "1h")["value"] == 2.0


def test_errors_are_typed(fake):
    client = fake.client("engineer")
    with pytest.raises(NotFound):
        client.signal("NOPE")
    with pytest.raises(BadRequest) as error:
        client.value("fake:FIC-101.PV", window="-1d")
    assert error.value.status_code == 422 and "window" in str(error.value)
    with pytest.raises(BadRequest):
        client.series("fake:FIC-101.PV", NOW, NOW - timedelta(hours=1))
    with pytest.raises(BadRequest):
        client.series("fake:FIC-101.PV", NOW - timedelta(days=30), NOW, step=1)
    with pytest.raises(Unauthorized):
        PlantCraftClient("http://processcraft.test", "garbage", http_client=fake.http_client()).me()
    fake.users["dash"] = {"name": "Dash", "level": "dashboards", "apps": {}}
    with pytest.raises(Forbidden):
        fake.client("dash").assets()


def test_service_token_is_acquired_and_renewed(fake):
    client = fake.client(None, app="linkcraft", key="test-app-key")
    grants = []
    original = client.service_token
    client.service_token = lambda app, key: grants.append(app) or original(app, key)
    assert client.me()["username"] == "app:linkcraft"
    assert client.me()["level"] == "viewer"
    assert grants == ["linkcraft"]  # one grant serves many calls
    client._expires = 0  # about to expire: the next call asks again
    client.me()
    assert grants == ["linkcraft", "linkcraft"]
    with pytest.raises(Unauthorized):
        fake.client(None, app="linkcraft", key="wrong").me()


def test_rejected_service_token_is_renewed_once(fake):
    client = fake.client(None, app="linkcraft", key="test-app-key")
    client.me()
    fake.rotate_key()
    fake._public = fake._public[-1:]  # the old key is withdrawn: its tokens fail
    assert client.me()["username"] == "app:linkcraft"


def test_reads_retry_on_5xx_and_connection_errors():
    answers = iter(
        [
            httpx.Response(503),
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"username": "a"}),
        ]
    )

    def handler(request):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = PlantCraftClient(
        "http://x.test",
        "token",
        backoff=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.me() == {"username": "a"}


def test_writes_are_not_resent_after_the_server_saw_them():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(502, json={"detail": "source down"})

    client = PlantCraftClient(
        "http://x.test",
        "token",
        backoff=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(Unavailable) as error:
        client.audit("a", "b")
    assert len(calls) == 1 and error.value.detail == "source down"


def test_a_client_needs_credentials():
    with pytest.raises(ValueError):
        PlantCraftClient("http://x.test")
