"""Folders for the site's blocks, algorithms and schedules (owner D14, 2026-10-26): made by
editors, an object put in one when made and moved only on purpose, with who moved it."""

from __future__ import annotations

from tests.conftest import client_for
from tests.test_algorithms import _save, api, rt, suite_fake  # noqa: F401


def test_an_algorithm_goes_in_a_folder_and_moves_on_purpose(api, rt):  # noqa: F811
    _save(api)
    made = api.post("/link/api/folders/algorithm", json={"name": "Valves"})
    assert made.status_code == 201 and made.json()["count"] == 0
    folder = made.json()["folder_id"]
    twin = api.post("/link/api/folders/algorithm", json={"name": "valves"})
    assert twin.status_code == 422  # one name per kind, whatever the case
    moved = api.put("/link/api/folders/algorithm/items/pv_and_valve", json={"folder_id": folder})
    assert moved.json()["place"]["folder_id"] == folder
    assert moved.json()["place"]["moved_by"] and moved.json()["place"]["moved_at"]
    listed = api.get("/link/api/folders/algorithm").json()
    assert listed["folders"][0]["count"] == 1 and listed["items"]["pv_and_valve"]["folder_id"]
    # A folder holds one kind only, and a full folder is not deleted.
    wrong = api.put("/link/api/folders/schedule/items/pv_and_valve", json={"folder_id": folder})
    assert wrong.status_code == 404
    assert api.delete(f"/link/api/folders/algorithm/{folder}").status_code == 409
    renamed = api.patch(f"/link/api/folders/algorithm/{folder}", json={"name": "Valve checks"})
    assert renamed.json()["name"] == "Valve checks"
    out = api.put("/link/api/folders/algorithm/items/pv_and_valve", json={"folder_id": ""})
    assert out.json()["place"] is None
    assert api.delete(f"/link/api/folders/algorithm/{folder}").status_code == 204
    assert api.get("/link/api/folders/algorithm").json()["folders"] == []


def test_a_deleted_algorithm_leaves_its_folder(api, rt):  # noqa: F811
    _save(api)
    folder = api.post("/link/api/folders/algorithm", json={"name": "Valves"}).json()["folder_id"]
    api.put("/link/api/folders/algorithm/items/pv_and_valve", json={"folder_id": folder})
    assert api.delete("/link/api/algorithms/pv_and_valve").status_code == 204
    assert api.get("/link/api/folders/algorithm").json()["items"] == {}


def test_only_the_sites_blocks_go_in_folders_and_viewers_only_read(rt, suite_fake):  # noqa: F811
    with client_for(rt, suite_fake) as editor:
        folder = editor.post("/link/api/folders/block", json={"name": "Mine"}).json()
        # A block Link ships stays in its library.
        shipped = editor.put(
            "/link/api/folders/block/items/method.stiction_screening",
            json={"folder_id": folder["folder_id"]},
        )
        assert shipped.status_code == 404
    with client_for(rt, suite_fake, "operator") as viewer:
        assert viewer.get("/link/api/folders/block").json()["folders"][0]["name"] == "Mine"
        refused = viewer.post("/link/api/folders/block", json={"name": "Theirs"})
        assert refused.status_code == 403
        assert viewer.get("/link/api/folders/nothing").status_code == 422
