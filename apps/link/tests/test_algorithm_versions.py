"""Versions on top of an algorithm's page: every save is kept as it was
saved, with its name and description to choose from; an older one reads but never edits."""

from __future__ import annotations

from tests.test_algorithms import _save, api, rt, suite_fake  # noqa: F401


def test_each_save_keeps_its_version_as_it_was(api):  # noqa: F811
    _save(api)
    again = api.put(
        "/link/api/algorithms/pv_and_valve",
        json={
            "algorithm_id": "pv_and_valve",
            "name": "PV and valve",
            "description": "Now with a note.",
            "diagram": _save(api)["diagram"],
        },
    ).json()
    assert again["version"] == 3
    versions = api.get("/link/api/algorithms/pv_and_valve/versions").json()
    assert [item["version"] for item in versions] == [3, 2, 1]
    assert [item["current"] for item in versions] == [True, False, False]
    assert versions[0]["description"] == "Now with a note." and versions[2]["description"] == ""
    assert versions[0]["saved_by"] and versions[0]["saved_at"]
    first = api.get("/link/api/algorithms/pv_and_valve/versions/1").json()
    assert first["version"] == 1 and first["editable"] is False
    assert first["diagram"]["nodes"] and first["check"]["valid"]
    assert api.get("/link/api/algorithms/pv_and_valve/versions/9").status_code == 404


def test_a_new_version_keeps_its_own_name_and_what_changed(api):  # noqa: F811
    """Owner D19 (2026-10-26): New version saves a note like a block's version."""

    diagram = _save(api)["diagram"]
    saved = api.put(
        "/link/api/algorithms/pv_and_valve",
        json={
            "algorithm_id": "pv_and_valve",
            "name": "PV and valve",
            "diagram": diagram,
            "version_name": "Wider window",
            "version_note": "Reads two hours.",
        },
    )
    assert saved.status_code == 200, saved.text
    versions = api.get("/link/api/algorithms/pv_and_valve/versions").json()
    assert (versions[0]["version_name"], versions[0]["version_note"]) == (
        "Wider window",
        "Reads two hours.",
    )
    assert versions[1]["version_name"] == ""


def test_links_own_algorithms_have_their_shipped_version(api):  # noqa: F811
    versions = api.get("/link/api/algorithms/flow_loop/versions").json()
    assert len(versions) == 1 and versions[0]["current"] and versions[0]["saved_by"] == "PlantCraft"
    shipped = api.get(f"/link/api/algorithms/flow_loop/versions/{versions[0]['version']}").json()
    assert shipped["name"] == "Flow loop"


def test_a_deleted_algorithm_takes_its_versions(api, rt):  # noqa: F811
    _save(api)
    assert api.delete("/link/api/algorithms/pv_and_valve").status_code == 204
    assert rt.presets.list_versions("pv_and_valve") == []


def test_a_restart_keeps_when_a_shipped_version_was_saved(rt):  # noqa: F811
    before = rt.presets.list_versions("flow_loop")
    shipped = [
        {
            "algorithm_id": item["profile_id"],
            "name": item["name"],
            "description": item["description"],
            "method_config": item["method_config"],
            "version": item["version"],
        }
        for item in rt.presets.list_profiles()
        if item["system"]
    ]
    rt.presets.seed_system_algorithms(shipped)
    assert rt.presets.list_versions("flow_loop") == before
