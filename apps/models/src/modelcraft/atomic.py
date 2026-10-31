"""Files Models keeps beside its database, written whole or not at all.

A run's ``files.json`` and ``compare.json``, a result's ``names.json`` and ``variables.json`` and
the cached reading of a library model are read back after a restart. ``Path.write_text`` writes
over the old file in place: a process killed in the middle leaves half a file, which reads as
broken JSON from then on (71 of 100 kills in the storage test of 2026-10-31,
``ci/bench/storage/crash_test.py``). Here the bytes go to a hidden temporary file beside the
target, reach the disk (``fsync``), and are renamed over it, so a reader finds the old file or
the new one, never half of one. PlantCraft's ``plantcraft.files.write_atomic`` does the same for
the platform.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

__all__ = ["write_atomic", "write_json"]


def write_atomic(path: str | Path, data: str | bytes) -> None:
    """Replace ``path`` with ``data`` (text is UTF-8) in one step."""

    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.partial")
    try:
        with open(temporary, "xb") as file:
            file.write(data.encode("utf-8") if isinstance(data, str) else data)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: str | Path, value: Any) -> None:
    """``value`` as JSON in ``path``, in one step (``write_atomic``)."""

    write_atomic(path, json.dumps(value))
