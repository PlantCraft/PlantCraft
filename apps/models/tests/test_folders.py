"""Folders for the site's models, blocks and studies (round 9, M5), as Link's."""

from __future__ import annotations

from tests.conftest import TLC, client_for, example
from tests.test_studies import SWEEP, wait_study

GAIN = (
    'within Utilities;\nblock Gain "Multiplies its input"\n'
    "  Modelica.Blocks.Interfaces.RealInput u;\n  Modelica.Blocks.Interfaces.RealOutput y;\n"
    "  parameter Real k = 2;\nequation\n  y = k * u;\nend Gain;\n"
)


def test_models_blocks_and_studies_go_in_folders_of_their_own(client):
    project = example(client)
    model_id = f"{project['id']}/{TLC}"
    folder = client.post("/api/folders/model", json={"name": "Tanks"}).json()
    moved = client.put(
        f"/api/folders/model/items/{model_id}", json={"folder_id": folder["folder_id"]}
    )
    assert moved.status_code == 200 and moved.json()["place"]["moved_by"]
    listed = client.get("/api/folders/model").json()
    assert listed["folders"][0]["count"] == 1 and model_id in listed["items"]
    assert (
        client.put(
            f"/api/folders/model/items/{project['id']}/Nope", json={"folder_id": ""}
        ).status_code
        == 404
    )
    # A study folder takes no model, and a model folder no study.
    studies = client.post("/api/folders/study", json={"name": "Tuning"}).json()
    assert (
        client.put(
            f"/api/folders/model/items/{model_id}", json={"folder_id": studies["folder_id"]}
        ).status_code
        == 422
    )
    study = client.post(f"/api/projects/{project['id']}/studies", json=SWEEP).json()
    wait_study(client, study["id"])
    assert (
        client.put(
            f"/api/folders/study/items/{study['id']}", json={"folder_id": studies["folder_id"]}
        ).status_code
        == 200
    )
    client.post(f"/api/projects/{project['id']}/simulate", json={"model": TLC, "stop": 10})
    quick = next(s for s in client.get("/api/studies").json() if s["kind"] == "quick")
    assert (
        client.put(
            f"/api/folders/study/items/{quick['id']}", json={"folder_id": studies["folder_id"]}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/studies/{study['id']}").status_code == 204
    assert client.get("/api/folders/study").json()["items"] == {}
    assert client.get("/api/folders/library").status_code == 422


def test_only_the_sites_own_blocks_go_in_folders(client):
    blocks = client.post("/api/folders/block", json={"name": "Mine"}).json()["folder_id"]
    shipped = client.put(
        "/api/folders/block/items/PlantCraftEquipment.Tank", json={"folder_id": blocks}
    )
    assert shipped.status_code == 404
    library = client.post("/api/blocks", json={"name": "Utilities"}).json()
    saved = client.post(
        f"/api/projects/{library['id']}/files", json={"path": "Utilities/Gain.mo", "content": GAIN}
    )
    assert saved.status_code == 201
    moved = client.put("/api/folders/block/items/Utilities.Gain", json={"folder_id": blocks})
    assert moved.status_code == 200
    assert client.delete(f"/api/projects/{library['id']}").status_code == 204
    assert client.get("/api/folders/block").json()["items"] == {}


def test_viewers_see_folders_but_do_not_change_them(runtime, fake, client):
    client.post("/api/folders/model", json={"name": "Tanks"})
    with client_for(runtime, fake, "operator") as viewer:
        assert [f["name"] for f in viewer.get("/api/folders/model").json()["folders"]] == ["Tanks"]
        assert viewer.post("/api/folders/model", json={"name": "Mine"}).status_code == 403
