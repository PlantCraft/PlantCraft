"""app.toml and ``plantcraft-app check`` (docs/app-standard.md, sections 4, 5 and 7)."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

import pytest

from plantcraft_sdk import app_cli
from plantcraft_sdk.app_cli import check, main
from plantcraft_sdk.app_manifest import ManifestError, parse_manifest

APP_TOML = '''
[app]
id = "cpmcraft"
name = "CPMCraft"
version = "0.1.0"
category = "Control loop performance"
summary = "Finds control loops that oscillate, stick or sit in manual, and says why."
description = """One paragraph for the Apps page."""
publisher = "PlantCraft"
license = "Apache-2.0"
homepage = ""
mark = "cpmcraft"

[runtime]
prefix = "/cpm/"
port = 8070
uid = 10002
health = "/healthz"
image = "cpmcraft"

[requires]
platform = ">=0.6,<0.8"
processcraft_api = ">=1.0"
sdk = "0.2.0"
asset_types = ["loop"]
roles = { loop = ["pv", "op"] }

[permissions]
read = ["assets", "signals", "series", "results"]
write = ["audit", "results", "events", "runs", "schedules"]
plant_write = false
outbound = []

[publishes]
results = [{ kind = "loop_health", subject = "asset:loop" }]
events = ["finding.opened", "finding.closed"]

[consumes]
results = [{ kind = "datacraft.signal_quality", subject = "signal" }]

[suggests]
asset_types = ["loop"]
'''
WHEEL = b"not really a wheel"
UI = b"not really a package"
FILES = {
    "README.md": "# CPMCraft\n",
    "AGENTS.md": "",
    "CLAUDE.md": "",
    "SPEC.md": "",
    "ROADMAP.md": "",
    "SECURITY.md": "",
    "LICENSE": "",
    "ATTRIBUTION.md": "",
    "CHANGELOG.md": "# Changelog\n\n## [0.1.0] - 2026-10-21\n\n### Added\n\n- First release.\n",
    "Makefile": f"ci: {' '.join(app_cli.CI_STEPS)}\n"
    + "".join(f"{name}:\n\t@true\n" for name in app_cli.MAKE_TARGETS if name != "ci"),
    "Dockerfile": "FROM scratch\n",
    "pyproject.toml": '[project]\nname = "cpmcraft"\nversion = "0.1.0"\n\n'
    "[tool.ruff]\nline-length = 100\n",
    "deploy/requirements.in": "",
    "deploy/requirements.lock": "",
    "vendor/README.md": "plantcraft-sdk 0.2.0\n\nSHA-256: "
    + hashlib.sha256(WHEEL).hexdigest()
    + "\n\n@plantcraft/ui 0.1.0\n\nSHA-256: "
    + hashlib.sha256(UI).hexdigest()
    + "\n",
    "src/cpmcraft/cli.py": "from plantcraft_sdk.server.logs import configure_logging\n"
    'configure_logging("cpmcraft", version="0.1.0")\n',
    "src/cpmcraft/api/__init__.py": "",
    "frontend/vite.config.ts": "export default { build: { assetsDir: 'static' } };\n",
    "frontend/package.json": '{"dependencies": {"@plantcraft/ui": '
    '"file:../vendor/plantcraft-ui-0.1.0.tgz"}}\n',
    "frontend/src/App.tsx": 'import { SuiteShell } from "@plantcraft/ui";\n',
    "tests/floors.toml": "",
    "docs/STATUS.md": "",
    "docs/gaps.md": "",
    "docs/devlog.md": "",
    "docs/help/index.md": "",
}


def _repo(root: Path) -> Path:
    (root / "app.toml").write_text(APP_TOML)
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "vendor" / "plantcraft_sdk-0.2.0-py3-none-any.whl").write_bytes(WHEEL)
    (root / "vendor" / "plantcraft-ui-0.1.0.tgz").write_bytes(UI)
    return root


def _manifest(**changes) -> dict:
    data = tomllib.loads(APP_TOML)
    for dotted, value in changes.items():
        table, key = dotted.split("__")
        if value is None:
            data[table].pop(key)
        else:
            data[table][key] = value
    return data


def test_the_reference_manifest_is_valid():
    manifest = parse_manifest(tomllib.loads(APP_TOML))
    assert manifest.app.id == "cpmcraft" and manifest.runtime.prefix == "/cpm/"
    # A bare name declares an event titled by its name.
    events = manifest.to_json()["publishes"]["events"]
    assert [item["name"] for item in events] == ["finding.opened", "finding.closed"]
    assert events[0]["title"] == "finding.opened" and events[0]["phase"] == "instant"


@pytest.mark.parametrize(
    ("changes", "needle"),
    [
        ({"app__id": "CPM"}, "app.id"),
        ({"app__id": "newcraft", "runtime__image": "newcraft"}, "prefix /cpm/ belongs to cpmcraft"),
        ({"app__name": "Cpm Tool"}, "app.name"),
        ({"app__name": "DataCraft"}, "name of cpmcraft is 'CPMCraft'"),
        ({"app__version": "1.0"}, "app.version"),
        ({"app__summary": None}, "app.summary: required"),
        ({"app__homepage": "http://example.test"}, "homepage"),
        ({"app__colour": "red"}, "unknown key"),
        ({"runtime__prefix": "/cpmcraft/"}, "prefix of cpmcraft"),
        ({"runtime__prefix": "cpm"}, "runtime.prefix"),
        ({"runtime__port": 8071}, "port of cpmcraft is 8070"),
        ({"runtime__port": 80}, "runtime.port"),
        ({"runtime__uid": 10003}, "uid of cpmcraft is 10002"),
        ({"runtime__image": "cpm"}, "image is named after the app id"),
        ({"requires__sdk": ">=0.2"}, "requires.sdk"),
        ({"requires__processcraft_api": "1.0"}, "requires.processcraft_api"),
        ({"requires__roles": {"valve": ["op"]}}, "roles name types not in asset_types"),
        ({"permissions__plant_write": True}, "plant_write is always false"),
        ({"permissions__outbound": ["example.test"]}, "outbound is []"),
        ({"permissions__write": ["plant"]}, "unknown write permissions"),
        ({"permissions__read": ["database"]}, "unknown read permissions"),
        ({"publishes__results": [{"kind": "cpmcraft.loop_health", "subject": "asset"}]}, "bare"),
        ({"publishes__results": [{"kind": "loop_health", "subject": "tag"}]}, "subject"),
        ({"publishes__events": ["cpmcraft.finding.opened.now.really"]}, "<noun>.<verb>"),
        ({"consumes__results": [{"kind": "signal_quality", "subject": "signal"}]}, "<app id>"),
    ],
)
def test_manifests_that_break_the_standard(changes, needle):
    with pytest.raises(ManifestError) as error:
        parse_manifest(_manifest(**changes))
    assert needle in str(error.value), str(error.value)


def test_unknown_tables_and_simcraft_without_prefix():
    with pytest.raises(ManifestError, match="unknown key"):
        parse_manifest({**tomllib.loads(APP_TOML), "extras": {}})
    data = _manifest(
        app__id="simcraft",
        app__name="PlantCraft Simulator",
        app__mark="simcraft",
        runtime__prefix="",
        runtime__port=4840,
        runtime__uid=10004,
        runtime__image="simcraft",
    )
    assert parse_manifest(data).runtime.prefix == ""


def _outside(**changes) -> dict:
    base = {
        "app__id": "starter",
        "app__name": "StarterCraft",
        "app__mark": "starter",
        "runtime__prefix": "/starter/",
        "runtime__port": 9100,
        "runtime__uid": 20100,
        "runtime__image": "starter",
    }
    return _manifest(**{**base, **changes})


def test_an_app_outside_the_suite_table_takes_free_values():
    assert parse_manifest(_outside()).app.id == "starter"
    # Its port is its own container's (scale review E5): a suite app's is no clash.
    assert parse_manifest(_outside(runtime__port=8140)).runtime.port == 8140


def test_an_app_may_name_no_port_and_no_user():
    from plantcraft_sdk.app_manifest import DEFAULT_PORT, default_uid

    manifest = parse_manifest(_outside(runtime__port=None, runtime__uid=None))
    assert manifest.runtime.port == DEFAULT_PORT
    assert manifest.runtime.uid == default_uid("starter") and 20000 <= manifest.runtime.uid < 60000


@pytest.mark.parametrize(
    ("changes", "needle"),
    [
        ({"app__name": "PlantCraft Starter"}, "kept for the suite's own apps"),
        ({"runtime__prefix": "/hist/"}, "prefix /hist/ belongs to histcraft"),
        ({"runtime__uid": 10005}, "stack of PlantCraft (installer)"),
        ({"runtime__uid": 65534}, "uid is between 10002 and 65533"),
        ({"runtime__image": "other"}, "image is named after the app id"),
    ],
)
def test_an_app_outside_the_suite_table_collides_with_nothing(changes, needle):
    with pytest.raises(ManifestError) as error:
        parse_manifest(_outside(**changes))
    assert needle in str(error.value), str(error.value)


def test_check_passes_on_a_repository_that_follows_the_standard(tmp_path, capsys):
    root = _repo(tmp_path)
    report = check(root)
    assert report.ok and report.warnings == [], report
    assert main(["check", str(root)]) == 0
    assert "follows the standard" in capsys.readouterr().out


def test_check_fails_with_clear_errors(tmp_path, capsys):
    root = _repo(tmp_path)
    (root / "SPEC.md").unlink()
    (root / "docs" / "help" / "index.md").unlink()
    (root / "docs" / "help").rmdir()
    (root / "pyproject.toml").write_text('[project]\nname = "cpmcraft"\nversion = "0.2.0"\n')
    (root / "vendor" / "README.md").write_text("plantcraft-sdk 0.2.0, no hash here\n")
    (root / "Makefile").write_text("ci:\n\t@true\n")
    errors = check(root).errors
    assert "SPEC.md: missing (section 5)" in errors
    assert "docs/help/: missing folder (section 5)" in errors
    assert any("version '0.2.0' differs from app.toml's '0.1.0'" in e for e in errors)
    assert any("no SHA-256 line" in e for e in errors)
    assert any(e.startswith("Makefile: missing targets deps, standard, lint") for e in errors)
    assert main(["check", str(root)]) == 1
    assert "problem(s)" in capsys.readouterr().err


def test_check_finds_a_wheel_that_does_not_match(tmp_path):
    root = _repo(tmp_path)
    (root / "vendor" / "plantcraft_sdk-0.2.0-py3-none-any.whl").write_bytes(b"changed")
    assert any("no SHA-256 line matches" in e for e in check(root).errors)


def test_check_accepts_a_sha256sum_block(tmp_path):
    root = _repo(tmp_path)
    digest = hashlib.sha256(WHEEL).hexdigest()
    (root / "vendor" / "README.md").write_text(
        f"```\n{digest}  plantcraft_sdk-0.2.0-py3-none-any.whl\n"
        f"{hashlib.sha256(UI).hexdigest()}  plantcraft-ui-0.1.0.tgz\n```\n"
    )
    assert not any("SHA-256" in e for e in check(root).errors)


def test_check_reports_a_bad_manifest_and_a_missing_one(tmp_path):
    assert check(tmp_path).errors == ["app.toml: missing (section 4)"]
    root = _repo(tmp_path)
    (root / "app.toml").write_text(APP_TOML.replace("plant_write = false", "plant_write = true"))
    assert any("plant_write is always false" in e for e in check(root).errors)
    (root / "app.toml").write_text("[app\n")
    assert any("not valid TOML" in e for e in check(root).errors)


def test_check_wants_the_suite_frame(tmp_path):
    root = _repo(tmp_path)
    (root / "frontend" / "src" / "App.tsx").write_text("export const topnav = true;\n")
    assert any("SuiteShell" in e for e in check(root).errors)
    (root / "vendor" / "plantcraft-ui-0.1.0.tgz").write_bytes(b"changed")
    assert any("no SHA-256 line matches plantcraft-ui" in e for e in check(root).errors)
    (root / "frontend" / "package.json").write_text('{"dependencies": {}}\n')
    assert any("depend on @plantcraft/ui" in e for e in check(root).errors)


def test_check_warns_when_vite_keeps_assets_dir(tmp_path):
    root = _repo(tmp_path)
    (root / "frontend" / "vite.config.ts").write_text("export default {};\n")
    report = check(root)
    assert report.ok and any("assetsDir to 'static'" in w for w in report.warnings)


def test_check_holds_the_operations_rules(tmp_path):
    root = _repo(tmp_path)
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## [0.0.9] - 2026-10-01\n")
    (root / "src" / "cpmcraft" / "cli.py").write_text(
        'DATABASE = "cpmcraft.sqlite3"\nimport uvicorn\nuvicorn.run(app)\n'
    )
    errors = check(root).errors
    assert "CHANGELOG.md: no entry for 0.1.0 (## [0.1.0] - <date>)" in errors
    assert any("[backup] sqlite does not name cpmcraft.sqlite3" in e for e in errors)
    assert any("configure_logging" in e for e in errors)
    assert any("log_config=None" in e for e in errors)
    (root / "app.toml").write_text(APP_TOML + '\n[backup]\nsqlite = ["cpmcraft.sqlite3"]\n')
    (root / "CHANGELOG.md").write_text("## [0.1.0] - 2026-10-21\n")
    (root / "src" / "cpmcraft" / "cli.py").write_text(
        'DATABASE = "cpmcraft.sqlite3"\nconfigure_logging("cpmcraft", version="0.1.0")\n'
        "uvicorn.run(app, log_config=None)\n"
    )
    assert check(root).ok, check(root).errors


@pytest.mark.parametrize(
    ("backup", "needle"),
    [
        ({"sqlite": ["/etc/passwd"]}, "backup.sqlite.0"),
        ({"files": ["../other/"]}, "without '..'"),
        ({"sqlite": ["data/"]}, "names a database file"),
        ({"sqlite": ["a.sqlite3"], "skip": ["a.sqlite3"]}, "named more than once"),
        ({"keep": ["x"]}, "unknown key"),
    ],
)
def test_backup_table_rules(backup, needle):
    data = _manifest()
    data["backup"] = backup
    with pytest.raises(ManifestError) as caught:
        parse_manifest(data)
    assert any(needle in problem for problem in caught.value.problems), caught.value.problems


def test_backup_table_accepts_data_paths():
    data = _manifest()
    data["backup"] = {"sqlite": ["cpmcraft.sqlite3"], "files": ["uploads/", "secret.key"]}
    assert parse_manifest(data).backup.files == ["uploads/", "secret.key"]


def test_every_app_ci_runs_the_same_steps(tmp_path):
    root = _repo(tmp_path)
    makefile = root / "Makefile"
    makefile.write_text(
        makefile.read_text().replace(f"ci: {' '.join(app_cli.CI_STEPS)}", "ci: deps lint test")
    )
    errors = check(root).errors
    assert any(e.startswith("Makefile: ci runs deps lint test;") for e in errors)
