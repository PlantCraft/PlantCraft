"""The suite's rule checks for app tests, and the test time budget plugin."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from plantcraft_sdk import apptest

pytest_plugins = ["pytester"]


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _app(root: Path) -> Path:
    _write(root, "src/demo/__init__.py", "")
    _write(root, "src/demo/config.py", "import os\n")
    _write(root, "src/demo/store.py", "from demo import config\n")
    _write(root, "src/demo/api/runtime.py", "import httpx\nPlantCraftClient(1)\n")
    _write(root, "src/demo/api/app.py", "from demo.api import runtime\nfrom demo import store\n")
    _write(root, "frontend/index.html", '<script src="/static/app.js"></script>')
    _write(root, "frontend/src/styles.css", "body { color: red; }")
    _write(root, "frontend/src/main.tsx", 'fetch("/api/me")')
    return root


def test_a_tidy_app_has_no_problems(tmp_path):
    root = _app(tmp_path)
    assert apptest.offline_problems(root, "demo") == []
    assert apptest.layer_problems(root, "demo", {"config": 0, "store": 1, "api": 2}) == []


def test_offline_problems_name_each_remote_load(tmp_path):
    root = _app(tmp_path)
    _write(root, "frontend/index.html", '<link href="https://fonts.example.com/x.css">')
    _write(root, "frontend/src/styles.css", '@import url("https://cdn.example.com/a.css");')
    _write(root, "frontend/src/main.tsx", 'fetch("https://telemetry.example.com/")')
    _write(root, "src/demo/store.py", "import requests\nPlantCraftClient(2)\n")
    problems = apptest.offline_problems(root, "demo")
    assert len(problems) == 5, problems
    assert any("store.py opens network connections (requests)" in p for p in problems)
    assert any("builds a PlantCraftClient" in p for p in problems)


def test_layer_problems_find_upward_imports_other_apps_and_missing_layers(tmp_path):
    root = _app(tmp_path)
    _write(root, "src/demo/config.py", "from demo import store\nimport linkcraft\nimport asyncua\n")
    _write(root, "src/demo/extra.py", "")
    problems = apptest.layer_problems(root, "demo", {"config": 0, "store": 1, "api": 2})
    assert "config.py -> store (points up)" in problems
    assert "config.py imports linkcraft" in problems and "config.py imports asyncua" in problems
    assert "extra: no layer (add it to the layer table)" in problems
    allowed = apptest.layer_problems(
        root, "demo", {"config": 0, "store": 1, "api": 2, "extra": 0}, allowed={"asyncua"}
    )
    assert "config.py imports asyncua" not in allowed


def test_suite_problems_keep_plantcraft_calls_in_suite(tmp_path):
    root = _app(tmp_path)
    _write(root, "src/demo/suite/events.py", "from plantcraft_sdk.events import EventCatalog\n")
    _write(
        root, "src/demo/api/routers/notes.py", "def f(rt):\n    rt.service_client.post_events([])\n"
    )
    _write(root, "src/demo/jobs.py", "from plantcraft_sdk.events import EventCatalog\n")
    assert apptest.suite_problems(root, "demo") == [
        "api/routers/notes.py talks to PlantCraft (service_client): move it to suite/",
        "jobs.py talks to PlantCraft (EventCatalog): move it to suite/",
    ]


def test_router_problems_name_stores_and_drivers(tmp_path):
    root = _app(tmp_path)
    _write(root, "src/demo/api/routers/ok.py", "from demo.notes.service import NoteService\n")
    _write(
        root,
        "src/demo/api/routers/bad.py",
        "import sqlite3\nfrom demo.notes.store import NoteStore\n",
    )
    problems = apptest.router_problems(root, "demo")
    assert problems == [
        "api/routers/bad.py imports demo.notes.store",
        "api/routers/bad.py imports sqlite3",
    ]


def test_contribution_problems_pair_each_table_with_code(tmp_path):
    root = _app(tmp_path)
    _write(
        root,
        "app.toml",
        '[[publishes.events]]\nname = "note.written"\n'
        '[contributes.search]\ntypes = ["Note"]\n'
        '[[contributes.calendar]]\nid = "follow-ups"\n'
        '[[contributes.llm]]\nid = "summary"\n'
        '[[contributes.refs]]\nkind = "demo_note"\n',
    )
    _write(root, "src/demo/suite/llm.py", 'USE = "summary"\nEVENT = f"{APP}.note.written"\n')
    problems = apptest.contribution_problems(root, "demo", [("GET", "/api/notes")])
    assert problems == [
        "calendar feed 'follow-ups' is declared but no code sends it",
        "search is declared but no route answers /api/search",
        "reference kind 'demo_note' is declared but no route names it",
    ]
    routes = [("GET", "/api/search"), ("GET", "/api/refs/demo_note/{id}")]
    assert len(apptest.contribution_problems(root, "demo", routes)) == 1


def test_ui_copy_problems_find_copies_of_the_shared_ui(tmp_path):
    root = _app(tmp_path)
    ui = tmp_path / "ui"
    _write(ui, "DataTable.tsx", "export const table = 1;\n")
    _write(root, "frontend/src/Table.tsx", "export const table = 1;\n")
    _write(root, "frontend/src/Plot.tsx", "export {};\n")
    _write(root, "frontend/src/HelpPage.tsx", 'import { AppHelp } from "@plantcraft/ui";\n')
    _write(ui, "plotly-cartesian.d.ts", "declare module 'x';\n")
    _write(root, "frontend/src/plotly-cartesian.d.ts", "declare module 'x';\n")
    _write(root, "frontend/src/brandTheme.ts", 'export { brandTheme } from "@plantcraft/ui";\n')
    assert apptest.ui_copy_problems(root, ui) == [
        "frontend/src/Plot.tsx: the suite's Plot comes from @plantcraft/ui",
        "frontend/src/Table.tsx is a copy of @plantcraft/ui's DataTable.tsx",
    ]
    _write(root, "frontend/src/brandTheme.ts", "export function brandTheme() {}\n")
    assert len(apptest.ui_copy_problems(root)) == 2


def test_image_problems_follow_app_toml(tmp_path):
    _write(
        tmp_path,
        "app.toml",
        '[app]\nid = "demo"\nsummary = "Does things."\n'
        '[runtime]\nprefix = "/demo/"\nport = 8999\nuid = 10099\nhealth = "/healthz"\n',
    )
    _write(tmp_path, "Dockerfile", "USER 10099:10099\nEXPOSE 8999\n")
    problems = apptest.image_problems(tmp_path)
    assert "Dockerfile: no the health check (127.0.0.1:8999/healthz)" in problems
    assert any("SBOM at build" in p for p in problems)
    assert "Dockerfile: the description label is not app.toml's summary" in problems
    _write(
        tmp_path,
        "Dockerfile",
        "ARG APP_PORT=8999\nARG APP_UID=10099\nUSER ${APP_UID}:${APP_UID}\nEXPOSE ${APP_PORT}\n",
    )
    assert not any("uid" in p or "port (" in p for p in apptest.image_problems(tmp_path))


def test_hostile_failures_report_server_errors_only():
    api = FastAPI()

    @api.get("/api/things/{thing_id}")
    def thing(thing_id: str) -> dict:
        if thing_id == "boom":
            raise RuntimeError("crash")
        return {"id": thing_id}

    @api.post("/api/things")
    def make(body: dict) -> dict:
        return body

    app = FastAPI()
    app.state.api = api
    app.mount("/demo", api)
    client = TestClient(app, base_url="http://testserver/demo/", raise_server_exceptions=False)
    assert apptest.api_routes(app) == [("GET", "/api/things/{thing_id}"), ("POST", "/api/things")]
    failures, answered = apptest.hostile_failures(client, real={"thing_id": "boom"})
    assert answered > 20
    assert len(failures) == 3 and all("-> 500" in failure for failure in failures)


def test_the_budget_fails_a_slow_test_unless_marked(pytester):
    pytester.makepyprojecttoml("[tool.plantcraft.tests]\ntest_seconds = 0.2\nslow_seconds = 5\n")
    pytester.makepyfile(
        """
        import time, pytest

        def test_quick():
            pass

        def test_sluggish():
            time.sleep(0.4)

        @pytest.mark.slow
        def test_marked():
            time.sleep(0.4)
        """
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=3)
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*test_sluggish: * s (a test gets 0.2 s)*"])
    assert "test_marked" not in "\n".join(
        line for line in result.stdout.lines if "a slow test gets" in line
    )


def test_without_a_budget_table_nothing_is_checked(pytester):
    pytester.makepyfile("import time\n\ndef test_sluggish():\n    time.sleep(0.3)\n")
    result = pytester.runpytest()
    assert result.ret == 0


def test_the_test_plant_serves_every_loop_to_one_app():
    from plantcraft_sdk.testplant import LOOPS, NOW, plant_assets, plant_fake

    fake = plant_fake("demo", "Demo", "/demo/")
    loops = [asset for asset in plant_assets() if asset["kind"] == "loop"]
    assert [asset["id"] for asset in loops] == [loop.loop_id for loop in LOOPS]
    assert set(loops[0]["signals"]) == {"pv", "sp", "op"}
    assert fake.now == NOW
    assert fake.token("operator")
