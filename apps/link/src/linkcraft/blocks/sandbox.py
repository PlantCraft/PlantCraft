"""Running the Python code of a block written on the site, away from the server.

A block file carries code people wrote (or an assistant wrote for them). It runs in the suite's
one sandbox, ``plantcraft_sdk.sandbox`` (written once: AGENTS.md, section 2), which Alarms'
Python rules and Documents' readers use too: worker processes that cannot write files or open
network connections, within a memory budget (``LINKCRAFT_BLOCK_MEMORY_MB``, default 1024 above
what they start with) and a time limit (``LINKCRAFT_BLOCK_TIMEOUT_SECONDS``, default 30), and
code checked before it runs (allowed modules, no ``_`` attributes, no ``eval`` or ``open``).

This module adds only what is a block's: the policy (``run(inputs, params, ctx)``, the modules
a block may import: the SDK's plus ``linkcraft.blocks.base``), one call as plain data
(``Call``) and what runs it in the worker (``execute``: the outputs and the block's new state).

``LINKCRAFT_BLOCK_SANDBOX=inline`` runs the checked code in the calling process, for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plantcraft_sdk import sandbox as _sandbox
from plantcraft_sdk.sandbox import (
    BASE_MODULES,
    DEFAULT_MEMORY_MB,
    DEFAULT_TIMEOUT_SECONDS,
    CodeError,
    CodePool,
    InlinePool,
    Params,
    Policy,
    compile_code,
)

from linkcraft.i18n import t

ALLOWED_MODULES = BASE_MODULES | {"linkcraft.blocks.base"}
POLICY = Policy(
    entry="run", arguments=("inputs", "params", "ctx"), modules=ALLOWED_MODULES, what="a block"
)
# LINKCRAFT_BLOCK_WORKERS, _TIMEOUT_SECONDS, _MEMORY_MB and _SANDBOX configure the pool.
PREFIX = "LINKCRAFT_BLOCK"

# The name Link's code and its callers have always caught.
BlockCodeError = CodeError


def check_code(code: str) -> list[str]:
    """What keeps ``code`` from running as a block, one sentence each (empty: it may run)."""

    return _sandbox.check_code(code, POLICY)


@dataclass
class Call:
    """One call of a block's ``run``: plain data, so it crosses to a worker process."""

    key: str
    code: str
    inputs: dict[str, Any]
    params: dict[str, Any]
    start: Any = None
    end: Any = None
    sample_seconds: float | None = None
    asset: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    node_id: str = ""


def execute(call: Call) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run ``call`` here (in a worker process, or inline): the outputs and the block's new state."""

    from plantcraft_sdk.blocks import Context, NoData, Result

    run = compile_code(call.code, POLICY, key=call.key, names={"Result": Result, "NoData": NoData})
    context = Context(
        start=call.start,
        end=call.end,
        sample_seconds=call.sample_seconds,
        asset=dict(call.asset),
        states={call.node_id: dict(call.state)},
        node_id=call.node_id,
    )
    given = run(dict(call.inputs), Params(call.params), context)
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise BlockCodeError(
            t(
                "run returned {kind}; it returns a dict with a value per output port.",
                kind=type(given).__name__,
            )
        )
    return given, context.state


def run(call: Call) -> tuple[dict[str, Any], dict[str, Any]]:
    """``call`` through this process's pool: the outputs and the block's new state."""

    return pool().run(execute, call)


def pool() -> Any:  # noqa: ANN401 - CodePool, InlinePool or the suite's RemoteCodePool
    """This process's pool for block code, started on first use."""

    return _sandbox.pool(PREFIX)


def use_pool(found: Any) -> None:  # noqa: ANN401
    """Set this process's pool (tests; ``None`` starts a new one on next use)."""

    _sandbox.use_pool(PREFIX, found)


def shutdown() -> None:
    use_pool(None)


__all__ = [
    "ALLOWED_MODULES",
    "DEFAULT_MEMORY_MB",
    "DEFAULT_TIMEOUT_SECONDS",
    "POLICY",
    "BlockCodeError",
    "Call",
    "CodePool",
    "InlinePool",
    "Params",
    "check_code",
    "execute",
    "pool",
    "run",
    "shutdown",
    "use_pool",
]
