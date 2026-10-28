"""The installer service (processcraft/apps/installer.py) with a fake Docker CLI.

``tests/fake_docker.py`` records the commands; the installer's files (compose service, proxy
route, state, statuses) are real. ``tests/test_installer_live.py`` runs the same against Docker.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

from processcraft.apps import installer as inst
from processcraft.apps import package as pkg
from tests import app_packages as ap

FAKE = Path(__file__).with_name("fake_docker.py")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    key, trusted = ap.publisher(tmp_path)
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "compose.yaml").write_text("services: {}\n")
    requests = tmp_path / "requests"
    requests.mkdir()
    binary = tmp_path / "bin" / "docker"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    binary.chmod(0o755)
    monkeypatch.setenv("FAKE_DOCKER_DIR", str(tmp_path / "docker"))
    monkeypatch.delenv("FAKE_DOCKER_FAIL", raising=False)
    monkeypatch.delenv("FAKE_DOCKER_WRONG_ID", raising=False)
    installer = inst.Installer(
        install_dir,
        requests_dir=requests,
        trusted_dir=trusted,
        helper_image="processcraft-installer:test",
        docker=inst.Docker(str(binary)),
        project="pc-test",
    )

    class Env:
        pass

    e = Env()
    e.tmp, e.key, e.trusted, e.installer, e.requests = tmp_path, key, trusted, installer, requests
    e.state = install_dir / "data" / "installer"
    e.install_dir = install_dir
    return e


def calls(env) -> list[list[str]]:
    path = env.tmp / "docker" / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def request(env, action: str, app_id: str, package: Path | None = None, **fields) -> str:
    request_id = uuid.uuid4().hex
    if package is not None:
        (env.requests / f"{request_id}.pcapp").write_bytes(package.read_bytes())
    body = {"request_id": request_id, "action": action, "app_id": app_id, "requested_by": "admin"}
    (env.requests / f"{request_id}.json").write_text(json.dumps({**body, **fields}))
    return request_id


def outcome(env, request_id: str) -> dict:
    return json.loads((env.state / "status" / "requests" / f"{request_id}.json").read_text())


def run(env, *args, **kwargs) -> dict:
    rid = request(env, *args, **kwargs)
    env.installer.process_pending()
    return outcome(env, rid)


def test_installed_apps_read_series_from_the_historian_when_it_is_the_data_layer(env, monkeypatch):
    monkeypatch.setenv("HISTCRAFT_URL", "http://histcraft:8100/hist")
    assert run(env, "install", "hello", ap.build(env.tmp / "b", env.key))["state"] == "done"
    compose = json.loads((env.state / "apps" / "hello" / "compose.json").read_text())
    environment = compose["services"]["app-hello"]["environment"]
    assert environment["PLANTCRAFT_HISTORIAN_URL"] == "http://histcraft:8100/hist"


def test_install_writes_a_hardened_service_a_route_and_its_record(env):
    package = ap.build(env.tmp / "b", env.key)
    runtime = ap.template()["runtime"]
    result = run(env, "install", "hello", package)
    assert result["state"] == "done", result
    compose = json.loads((env.state / "apps" / "hello" / "compose.json").read_text())
    service = compose["services"]["app-hello"]
    assert service["image"] == "hello:0.1.0"
    assert service["read_only"] is True and service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["pull_policy"] == "never" and service["networks"] == ["apps"]
    assert service["user"] == f"{runtime['uid']}:{runtime['uid']}"
    assert "ports" not in service and "network_mode" not in service and "privileged" not in service
    assert any(entry.startswith("/tmp:") for entry in service["tmpfs"])
    assert {"cpus", "memory", "pids"} <= set(service["deploy"]["resources"]["limits"])
    assert not any("docker.sock" in volume for volume in service.get("volumes", []))
    assert service["volumes"] == [f"{env.install_dir}/data/apps/hello:/data"]
    assert (env.install_dir / "data" / "apps" / "hello").is_dir()
    assert service["environment"] == {
        "PLANTCRAFT_URL": "http://processcraft:8060",
        "HELLO_ROOT_PATH": "/hello",
        "HELLO_DATA_DIR": "/data",
        "HELLO_HOST": "0.0.0.0",
        "HELLO_PORT": str(runtime["port"]),
    }
    route = (env.state / "routes" / "hello.caddy").read_text()
    assert f"handle /hello/* {{\n\treverse_proxy app-hello:{runtime['port']}\n}}" in route
    # The suite's frame: the person's own pages under the prefix are PlantCraft's (round 8).
    assert "@frame_hello {\n\tpath /hello/*\n\tnot path /hello/api/*\n" in route
    assert route.index("handle @frame_hello") < route.index("handle /hello/*")
    installed = json.loads((env.state / "status" / "installed.json").read_text())["apps"]
    assert [item["app_id"] for item in installed] == ["hello"]
    assert installed[0]["publisher"]["id"] == "testpub" and installed[0]["version"] == "0.1.0"
    versions = env.state / "apps" / "hello" / "versions" / "0.1.0"
    assert sorted(p.name for p in versions.iterdir()) == [
        "manifest.json",
        "manifest.sig",
        "sbom.spdx.json",
    ]
    assert list((env.state / "work").iterdir()) == []
    commands = calls(env)
    assert ["load", "-i"] == commands[0][:2]
    ups = [c for c in commands if c[0] == "compose" and "up" in c]
    assert ups[0][-1] == "app-hello" and ups[1][-1] == "proxy" and "--force-recreate" in ups[1]
    assert all(c[0] != "compose" or c[1:3] == ["--project-name", "pc-test"] for c in commands)


def test_a_manifest_cannot_set_the_container_settings(env):
    """No environment, volumes or ports from the package: only the standard's settings."""

    good = ap.build(env.tmp / "b", env.key)
    for extra in (
        {"environment": {"GREETING": "${COMPOSE_PROJECT_NAME}"}},
        {"volumes": ["/var/run/docker.sock:/s"]},
    ):
        package = ap.resign(good, env.key, env.tmp / "x.pcapp", lambda m, e=extra: m.update(e))
        result = run(env, "install", "hello", package)
        assert result["state"] == "failed" and "unknown sections" in result["message"]
    package = ap.resign(
        good, env.key, env.tmp / "y.pcapp", lambda m: m["runtime"].update(user="0:0")
    )
    result = run(env, "install", "hello", package)
    assert result["state"] == "failed" and "unknown keys" in result["message"]
    assert calls(env) == []


def test_a_tampered_package_is_refused_before_docker_sees_it(env):
    package = ap.build(env.tmp / "b", env.key)
    members = ap.members_of(package)
    members["manifest.json"] = members["manifest.json"].replace(b"/hello/", b"/hallo/")
    tampered = ap.raw(env.tmp / "t.pcapp", list(members.items()))
    result = run(env, "install", "hello", tampered)
    assert result["state"] == "failed" and "signature" in result["message"]
    assert calls(env) == []
    assert not (env.state / "apps" / "hello" / "compose.json").exists()


def test_the_installer_trusts_its_own_keys_not_processcraft(env):
    other_key, _ = ap.publisher(env.tmp / "other", "otherpub")
    package = ap.build(env.tmp / "b", other_key, app={"publisher": "otherpub"})
    result = run(env, "install", "hello", package)
    assert result["state"] == "failed" and "unknown publisher" in result["message"]


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        json.dumps({"action": "install"}),
        json.dumps({"request_id": "x", "action": "install", "app_id": "hello"}),
        json.dumps({"action": "format-disk", "app_id": "hello"}),
        json.dumps({"action": "install", "app_id": "../../etc"}),
        json.dumps({"action": "install", "app_id": "hello", "app_key": "x; rm -rf /"}),
        json.dumps([1, 2, 3]),
        "{" * 70_000,
    ],
)
def test_hostile_requests_fail_cleanly(env, body):
    request_id = uuid.uuid4().hex
    text = body
    if body.startswith("{") and "request_id" not in body and len(body) < 1000:
        text = json.dumps({**json.loads(body), "request_id": request_id})
    (env.requests / f"{request_id}.json").write_text(text)
    env.installer.process_pending()
    assert outcome(env, request_id)["state"] == "failed"
    assert calls(env) == []


def test_symlinked_and_oddly_named_requests_are_ignored(env):
    target = env.tmp / "elsewhere.json"
    target.write_text("{}")
    os.symlink(target, env.requests / f"{uuid.uuid4().hex}.json")
    (env.requests / "../escape.json").write_text("{}")
    (env.requests / "NOT-AN-ID.json").write_text("{}")
    assert env.installer.pending() == []


def test_the_package_must_be_the_app_named_in_the_request(env):
    package = ap.build(env.tmp / "b", env.key)
    result = run(env, "install", "other", package)
    assert result["state"] == "failed" and "not other" in result["message"]


def test_an_image_that_loads_as_something_else_is_refused(env, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_WRONG_ID", "1")
    result = run(env, "install", "hello", ap.build(env.tmp / "b", env.key))
    assert result["state"] == "failed" and "not the verified image" in result["message"]
    assert not (env.state / "apps" / "hello" / "compose.json").exists()


def test_upgrade_rollback_and_uninstall(env):
    first = ap.build(env.tmp / "v1", env.key, version="0.1.0")
    second = ap.build(env.tmp / "v2", env.key, version="0.2.0", image_kwargs={"layer": b"v2"})
    assert run(env, "install", "hello", first)["state"] == "done"
    assert run(env, "install", "hello", second)["state"] == "done"
    state = env.installer.app_state("hello")
    assert state["current"]["version"] == "0.2.0" and state["previous"]["version"] == "0.1.0"
    back = run(env, "rollback", "hello")
    assert back["state"] == "done" and back["version"] == "0.1.0"
    compose = json.loads((env.state / "apps" / "hello" / "compose.json").read_text())
    assert compose["services"]["app-hello"]["image"] == "hello:0.1.0"
    state = env.installer.app_state("hello")
    assert state["current"]["version"] == "0.1.0" and state["previous"]["version"] == "0.2.0"
    gone = run(env, "uninstall", "hello")
    assert gone["state"] == "done"
    assert not (env.state / "apps" / "hello" / "compose.json").exists()
    assert not (env.state / "routes" / "hello.caddy").exists()
    assert json.loads((env.state / "status" / "installed.json").read_text())["apps"] == []
    assert any(c[0] == "compose" and "rm" in c and c[-1] == "app-hello" for c in calls(env))
    assert run(env, "rollback", "hello")["state"] == "failed"


def test_rollback_refuses_a_replaced_image(env):
    run(env, "install", "hello", ap.build(env.tmp / "v1", env.key, version="0.1.0"))
    run(env, "install", "hello", ap.build(env.tmp / "v2", env.key, version="0.2.0"))
    docker_state = env.tmp / "docker" / "state.json"
    images = json.loads(docker_state.read_text())
    images["images"]["hello:0.1.0"] = "sha256:" + "f" * 64  # retagged behind the installer's back
    docker_state.write_text(json.dumps(images))
    result = run(env, "rollback", "hello")
    assert result["state"] == "failed" and "no longer the one installed" in result["message"]


def test_a_failed_start_puts_the_previous_version_back(env, monkeypatch):
    run(env, "install", "hello", ap.build(env.tmp / "v1", env.key, version="0.1.0"))
    before = (env.state / "apps" / "hello" / "compose.json").read_text()
    monkeypatch.setenv("FAKE_DOCKER_FAIL", "up:app-hello")
    result = run(env, "install", "hello", ap.build(env.tmp / "v2", env.key, version="0.2.0"))
    assert result["state"] == "failed" and "previous state is back" in result["message"]
    assert (env.state / "apps" / "hello" / "compose.json").read_text() == before
    assert env.installer.app_state("hello")["current"]["version"] == "0.1.0"


def test_a_failed_first_start_leaves_nothing_behind(env, monkeypatch):
    monkeypatch.setenv("FAKE_DOCKER_FAIL", "up:app-hello")
    result = run(env, "install", "hello", ap.build(env.tmp / "b", env.key))
    assert result["state"] == "failed"
    assert not (env.state / "apps" / "hello" / "compose.json").exists()
    assert not (env.state / "routes" / "hello.caddy").exists()
    assert json.loads((env.state / "status" / "installed.json").read_text())["apps"] == []


def test_prefixes_are_never_shared(env):
    assert run(env, "install", "hello", ap.build(env.tmp / "a", env.key))["state"] == "done"
    clash = ap.build(env.tmp / "b", env.key, app_id="other", runtime={"prefix": "/hello/"})
    result = run(env, "install", "other", clash)
    assert result["state"] == "failed" and "already served by hello" in result["message"]


@pytest.mark.parametrize("key", ["port", "uid"])
def test_ports_and_users_are_each_containers_own(env, key):
    """Scale review E5 (2026-10-25): each app runs in its own container, so two apps may
    listen on the same port and run as the same user; only the prefix is the installation's."""

    assert run(env, "install", "hello", ap.build(env.tmp / "a", env.key))["state"] == "done"
    taken = ap.template()["runtime"][key]
    same = ap.build(env.tmp / "b", env.key, app_id="other", runtime={key: taken})
    assert run(env, "install", "other", same)["state"] == "done"


def test_an_app_may_name_no_port_and_no_user(env):
    runtime = {"port": None, "uid": None}
    package = ap.build(env.tmp / "c", env.key, app_id="bare", runtime=runtime)
    assert run(env, "install", "bare", package)["state"] == "done"
    service = json.loads((env.state / "apps" / "bare" / "compose.json").read_text())
    user = next(iter(service["services"].values()))["user"]
    assert user == f"{pkg.default_uid('bare')}:{pkg.default_uid('bare')}"
    assert (
        pkg.default_uid("bare") == pkg.default_uid("bare")
        and 20000 <= pkg.default_uid("bare") < 60000
    )


def test_an_app_of_the_suite_table_installs_with_its_row(env):
    row = {"prefix": "/cpm/", "port": 8070, "uid": 10002, "image": "cpmcraft"}
    package = ap.build(env.tmp / "c", env.key, app_id="cpmcraft", runtime=row)
    assert run(env, "install", "cpmcraft", package)["state"] == "done"
    service = json.loads((env.state / "apps" / "cpmcraft" / "compose.json").read_text())
    service = service["services"]["app-cpmcraft"]
    assert service["user"] == "10002:10002"
    assert service["environment"]["CPMCRAFT_ROOT_PATH"] == "/cpm"


def test_an_app_key_reaches_only_its_app(env):
    package = ap.build(env.tmp / "b", env.key)
    key = "pck_0123456789ab." + "k" * 43
    assert run(env, "install", "hello", package, app_key=key)["state"] == "done"
    secret = env.state / "secrets" / "hello" / "app-key"
    assert secret.read_text().strip() == key
    service = json.loads((env.state / "apps" / "hello" / "compose.json").read_text())
    service = service["services"]["app-hello"]
    assert service["environment"]["PLANTCRAFT_APP_KEY_FILE"] == "/run/secrets/hello_app_key"
    assert f"{secret}:/run/secrets/hello_app_key:ro" in service["volumes"]
    status = (env.state / "status" / "requests").glob("*.json")
    assert all(key not in path.read_text() for path in status)
    assert key not in (env.state / "status" / "installed.json").read_text()


def test_each_app_runs_as_its_own_user(env):
    run(env, "install", "hello", ap.build(env.tmp / "a", env.key))
    run(env, "install", "other", ap.build(env.tmp / "b", env.key, app_id="other"))
    users = {env.installer.app_state(app)["current"]["uid"] for app in ("hello", "other")}
    assert users == {ap.template(app)["runtime"]["uid"] for app in ("hello", "other")}


def test_heartbeat_and_health(env):
    assert not inst.healthy(env.state)
    env.installer.serve(stop_after=1)
    assert inst.healthy(env.state)
    beat = json.loads((env.state / "status" / "heartbeat.json").read_text())
    assert beat["trusted_publishers"] == ["testpub"]


def test_the_command_line_adds_and_removes(env, monkeypatch, capsys):
    monkeypatch.setenv("PLANTCRAFT_INSTALL_DIR", str(env.install_dir))
    monkeypatch.setenv("PLANTCRAFT_APP_REQUESTS", str(env.requests))
    monkeypatch.setenv("PLANTCRAFT_TRUSTED_PUBLISHERS", str(env.trusted))
    monkeypatch.setenv("PLANTCRAFT_DOCKER", str(env.tmp / "bin" / "docker"))
    package = ap.build(env.tmp / "b", env.key)
    assert inst.main(["add", str(package), "--by", "operator"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "done"
    installed = json.loads((env.state / "status" / "installed.json").read_text())["apps"]
    assert installed[0]["requested_by"] == "cli:operator"
    assert inst.main(["list"]) == 0 and "hello" in capsys.readouterr().out
    assert inst.main(["remove", "hello"]) == 0
    assert inst.main(["remove", "hello"]) == 1
    capsys.readouterr()
    tampered = env.tmp / "junk.pcapp"
    tampered.write_bytes(b"junk")
    assert inst.main(["add", str(tampered)]) == 1
    assert "not a readable package" in capsys.readouterr().out
    assert list((env.state / "work").iterdir()) == []


def test_the_package_tool_ships_in_the_installer(env, capsys):
    package = ap.build(env.tmp / "b", env.key)
    assert inst.main(["package", "verify", "--trusted", str(env.trusted), str(package)]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "hello"


def test_the_installer_imports_only_the_package_module():
    import ast

    tree = ast.parse(Path(inst.__file__).read_text())
    found = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("processcraft")
        ):
            found.add(node.module)
    assert found == {"processcraft.apps"}
    assert pkg.__name__ == "processcraft.apps.package"


def test_an_operation_request_starts_the_driver_once(env):
    request_id = request(env, "backup", None)
    assert env.installer.process_pending() == 1
    assert outcome(env, request_id)["state"] == "running"
    driver = [call for call in calls(env) if "processcraft-ops" in call]
    assert len(driver) == 1
    assert driver[0][-6:] == ["drive", "backup", "--request-id", request_id, "--reason", "manual"]
    assert "--network" in driver[0] and driver[0][driver[0].index("--network") + 1] == "none"
    assert env.installer.process_pending() == 0  # the driver reports; never started twice


def test_operation_requests_are_checked(env, monkeypatch):
    bad = request(env, "restore", None, name="../../etc")
    env.installer.process_pending()
    assert outcome(env, bad) == {**outcome(env, bad), "state": "failed"}
    assert "invalid backup name" in outcome(env, bad)["message"]
    monkeypatch.setenv("FAKE_DOCKER_DRIVER", "1")
    busy = request(env, "restore", None, name="20261021-020000-daily")
    env.installer.process_pending()
    assert "another operation is running" in outcome(env, busy)["message"]


def test_the_daily_backup_starts_once_a_day(env):
    from datetime import datetime, timezone

    early = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
    late = datetime(2026, 10, 21, 2, 30, tzinfo=timezone.utc)
    assert env.installer.run_schedule(early) is None
    assert env.installer.run_schedule(late) == "backup"
    assert env.installer.run_schedule(late) is None
    (env.requests / "ops-settings.json").write_text('{"backup": {"enabled": false}}')
    assert env.installer.run_schedule(datetime(2026, 10, 22, 3, tzinfo=timezone.utc)) is None


def test_a_new_installation_starts_before_its_first_backup(env):
    from datetime import datetime, timezone

    # installed at 07:40, after the daily time: no backup or drill while the suite starts
    installed = datetime(2026, 10, 25, 7, 40, tzinfo=timezone.utc)
    assert env.installer.run_schedule(installed) is None
    assert env.installer.run_schedule(installed.replace(minute=50)) is None
    assert env.installer.run_schedule(installed.replace(minute=56)) == "backup"
    # Sunday: the week's drill once the backup is taken
    assert env.installer.run_schedule(installed.replace(minute=57)) == "drill"


def test_an_interrupted_operation_is_resumed_first(env):
    (env.state / "status" / "operation.json").write_text('{"action": "restore"}')
    from datetime import datetime, timezone

    assert env.installer.run_schedule(datetime(2026, 10, 21, 1, tzinfo=timezone.utc)) == "resume"
    assert any("resume" in call for call in calls(env) if "processcraft-ops" in call)


def test_a_diagnostic_bundle_holds_no_secret(env, monkeypatch):
    import zipfile

    run(env, "install", "hello", ap.build(env.tmp / "b", env.key))
    monkeypatch.setenv("PLANTCRAFT_PASSWORD", "admin-secret-9")
    monkeypatch.setenv("HISTCRAFT_DATABASE_URL", "postgresql://hist:db-secret-7@histcraft-db/hist")
    monkeypatch.setenv("PLANTCRAFT_VERSION", "0.2.0")
    (env.state / "status" / "release.json").write_text('{"version": "0.2.0"}')
    result = run(env, "diagnostics", None)
    assert result["state"] == "done", result
    path = env.state / "status" / "diagnostics" / result["file"]
    with zipfile.ZipFile(path) as bundle:
        names = set(bundle.namelist())
        text = "\n".join(bundle.read(name).decode() for name in names)
    assert {"diagnostics/README.txt", "diagnostics/settings.env", "diagnostics/compose-ps.json",
            "diagnostics/status/release.json", "diagnostics/logs/app-hello.log",
            "diagnostics/host.json", "diagnostics/docker-info.json"} <= names  # fmt: skip
    assert "PLANTCRAFT_VERSION=0.2.0" in text and "PLANTCRAFT_PASSWORD=***" in text
    for secret in ("admin-secret-9", "db-secret-7", "sekret-token-123"):
        assert secret not in text
    assert not any(name.endswith((".sqlite3", ".key", ".pem", ".dump")) for name in names)
    # kept 24 h
    os.utime(path, (0, 0))
    assert env.installer.prune_diagnostics() == 1 and not path.exists()


def test_diagnostics_from_the_command_line(env, monkeypatch, capsysbinary):
    import io
    import zipfile

    monkeypatch.setenv("PLANTCRAFT_INSTALL_DIR", str(env.install_dir))
    monkeypatch.setenv("PLANTCRAFT_APP_REQUESTS", str(env.requests))
    monkeypatch.setenv("PLANTCRAFT_TRUSTED_PUBLISHERS", str(env.trusted))
    monkeypatch.setenv("PLANTCRAFT_DOCKER", env.installer.docker.binary)
    assert inst.main(["diagnostics", "--out", "-"]) == 0
    data = capsysbinary.readouterr().out
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        assert "diagnostics/README.txt" in bundle.namelist()
