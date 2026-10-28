"""What a run may be: its kinds and states."""

from __future__ import annotations

KINDS = ("simulate", "fmu")
STATUSES = ("queued", "running", "done", "failed", "cancelled")
FINISHED = ("done", "failed", "cancelled")
# Quick simulations go ahead of the simulations of a sweep.
