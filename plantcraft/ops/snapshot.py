"""A backup of the install folder, taken while the suite runs, and its restore (docs/operations.md).

Runs as root in a throwaway container of the installer image with no network and the install
folder mounted (``python -m plantcraft.ops.snapshot take|verify|restore``), so it reads and
writes every app's files with their owners kept. Standard library only.

``take`` copies the install folder's state into ``<backup>/data.tar.gz`` and describes it in
``<backup>/manifest.json``:

- every SQLite database (found by its header, whatever its name) through SQLite's online backup,
  which is consistent while the app keeps writing, then checked with ``integrity_check`` and its
  rows counted per table;
- every other file of ``data/``, ``certs/``, ``trusted-publishers/`` and the settings (``.env``,
  ``compose.yaml``, ``bundle.env``, ``release.json``) as it is;
- the ``extra`` files the caller prepared, under ``extra/`` (in older backups, HistCraft's ``pg_dump``).

Left out: PostgreSQL's own files (``data/histcraft-db``: its base backup is beside the archive,
``plantcraft.apps.historian_backup``), logs, the installer's
scratch folder, pending app requests, SQLite's ``-wal``/``-shm`` files (the online copy holds
their content) and each app's ``[backup] skip`` paths.

``verify`` reads the archive back: every file's SHA-256 against the manifest and every database
through ``integrity_check``. ``restore`` sets the current state aside (renamed, nothing deleted)
and unpacks the archive in its place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

FORMAT = 1
MANIFEST = "manifest.json"
ARCHIVE = "data.tar.gz"
SQLITE_HEADER = b"SQLite format 3\x00"
SETTINGS = (".env", "compose.yaml", "bundle.env", "release.json", "install.sh", "RELEASE-NOTES.md")
# Settings a backup taken before they existed does not hold: a restore of it keeps the current one
# (install.sh is needed to run anything; every other setting returns to its state, even absent).
KEPT_WHEN_MISSING = ("install.sh", "RELEASE-NOTES.md")
FOLDERS = ("data", "certs", "trusted-publishers")
# Never in the archive: PostgreSQL's files (backed up apart), the installer's scratch and status (written
# again by the installer), pending uploads, and the Notebooks kits a deploy built.
SKIPPED_FOLDERS = (
    "data/histcraft-db",
    "data/installer/work",
    "data/installer/status",
    "data/app-requests",
    # Notebooks kits a deploy built (ci/macmini/notebook-kits): built again, never restored.
    "data/processcraft/notebook-kits",
)
# Kept across a restore, from the state it replaces: what the installer reports to PlantCraft
# (requests in progress, the operation running) belongs to now, not to the backup's day.
CARRIED = ("data/installer/status", "data/app-requests")
SKIPPED_NAMES = ("logs",)
SKIPPED_SUFFIXES = ("-wal", "-shm", "-journal")
CHUNK = 1024 * 1024


class SnapshotError(Exception):
    """A backup or restore that cannot go on; the message is for the administrator."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _skipped(relative: PurePosixPath, skip: tuple[str, ...]) -> bool:
    text = relative.as_posix()
    if any(text == folder or text.startswith(folder + "/") for folder in SKIPPED_FOLDERS):
        return True
    if any(part in SKIPPED_NAMES for part in relative.parts[:-1]):
        return True
    for pattern in skip:
        if pattern.endswith("/") and text.startswith(pattern):
            return True
        if text == pattern:
            return True
    return False


def app_skips(install: Path) -> tuple[str, ...]:
    """``data/<app>/<path>`` for each ``[backup] skip`` path an app declared.

    The installer writes the declarations it read from each app's ``app.toml`` to
    ``data/installer/status/backup-plan.json`` (``{"<app>": ["cache/", ...]}``).
    """

    try:
        plan = json.loads((install / "data/installer/status/backup-plan.json").read_text("utf-8"))
    except (OSError, ValueError):
        return ()
    skips = []
    if isinstance(plan, dict):
        for app, paths in plan.items():
            if isinstance(app, str) and app.isidentifier() and isinstance(paths, list):
                skips += [f"data/{app}/{path}" for path in paths if _safe_relative(path)]
    return tuple(skips)


def _safe_relative(path: Any) -> bool:
    if not isinstance(path, str) or not path or path.startswith("/"):
        return False
    return ".." not in PurePosixPath(path).parts


def sqlite_open(source: Path) -> sqlite3.Connection:
    """A read-only connection to ``source`` that holds one read snapshot from now on.

    In WAL mode the snapshot costs the apps nothing (writers go on beside it) and the copy taken
    from it later is the database as it was at this instant. ``take`` opens every database of the
    installation this way first, in a few milliseconds, so the backup holds the whole suite at one
    moment: a reference from one app to another (``run:<app>/<id>``) never points past the copy.
    A database not in WAL (Docker Desktop's bind mounts, a share) is not held: there a held read
    would stop its app's writes for the whole backup, so it is copied on its own, in one step.
    """

    reader = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60, isolation_level=None)
    try:
        reader.execute("PRAGMA busy_timeout = 60000")
        if reader.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            reader.execute("BEGIN")
            reader.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        reader.close()
        raise
    return reader


def sqlite_copy(
    source: Path, target: Path, reader: sqlite3.Connection | None = None
) -> dict[str, int]:
    """Copy one database with SQLite's online backup; returns its rows per table.

    ``reader`` is the connection ``sqlite_open`` gave (its snapshot is what is copied); without
    it one is opened now. The copy is one step: a backup in steps starts again whenever another
    process commits between two of them, and a busy app (a commit every few milliseconds) kept
    it from ever finishing. Raises ``SnapshotError`` when the copy fails ``integrity_check``.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    reader = reader or sqlite_open(source)
    writer = sqlite3.connect(target)
    try:
        reader.backup(writer)
        # One self-contained file (no -wal beside it); the app turns WAL on again when it opens.
        writer.execute("PRAGMA journal_mode = DELETE")
    finally:
        reader.close()
        writer.close()
    return sqlite_check(target)


def sqlite_check(path: Path) -> dict[str, int]:
    """``integrity_check`` and the rows of each table; raises ``SnapshotError``."""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if result != ["ok"]:
            raise SnapshotError(f"{path.name}: integrity_check says {'; '.join(result[:5])}")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in sorted(tables)
        }
    except sqlite3.DatabaseError as exc:
        raise SnapshotError(f"{path.name}: {exc}") from exc
    finally:
        connection.close()


def _sqlite_side_file(path: Path) -> bool:
    """A database's ``-wal``, ``-shm`` or ``-journal`` (its online copy holds their content)."""

    for suffix in SKIPPED_SUFFIXES:
        if path.name.endswith(suffix) and is_sqlite(path.with_name(path.name[: -len(suffix)])):
            return True
    return False


def _copy_one(source: Path, target: Path, reader: sqlite3.Connection | None) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {"kind": "file"}
    if reader is not None:
        entry = {"kind": "sqlite", "tables": sqlite_copy(source, target, reader)}
    else:
        shutil.copy2(source, target)
    status = source.stat()
    if os.geteuid() == 0:
        os.chown(target, status.st_uid, status.st_gid)
    os.chmod(target, status.st_mode & 0o7777)
    entry.update(size=target.stat().st_size, sha256=sha256(target))
    return entry


def _copy_tree(install: Path, stage: Path, skip: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    sources = [install / name for name in SETTINGS if (install / name).is_file()]
    for folder in FOLDERS:
        root = install / folder
        if root.is_dir():
            for directory, subfolders, names in os.walk(root):
                here = Path(directory)
                # Every folder, even an empty one (an app's routes), returns with its owner.
                (stage / here.relative_to(install)).mkdir(parents=True, exist_ok=True)
                subfolders[:] = sorted(
                    name
                    for name in subfolders
                    if not _skipped(PurePosixPath((here / name).relative_to(install)), skip)
                )
                sources += [here / name for name in sorted(names)]
    sources = [
        source
        for source in sources
        if not _skipped(PurePosixPath(source.relative_to(install)), skip)
        and not source.is_symlink()
        and source.is_file()
        and not _sqlite_side_file(source)
    ]
    # Every database's snapshot first, together: the backup is the suite at one instant.
    readers: dict[Path, sqlite3.Connection] = {}
    try:
        for source in sources:
            if is_sqlite(source):
                readers[source] = sqlite_open(source)
        for source in sources:
            relative = PurePosixPath(source.relative_to(install))
            files[relative.as_posix()] = _copy_one(
                source, stage / relative, readers.pop(source, None)
            )
    finally:
        for reader in readers.values():
            reader.close()
    # Folders keep their owners and modes too (each app owns its own).
    for directory in sorted(path for path in stage.rglob("*") if path.is_dir()):
        original = install / directory.relative_to(stage)
        if original.is_dir():
            status = original.stat()
            if os.geteuid() == 0:
                os.chown(directory, status.st_uid, status.st_gid)
            os.chmod(directory, status.st_mode & 0o7777)
    return files


def take(
    install: str | Path,
    out: str | Path,
    *,
    reason: str,
    extra: str | Path | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Back the install folder up into the new folder ``out``; returns the manifest."""

    install, out = Path(install), Path(out)
    if out.exists():
        raise SnapshotError(f"{out.name} already exists")
    out.mkdir(parents=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=out))
    try:
        files = _copy_tree(install, stage, app_skips(install))
        if extra is not None and Path(extra).is_dir():
            for source in sorted(Path(extra).iterdir()):
                if source.is_file() and not source.is_symlink():
                    target = stage / "extra" / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    os.chmod(target, 0o600)
                    files[f"extra/{source.name}"] = {
                        "kind": "dump" if source.suffix == ".dump" else "file",
                        "size": target.stat().st_size,
                        "sha256": sha256(target),
                    }
        archive = out / ARCHIVE
        with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
            for name in sorted(path.name for path in stage.iterdir()):
                tar.add(stage / name, arcname=name)
        os.chmod(archive, 0o600)
    except (OSError, sqlite3.Error) as exc:
        raise SnapshotError(f"the backup failed: {exc}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    # The folders left out, with their owners: a restore drill makes them again, empty.
    folders = {}
    for relative in SKIPPED_FOLDERS:
        path = install / relative
        if path.is_dir() and not path.is_symlink():
            status = path.stat()
            folders[relative] = {
                "uid": status.st_uid, "gid": status.st_gid, "mode": status.st_mode & 0o7777,
            }  # fmt: skip
    manifest = {
        "format": FORMAT,
        "folders": folders,
        "name": out.name,
        "created_at": now(),
        "reason": reason,
        **(context or {}),
        "files": files,
        "archive": {"name": ARCHIVE, "size": archive.stat().st_size, "sha256": sha256(archive)},
    }
    write_manifest(out, manifest)
    return manifest


def write_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    partial = folder / f".{MANIFEST}.partial"
    partial.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(partial, 0o600)
    partial.replace(folder / MANIFEST)


def read_manifest(folder: str | Path) -> dict[str, Any]:
    try:
        manifest = json.loads((Path(folder) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"{Path(folder).name}: no readable manifest ({exc})") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise SnapshotError(f"{Path(folder).name}: not a backup of this format")
    return manifest


def _members(tar: tarfile.TarFile) -> dict[str, tarfile.TarInfo]:
    return {member.name: member for member in tar.getmembers() if member.isfile()}


def verify(folder: str | Path) -> list[str]:
    """Every problem of the backup in ``folder`` (none: it can be restored)."""

    folder = Path(folder)
    try:
        manifest = read_manifest(folder)
    except SnapshotError as exc:
        return [str(exc)]
    archive = folder / ARCHIVE
    expected = manifest.get("archive") or {}
    if not archive.is_file():
        return [f"{ARCHIVE} is missing"]
    if sha256(archive) != expected.get("sha256"):
        return [f"{ARCHIVE} does not match its SHA-256: the file was changed or damaged"]
    problems: list[str] = []
    files: dict[str, dict[str, Any]] = manifest.get("files") or {}
    with tempfile.TemporaryDirectory(prefix=".verify-", dir=folder) as scratch:
        try:
            with tarfile.open(archive, "r:gz") as tar:
                members = _members(tar)
                for name in sorted(set(files) - set(members)):
                    problems.append(f"{name}: in the manifest, not in the archive")
                for name in sorted(set(members) - set(files)):
                    problems.append(f"{name}: in the archive, not in the manifest")
                for name, entry in sorted(files.items()):
                    member = members.get(name)
                    if member is None:
                        continue
                    digest = hashlib.sha256()
                    handle = tar.extractfile(member)
                    target = Path(scratch) / "db"
                    with handle as source, target.open("wb") as copy:  # type: ignore[union-attr]
                        for block in iter(lambda: source.read(CHUNK), b""):
                            digest.update(block)
                            if entry.get("kind") == "sqlite":
                                copy.write(block)
                    if digest.hexdigest() != entry.get("sha256"):
                        problems.append(f"{name}: does not match its SHA-256")
                    elif entry.get("kind") == "sqlite":
                        try:
                            if sqlite_check(target) != entry.get("tables"):
                                problems.append(f"{name}: its rows differ from the manifest")
                        except SnapshotError as exc:
                            problems.append(f"{name}: {exc}")
                    target.unlink(missing_ok=True)
        except (OSError, tarfile.TarError, EOFError) as exc:
            problems.append(f"{ARCHIVE} cannot be read: {exc}")
    return problems


def _safe_members(tar: tarfile.TarFile, target: Path) -> list[tarfile.TarInfo]:
    """The archive's members, each a file or folder inside ``target`` (nothing else)."""

    members = []
    for member in tar.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SnapshotError(f"the archive names a path outside the folder: {member.name}")
        if not (member.isfile() or member.isdir()):
            raise SnapshotError(f"the archive holds something other than files: {member.name}")
        if path.parts and path.parts[0] not in {*FOLDERS, *SETTINGS, "extra"}:
            raise SnapshotError(f"the archive holds an unexpected entry: {member.name}")
        members.append(member)
    return members


def restore(folder: str | Path, install: str | Path, aside: str | Path) -> dict[str, Any]:
    """Put the backup in ``folder`` in place of the install folder's state.

    The current state is moved to ``aside`` first (a rename: nothing is deleted, and it is
    instant on the same disk). ``extra/`` is unpacked to ``aside/extra-restore`` for the
    caller (the PostgreSQL dump of an older backup). Returns what was moved and restored.
    """

    folder, install, aside = Path(folder), Path(install), Path(aside)
    problems = verify(folder)
    if problems:
        raise SnapshotError("the backup did not pass its check: " + "; ".join(problems[:5]))
    manifest = read_manifest(folder)
    aside.mkdir(parents=True, exist_ok=False, mode=0o700)
    moved = []
    held = set(manifest.get("files") or {})
    for name in (*FOLDERS, *SETTINGS):
        current = install / name
        if name in KEPT_WHEN_MISSING and name not in held:
            continue
        if current.exists() or current.is_symlink():
            current.rename(aside / name)
            moved.append(name)
    # data/histcraft-db returns empty: the driver rebuilds the Historian database in it.
    try:
        with tarfile.open(folder / ARCHIVE, "r:gz") as tar:
            members = _safe_members(tar, install)
            plain = [m for m in members if PurePosixPath(m.name).parts[0] != "extra"]
            extra = [m for m in members if PurePosixPath(m.name).parts[0] == "extra"]
            tar.extractall(install, members=plain, filter="tar", numeric_owner=True)
            if extra:
                tar.extractall(
                    aside / "extra-restore", members=extra, filter="tar", numeric_owner=True
                )
        for relative in SKIPPED_FOLDERS:
            kept, target = aside / relative, install / relative
            if not kept.is_dir() or target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative in CARRIED:
                copy_owned(kept, target)
            else:
                # Empty, with its owner: the driver rebuilds PostgreSQL's files there.
                target.mkdir()
            status = kept.stat()
            if os.geteuid() == 0:
                os.chown(target, status.st_uid, status.st_gid)
            os.chmod(target, status.st_mode & 0o7777)
    except (OSError, tarfile.TarError) as exc:
        raise SnapshotError(f"the restore failed while unpacking: {exc}") from exc
    return {"restored": manifest["name"], "moved_aside": moved, "aside": aside.name}


def unpack(folder: str | Path, target: str | Path, extra: str | Path) -> dict[str, Any]:
    """The checked backup in ``folder`` unpacked into the new, empty folder ``target`` (a restore
    drill); ``extra/`` goes to ``extra``. Returns the manifest."""

    folder, target, extra = Path(folder), Path(target), Path(extra)
    problems = verify(folder)
    if problems:
        raise SnapshotError("the backup did not pass its check: " + "; ".join(problems[:5]))
    target.mkdir(parents=True, mode=0o700)
    try:
        with tarfile.open(folder / ARCHIVE, "r:gz") as tar:
            members = _safe_members(tar, target)
            plain = [m for m in members if PurePosixPath(m.name).parts[0] != "extra"]
            dumps = [m for m in members if PurePosixPath(m.name).parts[0] == "extra"]
            tar.extractall(target, members=plain, filter="tar", numeric_owner=True)
            tar.extractall(extra, members=dumps, filter="tar", numeric_owner=True)
        manifest = read_manifest(folder)
        for relative, owner in sorted((manifest.get("folders") or {}).items()):
            if relative not in SKIPPED_FOLDERS:
                continue
            path = target / relative
            path.mkdir(parents=True, exist_ok=True)
            if os.geteuid() == 0:
                os.chown(path, int(owner["uid"]), int(owner["gid"]))
            os.chmod(path, int(owner["mode"]) & 0o7777)
    except (OSError, tarfile.TarError, KeyError, TypeError, ValueError) as exc:
        raise SnapshotError(f"unpacking failed: {exc}") from exc
    return manifest


def copy_owned(source: Path, target: Path) -> None:
    """``shutil.copytree`` that keeps each entry's owner and mode (as root): the installer's
    status files stay its own after a restore, or it can no longer write them."""

    shutil.copytree(source, target, symlinks=True)
    if os.geteuid() != 0:
        return
    for directory, folders, files in os.walk(source):
        here = Path(directory)
        for name in [".", *folders, *files]:
            original = here / name
            copy = target / original.relative_to(source)
            status = original.lstat()
            os.lchown(copy, status.st_uid, status.st_gid)


def put_back(install: str | Path, aside: str | Path) -> list[str]:
    """Undo ``restore``: the state set aside goes back in place (what was restored is removed)."""

    install, aside = Path(install), Path(aside)
    returned = []
    # What the installer reported meanwhile goes back with the rest.
    for relative in CARRIED:
        current, kept = install / relative, aside / relative
        if current.is_dir() and kept.parent.is_dir():
            shutil.rmtree(kept, ignore_errors=True)
            copy_owned(current, kept)
    for name in (*FOLDERS, *SETTINGS):
        kept = aside / name
        if not (kept.exists() or kept.is_symlink()):
            continue
        current = install / name
        if current.is_dir() and not current.is_symlink():
            shutil.rmtree(current)
        elif current.exists() or current.is_symlink():
            current.unlink()
        kept.rename(current)
        returned.append(name)
    return returned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m plantcraft.ops.snapshot")
    commands = parser.add_subparsers(dest="command", required=True)
    take_cli = commands.add_parser("take")
    take_cli.add_argument("install")
    take_cli.add_argument("out")
    take_cli.add_argument("--reason", required=True)
    take_cli.add_argument("--extra")
    take_cli.add_argument("--context", help="a JSON file merged into the manifest")
    verify_cli = commands.add_parser("verify")
    verify_cli.add_argument("folder")
    restore_cli = commands.add_parser("restore")
    restore_cli.add_argument("folder")
    restore_cli.add_argument("install")
    restore_cli.add_argument("aside")
    back_cli = commands.add_parser("put-back")
    back_cli.add_argument("install")
    back_cli.add_argument("aside")
    args = parser.parse_args(argv)
    try:
        if args.command == "take":
            context = json.loads(Path(args.context).read_text("utf-8")) if args.context else {}
            manifest = take(args.install, args.out, reason=args.reason, extra=args.extra,
                            context=context)  # fmt: skip
            result: dict[str, Any] = {"state": "ok", "name": manifest["name"],
                                      "size": manifest["archive"]["size"]}  # fmt: skip
        elif args.command == "verify":
            problems = verify(args.folder)
            result = {"state": "failed" if problems else "ok", "problems": problems}
        elif args.command == "restore":
            result = {"state": "ok", **restore(args.folder, args.install, args.aside)}
        else:
            result = {"state": "ok", "returned": put_back(args.install, args.aside)}
    except SnapshotError as exc:
        result = {"state": "failed", "message": str(exc)}
    print(json.dumps(result))
    return 0 if result["state"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
