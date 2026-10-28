"""The Historian's part of the suite's search (Ctrl+K): points and sources."""

from __future__ import annotations

from histcraft.catalog.models import PointIn, SourceIn
from tests.conftest import client_for


def test_search_finds_points_and_sources(runtime, fake):
    runtime.catalog.save_source(
        SourceIn(id="plant", name="Plant", endpoint="opc.tcp://127.0.0.1:4840/"), create=True
    )
    runtime.catalog.add_points(
        [
            PointIn(tag="TI-100.PV", source_id="plant", address="ns=2;s=TI-100.PV"),
            PointIn(tag="FIC-101.PV", source_id="plant", address="ns=2;s=FIC-101.PV"),
        ]
    )
    with client_for(runtime, fake, "operator") as client:
        body = client.get("/hist/api/search", params={"q": "ti-100"}).json()
        assert body["format"] == "plantcraft-search/1"
        [hit] = body["items"]
        assert hit["title"] == "TI-100.PV" and hit["type"] == "Signal"
        assert hit["href"].startswith("/points/") and "TI-100.PV" in hit["href"]
        hits = client.get("/hist/api/search", params={"q": "plant"}).json()["items"]
        assert {"title": "Plant", "type": "Source", "href": "/sources/plant"}.items() <= hits[
            0
        ].items()
        assert (
            client.get("/hist/api/search", params={"q": "pv ti"}).json()["items"][0]["title"]
            == "TI-100.PV"
        )
        assert client.get("/hist/api/search", params={"q": "t"}).json()["items"] == []
