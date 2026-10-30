"""Compute workers: the suite's pool of machines that run the apps' code (docs/compute.md).

An app (Analytics, Models) never runs the code people write in its own container: it reads the
data it needs with its own token, packs a **task** (a folder of files, as a tar archive) and
hands it to PlantCraft. **Workers**, on this machine or on others of the internal network, ask
PlantCraft for tasks when they have room (they open no port), run them in the app's executor
(no network, no secret) and send the answer back. The app reads the answer.

- **Workers** are registered by an administrator (Settings › Compute): a one-time code, then
  a credential of the worker's own, kept here only as a hash, that does one thing: take and
  answer tasks. A worker is paused (it ends what it runs and takes nothing more) or revoked.
- **Tasks** carry their app, the app's version (a worker runs only what its executor of the
  same version can), the **environment** it needs (an executor's image: ``standard``, the app's
  own, or one with more packages), a **size** (``small``, ``medium``, ``large``: the CPUs and
  memory the worker's machine must have), a priority (``interactive`` before ``run`` before ``backfill``) and
  labels a worker must have. Among apps of one priority, the one served longest ago goes
  first. A task's lease lasts ``LEASE_SECONDS``, renewed while the worker runs it; a worker
  that stops answering gives its tasks back to the queue, up to ``MAX_ATTEMPTS`` times.
- Bytes (what a task takes and gives) are files under ``<data>/compute/``; the rows are small.

Times are ``utc_iso`` text, so they sort and compare as text.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from plantcraft.db import Database, Migration, Store, add_columns
from plantcraft.i18n import t
from plantcraft_sdk.compute.folder import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_SIZE,
    SIZES,
    environment_name,
    executor_name,
    fits,
    largest_size,
    size_name,
)
from plantcraft_sdk.utc import utc_iso

PRIORITIES = {"interactive": 0, "run": 1, "backfill": 2}
STATUSES = ("queued", "running", "done", "failed", "cancelled")
FINISHED = ("done", "failed", "cancelled")
WORKER_STATES = ("pending", "active", "paused", "revoked")
LEASE_SECONDS = 30
HEARTBEAT_SECONDS = 10
# A worker not heard from for this long is offline (its tasks go back after their lease).
ONLINE_SECONDS = 60
# A task is given to a worker at most this many times (the first try and two more).
MAX_ATTEMPTS = 3
ENROLL_MINUTES = 15
DEFAULT_TIMEOUT_SECONDS = 300.0
MAX_TIMEOUT_SECONDS = 6 * 3600.0
DEFAULT_MEMORY_MB = 2048
MAX_MEMORY_MB = 64 * 1024
MAX_QUEUED_PER_APP = 20_000
# What a task takes or gives, at most (PLANTCRAFT_COMPUTE_MAX_MB changes it).
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
# Answers nobody collected are dropped after an hour; the rows (for the 24 h numbers) after 7 days.
KEEP_OUTPUT = timedelta(hours=1)
KEEP_ROWS = timedelta(days=7)
CREDENTIAL_PREFIX = "pcw_"
CODE_PREFIX = "pce_"


class ComputeError(ValueError):
    """A request about tasks or workers that cannot be done, with a sentence for a person."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def compute_max_bytes() -> int:
    """``PLANTCRAFT_COMPUTE_MAX_MB``: the most a task takes or gives (64 MB by default)."""

    configured = os.environ.get("PLANTCRAFT_COMPUTE_MAX_MB", "").strip()
    if configured.isdigit() and int(configured) > 0:
        return int(configured) * 1024 * 1024
    return DEFAULT_MAX_BYTES


def _now() -> datetime:
    return datetime.now(UTC)


def _text(moment: datetime) -> str:
    return utc_iso(moment)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def priority_name(value: int) -> str:
    return next((name for name, rank in PRIORITIES.items() if rank == value), "run")


class ComputeStore(Store):
    # Where a task may run (2026-10-26): the executor's environment and the machine's size.
    MIGRATIONS = (
        Migration(
            "placement",
            add_columns(
                "compute_tasks",
                {
                    "environment": f"TEXT NOT NULL DEFAULT '{DEFAULT_ENVIRONMENT}'",
                    "size": f"TEXT NOT NULL DEFAULT '{DEFAULT_SIZE}'",
                },
            ),
        ),
    )
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS compute_workers (
        worker_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        labels_json TEXT NOT NULL DEFAULT '[]',
        state TEXT NOT NULL,
        enroll_hash TEXT,
        enroll_expires_at TEXT,
        credential_hash TEXT,
        host TEXT NOT NULL DEFAULT '',
        executors_json TEXT NOT NULL DEFAULT '[]',
        stats_json TEXT NOT NULL DEFAULT '{}',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        enrolled_at TEXT,
        last_seen_at TEXT,
        revoked_at TEXT
    );

    CREATE UNIQUE INDEX IF NOT EXISTS idx_compute_workers_credential
        ON compute_workers(credential_hash);

    CREATE TABLE IF NOT EXISTS compute_tasks (
        task_id TEXT PRIMARY KEY,
        app_id TEXT NOT NULL,
        version TEXT,
        kind TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL,
        labels_json TEXT NOT NULL DEFAULT '[]',
        run_id TEXT,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        worker_id TEXT,
        lease_until TEXT,
        timeout_seconds REAL NOT NULL,
        memory_mb INTEGER NOT NULL,
        input_bytes INTEGER NOT NULL DEFAULT 0,
        output_bytes INTEGER,
        error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        seconds REAL,
        collected INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_compute_tasks_queue
        ON compute_tasks(status, priority, created_at);
    CREATE INDEX IF NOT EXISTS idx_compute_tasks_app ON compute_tasks(app_id, status);
    CREATE INDEX IF NOT EXISTS idx_compute_tasks_worker ON compute_tasks(worker_id, status);

    CREATE TABLE IF NOT EXISTS compute_turns (
        app_id TEXT PRIMARY KEY,
        served_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS compute_limits (
        app_id TEXT PRIMARY KEY,
        timeout_seconds REAL,
        memory_mb INTEGER,
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    );
    """

    def __init__(self, db: Database, folder: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES):
        super().__init__(db)
        self.folder = Path(folder)
        self.max_bytes = max_bytes

    # Workers ---------------------------------------------------------------------------------

    @staticmethod
    def _worker(row: Any, now: datetime | None = None) -> dict[str, Any]:
        item = dict(row)
        seen = item.get("last_seen_at")
        now = now or _now()
        online = bool(seen) and seen >= _text(now - timedelta(seconds=ONLINE_SECONDS))
        state = item["state"]
        if state == "pending" and (item.get("enroll_expires_at") or "") < _text(now):
            status = "expired"
        elif state in ("active", "paused"):
            status = state if online else "offline"
        else:
            status = state
        return {
            "id": item["worker_id"],
            "name": item["name"],
            "labels": Store._loads(item.get("labels_json"), []),
            "state": state,
            "status": status,
            "online": online and state in ("active", "paused"),
            "host": item.get("host") or "",
            "executors": Store._loads(item.get("executors_json"), []),
            "stats": Store._loads(item.get("stats_json"), {}),
            # The largest task it has room for: its machine, and its executors' own memory per
            # task (sizes, docs/compute.md).
            "largest_size": _largest(
                Store._loads(item.get("stats_json"), {}),
                Store._loads(item.get("executors_json"), []),
            ),
            "created_by": item.get("created_by") or "",
            "created_at": item["created_at"],
            "enrolled_at": item.get("enrolled_at"),
            "last_seen_at": seen,
            "enroll_expires_at": item.get("enroll_expires_at") if state == "pending" else None,
        }

    def create_worker(
        self, name: str, *, labels: Iterable[str] = (), actor: str
    ) -> tuple[dict[str, Any], str]:
        """A new worker waiting for its machine, and the one-time code that machine enrolls with."""

        name = " ".join(str(name or "").split())[:80]
        if not name:
            raise ComputeError(422, t("Give the worker a name."))
        clean = sorted({_label(item) for item in labels if _label(item)})
        code = CODE_PREFIX + secrets.token_urlsafe(18)
        worker_id = "w" + secrets.token_hex(5)
        now = _now()
        with self._lock, self._write() as connection:
            taken = connection.execute(
                "SELECT 1 FROM compute_workers WHERE name = ? AND state != 'revoked'", (name,)
            ).fetchone()
            if taken:
                raise ComputeError(409, t("A worker named {name} already exists.", name=name))
            connection.execute(
                """
                INSERT INTO compute_workers (worker_id, name, labels_json, state, enroll_hash,
                    enroll_expires_at, created_by, created_at)
                VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    worker_id,
                    name,
                    self._json(clean),
                    _hash(code),
                    _text(now + timedelta(minutes=ENROLL_MINUTES)),
                    actor,
                    _text(now),
                ),
            )
        return self.worker(worker_id) or {}, code

    def renew_code(self, worker_id: str) -> str:
        """A new one-time code for a worker that did not enroll yet (the old one stops working)."""

        code = CODE_PREFIX + secrets.token_urlsafe(18)
        expires = _text(_now() + timedelta(minutes=ENROLL_MINUTES))
        with self._lock, self._write() as connection:
            changed = connection.execute(
                """UPDATE compute_workers SET enroll_hash = ?, enroll_expires_at = ?
                   WHERE worker_id = ? AND state = 'pending'""",
                (_hash(code), expires, worker_id),
            ).rowcount
        if not changed:
            raise ComputeError(409, t("Only a worker that has not started yet gets a new code."))
        return code

    def enroll(self, code: str, *, host: str, executors: list[dict[str, Any]]) -> tuple[dict, str]:
        """The machine trades the one-time code for its credential (shown once, kept hashed)."""

        credential = CREDENTIAL_PREFIX + secrets.token_urlsafe(32)
        now = _now()
        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT * FROM compute_workers WHERE enroll_hash = ? AND state = 'pending'",
                (_hash(str(code or "")),),
            ).fetchone()
            if row is None or (row["enroll_expires_at"] or "") < _text(now):
                raise ComputeError(
                    401,
                    t(
                        "This code is not valid or has expired: an administrator creates a new "
                        "one in PlantCraft › Settings › Compute."
                    ),
                )
            connection.execute(
                """
                UPDATE compute_workers SET state = 'active', enroll_hash = NULL,
                    enroll_expires_at = NULL, credential_hash = ?, host = ?, executors_json = ?,
                    enrolled_at = ?, last_seen_at = ?
                WHERE worker_id = ?
                """,
                (
                    _hash(credential),
                    str(host or "")[:120],
                    self._json(_executors(executors)),
                    _text(now),
                    _text(now),
                    row["worker_id"],
                ),
            )
        return self.worker(row["worker_id"]) or {}, credential

    def ensure_local(self, credential: str, *, name: str = "local") -> dict[str, Any]:
        """The installation's own worker, enrolled with a credential the installer wrote."""

        hashed = _hash(credential)
        now = _text(_now())
        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT worker_id, state FROM compute_workers WHERE credential_hash = ?", (hashed,)
            ).fetchone()
            if row is None:
                worker_id = "w" + secrets.token_hex(5)
                taken = connection.execute(
                    "SELECT 1 FROM compute_workers WHERE name = ? AND state != 'revoked'", (name,)
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO compute_workers (worker_id, name, labels_json, state,
                        credential_hash, created_by, created_at, enrolled_at)
                    VALUES (?, ?, '[]', 'active', ?, 'install', ?, ?)
                    """,
                    (worker_id, f"{name}-{worker_id}" if taken else name, hashed, now, now),
                )
            else:
                worker_id = row["worker_id"]
        return self.worker(worker_id) or {}

    def authenticate(self, credential: str) -> dict[str, Any] | None:
        """The worker of this credential, unless it was revoked."""

        if not credential.startswith(CREDENTIAL_PREFIX):
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_workers WHERE credential_hash = ?", (_hash(credential),)
            ).fetchone()
        if row is None or row["state"] not in ("active", "paused"):
            return None
        return self._worker(row)

    def worker(self, worker_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_workers WHERE worker_id = ?", (worker_id,)
            ).fetchone()
        return None if row is None else self._worker(row)

    def workers(self) -> list[dict[str, Any]]:
        now = _now()
        since = _text(now - timedelta(hours=24))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM compute_workers ORDER BY state = 'revoked', name"
            ).fetchall()
            counts = connection.execute(
                """
                SELECT worker_id, status, COUNT(*) AS n FROM compute_tasks
                WHERE worker_id IS NOT NULL AND (status = 'running' OR finished_at >= ?)
                GROUP BY worker_id, status
                """,
                (since,),
            ).fetchall()
        by_worker: dict[str, dict[str, int]] = {}
        for row in counts:
            by_worker.setdefault(row["worker_id"], {})[row["status"]] = row["n"]
        found = []
        for row in rows:
            item = self._worker(row, now)
            numbers = by_worker.get(item["id"], {})
            item["running"] = numbers.get("running", 0)
            item["done_24h"] = numbers.get("done", 0)
            item["failed_24h"] = numbers.get("failed", 0)
            found.append(item)
        return found

    def set_state(self, worker_id: str, state: str) -> dict[str, Any]:
        """Pause, resume or revoke a worker; a revoked one gives its tasks back at once."""

        if state not in ("active", "paused", "revoked"):
            raise ComputeError(422, t("Unknown state {state}.", state=state))
        now = _text(_now())
        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT state FROM compute_workers WHERE worker_id = ?", (worker_id,)
            ).fetchone()
            if row is None:
                raise ComputeError(404, t("Worker not found."))
            if row["state"] == "revoked" or (row["state"] == "pending" and state != "revoked"):
                raise ComputeError(409, t("This worker cannot change to {state}.", state=state))
            connection.execute(
                """UPDATE compute_workers SET state = ?, revoked_at = ?,
                   credential_hash = CASE WHEN ? = 'revoked' THEN NULL ELSE credential_hash END,
                   enroll_hash = CASE WHEN ? = 'revoked' THEN NULL ELSE enroll_hash END
                   WHERE worker_id = ?""",
                (state, now if state == "revoked" else None, state, state, worker_id),
            )
            if state == "revoked":
                self._give_back(
                    connection, "worker_id = ?", (worker_id,), t("its worker was revoked")
                )
        return self.worker(worker_id) or {}

    def remove_worker(self, worker_id: str) -> bool:
        """Forget a revoked worker, or one that never started."""

        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT state FROM compute_workers WHERE worker_id = ?", (worker_id,)
            ).fetchone()
            if row is None:
                return False
            if row["state"] not in ("revoked", "pending"):
                raise ComputeError(409, t("Revoke the worker before removing it."))
            connection.execute("DELETE FROM compute_workers WHERE worker_id = ?", (worker_id,))
        return True

    def seen(
        self, worker_id: str, *, executors: list[dict[str, Any]] | None, stats: dict[str, Any]
    ) -> None:
        values: list[Any] = [_text(_now()), self._json(_stats(stats))]
        extra = ""
        if executors is not None:
            extra = ", executors_json = ?"
            values.append(self._json(_executors(executors)))
        with self._lock, self._write() as connection:
            connection.execute(
                f"UPDATE compute_workers SET last_seen_at = ?, stats_json = ?{extra} "  # noqa: S608
                "WHERE worker_id = ?",
                (*values, worker_id),
            )

    # Limits per app (Settings › Compute) -----------------------------------------------------

    def limits(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM compute_limits").fetchall()
        return {
            row["app_id"]: {
                "timeout_seconds": row["timeout_seconds"],
                "memory_mb": row["memory_mb"],
                "updated_by": row["updated_by"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }

    def set_limits(
        self, app_id: str, *, timeout_seconds: float | None, memory_mb: int | None, actor: str
    ) -> dict[str, Any]:
        if timeout_seconds is not None and not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ComputeError(422, t("The time limit is between 1 second and 6 hours."))
        if memory_mb is not None and not 64 <= memory_mb <= MAX_MEMORY_MB:
            raise ComputeError(422, t("The memory limit is between 64 MB and 64 GB."))
        with self._lock, self._write() as connection:
            if timeout_seconds is None and memory_mb is None:
                connection.execute("DELETE FROM compute_limits WHERE app_id = ?", (app_id,))
            else:
                connection.execute(
                    """
                    INSERT INTO compute_limits (app_id, timeout_seconds, memory_mb, updated_by,
                        updated_at) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (app_id) DO UPDATE SET timeout_seconds = excluded.timeout_seconds,
                        memory_mb = excluded.memory_mb, updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (app_id, timeout_seconds, memory_mb, actor, _text(_now())),
                )
        return self.limits().get(app_id, {"timeout_seconds": None, "memory_mb": None})

    # Tasks: the app's side ------------------------------------------------------------------

    def _blob(self, task_id: str, name: str) -> Path:
        return self.folder / task_id / name

    def blob_path(self, task_id: str, name: str) -> Path | None:
        path = self._blob(task_id, name)
        return path if path.is_file() else None

    def new_task_id(self) -> str:
        return secrets.token_hex(12)

    def submit(
        self,
        task_id: str,
        *,
        app_id: str,
        version: str | None,
        kind: str,
        priority: str,
        labels: Iterable[str],
        run_id: str | None,
        timeout_seconds: float | None,
        memory_mb: int | None,
        input_bytes: int,
        environment: str | None = None,
        size: str | None = None,
    ) -> dict[str, Any]:
        """Queue a task whose input is already at ``blob_path(task_id, "input")``."""

        if priority not in PRIORITIES:
            raise ComputeError(422, t("priority is one of {names}.", names=", ".join(PRIORITIES)))
        environment = environment_name(environment)
        if not environment:
            raise ComputeError(
                422, t("An environment's name is letters, digits and dashes (40 at most).")
            )
        size = size_name(size)
        if not size:
            raise ComputeError(422, t("size is one of {names}.", names=", ".join(SIZES)))
        limit = self.limits().get(app_id, {})
        ceiling_time = float(limit.get("timeout_seconds") or MAX_TIMEOUT_SECONDS)
        ceiling_memory = int(limit.get("memory_mb") or MAX_MEMORY_MB)
        timeout = min(
            float(timeout_seconds or limit.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
            ceiling_time,
        )
        # A size asks for its memory at least, unless the app's limit is lower.
        asked = memory_mb or limit.get("memory_mb") or DEFAULT_MEMORY_MB
        memory = min(max(int(asked), SIZES[size]["memory_mb"]), ceiling_memory)
        with self._lock, self._write() as connection:
            queued = connection.execute(
                "SELECT COUNT(*) FROM compute_tasks WHERE app_id = ? AND status = 'queued'",
                (app_id,),
            ).fetchone()[0]
            if queued >= MAX_QUEUED_PER_APP:
                raise ComputeError(
                    429,
                    t("{count} tasks of this app are waiting already: try again later.",
                      count=queued),
                )  # fmt: skip
            connection.execute(
                """
                INSERT INTO compute_tasks (task_id, app_id, version, kind, priority, labels_json,
                    run_id, status, timeout_seconds, memory_mb, input_bytes, created_at,
                    environment, size)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    app_id,
                    version or None,
                    kind,
                    PRIORITIES[priority],
                    self._json(sorted({_label(item) for item in labels if _label(item)})),
                    run_id or None,
                    max(1.0, timeout),
                    max(64, memory),
                    input_bytes,
                    _text(_now()),
                    environment,
                    size,
                ),
            )
        return self.task(task_id) or {}

    @staticmethod
    def _task(row: Any) -> dict[str, Any]:
        item = dict(row)
        return {
            "id": item["task_id"],
            "app": item["app_id"],
            "version": item["version"],
            "kind": item["kind"],
            "environment": item.get("environment") or DEFAULT_ENVIRONMENT,
            "size": item.get("size") or DEFAULT_SIZE,
            "priority": priority_name(item["priority"]),
            "labels": Store._loads(item.get("labels_json"), []),
            "run": item["run_id"],
            "status": item["status"],
            "attempts": item["attempts"],
            "worker": item["worker_id"],
            "timeout_seconds": item["timeout_seconds"],
            "memory_mb": item["memory_mb"],
            "input_bytes": item["input_bytes"],
            "output_bytes": item["output_bytes"],
            "error": item["error"],
            "created_at": item["created_at"],
            "started_at": item["started_at"],
            "finished_at": item["finished_at"],
            "seconds": item["seconds"],
        }

    def task(self, task_id: str, *, app_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM compute_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None or (app_id is not None and row["app_id"] != app_id):
            return None
        return self._task(row)

    def tasks(self, ids: list[str], *, app_id: str) -> list[dict[str, Any]]:
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM compute_tasks WHERE app_id = ? AND task_id IN ({marks})",  # noqa: S608
                (app_id, *ids),
            ).fetchall()
        return [self._task(row) for row in rows]

    def cancel(self, task_id: str, *, app_id: str) -> dict[str, Any] | None:
        """Stop a task that waits or runs (the worker hears it at its next heartbeat)."""

        now = _text(_now())
        with self._lock, self._write() as connection:
            changed = connection.execute(
                """UPDATE compute_tasks SET status = 'cancelled', finished_at = ?, lease_until = NULL
                   WHERE task_id = ? AND app_id = ? AND status IN ('queued', 'running')""",
                (now, task_id, app_id),
            ).rowcount
        if changed:
            self._drop(task_id, "input")
        return self.task(task_id, app_id=app_id)

    def cancel_run(self, run_id: str, *, app_id: str) -> int:
        """Every task of an app's run that waits or runs (the run was cancelled)."""

        now = _text(_now())
        with self._lock, self._write() as connection:
            ids = [
                row[0]
                for row in connection.execute(
                    """SELECT task_id FROM compute_tasks WHERE app_id = ? AND run_id = ?
                       AND status IN ('queued', 'running')""",
                    (app_id, run_id),
                ).fetchall()
            ]
            connection.executemany(
                """UPDATE compute_tasks SET status = 'cancelled', finished_at = ?, lease_until = NULL
                   WHERE task_id = ?""",
                [(now, task_id) for task_id in ids],
            )
        for task_id in ids:
            self._drop(task_id, "input")
        return len(ids)

    def collected(self, task_id: str, *, app_id: str) -> bool:
        """The app has read the answer: its bytes go now (the row stays for the numbers)."""

        with self._lock, self._write() as connection:
            changed = connection.execute(
                "UPDATE compute_tasks SET collected = 1 WHERE task_id = ? AND app_id = ?",
                (task_id, app_id),
            ).rowcount
        if changed:
            shutil.rmtree(self.folder / task_id, ignore_errors=True)
        return bool(changed)

    def capacity(
        self,
        app_id: str,
        version: str | None = None,
        *,
        environment: str | None = None,
        size: str | None = None,
    ) -> dict[str, Any]:
        """How many workers online run this app (of this version, in this environment, with room
        for this size), how many tasks wait, and the environments and sizes the app has on
        offer (an app shows them where people say where their work runs)."""

        online = [item for item in self.workers() if item["online"] and item["state"] == "active"]
        environment = environment_name(environment) if environment else None
        size = size_name(size) if size else None

        def runs(executor: dict[str, Any]) -> bool:
            return (
                executor.get("app") == app_id
                and (version is None or executor.get("version") == version)
                and (
                    environment is None
                    or (executor.get("environment") or DEFAULT_ENVIRONMENT) == environment
                )
            )

        able = [
            item
            for item in online
            if any(
                runs(executor)
                and (size is None or fits(item["stats"], size, executor.get("memory_mb")))
                for executor in item["executors"]
            )
        ]
        offered = [
            (executor.get("environment") or DEFAULT_ENVIRONMENT, item, executor)
            for item in online
            for executor in item["executors"]
            if executor.get("app") == app_id
            and (version is None or executor.get("version") == version)
        ]
        with self._connect() as connection:
            row = connection.execute(
                """SELECT SUM(status = 'queued') AS queued, SUM(status = 'running') AS running,
                   MIN(CASE WHEN status = 'queued' THEN created_at END) AS oldest
                   FROM compute_tasks WHERE app_id = ? AND status IN ('queued', 'running')""",
                (app_id,),
            ).fetchone()
        return {
            "workers": len(able),
            "slots": sum(
                int(executor.get("slots") or 0)
                for item in able
                for executor in item["executors"]
                if runs(executor)
            ),
            "queued": int(row["queued"] or 0),
            "running": int(row["running"] or 0),
            "oldest_queued_at": row["oldest"],
            "environments": sorted({name for name, _item, _executor in offered}),
            "sizes": [
                name
                for name in SIZES
                if any(
                    fits(item["stats"], name, executor.get("memory_mb"))
                    for _env, item, executor in offered
                )
            ],
        }

    # Tasks: the worker's side ---------------------------------------------------------------

    def has_work(self, executors: Iterable[str]) -> bool:
        """A cheap look before a lease (no write): is anything queued for these executors' apps
        (their names, ``<app>`` or ``<app>.<environment>``)?"""

        names = sorted({str(name).partition(".")[0] for name in executors})
        if not names:
            return False
        marks = ",".join("?" for _ in names)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT 1 FROM compute_tasks WHERE status = 'queued' AND app_id IN ({marks}) "  # noqa: S608
                "LIMIT 1",
                names,
            ).fetchone()
        return row is not None

    def lease(self, worker: dict[str, Any], free: dict[str, int]) -> list[dict[str, Any]]:
        """Give the worker up to ``free[name]`` tasks per executor (``<app>`` or
        ``<app>.<environment>``, ``executor_name``).

        The order: priority, then the app served longest ago (each app gets its turn), then the
        oldest task. A task goes only to an executor of its app, version and environment, on a
        worker with its labels whose machine has room for its size.
        """

        if worker.get("state") != "active":
            return []
        versions = {
            executor_name(str(item.get("app")), item.get("environment")): item.get("version")
            for item in worker.get("executors") or []
            if item.get("app")
        }
        # The memory one task may use in each executor (its --memory-mb): a size above it
        # waits for another worker, whatever the machine has.
        limits = {
            executor_name(str(item.get("app")), item.get("environment")): item.get("memory_mb")
            for item in worker.get("executors") or []
            if item.get("app")
        }
        room = {name: max(0, int(count)) for name, count in free.items() if name in versions}
        room = {name: count for name, count in room.items() if count}
        if not room:
            return []
        labels = set(worker.get("labels") or [])
        stats = worker.get("stats") or {}
        apps = sorted({name.partition(".")[0] for name in room})
        now = _now()
        marks = ",".join("?" for _ in apps)
        given: list[str] = []
        with self._lock, self._write() as connection:
            rows = connection.execute(
                f"""SELECT task_id, app_id, version, priority, labels_json, created_at,
                    environment, size
                    FROM compute_tasks WHERE status = 'queued' AND app_id IN ({marks})
                    ORDER BY priority, created_at LIMIT 500""",  # noqa: S608
                apps,
            ).fetchall()
            turns = {
                row["app_id"]: row["served_at"]
                for row in connection.execute("SELECT * FROM compute_turns").fetchall()
            }

            def name_of(row: Any) -> str:
                return executor_name(row["app_id"], row["environment"])

            fit = [
                row
                for row in rows
                if name_of(row) in room
                and (row["version"] is None or row["version"] == versions.get(name_of(row)))
                and set(Store._loads(row["labels_json"], [])) <= labels
                and fits(stats, row["size"], limits.get(name_of(row)))
            ]
            while fit and any(room.values()):
                best = min(fit, key=lambda row: row["priority"])["priority"]
                same = [row for row in fit if row["priority"] == best and room.get(name_of(row))]
                if not same:
                    fit = [row for row in fit if row["priority"] != best]
                    continue
                app = min({row["app_id"] for row in same}, key=lambda name: turns.get(name, ""))
                chosen = next(row for row in same if row["app_id"] == app)
                fit.remove(chosen)
                room[name_of(chosen)] -= 1
                turns[app] = _text(now) + f"#{len(given):05d}"
                given.append(chosen["task_id"])
            if given:
                connection.executemany(
                    """UPDATE compute_tasks SET status = 'running', worker_id = ?,
                       lease_until = ?, attempts = attempts + 1, started_at = ?, error = ''
                       WHERE task_id = ? AND status = 'queued'""",
                    [
                        (
                            worker["id"],
                            _text(now + timedelta(seconds=LEASE_SECONDS)),
                            _text(now),
                            task_id,
                        )
                        for task_id in given
                    ],
                )
                connection.executemany(
                    """INSERT INTO compute_turns (app_id, served_at) VALUES (?, ?)
                       ON CONFLICT (app_id) DO UPDATE SET served_at = excluded.served_at""",
                    [
                        (app, served)
                        for app, served in turns.items()
                        if served.startswith(_text(now))
                    ],
                )
        return [task for task in (self.task(task_id) for task_id in given) if task]

    def heartbeat(self, worker_id: str, running: Iterable[str]) -> list[str]:
        """Renew the lease of the tasks the worker still runs; answer the ones it must stop."""

        ids = list(dict.fromkeys(str(item) for item in running))[:1000]
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        until = _text(_now() + timedelta(seconds=LEASE_SECONDS))
        with self._lock, self._write() as connection:
            connection.execute(
                f"""UPDATE compute_tasks SET lease_until = ?
                    WHERE worker_id = ? AND status = 'running' AND task_id IN ({marks})""",  # noqa: S608
                (until, worker_id, *ids),
            )
            kept = {
                row[0]
                for row in connection.execute(
                    f"""SELECT task_id FROM compute_tasks WHERE worker_id = ?
                        AND status = 'running' AND task_id IN ({marks})""",  # noqa: S608
                    (worker_id, *ids),
                ).fetchall()
            }
        return [task_id for task_id in ids if task_id not in kept]

    def owns(self, worker_id: str, task_id: str) -> dict[str, Any] | None:
        task = self.task(task_id)
        if task is None or task["worker"] != worker_id or task["status"] != "running":
            return None
        return task

    def finish(
        self,
        worker_id: str,
        task_id: str,
        *,
        status: str,
        seconds: float | None,
        error: str,
        output_bytes: int | None,
    ) -> dict[str, Any]:
        """The worker's answer. ``done``: the executor answered (its result is in the output);
        ``failed``: it could not (a timeout without an answer, an executor that died): the task
        goes back to the queue while it has tries left."""

        if status not in ("done", "failed"):
            raise ComputeError(422, t("status is done or failed."))
        now = _text(_now())
        with self._lock, self._write() as connection:
            row = connection.execute(
                "SELECT * FROM compute_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None or row["worker_id"] != worker_id or row["status"] != "running":
                raise ComputeError(409, t("This task is no longer this worker's."))
            if status == "done":
                connection.execute(
                    """UPDATE compute_tasks SET status = 'done', finished_at = ?, seconds = ?,
                       output_bytes = ?, lease_until = NULL WHERE task_id = ?""",
                    (now, seconds, output_bytes, task_id),
                )
            elif row["attempts"] >= MAX_ATTEMPTS:
                connection.execute(
                    """UPDATE compute_tasks SET status = 'failed', finished_at = ?, seconds = ?,
                       error = ?, lease_until = NULL WHERE task_id = ?""",
                    (now, seconds, _error(error), task_id),
                )
            else:
                connection.execute(
                    """UPDATE compute_tasks SET status = 'queued', worker_id = NULL,
                       lease_until = NULL, error = ? WHERE task_id = ?""",
                    (_error(error), task_id),
                )
        task = self.task(task_id) or {}
        if task.get("status") in FINISHED:
            self._drop(task_id, "input")
        return task

    # Upkeep (the leader process) ------------------------------------------------------------

    def _give_back(self, connection: Any, where: str, values: tuple[Any, ...], reason: str) -> int:
        now = _text(_now())
        failed = connection.execute(
            f"""UPDATE compute_tasks SET status = 'failed', finished_at = ?, lease_until = NULL,
                error = ? WHERE status = 'running' AND attempts >= ? AND {where}""",  # noqa: S608
            (now, _error(t("given to a worker {count} times; {reason}", count=MAX_ATTEMPTS,
                           reason=reason)), MAX_ATTEMPTS, *values),
        ).rowcount  # fmt: skip
        back = connection.execute(
            f"""UPDATE compute_tasks SET status = 'queued', worker_id = NULL, lease_until = NULL,
                error = ? WHERE status = 'running' AND {where}""",  # noqa: S608
            (_error(reason), *values),
        ).rowcount
        return failed + back

    def expire(self) -> int:
        """Tasks whose worker stopped renewing their lease go back to the queue (or fail)."""

        now = _text(_now())
        with self._lock, self._write() as connection:
            return self._give_back(
                connection, "lease_until < ?", (now,), t("its worker stopped answering")
            )

    def housekeeping(self) -> None:
        now = _now()
        old_output = _text(now - KEEP_OUTPUT)
        old_rows = _text(now - KEEP_ROWS)
        with self._lock, self._write() as connection:
            gone = [
                row[0]
                for row in connection.execute(
                    """SELECT task_id FROM compute_tasks WHERE status IN ('done', 'failed',
                       'cancelled') AND (collected = 1 OR finished_at < ?)""",
                    (old_output,),
                ).fetchall()
            ]
            connection.execute(
                "UPDATE compute_tasks SET collected = 1 WHERE finished_at < ? AND collected = 0",
                (old_output,),
            )
            connection.execute(
                "DELETE FROM compute_tasks WHERE finished_at < ? AND status IN "
                "('done', 'failed', 'cancelled')",
                (old_rows,),
            )
            connection.execute(
                """DELETE FROM compute_workers WHERE state = 'pending'
                   AND enroll_expires_at < ?""",
                (_text(now - timedelta(days=7)),),
            )
        for task_id in gone:
            shutil.rmtree(self.folder / task_id, ignore_errors=True)
        # Folders without a task (a submit that never finished, a row dropped): an hour later.
        if self.folder.is_dir():
            known = self._known_ids()
            limit = now.timestamp() - KEEP_OUTPUT.total_seconds()
            for entry in self.folder.iterdir():
                try:
                    if entry.name not in known and entry.stat().st_mtime < limit:
                        shutil.rmtree(entry, ignore_errors=True)
                except OSError:
                    continue

    def _known_ids(self) -> set[str]:
        with self._connect() as connection:
            return {
                row[0]
                for row in connection.execute(
                    "SELECT task_id FROM compute_tasks WHERE collected = 0"
                ).fetchall()
            }

    def _drop(self, task_id: str, name: str) -> None:
        try:
            self._blob(task_id, name).unlink(missing_ok=True)
        except OSError:
            pass

    def waiting_without_worker(self, older_than_seconds: float = 120) -> list[dict[str, Any]]:
        """Apps whose tasks wait for longer than this with no worker online able to run them."""

        limit = _text(_now() - timedelta(seconds=older_than_seconds))
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT app_id, version, environment, size, COUNT(*) AS n,
                   MIN(created_at) AS oldest
                   FROM compute_tasks WHERE status = 'queued'
                   GROUP BY app_id, version, environment, size""",
            ).fetchall()
        if not rows:
            return []
        online = [item for item in self.workers() if item["online"] and item["state"] == "active"]
        found = []
        for row in rows:
            able = any(
                executor.get("app") == row["app_id"]
                and (row["version"] is None or executor.get("version") == row["version"])
                and (executor.get("environment") or DEFAULT_ENVIRONMENT) == row["environment"]
                and fits(item["stats"], row["size"], executor.get("memory_mb"))
                for item in online
                for executor in item["executors"]
            )
            if not able and row["oldest"] < limit:
                found.append(
                    {
                        "app": row["app_id"],
                        "version": row["version"],
                        "environment": row["environment"],
                        "size": row["size"],
                        "queued": row["n"],
                        "oldest_queued_at": row["oldest"],
                    }
                )
        return found

    def overview(self) -> dict[str, Any]:
        """Settings › Compute: the workers, what waits and runs per app, the limits."""

        since = _text(_now() - timedelta(hours=24))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT app_id, priority,
                    SUM(status = 'queued') AS queued, SUM(status = 'running') AS running,
                    SUM(status = 'done' AND finished_at >= ?) AS done,
                    SUM(status = 'failed' AND finished_at >= ?) AS failed,
                    MIN(CASE WHEN status = 'queued' THEN created_at END) AS oldest,
                    AVG(CASE WHEN status = 'done' AND finished_at >= ? THEN seconds END) AS seconds
                FROM compute_tasks GROUP BY app_id, priority ORDER BY app_id, priority
                """,
                (since, since, since),
            ).fetchall()
        queue = [
            {
                "app": row["app_id"],
                "priority": priority_name(row["priority"]),
                "queued": int(row["queued"] or 0),
                "running": int(row["running"] or 0),
                "done_24h": int(row["done"] or 0),
                "failed_24h": int(row["failed"] or 0),
                "oldest_queued_at": row["oldest"],
                "average_seconds": row["seconds"],
            }
            for row in rows
        ]
        return {
            "workers": self.workers(),
            "queue": queue,
            "limits": self.limits(),
            "waiting_without_worker": self.waiting_without_worker(),
        }

    def summary(self) -> dict[str, Any]:
        """What anyone signed in may read of the workers, per app (the Queue panel, an app
        opened): each enrolled worker's name and state, the environments it runs the app in,
        its slots and how many of the app's tasks it runs now, the largest size its machine
        takes. No host, label, credential or machine numbers beyond that."""

        workers = [item for item in self.workers() if item["state"] in ("active", "paused")]
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT worker_id, app_id, COUNT(*) AS n FROM compute_tasks
                   WHERE status = 'running' AND worker_id IS NOT NULL
                   GROUP BY worker_id, app_id"""
            ).fetchall()
            waiting = connection.execute(
                """SELECT app_id, SUM(status = 'queued') AS queued,
                   SUM(status = 'running') AS running FROM compute_tasks
                   WHERE status IN ('queued', 'running') GROUP BY app_id"""
            ).fetchall()
        busy = {(row["worker_id"], row["app_id"]): int(row["n"]) for row in rows}
        apps: dict[str, dict[str, Any]] = {
            row["app_id"]: {
                "queued": int(row["queued"] or 0),
                "running": int(row["running"] or 0),
                "workers": [],
            }
            for row in waiting
        }
        for worker in workers:
            by_app: dict[str, list[dict[str, Any]]] = {}
            for executor in worker["executors"]:
                by_app.setdefault(executor["app"], []).append(executor)
            for app, executors in by_app.items():
                entry = apps.setdefault(app, {"queued": 0, "running": 0, "workers": []})
                entry["workers"].append(
                    {
                        "name": worker["name"],
                        "status": worker["status"],
                        "environments": sorted(
                            {item.get("environment") or DEFAULT_ENVIRONMENT for item in executors}
                        ),
                        "slots": sum(int(item.get("slots") or 0) for item in executors),
                        "running": busy.get((worker["id"], app), 0),
                        "largest_size": _largest(worker["stats"], executors),
                    }
                )
        return {"apps": apps}


def _label(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text and len(text) <= 40 and all(c.isalnum() or c in "-_." for c in text) else ""


def _error(text: Any) -> str:
    return " ".join(str(text or "").split())[:500]


def _executors(items: Any) -> list[dict[str, Any]]:
    """What a worker says its executors are: app, environment, version, slots (anything else
    is dropped); one per app and environment."""

    found: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        app = str(item.get("app") or "").strip().lower()
        if not app or len(app) > 40 or not all(c.isalnum() or c in "-_" for c in app):
            continue
        version = item.get("version")
        try:
            slots = max(0, min(256, int(item.get("slots") or 0)))
        except (TypeError, ValueError):
            slots = 0
        environment = environment_name(item.get("environment"))
        if not environment:
            continue
        found[executor_name(app, environment)] = {
            "app": app,
            "environment": environment,
            "version": str(version)[:40] if version else None,
            "slots": slots,
            "memory_mb": _number(item.get("memory_mb")),
        }
        if len(found) >= 32:
            break
    return list(found.values())


def _largest(stats: dict[str, Any], executors: list[dict[str, Any]]) -> str:
    """The largest size one of these executors takes on this machine."""

    if not executors:
        return largest_size(stats)
    sizes = [largest_size(stats, item.get("memory_mb")) for item in executors]
    return max(sizes, key=list(SIZES).index)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return round(float(value), 2)


def _stats(stats: Any) -> dict[str, Any]:
    if not isinstance(stats, dict):
        return {}
    kept: dict[str, Any] = {}
    for key in ("cpus", "load", "memory_mb", "memory_used_mb", "version"):
        value = stats.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            kept[key] = round(float(value), 2)
        elif key == "version" and isinstance(value, str):
            kept[key] = value[:40]
    return kept


__all__ = [
    "FINISHED",
    "HEARTBEAT_SECONDS",
    "LEASE_SECONDS",
    "MAX_ATTEMPTS",
    "PRIORITIES",
    "ComputeError",
    "ComputeStore",
    "compute_max_bytes",
    "executor_name",
]
