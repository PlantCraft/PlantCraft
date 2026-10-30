"""HistCraft's PostgreSQL in a backup: full and incremental base backups (docs/operations.md).

PostgreSQL 17 backs itself up by blocks: ``pg_basebackup`` takes a **full** copy of the
database files with the WAL that makes them consistent, and an **incremental** one
(``--incremental``) holds only the blocks changed since the backup it names, which the
server knows from its WAL summaries (``summarize_wal = on``). ``pg_combinebackup`` joins a
full backup and the incrementals after it into one database folder; ``pg_verifybackup``
checks every file against the backup's manifest (SHA-256). The tools are in the
``histcraft-db`` image already: nothing is added to the bundle and nothing goes out.

Where each part runs:

- ``pg_basebackup`` inside the running ``histcraft-db`` (``docker compose exec``, as its own
  user, over its local socket), into ``data/histcraft-db/.ops-staging/<name>``, which the
  driver then moves to ``backups/<name>/histcraft-db/``;
- ``pg_verifybackup`` and ``pg_combinebackup`` in a throwaway container of the same image
  (``processcraft-ops-pg``): no network, read-only, HistCraft's uid, the backups mounted
  read-only.

A **chain** is a full backup and the incrementals after it, each naming the one before
(``base``). It belongs to one **lineage** of the database, a random id kept in
``data/histcraft-db/backup-lineage``. A restore starts the database from a combined copy on a
new timeline, in a fresh ``data/histcraft-db`` without that file: the next backup is full
again. An incremental taken against a backup of another history would hold wrong blocks
without an error, so both checks guard it (PostgreSQL's own, by timeline, and ours, by lineage).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the driver imports this module
    from plantcraft.apps.operations import Driver

SERVICE = "histcraft-db"
FOLDER = "histcraft-db"  # in each backup folder
UID = 10008  # HistCraft's uid (docs/suite.md)
MOUNT = "/var/lib/postgresql/data"  # data/histcraft-db inside the container
PGDATA = "pgdata"
STAGING = ".ops-staging"
LINEAGE = "backup-lineage"
TOOL = "processcraft-ops-pg"
# A chain is at most a full backup and six incrementals: with daily backups, one full a week.
MAX_CHAIN = 7
TIMEOUT = 6 * 3600


class HistorianBackupError(Exception):
    """The Historian's database could not be backed up, checked or rebuilt."""


def _own(path: Path) -> None:
    """HistCraft's uid owns what its database and tools read or write (the driver is root)."""

    if os.geteuid() == 0:
        os.chown(path, UID, UID)


def tree_size(folder: Path) -> int:
    total = 0
    for directory, _, names in os.walk(folder):
        for name in names:
            path = Path(directory) / name
            if not path.is_symlink():
                total += path.stat().st_size
    return total


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class HistorianBackup:
    """The Historian database's part of the driver's backup, check, restore and drill."""

    def __init__(self, driver: Driver):
        self.driver = driver

    @property
    def data(self) -> Path:
        return self.driver.install / "data" / SERVICE

    # The running database --------------------------------------------------------------

    def running(self) -> bool:
        return self.driver.running(SERVICE)

    def sql(self, query: str) -> str:
        result = self.driver.compose(
            "exec", "-T", SERVICE, "psql", "-X", "-U", "histcraft", "-d", "histcraft",
            "--no-password", "-tA", "-c", query, timeout=300,
        )  # fmt: skip
        return str(result.stdout or "").strip()

    def facts(self) -> dict[str, Any]:
        """What the server says about itself: version, system id, size, WAL summaries, tables."""

        line = self.sql(
            "SELECT current_setting('server_version_num'), "
            "(SELECT system_identifier FROM pg_control_system()), "
            "(SELECT sum(pg_database_size(oid)) FROM pg_database), "
            "current_setting('summarize_wal')"
        )
        try:
            version, system, size, summaries = line.split("|")
            facts: dict[str, Any] = {
                "pg_version": int(version) // 10000,
                "system_identifier": system,
                "database_bytes": int(size),
                "summaries": summaries == "on",
            }
        except ValueError as exc:
            raise HistorianBackupError(f"the Historian database did not answer: {line!r}") from exc
        tables = self.sql(
            "SELECT string_agg(schemaname || '.' || relname, ',' ORDER BY schemaname, relname) "
            "FROM pg_stat_user_tables"
        )
        facts["tables"] = [name for name in tables.split(",") if name]
        return facts

    def lineage(self, *, create: bool) -> str | None:
        path = self.data / LINEAGE
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value or not create:
            return value or None
        value = uuid.uuid4().hex
        path.write_text(value + "\n", encoding="utf-8")
        path.chmod(0o644)
        return value

    # Backup ----------------------------------------------------------------------------

    def plan(self, backups: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
        """Full or incremental, and on which backup (``None``: no Historian database runs)."""

        if not self.running():
            return None
        facts = self.facts()
        lineage = self.lineage(create=False)
        base, why = None, "first backup of this database"
        if not facts["summaries"]:
            why = "WAL summaries are off (summarize_wal): restart the Historian database"
        elif lineage:
            why = "no good backup of this database to build on"
            backups = list(backups)
            good = {b["name"] for b in backups if b.get("state") == "ok"}
            for backup in backups:
                info = backup.get("histcraft_db") or {}
                if backup.get("state") != "ok" or not info:
                    continue
                chain = info.get("chain") or []
                if (
                    info.get("lineage") != lineage
                    or info.get("pg_version") != facts["pg_version"]
                    or info.get("system_identifier") != facts["system_identifier"]
                ):
                    continue
                if len(chain) >= MAX_CHAIN:
                    why = f"the chain reached {MAX_CHAIN} backups"
                    break
                if not set(chain) <= good or not self.intact(chain):
                    continue
                base, why = backup["name"], ""
                break
        return {**facts, "lineage": lineage, "base": base, "why_full": why}

    def intact(self, chain: list[str]) -> bool:
        """Every backup of the chain is there with the manifest it was taken with."""

        for name in chain:
            manifest = self.chain_folder(name) / "backup_manifest"
            info = self.read_info(name) or {}
            if not manifest.is_file() or file_sha256(manifest) != info.get("manifest_sha256"):
                return False
        return True

    def needed_bytes(self, plan: dict[str, Any], backups: list[dict[str, Any]]) -> int:
        size = int(plan.get("database_bytes") or 0)
        if not plan.get("base"):
            return int(size * 1.1)
        last = next((b.get("histcraft_db") or {} for b in backups if b.get("histcraft_db")), {})
        return max(2 * int(last.get("size") or 0), size // 20)

    def staging(self) -> Path:
        return self.data / STAGING

    def chain_folder(self, name: str) -> Path:
        return self.driver.backups / name / FOLDER

    def take(self, name: str, plan: dict[str, Any]) -> dict[str, Any]:
        """Back the running database up into the staging folder; returns what the manifest says.

        An incremental the server refuses (summaries gone, another timeline) becomes a full one.
        """

        stage = self.staging()
        shutil.rmtree(stage, ignore_errors=True)  # one operation at a time: leftovers only
        stage.mkdir(mode=0o700, parents=True)
        _own(stage)
        base = plan.get("base")
        if base:
            prior = stage / f"{name}.base-manifest"
            shutil.copyfile(self.chain_folder(base) / "backup_manifest", prior)
            _own(prior)
            result = self._basebackup(name, f"{MOUNT}/{STAGING}/{prior.name}")
            prior.unlink(missing_ok=True)
            if result.returncode != 0:
                refused = str(result.stderr or "").strip().splitlines()[-1:] or ["no reason"]
                self.driver.log(f"incremental backup refused ({refused[0]}); taking a full one")
                shutil.rmtree(stage / name, ignore_errors=True)
                base, plan = None, {**plan, "why_full": f"incremental refused: {refused[0]}"}
        if not base:
            result = self._basebackup(name, None)
            if result.returncode != 0:
                error = str(result.stderr or "").strip()[-600:]
                raise HistorianBackupError(
                    f"pg_basebackup of the Historian database failed: {error}"
                )
        taken = stage / name
        if not (taken / "backup_manifest").is_file():
            raise HistorianBackupError("pg_basebackup wrote no backup_manifest")
        lineage = plan.get("lineage") if base else self.lineage(create=True)
        parent = (self.read_info(base) or {}) if base else {}
        info = {
            "format": "pg_basebackup",
            "kind": "incremental" if base else "full",
            "base": base,
            "chain": [*(parent.get("chain") or []), name] if base else [name],
            "lineage": lineage,
            "pg_version": plan["pg_version"],
            "system_identifier": plan["system_identifier"],
            "database_bytes": plan["database_bytes"],
            "tables": plan["tables"],
            "size": tree_size(taken),
            "manifest_sha256": file_sha256(taken / "backup_manifest"),
        }
        if not base:
            info["why_full"] = plan.get("why_full") or ""
        return info

    def _basebackup(self, name: str, base_manifest: str | None) -> Any:
        return self.driver.compose(
            "exec", "-T", SERVICE, "pg_basebackup", "-U", "histcraft", "--no-password",
            "-D", f"{MOUNT}/{STAGING}/{name}", "-X", "stream", "-c", "fast",
            "--manifest-checksums=SHA256",
            *([f"--incremental={base_manifest}"] if base_manifest else []),
            timeout=TIMEOUT, check=False,
        )  # fmt: skip

    def place(self, name: str, folder: Path) -> None:
        """The staged backup moves into its backup folder (a rename on the same disk)."""

        shutil.move(str(self.staging() / name), str(folder / FOLDER))
        shutil.rmtree(self.staging(), ignore_errors=True)

    def discard(self) -> None:
        shutil.rmtree(self.staging(), ignore_errors=True)
        self.driver.docker.run("rm", "-f", TOOL, check=False)

    def read_info(self, name: str) -> dict[str, Any] | None:
        from plantcraft.ops import snapshot

        try:
            return snapshot.read_manifest(self.driver.backups / name).get("histcraft_db")
        except snapshot.SnapshotError:
            return None

    # Check -----------------------------------------------------------------------------

    def tool(self, image: str, mounts: list[tuple[Path, str, bool]], *args: str) -> Any:
        """A PostgreSQL tool in a throwaway container of the database's image (no network)."""

        volumes = []
        for source, target, writable in mounts:
            volumes += ["-v", f"{source}:{target}{'' if writable else ':ro'}"]
        return self.driver.docker.run(
            "run", "--rm", "--name", TOOL, "--network", "none", "--user", f"{UID}:{UID}",
            "--pull", "never", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--tmpfs", "/tmp:size=64m,mode=1777,noexec,nosuid,nodev",
            "--label", "org.processcraft.ops=tool", *volumes, "--entrypoint", args[0], image,
            *args[1:], timeout=TIMEOUT, check=False,
        )  # fmt: skip

    def verify(self, info: dict[str, Any], image: str, *, deep: bool = False) -> list[str]:
        """Every problem of the backup's chain (none: it can be rebuilt).

        The backup itself is read in full (every file's SHA-256 and its WAL); the ones it builds
        on were read in full when they were taken, so here each must be present with every file
        at its size, and their manifests unchanged. ``deep`` reads the whole chain in full.
        """

        chain = [str(name) for name in info.get("chain") or []]
        if not chain:
            return ["the Historian backup names no chain"]
        problems = []
        for position, name in enumerate(chain):
            folder = self.chain_folder(name)
            here = info if position == len(chain) - 1 else (self.read_info(name) or {})
            if not (folder / "backup_manifest").is_file():
                problems.append(f"the Historian backup {name}, which this one builds on, is gone")
                continue
            if file_sha256(folder / "backup_manifest") != here.get("manifest_sha256"):
                problems.append(f"the Historian backup {name}: its manifest was changed")
                continue
            quick = not deep and position < len(chain) - 1
            result = self.tool(
                image, [(folder, "/backup", False)], "pg_verifybackup",
                *(["--skip-checksums", "--no-parse-wal"] if quick else []), "/backup",
            )  # fmt: skip
            if result.returncode != 0:
                detail = str(result.stderr or result.stdout or "").strip()[-400:]
                problems.append(
                    f"the Historian backup {name} did not pass pg_verifybackup: {detail}"
                )
        return problems

    # Rebuild ---------------------------------------------------------------------------

    def rebuild(self, info: dict[str, Any], image: str, target: Path) -> None:
        """The chain joined into ``target/pgdata`` (``target`` is an empty ``data/histcraft-db``),
        checked, and set to start on a new timeline (``recovery.signal``)."""

        chain = [str(name) for name in info.get("chain") or []]
        if not chain:
            raise HistorianBackupError("the Historian backup names no chain")
        if (target / PGDATA).exists():
            raise HistorianBackupError(f"{target / PGDATA} is not empty")
        target.mkdir(parents=True, exist_ok=True)
        _own(target)
        mounts = [(self.chain_folder(name), f"/chain/{i}", False) for i, name in enumerate(chain)]
        joined = self.tool(
            image, [*mounts, (target, "/target", True)], "pg_combinebackup",
            *(f"/chain/{i}" for i in range(len(chain))), "-o", f"/target/{PGDATA}",
        )  # fmt: skip
        if joined.returncode != 0:
            detail = str(joined.stderr or "").strip()[-600:]
            raise HistorianBackupError(f"pg_combinebackup could not rebuild the database: {detail}")
        checked = self.tool(image, [(target, "/target", False)], "pg_verifybackup",
                            f"/target/{PGDATA}")  # fmt: skip
        if checked.returncode != 0:
            detail = str(checked.stderr or checked.stdout or "").strip()[-600:]
            raise HistorianBackupError(
                f"the rebuilt database did not pass pg_verifybackup: {detail}"
            )
        # The copy's own manifest is not PostgreSQL's file; recovery.signal ends the recovery on a
        # new timeline, so no incremental of the old history is ever taken against it.
        (target / PGDATA / "backup_manifest").unlink(missing_ok=True)
        signal = target / PGDATA / "recovery.signal"
        signal.touch()
        _own(signal)
        (target / PGDATA).chmod(0o700)
