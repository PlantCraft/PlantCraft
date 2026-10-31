"""Files written whole or not at all (standard library only), for every app and the platform.

``Path.write_text`` writes over the old file in place: a process killed in the middle leaves
half a file, which reads as broken JSON from then on (71 of 100 kills in the storage test of
2026-10-31, ``ci/bench/storage/crash_test.py``). ``write_atomic`` writes the bytes to a hidden
temporary file beside the target, created with its final mode (a secret is never readable by
others on the way, whatever the umask), makes them reach the disk (``fsync``), and renames it
over the target. A reader (another worker process, a folder watcher) finds the old file or the
new one, never half of one.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

__all__ = ["write_atomic", "write_json"]


def write_atomic(path: str | Path, data: str | bytes, *, mode: int | None = None) -> None:
    """Replace ``path`` with ``data`` (text is UTF-8) in one step.

    ``mode``: the file's permissions (``0o600`` for a secret); None gives a new file's usual
    ones (``0o666`` less the umask). The temporary file is hidden and unique
    (``.<name>.<random>.partial``), so two processes writing the same file never share it and
    a watcher's ``*.json`` never matches it.
    """

    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.partial")
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else mode
    )
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data.encode("utf-8") if isinstance(data, str) else data)
            file.flush()
            os.fsync(file.fileno())
        if mode is not None:
            os.chmod(temporary, mode)  # the umask may have narrowed it
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: str | Path, value: Any, *, mode: int | None = None, **dumps: Any) -> None:
    """``value`` as JSON in ``path``, in one step (``write_atomic``); ``dumps`` go to
    ``json.dumps`` (``indent``, ``sort_keys``...)."""

    write_atomic(path, json.dumps(value, **dumps), mode=mode)
