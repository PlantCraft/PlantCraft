"""Files written whole or not at all, never readable by others on the way (standard library only).

A reader (another worker process, the installer watching a folder) sees the old file or the new
one, never half of one: the bytes go to a temporary file beside the target, created with its
final mode, then renamed over it. Creating it with the mode, rather than writing it and then
``chmod``, keeps a secret from being readable by others for a moment, whatever the umask.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

__all__ = ["write_atomic"]


def write_atomic(path: str | Path, data: str | bytes, *, mode: int = 0o600) -> None:
    """Replace ``path`` with ``data`` (text is UTF-8), readable as ``mode`` says.

    The temporary file is hidden and unique (``.<name>.<random>.partial``), so two processes
    writing the same file never share it and a folder watcher's ``*.json`` never matches it.
    """

    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.partial")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.chmod(temporary, mode)  # the umask may have narrowed it
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
