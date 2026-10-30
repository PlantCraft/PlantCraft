"""The installer service: the only part of the suite with access to Docker (docs/app-package.md).

It runs in its own container (``processcraft-installer``, compose service
``installer``) with no network at all. PlantCraft never talks to Docker: it
drops a request (``<id>.json``) and the package it verified (``<id>.pcapp``)
in a folder this service reads; this service checks the package again against
the trusted publisher keys, loads the image, writes the app's compose file and
proxy route, starts it and writes the outcome to a status folder PlantCraft
reads. ``install.sh --add`` and ``--remove`` run the same code once, from the
command line.

Imports only :mod:`plantcraft.apps.package` and the standard library.

Folders (``state`` is ``<install dir>/data/installer``)::

    state/status/heartbeat.json        written every loop (the container health check)
    state/status/metrics.json          Docker's view of every service and the free disk, every
                                       30 s (PlantCraft's monitor reads it; docs/operations.md)
    state/status/installed.json        the apps this installer runs
    state/status/diagnostics/<id>.zip  a diagnostic bundle an administrator asked for (24 h)
    state/status/requests/<id>.json    outcome of each request
    state/apps/<app>/compose.json      the app's compose service (JSON is YAML)
    state/apps/<app>/state.json        current and previous version
    state/apps/<app>/versions/<v>/     manifest.json, manifest.sig, sbom.spdx.json
    state/routes/<app>.caddy           the proxy route (mounted read-only in the proxy)
    state/secrets/<app>/app-key        the app's key, owned by the app's user
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plantcraft.apps import package as pkg

REQUEST_LIMIT = 64 * 1024
ACTIONS = {"install", "uninstall", "rollback", "set_key"}
# Operations of the whole installation, run by the driver (plantcraft.apps.operations).
OPS_ACTIONS = {"backup", "verify", "restore", "prune", "drill"}
OPS_SETTINGS = "ops-settings.json"
# The suite starts before the schedule runs its first backup or drill (run_schedule).
SCHEDULE_GRACE = timedelta(minutes=15)
# Done here, by the installer itself: a zip of what support needs to see (docs/operations.md).
DIAGNOSTICS = "diagnostics"
DIAGNOSTICS_HOURS = 24
LOG_BYTES = 20 * 2**20
LOG_LINES = 200_000
# Status files a diagnostic bundle carries (never databases, plant data, certificates or keys).
STATUS_FILES = (
    "metrics.json", "installed.json", "heartbeat.json", "release.json", "backups.json",
    "drill.json", "operation.json", "operations.json", "update.json", "schedule.json",
)  # fmt: skip
_SECRET_NAME = re.compile(r"PASS|SECRET|TOKEN|KEY|CREDENTIAL|COOKIE|PRIVATE|DSN|AUTH", re.I)
_SECRET_TEXT = re.compile(
    r"(?i)((?:authorization[\"':=\s]+)?(?:bearer|basic)\s+|authorization[\"':=\s]+|"
    r"(?:password|passwd|secret|token|api[_-]?key|app[_-]?key|cookie)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\s\"',;]+)"
)
_URL_PASSWORD = re.compile(r"(://[^/\s:@]+:)([^@\s/]+)(@)")
HEARTBEAT_SECONDS = 30
METRICS_SECONDS = 30
POLL_SECONDS = 2.0
WAIT_SECONDS = 300
CPUS, MEMORY, PIDS = 2.0, "2g", 512
PROXY = "proxy"
LOG_TAIL = 4000


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SIZE = re.compile(r"^\s*([0-9.]+)\s*([KMGTP]?i?B)\s*$", re.IGNORECASE)
_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12, "PB": 10**15,
          "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "TIB": 2**40, "PIB": 2**50}  # fmt: skip


def json_lines(text: str) -> list[dict[str, Any]]:
    """What ``docker ... --format json`` prints: one array (older Compose) or one object a line."""

    text = (text or "").strip()
    if text.startswith("["):
        found = json.loads(text)
        return [item for item in found if isinstance(item, dict)]
    return [json.loads(line) for line in text.splitlines() if line.strip().startswith("{")]


def size_bytes(text: str) -> int | None:
    """``"12.5MiB"`` (as ``docker stats`` writes sizes) in bytes; None when unreadable."""

    match = _SIZE.match(text or "")
    if not match:
        return None
    return int(float(match.group(1)) * _UNITS[match.group(2).upper()])


def percent(text: str) -> float | None:
    try:
        return round(float(str(text).strip().rstrip("%")), 2)
    except ValueError:
        return None


def redact(text: str) -> str:
    """``text`` with passwords, tokens, keys, cookies and URL passwords replaced by ``***``."""

    text = _SECRET_TEXT.sub(lambda m: f"{m.group(1)}***", text)
    return _URL_PASSWORD.sub(r"\1***\3", text)


def settings_text(environ: dict[str, str]) -> str:
    """The suite's settings as the installer sees them (its ``env_file`` is ``.env``), one
    ``NAME=value`` a line, every secret by its name or its look replaced."""

    lines = []
    for name in sorted(environ):
        if not re.match(r"^[A-Z][A-Z0-9_]*$", name) or name in {"PATH", "HOME", "HOSTNAME"}:
            continue
        value = environ[name]
        shown = "***" if _SECRET_NAME.search(name) and value else redact(value)
        lines.append(f"{name}={shown}")
    return "\n".join(lines) + "\n"


class InstallError(Exception):
    """A request that could not be carried out; the message goes to the administrator."""


class Docker:
    """The Docker CLI, run as a subprocess (``PLANTCRAFT_DOCKER`` names another binary)."""

    def __init__(self, binary: str | None = None):
        self.binary = binary or os.environ.get("PLANTCRAFT_DOCKER") or "docker"

    def run(
        self,
        *args: str,
        timeout: float = 900,
        check: bool = True,
        env: dict[str, str] | None = None,
        stdin: Path | None = None,
        stdout: Path | None = None,
    ) -> subprocess.CompletedProcess:
        """Run ``docker *args``; ``stdin`` and ``stdout`` stream a file in or out as bytes (a
        database dump), ``env`` replaces the environment (a Compose that reads ``.env`` only)."""

        try:
            if stdin is None and stdout is None:
                result = subprocess.run(
                    [self.binary, *args], capture_output=True, text=True, timeout=timeout, env=env
                )
            else:
                with (
                    stdin.open("rb") if stdin else open(os.devnull, "rb") as source,
                    stdout.open("wb") if stdout else open(os.devnull, "wb") as target,
                ):
                    done = subprocess.run(
                        [self.binary, *args], stdin=source, stdout=target,
                        stderr=subprocess.PIPE, timeout=timeout, env=env,
                    )  # fmt: skip
                result = subprocess.CompletedProcess(
                    done.args, done.returncode, "", done.stderr.decode("utf-8", "replace")
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallError(f"docker {args[0] if args else ''} failed: {exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-LOG_TAIL:]
            raise InstallError(f"docker {' '.join(args[:3])} failed: {detail}")
        return result

    def image_id(self, ref: str) -> str | None:
        result = self.run("image", "inspect", "--format", "{{.Id}}", ref, check=False)
        return result.stdout.strip() if result.returncode == 0 else None


class Installer:
    def __init__(
        self,
        install_dir: str | Path,
        *,
        requests_dir: str | Path,
        trusted_dir: str | Path,
        helper_image: str,
        docker: Docker | None = None,
        project: str | None = None,
        max_image_bytes: int = pkg.DEFAULT_MAX_IMAGE_BYTES,
        wait_seconds: int = WAIT_SECONDS,
    ):
        self.install_dir = Path(install_dir)
        self.state = self.install_dir / "data" / "installer"
        self.requests = Path(requests_dir)
        self.trusted_dir = Path(trusted_dir)
        self.helper_image = helper_image
        self.docker = docker or Docker()
        self.project = project or os.environ.get("COMPOSE_PROJECT_NAME") or "processcraft"
        self.max_image_bytes = max_image_bytes
        self.wait_seconds = wait_seconds
        for folder in ("status/requests", "apps", "routes", "secrets", "work"):
            (self.state / folder).mkdir(parents=True, exist_ok=True)
        for folder in ("secrets", "work"):
            (self.state / folder).chmod(0o700)

    @classmethod
    def from_environment(cls) -> Installer:
        install_dir = os.environ.get("PLANTCRAFT_INSTALL_DIR", "").strip()
        if not install_dir or not os.path.isabs(install_dir):
            raise SystemExit("PLANTCRAFT_INSTALL_DIR must be the absolute install folder")
        max_mb = os.environ.get("PLANTCRAFT_APP_MAX_MB", "").strip()
        return cls(
            install_dir,
            requests_dir=os.environ.get("PLANTCRAFT_APP_REQUESTS", "/requests"),
            trusted_dir=os.environ.get("PLANTCRAFT_TRUSTED_PUBLISHERS", "/trusted-publishers"),
            helper_image=os.environ.get("PLANTCRAFT_INSTALLER_IMAGE", "processcraft-installer"),
            max_image_bytes=int(max_mb) * pkg.MiB
            if max_mb.isdigit()
            else pkg.DEFAULT_MAX_IMAGE_BYTES,
        )

    # Files ---------------------------------------------------------------------------------

    @staticmethod
    def _write(path: Path, data: bytes | str, mode: int = 0o644) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}")
        partial.write_bytes(data.encode() if isinstance(data, str) else data)
        partial.chmod(mode)
        partial.replace(path)

    def _json(self, path: Path, value: Any, mode: int = 0o644) -> None:
        self._write(path, json.dumps(value, indent=2, sort_keys=True) + "\n", mode)

    @staticmethod
    def _read_json(path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    @contextmanager
    def locked(self) -> Iterator[None]:
        with (self.state / "lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def heartbeat(self) -> None:
        self._json(
            self.state / "status" / "heartbeat.json",
            {"at": now(), "trusted_publishers": sorted(pkg.load_trusted(self.trusted_dir))},
        )

    def metrics(self) -> dict[str, Any]:
        """Every container of the suite as Docker sees it (state, health, restarts, CPU,
        memory) and the free disk of the install folder. Docker runs each service's health
        check (``/healthz``), so ``health`` is the suite's own answer, seen from outside it."""

        value: dict[str, Any] = {"at": now(), "services": [], "error": None}
        try:
            disk = shutil.disk_usage(self.install_dir)
            value["disk"] = {
                "total_bytes": disk.total,
                "free_bytes": disk.free,
                "free_pct": round(100 * disk.free / disk.total, 2) if disk.total else None,
            }
        except OSError:
            value["disk"] = None
        try:
            containers = json_lines(self.compose("ps", "-a", "--format", "json", timeout=60).stdout)
        except (InstallError, ValueError) as exc:
            value["error"] = str(exc)[-LOG_TAIL:]
            return value
        ids = [str(c.get("ID")) for c in containers if c.get("ID")]
        details: dict[str, list[str]] = {}
        if ids:
            shown = self.docker.run(
                "inspect", "--format",
                "{{.Id}}|{{.RestartCount}}|{{.State.StartedAt}}|{{.State.OOMKilled}}",
                *ids, check=False, timeout=60,
            ).stdout  # fmt: skip
            for line in shown.splitlines():
                parts = line.strip().split("|")
                if len(parts) == 4:
                    details[parts[0]] = parts[1:]
        running = [
            str(c["Name"]) for c in containers if c.get("State") == "running" and c.get("Name")
        ]
        usage: dict[str, dict[str, Any]] = {}
        if running:
            stats = self.docker.run(
                "stats", "--no-stream", "--format", "{{json .}}", *running, check=False, timeout=60
            ).stdout  # fmt: skip
            try:
                usage = {str(item.get("Name")): item for item in json_lines(stats)}
            except ValueError:
                usage = {}
        for container in sorted(containers, key=lambda c: str(c.get("Service"))):
            container_id = str(container.get("ID") or "")
            extra = next(
                (v for k, v in details.items() if container_id and k.startswith(container_id)), None
            )
            used = usage.get(str(container.get("Name"))) or {}
            memory = str(used.get("MemUsage") or "").split("/")
            restarts = extra[0] if extra else ""
            value["services"].append(
                {
                    "service": container.get("Service"),
                    "name": container.get("Name"),
                    "state": container.get("State") or "",
                    "health": container.get("Health") or "",
                    "exit_code": container.get("ExitCode"),
                    "status": container.get("Status") or "",
                    "image": container.get("Image") or "",
                    "restarts": int(restarts) if restarts.isdigit() else None,
                    "started_at": extra[1] if extra else None,
                    "oom_killed": (extra[2] == "true") if extra else None,
                    "cpu_pct": percent(used["CPUPerc"]) if used.get("CPUPerc") else None,
                    "mem_bytes": size_bytes(memory[0]) if used else None,
                    "mem_limit_bytes": size_bytes(memory[1]) if len(memory) == 2 else None,
                    "mem_pct": percent(used["MemPerc"]) if used.get("MemPerc") else None,
                }
            )
        return value

    def publish_metrics(self) -> None:
        self._json(self.state / "status" / "metrics.json", self.metrics())

    def app_dir(self, app_id: str) -> Path:
        return self.state / "apps" / app_id

    def app_state(self, app_id: str) -> dict[str, Any]:
        return self._read_json(self.app_dir(app_id) / "state.json", {}) or {}

    def installed(self) -> list[dict[str, Any]]:
        apps = []
        for folder in sorted((self.state / "apps").iterdir()):
            state = self._read_json(folder / "state.json", {}) or {}
            current = state.get("current")
            if folder.is_dir() and current and pkg.APP_ID.match(folder.name):
                apps.append(
                    {
                        **current,
                        "app_id": folder.name,
                        "previous_version": (state.get("previous") or {}).get("version"),
                        "has_key": (self.state / "secrets" / folder.name / "app-key").exists()
                        or bool(state.get("has_key")),
                    }
                )
        return apps

    def publish_installed(self) -> None:
        self._json(
            self.state / "status" / "installed.json", {"at": now(), "apps": self.installed()}
        )

    def report(self, request_id: str, **fields: Any) -> None:
        path = self.state / "status" / "requests" / f"{request_id}.json"
        current = self._read_json(path, {}) or {}
        self._json(path, {**current, "request_id": request_id, **fields, "updated_at": now()})

    # Compose -------------------------------------------------------------------------------

    def compose_files(self) -> list[str]:
        files = ["-f", str(self.install_dir / "compose.yaml")]
        for path in sorted((self.state / "apps").glob("*/compose.json")):
            files += ["-f", str(path)]
        return files

    def compose(self, *args: str, timeout: float = 900) -> subprocess.CompletedProcess:
        return self.docker.run(
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(self.install_dir),
            *self.compose_files(),
            *args,
            timeout=timeout,
        )

    def service(self, manifest: dict[str, Any], *, has_key: bool) -> dict[str, Any]:
        """The app's compose service: the settings and container rules of docs/app-standard.md
        (section 7), the same hardening as the suite's own services."""

        view = pkg.flat(manifest)
        app_id, uid, upper = view["id"], view["uid"], view["id"].upper()
        cpus = min(CPUS, float(os.cpu_count() or 1))
        environment = {
            "PLANTCRAFT_URL": "http://processcraft:8060",
            f"{upper}_ROOT_PATH": view["prefix"].rstrip("/"),
            f"{upper}_DATA_DIR": "/data",
            f"{upper}_HOST": "0.0.0.0",
            f"{upper}_PORT": str(view["port"]),
        }
        historian = os.environ.get("HISTCRAFT_URL", "").strip()
        if historian:
            # Signal and series reads straight from the Historian, the data layer (the suite's
            # .env); without it they go through PlantCraft.
            environment["PLANTCRAFT_HISTORIAN_URL"] = historian
        volumes = [f"{self.install_dir}/data/apps/{app_id}:/data"]
        if has_key:
            secret = f"/run/secrets/{app_id}_app_key"
            environment["PLANTCRAFT_APP_KEY_FILE"] = secret
            volumes.append(f"{self.state}/secrets/{app_id}/app-key:{secret}:ro")
        service: dict[str, Any] = {
            "image": view["image"],
            "init": True,
            "restart": "unless-stopped",
            "read_only": True,
            "pull_policy": "never",
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "tmpfs": ["/tmp:size=64m,mode=1777,noexec,nosuid,nodev"],
            "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "5"}},
            "user": f"{uid}:{uid}",
            "environment": environment,
            "networks": ["apps"],
            "labels": {
                "org.processcraft.app": app_id,
                "org.processcraft.version": view["version"],
                "org.processcraft.origin": "package",
            },
            "depends_on": {"processcraft": {"condition": "service_healthy"}},
            "stop_grace_period": "30s",
            "deploy": {
                "resources": {
                    "limits": {
                        "cpus": f"{cpus:g}",
                        "memory": MEMORY,
                        "pids": PIDS,
                    }
                }
            },
        }
        service["volumes"] = volumes
        return {"services": {f"app-{app_id}": service}}

    @staticmethod
    def route(manifest: dict[str, Any]) -> str:
        view = pkg.flat(manifest)
        prefix = view["prefix"]
        if not pkg.PREFIX.match(prefix) or not pkg.APP_ID.match(view["id"]):
            raise InstallError("invalid prefix or id")  # validated already; never reach Caddy
        bare = prefix.rstrip("/")
        return (
            f"# Written by the PlantCraft installer for {view['id']} "
            f"{view['version']}; do not edit.\n"
            f"redir {bare} {prefix} 308\n"
            # The suite's frame (Caddyfile, "The suite's frame"): a signed-in person's page under
            # the prefix is PlantCraft's, which loads the app beside the sidebar.
            f"@frame_{view['id']} {{\n"
            f"\tpath {prefix}*\n"
            f"\tnot path {prefix}api/*\n"
            "\theader Sec-Fetch-Dest document\n"
            "\theader Cookie *processcraft_token=*\n"
            "\tnot query pc-frame=off\n"
            "}\n"
            f"handle @frame_{view['id']} {{\n"
            "\treverse_proxy processcraft:8060\n"
            "}\n"
            f"handle {prefix}* {{\n"
            f"\treverse_proxy app-{view['id']}:{int(view['port'])}\n"
            "}\n"
        )

    def restart_proxy(self) -> None:
        self.compose(
            "up", "-d", "--no-deps", "--force-recreate", "--wait",
            "--wait-timeout", str(self.wait_seconds), PROXY,
        )  # fmt: skip

    def start_app(self, app_id: str) -> None:
        self.compose(
            "up", "-d", "--no-deps", "--wait", "--wait-timeout", str(self.wait_seconds),
            f"app-{app_id}",
        )  # fmt: skip

    def stop_app(self, app_id: str) -> None:
        self.compose("rm", "--stop", "--force", f"app-{app_id}")

    def helper(self, script: str) -> None:
        """Runs ``script`` as root in a throwaway container with no network, the data folder at /d."""

        self.docker.run(
            "run", "--rm", "--network", "none", "--user", "0:0", "--pull", "never",
            "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE",
            "--cap-add", "FOWNER", "--security-opt", "no-new-privileges:true",
            "-v", f"{self.install_dir}/data:/d", "--entrypoint", "/bin/sh",
            self.helper_image, "-c", script,
        )  # fmt: skip

    # Requests ------------------------------------------------------------------------------

    def pending(self) -> list[Path]:
        if not self.requests.is_dir():
            return []
        found = []
        for path in self.requests.glob("*.json"):
            request_id = path.stem
            if not pkg.REQUEST_ID.match(request_id) or not path.is_file() or path.is_symlink():
                continue
            status = self._read_json(self.state / "status" / "requests" / f"{request_id}.json")
            if status and status.get("state") in {"done", "failed"}:
                continue
            # An operation, once started, is the driver's: it writes the outcome itself.
            if status and status.get("action") in OPS_ACTIONS:
                continue
            found.append(path)
        return sorted(found, key=lambda item: item.stat().st_mtime)

    def read_request(self, path: Path) -> dict[str, Any]:
        if path.stat().st_size > REQUEST_LIMIT:
            raise InstallError("the request is too large")
        try:
            request = pkg.strict_json(path.read_bytes(), "request")
        except pkg.PackageError as exc:
            raise InstallError(str(exc)) from exc
        known = ACTIONS | OPS_ACTIONS | {DIAGNOSTICS}
        if not isinstance(request, dict) or request.get("action") not in known:
            raise InstallError("unknown request")
        if request.get("request_id") != path.stem:
            raise InstallError("the request id does not match its file")
        if request["action"] in OPS_ACTIONS | {DIAGNOSTICS}:
            return self._ops_request(request)
        app_id = request.get("app_id")
        if not isinstance(app_id, str) or not pkg.APP_ID.match(app_id):
            raise InstallError("invalid app id")
        key = request.get("app_key")
        if key is not None and (not isinstance(key, str) or not pkg.APP_KEY.match(key)):
            raise InstallError("invalid app key")
        by = request.get("requested_by")
        request["requested_by"] = str(by)[:120] if isinstance(by, str) else "unknown"
        return request

    def _ops_request(self, request: dict[str, Any]) -> dict[str, Any]:
        from plantcraft.apps import operations

        name = request.get("name")
        if request["action"] in {"verify", "restore"} and (
            not isinstance(name, str) or not operations.NAME.match(name)
        ):
            raise InstallError("invalid backup name")
        by = request.get("requested_by")
        return {
            "request_id": request["request_id"],
            "action": request["action"],
            "app_id": None,
            "name": name if isinstance(name, str) else None,
            "requested_by": str(by)[:120] if isinstance(by, str) else "unknown",
        }

    def launch_operation(self, action: str, request_id: str | None = None, **params: str) -> None:
        """Start the operations driver (``plantcraft.apps.operations``) in the background."""

        from plantcraft.apps import operations

        operations.launch(
            self.docker, self.install_dir, self.helper_image, action, project=self.project,
            request_id=request_id, **params,
        )  # fmt: skip

    def run_schedule(self, moment: datetime | None = None) -> str | None:
        """Start the daily backup when it is due; an interrupted operation is resumed first."""

        from plantcraft.apps import operations

        if operations.driver_running(self.docker):
            return None
        if (self.state / "status" / "operation.json").exists():
            self.docker.run(
                *operations.driver_command(
                    self.install_dir, self.helper_image, ["resume"], detach=True,
                    project=self.project,
                ),
            )  # fmt: skip
            return "resume"
        settings = operations.schedule_settings(self.requests / OPS_SETTINGS)
        path = self.state / "status" / "schedule.json"
        schedule = self._read_json(path, {}) or {}
        moment = moment or datetime.now(timezone.utc)
        # A new installation (or one updated from before this) starts its suite first: no
        # backup or drill in its first minutes, when the databases may not answer yet.
        first = schedule.get("first_seen")
        if not first:
            schedule["first_seen"] = moment.isoformat()
            self._json(path, schedule)
            return None
        if moment < datetime.fromisoformat(first) + SCHEDULE_GRACE:
            return None
        if operations.due(settings, schedule.get("last_daily"), moment):
            schedule.update(last_daily=operations.local_day(settings, moment), at=now())
            self._json(path, schedule)
            self.launch_operation("backup", reason="daily")
            return "backup"
        if operations.drill_due(settings, schedule.get("last_drill"), moment):
            schedule.update(last_drill=operations.local_week(settings, moment), at=now())
            self._json(path, schedule)
            self.launch_operation("drill")
            return "drill"
        return None

    def process_pending(self) -> int:
        done = 0
        for path in self.pending():
            request_id = path.stem
            try:
                request = self.read_request(path)
            except (InstallError, OSError) as exc:
                self.report(request_id, state="failed", message=str(exc))
                continue
            self.handle(request, self.requests / f"{request_id}.pcapp")
            done += 1
        return done

    def handle(self, request: dict[str, Any], package_path: Path | None = None) -> dict[str, Any]:
        request_id = request["request_id"]
        action, app_id = request["action"], request["app_id"]
        if action == DIAGNOSTICS:
            self.report(request_id, state="running", action=action, step="collecting",
                        requested_by=request["requested_by"])  # fmt: skip
            try:
                path = self.diagnostics(request_id, request["requested_by"])
            except (InstallError, OSError) as exc:
                self.report(request_id, state="failed", message=str(exc)[-LOG_TAIL:])
                return {"state": "failed", "message": str(exc)}
            result = {"file": path.name, "size": path.stat().st_size}
            self.report(request_id, state="done", step="done", **result)
            return {"state": "done", **result}
        if action in OPS_ACTIONS:
            self.report(request_id, state="running", action=action, step="starting",
                        name=request.get("name"), requested_by=request["requested_by"])  # fmt: skip
            params = {"name": request["name"]} if request.get("name") else {}
            if action == "backup":
                params = {"reason": "manual"}
            try:
                self.launch_operation(action, request_id, **params)
            except InstallError as exc:
                self.report(request_id, state="failed", message=str(exc)[-LOG_TAIL:])
                return {"state": "failed", "message": str(exc)}
            return {"state": "running"}
        self.report(request_id, state="running", action=action, app_id=app_id, step="queued")
        try:
            with self.locked():
                if action == "install":
                    result = self.install(
                        package_path, request_id, request["requested_by"],
                        app_id=app_id, app_key=request.get("app_key"),
                    )  # fmt: skip
                elif action == "uninstall":
                    result = self.uninstall(app_id, request_id)
                elif action == "rollback":
                    result = self.rollback(app_id, request_id, request["requested_by"])
                else:
                    result = self.set_key(app_id, request.get("app_key"), request_id)
                self.publish_installed()
        except (InstallError, pkg.PackageError, OSError) as exc:
            self.publish_installed()
            self.report(request_id, state="failed", message=str(exc)[-LOG_TAIL:])
            return {"state": "failed", "message": str(exc)}
        self.report(request_id, state="done", step="done", **result)
        return {"state": "done", **result}

    # Actions -------------------------------------------------------------------------------

    def _check_conflicts(self, manifest: dict[str, Any]) -> None:
        """Prefix, port and uid are the app's own (suite table, then every other installed app)."""

        view = pkg.flat(manifest)
        others = [{**item, "id": item["app_id"]} for item in self.installed()]
        owner = pkg.prefix_owner(
            view["id"], view["prefix"], {item["prefix"]: item["id"] for item in others}
        )
        if owner:
            raise InstallError(f"{view['prefix']} is already served by {owner}")
        conflict = pkg.runtime_conflict(manifest, others)
        if conflict:
            raise InstallError(conflict)

    def install(
        self,
        package_path: Path | None,
        request_id: str,
        requested_by: str,
        *,
        app_id: str | None = None,
        app_key: str | None = None,
    ) -> dict[str, Any]:
        if package_path is None or not package_path.is_file() or package_path.is_symlink():
            raise InstallError("the package file is missing")
        work = self.state / "work" / request_id
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(mode=0o700, parents=True)
        try:
            self.report(request_id, step="verify")
            verified = pkg.verify_package(
                package_path,
                pkg.load_trusted(self.trusted_dir),
                extract_to=work,
                max_image_bytes=self.max_image_bytes,
            )
            manifest = verified.manifest
            view = pkg.flat(manifest)
            if app_id is not None and view["id"] != app_id:
                raise InstallError(f"the package is {view['id']}, not {app_id}")
            app_id = view["id"]
            self._check_conflicts(manifest)
            self.report(request_id, step="load", app_id=app_id, version=view["version"])
            self.docker.run("load", "-i", str(work / pkg.IMAGE), timeout=1800)
            image_id = self.docker.image_id(view["image"])
            if image_id not in verified.image_ids:
                raise InstallError(
                    f"after docker load, {view['image']} is {image_id}, not the verified image"
                )
            version_dir = self.app_dir(app_id) / "versions" / view["version"]
            self._write(version_dir / pkg.MANIFEST, verified.manifest_raw)
            self._write(version_dir / pkg.SIGNATURE, verified.signature)
            self._write(version_dir / pkg.SBOM, verified.sbom_raw)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        record = {
            "version": view["version"],
            "name": view["name"],
            "summary": view["summary"],
            "prefix": view["prefix"],
            "port": view["port"],
            "uid": view["uid"],
            "image": view["image"],
            "image_id": image_id,
            "publisher": verified.publisher,
            "permissions": view["permissions"],
            "asset_types": list(view["requires"].get("asset_types") or []),
            "package_sha256": verified.sha256,
            "installed_at": now(),
            "requested_by": requested_by,
        }
        state = self.app_state(app_id)
        current = state.get("current")
        previous = (
            current
            if current and current.get("version") != record["version"]
            else state.get("previous")
        )
        self._activate(app_id, manifest, record, request_id, app_key=app_key, previous=previous)
        return {"app_id": app_id, "version": view["version"], "message": "installed"}

    def _prepare_folders(self, app_id: str, uid: int, app_key: str | None) -> bool:
        """Creates the app's data folder and key file, owned by its user; True when it has a key."""

        secret_dir = self.state / "secrets" / app_id
        key_file = secret_dir / "app-key"
        steps = [
            f"mkdir -p /d/apps/{app_id} && chown {uid}:{uid} /d/apps/{app_id} "
            f"&& chmod 0700 /d/apps/{app_id}"
        ]
        if app_key:
            secret_dir.mkdir(mode=0o700, exist_ok=True)
            self._write(secret_dir / "app-key.new", app_key + "\n", 0o600)
            relative = f"installer/secrets/{app_id}"
            steps.append(
                f"mv -f /d/{relative}/app-key.new /d/{relative}/app-key "
                f"&& chown {uid}:{uid} /d/{relative}/app-key && chmod 0400 /d/{relative}/app-key"
            )
        self.helper(" && ".join(["set -e", *steps]))
        return bool(app_key) or key_file.exists() or bool(self.app_state(app_id).get("has_key"))

    def _activate(
        self,
        app_id: str,
        manifest: dict[str, Any],
        record: dict[str, Any],
        request_id: str,
        *,
        app_key: str | None,
        previous: dict[str, Any] | None,
    ) -> None:
        """Writes the compose file and route, starts the app; puts the old ones back on failure."""

        folder = self.app_dir(app_id)
        compose_path = folder / "compose.json"
        route_path = self.state / "routes" / f"{app_id}.caddy"
        old_compose = compose_path.read_bytes() if compose_path.exists() else None
        old_route = route_path.read_bytes() if route_path.exists() else None
        self.report(request_id, step="start")
        has_key = self._prepare_folders(app_id, pkg.flat(manifest)["uid"], app_key)
        self._json(compose_path, self.service(manifest, has_key=has_key))
        try:
            self.start_app(app_id)
            self._write(route_path, self.route(manifest))
            self.report(request_id, step="proxy")
            self.restart_proxy()
        except InstallError as exc:
            self._restore(app_id, compose_path, old_compose, route_path, old_route)
            raise InstallError(f"the app did not start; the previous state is back. {exc}") from exc
        self._json(
            folder / "state.json",
            {"current": record, "previous": previous, "has_key": has_key},
        )

    def _restore(
        self,
        app_id: str,
        compose_path: Path,
        old_compose: bytes | None,
        route_path: Path,
        old_route: bytes | None,
    ) -> None:
        try:
            if old_compose is None:
                self.stop_app(app_id)
                compose_path.unlink(missing_ok=True)
            else:
                self._write(compose_path, old_compose)
                self.start_app(app_id)
            if old_route is None:
                route_path.unlink(missing_ok=True)
            else:
                self._write(route_path, old_route)
            self.restart_proxy()
        except InstallError:
            pass  # Reported with the original error; `docker compose ps` shows the rest.

    def uninstall(self, app_id: str, request_id: str) -> dict[str, Any]:
        state = self.app_state(app_id)
        compose_path = self.app_dir(app_id) / "compose.json"
        if not state.get("current") and not compose_path.exists():
            raise InstallError(f"{app_id} is not installed by the installer")
        self.report(request_id, step="stop")
        if compose_path.exists():
            self.stop_app(app_id)
            compose_path.unlink()
        (self.state / "routes" / f"{app_id}.caddy").unlink(missing_ok=True)
        self.report(request_id, step="proxy")
        self.restart_proxy()
        if (self.state / "secrets" / app_id).exists():
            self.helper(f"rm -rf /d/installer/secrets/{app_id}")
        version = (state.get("current") or {}).get("version")
        # The versions and the data folder stay; a later install of the app reads its data again.
        self._json(
            self.app_dir(app_id) / "state.json", {"current": None, "previous": state.get("current")}
        )
        return {"app_id": app_id, "version": version, "message": "uninstalled; its data is kept"}

    def rollback(self, app_id: str, request_id: str, requested_by: str) -> dict[str, Any]:
        state = self.app_state(app_id)
        previous = state.get("previous")
        if not state.get("current") or not previous:
            raise InstallError(f"{app_id} has no previous version to return to")
        version_dir = self.app_dir(app_id) / "versions" / str(previous.get("version"))
        try:
            raw = (version_dir / pkg.MANIFEST).read_bytes()
            signature = (version_dir / pkg.SIGNATURE).read_bytes()
        except OSError as exc:
            raise InstallError("the previous version's manifest is gone") from exc
        self.report(request_id, step="verify", version=previous.get("version"))
        document = pkg.strict_json(raw, pkg.MANIFEST)
        try:
            key = pkg.trusted_key(document, pkg.load_trusted(self.trusted_dir))
        except pkg.PackageError as exc:
            raise InstallError(f"the previous version can no longer be trusted: {exc}") from exc
        pkg.verify_signature(raw, signature, key)
        manifest = pkg.validate_manifest(document)
        view = pkg.flat(manifest)
        if view["id"] != app_id:
            raise InstallError("the previous version belongs to another app")
        image_id = self.docker.image_id(view["image"])
        if not image_id or image_id != previous.get("image_id"):
            raise InstallError(
                f"image {view['image']} is no longer the one installed; install that package again"
            )
        self._check_conflicts(manifest)
        record = {**previous, "installed_at": now(), "requested_by": requested_by}
        self._activate(
            app_id, manifest, record, request_id, app_key=None, previous=state.get("current")
        )
        return {"app_id": app_id, "version": view["version"], "message": "rolled back"}

    def set_key(self, app_id: str, app_key: str | None, request_id: str) -> dict[str, Any]:
        state = self.app_state(app_id)
        current = state.get("current")
        if not current or not app_key:
            raise InstallError(f"{app_id} is not installed, or no key was sent")
        version_dir = self.app_dir(app_id) / "versions" / current["version"]
        manifest = pkg.validate_manifest(
            pkg.strict_json((version_dir / pkg.MANIFEST).read_bytes(), "manifest")
        )
        self._activate(
            app_id, manifest, dict(current), request_id, app_key=app_key,
            previous=state.get("previous"),
        )  # fmt: skip
        return {"app_id": app_id, "version": current["version"], "message": "app key set"}

    # Diagnostic bundle ---------------------------------------------------------------------

    @property
    def diagnostics_dir(self) -> Path:
        return self.state / "status" / "diagnostics"

    def diagnostics(self, request_id: str, requested_by: str) -> Path:
        """A zip of what support needs to see: versions, images, Docker's view of every
        service, the health and metrics, the end of each service's log, the settings with
        every secret replaced, disk, backups, the last drill and the operations journal,
        Docker and host facts. Never databases, plant data, certificates or keys."""

        self.prune_diagnostics()
        target = self.diagnostics_dir / f"{request_id}.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.partial")
        inside: list[str] = []
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as bundle:

            def put(name: str, data: str | bytes) -> None:
                bundle.writestr(f"diagnostics/{name}", data)
                inside.append(name)

            def run(*args: str, timeout: float = 60) -> str:
                try:
                    done = self.docker.run(*args, check=False, timeout=timeout)
                except InstallError as exc:
                    return f"(failed: {exc})\n"
                return redact((done.stdout or "") + (done.stderr or ""))

            def compose(*args: str, timeout: float = 60) -> str:
                try:
                    done = self.compose(*args, timeout=timeout)
                except InstallError as exc:
                    return f"(failed: {exc})\n"
                return redact(done.stdout or "")

            status = self.state / "status"
            for name in STATUS_FILES:
                path = status / name
                if path.is_file() and path.stat().st_size <= 8 * 2**20:
                    put(f"status/{name}", redact(path.read_text("utf-8", errors="replace")))
            put("compose-ps.json", compose("ps", "-a", "--format", "json"))
            put("compose-images.json", compose("images", "--format", "json"))
            put("settings.env", settings_text(dict(os.environ)))
            try:
                disk = shutil.disk_usage(self.install_dir)
                put("disk.json", json.dumps(
                    {"path": str(self.install_dir), "total_bytes": disk.total,
                     "free_bytes": disk.free, "used_bytes": disk.used}, indent=2))  # fmt: skip
            except OSError as exc:
                put("disk.json", json.dumps({"error": str(exc)}))
            put("docker-version.json", run("version", "--format", "{{json .}}"))
            put("docker-info.json", run("info", "--format", "{{json .}}"))
            put("host.json", json.dumps(
                {"platform": platform.platform(), "machine": platform.machine(),
                 "cpus": os.cpu_count(), "python": platform.python_version(),
                 "collected_at": now(), "requested_by": requested_by}, indent=2))  # fmt: skip
            services = []
            try:
                services = sorted(
                    {str(c.get("Service")) for c in json_lines(self.compose(
                        "ps", "-a", "--format", "json", timeout=60).stdout) if c.get("Service")}
                )  # fmt: skip
            except (InstallError, ValueError):
                services = []
            for service in services:
                text = compose("logs", "--no-color", "--timestamps", "--tail", str(LOG_LINES),
                               service, timeout=120)  # fmt: skip
                data = text.encode("utf-8", errors="replace")[-LOG_BYTES:]
                put(f"logs/{re.sub(r'[^A-Za-z0-9_.-]', '-', service)}.log", data)
            put("README.txt", self._readme(inside, requested_by))
        partial.chmod(0o640)
        partial.replace(target)
        return target

    @staticmethod
    def _readme(inside: list[str], requested_by: str) -> str:
        return (
            "PlantCraft diagnostic bundle\n"
            f"Collected {now()} for {requested_by} by the installer service.\n\n"
            "It holds what support needs to see why the suite misbehaves: versions and images,\n"
            "Docker's view of every service, the suite's health and metrics, the end of each\n"
            "service's log (at most 20 MB each), the settings with every password, key, token\n"
            "and secret replaced by ***, the disk, the backups, the last restore drill, the\n"
            "operations journal, and Docker and host facts.\n\n"
            "It never holds databases, plant data, certificates or keys. Read it before you send\n"
            "it: log lines may name tags, assets and people of the plant.\n\nFiles:\n"
            + "".join(f"  {name}\n" for name in inside)
        )

    def prune_diagnostics(self, hours: float = DIAGNOSTICS_HOURS) -> int:
        """Removes diagnostic bundles older than ``hours``; how many."""

        removed = 0
        limit = time.time() - hours * 3600
        for path in self.diagnostics_dir.glob("*.zip") if self.diagnostics_dir.is_dir() else []:
            try:
                if path.stat().st_mtime < limit:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    # Loop ----------------------------------------------------------------------------------

    def serve(self, stop_after: int | None = None) -> None:
        loops, next_metrics = 0, 0.0
        while stop_after is None or loops < stop_after:
            self.heartbeat()
            try:
                self.process_pending()
                self.run_schedule()
                if time.monotonic() >= next_metrics:
                    next_metrics = time.monotonic() + METRICS_SECONDS
                    self.publish_metrics()
                    self.prune_diagnostics()
            except (OSError, InstallError) as exc:
                print(f"installer: {exc}", file=sys.stderr, flush=True)
            loops += 1
            if stop_after is None or loops < stop_after:
                time.sleep(POLL_SECONDS)


def healthy(state_dir: Path) -> bool:
    try:
        beat = json.loads((state_dir / "status" / "heartbeat.json").read_text(encoding="utf-8"))
        at = datetime.fromisoformat(beat["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return (datetime.now(timezone.utc) - at).total_seconds() < HEARTBEAT_SECONDS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="processcraft-installer")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="process requests from PlantCraft (the compose service)")
    commands.add_parser("health", help="exit 0 when the service wrote its heartbeat recently")
    add = commands.add_parser("add", help="install a package now (install.sh --add)")
    add.add_argument("package", help="path, or - to read it from standard input")
    add.add_argument("--by", default="install.sh")
    for name in ("remove", "rollback"):
        command = commands.add_parser(name, help=f"{name} an app now (install.sh --{name})")
        command.add_argument("app_id")
        command.add_argument("--by", default="install.sh")
    commands.add_parser("list", help="the apps this installer runs (JSON)")
    diagnostics = commands.add_parser(
        "diagnostics", help="write a diagnostic bundle (install.sh --diagnostics)"
    )
    diagnostics.add_argument("--out", default="-", help="the zip's path, or - for standard output")
    diagnostics.add_argument("--by", default="install.sh")
    package_cli = commands.add_parser(
        "package", help="the package tool (keygen, build, verify, index)"
    )
    package_cli.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "package":
        return pkg.main(args.args)
    if args.command == "health":
        state = Path(os.environ.get("PLANTCRAFT_INSTALL_DIR", "/")) / "data" / "installer"
        return 0 if healthy(state) else 1
    installer = Installer.from_environment()
    if args.command == "serve":
        print(
            f"installer: watching {installer.requests} (no network, Docker socket only)", flush=True
        )
        installer.serve()
        return 0
    if args.command == "list":
        print(json.dumps(installer.installed(), indent=2))
        return 0
    request_id = uuid.uuid4().hex
    by = re.sub(r"[^\w.@:-]", "", args.by)[:60] or "install.sh"
    if args.command == "diagnostics":
        path = installer.diagnostics(request_id, f"cli:{by}")
        if args.out == "-":
            with path.open("rb") as handle:
                shutil.copyfileobj(handle, sys.stdout.buffer)
            sys.stdout.buffer.flush()
        else:
            shutil.copyfile(path, args.out)
            print(args.out)
        return 0
    if args.command == "add":
        source = args.package
        target = installer.state / "work" / f"cli-{request_id}.pcapp"
        try:
            with target.open("wb") as out:
                if source == "-":
                    shutil.copyfileobj(sys.stdin.buffer, out, pkg.CHUNK)
                else:
                    with open(source, "rb") as handle:
                        shutil.copyfileobj(handle, out, pkg.CHUNK)
            result = installer.handle(
                {
                    "request_id": request_id,
                    "action": "install",
                    "app_id": None,
                    "requested_by": f"cli:{by}",
                },
                target,
            )
        finally:
            target.unlink(missing_ok=True)
    else:
        action = "uninstall" if args.command == "remove" else "rollback"
        result = installer.handle(
            {
                "request_id": request_id,
                "action": action,
                "app_id": args.app_id,
                "requested_by": f"cli:{by}",
            }
        )
    print(json.dumps(result, indent=2))
    return 0 if result.get("state") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
