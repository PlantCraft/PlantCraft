"""The suite's rules (``plantcraft_sdk.apptest``, PlantCraft ``docs/testing.md``): offline by
default, layers that only point down, the image that follows ``app.toml``. Historian is the data
layer, so it adds its own: only the collector's readers talk to plant servers, and the API writes
only derived series. Junk inputs: ``tests/test_hostile_inputs.py``; floors: ``tests/test_floors.py``.
"""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk import apptest

from histcraft.api.app import create_app
from tests.conftest import client_for

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "histcraft"
# | Layer | Packages |
# | -1 | i18n (everything may use t()) |
# | 0 | db (its own PostgreSQL or SQLite), clock, config, meta, vault |
# | 1 | archive, catalog, sources |
# | 2 | collector |
# | 3 | api, cli, bench |
LAYERS = {
    "i18n": -1,
    "db": 0,
    "clock": 0,
    "config": 0,
    "meta": 0,
    "notebook_examples": 0,
    "kinds": 0,
    "opc_status": 0,
    "vault": 0,
    "archive": 1,
    "catalog": 1,
    "sources": 1,
    "export": 1,
    "collector": 2,
    "conditions": 2,
    "api": 3,
    "cli": 3,
    "bench": 3,
}
NETWORK_MODULES = (
    "api/runtime.py",  # the httpx client every PlantCraftClient shares
    "collector/opcua.py",  # the OPC UA client of the configured sources
    "sources/pi_web_api.py",  # PI Web API sources (GET only)
    "sources/pi_check.py",  # the PI connection check (DNS, TCP, HTTPS)
    "sources/opcua_history.py",  # OPC UA Historical Access sources
    "sources/certificates.py",  # OPC UA GetEndpoints before a secure channel (G2)
    "db.py",  # Historian's own PostgreSQL database
)
PLANT_MODULES = {
    "src/histcraft/collector/opcua.py",
    "src/histcraft/sources/opcua_history.py",
    "src/histcraft/sources/certificates.py",
}
PLANT_IMPORTS = {"asyncua", "opcua", "PIconnect", "osisoft", "pyodbc", "pymodbus", "paho"}


def test_offline_by_default():
    assert not apptest.offline_problems(ROOT, "histcraft", network_modules=NETWORK_MODULES)


def test_layers_only_point_down():
    assert not apptest.layer_problems(ROOT, "histcraft", LAYERS, allowed={"asyncua"})


def test_only_suite_talks_to_plantcraft_for_the_app():
    assert not apptest.suite_problems(ROOT, "histcraft")


def test_routers_import_no_store():
    assert not apptest.router_problems(ROOT, "histcraft")


def test_what_app_toml_contributes_is_wired(runtime):
    routes = apptest.api_routes(create_app(runtime))
    assert not apptest.contribution_problems(ROOT, "histcraft", routes)


def test_the_screens_use_the_shared_ui_instead_of_copies():
    assert not apptest.ui_copy_problems(ROOT, ROOT.parents[1] / "ui" / "src")


def test_the_image_follows_the_manifest():
    # Historian's SBOM is CycloneDX with the interface's npm packages (deploy/sbom.py) until the
    # SDK's covers them (PlantCraft docs/gaps.md).
    problems = [p for p in apptest.image_problems(ROOT) if "SBOM" not in p]
    assert not problems


def test_only_the_collector_reader_talks_to_plant_servers():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        for name in apptest.imports(path):
            if name.split(".")[0] in PLANT_IMPORTS and relative not in PLANT_MODULES:
                offenders.append(f"{relative} imports {name}")
    assert not offenders, "\n".join(offenders)


def test_the_server_writes_only_derived_series_to_the_archive():
    """The collector writes collected values (docs/boundary.md); the API writes only the series
    apps compute (``POST /api/v1/data/derived`` and ``/derived/runs``) and laboratory results
    (``POST /api/v1/lab``), never plant points."""

    writes = ("append(", "put_snapshots(", "set_state(", "compact(", "prune(", "delete_points(")
    derived = {"put_snapshots("}
    for path in (PACKAGE / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for call in writes:
            # Laboratory results are written here too (``lab.py``): people or the LIMS give them.
            if path.name in ("data.py", "lab.py") and call in derived:
                continue
            assert f"archive.{call}" not in text, f"{path.name} writes the archive: {call}"
    data = (PACKAGE / "api" / "routers" / "data.py").read_text(encoding="utf-8")
    assert data.count("archive.replace(") == 1 and data.count("archive.put_run(") == 1
    assert data.count("archive.put_snapshots(") == 2
    lab = (PACKAGE / "api" / "routers" / "lab.py").read_text(encoding="utf-8")
    assert lab.count("archive.replace(") == 1 and lab.count("archive.put_snapshots(") == 1


def test_no_api_route_answers_without_a_token(runtime, fake):
    """A route that forgot its access check fails here (docs/contributing-safety.md)."""

    with client_for(runtime, fake, None) as client:
        client.headers.pop("Authorization", None)
        leaks, reached = apptest.open_routes(client, prefix="/hist")
    assert not leaks, "routes answering without a token:\n" + "\n".join(leaks)
    assert reached > 10
