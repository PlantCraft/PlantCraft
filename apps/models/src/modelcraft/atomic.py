"""Files Models keeps beside its database, written whole or not at all.

A run's ``files.json`` and ``compare.json``, a result's ``names.json`` and ``variables.json`` and
the cached reading of a library model are read back after a restart. ``Path.write_text`` writes
over the old file in place: a process killed in the middle leaves half a file, which reads as
broken JSON from then on (71 of 100 kills in the storage test of 2026-10-31,
``ci/bench/storage/crash_test.py``). Here the bytes go to a hidden temporary file beside the
target, reach the disk (``fsync``), and are renamed over it, so a reader finds the old file or
the new one, never half of one. The SDK's ``plantcraft_sdk.files`` does it for every app.
"""

from __future__ import annotations

from plantcraft_sdk.files import write_atomic, write_json

__all__ = ["write_atomic", "write_json"]
