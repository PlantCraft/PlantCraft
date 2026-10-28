"""The part of the plant a person sees (PlantCraft's docs/asset-scope.md, decision D2): their
token's claim ``assets`` names the roots of the asset tree they see. Analytics answers them only
about the loops, signals and assets under those roots; what is outside reads as not found.

A loop read from PlantCraft is the asset of the same id. A loop defined here is seen when every
signal it reads is. A run's subject (its ``loop_id``) is a loop, an asset or a signal; a run on
no subject (a round, a replay) stays visible.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException
from plantcraft_sdk.asset_scope import AssetScope
from plantcraft_sdk.server.access import CurrentUser

from linkcraft.api.deps import RuntimeDep

# The subjects of a run that are no part of the plant (a round, a replay over every loop).
NO_SUBJECT = {"", "*"}


def asset_scope(user: CurrentUser, rt: RuntimeDep) -> AssetScope:
    return rt.asset_scope(user)


Scope = Annotated[AssetScope, Depends(asset_scope)]


def loop_signals(loop: Any) -> list[str]:
    signals = getattr(loop, "signals", None)
    if signals is None:
        return []
    return [value for value in signals.model_dump().values() if isinstance(value, str) and value]


def sees_loop(scope: AssetScope, rt: Any, loop_id: str, loop: Any = None) -> bool:
    if scope.everything or scope.asset(loop_id):
        return True
    loop = loop if loop is not None else rt.loops.get_loop(loop_id)
    found = loop_signals(loop)
    return bool(found) and scope.all_signals(found)


def sees_subject(scope: AssetScope, rt: Any, subject: str | None) -> bool:
    """A run's or a row's subject: a loop, an asset or a signal id (or ``asset:``/``signal:``)."""

    if scope.everything or str(subject or "") in NO_SUBJECT:
        return True
    subject = str(subject)
    if subject.partition(":")[0] in ("asset", "signal"):
        return scope.subject(subject)
    return scope.asset(subject) or scope.signal(subject) or sees_loop(scope, rt, subject)


def sees_job(scope: AssetScope, rt: Any, job: dict[str, Any]) -> bool:
    return sees_subject(scope, rt, job.get("loop_id"))


def require(found: bool, detail: str) -> None:
    """404 for what lies outside the person's part of the plant, as for what is not here."""

    if not found:
        raise HTTPException(status_code=404, detail=detail)


def paged(
    scope: AssetScope, rt: Any, rows: list[dict[str, Any]], limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """Runs the person sees, one page of them and how many in all."""

    kept = [row for row in rows if sees_job(scope, rt, row)]
    return kept[offset : offset + limit], len(kept)


__all__ = [
    "Scope",
    "loop_signals",
    "paged",
    "require",
    "sees_job",
    "sees_loop",
    "sees_subject",
]
