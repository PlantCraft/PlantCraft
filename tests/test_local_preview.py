"""dev/local_preview.py (make preview, make preview-light): its light proxy routes as the suite's
Caddy proxy does, and it never installs into another suite's folder."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_preview", ROOT / "dev" / "local_preview.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)

PLATFORM = "http://127.0.0.1:8270"
ROUTES = {prefix: f"http://127.0.0.1:{8271 + i}" for i, (_, _, prefix) in enumerate(preview.APPS)}


def scope(path: str, *, document: bool = False, signed_in: bool = False, query: bytes = b""):
    headers = []
    if document:
        headers.append((b"sec-fetch-dest", b"document"))
    if signed_in:
        headers.append((b"cookie", b"a=1; processcraft_token=xyz"))
    return {"path": path, "headers": headers, "query_string": query}


def test_apps_and_frame_match_the_caddy_proxy():
    caddy = (ROOT / "deploy" / "proxy" / "Caddyfile").read_text()
    handled = set(re.findall(r"^\thandle (/[a-z]+/)\*", caddy, re.M))
    assert handled == {prefix for _, _, prefix in preview.APPS}
    frame = re.search(r"@frame \{\n\t\tpath ([^\n]+)", caddy).group(1)
    assert {item.rstrip("*") for item in frame.split()} == set(preview.FRAMED)


@pytest.mark.parametrize(
    ("request_scope", "expected"),
    [
        (scope("/"), (PLATFORM, True)),
        (scope("/api/login"), (PLATFORM, True)),
        (scope("/link"), ("redirect", "/link/")),
        (scope("/link/api/loops", document=True, signed_in=True), (ROUTES["/link/"], False)),
        (scope("/link/static/app.js"), (ROUTES["/link/"], False)),
        # A signed-in person's page under an app is PlantCraft's frame...
        (scope("/link/algorithms", document=True, signed_in=True), (PLATFORM, True)),
        # ...unless the app's page is asked for itself, or nobody is signed in.
        (
            scope("/link/algorithms", document=True, signed_in=True, query=b"pc-frame=off"),
            (ROUTES["/link/"], False),
        ),
        (scope("/dash/share/x", document=True), (ROUTES["/dash/"], False)),
        # Documents is framed like every other app (the visit's clock, the platform's sidebar)...
        (scope("/doc/", document=True, signed_in=True), (PLATFORM, True)),
        # ...but its API and its files (Open the PDF, Download) stay the app's.
        (
            scope("/doc/api/documents/x/file", document=True, signed_in=True),
            (ROUTES["/doc/"], False),
        ),
    ],
)
def test_upstream(request_scope, expected):
    assert preview.upstream(request_scope, PLATFORM, ROUTES) == expected


def test_never_installs_over_another_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(preview, "FORBIDDEN", [tmp_path / "PlantCraft"])
    with pytest.raises(SystemExit):
        preview.check_folder(preview.Layout(tmp_path / "PlantCraft", 8260))
    with pytest.raises(SystemExit):
        preview.check_folder(preview.Layout(tmp_path / "PlantCraft" / "preview", 8260))
    other = preview.Layout(tmp_path / "elsewhere", 8260)
    other.suite.mkdir(parents=True)
    (other.suite / ".env").write_text("COMPOSE_PROJECT_NAME=processcraft\n")
    with pytest.raises(SystemExit):
        preview.check_folder(other)
    (other.suite / ".env").write_text(f"COMPOSE_PROJECT_NAME={preview.PROJECT}\n")
    preview.check_folder(other)


def test_ports_do_not_meet():
    layout = preview.Layout(Path("/tmp/x"), 8260)
    ports = [layout.port, layout.site_port, layout.platform_port]
    ports += [layout.app_port(index) for index in range(len(preview.APPS))]
    assert len(set(ports)) == len(ports)
    assert preview.OPCUA_PORT != 4840  # the Simulator of `python run_opcua_demo.py`
