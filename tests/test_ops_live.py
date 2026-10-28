"""Backup and restore against real Docker, through the operations driver container.

Runs with ``PLANTCRAFT_OPS_LIVE=live`` and the installer image of ``make image``
(``processcraft-installer:<version>``, version from ``PLANTCRAFT_VERSION``, default the
project's). A small stack stands in for the suite: ``processcraft`` writes to SQLite all the
time (the installer image running a loop as uid 10001) and ``histcraft-db`` is PostgreSQL. Then,
each through ``docker run processcraft-ops`` exactly as the installer and ``install.sh`` start
it:

- a backup while both write: verified, with the SQLite files and a full base backup of
  PostgreSQL; the next one is incremental (only the blocks changed since);
- the data is damaged, a restore of the incremental brings back every row of both databases,
  the suite healthy, the database on a new timeline; the backup after it is full again;
- a restore that cannot come up (an image no longer on the host) returns by itself to the state
  before it, healthy, with the data written after the backup.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from processcraft.apps import operations

ROOT = Path(__file__).resolve().parents[1]
LIVE = os.environ.get("PLANTCRAFT_OPS_LIVE") == "live"
pytestmark = pytest.mark.skipif(not LIVE, reason="set PLANTCRAFT_OPS_LIVE=live")
# The suite's PostgreSQL (deploy/compose.yaml): incremental backups need PostgreSQL 17.
POSTGRES = os.environ.get(
    "PLANTCRAFT_OPS_POSTGRES",
    "postgres:17.11-trixie@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3",
)

WRITER = """
import os, sqlite3, time
fixed = '/data/fixed.sqlite3'
if not os.path.exists(fixed):
    db = sqlite3.connect(fixed); db.execute('CREATE TABLE items (id INTEGER PRIMARY KEY)')
    db.executemany('INSERT INTO items VALUES (?)', [(i,) for i in range(50)]); db.commit(); db.close()
db = sqlite3.connect('/data/live.sqlite3'); db.execute('PRAGMA journal_mode = WAL')
db.execute('CREATE TABLE IF NOT EXISTS ticks (at REAL)'); db.commit()
while True:
    db.execute('INSERT INTO ticks VALUES (?)', (time.time(),)); db.commit(); time.sleep(0.05)
"""

COMPOSE = """
name: {project}
services:
  processcraft:
    image: {installer}
    user: "10001:10001"
    read_only: true
    entrypoint: ["python", "-c", {writer}]
    volumes: ["./data/processcraft:/data"]
    network_mode: none
    healthcheck:
      test: ["CMD", "python", "-c", "import os; os.stat('/data/live.sqlite3')"]
      interval: 1s
      retries: 30
  histcraft-db:
    image: {postgres}
    user: "10008:10008"
    command: ["postgres", "-c", "summarize_wal=on", "-c", "restore_command=false"]
    environment:
      POSTGRES_USER: histcraft
      POSTGRES_DB: histcraft
      POSTGRES_HOST_AUTH_METHOD: trust
      POSTGRES_INITDB_ARGS: "--data-checksums"
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes: ["./data/histcraft-db:/var/lib/postgresql/data"]
    tmpfs: ["/var/run/postgresql:size=1m,uid=10008,gid=10008,mode=0700"]
    network_mode: none
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "histcraft", "-d", "histcraft"]
      interval: 1s
      retries: 60
"""


def _version() -> str:
    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return os.environ.get("PLANTCRAFT_VERSION") or pyproject["project"]["version"]


def _run(*args: str, check: bool = True, timeout: float = 900) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise AssertionError(
            f"{' '.join(args[:8])}:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )
    return result


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    installer = f"processcraft-installer:{_version()}"
    _run("docker", "image", "inspect", installer)
    if _run("docker", "image", "inspect", POSTGRES, check=False).returncode != 0:
        _run("docker", "pull", "-q", POSTGRES, timeout=600)
    install = tmp_path_factory.mktemp("ops-live") / "install"
    project = f"pcops{uuid.uuid4().hex[:6]}"
    (install / "data" / "processcraft").mkdir(parents=True)
    (install / "data" / "installer" / "status").mkdir(parents=True)
    (install / "data" / "histcraft-db").mkdir(parents=True)
    os.chown(install / "data" / "processcraft", 10001, 10001)
    os.chown(install / "data" / "histcraft-db", 10008, 10008)
    (install / "compose.yaml").write_text(
        COMPOSE.format(
            project=project, installer=installer, postgres=POSTGRES, writer=json.dumps(WRITER)
        )  # fmt: skip
    )
    (install / ".env").write_text(f"PLANTCRAFT_VERSION={_version()}\n")

    def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return _run("docker", "compose", "--project-directory", str(install), "-p", project,
                    *args, check=check)  # fmt: skip

    def driver(*args: str) -> dict:
        command = operations.driver_command(install, installer, list(args), detach=False,
                                            project=project)  # fmt: skip
        result = _run("docker", *command, check=False, timeout=1800)
        assert result.stdout.strip(), result.stderr
        return json.loads(result.stdout[result.stdout.index("{") :])

    def sql(statement: str) -> str:
        return compose("exec", "-T", "histcraft-db", "psql", "-U", "histcraft", "-d", "histcraft",
                       "-tAc", statement).stdout.strip()  # fmt: skip

    def rows(name: str, table: str) -> int:
        return int(compose("exec", "-T", "processcraft", "python", "-c",
                           f"import sqlite3; print(sqlite3.connect('/data/{name}').execute("
                           f"'SELECT COUNT(*) FROM {table}').fetchone()[0])").stdout)  # fmt: skip

    compose("up", "-d", "--wait", "--wait-timeout", "180")
    sql("CREATE TABLE points (id INTEGER); INSERT INTO points SELECT generate_series(1, 100);")

    class Stack:
        pass

    s = Stack()
    s.install, s.project, s.compose, s.driver, s.sql, s.rows = (
        install,
        project,
        compose,
        driver,
        sql,
        rows,
    )
    yield s
    compose("down", "-v", "--remove-orphans", check=False)
    for line in _run(
        "docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"
    ).stdout.split():
        if ":rollback-" in line:
            _run("docker", "image", "rm", line, check=False)
    shutil.rmtree(install, ignore_errors=True)


def test_backup_then_restore_brings_every_row_back(stack):
    full = stack.driver("drive", "backup", "--reason", "manual")
    assert full["state"] == "ok", full
    assert full["histcraft_db"] == "full"
    stack.sql("INSERT INTO points SELECT generate_series(101, 150);")
    outcome = stack.driver("drive", "backup", "--reason", "manual")
    assert outcome["state"] == "ok", outcome
    assert outcome["histcraft_db"] == "incremental"
    folder = stack.install / "backups" / outcome["name"]
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["files"]["data/processcraft/fixed.sqlite3"]["tables"] == {"items": 50}
    assert manifest["files"]["data/processcraft/live.sqlite3"]["tables"]["ticks"] > 0
    assert manifest["histcraft_db"]["chain"] == [full["name"], outcome["name"]]
    assert "public.points" in manifest["histcraft_db"]["tables"]
    assert (folder / "histcraft-db" / "backup_manifest").is_file()
    assert json.loads((folder / "status.json").read_text())["state"] == "ok"
    assert oct(folder.stat().st_mode & 0o777) == "0o700"

    stack.sql("DELETE FROM points;")
    stack.compose("exec", "-T", "processcraft", "python", "-c",
                  "import sqlite3; d = sqlite3.connect('/data/fixed.sqlite3'); "
                  "d.execute('DELETE FROM items'); d.commit()")  # fmt: skip
    assert stack.rows("fixed.sqlite3", "items") == 0

    restored = stack.driver("drive", "restore", "--name", outcome["name"])
    assert restored["state"] == "ok", restored
    assert stack.rows("fixed.sqlite3", "items") == 50
    assert stack.sql("SELECT COUNT(*) FROM points;") == "150"
    assert stack.sql("SELECT timeline_id FROM pg_control_checkpoint();") != "1"
    after = stack.driver("drive", "backup", "--reason", "manual")
    assert after["state"] == "ok" and after["histcraft_db"] == "full", after
    owner = (stack.install / "data" / "processcraft" / "fixed.sqlite3").stat()
    assert (owner.st_uid, owner.st_gid) == (10001, 10001)
    aside = stack.install / "backups" / restored["aside"]
    assert (aside / "data" / "processcraft" / "fixed.sqlite3").exists()  # set aside, not deleted


def test_a_restore_that_cannot_start_returns_by_itself(stack):
    outcome = stack.driver("drive", "backup", "--reason", "manual")
    assert outcome["state"] == "ok", outcome
    folder = stack.install / "backups" / outcome["name"]
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["images"] = [{"ref": "processcraft-gone:9.9.9", "id": "sha256:" + "0" * 64}]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    stack.sql("INSERT INTO points SELECT generate_series(151, 170);")
    marker = stack.install / "data" / "processcraft" / "written-after.txt"
    marker.write_text("after the backup")

    failed = stack.driver("drive", "restore", "--name", outcome["name"])
    assert failed["state"] == "failed", failed
    assert "returned to its state before it" in failed["message"]
    assert marker.read_text() == "after the backup"
    assert stack.sql("SELECT COUNT(*) FROM points;") == "170"
    states = stack.compose("ps", "--format", "{{.Service}} {{.Health}}").stdout.split("\n")
    assert sorted(line for line in states if line) == [
        "histcraft-db healthy",
        "processcraft healthy",
    ]


def test_the_restore_drill_starts_a_separate_copy_and_leaves_nothing(stack):
    before = set(_run("docker", "ps", "-aq").stdout.split())
    networks = set(_run("docker", "network", "ls", "-q").stdout.split())
    outcome = stack.driver("drive", "drill")
    assert outcome["state"] == "ok", outcome
    drill = json.loads((stack.install / "data" / "installer" / "status" / "drill.json").read_text())
    assert drill["state"] == "ok" and drill["problems"] == []
    assert set(_run("docker", "ps", "-aq").stdout.split()) == before
    assert set(_run("docker", "network", "ls", "-q").stdout.split()) == networks
    assert not list((stack.install / "backups").glob(".drill-*"))
    states = stack.compose("ps", "--format", "{{.Service}} {{.Health}}").stdout.split("\n")
    assert "processcraft healthy" in states  # the live suite never stopped
