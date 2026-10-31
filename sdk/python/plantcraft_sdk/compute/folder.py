"""The job folder: how a task travels, and how a worker's gateway and an executor share it.

A task is a **folder of files** (``job.json`` and whatever the app adds), sent as a tar archive.
Its answer is ``result.json`` and the files under ``out/``, sent back the same way. On a worker,
the gateway and each app's executor share one folder per app, the protocol PlantCraft Models'
runner has used from the start::

    <jobs>/<app>/queue/<id>/    a task, renamed in whole by the gateway (job.json, task.json, files)
    <jobs>/<app>/work/<id>/     claimed by the executor (an atomic rename)
    <jobs>/<app>/work/<id>/cancel   written by the gateway: stop this task
    <jobs>/<app>/done/<id>/     the answer (result.json, out/), renamed in when complete
    <jobs>/<app>/runner.json    the executor's heartbeat: app, version, workers, at

An executor of another **environment** than ``standard`` (the app's image with more packages,
docs/compute.md) has its own folder, ``<jobs>/<app>.<environment>/``.

``task.json`` is the gateway's: the task id, its time and memory limits. Archives are read with
care in both directions (``unpack``): only plain files and folders, no link, no absolute path, no
``..``, a ceiling on the size and on the number of files. An answer comes from code people wrote,
so ``pack_answer`` never follows a link out of the job's folder.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
import time
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from plantcraft_sdk import files

PROTOCOL = 1
QUEUE, WORK, DONE = "queue", "work", "done"
HEARTBEAT = "runner.json"
TASK = "task.json"
JOB = "job.json"
RESULT = "result.json"
CANCEL = "cancel"
OUT = "out"
# An executor whose heartbeat is older than this is not running.
STALE_SECONDS = 60.0
MAX_FILES = 10_000
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


# Where a task may run (docs/compute.md): an executor's environment, and a size the worker's
# machine must have room for (CPUs and memory, as its gateway reports them).
DEFAULT_ENVIRONMENT = "standard"
DEFAULT_SIZE = "small"
SIZES: dict[str, dict[str, int]] = {
    "small": {"cpus": 1, "memory_mb": 1024},
    "medium": {"cpus": 2, "memory_mb": 4096},
    "large": {"cpus": 4, "memory_mb": 16384},
}
# A machine reports a little less memory than it has (the kernel's share).
MEMORY_MARGIN = 0.9


def environment_name(value: object) -> str:
    """An environment's name (letters, digits, ``-``; ``standard`` when empty), or ``""``."""

    text = str(value or "").strip().lower() or DEFAULT_ENVIRONMENT
    ok = len(text) <= 40 and text[0].isalnum() and all(c.isalnum() or c == "-" for c in text)
    return text if ok else ""


def executor_name(app: str, environment: str | None = None) -> str:
    """The executor's folder under a worker's jobs: ``<app>`` or ``<app>.<environment>``."""

    environment = environment_name(environment)
    return app if environment in ("", DEFAULT_ENVIRONMENT) else f"{app}.{environment}"


def size_name(value: object) -> str:
    text = str(value or "").strip().lower() or DEFAULT_SIZE
    return text if text in SIZES else ""


def fits(stats: Mapping[str, Any] | None, size: str, limit_mb: Any = None) -> bool:  # noqa: ANN401
    """Whether a machine with these numbers (``cpus``, ``memory_mb``) has room for ``size``,
    and the executor's own memory per task (``limit_mb``, when it says) too. A machine that
    said nothing about itself takes small tasks only."""

    need = SIZES.get(size_name(size) or DEFAULT_SIZE, SIZES[DEFAULT_SIZE])
    if size_name(size) == DEFAULT_SIZE:
        return True
    stats = stats or {}
    try:
        cpus = float(stats.get("cpus") or 0)
        memory = float(stats.get("memory_mb") or 0)
    except (TypeError, ValueError):
        return False
    try:
        limit = float(limit_mb) if limit_mb else None
    except (TypeError, ValueError):
        limit = None
    if limit is not None and limit < need["memory_mb"] * MEMORY_MARGIN:
        return False
    return cpus >= need["cpus"] and memory >= need["memory_mb"] * MEMORY_MARGIN


def largest_size(stats: Mapping[str, Any] | None, limit_mb: Any = None) -> str:  # noqa: ANN401
    return [name for name in SIZES if fits(stats, name, limit_mb)][-1]


class ArchiveError(ValueError):
    """An archive that is not a job folder (or is too big), with the reason."""


def pack(files: Mapping[str, bytes | str]) -> bytes:
    """A job folder from ``{relative path: content}`` as a compressed tar archive."""

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=3) as archive:
        for name, content in sorted(files.items()):
            path = _safe_name(name)
            data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
            info = tarfile.TarInfo(str(path))
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def pack_folder(
    folder: Path, names: list[str] | None = None, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> bytes:
    """``folder`` (or only ``names`` in it) as a compressed tar archive: plain files only, and
    never a file reached through a link."""

    root = folder.resolve()
    files: dict[str, bytes] = {}
    total = 0
    tops = [root / name for name in names] if names is not None else [root]
    for top in tops:
        if top.is_symlink() or not top.exists():
            continue
        walk = [top] if top.is_file() else sorted(_walk(top))
        for path in walk:
            if path.is_symlink() or not path.is_file():
                continue
            if root not in path.resolve().parents:
                continue
            total += path.stat().st_size
            if total > max_bytes or len(files) >= MAX_FILES:
                raise ArchiveError(f"the answer is larger than {max_bytes // (1024 * 1024)} MB")
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return pack(files)


def _walk(top: Path) -> list[Path]:
    found = []
    for directory, folders, names in os.walk(top, followlinks=False):
        folders[:] = [name for name in folders if not (Path(directory) / name).is_symlink()]
        found += [Path(directory) / name for name in names]
    return found


def pack_answer(job_dir: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> bytes:
    """What goes back to the app: ``result.json`` and ``out/``."""

    return pack_folder(job_dir, [RESULT, OUT], max_bytes=max_bytes)


def _safe_name(name: str) -> PurePosixPath:
    path = PurePosixPath(str(name).replace("\\", "/"))
    if (
        not str(name)
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or len(str(path)) > 300
    ):
        raise ArchiveError(f"{name!r} is not a file name inside a job folder")
    return path


def _members(data: bytes, max_bytes: int) -> list[tuple[PurePosixPath, tarfile.TarInfo]]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ArchiveError(f"not a tar archive ({exc})") from exc
    found = []
    total = 0
    with archive:
        for member in archive:
            if len(found) >= MAX_FILES:
                raise ArchiveError("too many files")
            if not (member.isfile() or member.isdir()):
                raise ArchiveError(f"{member.name!r} is not a plain file")
            path = _safe_name(member.name.rstrip("/"))
            total += max(0, member.size)
            if total > max_bytes:
                raise ArchiveError(f"larger than {max_bytes // (1024 * 1024)} MB")
            found.append((path, member))
    return found


def unpack(data: bytes, target: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> list[str]:
    """Write the archive's plain files under ``target``; the names written."""

    members = _members(data, max_bytes)
    written = []
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for path, member in members:
            destination = target.joinpath(*path.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                continue
            with open(destination, "wb") as file:
                shutil.copyfileobj(source, file)
            written.append(path.as_posix())
    return written


def read(data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, bytes]:
    """The archive's plain files in memory: ``{relative path: bytes}``."""

    members = _members(data, max_bytes)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        for path, member in members:
            if member.isfile():
                source = archive.extractfile(member)
                files[path.as_posix()] = source.read() if source else b""
    return files


# The folder a gateway and an executor share ---------------------------------------------------


def prepare(app_dir: Path) -> None:
    for name in (QUEUE, WORK, DONE):
        (app_dir / name).mkdir(parents=True, exist_ok=True)


def write_json(path: Path, value: Any) -> None:
    """``value`` in ``path`` whole or not at all (``plantcraft_sdk.files``)."""

    files.write_json(path, value)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def heartbeat(app_dir: Path) -> dict[str, Any] | None:
    """The executor's last heartbeat, if it is fresh."""

    found = read_json(app_dir / HEARTBEAT)
    if not found:
        return None
    try:
        at = float(found.get("at") or 0)
    except (TypeError, ValueError):
        return None
    return found if time.time() - at < STALE_SECONDS else None


__all__ = [
    "CANCEL",
    "DEFAULT_ENVIRONMENT",
    "DEFAULT_SIZE",
    "DONE",
    "HEARTBEAT",
    "JOB",
    "OUT",
    "PROTOCOL",
    "QUEUE",
    "RESULT",
    "SIZES",
    "TASK",
    "WORK",
    "ArchiveError",
    "environment_name",
    "executor_name",
    "fits",
    "heartbeat",
    "largest_size",
    "pack",
    "pack_answer",
    "pack_folder",
    "prepare",
    "read",
    "read_json",
    "size_name",
    "unpack",
    "write_json",
]
