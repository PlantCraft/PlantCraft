"""The suite's app standard (PlantCraft docs/app-standard.md): manifest, settings, endpoints."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import histcraft
from tests.conftest import client_for

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = tomllib.loads((ROOT / "app.toml").read_text())


def test_manifest_matches_the_suite_table_and_the_package():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert MANIFEST["app"]["id"] == histcraft.APP_ID == "histcraft"
    assert MANIFEST["app"]["version"] == pyproject["project"]["version"] == histcraft.__version__
    runtime = MANIFEST["runtime"]
    assert (runtime["prefix"], runtime["port"], runtime["uid"]) == ("/hist/", 8100, 10008)
    assert MANIFEST["permissions"]["plant_write"] is False
    assert MANIFEST["permissions"]["outbound"] == []


def test_image_and_cli_use_the_manifest_values():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "HISTCRAFT_PORT=8100" in dockerfile and "USER 10008:10008" in dockerfile
    assert 'org.processcraft.app.id="histcraft"' in dockerfile
    assert re.search(r'"HISTCRAFT_PORT", "8100"', (ROOT / "src/histcraft/cli.py").read_text())
    assert 'assetsDir: "static"' in (ROOT / "frontend/vite.config.ts").read_text()


def test_meta_and_help_need_a_token_and_answer_with_one(runtime, fake):
    anonymous = client_for(runtime, fake, None)
    assert anonymous.get("/hist/api/meta").status_code == 401
    assert anonymous.get("/hist/api/help").status_code == 401
    client = client_for(runtime, fake, "operator")
    meta = client.get("/hist/api/meta").json()
    assert meta["app"]["id"] == "histcraft" and "revision" in meta
    pages = client.get("/hist/api/help").json()
    assert {"overview", "sources", "points", "compression", "settings"} <= {p["id"] for p in pages}
    assert all(p["title"] and p["category"] for p in pages)
    page = client.get("/hist/api/help/compression").json()
    assert page["markdown"].startswith("# Compression")
    for bad in ("missing", "..%2Fapp", "UPPER"):
        assert client.get(f"/hist/api/help/{bad}").status_code == 404


def test_health_needs_no_token(runtime, fake):
    client = client_for(runtime, fake, None)
    assert client.get("/hist/healthz").json()["status"] == "ok"
    assert client.get("/healthz").status_code == 200
