"""Backup and restore of an installation, and their schedule (docs/operations.md).

Two halves, both in the installer image:

- The **installer service** (uid 10005, no network) reads the operation requests PlantCraft
  writes (``action`` backup, verify, restore, prune), runs the schedule (``due``) and starts
  the driver for each (``launch``).
- The **driver** (``Driver``): a one-off container of the installer image named
  ``processcraft-ops``, root, no network, with the install folder at its own path and the Docker
  socket. It is outside the Compose project, so it keeps running while it stops and starts the
  suite (a restore). Its name is the lock: Docker never runs two containers with one name.
  ``install.sh --backup`` and ``--restore`` run the same driver in the foreground.

Files. The journal lives beside ``data/``, never inside it, because a restore swaps ``data/``::

    .ops/current.json       the operation running and its phase (the journal; root only)
    .ops/history.jsonl      one line per finished operation

and what PlantCraft and the proxy read is in ``data/installer/status`` (handed to the
installer's user, carried across a restore)::

    operation.json          the operation running, its phase (a copy of the journal), else none
    operations.json         the last 50 finished operations
    backups.json            every backup and its state
    requests/<id>.json      the outcome of a request, as for app requests

A backup is ``backups/<date>-<reason>/`` (``plantcraft.ops.snapshot``): ``manifest.json``,
``data.tar.gz``, ``histcraft-db/`` (the Historian's database, a full or incremental base backup,
``plantcraft.apps.historian_backup``) and ``status.json`` (``ok`` once verified, else ``failed``
with the problems).
A restore first renames the current state to ``backups/<date>-before-restore/`` and returns to it
by itself when the suite does not come back healthy.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from plantcraft.apps import historian_backup
from plantcraft.apps.historian_backup import HistorianBackup, HistorianBackupError
from plantcraft.apps.installer import Docker, InstallError, json_lines
from plantcraft.ops import snapshot

DRIVER = "processcraft-ops"
ACTIONS = ("backup", "verify", "restore", "prune", "drill")
REASONS = ("manual", "daily", "pre-update", "pre-restore")
NAME = re.compile(r"^\d{8}-\d{6}-[a-z][a-z0-9-]{1,30}$")
INSTALLER_UID = 10005
WAIT_SECONDS = 600
HISTCRAFT_DB = "histcraft-db"
# Older backups hold the Historian's database as a pg_dump; they still restore.
DUMP = "histcraft-db.dump"
# Retention (docs/operations.md, section 2): the newest of each kind are kept.
KEEP = {"daily": 7, "weekly": 4, "monthly": 3, "manual": 5, "aside": 2}
FAILED_DAYS = 7
DEFAULT_SCHEDULE = {
    "enabled": True,
    "daily_at": "02:00",
    # "local": the installation's zone, which PlantCraft writes beside it as ``local_zone``.
    "timezone": "local",
    "local_zone": "UTC",
    # The weekly restore drill: weekday 0 is Monday, 6 Sunday.
    "drill": True,
    "drill_weekday": 6,
    "drill_at": "03:00",
}
# The restore drill (docs/operations.md, section 2): its own Compose project, no route out, no
# published port the plant could reach, never the installer (it holds the Docker socket).
DRILL_PROJECT = "processcraft-drill"
DRILL_SKIPPED_SERVICES = ("installer",)
DRILL_MEMORY = 2 * 2**30
DRILL_ENV = {
    "PLANTCRAFT_EDGE_SUBNET": "172.31.12.0/24",
    "PLANTCRAFT_APPS_SUBNET": "172.31.11.0/24",
    "PLANTCRAFT_PLANT_SUBNET": "172.31.10.0/24",
    "PLANTCRAFT_DEMO_SUBNET": "172.31.13.0/24",
    "PLANTCRAFT_HISTDB_SUBNET": "172.31.14.0/24",
    "PLANTCRAFT_PROXY_ADDRESS": "172.31.11.250",
    "PLANTCRAFT_BIND_ADDRESS": "127.0.0.1",
    "PLANTCRAFT_HTTPS_PORT": "0",
}
# Every network of the drill is internal: nothing in it reaches out of the host (or the plant).
DRILL_OVERRIDE = "networks:\n" + "".join(
    f"  {name}:\n    internal: true\n" for name in ("edge", "apps", "plant", "demo", "histdb")
)


class OperationError(Exception):
    """An operation that stopped; the message is for the administrator."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")


def parse_stamp(name: str) -> datetime | None:
    try:
        return datetime.strptime(name[:15], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# Retention ---------------------------------------------------------------------------------


def to_delete(backups: Iterable[dict[str, Any]], now: datetime) -> list[str]:
    """The backups retention removes (the newest of each kind stay, see ``KEEP``).

    Never removed: the newest good backup of all, the newest ``pre-update`` (the way back from
    the last update), anything whose date cannot be read, and every backup a kept one builds on
    (its Historian database is incremental: ``chain``). Weekly and monthly keep a full backup of
    the period when there is one, so that old periods hold no chain of incrementals.
    """

    items = [b for b in backups if parse_stamp(str(b.get("name", ""))) and b.get("name")]
    items.sort(key=lambda b: b["name"], reverse=True)
    good = [b for b in items if b.get("state") == "ok"]
    keep: set[str] = set()
    if good:
        keep.add(good[0]["name"])
    updates = [b for b in good if b.get("reason") == "pre-update"]
    if updates:
        keep.add(updates[0]["name"])
    daily = [b for b in good if b.get("reason") == "daily"]
    keep.update(b["name"] for b in daily[: KEEP["daily"]])
    for period, size in (("weekly", KEEP["weekly"]), ("monthly", KEEP["monthly"])):
        periods: dict[str, list[dict[str, Any]]] = {}
        for backup in daily:
            moment = parse_stamp(backup["name"])
            assert moment is not None
            key = moment.strftime("%G-%V") if period == "weekly" else moment.strftime("%Y-%m")
            periods.setdefault(key, []).append(backup)
        for key in list(periods)[:size]:
            full = [b for b in periods[key] if _kind(b) != "incremental"]
            keep.add((full or periods[key])[0]["name"])
    manual = [b for b in good if b.get("reason") in {"manual", "pre-restore"}]
    keep.update(b["name"] for b in manual[: KEEP["manual"]])
    asides = [b for b in items if b.get("reason") in {"before-restore", "before-rollback"}]
    keep.update(b["name"] for b in asides[: KEEP["aside"]])
    held = set(keep)
    for backup in items:
        if backup["name"] in keep:
            held.update(str(name) for name in (backup.get("histcraft_db") or {}).get("chain") or [])
    keep = held
    remove = []
    for backup in items:
        if backup["name"] in keep:
            continue
        if backup.get("state") == "failed" or backup.get("state") not in {"ok", "aside"}:
            moment = parse_stamp(backup["name"])
            if moment and now - moment < timedelta(days=FAILED_DAYS):
                continue
        elif backup.get("reason") == "pre-update":
            continue  # older pre-update backups go only with an explicit prune of updates
        remove.append(backup["name"])
    return sorted(remove)


def _kind(backup: dict[str, Any]) -> str:
    return str((backup.get("histcraft_db") or {}).get("kind") or "")


# Schedule ----------------------------------------------------------------------------------


def schedule_settings(path: Path) -> dict[str, Any]:
    """The schedule PlantCraft wrote (``ops-settings.json``), checked; defaults otherwise."""

    settings = dict(DEFAULT_SCHEDULE)
    try:
        given = json.loads(path.read_text(encoding="utf-8")).get("backup") or {}
    except (OSError, ValueError, AttributeError):
        return settings
    if isinstance(given.get("enabled"), bool):
        settings["enabled"] = given["enabled"]
    if isinstance(given.get("daily_at"), str) and re.match(
        r"^([01]\d|2[0-3]):[0-5]\d$", given["daily_at"]
    ):
        settings["daily_at"] = given["daily_at"]
    for key in ("timezone", "local_zone"):
        if isinstance(given.get(key), str) and re.match(r"^[A-Za-z0-9_/+-]{1,64}$", given[key]):
            settings[key] = given[key]
    if isinstance(given.get("drill"), bool):
        settings["drill"] = given["drill"]
    weekday = given.get("drill_weekday")
    if isinstance(weekday, int) and not isinstance(weekday, bool) and 0 <= weekday <= 6:
        settings["drill_weekday"] = weekday
    if isinstance(given.get("drill_at"), str) and re.match(
        r"^([01]\d|2[0-3]):[0-5]\d$", given["drill_at"]
    ):
        settings["drill_at"] = given["drill_at"]
    return settings


def _zone(settings: dict[str, Any]) -> Any:
    name = settings.get("timezone", "local")
    if name == "local":
        name = settings.get("local_zone") or "UTC"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # no tz database in the image, or an unknown name: UTC
        return timezone.utc


def due(settings: dict[str, Any], last_daily: str | None, now: datetime) -> bool:
    """True when today's backup (in the schedule's time zone) is due and not yet taken."""

    if not settings.get("enabled", True):
        return False
    local = now.astimezone(_zone(settings))
    hour, minute = (int(part) for part in settings.get("daily_at", "02:00").split(":"))
    if (local.hour, local.minute) < (hour, minute):
        return False
    return last_daily != local.date().isoformat()


def drill_due(settings: dict[str, Any], last_drill: str | None, now: datetime) -> bool:
    """True on the drill's weekday, after its hour, when this week's drill has not run."""

    if not settings.get("enabled", True) or not settings.get("drill", True):
        return False
    local = now.astimezone(_zone(settings))
    hour, minute = (int(part) for part in settings.get("drill_at", "03:00").split(":"))
    if local.weekday() != settings.get("drill_weekday", 6) or (local.hour, local.minute) < (
        hour,
        minute,
    ):
        return False
    return last_drill != local.strftime("%G-W%V")


def local_week(settings: dict[str, Any], now: datetime) -> str:
    return now.astimezone(_zone(settings)).strftime("%G-W%V")


def local_day(settings: dict[str, Any], now: datetime) -> str:
    return now.astimezone(_zone(settings)).date().isoformat()


# The driver --------------------------------------------------------------------------------


def clean_env() -> dict[str, str]:
    """What Compose runs with: no setting of the suite, so it reads the current ``.env`` only."""

    keep = ("PATH", "HOME", "DOCKER_CONFIG", "DOCKER_HOST", "TZ")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.setdefault("HOME", "/tmp")
    return env


def env_values(path: Path) -> dict[str, str]:
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and re.match(r"^[A-Z][A-Z0-9_]*$", key.strip()):
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


CPU_LIMIT = re.compile(r'^\s*cpus:\s*"\$\{([A-Z][A-Z0-9_]*_CPUS):-([0-9.]+)\}"', re.MULTILINE)


def host_cpus() -> int:
    try:
        return len(os.sched_getaffinity(0)) or 1
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def fit_cpu_limits(install: Path, cpus: int | None = None) -> dict[str, str]:
    """Every ``${KEY:-default}`` CPU limit of compose.yaml capped at this host's CPU count, in
    ``.env`` (install.sh's fit_cpu_limits): Docker refuses a container whose limit is above the
    host's CPUs, and a backup brings the limits of the machine it was made on.
    Returns the keys it changed, with their old value."""

    cpus = cpus or host_cpus()
    try:
        compose = (install / "compose.yaml").read_text(encoding="utf-8")
    except OSError:
        return {}
    env_file = install / ".env"
    current = env_values(env_file)
    changed: dict[str, str] = {}
    for key, default in sorted(set(CPU_LIMIT.findall(compose))):
        value = current.get(key) or default
        try:
            over = float(value) > cpus
        except ValueError:
            continue
        if over:
            changed[key] = value
    if not changed:
        return {}
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    kept, written = [], set()
    for line in lines:
        key = line.partition("=")[0].strip()
        if key in changed:
            if key not in written:
                kept.append(f"{key}={cpus}")
                written.add(key)
            continue
        kept.append(line)
    kept += [f"{key}={cpus}" for key in changed if key not in written]
    status = env_file.stat() if env_file.exists() else None
    env_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
    if status is not None:
        os.chmod(env_file, status.st_mode & 0o7777)
        if os.geteuid() == 0:
            os.chown(env_file, status.st_uid, status.st_gid)
    return changed


class Driver:
    """Runs one operation against the installation at ``install_dir`` (as root, no network)."""

    def __init__(
        self,
        install_dir: str | Path,
        *,
        docker: Docker | None = None,
        project: str = "processcraft",
        owner: tuple[int, int] = (INSTALLER_UID, INSTALLER_UID),
        wait_seconds: int = WAIT_SECONDS,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.install = Path(install_dir)
        self.state = self.install / "data" / "installer"
        self.backups = self.install / "backups"
        self.docker = docker or Docker()
        self.project = project
        self.owner = owner
        self.wait_seconds = wait_seconds
        self.clock = clock
        self.request_id: str | None = None
        self.operation: dict[str, Any] = {}
        self.historian = HistorianBackup(self)

    # Files ---------------------------------------------------------------------------------

    def _hand_over(self, path: Path) -> None:
        if os.geteuid() == 0:
            os.chown(path, *self.owner)

    def _write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._hand_over(path.parent)
        partial = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}")
        partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        partial.chmod(0o644)
        self._hand_over(partial)
        partial.replace(path)

    def log(self, message: str) -> None:
        print(f"[{self.clock().strftime('%H:%M:%S')}] {message}", flush=True)

    @property
    def journal(self) -> Path:
        return self.install / ".ops" / "current.json"

    def _journal_write(self, value: dict[str, Any]) -> None:
        folder = self.journal.parent
        folder.mkdir(mode=0o700, exist_ok=True)
        partial = folder / f".current.{uuid.uuid4().hex[:8]}"
        partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        partial.chmod(0o600)
        partial.replace(self.journal)

    def phase(self, phase: str, **fields: Any) -> None:
        """Write the journal before each step: a driver that stops is finished or undone."""

        self.operation.update(phase=phase, updated_at=self.clock().isoformat(), **fields)
        self._journal_write(self.operation)
        self._mirror()
        if self.request_id:
            self.report(state="running", step=phase)
        self.log(phase)

    def _mirror(self) -> None:
        """The journal, without image ids, where PlantCraft and the proxy read it."""

        shown = {k: v for k, v in self.operation.items() if k != "images"}
        try:
            self._write_json(self.state / "status" / "operation.json", shown)
        except OSError:
            pass  # data/ is being swapped (a restore): the journal itself is beside it

    def report(self, **fields: Any) -> None:
        if not self.request_id:
            return
        path = self.state / "status" / "requests" / f"{self.request_id}.json"
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        self._write_json(
            path,
            {
                **current,
                "request_id": self.request_id,
                **fields,
                "updated_at": self.clock().isoformat(),
            },
        )

    def finish(self, outcome: dict[str, Any]) -> dict[str, Any]:
        record = {**self.operation, **outcome, "finished_at": self.clock().isoformat()}
        for key in ("phase", "images"):
            record.pop(key, None)
        history = self.journal.with_name("history.jsonl")
        history.parent.mkdir(mode=0o700, exist_ok=True)
        with history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        history.chmod(0o600)
        self.journal.unlink(missing_ok=True)
        lines = history.read_text(encoding="utf-8").splitlines()[-50:]
        self._write_json(
            self.state / "status" / "operations.json",
            {"operations": [json.loads(line) for line in reversed(lines)]},
        )
        (self.state / "status" / "operation.json").unlink(missing_ok=True)
        self.report(state="done" if outcome.get("state") == "ok" else "failed", step="done",
                    **{k: v for k, v in outcome.items() if k != "state"})  # fmt: skip
        self.index()
        return outcome

    # Docker --------------------------------------------------------------------------------

    def compose_files(self) -> list[str]:
        files = ["-f", str(self.install / "compose.yaml")]
        for path in sorted((self.state / "apps").glob("*/compose.json")):
            files += ["-f", str(path)]
        return files

    def compose(self, *args: str, timeout: float = 900, **kwargs: Any) -> Any:
        return self.docker.run(
            "compose", "--project-name", self.project, "--project-directory", str(self.install),
            *self.compose_files(), *args, timeout=timeout, env=clean_env(), **kwargs,
        )  # fmt: skip

    def running(self, service: str) -> bool:
        result = self.compose("ps", "-q", "--status", "running", service, check=False)
        return result.returncode == 0 and bool(result.stdout.strip())

    def images(self) -> list[dict[str, str]]:
        """Every image the suite runs now, with its id."""

        result = self.compose("config", "--images", check=False)
        found = []
        for ref in sorted(set(result.stdout.split())):
            image_id = self.docker.image_id(ref)
            if image_id:
                found.append({"ref": ref, "id": image_id})
        return found

    def retag(self, images: Iterable[dict[str, str]]) -> list[str]:
        """Point each reference at the image id it had (``docker tag``); returns those missing."""

        missing = []
        for image in images:
            ref, image_id = image.get("ref", ""), image.get("id", "")
            if "@sha256:" in ref:
                if not self.docker.image_id(ref):
                    missing.append(ref)
                continue
            if self.docker.run("tag", image_id, ref, check=False).returncode != 0:
                missing.append(ref)
        return missing

    def keep_images(self, images: Iterable[dict[str, str]], when: str) -> None:
        """A ``:rollback-<date>`` tag keeps each image on the host when a new one takes its name."""

        for image in images:
            name = image["ref"].split("@", 1)[0]
            if ":" in name.rsplit("/", 1)[-1]:
                name = name.rsplit(":", 1)[0]
            self.docker.run("tag", image["id"], f"{name}:rollback-{when}", check=False)

    def free_bytes(self) -> int:
        return shutil.disk_usage(self.install).free

    # Index ---------------------------------------------------------------------------------

    def list_backups(self) -> list[dict[str, Any]]:
        found = []
        if not self.backups.is_dir():
            return found
        for folder in sorted(self.backups.iterdir(), reverse=True):
            if not folder.is_dir() or not NAME.match(folder.name):
                continue
            try:
                status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                status = {}
            item: dict[str, Any] = {"name": folder.name, "state": status.get("state", "unknown")}
            item["reason"] = folder.name[16:]
            for key in ("problems", "verified_at", "drill", "restored_from"):
                if key in status:
                    item[key] = status[key]
            try:
                manifest = snapshot.read_manifest(folder)
                historian = manifest.get("histcraft_db") or None
                item.update(
                    created_at=manifest.get("created_at"),
                    size=int((manifest.get("archive") or {}).get("size") or 0)
                    + int((historian or {}).get("size") or 0),
                    versions=manifest.get("versions") or {},
                    suite_version=manifest.get("suite_version"),
                )
                if historian:
                    item["histcraft_db"] = {
                        key: historian.get(key)
                        for key in ("kind", "base", "chain", "lineage", "pg_version",
                                    "system_identifier", "size", "database_bytes", "why_full")
                    }  # fmt: skip
            except snapshot.SnapshotError:
                if item["state"] == "unknown":
                    item["state"] = "aside" if (folder / "data").exists() else "failed"
            found.append(item)
        # Which newer backups build on each one (retention keeps it for them).
        by_name = {item["name"]: item for item in found}
        for item in found:
            for name in ((item.get("histcraft_db") or {}).get("chain") or [])[:-1]:
                if name in by_name:
                    by_name[name].setdefault("needed_by", []).append(item["name"])
        return found

    def index(self) -> list[dict[str, Any]]:
        backups = self.list_backups()
        self.publish_release()
        self._write_json(
            self.state / "status" / "backups.json",
            {
                "at": self.clock().isoformat(),
                "backups": backups,
                "free_bytes": self.free_bytes(),
            },  # fmt: skip
        )
        return backups

    def publish_release(self) -> None:
        """The installed release and its notes, for the Updates page (PlantCraft cannot read
        the install folder)."""

        try:
            release = json.loads((self.install / "release.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            release = None
        try:
            notes = (self.install / "RELEASE-NOTES.md").read_text(encoding="utf-8")[:262144]
        except OSError:
            notes = ""
        env = env_values(self.install / ".env")
        self._write_json(
            self.state / "status" / "release.json",
            {"version": env.get("PLANTCRAFT_VERSION", ""), "release": release, "notes": notes},
        )

    def _status(self, folder: Path, **fields: Any) -> None:
        path = folder / "status.json"
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        path.write_text(json.dumps({**current, **fields}, indent=2, sort_keys=True) + "\n")
        path.chmod(0o600)

    # Backup --------------------------------------------------------------------------------

    def context(self) -> dict[str, Any]:
        env = env_values(self.install / ".env")
        versions = {
            key[: -len("_VERSION")].lower(): value
            for key, value in sorted(env.items())
            if key.endswith("_VERSION") and value
        }
        return {
            "installation_id": env.get("PLANTCRAFT_INSTALLATION_ID", ""),
            "suite_version": env.get("PLANTCRAFT_VERSION", ""),
            "versions": versions,
            "profiles": env.get("COMPOSE_PROFILES", ""),
            "images": self.images(),
        }

    def histcraft_image(self, config: dict[str, Any] | None = None) -> str:
        """The image of the Historian's database in the settings (the PostgreSQL tools)."""

        if config is None:
            config = json.loads(self.compose("config", "--format", "json").stdout or "{}")
        image = str(((config.get("services") or {}).get(HISTCRAFT_DB) or {}).get("image") or "")
        if not image:
            raise OperationError("the settings name no image for the Historian database")
        return image

    def backup(self, reason: str) -> dict[str, Any]:
        if reason not in REASONS:
            raise OperationError(f"unknown reason {reason!r}")
        moment = self.clock()
        name = f"{stamp(moment)}-{reason}"
        self.operation = {"action": "backup", "name": name, "reason": reason,
                          "started_at": moment.isoformat()}  # fmt: skip
        backups = self.list_backups()
        try:
            plan = self.historian.plan(backups)
        except (InstallError, HistorianBackupError) as exc:
            raise OperationError(f"the backup {name} failed: {exc}") from exc
        previous = [b for b in backups if b.get("size")]
        files = max(
            (int(b["size"]) - int((b.get("histcraft_db") or {}).get("size") or 0)
             for b in previous[:1]), default=0,
        )  # fmt: skip
        needed = 2 * files + (self.historian.needed_bytes(plan, backups) if plan else 0)
        if self.free_bytes() < needed:
            raise OperationError(
                f"not enough free disk: {self.free_bytes() // 2**20} MB free, this backup needs "
                f"{needed // 2**20} MB. Free space or remove old backups."
            )
        self.backups.mkdir(mode=0o700, exist_ok=True)
        self.backups.chmod(0o700)
        folder = self.backups / name
        problems: list[str] = []
        try:
            self.phase("context")
            context = self.context()
            if plan:
                kind = "an incremental" if plan.get("base") else "a full"
                self.phase(f"backing up the Historian database ({kind} backup)")
                context["histcraft_db"] = self.historian.take(name, plan)
            self.phase("copying")
            snapshot.take(self.install, folder, reason=reason, context=context)
            if plan:
                self.historian.place(name, folder)
            self.phase("verifying")
            problems = snapshot.verify(folder)
            if plan and not problems:
                problems = self.historian.verify(context["histcraft_db"], self.histcraft_image())
            state = "failed" if problems else "ok"
            self._status(folder, state=state, problems=problems,
                         verified_at=self.clock().isoformat())  # fmt: skip
            if state == "ok":
                self.keep_images(context["images"], stamp(moment))
        except (OSError, ValueError, InstallError, snapshot.SnapshotError, HistorianBackupError,
                OperationError) as exc:  # fmt: skip
            if folder.is_dir():
                self._status(folder, state="failed", problems=[str(exc)])
            raise OperationError(f"the backup {name} failed: {exc}") from exc
        finally:
            self.historian.discard()
        if problems:
            raise OperationError(f"the backup {name} did not pass its check: {problems[0]}")
        size = folder.joinpath(snapshot.ARCHIVE).stat().st_size
        historian = context.get("histcraft_db") or {}
        outcome: dict[str, Any] = {"state": "ok", "name": name,
                                   "size": size + int(historian.get("size") or 0)}  # fmt: skip
        if historian:
            outcome["histcraft_db"] = historian["kind"]
        return outcome

    def verify(self, name: str) -> dict[str, Any]:
        """Check a backup again, reading every file of it, its Historian chain included."""

        folder = self._folder(name)
        self.operation = {"action": "verify", "name": name, "started_at": self.clock().isoformat()}
        self.phase("verifying")
        problems = snapshot.verify(folder)
        historian = snapshot.read_manifest(folder).get("histcraft_db") if not problems else None
        if historian:
            try:
                problems = self.historian.verify(historian, self.histcraft_image(), deep=True)
            except (InstallError, HistorianBackupError, OperationError, ValueError) as exc:
                problems = [str(exc)]
        self._status(folder, state="failed" if problems else "ok", problems=problems,
                     verified_at=self.clock().isoformat())  # fmt: skip
        if problems:
            raise OperationError(f"{name} did not pass its check: {problems[0]}")
        return {"state": "ok", "name": name}

    def _folder(self, name: str) -> Path:
        if not NAME.match(name):
            raise OperationError(f"no backup named {name!r}")
        folder = self.backups / name
        if not (folder / snapshot.MANIFEST).is_file():
            raise OperationError(f"no backup named {name!r}")
        return folder

    def prune(self) -> dict[str, Any]:
        removed = to_delete(self.list_backups(), self.clock())
        for name in removed:
            shutil.rmtree(self.backups / name, ignore_errors=True)
            self.log(f"removed backups/{name} (retention)")
        return {"state": "ok", "removed": removed}

    # Restore drill -------------------------------------------------------------------------

    @staticmethod
    def available_memory() -> int:
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        return DRILL_MEMORY

    def drill_compose(self, target: Path, scratch: Path, *args: str, **kwargs: Any) -> Any:
        files = ["-f", str(target / "compose.yaml")]
        for path in sorted((scratch / "apps").glob("*.json")):
            files += ["-f", str(path)]
        files += ["-f", str(scratch / "drill.yaml")]
        return self.docker.run(
            "compose", "--project-name", DRILL_PROJECT, "--project-directory", str(target),
            *files, "--env-file", str(target / ".env"), "--env-file", str(scratch / "drill.env"),
            *args, env=clean_env(), **kwargs,
        )  # fmt: skip

    def _drill_files(self, target: Path, scratch: Path) -> None:
        """The drill's settings: other subnets, no published port, every network internal, and
        the installed apps' services pointing at the drill's copy instead of the live folder."""

        env = {**DRILL_ENV, "PLANTCRAFT_INSTALL_DIR": str(target)}
        (scratch / "drill.env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
        (scratch / "drill.yaml").write_text(DRILL_OVERRIDE)
        (scratch / "apps").mkdir(exist_ok=True)
        live = str(self.install)
        for path in sorted((target / "data" / "installer" / "apps").glob("*/compose.json")):
            text = path.read_text(encoding="utf-8").replace(live, str(target))
            (scratch / "apps" / f"{path.parent.name}.json").write_text(text)

    def drill_guard(self, config: dict[str, Any], target: Path) -> list[str]:
        """What would let the drill touch the live installation (it must find nothing)."""

        problems = []
        live = str(self.install).rstrip("/") + "/"
        for name, service in sorted((config.get("services") or {}).items()):
            if name in DRILL_SKIPPED_SERVICES:
                continue  # never started in the drill
            for volume in service.get("volumes") or []:
                source = str(volume.get("source", "")) if isinstance(volume, dict) else ""
                if source.startswith(live) and not source.startswith(str(target)):
                    problems.append(f"{name} mounts the live folder {source}")
                if "docker.sock" in source:
                    problems.append(f"{name} mounts the Docker socket")
            for port in service.get("ports") or []:
                if isinstance(port, dict) and port.get("host_ip") not in {"127.0.0.1", None}:
                    problems.append(f"{name} publishes a port on {port.get('host_ip')}")
        for name, network in sorted((config.get("networks") or {}).items()):
            if not network.get("internal"):
                problems.append(f"network {name} is not internal")
        return problems

    def drill(self, name: str | None = None) -> dict[str, Any]:
        """Restore a backup into a separate, isolated copy of the suite and start it."""

        good = [b for b in self.list_backups() if b.get("state") == "ok"]
        if name is None:
            if not good:
                raise OperationError("no good backup to test yet")
            name = good[0]["name"]
        folder = self._folder(name)
        moment = self.clock()
        self.operation = {"action": "drill", "name": name, "started_at": moment.isoformat()}
        manifest = snapshot.read_manifest(folder)
        unpacked = sum(int(f.get("size") or 0) for f in (manifest.get("files") or {}).values())
        needed = int(unpacked * 1.5) + int((manifest.get("archive") or {}).get("size") or 0)
        historian = manifest.get("histcraft_db") or {}
        needed += int(int(historian.get("database_bytes") or 0) * 1.1)
        if self.free_bytes() < needed:
            raise OperationError(
                f"not enough free disk for the restore drill: {needed // 2**20} MB needed"
            )
        if self.available_memory() < DRILL_MEMORY:
            raise OperationError(
                "not enough free memory for the restore drill (2 GB): it runs a second copy of "
                "the suite. Run it at a quieter hour or on a larger server."
            )
        scratch = self.backups / f".drill-{stamp(moment)}"
        target = scratch / "install"
        problems: list[str] = []
        started = time.monotonic()
        try:
            self.phase("unpacking")
            snapshot.unpack(folder, target, scratch / "extra")
            self._drill_files(target, scratch)
            config = json.loads(
                self.drill_compose(target, scratch, "config", "--format", "json").stdout
            )
            unsafe = self.drill_guard(config, target)
            if unsafe:
                raise OperationError("the drill would not be isolated: " + "; ".join(unsafe))
            services = [s for s in sorted(config.get("services") or {})
                        if s not in DRILL_SKIPPED_SERVICES]  # fmt: skip
            dump = scratch / "extra" / "extra" / DUMP
            if historian and HISTCRAFT_DB in services:
                self.phase("rebuilding the Historian database in the drill")
                self.historian.rebuild(historian, self.histcraft_image(config),
                                       target / "data" / HISTCRAFT_DB)  # fmt: skip
            elif dump.is_file() and HISTCRAFT_DB in services:
                self.phase("restoring the Historian database in the drill")
                self.drill_compose(
                    target, scratch, "up", "-d", "--wait", "--wait-timeout",
                    str(self.wait_seconds), HISTCRAFT_DB, timeout=self.wait_seconds + 120,
                )  # fmt: skip
                self.drill_compose(
                    target, scratch, "exec", "-T", HISTCRAFT_DB, "pg_restore", "-U", "histcraft",
                    "-d", "histcraft", "--clean", "--if-exists", "--no-owner",
                    "--exit-on-error", timeout=7200, stdin=dump,
                )  # fmt: skip
            self.phase("starting the copy")
            self.drill_compose(
                target, scratch, "up", "-d", "--no-deps", "--wait", "--wait-timeout",
                str(self.wait_seconds), *services, timeout=self.wait_seconds + 120,
            )  # fmt: skip
            if historian and HISTCRAFT_DB in services:
                problems += self.drill_tables(target, scratch, historian.get("tables") or [])
        except (OSError, ValueError, InstallError, snapshot.SnapshotError,
                HistorianBackupError) as exc:  # fmt: skip
            problems.append(str(exc)[-800:])
        except OperationError as exc:
            problems.append(str(exc))
        finally:
            self.phase("removing the copy")
            if target.is_dir():
                self.drill_compose(target, scratch, "down", "-v", "--remove-orphans",
                                   timeout=600, check=False)  # fmt: skip
        if not problems:
            for relative, entry in sorted((manifest.get("files") or {}).items()):
                if entry.get("kind") == "sqlite":
                    try:
                        snapshot.sqlite_check(target / relative)
                    except snapshot.SnapshotError as exc:
                        problems.append(f"after start, {exc}")
        shutil.rmtree(scratch, ignore_errors=True)
        result = {
            "state": "failed" if problems else "ok",
            "at": self.clock().isoformat(),
            "seconds": round(time.monotonic() - started, 1),
            "problems": problems,
        }
        self._status(folder, drill=result)
        self._write_json(self.state / "status" / "drill.json", {"name": name, **result})
        if problems:
            raise OperationError(f"the restore drill of {name} failed: {problems[0]}")
        return {"state": "ok", "name": name, "seconds": result["seconds"]}

    def drill_tables(self, target: Path, scratch: Path, tables: list[str]) -> list[str]:
        """Every table the Historian database had at the backup is there and reads."""

        reads = "; ".join(f"SELECT 1 FROM {_quoted(name)} LIMIT 1" for name in tables)
        query = "SELECT string_agg(schemaname || '.' || relname, ',') FROM pg_stat_user_tables"
        listed = self.drill_compose(
            target, scratch, "exec", "-T", HISTCRAFT_DB, "psql", "-X", "-U", "histcraft",
            "-d", "histcraft", "--no-password", "-v", "ON_ERROR_STOP=1", "-tA", "-c", query,
            *(["-c", reads] if reads else []), timeout=1800, check=False,
        )  # fmt: skip
        if listed.returncode != 0:
            return [f"the Historian database of the copy cannot be read: {listed.stderr[-400:]}"]
        lines = str(listed.stdout or "").strip().splitlines()
        found = set((lines[0] if lines else "").split(","))
        missing = sorted(set(tables) - found)
        if missing:
            return [f"the Historian database of the copy lacks {', '.join(missing[:5])}"]
        return []

    # Health and updates ------------------------------------------------------------------

    def health(self) -> list[str]:
        """What keeps the installation from being right: every service of its profiles running,
        healthy, and on the image its settings name (after an update: the new version)."""

        config = json.loads(self.compose("config", "--format", "json").stdout or "{}")
        services = config.get("services") or {}
        containers = json_lines(self.compose("ps", "-a", "--format", "json", check=False).stdout)
        by_service = {c.get("Service"): c for c in containers}
        problems = []
        for name, service in sorted(services.items()):
            container = by_service.get(name)
            if not container:
                problems.append(f"{name}: no container")
                continue
            state, health = container.get("State", ""), container.get("Health", "")
            if state != "running":
                problems.append(f"{name}: {state or 'not running'}")
            elif health not in {"healthy", ""}:
                problems.append(f"{name}: {health}")
            wanted = self.docker.image_id(str(service.get("image", "")))
            found = self.docker.run(
                "inspect", "--format", "{{.Image}}", str(container.get("ID", "")), check=False
            ).stdout.strip()  # fmt: skip
            if wanted and found and found != wanted:
                problems.append(f"{name}: runs another image than {service.get('image')}")
        return problems

    def note_update(self, **fields: Any) -> dict[str, Any]:
        """``install.sh`` records an update (done, refused, returned) in the operations history
        and in ``status/update.json``, which PlantCraft shows on the Updates page."""

        moment = self.clock().isoformat()
        record = {key: value for key, value in fields.items() if value not in (None, "")}
        record["state"] = record.get("state") or "ok"
        self._write_json(self.state / "status" / "update.json", {**record, "at": moment})
        self.operation = {"action": "update", "started_at": record.pop("started_at", moment)}
        return self.finish(record)

    # Restore -------------------------------------------------------------------------------

    def start_suite(self) -> None:
        # The proxy reads certs/ when it starts: recreate it (as install.sh does).
        self.compose("rm", "-s", "-f", "proxy", check=False)
        self.compose(
            "up", "-d", "--remove-orphans", "--wait", "--wait-timeout", str(self.wait_seconds),
            timeout=self.wait_seconds + 120,
        )  # fmt: skip

    def restore_histcraft(self, dump: Path) -> None:
        self.compose(
            "up", "-d", "--wait", "--wait-timeout", str(self.wait_seconds), HISTCRAFT_DB,
            timeout=self.wait_seconds + 120,
        )  # fmt: skip
        self.compose(
            "exec", "-T", HISTCRAFT_DB, "pg_restore", "-U", "histcraft", "-d", "histcraft",
            "--clean", "--if-exists", "--no-owner", "--exit-on-error", timeout=7200, stdin=dump,
        )  # fmt: skip

    def restore(self, name: str) -> dict[str, Any]:
        folder = self._folder(name)
        moment = self.clock()
        self.operation = {"action": "restore", "name": name, "started_at": moment.isoformat()}
        self.phase("verifying")
        problems = snapshot.verify(folder)
        manifest = snapshot.read_manifest(folder) if not problems else {}
        historian = manifest.get("histcraft_db")
        if historian:
            try:
                problems = self.historian.verify(historian, self.histcraft_image())
            except (InstallError, HistorianBackupError, ValueError) as exc:
                problems = [str(exc)]
        if problems:
            raise OperationError(f"{name} did not pass its check, nothing changed: {problems[0]}")
        current_images = self.images()
        aside = self.backups / f"{stamp(moment)}-before-restore"
        self.phase("stopping the suite", aside=aside.name, images=current_images)
        self.compose("down", "--remove-orphans", timeout=600)
        try:
            self.phase("restoring files")
            snapshot.restore(folder, self.install, aside)
            self._status(aside, state="aside", restored_from=name)
            # A backup from a bigger machine asks for more CPUs than this one has.
            cpus = host_cpus()
            for key, value in fit_cpu_limits(self.install, cpus).items():
                self.log(f"{key}={value} is more than the {cpus} CPUs of this host: using {cpus}")
            missing = self.retag(manifest.get("images") or [])
            if missing:
                raise OperationError(f"images no longer on this host: {', '.join(missing)}")
            dump = aside / "extra-restore" / "extra" / DUMP
            if historian:
                self.phase("rebuilding the Historian database")
                self.historian.rebuild(historian, self.histcraft_image(),
                                       self.install / "data" / HISTCRAFT_DB)  # fmt: skip
            elif dump.is_file():
                self.phase("restoring the Historian database")
                self.restore_histcraft(dump)
            self.phase("starting the suite")
            self.start_suite()
        except (OSError, ValueError, InstallError, snapshot.SnapshotError, HistorianBackupError,
                OperationError) as exc:  # fmt: skip
            reason = str(exc)[-800:]
            self.log(f"restore failed: {reason}; returning to the state before it")
            try:
                self.undo_restore(aside, current_images)
            except (OSError, InstallError, snapshot.SnapshotError) as again:
                raise OperationError(
                    f"the restore of {name} failed ({reason}) and the return to the state before "
                    f"it failed too ({str(again)[-400:]}): the files before the restore are in "
                    f"backups/{aside.name}. Run install.sh --rollback or ask for help."
                ) from again
            raise OperationError(
                f"the restore of {name} failed and the suite returned to its state before it: "
                f"{reason}"
            ) from exc
        return {"state": "ok", "name": name, "aside": aside.name}

    def undo_restore(self, aside: Path, images: list[dict[str, str]]) -> None:
        self.phase("returning to the state before the restore")
        self.compose("down", "--remove-orphans", timeout=600, check=False)
        if aside.is_dir():
            snapshot.put_back(self.install, aside)
            self._status(aside, state="returned")
        self.retag(images)
        self.start_suite()

    def resume(self) -> dict[str, Any] | None:
        """A driver that stopped mid-way: finish what is safe, undo the rest (the journal)."""

        try:
            journal = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        self.operation = journal
        self.request_id = journal.get("request_id")
        action, phase = journal.get("action"), journal.get("phase")
        if action == "restore" and phase not in {"verifying", None}:
            aside = self.backups / str(journal.get("aside", ""))
            try:
                self.undo_restore(aside, journal.get("images") or [])
            except (OSError, InstallError, snapshot.SnapshotError) as exc:
                return self.finish({"state": "failed", "message": f"interrupted restore: {exc}"})
            return self.finish({"state": "failed",
                                "message": "the restore was interrupted; the suite returned to "
                                           "its state before it"})  # fmt: skip
        if action == "drill":
            self.docker.run("compose", "--project-name", DRILL_PROJECT, "down", "-v",
                            "--remove-orphans", check=False, env=clean_env())  # fmt: skip
            self.docker.run("rm", "-f", historian_backup.TOOL, check=False)
            for scratch in self.backups.glob(".drill-*"):
                shutil.rmtree(scratch, ignore_errors=True)
        if action == "backup" and journal.get("name"):
            self.historian.discard()
            shutil.rmtree(self.backups / journal["name"], ignore_errors=True)
            shutil.rmtree(self.state / "work" / f"ops-{journal['name']}", ignore_errors=True)
        return self.finish({"state": "failed", "message": f"the {action} was interrupted"})

    def run(self, action: str, *, request_id: str | None = None, **params: Any) -> dict[str, Any]:
        """One operation, start to end, with its journal, history and request outcome."""

        self.request_id = request_id
        if self.journal.exists():
            self.resume()
            self.request_id = request_id
        try:
            if action == "backup":
                outcome = self.backup(params.get("reason") or "manual")
                if params.get("reason") == "daily":
                    outcome["removed"] = self.prune()["removed"]
            elif action == "verify":
                outcome = self.verify(str(params.get("name", "")))
            elif action == "restore":
                outcome = self.restore(str(params.get("name", "")))
            elif action == "drill":
                outcome = self.drill(params.get("name") or None)
            elif action == "prune":
                self.operation = {"action": "prune", "started_at": self.clock().isoformat()}
                outcome = self.prune()
            else:
                raise OperationError(f"unknown operation {action!r}")
        except OperationError as exc:
            self.operation.setdefault("action", action)
            return self.finish({"state": "failed", "message": str(exc)})
        self.operation.setdefault("action", action)
        self.operation["request_id"] = request_id
        return self.finish(outcome)


def _quoted(name: str) -> str:
    """``schema.table`` as SQL identifiers."""

    return ".".join('"' + part.replace('"', '""') + '"' for part in name.split(".", 1))


def older(version: Any, than: str) -> bool:
    """``version`` is a valid version below ``than`` (a rollback goes to an older version)."""

    from plantcraft.apps.release import ReleaseError, version_key

    try:
        return version_key(str(version)) < version_key(than)
    except ReleaseError:
        return False


# The installer's side ----------------------------------------------------------------------


def driver_command(
    install_dir: Path, image: str, args: list[str], *, detach: bool, project: str
) -> list[str]:
    """``docker run`` of the driver: root, no network, the install folder and the socket."""

    return [
        "run", "--rm", *(["-d"] if detach else []), "--name", DRIVER,
        "--network", "none", "--user", "0:0", "--pull", "never", "--read-only",
        "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE",
        "--cap-add", "FOWNER", "--cap-add", "FSETID",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:size=256m,mode=1777,noexec,nosuid,nodev",
        "--label", "org.processcraft.ops=driver",
        "-e", f"PLANTCRAFT_INSTALL_DIR={install_dir}",
        "-e", f"COMPOSE_PROJECT_NAME={project}",
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{install_dir}:{install_dir}",
        # The old name answers on every version's image (plantcraft/legacy.py from 0.5.1 on),
        # and the image may be older than this code (a rollback).
        "--entrypoint", "python", image, "-m", "processcraft.apps.operations", *args,
    ]  # fmt: skip


def driver_running(docker: Docker) -> bool:
    result = docker.run("ps", "-q", "--filter", f"name=^{DRIVER}$", check=False)
    return bool(result.stdout.strip())


def launch(
    docker: Docker, install_dir: Path, image: str, action: str, *, project: str,
    request_id: str | None = None, **params: str,
) -> None:  # fmt: skip
    """Start the driver in the background (the installer service); raises when one runs."""

    if driver_running(docker):
        raise InstallError("another operation is running; try again when it ends")
    args = ["drive", action]
    if request_id:
        args += ["--request-id", request_id]
    for key, value in params.items():
        args += [f"--{key}", value]
    docker.run(*driver_command(install_dir, image, args, detach=True, project=project))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m plantcraft.apps.operations")
    commands = parser.add_subparsers(dest="command", required=True)
    drive = commands.add_parser("drive", help="run one operation (inside the driver container)")
    drive.add_argument("action", choices=ACTIONS)
    drive.add_argument("--request-id")
    drive.add_argument("--reason")
    drive.add_argument("--name")
    commands.add_parser("resume", help="finish or undo an interrupted operation")
    commands.add_parser("list", help="the backups (JSON)")
    latest = commands.add_parser("latest", help="the name of the newest good backup")
    latest.add_argument("--reason")
    latest.add_argument("--before", help="only a backup of a version older than this one")
    commands.add_parser("health", help="every service running, healthy, on its image (JSON)")
    noted = commands.add_parser("note-update", help="record an update (install.sh)")
    for key in ("from", "to", "state", "message", "backup", "started-at"):
        noted.add_argument(f"--{key}", dest=key.replace("-", "_"))
    args = parser.parse_args(argv)
    install_dir = os.environ.get("PLANTCRAFT_INSTALL_DIR", "").strip()
    if not install_dir or not os.path.isabs(install_dir):
        print("PLANTCRAFT_INSTALL_DIR must be the absolute install folder", file=sys.stderr)
        return 2
    driver = Driver(install_dir, project=os.environ.get("COMPOSE_PROJECT_NAME") or "processcraft")
    if args.command == "list":
        print(json.dumps(driver.index(), indent=2))
        return 0
    if args.command == "latest":
        good = [b for b in driver.list_backups() if b.get("state") == "ok"
                and (not args.reason or b.get("reason") == args.reason)
                and (not args.before or older(b.get("suite_version"), args.before))]  # fmt: skip
        print(good[0]["name"] if good else "")
        return 0 if good else 1
    if args.command == "health":
        problems = driver.health()
        print(json.dumps({"state": "failed" if problems else "ok", "problems": problems},
                         indent=2))  # fmt: skip
        return 1 if problems else 0
    if args.command == "note-update":
        fields = {key: getattr(args, key) for key in
                  ("from", "to", "state", "message", "backup", "started_at")}  # fmt: skip
        print(json.dumps(driver.note_update(**fields), indent=2))
        return 0
    if args.command == "resume":
        outcome = driver.resume() or {"state": "ok", "message": "nothing to resume"}
    else:
        params = {key: getattr(args, key) for key in ("reason", "name") if getattr(args, key)}
        started = time.monotonic()
        outcome = driver.run(args.action, request_id=args.request_id, **params)
        outcome.setdefault("seconds", round(time.monotonic() - started, 1))
    print(json.dumps(outcome, indent=2))
    return 0 if outcome.get("state") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
