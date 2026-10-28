"""Backups of the install folder: online copies, checks and restores (docs/operations.md)."""

import json
import os
import sqlite3
import tarfile
import threading
import time

import pytest

from processcraft.ops import snapshot
from processcraft.ops.snapshot import SnapshotError


def _install(root):
    """An install folder like install.sh leaves it, with two apps writing to SQLite."""

    root.mkdir(parents=True)
    (root / ".env").write_text("PLANTCRAFT_VERSION=0.1.0\nSECRET=x\n")
    (root / "compose.yaml").write_text("services: {}\n")
    (root / "certs").mkdir()
    (root / "certs" / "server.crt").write_text("cert")
    for app in ("processcraft", "linkcraft"):
        folder = root / "data" / app
        folder.mkdir(parents=True)
        db = sqlite3.connect(folder / f"{app}.sqlite3")
        db.execute("PRAGMA journal_mode = WAL")
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        db.executemany("INSERT INTO items (name) VALUES (?)", [(f"n{i}",) for i in range(50)])
        db.commit()
        db.close()
        (folder / "secret.key").write_text(f"{app}-key")
        (folder / "logs").mkdir()
        (folder / "logs" / f"{app}.jsonl").write_text("{}\n")
    (root / "data" / "linkcraft" / "cache").mkdir()
    (root / "data" / "linkcraft" / "cache" / "big.bin").write_bytes(b"x" * 100)
    (root / "data" / "histcraft-db" / "pgdata").mkdir(parents=True)
    (root / "data" / "histcraft-db" / "pgdata" / "PG_VERSION").write_text("17")
    (root / "data" / "installer" / "status").mkdir(parents=True)
    (root / "data" / "installer" / "status" / "backup-plan.json").write_text(
        json.dumps({"linkcraft": ["cache/"], "bad": ["../../etc/"]})
    )
    (root / "data" / "installer" / "work").mkdir()
    (root / "data" / "installer" / "work" / "upload.pcapp").write_bytes(b"pkg")
    return root


def _rows(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def test_a_backup_holds_the_state_and_leaves_the_rest_out(tmp_path):
    install = _install(tmp_path / "install")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "histcraft-db.dump").write_bytes(b"PGDMP dump")
    manifest = snapshot.take(
        install, tmp_path / "backups" / "b1", reason="daily", extra=extra,
        context={"versions": {"processcraft": "0.1.0"}},
    )  # fmt: skip
    files = manifest["files"]
    assert files["data/linkcraft/linkcraft.sqlite3"]["kind"] == "sqlite"
    assert files["data/linkcraft/linkcraft.sqlite3"]["tables"] == {"items": 50}
    assert files["extra/histcraft-db.dump"]["kind"] == "dump"
    assert {".env", "compose.yaml", "certs/server.crt", "data/linkcraft/secret.key"} <= set(files)
    for left_out in (
        "data/linkcraft/logs/linkcraft.jsonl",
        "data/linkcraft/cache/big.bin",
        "data/histcraft-db/pgdata/PG_VERSION",
        "data/installer/work/upload.pcapp",
        "data/linkcraft/linkcraft.sqlite3-wal",
    ):
        assert left_out not in files
    assert manifest["versions"] == {"processcraft": "0.1.0"} and manifest["reason"] == "daily"
    assert snapshot.verify(tmp_path / "backups" / "b1") == []
    assert oct((tmp_path / "backups" / "b1").stat().st_mode & 0o777) == "0o700"


def test_the_online_copy_holds_every_committed_row_while_the_app_writes(tmp_path):
    install = _install(tmp_path / "install")
    path = install / "data" / "linkcraft" / "linkcraft.sqlite3"
    stop = threading.Event()
    committed = []

    def write():
        db = sqlite3.connect(path, timeout=30)
        while not stop.is_set():
            db.execute("INSERT INTO items (name) VALUES ('live')")
            db.commit()
            committed.append(time.monotonic())
        db.close()

    writer = threading.Thread(target=write)
    writer.start()
    time.sleep(0.2)
    started = len(committed)
    try:
        manifest = snapshot.take(install, tmp_path / "b", reason="test")
    finally:
        stop.set()
        writer.join()
    rows = manifest["files"]["data/linkcraft/linkcraft.sqlite3"]["tables"]["items"]
    assert rows >= 50 + started  # every row committed before the copy started
    assert snapshot.verify(tmp_path / "b") == []


def test_a_damaged_backup_never_passes(tmp_path):
    install = _install(tmp_path / "install")
    snapshot.take(install, tmp_path / "b", reason="test")
    archive = tmp_path / "b" / snapshot.ARCHIVE
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0xFF
    archive.write_bytes(bytes(data))
    assert "does not match its SHA-256" in snapshot.verify(tmp_path / "b")[0]
    (tmp_path / "b" / snapshot.MANIFEST).write_text("{}")
    assert "not a backup of this format" in snapshot.verify(tmp_path / "b")[0]
    with pytest.raises(SnapshotError, match="did not pass its check"):
        snapshot.restore(tmp_path / "b", install, tmp_path / "aside")
    assert _rows(install / "data" / "linkcraft" / "linkcraft.sqlite3") == 50


def test_a_file_changed_inside_the_archive_is_found(tmp_path):
    install = _install(tmp_path / "install")
    manifest = snapshot.take(install, tmp_path / "b", reason="test")
    manifest["files"]["certs/server.crt"]["sha256"] = "0" * 64
    manifest["archive"]["sha256"] = snapshot.sha256(tmp_path / "b" / snapshot.ARCHIVE)
    snapshot.write_manifest(tmp_path / "b", manifest)
    assert snapshot.verify(tmp_path / "b") == ["certs/server.crt: does not match its SHA-256"]


def test_restore_sets_the_current_state_aside_and_can_be_undone(tmp_path):
    install = _install(tmp_path / "install")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "histcraft-db.dump").write_bytes(b"PGDMP dump")
    snapshot.take(install, tmp_path / "b", reason="test", extra=extra)
    with sqlite3.connect(install / "data" / "linkcraft" / "linkcraft.sqlite3") as db:
        db.execute("DELETE FROM items")
    (install / "data" / "linkcraft" / "new-after-backup.txt").write_text("later")
    result = snapshot.restore(tmp_path / "b", install, tmp_path / "aside")
    assert result["restored"] == "b" and "data" in result["moved_aside"]
    assert _rows(install / "data" / "linkcraft" / "linkcraft.sqlite3") == 50
    assert not (install / "data" / "linkcraft" / "new-after-backup.txt").exists()
    assert (tmp_path / "aside" / "data" / "linkcraft" / "new-after-backup.txt").exists()
    assert (tmp_path / "aside" / "extra-restore" / "extra" / "histcraft-db.dump").read_bytes() == (
        b"PGDMP dump"
    )
    assert (install / ".env").read_text().startswith("PLANTCRAFT_VERSION=0.1.0")
    # PostgreSQL's folder is there again, empty, to be filled from the dump.
    assert list((install / "data" / "histcraft-db").iterdir()) == []
    snapshot.put_back(install, tmp_path / "aside")
    assert _rows(install / "data" / "linkcraft" / "linkcraft.sqlite3") == 0
    assert (install / "data" / "linkcraft" / "new-after-backup.txt").read_text() == "later"
    assert (install / "data" / "histcraft-db" / "pgdata" / "PG_VERSION").exists()


def test_restore_refuses_an_archive_that_reaches_outside(tmp_path):
    install = _install(tmp_path / "install")
    snapshot.take(install, tmp_path / "b", reason="test")
    evil = tmp_path / "evil.txt"
    evil.write_text("x")
    archive = tmp_path / "b" / snapshot.ARCHIVE
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(evil, arcname="../outside.txt")
    manifest = snapshot.read_manifest(tmp_path / "b")
    manifest["archive"]["sha256"] = snapshot.sha256(archive)
    manifest["files"] = {"../outside.txt": {"sha256": snapshot.sha256(evil), "kind": "file"}}
    snapshot.write_manifest(tmp_path / "b", manifest)
    with pytest.raises(SnapshotError, match="outside the folder"):
        snapshot.restore(tmp_path / "b", install, tmp_path / "aside")
    assert not (tmp_path / "outside.txt").exists()


def test_the_command_line_answers_json(tmp_path, capsys):
    install = _install(tmp_path / "install")
    assert snapshot.main(["take", str(install), str(tmp_path / "b"), "--reason", "cli"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "ok"
    assert snapshot.main(["verify", str(tmp_path / "b")]) == 0
    assert json.loads(capsys.readouterr().out) == {"state": "ok", "problems": []}
    assert snapshot.main(["take", str(install), str(tmp_path / "b"), "--reason", "cli"]) == 1
    assert "already exists" in json.loads(capsys.readouterr().out)["message"]


def test_a_backup_from_before_install_sh_was_kept_leaves_the_current_one(tmp_path):
    install = _install(tmp_path / "install")
    snapshot.take(install, tmp_path / "b", reason="test")
    (install / "install.sh").write_text("#!/bin/sh\n")
    (install / "release.json").write_text("{}")
    snapshot.restore(tmp_path / "b", install, tmp_path / "aside")
    assert (install / "install.sh").read_text() == "#!/bin/sh\n"  # needed to run anything
    assert not (install / "release.json").exists()  # the restored state had none


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to give files away")
def test_the_carried_status_keeps_its_owner_across_a_restore(tmp_path):
    install = _install(tmp_path / "install")
    status = install / "data" / "installer" / "status"
    (status / "requests").mkdir()
    (status / "requests" / "r1.json").write_text("{}")
    for path in (status, status / "requests", status / "requests" / "r1.json"):
        os.chown(path, 10005, 10005)
    snapshot.take(install, tmp_path / "b", reason="test")
    snapshot.restore(tmp_path / "b", install, tmp_path / "aside")
    for path in (status, status / "requests", status / "requests" / "r1.json"):
        assert (path.stat().st_uid, path.stat().st_gid) == (10005, 10005), path


@pytest.mark.skipif(os.geteuid() != 0, reason="needs root to give files away")
def test_folders_return_with_their_owners_even_when_empty(tmp_path):
    install = _install(tmp_path / "install")
    installer = install / "data" / "installer"
    (installer / "routes").mkdir()
    for path in (installer, installer / "routes"):
        os.chown(path, 10005, 10005)
    snapshot.take(install, tmp_path / "b", reason="test")
    snapshot.restore(tmp_path / "b", install, tmp_path / "aside")
    for path in (installer, installer / "routes"):
        assert path.is_dir() and (path.stat().st_uid, path.stat().st_gid) == (10005, 10005), path
