"""The offline deployment keeps every app container away from the internet and the plant.

Two layers (docs/install-offline.md, docs/security-guide.md):

- Static checks of ``deploy/compose.yaml``, the Dockerfiles and the proxy configuration. They
  always run, with or without Docker, so CI enforces them on every change.
- Live checks with ``PLANTCRAFT_ISOLATION=live`` (``make isolation``, the CI job
  ``isolation``): ``deploy/install.sh --dev`` installs the stack into a temporary folder, a
  stand-in serves each app (``linkcraft``, ``dashcraft``, ``histcraft`` and its database,
  ``alarmcraft``, ``modelcraft``) whose image is not built, and the tests try to reach the internet and the plant from
  inside the containers. The Simulator (``simcraft``,
  profile ``demo``) runs from its own image when ``simcraft:$SIMCRAFT_VERSION`` is built
  (``make simcraft-image``); CI cannot build it (the Simulator is a separate repository), so
  there a stand-in listens on the demo network at ``simcraft:4840`` instead and the plant
  checks still run.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.request
import warnings
from pathlib import Path
from typing import Any

import pytest

# PyYAML comes with uvicorn[standard] (the `server` extra).
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
COMPOSE_FILE = DEPLOY / "compose.yaml"

PROXY = "proxy"
# The services on the plant network: PlantCraft and Historian, the historian, which reads its
# own sources (OPC UA, PI Web API, CSV), with its collector. Every other service except the proxy is an app.
PLANT_SERVICES = {"processcraft", "histcraft", "histcraft-collector", "histcraft-gateway"}
# The Simulator, the demo's simulator, shares an internal network with PlantCraft and Historian
# only.
DEMO_SERVICES = {
    "processcraft",
    "simcraft",
    "histcraft",
    "histcraft-collector",
    "histcraft-gateway",
}
EXPECTED_NETWORKS = {
    "proxy": {"edge", "apps"},
    "processcraft": {"plant", "apps", "demo", "llm", "compute"},
    # The local compute worker: PlantCraft only (it asks for tasks; it opens no port).
    "compute-gateway": {"compute"},
    # The one way out to a language model in the cloud: PlantCraft in, the providers out.
    "llm-egress": {"llm", "egress"},
    "simcraft": {"demo"},
    "histcraft": {"plant", "apps", "demo", "histdb"},
    "histcraft-collector": {"plant", "demo", "histdb"},
    # Telegraf: MQTT, Modbus and SQL sources in, the collector out; never the database.
    "histcraft-gateway": {"plant", "demo"},
    "histcraft-db": {"histdb"},
}
# Historian's database network: Historian, its collector and its database only.
HISTDB_SERVICES = {"histcraft", "histcraft-collector", "histcraft-db"}
# llm-egress (plantcraft/egress): the only service that resolves internet names, and opens a
# tunnel only to the hosts of the language model providers PlantCraft lists.
LLM_EGRESS = "llm-egress"
LLM_SERVICES = {"processcraft", LLM_EGRESS}
# The apps of the suite compose.yaml runs (docs/app-standard.md, section 7), each in the
# profile named after it: id -> (prefix, port, uid, root path variable).
APPS = {
    "linkcraft": ("/link/", 8140, "10012", "LINKCRAFT_ROOT_PATH"),
    "dashcraft": ("/dash/", 8080, "10006", "DASHCRAFT_ROOT_PATH"),
    "histcraft": ("/hist/", 8100, "10008", "HISTCRAFT_ROOT_PATH"),
    "alarmcraft": ("/alarm/", 8110, "10009", "ALARMCRAFT_ROOT_PATH"),
    "modelcraft": ("/model/", 8130, "10011", "MODELCRAFT_ROOT_PATH"),
    "doccraft": ("/doc/", 8150, "10015", "DOCCRAFT_ROOT_PATH"),
}
# PlantCraft Models' Modelica runner compiles and runs models: no network at all, no secret,
# only the jobs folder it shares with PlantCraft Models.
MODELCRAFT_RUNNER = "modelcraft-executor"
MODELCRAFT_RUNNER_IMAGE = "modelcraft-runner"
# The apps' executors on the local compute worker (docs/compute.md): they run what people wrote.
EXECUTORS = {"linkcraft-executor": "linkcraft", MODELCRAFT_RUNNER: "modelcraft"}
# An executor runs its app's own image, but for Models' runner (OpenModelica's, same version).
EXECUTOR_IMAGES = {MODELCRAFT_RUNNER: f"{MODELCRAFT_RUNNER_IMAGE}:${{MODELCRAFT_VERSION:-0.5.1}}"}
# The app's setting that sends its work to the compute workers (default `suite`).
COMPUTE_SETTINGS = {"linkcraft": "LINKCRAFT_COMPUTE", "modelcraft": "MODELCRAFT_RUNNER"}
# Services with no network at all.
# Code sandboxes an app reaches only through a socket in a shared folder (sandbox_remote).
CODE_SANDBOXES = {"alarmcraft-sandbox": "alarmcraft"}
NO_NETWORK = {"installer", *EXECUTORS, *CODE_SANDBOXES}
HISTCRAFT_DB = "histcraft-db"
HISTCRAFT_GATEWAY = "histcraft-gateway"
# Apps that need no app key (Historian reads its own sources).
KEYLESS_APPS = {"histcraft"}
OUTSIDE = ("1.1.1.1", 443)
# Names a container must not resolve: with Docker's default upstream servers one of them would.
EXTERNAL_NAMES = ("github.com", "pypi.org", "example.com")
# Upstream DNS that keeps lookups inside the container (nothing listens there): service names
# still resolve through Docker's embedded resolver, every other name fails at once.
NO_DNS = "127.0.0.1"
# The one service with the Docker socket (docs/app-package.md): no network at all.
INSTALLER = "installer"
INSTALLER_VOLUMES = {
    "/var/run/docker.sock:/var/run/docker.sock",
    "./compose.yaml:${PLANTCRAFT_INSTALL_DIR:-/opt/processcraft}/compose.yaml:ro",
    "./data/installer:${PLANTCRAFT_INSTALL_DIR:-/opt/processcraft}/data/installer",
    "./data/app-requests:/requests:ro",
    "./trusted-publishers:/trusted-publishers:ro",
}
# The Notebooks kits people download (an optional part of the bundle) are read-only too.
READ_ONLY_MOUNTS = {
    "./certs:/certs:ro",
    "./trusted-publishers:/trusted-publishers:ro",
    "./notebook-kits:/notebook-kits:ro",
}


def _compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _services() -> dict[str, dict[str, Any]]:
    return _compose()["services"]


def _networks_of(service: dict[str, Any]) -> set[str]:
    networks = service.get("networks", [])
    return set(networks if isinstance(networks, list) else networks.keys())


def _uid(user: str) -> str:
    return str(user).split(":", 1)[0].strip()


# Static checks: always run ---------------------------------------------------------------


def test_simcraft_runs_its_own_image() -> None:
    """The demo plant is the Simulator's image (uid 10004), serving its loop portfolio."""

    plant = _services()["simcraft"]
    assert plant["image"] == "simcraft:${SIMCRAFT_VERSION:-0.5.1}"
    assert _uid(plant["user"]) == "10004"
    assert plant["command"][:3] == ["simcraft", "loops", "serve"]
    endpoint = plant["command"][plant["command"].index("--endpoint") + 1]
    assert endpoint == "opc.tcp://0.0.0.0:4840/plantcraft/"
    assert plant["healthcheck"]["test"] == ["CMD", "python", "-m", "simcraft.healthcheck"]
    assert plant["environment"]["SIMCRAFT_HISTORY_DB"].startswith("/data/")
    assert plant["environment"]["SIMCRAFT_STATE_DB"].startswith("/data/")
    assert plant["volumes"] == ["./data/simcraft:/data"]
    assert "SIMCRAFT_VERSION=" in (DEPLOY / ".env.example").read_text(encoding="utf-8")


def test_compose_has_the_expected_services() -> None:
    services = _services()
    assert {"proxy", "processcraft", "simcraft", INSTALLER, HISTCRAFT_DB} | set(APPS) <= set(
        services
    )
    for app in APPS:
        assert services[app]["profiles"] == [app], app
    assert services[HISTCRAFT_DB]["profiles"] == ["histcraft"]
    assert services["simcraft"]["profiles"] == ["demo"]
    assert "profiles" not in services["proxy"]
    assert "profiles" not in services["processcraft"]
    assert "profiles" not in services[INSTALLER]


def test_only_the_proxy_publishes_a_port() -> None:
    for name, service in _services().items():
        if name == PROXY:
            continue
        assert "ports" not in service, f"{name} publishes a port; only the proxy may"
        expected_mode = "none" if name in NO_NETWORK else None
        assert service.get("network_mode") == expected_mode, f"{name} sets network_mode"
    ports = _services()[PROXY]["ports"]
    assert len(ports) == 1
    assert str(ports[0]).endswith(":8443"), "the proxy publishes only its HTTPS listener"


@pytest.mark.parametrize("name", sorted(_services()))
def test_every_service_is_hardened(name: str) -> None:
    service = _services()[name]
    assert _uid(service.get("user", "")) not in {"", "0", "root"}, f"{name} runs as root"
    assert service.get("read_only") is True, f"{name}: root filesystem must be read-only"
    assert service.get("cap_drop") == ["ALL"], f"{name} keeps Linux capabilities"
    assert not service.get("cap_add"), f"{name} adds capabilities"
    assert "no-new-privileges:true" in service.get("security_opt", [])
    assert not service.get("privileged")
    for key in ("pid", "ipc", "userns_mode", "uts"):
        assert service.get(key) != "host", f"{name} shares the host {key} namespace"
    assert any(str(entry).startswith("/tmp:") for entry in service.get("tmpfs", []))
    healthcheck = service.get("healthcheck", {})
    assert healthcheck.get("test") and not healthcheck.get("disable"), f"{name}: no healthcheck"
    assert service.get("restart") in {"unless-stopped", "always", "on-failure"}
    limits = service.get("deploy", {}).get("resources", {}).get("limits", {})
    assert {"cpus", "memory", "pids"} <= set(limits), f"{name}: missing resource limits"
    assert service.get("pull_policy") == "never", f"{name} could be pulled from the internet"
    image = service["image"]
    assert ":" in image and not image.endswith(":latest"), f"{name}: image not pinned"


@pytest.mark.parametrize("name", sorted(_services()))
def test_state_lives_in_the_install_folder(name: str) -> None:
    volumes = [str(volume) for volume in _services()[name].get("volumes", [])]
    if name == INSTALLER:
        assert set(volumes) == INSTALLER_VOLUMES, volumes
    for volume in volumes:
        source = volume.split(":", 1)[0]
        if name != INSTALLER:
            assert "docker.sock" not in volume, f"{name} mounts the Docker socket"
        assert (
            source.startswith("./data/")
            or volume in READ_ONLY_MOUNTS
            or (name == INSTALLER and volume in INSTALLER_VOLUMES)
        ), f"{name}: {volume} is outside ./data (only ./certs and trusted keys, read-only)"
    for secret in _compose().get("secrets", {}).values():
        assert secret["file"].startswith("./data/")
    assert "volumes" not in _compose(), "named volumes would live outside ./data"


def test_only_the_installer_reaches_docker() -> None:
    """The Docker socket is root on the host: one service has it, without any network."""

    for name, service in _services().items():
        mounts_socket = any("docker.sock" in str(volume) for volume in service.get("volumes", []))
        assert mounts_socket == (name == INSTALLER), name
    installer = _services()[INSTALLER]
    assert installer["network_mode"] == "none" and "networks" not in installer
    assert installer["image"].startswith("processcraft-installer:")
    assert _uid(installer["user"]) == "10005"


def test_networks_separate_edge_apps_and_plant() -> None:
    compose = _compose()
    networks = compose["networks"]
    assert networks["apps"].get("internal") is True
    assert networks["demo"].get("internal") is True
    assert networks["histdb"].get("internal") is True
    assert not networks["plant"].get("internal")
    assert networks["llm"].get("internal") is True
    assert not networks["egress"].get("internal")
    edge_options = networks["edge"].get("driver_opts", {})
    assert edge_options.get("com.docker.network.bridge.enable_ip_masquerade") == "false"
    for name, service in compose["services"].items():
        networks_of = _networks_of(service)
        if name in NO_NETWORK:
            assert networks_of == set() and service["network_mode"] == "none"
        elif name in EXPECTED_NETWORKS:
            assert networks_of == EXPECTED_NETWORKS[name], name
        else:
            assert networks_of == {"apps"}, f"app container {name} must be only on `apps`"
        if name not in PLANT_SERVICES:
            assert "plant" not in networks_of
        if name not in DEMO_SERVICES:
            assert "demo" not in networks_of
        if name not in HISTDB_SERVICES:
            assert "histdb" not in networks_of, f"{name} could reach histcraft-db"
        if name not in LLM_SERVICES:
            assert "llm" not in networks_of, f"{name} could reach llm-egress"
        if name != LLM_EGRESS:
            assert "egress" not in networks_of, f"{name} is on llm-egress's way out"


def test_no_service_resolves_names_outside_the_suite() -> None:
    """Docker forwards lookups of a service on a routed network to the host's DNS servers.

    Every such service names the loopback address instead (PlantCraft: unless
    PLANTCRAFT_DNS names the plant's DNS server); a service only on internal networks gets
    no forwarded lookups from Docker.
    """

    compose = _compose()
    internal = {name for name, network in compose["networks"].items() if network.get("internal")}
    for name, service in compose["services"].items():
        if name == INSTALLER or _networks_of(service) <= internal:
            continue
        if name == LLM_EGRESS:
            assert service.get("dns") == ["${PLANTCRAFT_LLM_DNS:-1.1.1.1}"]
            continue
        expected = ["${PLANTCRAFT_DNS:-127.0.0.1}"] if name in PLANT_SERVICES else [NO_DNS]
        assert service.get("dns") == expected, f"{name} resolves names through the host"
    assert compose["services"]["simcraft"]["dns"] == [NO_DNS]
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^PLANTCRAFT_DNS=$", example, re.MULTILINE)
    assert re.search(r"^PLANTCRAFT_DEMO_SUBNET=\S+$", example, re.MULTILINE)


def test_llm_egress_opens_only_what_plantcraft_lists() -> None:
    """PlantCraft writes the providers' hosts; llm-egress only reads them, runs PlantCraft's
    image with the proxy command, holds no secret, and PlantCraft calls models through it."""

    services = _services()
    gate = services[LLM_EGRESS]
    assert gate["image"].startswith("processcraft:") and _uid(gate["user"]) == "10014"
    assert gate["command"] == ["python", "-m", "plantcraft.egress", "serve"]
    assert gate["volumes"] == ["./data/egress:/egress:ro"]
    assert "secrets" not in gate and "profiles" not in gate
    assert gate["environment"]["PLANTCRAFT_EGRESS_ALLOWLIST"] == "/egress/allow.json"
    platform = services["processcraft"]
    assert "./data/egress:/egress" in platform["volumes"]
    assert platform["environment"]["PLANTCRAFT_LLM_PROXY"] == "http://llm-egress:3128"
    assert platform["environment"]["PLANTCRAFT_EGRESS_ALLOWLIST"] == "/egress/allow.json"


@pytest.mark.parametrize("app", sorted(APPS))
def test_apps_follow_the_linkcraft_pattern(app: str) -> None:
    """Each app: its uid, PlantCraft inside the network, its app key as a secret file, its
    prefix, its own data folder, a health check on its port and a route in the proxy."""

    prefix, port, uid, root_variable = APPS[app]
    service = _services()[app]
    assert service["image"] == f"{app}:${{{app.upper()}_VERSION:-0.5.1}}"
    assert service["user"] == f"{uid}:{uid}"
    environment = service["environment"]
    assert environment["PLANTCRAFT_URL"] == "http://processcraft:8060"
    assert environment[root_variable] == prefix.rstrip("/")
    if app not in KEYLESS_APPS:
        assert environment["PLANTCRAFT_APP_KEY_FILE"] == f"/run/secrets/{app}_app_key"
        assert f"{app}_app_key" in service["secrets"]
        assert _compose()["secrets"][f"{app}_app_key"]["file"] == f"./data/{app}-app-key"
    assert service["volumes"][0] == f"./data/{app}:/data"
    assert f"127.0.0.1:{port}/healthz" in " ".join(service["healthcheck"]["test"])
    assert service["depends_on"]["processcraft"]["condition"] == "service_healthy"
    assert f"{app.upper()}_VERSION=" in (DEPLOY / ".env.example").read_text(encoding="utf-8")
    caddyfile = (DEPLOY / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    # A restarting app is dialled again for 15 s instead of answering 502 (ci/macmini/README.md).
    upstream = rf"reverse_proxy {app}:{port} \{{\s*import upstream 15s\s*\}}"
    assert re.search(rf"handle {prefix}\* \{{\s*{upstream}\s*\}}", caddyfile)


def test_the_modelica_runner_is_a_sandbox() -> None:
    """PlantCraft Models compiles and runs models on the compute workers only (its runner,
    `modelcraft-executor`, OpenModelica's image): Models itself shares no folder with it."""

    services = _services()
    runner, models = services[MODELCRAFT_RUNNER], services["modelcraft"]
    assert runner["image"] == EXECUTOR_IMAGES[MODELCRAFT_RUNNER]
    assert runner["command"][:2] == ["python3", "/opt/runner/runner.py"]
    assert models["volumes"] == ["./data/modelcraft:/data"]
    assert "MODELCRAFT_JOBS_DIR" not in models["environment"]


def test_the_compute_executors_are_sandboxes() -> None:
    """An app's executor runs the code people wrote (docs/compute.md): no network, no secret,
    only its app's jobs folder, which it shares with compute-gateway alone; the gateway holds
    the worker's credential and reaches PlantCraft only."""

    services = _services()
    gateway = services["compute-gateway"]
    assert gateway["networks"] == ["compute"] and gateway["user"] == "10020:10020"
    assert gateway["volumes"] == ["./data/compute-jobs:/jobs"]
    assert gateway["secrets"] == ["compute_local_key"]
    for name, app in EXECUTORS.items():
        executor = services[name]
        assert executor["profiles"] == [app]
        image = EXECUTOR_IMAGES.get(name, services[app]["image"])
        assert executor["image"] == image, "the app's own image and version"
        assert executor["user"] == gateway["user"]
        assert executor["network_mode"] == "none" and "networks" not in executor
        assert "secrets" not in executor and "depends_on" not in executor
        assert executor["volumes"] == [f"./data/compute-jobs/{app}:/jobs"]
        assert not any(
            key in str(executor.get("environment", {})) for key in ("KEY", "TOKEN", "PASSWORD")
        )
        limits = executor["deploy"]["resources"]["limits"]
        assert limits["pids"] <= 1024 and limits["memory"] and limits["cpus"]
        assert services[app]["environment"][COMPUTE_SETTINGS[app]].endswith(":-suite}")
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "chown -R $COMPUTE_UID:$COMPUTE_UID data/compute-jobs" in install


def test_a_worker_on_another_machine_is_as_closed() -> None:
    """compose-worker.yaml (install.sh --worker): the same hardening, the gateway on its one
    network out to PlantCraft with no port, each executor with no network, the app's image."""

    worker = yaml.safe_load((DEPLOY / "compose-worker.yaml").read_text(encoding="utf-8"))
    services, suite = worker["services"], _services()
    assert set(services) == {"compute-gateway", *EXECUTORS}
    for name, service in services.items():
        assert service["user"] == "10020:10020", name
        assert service["read_only"] is True and service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert service["pull_policy"] == "never" and "ports" not in service, name
        assert service["healthcheck"]["test"], name
        assert "secrets" not in service, name
    gateway = services["compute-gateway"]
    assert gateway["networks"] == ["out"] and gateway["image"] == suite["processcraft"]["image"]
    assert "./data/worker:/worker" in gateway["volumes"]
    for name, app in EXECUTORS.items():
        executor = services[name]
        assert executor["network_mode"] == "none" and "networks" not in executor
        assert executor["image"] == suite[name]["image"]
        assert executor["command"] == suite[name]["command"]
        assert executor["volumes"] == [f"./data/compute-jobs/{app}:/jobs"]
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "WORKER_APPS=(" + " ".join(EXECUTORS.values()) + ")" in install


def test_histcraft_collects_simcraft_and_keeps_its_own_database() -> None:
    """Historian reads its own sources (the Simulator over the demo network in a trial); its
    PostgreSQL database stays on the apps network, unpublished."""

    services = _services()
    histcraft = services["histcraft"]["environment"]
    # The collector runs on its own: an update or restart of the server never stops recording.
    assert histcraft["HISTCRAFT_COLLECTOR"] == "off"
    collector = services["histcraft-collector"]
    assert collector["image"] == services["histcraft"]["image"]
    assert collector["command"] == ["histcraft", "collect"]
    assert collector["user"] == "10008:10008" and "ports" not in collector
    assert collector["volumes"] == services["histcraft"]["volumes"]
    assert collector["healthcheck"]["test"] == ["CMD", "histcraft", "healthcheck"]
    assert collector["depends_on"] == {HISTCRAFT_DB: {"condition": "service_healthy"}}
    for name in (
        "HISTCRAFT_DATABASE_URL",
        "HISTCRAFT_DATABASE_PASSWORD_FILE",
        "HISTCRAFT_DATA_DIR",
    ):
        assert collector["environment"][name] == histcraft[name], name
    assert services["histcraft"]["volumes"] == [
        "./data/histcraft:/data",
        "./data/histcraft-csv:/csv:ro",
    ]
    assert (
        histcraft["HISTCRAFT_DATABASE_URL"] == "postgresql://histcraft@histcraft-db:5432/histcraft"
    )
    assert histcraft["HISTCRAFT_DATABASE_PASSWORD_FILE"] == "/run/secrets/histcraft_db_password"
    assert services["histcraft"]["depends_on"][HISTCRAFT_DB]["condition"] == "service_healthy"
    database = services[HISTCRAFT_DB]
    # The default is the multi-platform index; a bundle sets the one-platform digest it saved.
    assert re.fullmatch(
        r"\$\{HISTCRAFT_DB_IMAGE:-postgres:17[\w.-]*@sha256:[0-9a-f]{64}\}", database["image"]
    )
    assert database["user"] == "10008:10008"
    assert _networks_of(database) == {"histdb"} and "ports" not in database
    # The gateway (Telegraf, pinned): the configuration the collector writes, read-only, and
    # its disk buffer (store and forward), the only folder it writes.
    gateway = services[HISTCRAFT_GATEWAY]
    assert gateway["profiles"] == ["histcraft"]
    assert re.fullmatch(
        r"\$\{HISTCRAFT_GATEWAY_IMAGE:-telegraf:[\w.-]+@sha256:[0-9a-f]{64}\}", gateway["image"]
    )
    assert gateway["user"] == "10008:10008" and "secrets" not in gateway
    assert gateway["volumes"] == [
        "./data/histcraft/gateway:/etc/telegraf:ro",
        "./data/histcraft/gateway-buffer:/var/lib/telegraf-buffer",
    ]
    assert gateway["command"][:3] == ["telegraf", "--config", "/etc/telegraf/telegraf.conf"]
    assert collector["environment"]["HISTCRAFT_INGEST_PORT"] == "8186"
    assert database["volumes"] == ["./data/histcraft-db:/var/lib/postgresql/data"]
    assert database["environment"]["POSTGRES_PASSWORD_FILE"] == "/run/secrets/histcraft_db_password"
    assert "scram-sha-256" in database["environment"]["POSTGRES_INITDB_ARGS"]
    assert _compose()["secrets"]["histcraft_db_password"]["file"] == "./data/histcraft-db-password"
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "pg_dump -U histcraft" in install and "histcraft-db-password" in install


def test_processcraft_starts_with_secure_defaults() -> None:
    environment = _services()["processcraft"]["environment"]
    assert environment["PLANTCRAFT_BASIC_AUTH_ENABLED"] == "true"
    assert environment["PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE"].startswith("/run/secrets/")
    assert environment["PLANTCRAFT_SESSION_HTTPS_ONLY"] == "true"
    assert environment["PLANTCRAFT_DEMO_USERS"] == "false"
    # No provider or key belongs here, and nothing here turns a language model on: only the way
    # out through llm-egress and the installation's switch, passed through from .env (empty: on
    # only once an administrator adds a provider in Setup; off forbids).
    llm = {name: value for name, value in environment.items() if "LLM" in name}
    assert llm == {
        "PLANTCRAFT_LLM_PROXY": "http://llm-egress:3128",
        "PLANTCRAFT_LLM_NO_PROXY": "${PLANTCRAFT_LLM_NO_PROXY:-}",
        "PLANTCRAFT_LLM": "${PLANTCRAFT_LLM:-}",
        # A public demo's visitors ask the model only when its .env turns it on, under limits.
        "PLANTCRAFT_PUBLIC_DEMO_LLM": "${PLANTCRAFT_PUBLIC_DEMO_LLM:-off}",
        "PLANTCRAFT_PUBLIC_DEMO_LLM_QUESTIONS": "${PLANTCRAFT_PUBLIC_DEMO_LLM_QUESTIONS:-10}",
        "PLANTCRAFT_PUBLIC_DEMO_LLM_PER_ADDRESS": "${PLANTCRAFT_PUBLIC_DEMO_LLM_PER_ADDRESS:-30}",
        "PLANTCRAFT_PUBLIC_DEMO_LLM_DAILY": "${PLANTCRAFT_PUBLIC_DEMO_LLM_DAILY:-600}",
    }
    assert not any("API_KEY" in name or "TOKEN" in name for name in environment)
    assert "PASSWORD=" not in json.dumps(environment)


def test_proxy_routes_and_stays_offline() -> None:
    caddyfile = (DEPLOY / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] for line in caddyfile.splitlines())
    retry = r"\{\s*import upstream (\d+)s\s*\}"
    assert re.search(rf"handle /link/\* \{{\s*reverse_proxy linkcraft:8140 {retry}\s*\}}", code)
    edge = r"\{\s*import upstream (\d+)s\s*import edge\s*\}"
    assert re.search(rf"handle \{{\s*reverse_proxy processcraft:8060 {edge}\s*\}}", code)
    # PlantCraft learns which requests came from outside (people's reads count against their
    # limits, plantcraft/api/usage.py): the proxy sets the mark, whatever the client sent.
    assert re.search(r"\(edge\) \{\s*header_up X-PlantCraft-Edge 1\s", code)
    assert code.count("import edge") == code.count("reverse_proxy processcraft:8060")
    # Only refused connections are retried, for a bounded time.
    assert re.search(
        r"\(upstream\) \{\s*lb_try_duration \{args\[0\]\}\s*lb_try_interval 500ms\s*\}", code
    )
    # Hashed built files are kept by the browser, never a 404 met during an update.
    assert re.search(
        r'header @built \{\s*Cache-Control "public, max-age=31536000, immutable"'
        r"\s*match \{\s*status 200\s*\}\s*\}",
        code,
    )
    # Installed apps' routes are imported before the suite's own, from the installer's folder.
    assert code.index("import /etc/caddy/apps/*.caddy") < code.index("handle /link/*")
    # PlantCraft Twin's addresses open Analytics' algorithms.
    assert "redir /twin/* /link/algorithms 308" in code
    for directive in ("admin off", "skip_install_trust", "ocsp_stapling off"):
        assert directive in code
    assert "tls {$PLANTCRAFT_TLS}" in code
    assert "acme" not in code.lower()
    entrypoint = (DEPLOY / "proxy" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "/certs/cert.pem" in entrypoint and 'PLANTCRAFT_TLS="internal"' in entrypoint


@pytest.mark.parametrize(
    ("hostnames", "default_sni"),
    [("vm 192.0.2.2", "192.0.2.2"), ("processcraft.plant.example", "processcraft.plant.example"),
     ("a.example,10.0.0.5,10.0.0.6", "10.0.0.5")],
)  # fmt: skip
def test_proxy_serves_the_ip_certificate_to_clients_without_sni(
    tmp_path: Path, hostnames: str, default_sni: str
) -> None:
    """Browsers send no SNI for an IP address: the default SNI must name that IP's certificate."""

    if shutil.which("sh") is None:
        pytest.skip("no POSIX shell")
    caddy = tmp_path / "caddy"
    caddy.write_text('#!/bin/sh\necho "$PLANTCRAFT_DEFAULT_SNI|$PLANTCRAFT_SITES"\n')
    caddy.chmod(0o755)
    result = subprocess.run(
        ["sh", str(DEPLOY / "proxy" / "entrypoint.sh")],
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
            "PLANTCRAFT_HOSTNAME": hostnames,
        },
    )
    sni, sites = result.stdout.strip().splitlines()[-1].split("|")
    assert sni == default_sni
    assert f"https://{default_sni}:8443" in sites


def _proxy_entrypoint(tmp_path: Path, trusted: str | None) -> subprocess.CompletedProcess[str]:
    caddy = tmp_path / "caddy"
    caddy.write_text(
        '#!/bin/sh\necho "$PLANTCRAFT_TRUSTED_PROXIES_LINE|$PLANTCRAFT_CLIENT_IP_HEADERS_LINE"\n'
    )
    caddy.chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ.get('PATH', '')}"}
    if trusted is not None:
        env["PLANTCRAFT_TRUSTED_PROXIES"] = trusted
    return subprocess.run(
        ["sh", str(DEPLOY / "proxy" / "entrypoint.sh")],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize("trusted", [None, "", " , "])
def test_proxy_trusts_no_forwarded_address_by_default(tmp_path: Path, trusted: str | None) -> None:
    """On a plant's network the client's address is the connection's own, as always."""

    if shutil.which("sh") is None:
        pytest.skip("no POSIX shell")
    result = _proxy_entrypoint(tmp_path, trusted)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "|"
    code = (DEPLOY / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    edge = code.split("(edge) {", 1)[1].split("\n}", 1)[0]
    # PlantCraft (FORWARDED_ALLOW_IPS = the proxy) reads one address, never one a client wrote.
    assert "header_up X-Forwarded-For {client_ip}" in edge
    assert (
        "{$PLANTCRAFT_TRUSTED_PROXIES_LINE}" in code.split("servers {", 1)[1].split("\n\t}", 1)[0]
    )


def test_proxy_reads_the_visitors_address_from_a_trusted_tunnel(tmp_path: Path) -> None:
    """Behind a tunnel every visitor would share one address: one demo place, one rate limit."""

    if shutil.which("sh") is None:
        pytest.skip("no POSIX shell")
    result = _proxy_entrypoint(tmp_path, "172.30.12.1/32, 10.0.0.0/8")
    assert result.returncode == 0, result.stderr
    trusted, headers = result.stdout.strip().splitlines()[-1].split("|")
    assert trusted == "trusted_proxies static 172.30.12.1/32  10.0.0.0/8"
    assert headers == "client_ip_headers CF-Connecting-IP X-Forwarded-For"
    environment = _services()["proxy"]["environment"]
    assert environment["PLANTCRAFT_TRUSTED_PROXIES"] == "${PLANTCRAFT_TRUSTED_PROXIES:-}"


@pytest.mark.parametrize("trusted", ["private_ranges", "10.0.0.0/8\n}\nimport x", "1.2.3.4;rm"])
def test_proxy_refuses_anything_but_addresses_to_trust(tmp_path: Path, trusted: str) -> None:
    if shutil.which("sh") is None:
        pytest.skip("no POSIX shell")
    result = _proxy_entrypoint(tmp_path, trusted)
    assert result.returncode != 0
    assert "addresses or CIDR ranges only" in result.stderr


def test_processcraft_lists_the_apps_this_file_runs() -> None:
    environment = _services()["processcraft"]["environment"]
    assert environment["PLANTCRAFT_APPS"] == "${PLANTCRAFT_APPS:-}"
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    table = re.search(r"^SUITE_APPS=\((.*?)^\)", install, re.MULTILINE | re.DOTALL).group(1)
    entries = {
        app_id: (prefix, uid, key)
        for app_id, _name, prefix, uid, key in (
            entry.split(":") for entry in re.findall(r'"(.+?)"', table)
        )
    }
    assert entries == {
        app: (prefix, uid, "" if app in KEYLESS_APPS else "key")
        for app, (prefix, _port, uid, _var) in APPS.items()
    }
    assert "provision_app_keys" in install.split("do_install() {", 1)[1]
    for app in APPS:
        assert f"--with-{app}" in install
    assert "--all-apps" in install


@pytest.mark.parametrize(
    ("profiles", "current", "expected"),
    [("linkcraft,demo", "", "linkcraft=/link/@0.1.0"),
     ("demo,histcraft,linkcraft,dashcraft", "linkcraft=/old/,other=/x/",
      "linkcraft=/link/@0.1.0,dashcraft=/dash/@0.2.0,histcraft=/hist/@0.1.0,other=/x/"),
     ("", "linkcraft=/link/@0.1.0", "")],
)  # fmt: skip
def test_install_lists_every_app_whose_profile_is_on(
    tmp_path: Path, profiles: str, current: str, expected: str
) -> None:
    if shutil.which("bash") is None:
        pytest.skip("no bash")
    env = tmp_path / ".env"
    env.write_text("LINKCRAFT_VERSION=0.1.0\nDASHCRAFT_VERSION=0.2.0\nHISTCRAFT_VERSION=0.1.0\n")
    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    table = re.search(r"^SUITE_APPS=\(.*?^\)$", install, re.MULTILINE | re.DOTALL).group(0)
    names = ("env_get", "app_field", "app_ids", "version_key", "suite_apps_setting")
    functions = [
        re.search(
            rf"^{name}\(\) {{[^\n]*}}$|^{name}\(\) {{.*?^}}$", install, re.MULTILINE | re.DOTALL
        ).group(0)
        for name in names
    ]
    script = "\n".join([table, *functions, 'suite_apps_setting "$1" "$2" "$3"'])
    result = subprocess.run(
        ["bash", "-c", script, "install.sh", profiles, current, str(env)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert result.stdout == expected


def test_install_accepts_the_app_keys_processcraft_issues(tmp_path: Path) -> None:
    # The isolation job runs without PlantCraft installed; the backend job runs this test.
    pytest.importorskip("plantcraft_sdk")
    from plantcraft.auth.app_keys import AppKeyStore
    from plantcraft.db import Database

    install = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    pattern = re.search(r'\[\[ ! "\$key" =~ (\S+) \]\]', install).group(1)
    _, key = AppKeyStore(Database(tmp_path / "keys.sqlite3")).create("linkcraft")
    result = subprocess.run(["bash", "-c", f'[[ "$1" =~ {pattern} ]]', "check", key], check=False)
    assert result.returncode == 0, key


@pytest.mark.parametrize(
    "dockerfile", ["Dockerfile", "deploy/proxy/Dockerfile", "deploy/installer/Dockerfile"]
)
def test_images_are_pinned_and_unprivileged(dockerfile: str) -> None:
    text = (ROOT / dockerfile).read_text(encoding="utf-8")
    base_images = re.findall(r"^ARG \w+_IMAGE=(\S+)$", text, re.MULTILINE)
    assert base_images, "base images are build arguments with pinned defaults"
    for image in base_images:
        assert re.search(r":[\w.-]+@sha256:[0-9a-f]{64}$", image), f"{image} not pinned"
    # A stage may run on the build machine's processor (--platform=$BUILDPLATFORM).
    for line in re.findall(r"^FROM (?:--platform=\$BUILDPLATFORM )?(\S+)", text, re.MULTILINE):
        assert line.startswith("${"), f"FROM {line} bypasses the pinned build arguments"
    users = re.findall(r"^USER (\S+)$", text, re.MULTILINE)
    assert users and _uid(users[-1]) not in {"0", "root"}
    assert "HEALTHCHECK" in text
    assert "org.opencontainers.image.version" in text
    assert not re.search(r"\b(apt-get|apk add)\b.*\b(gcc|build-essential|make)\b", text)


def test_python_dependencies_install_offline_from_hashed_wheels() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "--no-index" in dockerfile and "--require-hashes" in dockerfile
    assert "--only-binary=:all:" in dockerfile, "no source builds, so no compiler"
    assert "pip uninstall" in dockerfile
    lock = (DEPLOY / "requirements.lock").read_text(encoding="utf-8")
    requirements = re.findall(r"^([A-Za-z0-9_.-]+)==\S+ \\$", lock, re.MULTILINE)
    assert len(requirements) > 10
    blocks = re.split(r"^(?=[A-Za-z0-9_.-]+==)", lock, flags=re.MULTILINE)[1:]
    assert all("--hash=sha256:" in block for block in blocks)


def test_root_compose_runs_the_deploy_file() -> None:
    root = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert root == {"include": [{"path": "deploy/compose.yaml", "project_directory": "deploy"}]}


@pytest.mark.slow  # runs docker compose config: near ten seconds on a busy CI runner
def test_docker_compose_accepts_the_file() -> None:
    """The same rules on the configuration as Docker Compose resolves it (no daemon needed)."""

    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is not installed; the YAML checks above still ran.")
    profiles = [part for app in [*APPS, "demo"] for part in ("--profile", app)]
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *profiles, "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "COMPOSE_PROJECT_NAME": "pc-config-check"},
    )
    if result.returncode != 0 and "unknown" in result.stderr and "compose" in result.stderr:
        pytest.skip("Docker Compose plugin is not installed.")
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert {"proxy", "processcraft", "simcraft", HISTCRAFT_DB, *APPS} <= set(config["services"])
    for name, service in config["services"].items():
        assert bool(service.get("ports")) == (name == PROXY), name
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
    assert config["networks"]["apps"]["internal"] is True
    assert config["networks"]["histdb"]["internal"] is True
    for name, service in config["services"].items():
        assert ("histdb" in (service.get("networks") or {})) == (name in HISTDB_SERVICES), name


# Live checks: PLANTCRAFT_ISOLATION=live -------------------------------------------------

LIVE = os.environ.get("PLANTCRAFT_ISOLATION") == "live"
live = pytest.mark.skipif(
    not LIVE, reason="set PLANTCRAFT_ISOLATION=live (make isolation) to bring the stack up"
)


def _docker(*args: str, check: bool = True, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )


def _version() -> str:
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return os.environ.get("PLANTCRAFT_VERSION") or pyproject["project"]["version"]


def _simcraft_version() -> str:
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    default = re.search(r"^SIMCRAFT_VERSION=(\S+)$", example, re.MULTILINE).group(1)
    return os.environ.get("SIMCRAFT_VERSION") or default


# An app whose image is not built (CI cannot build the apps: separate repositories): PlantCraft's
# image serves <prefix>healthz on the app's port, under the app's name, user and networks.
STAND_IN_APP = """
  {name}:
    image: processcraft:{version}
    command:
      - sh
      - -c
      - mkdir -p /tmp/www{prefix} && echo ok > /tmp/www{prefix}index.html
        && echo '{{{{"status":"ok"}}}}' > /tmp/www{prefix}healthz
        && exec python -m http.server {port} --bind 0.0.0.0 --directory /tmp/www
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/', timeout=4)"]
"""

# Historian's database without its PostgreSQL image: a TCP listener at histcraft-db:5432.
STAND_IN_HISTCRAFT_DB = """
  histcraft-db:
    image: processcraft:{version}
    command:
      - python
      - -c
      - import socketserver; socketserver.TCPServer(("0.0.0.0", 5432),
        socketserver.BaseRequestHandler).serve_forever()
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 5432), timeout=4)"]
      start_period: 10s
"""

# The gateway without Telegraf's image: an idle container under its name, user and networks.
STAND_IN_HISTCRAFT_GATEWAY = """
  histcraft-gateway:
    image: processcraft:{version}
    command: ["python", "-c", "import time; time.sleep(10**9)"]
    healthcheck:
      test: ["CMD", "python", "-c", "print('ok')"]
"""

# Without the Simulator's image: a TCP listener at simcraft:4840 on the demo network, so the
# plant checks below still prove who can reach it.
STAND_IN_PLANTCRAFT = """
  simcraft:
    image: processcraft:{version}
    command:
      - python
      - -c
      - import socketserver; socketserver.TCPServer(("0.0.0.0", 4840),
        socketserver.BaseRequestHandler).serve_forever()
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 4840), timeout=4)"]
      start_period: 10s
"""


# An executor (or Historian's collector) without its image: a process that sleeps, on the
# service's own networks.
STAND_IN_EXECUTOR = """
  {name}:
    image: processcraft:{{version}}
    entrypoint: ["python", "-c", "import time; time.sleep(10 ** 9)"]
    command: []
    healthcheck:
      test: ["CMD", "python", "-c", "pass"]
"""


def _app_version(app: str) -> str:
    return os.environ.get(f"{app.upper()}_VERSION") or _version()


PROBE = """
import json, socket, sys
host, port = sys.argv[1], int(sys.argv[2])
routes = open("/proc/net/route").read().splitlines()[1:]
default = any(line.split()[1] == "00000000" for line in routes if line.split())
try:
    socket.create_connection((host, port), timeout=4).close()
    reached = True
except OSError:
    reached = False
print(json.dumps({"default_route": default, "reached": reached}))
"""


class Stack:
    def __init__(self, prefix: Path, version: str, port: int) -> None:
        self.prefix = prefix
        self.version = version
        self.port = port
        self.override = prefix / "stand-in.yaml"

    def compose(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        files = ["-f", str(self.prefix / "compose.yaml")]
        if self.override.exists():
            files += ["-f", str(self.override)]
        return _docker(
            "compose",
            "--project-directory",
            str(self.prefix),
            *files,
            "--env-file",
            str(self.prefix / ".env"),
            *args,
            check=check,
        )

    def diagnostics(self, failed: subprocess.CompletedProcess) -> str:
        """What a CI log needs to explain a failed start: the error, states and last logs."""

        ps = self.compose("ps", "-a", check=False)
        logs = self.compose("logs", "--no-color", "--tail", "60", check=False)
        return "\n".join(
            [
                f"$ {' '.join(map(str, failed.args))}",
                failed.stdout[-3000:],
                failed.stderr[-3000:],
                "$ docker compose ps -a",
                ps.stdout + ps.stderr,
                "$ docker compose logs --tail 60",
                logs.stdout[-12000:] + logs.stderr[-2000:],
            ]
        )

    def container(self, service: str) -> str:
        return self.compose("ps", "-q", service).stdout.strip()

    def containers(self) -> dict[str, dict[str, Any]]:
        ids = self.compose("ps", "-q").stdout.split()
        inspected = json.loads(_docker("inspect", *ids).stdout)
        return {item["Config"]["Labels"]["com.docker.compose.service"]: item for item in inspected}

    def probe(self, service: str, host: str, port: int) -> dict[str, bool]:
        result = _docker("exec", self.container(service), "python", "-c", PROBE, host, str(port))
        return json.loads(result.stdout)

    def default_route(self, service: str) -> bool:
        """Whether a container has a default route (for images without Python: PostgreSQL)."""

        routes = _docker("exec", self.container(service), "cat", "/proc/net/route").stdout
        return any(
            line.split()[1] == "00000000" for line in routes.splitlines()[1:] if line.split()
        )


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory):
    if shutil.which("docker") is None or _docker("info", check=False).returncode != 0:
        pytest.fail("PLANTCRAFT_ISOLATION=live needs a running Docker daemon")
    version = _version()
    for image in (f"processcraft:{version}", f"processcraft-proxy:{version}"):
        if _docker("image", "inspect", image, check=False).returncode != 0:
            pytest.fail(f"image {image} is missing: run `make image`")
    prefix = tmp_path_factory.mktemp("isolation")
    port = int(os.environ.get("PLANTCRAFT_ISOLATION_PORT", "18443"))
    example = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    settings = {
        "COMPOSE_PROJECT_NAME": "pc-isolation",
        "COMPOSE_PROFILES": "demo",
        # The Analytics image checked below, not the version .env.example names.
        "LINKCRAFT_VERSION": os.environ.get("LINKCRAFT_VERSION") or version,
        "SIMCRAFT_VERSION": _simcraft_version(),
        "PLANTCRAFT_HOSTNAME": "localhost",
        "PLANTCRAFT_BIND_ADDRESS": "127.0.0.1",
        "PLANTCRAFT_HTTPS_PORT": str(port),
        "PLANTCRAFT_CPUS": "2",
        "PLANTCRAFT_MEMORY": "2g",
        # More than the host has makes Docker refuse the container; install.sh lowers it.
        "LINKCRAFT_CPUS": "64",
        "LINKCRAFT_MEMORY": "1g",
        "DASHCRAFT_MEMORY": "1g",
        "HISTCRAFT_MEMORY": "1g",
        "HISTCRAFT_DB_MEMORY": "512m",
        "TWINCRAFT_MEMORY": "1g",
        "ALARMCRAFT_MEMORY": "1g",
        "MODELCRAFT_MEMORY": "1g",
        "MODELCRAFT_EXECUTOR_MEMORY": "1g",
        "PLANTCRAFT_PLANT_SUBNET": "172.31.240.0/24",
        "PLANTCRAFT_APPS_SUBNET": "172.31.241.0/24",
        "PLANTCRAFT_PROXY_ADDRESS": "172.31.241.250",
        "PLANTCRAFT_EDGE_SUBNET": "172.31.242.0/24",
        "PLANTCRAFT_DEMO_SUBNET": "172.31.243.0/24",
        "PLANTCRAFT_HISTDB_SUBNET": "172.31.244.0/24",
    }
    for app in APPS:
        settings[f"{app.upper()}_VERSION"] = _app_version(app)
    for key, value in settings.items():
        example = re.sub(rf"^{key}=.*$", f"{key}={value}", example, flags=re.MULTILINE)
    (prefix / ".env").write_text(example, encoding="utf-8")
    running = Stack(prefix, version, port)
    environment = {**os.environ, "PLANTCRAFT_HOME": str(prefix), "PLANTCRAFT_VERSION": version}
    try:
        install = subprocess.run(
            [str(DEPLOY / "install.sh"), "--dev", "--yes"],
            capture_output=True,
            text=True,
            env=environment,
            timeout=900,
        )
        assert install.returncode == 0, install.stdout[-4000:] + install.stderr[-4000:]
        stand_ins = []
        for app, (app_prefix, port, _uid, _variable) in APPS.items():
            if _docker("image", "inspect", f"{app}:{_app_version(app)}", check=False).returncode:
                stand_ins.append(
                    STAND_IN_APP.format(name=app, version="{version}", prefix=app_prefix, port=port)
                )
                if app == "histcraft":  # its collector runs the same image
                    stand_ins.append(STAND_IN_EXECUTOR.format(name="histcraft-collector"))
        for name, app in EXECUTORS.items():
            image = MODELCRAFT_RUNNER_IMAGE if name == MODELCRAFT_RUNNER else app
            if _docker("image", "inspect", f"{image}:{_app_version(app)}", check=False).returncode:
                stand_ins.append(STAND_IN_EXECUTOR.format(name=name))
        database = _services()[HISTCRAFT_DB]["image"].removeprefix("${HISTCRAFT_DB_IMAGE:-")
        database = os.environ.get("HISTCRAFT_DB_IMAGE") or database.removesuffix("}")
        if _docker("image", "inspect", database, check=False).returncode != 0:
            warnings.warn(f"{database} is not loaded: a stand-in serves histcraft-db", stacklevel=1)
            stand_ins.append(STAND_IN_HISTCRAFT_DB)
        gateway = _services()[HISTCRAFT_GATEWAY]["image"].removeprefix(
            "${HISTCRAFT_GATEWAY_IMAGE:-"
        )
        gateway = os.environ.get("HISTCRAFT_GATEWAY_IMAGE") or gateway.removesuffix("}")
        if _docker("image", "inspect", gateway, check=False).returncode != 0:
            warnings.warn(
                f"{gateway} is not loaded: a stand-in runs histcraft-gateway", stacklevel=1
            )
            stand_ins.append(STAND_IN_HISTCRAFT_GATEWAY)
        plant = f"simcraft:{_simcraft_version()}"
        if _docker("image", "inspect", plant, check=False).returncode != 0:
            warnings.warn(f"{plant} is not built: a stand-in serves the demo network", stacklevel=1)
            stand_ins.append(STAND_IN_PLANTCRAFT)
        if stand_ins:
            text = "services:" + "".join(stand_ins).format(version=version)
            running.override.write_text(text, encoding="utf-8")
        env_file = prefix / ".env"
        env_file.write_text(
            re.sub(
                r"^COMPOSE_PROFILES=.*$",
                "COMPOSE_PROFILES=" + ",".join(["demo", *APPS]),
                env_file.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            ),
            encoding="utf-8",
        )
        up = running.compose("up", "-d", "--wait", "--wait-timeout", "300", check=False)
        if up.returncode != 0:
            pytest.fail("the stack did not come up:\n" + running.diagnostics(up))
        yield running
    finally:
        running.compose("down", "-v", "--remove-orphans", check=False)
        _docker(
            "run", "--rm", "--network", "none", "--user", "0:0", "--entrypoint", "/bin/sh",
            "-v", f"{prefix}:/install", f"processcraft:{version}", "-c",
            "rm -rf /install/data /install/backups", check=False,
        )  # fmt: skip
        shutil.rmtree(prefix, ignore_errors=True)


@live
def test_live_only_the_proxy_publishes_ports(stack: Stack) -> None:
    containers = stack.containers()
    assert {"proxy", "processcraft", "simcraft", HISTCRAFT_DB, *APPS} <= set(containers)
    for service, item in containers.items():
        published = [
            binding
            for bindings in (item["NetworkSettings"]["Ports"] or {}).values()
            for binding in (bindings or [])
        ]
        if service == PROXY:
            assert [binding["HostPort"] for binding in published] == [str(stack.port)]
        else:
            assert not published, f"{service} publishes {published}"


@live
def test_live_containers_are_non_root_read_only_without_capabilities(stack: Stack) -> None:
    for service, item in stack.containers().items():
        host = item["HostConfig"]
        assert _uid(item["Config"]["User"]) not in {"", "0", "root"}, service
        assert host["ReadonlyRootfs"] is True, service
        assert "ALL" in (host["CapDrop"] or []), service
        assert not host["CapAdd"], service
        assert not host["Privileged"], service
        assert any(option.startswith("no-new-privileges") for option in host["SecurityOpt"])
        uid = _docker("exec", item["Id"], "id", "-u").stdout.strip()
        assert uid != "0", f"{service} runs as root"


@live
def test_live_app_containers_have_no_route_out(stack: Stack) -> None:
    control = stack.probe("processcraft", *OUTSIDE)
    if not control["reached"]:
        warnings.warn(
            "processcraft (plant network) cannot reach 1.1.1.1:443 either: this host has no "
            "internet, so the outbound checks rest on the route tables",
            stacklevel=1,
        )
    for app in sorted(set(APPS) - PLANT_SERVICES):
        probe = stack.probe(app, *OUTSIDE)
        assert probe == {"default_route": False, "reached": False}, (app, probe)
    assert stack.default_route(HISTCRAFT_DB) is False, "histcraft-db has a route out"
    proxy = _docker(
        "exec", stack.container("proxy"), "wget", "-q", "-T", "4", "-O", "/dev/null",
        "https://1.1.1.1/", check=False,
    )  # fmt: skip
    assert proxy.returncode != 0, "the proxy reached the internet"


@live
def test_live_only_processcraft_and_histcraft_reach_the_plant(stack: Stack) -> None:
    assert stack.probe("processcraft", "simcraft", 4840)["reached"] is True
    # The simulator is on an internal network: no route out, even without firewall.sh.
    assert stack.probe("simcraft", *OUTSIDE) == {"default_route": False, "reached": False}
    # Historian collects the Simulator's values itself, over the demo network.
    assert stack.probe("histcraft", "simcraft", 4840)["reached"] is True
    for app in sorted(set(APPS) - PLANT_SERVICES):
        result = _docker(
            "exec", stack.container(app), "python", "-c",
            "import socket; socket.create_connection(('simcraft', 4840), timeout=4)", check=False,
        )  # fmt: skip
        assert result.returncode != 0, f"{app} reached the plant network"


@live
def test_live_the_modelica_runner_has_no_network(stack: Stack) -> None:
    runner = stack.container(MODELCRAFT_RUNNER)
    interfaces = _docker("exec", runner, "cat", "/proc/net/dev").stdout
    assert [line.split(":")[0].strip() for line in interfaces.splitlines()[2:]] == ["lo"]
    for host, port in (("processcraft", 8060), ("modelcraft", 8130), OUTSIDE):
        result = _docker(
            "exec", runner, "python3", "-c",
            f"import socket; socket.create_connection(('{host}', {port}), timeout=4)", check=False,
        )  # fmt: skip
        assert result.returncode != 0, f"the Modelica runner reached {host}:{port}"


@live
def test_live_only_histcraft_reaches_its_database(stack: Stack) -> None:
    assert stack.probe("histcraft", HISTCRAFT_DB, 5432)["reached"] is True
    for service in sorted({"processcraft", *APPS} - HISTDB_SERVICES):  # the proxy: no Python
        result = _docker(
            "exec", stack.container(service), "python", "-c",
            f"import socket; socket.create_connection(('{HISTCRAFT_DB}', 5432), timeout=4)",
            check=False,
        )  # fmt: skip
        assert result.returncode != 0, f"{service} reached {HISTCRAFT_DB}"


@live
def test_live_https_through_the_proxy(stack: Stack) -> None:
    context = ssl.create_default_context(cafile=str(stack.prefix / "local-ca-root.crt"))
    base = f"https://localhost:{stack.port}"
    with urllib.request.urlopen(f"{base}/healthz", context=context, timeout=10) as response:
        assert response.status == 200
        assert json.load(response)["status"] == "ok"
        assert response.headers["Strict-Transport-Security"]
        # Scripts from the suite's own files only: every app shares PlantCraft's origin.
        assert "script-src 'self';" in response.headers["Content-Security-Policy"]
        assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]
    # The apps' pages need a sign-in; each one's health check answers under its prefix.
    for app, (prefix, *_rest) in APPS.items():
        url = f"{base}{prefix}healthz"
        with urllib.request.urlopen(url, context=context, timeout=10) as response:
            assert response.status == 200, app
            assert json.load(response)["status"] == "ok", app


@live
def test_live_admin_password_is_private(stack: Stack) -> None:
    status = (stack.prefix / "data" / "initial-admin-password").stat()
    assert status.st_mode & 0o777 == 0o600
    assert status.st_uid == 10001


def _resolves(container: str, name: str) -> bool:
    return _docker("exec", container, "getent", "hosts", name, check=False).returncode == 0


@live
def test_live_no_container_resolves_an_external_name(stack: Stack) -> None:
    control = _docker(
        "run", "--rm", "--network", "bridge", "--entrypoint", "getent",
        f"processcraft:{stack.version}", "hosts", *EXTERNAL_NAMES[:1], check=False,
    )  # fmt: skip
    if control.returncode != 0:
        warnings.warn(
            "a container on Docker's default network resolves no external name either: this "
            "host has no DNS out, so the checks below rest on the compose settings",
            stacklevel=1,
        )
    containers = stack.containers()
    assert {"proxy", "processcraft", "simcraft", HISTCRAFT_DB, *APPS} <= set(containers)
    for service, item in containers.items():
        if service == LLM_EGRESS:
            continue  # resolves internet names for the providers' hosts only (next test)
        resolved = [name for name in EXTERNAL_NAMES if _resolves(item["Id"], name)]
        assert not resolved, f"{service} resolves {resolved}"
    # Service names still resolve where the conduits need them.
    pairs = [("processcraft", "simcraft"), ("histcraft", "simcraft"),
             ("histcraft", HISTCRAFT_DB)]  # fmt: skip
    pairs += [("proxy", app) for app in APPS] + [(app, "processcraft") for app in APPS]
    for service, peer in [("proxy", "processcraft"), *pairs]:
        assert _resolves(containers[service]["Id"], peer), f"{service} cannot resolve {peer}"


@live
def test_live_llm_egress_refuses_hosts_no_provider_names(stack: Stack) -> None:
    """With no provider in the cloud, llm-egress opens nothing, not even a famous name."""

    asked = _docker(
        "exec", stack.container("processcraft"), "python", "-c",
        "import socket; s = socket.create_connection(('llm-egress', 3128), timeout=4); "
        "s.sendall(b'CONNECT github.com:443 HTTP/1.1\\r\\n\\r\\n'); print(s.recv(64).decode())",
        check=False,
    )  # fmt: skip
    assert asked.returncode == 0 and " 403 " in asked.stdout, asked.stdout + asked.stderr


def test_the_code_sandboxes_have_no_network_no_secret_and_no_app_data() -> None:
    """Alarms' rules run their Python in alarmcraft-sandbox (security test 2026-10-31, D8): the
    app's image, no network, no secret, and only the socket folder shared with the app."""

    services = _compose()["services"]
    for name, app in CODE_SANDBOXES.items():
        sandbox, owner = services[name], services[app]
        assert sandbox["profiles"] == [app]
        assert sandbox["image"] == owner["image"]
        assert sandbox["network_mode"] == "none" and "networks" not in sandbox
        assert "secrets" not in sandbox
        assert sandbox["volumes"] == [f"./data/{app}-sandbox:/sandbox"]
        assert f"./data/{app}-sandbox:/sandbox" in owner["volumes"]
        assert owner["environment"]["ALARMCRAFT_CODE_SOCKET"] == "/sandbox/code.sock"


def test_the_installer_image_holds_every_module_its_code_imports() -> None:
    """The installer image copies single files, not the package: each first-party module those
    files import must be copied too, or the image build stops (plantcraft.files, 2026-10-31)."""

    text = (ROOT / "deploy" / "installer" / "Dockerfile").read_text(encoding="utf-8")
    copied: dict[str, Path] = {}
    for sources, target in re.findall(r"^COPY (?!--)(.+) (/app/\S+)$", text, re.MULTILINE):
        for source in sources.split():
            dest = target + Path(source).name if target.endswith("/") else target
            module = dest.removeprefix("/app/").removesuffix(".py").replace("/", ".")
            copied[module.removesuffix(".__init__")] = ROOT / source
    missing = []
    for module, path in copied.items():
        if path.suffix != ".py":
            continue
        for name in re.findall(
            r"^\s*(?:from|import) ((?:plantcraft|plantcraft_sdk|processcraft)(?:\.\w+)*)",
            path.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            parts = name.split(".")
            if not any(".".join(parts[:i]) in copied for i in range(len(parts), 1, -1)) and (
                name not in copied
            ):
                missing.append(f"{module} imports {name}")
    assert not missing, missing
