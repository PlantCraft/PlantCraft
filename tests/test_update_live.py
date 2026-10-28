"""Updates through install.sh, against real Docker: a good update stays, a bad one returns.

Runs with ``PLANTCRAFT_UPDATE_LIVE=live`` and the images of ``make image``
(``processcraft``, ``processcraft-proxy``, ``processcraft-installer`` at
``PLANTCRAFT_VERSION``, default the project's). From them it builds, with ``deploy/bundle.sh``,
bundles of three versions as a release would be built: 9.1.0, 9.2.0 and a 9.3.0 whose PlantCraft
stops as it starts. Then, in a temporary install folder, each through ``install.sh``:

- 9.1.0 is installed; the server trusts a publisher key;
- 9.2.0 unsigned is refused with nothing changed; signed, it updates, with a backup first;
- 9.3.0 fails its health check: the suite returns to 9.2.0 by itself, with the data written after
  the update, a record of the attempt and its log;
- 9.1.0 again is refused (going back is a rollback); ``install.sh --rollback`` returns to 9.1.0.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import uuid
from pathlib import Path

import pytest

from processcraft.apps import package, release

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
LIVE = os.environ.get("PLANTCRAFT_UPDATE_LIVE") == "live"
pytestmark = pytest.mark.skipif(not LIVE, reason="set PLANTCRAFT_UPDATE_LIVE=live")
IMAGES = ("processcraft", "processcraft-proxy", "processcraft-installer")
VERSIONS = ("9.1.0", "9.2.0", "9.3.0")
ARCH = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine, os.uname().machine)
BAD = "9.3.0"


def _version() -> str:
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return os.environ.get("PLANTCRAFT_VERSION") or pyproject["project"]["version"]


def _run(*args: str, check: bool = True, env: dict | None = None, timeout: float = 1800,
         stdin: str | None = None) -> subprocess.CompletedProcess:  # fmt: skip
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            env=env, input=stdin)  # fmt: skip
    if check and result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args[:6])}:\n{result.stdout[-4000:]}\n{result.stderr[-4000:]}"
        )
    return result


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def suite(tmp_path_factory):
    base = _version()
    for image in IMAGES:
        _run("docker", "image", "inspect", f"{image}:{base}")
    work = tmp_path_factory.mktemp("update-live")
    for version in VERSIONS:
        for image in IMAGES:
            _run("docker", "tag", f"{image}:{base}", f"{image}:{version}")
    # 9.3.0: PlantCraft stops as it starts (a broken release), so it never becomes healthy.
    (work / "Dockerfile").write_text(
        f"FROM processcraft:{base}\n"
        'CMD ["python", "-c", "raise SystemExit(\'9.3.0 is broken on purpose\')"]\n'
    )
    _run("docker", "build", "-q", "-t", f"processcraft:{BAD}", str(work))
    private, public = package.keygen("processcraft", work / "keys")
    bundles = {}
    for version in VERSIONS:
        environment = {**os.environ, "VERSION": version, "UPGRADE_FROM": "9.1.0",
                       "PYTHON": shutil.which("python") or "python3"}  # fmt: skip
        for app in ("LINKCRAFT", "DASHCRAFT", "HISTCRAFT", "TWINCRAFT", "ALARMCRAFT", "MODELCRAFT"):
            environment[f"{app}_VERSION"] = "0.0.0-none"
        environment["SIMCRAFT_VERSION"] = "0.0.0-none"
        _run(str(DEPLOY / "bundle.sh"), env=environment, timeout=3600)
        bundles[version] = ROOT / "dist" / f"processcraft-{version}-linux-{ARCH}-bundle"
        (ROOT / "dist" / f"processcraft-{version}-linux-{ARCH}-bundle.tar.gz").unlink(
            missing_ok=True
        )

    prefix = work / "install"
    prefix.mkdir()
    project = f"pcupd{uuid.uuid4().hex[:6]}"
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    settings = {
        "COMPOSE_PROJECT_NAME": project,
        "COMPOSE_PROFILES": "",
        "PLANTCRAFT_HOSTNAME": "localhost",
        "PLANTCRAFT_BIND_ADDRESS": "127.0.0.1",
        "PLANTCRAFT_HTTPS_PORT": str(_free_port()),
        "PLANTCRAFT_CPUS": "2",
        "PLANTCRAFT_MEMORY": "2g",
        "PLANTCRAFT_PLANT_SUBNET": "172.31.250.0/24",
        "PLANTCRAFT_APPS_SUBNET": "172.31.251.0/24",
        "PLANTCRAFT_PROXY_ADDRESS": "172.31.251.250",
        "PLANTCRAFT_EDGE_SUBNET": "172.31.252.0/24",
        "PLANTCRAFT_DEMO_SUBNET": "172.31.253.0/24",
        "PLANTCRAFT_HISTDB_SUBNET": "172.31.254.0/24",
    }
    for key, value in settings.items():
        example = re.sub(rf"^{key}=.*$", f"{key}={value}", example, flags=re.MULTILINE)
    (prefix / ".env").write_text(example, encoding="utf-8")

    environment = {**os.environ, "PLANTCRAFT_WAIT_SECONDS": "240"}
    environment.pop("PLANTCRAFT_HOME", None)

    class Suite:
        pass

    s = Suite()
    s.prefix, s.project, s.bundles, s.key, s.public = prefix, project, bundles, private, public

    def install(version: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return _run(str(bundles[version] / "install.sh"), "--yes", "--prefix", str(prefix),
                    *args, env=environment, check=check)  # fmt: skip

    def installed(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return _run(str(prefix / "install.sh"), "--yes", "--prefix", str(prefix), *args,
                    env=environment, check=check)  # fmt: skip

    def env(key: str) -> str:
        text = (prefix / ".env").read_text(encoding="utf-8")
        return re.search(rf"^{key}=(.*)$", text, flags=re.MULTILINE).group(1)

    def as_root(command: str) -> str:
        return _run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--entrypoint",
                    "/bin/sh", "-v", f"{prefix}:/install", f"processcraft:{base}", "-c",
                    command).stdout  # fmt: skip

    def health() -> dict:
        command = ["docker", "run", "--rm", "--network", "none", "--user", "0:0",
                   "-e", f"PLANTCRAFT_INSTALL_DIR={prefix}", "-e", f"COMPOSE_PROJECT_NAME={project}",
                   "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{prefix}:{prefix}",
                   "--entrypoint", "python", f"processcraft-installer:{env('PLANTCRAFT_VERSION')}",
                   "-m", "processcraft.apps.operations", "health"]  # fmt: skip
        result = _run(*command, check=False)
        return json.loads(result.stdout)

    def status(name: str) -> dict:
        return json.loads(as_root(f"cat /install/data/installer/status/{name}"))

    s.install, s.installed, s.env, s.as_root, s.health, s.status = (
        install, installed, env, as_root, health, status,
    )  # fmt: skip
    yield s
    if os.environ.get("PLANTCRAFT_UPDATE_KEEP"):
        return  # left for a look: the install folder, the stack, the bundles
    _run("docker", "compose", "-p", project, "down", "-v", "--remove-orphans", check=False)
    as_root("rm -rf /install/data /install/backups /install/.ops")
    for line in _run(
        "docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"
    ).stdout.split():
        name, _, tag = line.partition(":")
        if name in IMAGES and (tag in VERSIONS or tag.startswith("rollback-")):
            _run("docker", "image", "rm", line, check=False)
    for version in VERSIONS:
        shutil.rmtree(
            ROOT / "dist" / f"processcraft-{version}-linux-{ARCH}-bundle", ignore_errors=True
        )
        (ROOT / "dist" / f"processcraft-{version}-linux-{ARCH}-bundle.tar.gz.sha256").unlink(
            missing_ok=True
        )
    shutil.rmtree(work, ignore_errors=True)


def test_a_first_install_checks_the_signature_against_the_key_it_trusts(suite):
    # Signed with a key that is not the one the bundle carries (deploy/trusted-publishers/).
    release.sign(suite.bundles["9.1.0"], suite.key, "processcraft")
    refused = suite.install("9.1.0", check=False)
    assert refused.returncode != 0
    assert "Nothing was started" in refused.stderr
    assert not (suite.prefix / "data").exists()
    named = suite.prefix.parent / "named"
    named.mkdir()
    shutil.copy(suite.public, named / "processcraft.pub")
    done = suite.install("9.1.0", "--publisher-key", str(named / "processcraft.pub"))
    assert "signed by processcraft (key " in done.stdout
    (suite.bundles["9.1.0"] / release.SIGNATURE).unlink()


def test_install_then_an_unsigned_update_is_refused_with_nothing_changed(suite):
    suite.install("9.1.0", "--allow-unsigned")
    assert suite.env("PLANTCRAFT_VERSION") == "9.1.0"
    assert suite.health()["state"] == "ok"
    suite.as_root("echo before > /install/data/processcraft/marker.txt")
    shutil.copy(suite.public, suite.prefix / "trusted-publishers" / "processcraft.pub")

    refused = suite.install("9.2.0", check=False)
    assert refused.returncode != 0
    assert "not signed" in refused.stderr and "Nothing was changed" in refused.stderr
    assert suite.env("PLANTCRAFT_VERSION") == "9.1.0"
    assert "pre-update" not in suite.as_root("ls /install/backups 2>/dev/null || true")


def test_a_signed_update_backs_up_first_and_stays(suite):
    release.sign(suite.bundles["9.2.0"], suite.key, "processcraft")
    done = suite.install("9.2.0")
    assert "signed by processcraft (key " in done.stderr
    assert suite.env("PLANTCRAFT_VERSION") == "9.2.0"
    assert suite.health() == {"state": "ok", "problems": []}
    update = suite.status("update.json")
    assert (update["from"], update["to"], update["state"]) == ("9.1.0", "9.2.0", "ok")
    assert update["backup"].endswith("-pre-update")
    backups = suite.status("backups.json")["backups"]
    before = next(b for b in backups if b["name"] == update["backup"])
    assert before["state"] == "ok" and before["suite_version"] == "9.1.0"
    assert (suite.prefix / "RELEASE-NOTES.md").read_text().startswith("# PlantCraft 9.2.0")


def test_an_update_that_is_not_healthy_returns_by_itself(suite):
    suite.as_root("echo after > /install/data/processcraft/written-on-9.2.0.txt")
    # 9.2.0 brought the real release key (deploy/trusted-publishers/); these bundles use the test's.
    shutil.copy(suite.public, suite.prefix / "trusted-publishers" / "processcraft.pub")
    release.sign(suite.bundles[BAD], suite.key, "processcraft")
    failed = suite.install(BAD, check=False)
    assert failed.returncode != 0
    assert "returning to 9.2.0 by itself" in failed.stderr
    assert "Back on 9.2.0, healthy" in failed.stderr, failed.stdout[-6000:] + failed.stderr[-3000:]
    assert suite.env("PLANTCRAFT_VERSION") == "9.2.0"
    assert suite.health() == {"state": "ok", "problems": []}
    assert suite.as_root("cat /install/data/processcraft/written-on-9.2.0.txt").strip() == "after"
    update = suite.status("update.json")
    assert (update["to"], update["state"]) == (BAD, "returned")
    logs = list(suite.prefix.glob(f"update-*-{BAD}-failed.log"))
    assert logs and oct(logs[0].stat().st_mode & 0o777) == "0o600"


def test_going_back_is_a_rollback_not_an_install(suite):
    refused = suite.install("9.1.0", check=False)
    assert refused.returncode != 0 and "older than the installed version" in refused.stderr
    assert suite.env("PLANTCRAFT_VERSION") == "9.2.0"
    back = suite.installed("--rollback")
    assert "Back on 9.1.0" in back.stdout
    assert suite.env("PLANTCRAFT_VERSION") == "9.1.0"
    assert suite.health() == {"state": "ok", "problems": []}
    assert suite.as_root("cat /install/data/processcraft/marker.txt").strip() == "before"
    assert suite.status("update.json")["state"] == "rolled-back"
