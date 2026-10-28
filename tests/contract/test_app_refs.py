"""#<kind>:<id> of the kinds an app declares in [[contributes.refs]] link to its pages.

The fixture ``central`` is the one of ``test_api_v1.py``: Link (``linkcraft``) at ``/link/``.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from plantcraft_sdk.app_manifest import AppManifest
from tests.contract.test_api_v1_links import _service

ROOT = Path(__file__).resolve().parents[2]

REFS = {
    "contributes": {
        "refs": [
            {"kind": "protocol", "title": "Algorithm", "url": "/link/algorithms/{id}"},
            {"kind": "elsewhere", "title": "Nope", "url": "/other/{id}"},
        ]
    }
}


def _resolve(central, *refs: str) -> dict:
    central.post("/api/login", json={"username": "eng", "password": "password-123"})
    return central.get("/api/refs", params=[("ref", ref) for ref in refs]).json()


def test_a_declared_kind_gets_its_name_and_the_page_of_its_app(central):
    before = _resolve(central, "protocol:loop health")["protocol:loop health"]
    assert before["exists"] is False and before["href"] is None
    put = central.put("/api/v1/contributions", json=REFS, headers=_service(central))
    assert put.status_code == 200, put.text
    found = _resolve(central, "protocol:loop health", "elsewhere:x", "asset:nothing-here")
    item = found["protocol:loop health"]
    assert item["exists"] is True and item["kind_label"] == "Algorithm"
    assert item["href"] == "/link/algorithms/loop%20health" and item["owner"] == "linkcraft"
    assert item["title"] == "loop health"
    # A page outside the app's prefix is not a link, and PlantCraft's own kinds stay its own.
    assert found["elsewhere:x"]["exists"] is False
    assert found["asset:nothing-here"]["exists"] is False


def test_a_text_the_app_wrote_names_its_object(central):
    headers = _service(central)
    central.put("/api/v1/contributions", json=REFS, headers=headers)
    text = [{"app": "linkcraft", "ref": "protocol:flow", "title": "Flow loops", "text": "x",
             "url": "/link/algorithms/flow"}]  # fmt: skip
    assert central.put("/api/v1/knowledge", json=text, headers=headers).status_code == 200
    item = _resolve(central, "protocol:flow")["protocol:flow"]
    assert item["title"] == "Flow loops" and item["kind_label"] == "Algorithm"


def test_the_manifest_keeps_a_kind_s_page_under_the_app_s_prefix():
    base = tomllib.loads((ROOT / "apps" / "link" / "app.toml").read_text(encoding="utf-8"))
    base["contributes"] = {"refs": [REFS["contributes"]["refs"][0]]}
    AppManifest.model_validate(base)
    base["contributes"] = REFS["contributes"]
    with pytest.raises(ValueError, match="under /link/"):
        AppManifest.model_validate(base)
