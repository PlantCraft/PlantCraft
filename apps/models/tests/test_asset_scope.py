"""A person who sees only part of the plant (PlantCraft's token claim ``assets``, its
docs/asset-scope.md) sees in Models only the simulations and studies on plant data of that part
(every signal a run read); a run on no plant data is everyone's."""

from __future__ import annotations

import pytest
from plantcraft_sdk.asset_scope import forget

from tests.conftest import TLC, client_for, example, wait_for
from tests.plant import NOW


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def limited(runtime, fake, asset: str, username="engineer"):
    client = client_for(runtime, fake, None)
    client.headers["Authorization"] = f"Bearer {fake.token(username, assets=[asset])}"
    return client


def test_runs_on_plant_data_keep_to_the_part(client, runtime, fake):
    project = example(client)
    signal = next(s["id"] for s in client.get("/api/signals", params={"q": "FIC"}).json())
    body = {
        "model": TLC,
        "plant": {
            "start": (NOW.replace(hour=6)).isoformat(),
            "end": (NOW.replace(hour=7)).isoformat(),
            "step": 60,
            "inputs": {"qin": signal},
        },
    }
    fed = wait_for(
        client, client.post(f"/api/projects/{project['id']}/simulate", json=body).json()["id"]
    )
    plain = wait_for(
        client,
        client.post(f"/api/projects/{project['id']}/simulate", json={"model": TLC}).json()["id"],
    )
    own = signal.split(".")[2]
    other = next(
        item["id"] for item in fake.assets if item.get("kind") == "loop" and item["id"] != own
    )

    with limited(runtime, fake, other) as stranger:
        ids = {run["id"] for run in stranger.get("/api/runs").json()}
        assert plain["id"] in ids and fed["id"] not in ids
        assert stranger.get(f"/api/runs/{fed['id']}").status_code == 404
        assert (
            stranger.post(
                f"/api/runs/{fed['id']}/series", json={"names": ["tank.level"]}
            ).status_code
            == 404
        )
        assert stranger.get(f"/api/runs/{plain['id']}").status_code == 200
    with limited(runtime, fake, own) as insider:
        assert insider.get(f"/api/runs/{fed['id']}").status_code == 200
