"""Versions of a model and of a block (round 9 M3, M4): open one, use it again, compare them."""

from __future__ import annotations

import json

from tests.conftest import TLC, TLC_FILE, editable_example, example, wait_for
from tests.test_folders import GAIN


def _save(client, project_id: str, path: str, change) -> None:
    current = client.get(f"/api/projects/{project_id}/files/{path}").json()
    saved = client.put(
        f"/api/projects/{project_id}/files/{path}",
        json={"content": change(current["content"]), "base_updated_at": current["updated_at"]},
    )
    assert saved.status_code == 200, saved.text


def test_a_model_version_opens_is_used_again_and_compares_on_one_experiment(client, runtime):
    project = editable_example(client)
    pid = project["id"]
    _save(client, pid, TLC_FILE, lambda text: text.replace("Tank level control", "Tank level v2"))
    revisions = client.get(f"/api/projects/{pid}/files/{TLC_FILE}/revisions").json()
    first = revisions[-1]["id"]
    old = client.get(f"/api/models/{pid}/{TLC}/versions/{first}")
    assert old.status_code == 200 and old.json()["revision"] == first
    assert "Tank level v2" not in old.json()["description"]
    assert "Tank level v2" in client.get(f"/api/models/{pid}/{TLC}").json()["description"]
    assert client.get(f"/api/models/{pid}/{TLC}/versions/999999").status_code == 404

    runs = client.post(
        f"/api/models/{pid}/{TLC}/compare",
        json={"revisions": [first, 0], "labels": ["Version 1", "Version 2"]},
    )
    assert runs.status_code == 201, runs.text
    assert [run["label"] for run in runs.json()] == ["Version 1", "Version 2"]
    for run in runs.json():
        assert wait_for(client, run["id"])["status"] == "done"
    sent = [
        json.loads((runtime.workbench.run_dir(run["id"]) / "files.json").read_text())
        for run in runs.json()
    ]
    assert sent[0][TLC_FILE] != sent[1][TLC_FILE] and "Tank level v2" in sent[1][TLC_FILE]
    assert "PlantCraftEquipment/Tank.mo" in sent[0]  # the shared blocks ride along
    assert (
        client.post(f"/api/models/{pid}/{TLC}/compare", json={"revisions": [first]}).status_code
        == 422
    )

    used = client.post(f"/api/models/{pid}/{TLC}/versions/{first}/use")
    assert used.status_code == 200 and "Tank level v2" not in used.json()["description"]
    assert len(client.get(f"/api/projects/{pid}/files/{TLC_FILE}/revisions").json()) == 2
    shipped = example(client)["id"]
    assert client.post(f"/api/models/{shipped}/{TLC}/versions/{first}/use").status_code in (
        403,
        404,
    )


def test_a_block_version_has_its_ports_and_code_then(client):
    library = client.post("/api/blocks", json={"name": "Utilities"}).json()
    client.post(
        f"/api/projects/{library['id']}/files", json={"path": "Utilities/Gain.mo", "content": GAIN}
    )
    _save(
        client,
        library["id"],
        "Utilities/Gain.mo",
        lambda text: text.replace(
            "  parameter Real k = 2;",
            "  Modelica.Blocks.Interfaces.RealInput b;\n  parameter Real k = 2;",
        ).replace("y = k * u;", "y = k * u + b;"),
    )
    revisions = client.get(
        f"/api/projects/{library['id']}/files/Utilities/Gain.mo/revisions"
    ).json()
    old = client.get(f"/api/catalog/Utilities.Gain/versions/{revisions[0]['id']}").json()
    now = client.get("/api/catalog/Utilities.Gain").json()
    assert [port["port"] for port in old["inputs"]] == ["u"]
    assert [port["port"] for port in now["inputs"]] == ["u", "b"]
    assert "y = k * u;" in old["code"] and old["saved_by"]
    assert client.get("/api/catalog/Utilities.Gain/versions/999999").status_code == 404


def test_each_version_of_a_model_has_a_name_and_what_changed(client):
    """Round 9 M4 leftover: a save names its version, as Link's algorithms;
    the name travels with the text into the versions a later save replaces."""

    project = editable_example(client)
    pid = project["id"]
    model = client.get(f"/api/models/{pid}/{TLC}").json()
    body = {
        "diagram": model["diagram"],
        "settings": model["settings"],
        "base_updated_at": model["updated_at"],
        "version_name": "Same diagram",
        "version_note": "Saved from the form.",
    }
    saved = client.put(f"/api/models/{pid}/{TLC}", json=body)
    assert saved.status_code == 200, saved.text
    assert (saved.json()["version_name"], saved.json()["version_note"]) == (
        "Same diagram",
        "Saved from the form.",
    )
    current = client.get(f"/api/projects/{pid}/files/{TLC_FILE}").json()
    changed = client.put(
        f"/api/projects/{pid}/files/{TLC_FILE}",
        json={
            "content": current["content"].replace("Tank level control", "Tank level v3"),
            "base_updated_at": current["updated_at"],
            "version_name": "Renamed",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version_name"] == "Renamed" and changed.json()["version_note"] == ""
    revisions = client.get(f"/api/projects/{pid}/files/{TLC_FILE}/revisions").json()
    assert revisions[0]["version_name"] == "Same diagram"
    assert revisions[0]["version_note"] == "Saved from the form."
    one = client.get(f"/api/projects/{pid}/revisions/{revisions[0]['id']}").json()
    assert one["version_name"] == "Same diagram"
    # Use this version: its name comes back, marked as saved again.
    used = client.post(f"/api/models/{pid}/{TLC}/versions/{revisions[0]['id']}/use")
    assert used.status_code == 200, used.text
    assert used.json()["version_name"] == "Same diagram"
    assert used.json()["version_note"] == "Saved again from an earlier version."
    too_long = {**body, "base_updated_at": used.json()["updated_at"], "version_name": "x" * 121}
    assert client.put(f"/api/models/{pid}/{TLC}", json=too_long).status_code == 422
