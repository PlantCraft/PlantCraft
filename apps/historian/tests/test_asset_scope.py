"""A person who sees only part of the plant (PlantCraft's token claim ``assets``, its
docs/asset-scope.md) reads here only the points of that part: the direct reads, the Points
pages, the trend widget, the search and the exports. Everyone else reads every point."""

from __future__ import annotations

import pytest
from plantcraft_sdk.asset_scope import forget

from histcraft.catalog.models import PointIn, SourceIn
from tests.conftest import client_for
from tests.test_api import MS

V1 = "/hist/api/v1"
WINDOW = {"start": "2026-10-19T00:00:00Z", "end": "2026-10-19T01:00:00Z"}
# The ids PlantCraft gives (the fake plant's source is "fake"): FIC-101 is in the part.
SEEN, HIDDEN = "fake:FIC-101.PV", "fake:LIC-102.PV"


@pytest.fixture
def loaded(runtime):
    runtime.catalog.save_source(
        SourceIn(id="fake", name="Plant", endpoint="opc.tcp://127.0.0.1:4840/"), create=True
    )
    runtime.catalog.add_points(
        [
            PointIn(tag=tag, source_id="fake", address=f"ns=2;s={tag}")
            for tag in ("FIC-101.PV", "LIC-102.PV")
        ]
    )
    points = {p["tag"]: p["id"] for p in runtime.catalog.points()}
    runtime.archive.append(
        {
            points[tag]: ("number", [(MS + i * 60_000, float(i)) for i in range(60)])
            for tag in ("FIC-101.PV", "LIC-102.PV")
        }
    )
    return runtime


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def limited(runtime, fake, username="operator"):
    """``username`` limited to the loop FIC-101 (the fake plant's asset ``fic-101``)."""

    client = client_for(runtime, fake, None)
    client.headers["Authorization"] = f"Bearer {fake.token(username, assets=['fic-101'])}"
    return client


def test_direct_reads_keep_to_the_part(runtime, fake, loaded):
    client = limited(runtime, fake)
    ids = {item["id"] for item in client.get(f"{V1}/signals").json()}
    assert SEEN in ids and HIDDEN not in ids
    assert client.get(f"{V1}/signals/{SEEN}").status_code == 200
    for path in ("", "/series", "/value"):
        params = {"window": "366d"} if path == "/value" else WINDOW
        assert client.get(f"{V1}/signals/{HIDDEN}{path}", params=params).status_code == 404
    batch = client.post(f"{V1}/series", json={"signals": [SEEN, HIDDEN], **WINDOW}).json()
    assert [item["signal"] for item in batch["series"]] == [SEEN]
    assert {"signal": HIDDEN, "status": 404} == {
        key: batch["errors"][0][key] for key in ("signal", "status")
    }
    # The whole plant for whoever has no limit.
    everyone = client_for(runtime, fake, "operator")
    assert everyone.get(f"{V1}/signals/{HIDDEN}").status_code == 200


def test_pages_search_widgets_and_exports_keep_to_the_part(runtime, fake, loaded):
    client = limited(runtime, fake)
    tags = {point["signal"] for point in client.get("/hist/api/points").json()}
    assert tags == {SEEN}
    assert client.get(f"/hist/api/points/{HIDDEN}").status_code == 404
    assert client.get(f"/hist/api/points/{HIDDEN}/series", params=WINDOW).status_code == 404
    assert client.get(f"/hist/api/points/{SEEN}").status_code == 200
    assert HIDDEN not in client.get("/hist/api/points/export").text

    assert "LIC-102" not in client.get("/hist/api/search", params={"q": "LIC-102"}).text
    assert "FIC-101" in client.get("/hist/api/search", params={"q": "FIC-101"}).text

    options = client.get("/hist/api/widgets/trend/options").json()
    assert HIDDEN not in str(options) and SEEN in str(options)
    trend = client.get("/hist/api/widgets/trend", params={"item": HIDDEN}).json()
    assert "LIC-102" not in str(trend)

    refused = client.post("/hist/api/export/preview", json={"signals": [HIDDEN], "hours": 1})
    assert refused.status_code == 422

    # An administrator sees every point.
    admin = client_for(runtime, fake, "admin")
    assert {point["signal"] for point in admin.get("/hist/api/points").json()} >= {SEEN, HIDDEN}
