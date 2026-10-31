"""API v1 reads served by the Historian to the apps (``api/routers/reads.py``).

Same answers as PlantCraft's API v1 (here: as the data routes PlantCraft forwards to), for
whoever may read PlantCraft's API v1: a person at viewer level or above, or an app's service
token, even without access to the Historian app. Nothing else gets in, and nothing writes.
"""

from __future__ import annotations

import numpy as np
import pytest
from plantcraft_sdk.contract import parse_times
from plantcraft_sdk.wire import MEDIA_TYPE, read_binary

from histcraft.catalog.models import PointIn
from tests.conftest import client_for
from tests.test_api import DATA, loaded, pc  # noqa: F401 - fixtures

V1 = "/hist/api/v1"
WINDOW = {"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T01:00:00Z"}


def bearer(runtime, fake, token):
    client = client_for(runtime, fake, None)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
def app(runtime, fake):
    """Link's service token: viewer level, no access to the Historian app."""

    return bearer(runtime, fake, fake.token("app:linkcraft", apps={"linkcraft": "viewer"}))


def test_the_reads_answer_as_the_data_routes(pc, app, loaded):  # noqa: F811
    assert app.get(f"{V1}/reads").json() == {"api": 1, "formats": ["pcs1"]}
    for path, params in (
        ("/signals", {}),
        ("/signals", {"q": "mode"}),
        ("/signals/plant:TI-100.PV", {}),
        ("/signals/TI-100.PV", {}),
        ("/signals/plant:TI-100.PV/series", WINDOW),
        ("/signals/plant:TI-100.PV/series", {**WINDOW, "step": 600}),
        ("/signals/plant:Area%2F1%2FTT/series", WINDOW),
        ("/signals/plant:FIC-101.MODE/series", {**WINDOW, "step": 900}),
        ("/signals/plant:FIC-101.MODE/value", {"window": "366d"}),
    ):
        mine = app.get(f"{V1}{path}", params=params)
        assert mine.status_code == 200, (path, mine.text)
        assert mine.json() == pc.get(f"{DATA}{path}", params=params).json(), path
    body = {"signals": ["plant:TI-100.PV", "missing", "plant:FIC-101.MODE"], **WINDOW}
    for step in (None, 60):
        batch = {**body, "step": step}
        assert (
            app.post(f"{V1}/series", json=batch).json()
            == pc.post(f"{DATA}/series", json=batch).json()
        )
    assert app.get(f"{V1}/signals/plant:nope").status_code == 404
    assert (
        app.get(f"{V1}/signals/plant:FIC-101.MODE/value", params={"agg": "mean"}).status_code == 422
    )
    assert app.post(f"{V1}/series", json={"signals": []}).status_code == 422


def test_who_reads(runtime, fake, loaded):  # noqa: F811
    url = f"{V1}/signals/plant:TI-100.PV/series"
    # a viewer without the Historian app reads, as in PlantCraft's API v1
    assert client_for(runtime, fake, "outsider").get(url, params=WINDOW).status_code == 200
    assert client_for(runtime, fake, "operator").get(url, params=WINDOW).status_code == 200
    anonymous = client_for(runtime, fake, None).get(url)
    assert anonymous.status_code == 401 and anonymous.headers["www-authenticate"] == "Bearer"
    dashboards = bearer(runtime, fake, fake.token("viewer", level="dashboards"))
    assert dashboards.get(url).status_code == 403
    # a token for another app only, an expired one and a forged one are refused
    assert bearer(runtime, fake, fake.token("admin", aud="linkcraft")).get(url).status_code == 401
    assert bearer(runtime, fake, fake.token("admin", ttl=-120)).get(url).status_code == 401
    forged = fake.token("admin")[:-4] + "AAAA"
    assert bearer(runtime, fake, forged).get(url).status_code == 401


def test_ended_tokens_are_refused(runtime, fake, loaded):  # noqa: F811
    url = f"{V1}/signals"
    person = client_for(runtime, fake, "operator")
    assert person.get(url).status_code == 200
    fake.revoke("operator")
    runtime.verifier.revoked_ttl = 0
    assert person.get(url).status_code == 401
    key = fake.token("app:linkcraft", apps={"linkcraft": "viewer"}, key_id="k-1")
    assert bearer(runtime, fake, key).get(url).status_code == 200
    fake.revoked_keys.add("k-1")
    assert bearer(runtime, fake, key).get(url).status_code == 401


def test_nothing_writes(app, loaded):  # noqa: F811
    derived = [{"signal": "app-linkcraft:x", "t": ["2026-10-19T00:00:00Z"], "v": [1.0]}]
    refused = (404, 405)
    assert app.put(f"{V1}/series", json=derived).status_code in refused
    patch = app.patch(f"{V1}/signals/plant:TI-100.PV", json={"enabled": False})
    assert patch.status_code in refused
    assert app.delete(f"{V1}/signals/plant:TI-100.PV").status_code in refused
    assert loaded.catalog.point("plant:TI-100.PV")["enabled"]
    assert app.get(f"{DATA}/signals").status_code == 403


def test_a_batch_reads_the_archive_in_one_go(app, loaded, monkeypatch):  # noqa: F811
    loaded.catalog.add_points(
        [
            PointIn(tag=f"LC-{n}.PV", source_id="plant", address=f"ns=2;s=LC-{n}.PV")
            for n in range(40)
        ]
    )
    calls = {"read": 0, "read_many": 0, "find": 0}
    for store, name in (
        (loaded.archive, "read"),
        (loaded.archive, "read_many"),
        (loaded.catalog, "find"),
    ):
        original = getattr(store, name)

        def counted(*args, _original=original, _name=name, **kwargs):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(store, name, counted)
    signals = [f"plant:LC-{n}.PV" for n in range(40)] + ["plant:TI-100.PV", "TI-100.PV"]
    answer = app.post(f"{V1}/series", json={"signals": signals, **WINDOW}).json()
    assert len(answer["series"]) == 42 and not answer["errors"]
    # one archive read for the batch; only the bare tag is looked up on its own
    assert calls == {"read": 0, "read_many": 1, "find": 1}


def test_the_binary_answer_holds_the_json_answer(app, loaded):  # noqa: F811
    """``Accept: application/x-plantcraft-series``: the same series, errors and order, as
    millisecond times and floats (NaN for null) instead of text."""

    signals = ["plant:TI-100.PV", "missing", "plant:FIC-101.MODE", "plant:Area/1/TT"]
    for step in (None, 60, 3600):
        body = {"signals": signals, **WINDOW, "step": step}
        text = app.post(f"{V1}/series", json=body).json()
        answer = app.post(f"{V1}/series", json=body, headers={"Accept": MEDIA_TYPE})
        assert answer.headers["content-type"].startswith(MEDIA_TYPE)
        series, errors = read_binary(answer.content)
        assert errors == text["errors"]
        assert [item["signal"] for item in series] == [item["signal"] for item in text["series"]]
        for mine, theirs in zip(series, text["series"], strict=True):
            assert mine["kind"] == theirs["kind"]
            stamps = parse_times(theirs["t"]).as_unit("ms").asi8
            assert np.array_equal(np.asarray(mine["t"]), stamps)
            if isinstance(mine["v"], np.ndarray):
                wanted = np.array([np.nan if v is None else v for v in theirs["v"]], dtype=float)
                assert np.array_equal(mine["v"], wanted, equal_nan=True)
            else:
                assert mine["v"] == theirs["v"]
