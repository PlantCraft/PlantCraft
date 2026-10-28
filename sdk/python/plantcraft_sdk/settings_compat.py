"""Settings named before the rename to PlantCraft (2026-10-27) are still read.

Every setting was ``PROCESSCRAFT_<NAME>`` until then; it is ``PLANTCRAFT_<NAME>`` now. An
installation's ``.env`` is renamed by ``install.sh`` on upgrade, but a compose file written by an
older release keeps passing the old names, so each process copies them to the new ones when it
starts (this module runs on the first import of ``plantcraft_sdk``, and PlantCraft's own package
calls it too). The old name wins over a new one already set: the images set their defaults under
the new names (``ENV PLANTCRAFT_URL=...``), so beside an old name the new one is only that default,
and a compose file written after the rename passes no old names. ``PLANTCRAFT_VERSION`` in an old
``.env`` was even the Simulator's version (before its 0.5.0).
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

FORMER = "PROCESSCRAFT_"
CURRENT = "PLANTCRAFT_"


def adopt(environ: MutableMapping[str, str] | None = None) -> list[str]:
    """Copy every ``PROCESSCRAFT_*`` setting to its ``PLANTCRAFT_*`` name; the names copied."""

    env = os.environ if environ is None else environ
    adopted = []
    for key in [key for key in env if key.startswith(FORMER)]:
        new = CURRENT + key[len(FORMER) :]
        if env.get(new) != env[key]:
            env[new] = env[key]
            adopted.append(new)
    return adopted
