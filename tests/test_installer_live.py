"""App installs against real Docker: the suite from install.sh --dev, a tiny test app, both ways in.

Runs with ``PLANTCRAFT_INSTALLER_LIVE=live`` and the images of ``make image`` (version from
``PLANTCRAFT_VERSION``, default the project version). It installs a stack into a temporary
folder, builds ``hello:0.1.0`` and ``hello:0.2.0`` (Python's HTTP server on the PlantCraft
image), signs them with an ephemeral key, then:

- ``deploy/package.sh --app app.toml`` builds each package;
- ``install.sh --add`` installs 0.1.0; the proxy serves it at /hello/;
- the Apps page API uploads 0.2.0, confirms, sees it running; rolls back to 0.1.0; uninstalls;
- the app container runs as described (read-only, no capabilities, apps network only).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from tests import app_packages as ap

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
LIVE = os.environ.get("PLANTCRAFT_INSTALLER_LIVE") == "live"
pytestmark = pytest.mark.skipif(not LIVE, reason="set PLANTCRAFT_INSTALLER_LIVE=live")

APP_DOCKERFILE = """
FROM processcraft:{base}
ENV HELLO_VERSION={version}
HEALTHCHECK --interval=2s --timeout=3s --retries=20 \\
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8099/hello/', timeout=2)"]
CMD ["python", "-c", "import http.server, os\\nclass H(http.server.BaseHTTPRequestHandler):\\n    def do_GET(self):\\n        body = ('hello ' + os.environ['HELLO_VERSION'] + ' uid ' + str(os.getuid())).encode()\\n        self.send_response(200); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)\\nhttp.server.ThreadingHTTPServer(('0.0.0.0', 8099), H).serve_forever()"]
"""


def _version() -> str:
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return os.environ.get("PLANTCRAFT_VERSION") or pyproject["project"]["version"]


def _run(
    *args: str, check: bool = True, timeout: float = 900, **kwargs
) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)
    if check and result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args[:6])} failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )
    return result


class Suite:
    def __init__(self, prefix: Path, port: int):
        self.prefix, self.port = prefix, port
        self.context = ssl.create_default_context()
        self.context.check_hostname = False
        self.context.verify_mode = ssl.CERT_NONE  # the suite's own local CA, on localhost
        self.cookies: dict[str, str] = {}

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        files = ["-f", str(self.prefix / "compose.yaml")]
        for path in sorted((self.prefix / "data" / "installer" / "apps").glob("*/compose.json")):
            files += ["-f", str(path)]
        return _run("docker", "compose", "--project-directory", str(self.prefix), *files,
                    "--env-file", str(self.prefix / ".env"), *args, check=check)  # fmt: skip

    def request(self, method: str, path: str, body: bytes | None = None, json_body=None):
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"https://localhost:{self.port}{path}", data=body, method=method, headers=headers
        )
        try:
            response = urllib.request.urlopen(request, context=self.context, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        for header in response.headers.get_all("Set-Cookie") or []:
            name, _, rest = header.partition("=")
            self.cookies[name] = rest.split(";", 1)[0]
        return response.status, response.read()

    def wait_for(self, check, timeout: float = 240):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                value = check()
            except OSError:  # the proxy restarts when an app's route changes
                value = None
            if value:
                return value
            time.sleep(2)
        raise AssertionError("timed out")


@pytest.fixture(scope="module")
def suite(tmp_path_factory):
    version = _version()
    for image in ("processcraft", "processcraft-proxy", "processcraft-installer"):
        if _run("docker", "image", "inspect", f"{image}:{version}", check=False).returncode:
            pytest.fail(f"image {image}:{version} is missing: run make image")
    prefix = tmp_path_factory.mktemp("apps-live")
    port = int(os.environ.get("PLANTCRAFT_INSTALLER_LIVE_PORT", "18543"))
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    settings = {
        "COMPOSE_PROJECT_NAME": "pc-apps-live",
        "PLANTCRAFT_HOSTNAME": "localhost",
        "PLANTCRAFT_BIND_ADDRESS": "127.0.0.1",
        "PLANTCRAFT_HTTPS_PORT": str(port),
        "PLANTCRAFT_CPUS": "2",
        "PLANTCRAFT_MEMORY": "2g",
        "PLANTCRAFT_PLANT_SUBNET": "172.31.250.0/24",
        "PLANTCRAFT_APPS_SUBNET": "172.31.251.0/24",
        "PLANTCRAFT_PROXY_ADDRESS": "172.31.251.250",
        "PLANTCRAFT_EDGE_SUBNET": "172.31.252.0/24",
    }
    for key, value in settings.items():
        example = re.sub(rf"^{key}=.*$", f"{key}={value}", example, flags=re.MULTILINE)
    (prefix / ".env").write_text(example, encoding="utf-8")
    environment = {**os.environ, "PLANTCRAFT_HOME": str(prefix), "PLANTCRAFT_VERSION": version}
    running = Suite(prefix, port)
    keys = prefix.parent / f"{prefix.name}-keys"
    keys.mkdir()
    try:
        _run(str(DEPLOY / "install.sh"), "--dev", "--yes", env=environment, timeout=900)
        key, trusted = ap.publisher(keys)
        shutil.copy(trusted / "testpub.pub", prefix / "trusted-publishers" / "testpub.pub")
        running.key, running.version, running.keys = key, version, keys
        running.password = (prefix / "data" / "initial-admin-password").read_text().strip()
        yield running
    finally:
        running.compose("down", "-v", "--remove-orphans", check=False)
        _run("docker", "run", "--rm", "--network", "none", "--user", "0:0", "--entrypoint",
             "/bin/sh", "-v", f"{prefix}:/install", f"processcraft:{version}", "-c",
             "rm -rf /install/data /install/backups", check=False)  # fmt: skip
        shutil.rmtree(prefix, ignore_errors=True)
        shutil.rmtree(keys, ignore_errors=True)


def _package(suite: Suite, version: str) -> Path:
    tag = f"hello:{version}"
    dockerfile = APP_DOCKERFILE.format(base=suite.version, version=version)
    _run("docker", "build", "-q", "-t", tag, "-", input=dockerfile, timeout=600)
    work = suite.keys / version
    work.mkdir(exist_ok=True)
    manifest = work / "app.toml"
    manifest.write_text(_toml(ap.template("hello", version, runtime={"port": 8099})))
    sbom = work / "sbom.spdx.json"
    sbom.write_text(json.dumps(ap.SBOM))
    _run(str(DEPLOY / "package.sh"), "--app", str(manifest), "--key", str(suite.key),
         "--sbom", str(sbom), "--out", str(work))  # fmt: skip
    _run("docker", "image", "rm", tag)  # the package is now the only copy: docker load must work
    return work / f"hello-{version}.pcapp"


def _toml(sections: dict) -> str:
    """A small app.toml writer for the test app (strings, numbers, booleans, lists)."""

    lines = []
    for name, table in sections.items():
        lines.append(f"[{name}]")
        for key, value in table.items():
            lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def _hello(suite: Suite) -> str | None:
    status, body = suite.request("GET", "/hello/")
    return body.decode() if status == 200 and body.startswith(b"hello") else None


def test_add_from_the_command_line_then_upgrade_rollback_and_remove_from_the_page(suite):
    first = _package(suite, "0.1.0")
    environment = {**os.environ, "PLANTCRAFT_HOME": str(suite.prefix)}
    added = _run(str(suite.prefix / "install.sh"), "--add", str(first), env=environment)
    assert '"state": "done"' in added.stdout, added.stdout
    served = suite.wait_for(lambda: _hello(suite))
    assert served.startswith("hello 0.1.0")

    container = suite.compose("ps", "-q", "app-hello").stdout.strip()
    info = json.loads(_run("docker", "inspect", container).stdout)[0]
    host = info["HostConfig"]
    assert host["ReadonlyRootfs"] is True and host["CapDrop"] == ["ALL"]
    assert "no-new-privileges:true" in host["SecurityOpt"] and not host["Privileged"]
    assert list(info["NetworkSettings"]["Networks"]) == ["pc-apps-live_apps"]
    assert not any(binding for binding in (info["NetworkSettings"]["Ports"] or {}).values())
    uid = ap.template("hello")["runtime"]["uid"]
    assert info["Config"]["User"] == f"{uid}:{uid}", "the uid of app.toml"
    assert "HELLO_ROOT_PATH=/hello" in info["Config"]["Env"]
    assert not any("docker.sock" in mount["Source"] for mount in info["Mounts"])
    key_file = suite.compose(
        "exec", "-T", "app-hello", "cat", "/run/secrets/hello_app_key", check=False
    )
    assert key_file.returncode != 0 or not key_file.stdout.strip(), "a CLI install has no key yet"

    status, _ = suite.request(
        "POST", "/api/login", json_body={"username": "admin", "password": suite.password}
    )
    assert status == 200

    def listed():
        status, body = suite.request("GET", "/api/apps")
        apps = {item["id"]: item for item in json.loads(body)["apps"]} if status == 200 else {}
        return apps.get("hello")

    row = suite.wait_for(listed)
    assert row["status"] == "running" and row["installed_by"].startswith("cli:")
    _, body = suite.request("GET", "/api/apps")
    assert json.loads(body)["installer"]["online"] is True

    second = _package(suite, "0.2.0")
    status, body = suite.request("POST", "/api/apps/packages", body=second.read_bytes())
    assert status == 201, body
    preview = json.loads(body)
    assert preview["replaces"] == "0.1.0" and preview["app"]["publisher"]["id"] == "testpub"
    status, body = suite.request("POST", f"/api/apps/packages/{preview['upload_id']}/install")
    assert status == 202, body
    row = suite.wait_for(
        lambda: (r := listed()) and r["status"] == "running" and r["version"] == "0.2.0" and r
    )
    assert row["previous_version"] == "0.1.0"
    assert suite.wait_for(lambda: (h := _hello(suite)) and h.startswith("hello 0.2.0") and h)
    secret = suite.compose("exec", "-T", "app-hello", "cat", "/run/secrets/hello_app_key")
    assert secret.stdout.startswith("pck_"), "the page's install issued an app key"

    status, _ = suite.request("POST", "/api/apps/hello/rollback")
    assert status == 202
    suite.wait_for(lambda: (r := listed()) and r["status"] == "running" and r["version"] == "0.1.0")
    assert suite.wait_for(lambda: (h := _hello(suite)) and h.startswith("hello 0.1.0") and h)

    status, _ = suite.request("POST", "/api/apps/hello/uninstall")
    assert status == 202
    suite.wait_for(lambda: listed() is None)
    assert not suite.compose("ps", "-q", "app-hello", check=False).stdout.strip()
    assert not (suite.prefix / "data" / "installer" / "routes" / "hello.caddy").exists()
    status, body = suite.request("GET", "/hello/")
    assert not body.startswith(b"hello"), "the route is gone"
    logs = subprocess.run(["docker", "compose", "--project-directory", str(suite.prefix), "-f",
                            str(suite.prefix / "compose.yaml"), "--env-file", str(suite.prefix / ".env"),
                            "logs", "installer"], capture_output=True, text=True)  # fmt: skip
    assert "watching" in logs.stdout + logs.stderr


def test_a_tampered_package_never_reaches_docker(suite):
    package = _package(suite, "0.3.0")
    members = ap.members_of(package)
    members["manifest.json"] = members["manifest.json"].replace(b"/hello/", b"/hallo/")
    tampered = ap.raw(suite.keys / "tampered.pcapp", list(members.items()))
    environment = {**os.environ, "PLANTCRAFT_HOME": str(suite.prefix)}
    result = _run(
        str(suite.prefix / "install.sh"), "--add", str(tampered), env=environment, check=False
    )
    assert result.returncode != 0 and "signature" in result.stdout + result.stderr
    assert _run("docker", "image", "inspect", "hello:0.3.0", check=False).returncode != 0
