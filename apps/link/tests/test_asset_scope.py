"""A person who sees only part of the plant (PlantCraft's token claim ``assets``, its
docs/asset-scope.md) finds in Analytics only the loops, results and runs of that part; any other
reads as not found. Everyone else sees every loop."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from plantcraft_sdk.asset_scope import forget

from linkcraft.api.app import create_app


@pytest.fixture(autouse=True)
def _fresh():
    forget()
    yield
    forget()


def limited(runtime, fake, username="engineer") -> TestClient:
    """``username`` limited to the loop LIC-102 (asset ``lic-102``)."""

    client = TestClient(create_app(runtime), raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {fake.token(username, assets=['lic-102'])}"
    return client


def test_loops_results_and_runs_keep_to_the_part(analysed, client, fake):
    runtime = analysed
    with limited(runtime, fake, "operator") as operator:
        assert {row["loop_id"] for row in operator.get("/link/api/loops").json()} == {"lic-102"}
        assert operator.get("/link/api/loops/lic-102").status_code == 200
        assert operator.get("/link/api/loops/fic-101").status_code == 404
        assert operator.get("/link/api/loops/fic-101/report.pdf").status_code == 404

        results = operator.get("/link/api/results", params={"kind": "loop"}).json()["items"]
        assert {row["id"] for row in results} == {"lic-102"}

        jobs = operator.get("/link/api/jobs").json()
        assert jobs and {job["loop_id"] for job in jobs} <= {"lic-102", "*", ""}
        others = [job for job in client.get("/link/api/jobs").json() if job["loop_id"] == "fic-101"]
        assert others
        assert operator.get(f"/link/api/jobs/{others[0]['job_id']}").status_code == 404

        found = operator.get("/link/api/search", params={"q": "FIC-101"}).json()["items"]
        assert all(item["type"] != "Loop" for item in found)
        assert operator.get("/link/api/assets/fic-101").status_code == 404
        assert operator.get("/link/api/assets/lic-102").status_code == 200

    # Everyone else: every loop.
    assert {row["loop_id"] for row in client.get("/link/api/loops").json()} >= {
        "fic-101",
        "lic-102",
    }
