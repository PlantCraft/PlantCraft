"""The command line every app has (plantcraft_sdk.server.cli)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.server import cli


class Runtime:
    def __init__(self, client):
        self.service_client = client
        self.closed = False

    def shutdown(self):
        self.closed = True


class Client:
    def __init__(self, fail=False):
        self.fail = fail

    def assets(self):
        if self.fail:
            raise PlantCraftError("PlantCraft did not answer.")
        return [{"id": "a"}]

    def signals(self):
        return [{"id": "s1"}, {"id": "s2"}]


def test_the_parser_has_serve_with_the_app_s_host_and_port(monkeypatch):
    monkeypatch.setenv("STARTER_PORT", "9200")
    parser, commands = cli.app_parser(
        "starter", "Command line: x.\n\nMore.", port=9100, serve_help="Serve.", check_help="Check."
    )
    commands.add_parser("other")
    args = parser.parse_args(["serve"])
    assert (args.command, args.host, args.port) == ("serve", "127.0.0.1", 9200)
    assert parser.description == "Command line: x."
    assert parser.parse_args(["check"]).command == "check"
    assert parser.parse_args(["other"]).command == "other"
    monkeypatch.delenv("STARTER_PORT")
    parser, _ = cli.app_parser("starter", None, port=9100, serve_help="Serve.")
    assert parser.parse_args(["serve", "--port", "1"]).port == 1
    assert parser.parse_args(["serve"]).port == 9100


def test_logs_go_to_the_data_folder_only_for_serve(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(
        cli, "configure_logging", lambda app_id, version, data_dir: seen.append(data_dir)
    )
    settings = SimpleNamespace(from_environment=lambda: SimpleNamespace(data_dir=tmp_path))
    cli.start_logs("starter", "1.0.0", settings, "serve")
    cli.start_logs("starter", "1.0.0", settings, "check")
    cli.start_logs("starter", "1.0.0", settings, "check", to_file=True)
    assert seen == [tmp_path, None, tmp_path]


def test_serve_runs_uvicorn_with_the_suite_options(monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: calls.append((app, options)))
    assert cli.serve("app", SimpleNamespace(host="h", port=1), workers=2) == 0
    assert calls == [
        (
            "app",
            {
                "host": "h",
                "port": 1,
                "proxy_headers": True,
                "log_config": None,
                "access_log": False,
                "workers": 2,
            },
        )
    ]


def test_check_answers_one_json_line_and_shuts_the_runtime_down(capsys):
    runtime = Runtime(Client())
    assert cli.check_platform(runtime, notes=lambda: 3) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "assets": 1,
        "signals": 2,
        "notes": 3,
    }
    assert runtime.closed

    runtime = Runtime(None)
    assert cli.check_platform(runtime) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "PLANTCRAFT_APP_KEY is not set."
    assert runtime.closed

    runtime = Runtime(Client(fail=True))
    assert cli.check_platform(runtime) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "error": "PlantCraft did not answer.",
    }
    assert runtime.closed


def test_an_app_s_i18n_module_adds_the_locales_next_to_it(tmp_path):
    from plantcraft_sdk import i18n

    module = tmp_path / "i18n.py"
    i18n.use_app_catalogs(module)
    assert Path(tmp_path / "locales") in i18n._folders
    i18n._folders.remove(tmp_path / "locales")
    i18n.catalog.cache_clear()
