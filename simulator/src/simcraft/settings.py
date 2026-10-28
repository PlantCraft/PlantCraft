"""Settings from the environment (`SIMCRAFT_*`, listed in docs/opcua-interface.md)."""

from __future__ import annotations

import os


def env(name: str, default: str) -> str:
    """Return the variable `name` when it is set and not empty, else `default`."""

    value = os.environ.get(name)
    return value if value not in (None, "") else default
