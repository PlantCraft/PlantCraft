"""Files written whole or not at all: ``plantcraft_sdk.files``, private (``0o600``) by default.

The platform writes secrets and settings, so a file it writes is readable by its owner only
unless the caller says otherwise. See ``plantcraft_sdk.files`` for how the write stays atomic.
"""

from __future__ import annotations

from pathlib import Path

from plantcraft_sdk.files import write_atomic as _write_atomic

__all__ = ["write_atomic"]


def write_atomic(path: str | Path, data: str | bytes, *, mode: int = 0o600) -> None:
    """Replace ``path`` with ``data`` (text is UTF-8), readable as ``mode`` says."""

    _write_atomic(path, data, mode=mode)
