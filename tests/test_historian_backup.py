"""The Historian's database in a backup: full and incremental base backups, their chain, its
check, its rebuild on restore and in the drill, and retention (against a recorded Docker)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from plantcraft.apps import historian_backup as hb
from plantcraft.apps import operations as ops
from tests.test_ops_driver import NOW, FakeDocker
from tests.test_ops_snapshot import _install

IMAGE = "postgres:17.11-trixie@sha256:abc"


class FakePostgres(FakeDocker):
    """``histcraft-db`` runs: psql answers, pg_basebackup writes a backup folder, the tools in
    their throwaway container check and join them (``fail``: incremental, verify, combine)."""

    def __init__(self, install: Path):
        super().__init__(histcraft=True)
        self.install = install
        self.summaries = "on"
        self.taken: list[tuple[str, str | None]] = []
        self.tools: list[list[str]] = []

    def images_in_use(self):
        return [*super().images_in_use(), IMAGE]

    def run(self, *args, check=True, stdin=None, stdout=None, env=None, timeout=900):
        args = list(args)
        if args[0] == "compose" and "config" in args and "json" in args:
            self.calls.append(args)
            services = {"processcraft": {"image": "processcraft:0.1.0"},
                        "histcraft-db": {"image": IMAGE}}  # fmt: skip
            return self._done(args, out=json.dumps({"services": services}))
        if args[0] == "compose" and "psql" in args:
            self.calls.append(args)
            query = " ".join(args)
            if "server_version_num" in query:
                return self._done(
                    args, out=f"170011|7300000000000000001|1048576|{self.summaries}\n"
                )
            if "pg_stat_user_tables" in query:
                return self._done(args, out="public.archive,public.signals\n")
            return self._done(args)
        if args[0] == "compose" and "pg_basebackup" in args:
            self.calls.append(args)
            target = args[args.index("-D") + 1]
            name = target.rsplit("/", 1)[-1]
            base = next((a.split("=", 1)[1] for a in args if a.startswith("--incremental=")), None)
            if base and "incremental" in self.fail:
                return self._done(args, 1)
            folder = self.install / "data" / "histcraft-db" / hb.STAGING / name
            folder.mkdir(parents=True)
            (folder / "base").write_bytes(b"x" * (10 if base else 1000))
            (folder / "backup_manifest").write_text(json.dumps({"name": name, "base": base}))
            self.taken.append((name, base))
            return self._done(args)
        if args[0] == "run" and hb.TOOL in args:
            self.calls.append(args)
            tool = args[args.index("--entrypoint") + 1]
            self.tools.append([tool, *args[args.index("--entrypoint") + 3 :]])
            mounts = dict(
                reversed(args[i + 1].rsplit(":ro", 1)[0].split(":", 1))
                for i, a in enumerate(args) if a == "-v"
            )  # fmt: skip
            if tool == "pg_verifybackup" and "verify" in self.fail:
                return self._done(args, 1)
            if tool == "pg_combinebackup":
                if "combine" in self.fail:
                    return self._done(args, 1)
                out = Path(mounts["/target"]) / hb.PGDATA
                out.mkdir(mode=0o700)
                (out / "PG_VERSION").write_text("17")
                (out / "backup_manifest").write_text("{}")
                chain = [
                    json.loads((Path(mounts[c]) / "backup_manifest").read_text())["name"]
                    for c in args[args.index("--entrypoint") + 3 :]
                    if c.startswith("/chain/")
                ]
                (out / "chain.json").write_text(json.dumps(chain))
            return self._done(args)
        return super().run(*args, check=check, stdin=stdin, stdout=stdout, env=env,
                           timeout=timeout)  # fmt: skip


@pytest.fixture()
def driver(tmp_path):
    install = _install(tmp_path / "install")
    clock = iter(NOW + timedelta(minutes=i) for i in range(10_000))
    return ops.Driver(install, docker=FakePostgres(install), project="pc-test",
                      clock=lambda: next(clock))  # fmt: skip


def _manifest(driver, name):
    return json.loads((driver.backups / name / "manifest.json").read_text())["histcraft_db"]


def test_the_first_backup_is_full_and_starts_a_lineage(driver):
    outcome = driver.run("backup", reason="manual")
    assert outcome["state"] == "ok", outcome
    assert outcome["histcraft_db"] == "full"
    info = _manifest(driver, outcome["name"])
    assert info["kind"] == "full" and info["base"] is None and info["chain"] == [outcome["name"]]
    assert info["why_full"] == "first backup of this database"
    assert info["tables"] == ["public.archive", "public.signals"]
    assert (
        info["lineage"] == (driver.install / "data/histcraft-db/backup-lineage").read_text().strip()
    )
    assert (driver.backups / outcome["name"] / "histcraft-db" / "backup_manifest").is_file()
    assert not (driver.install / "data" / "histcraft-db" / hb.STAGING).exists()
    assert driver.docker.tools == [["pg_verifybackup", "/backup"]]  # read in full
    command = next(c for c in driver.docker.calls if "pg_basebackup" in c)
    assert "-X" in command and "stream" in command and "--manifest-checksums=SHA256" in command
    listed = driver.list_backups()[0]
    assert listed["histcraft_db"]["kind"] == "full"
    assert listed["size"] == (
        driver.backups / outcome["name"] / "data.tar.gz"
    ).stat().st_size + 1000 + len(
        (driver.backups / outcome["name"] / "histcraft-db" / "backup_manifest").read_text()
    )


def test_the_next_backups_are_incremental_until_the_chain_is_long(driver):
    names = [driver.run("backup", reason="daily")["name"] for _ in range(hb.MAX_CHAIN + 1)]
    kinds = [_manifest(driver, name)["kind"] for name in names]
    assert kinds == ["full"] + ["incremental"] * (hb.MAX_CHAIN - 1) + ["full"]
    second = _manifest(driver, names[1])
    assert second["base"] == names[0] and second["chain"] == names[:2]
    assert _manifest(driver, names[-2])["chain"] == names[: hb.MAX_CHAIN]
    assert _manifest(driver, names[-1])["why_full"] == f"the chain reached {hb.MAX_CHAIN} backups"
    assert driver.docker.taken[1] == (names[1], f"{hb.MOUNT}/{hb.STAGING}/{names[1]}.base-manifest")
    # The newest is read in full, the ones it builds on only for presence and size.
    assert [
        "pg_verifybackup",
        "--skip-checksums",
        "--no-parse-wal",
        "/backup",
    ] in driver.docker.tools
    listed = {b["name"]: b for b in driver.list_backups()}
    assert sorted(listed[names[0]]["needed_by"]) == names[1 : hb.MAX_CHAIN]


def test_an_incremental_the_server_refuses_becomes_a_full_backup(driver):
    driver.run("backup", reason="manual")
    driver.docker.fail.add("incremental")
    outcome = driver.run("backup", reason="manual")
    assert outcome["state"] == "ok", outcome
    info = _manifest(driver, outcome["name"])
    assert info["kind"] == "full" and info["why_full"].startswith("incremental refused")


def test_without_wal_summaries_every_backup_is_full(driver):
    driver.docker.summaries = "off"
    driver.run("backup", reason="manual")
    outcome = driver.run("backup", reason="manual")
    assert _manifest(driver, outcome["name"])["kind"] == "full"
    assert "summarize_wal" in _manifest(driver, outcome["name"])["why_full"]


def test_a_database_of_another_lineage_never_builds_on_an_old_backup(driver):
    driver.run("backup", reason="manual")
    (driver.install / "data" / "histcraft-db" / "backup-lineage").write_text("someone-else\n")
    outcome = driver.run("backup", reason="manual")
    assert _manifest(driver, outcome["name"])["kind"] == "full"


def test_a_backup_whose_base_is_damaged_does_not_count(driver):
    first = driver.run("backup", reason="manual")["name"]
    second = driver.run("backup", reason="manual")["name"]
    (driver.backups / first / "histcraft-db" / "backup_manifest").write_text("changed")
    outcome = driver.run("verify", name=second)
    assert outcome["state"] == "failed" and "its manifest was changed" in outcome["message"]
    status = json.loads((driver.backups / second / "status.json").read_text())
    assert status["state"] == "failed"
    # A damaged chain is never built on: the next backup is full.
    assert _manifest(driver, driver.run("backup", reason="manual")["name"])["kind"] == "full"


def test_a_failed_check_of_the_database_fails_the_backup(driver):
    driver.docker.fail.add("verify")
    outcome = driver.run("backup", reason="manual")
    assert outcome["state"] == "failed" and "pg_verifybackup" in outcome["message"]


def test_a_check_again_reads_the_whole_chain(driver):
    driver.run("backup", reason="manual")
    second = driver.run("backup", reason="manual")["name"]
    driver.docker.tools.clear()
    assert driver.run("verify", name=second)["state"] == "ok"
    assert driver.docker.tools == [["pg_verifybackup", "/backup"]] * 2


def test_restore_rebuilds_the_chain_on_a_new_timeline_and_the_next_backup_is_full(driver):
    names = [driver.run("backup", reason="daily")["name"] for _ in range(3)]
    outcome = driver.run("restore", name=names[-1])
    assert outcome["state"] == "ok", outcome
    pgdata = driver.install / "data" / "histcraft-db" / "pgdata"
    assert json.loads((pgdata / "chain.json").read_text()) == names
    assert (pgdata / "recovery.signal").is_file()
    assert not (pgdata / "backup_manifest").exists()
    assert ["pg_verifybackup", "/target/pgdata"] in driver.docker.tools  # the rebuilt copy
    assert not (driver.install / "data" / "histcraft-db" / "backup-lineage").exists()
    # The database set aside keeps its files and its lineage.
    aside = driver.backups / outcome["aside"] / "data" / "histcraft-db"
    assert (aside / "pgdata" / "PG_VERSION").is_file() and (aside / "backup-lineage").is_file()
    assert _manifest(driver, driver.run("backup", reason="manual")["name"])["kind"] == "full"


def test_a_restore_whose_database_cannot_be_rebuilt_returns_by_itself(driver):
    name = driver.run("backup", reason="manual")["name"]
    lineage = (driver.install / "data" / "histcraft-db" / "backup-lineage").read_text()
    driver.docker.fail.add("combine")
    outcome = driver.run("restore", name=name)
    assert outcome["state"] == "failed" and "returned to its state before it" in outcome["message"]
    assert "pg_combinebackup" in outcome["message"]
    db = driver.install / "data" / "histcraft-db"
    assert (db / "backup-lineage").read_text() == lineage  # the same database, chain intact
    assert (db / "pgdata" / "PG_VERSION").is_file()


def test_restore_refuses_a_backup_whose_chain_is_gone(driver):
    first = driver.run("backup", reason="manual")["name"]
    second = driver.run("backup", reason="manual")["name"]
    import shutil

    shutil.rmtree(driver.backups / first)
    outcome = driver.run("restore", name=second)
    assert outcome["state"] == "failed" and "nothing changed" in outcome["message"]
    assert "is gone" in outcome["message"]
    assert not any(" down " in f" {verb} " for verb in driver.docker.verbs())


def test_the_drill_rebuilds_the_database_in_the_copy_and_reads_its_tables(driver, monkeypatch):
    monkeypatch.setattr(ops.Driver, "available_memory", staticmethod(lambda: 2**40))
    driver.run("backup", reason="manual")
    outcome = driver.run("drill")
    assert outcome["state"] == "ok", outcome
    combine = next(c for c in driver.docker.calls if "pg_combinebackup" in c)
    target = next(v for v in combine if v.endswith(":/target"))
    assert "/.drill-" in target  # never the live folder
    reads = next(c for c in driver.docker.calls if "psql" in c and ops.DRILL_PROJECT in c)
    assert (
        'SELECT 1 FROM "public"."archive" LIMIT 1; SELECT 1 FROM "public"."signals" LIMIT 1'
        in reads
    )


def test_an_interrupted_backup_leaves_no_staged_copy(driver):
    stage = driver.install / "data" / "histcraft-db" / hb.STAGING / "x"
    stage.mkdir(parents=True)
    driver.operation = {"action": "backup", "name": "20261021-020000-manual"}
    driver.phase("backing up the Historian database (a full backup)")
    driver.resume()
    assert not stage.parent.exists()
    assert ["rm", "-f", hb.TOOL] in driver.docker.calls


def _backup(name, kind=None, chain=None, state="ok"):
    item = {"name": name, "state": state, "reason": name[16:]}
    if kind:
        item["histcraft_db"] = {"kind": kind, "chain": chain or [name]}
    return item


def test_retention_keeps_every_backup_a_kept_one_builds_on():
    now = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)
    names = [(now - timedelta(days=day)).strftime("%Y%m%d-020000") + "-daily" for day in range(30)]
    names.reverse()  # oldest first
    backups = []
    chain: list[str] = []
    for position, name in enumerate(names):
        chain = [name] if position % hb.MAX_CHAIN == 0 else [*chain, name]
        backups.append(_backup(name, "full" if len(chain) == 1 else "incremental", chain))
    removed = set(ops.to_delete(backups, now))
    kept = {b["name"]: b for b in backups if b["name"] not in removed}
    for backup in kept.values():
        assert set(backup["histcraft_db"]["chain"]) <= set(kept), backup["name"]
    # Old weeks and months are held by their full backup, not a chain of incrementals.
    recent = {name for b in backups[-7:] for name in b["histcraft_db"]["chain"]}
    old = [b for b in kept.values() if b["name"] not in recent]
    assert old and all(b["histcraft_db"]["kind"] == "full" for b in old)
