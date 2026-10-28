"""The Python block of a rule, run isolated (``plantcraft_sdk.sandbox``, the suite's one
sandbox): never in the server's process, without network or files, within a time and memory
budget (``ALARMCRAFT_CODE_TIMEOUT_SECONDS``, ``ALARMCRAFT_CODE_MEMORY_MB``). The function is
``check(inputs)``: ``inputs.<label>`` is the last value of each block wired to it; it answers
``True`` or ``False`` and, optionally, a sentence (``return True, "Health 42 with FIC-1002
oscillating"``). Only administrators write it (``api.routers.rules``).
"""

from __future__ import annotations

import hashlib
from typing import Any

from plantcraft_sdk.sandbox import CodeError, Params, Policy, check_code, compile_code, pool

POLICY = Policy(entry="check", arguments=("inputs",), what="a rule")
PREFIX = "ALARMCRAFT_CODE"


def problems(code: str) -> list[str]:
    """What keeps the code from running (empty when it may run)."""

    return check_code(code, POLICY)


def _evaluate(payload: dict[str, Any]) -> tuple[bool, str]:
    """In the worker: compile the person's function and call it."""

    check = compile_code(payload["code"], POLICY, key=payload["key"])
    answer = check(Params(payload["inputs"]))
    if isinstance(answer, tuple):
        verdict, message = (answer + ("",))[:2]
    else:
        verdict, message = answer, ""
    return bool(verdict), str(message or "")[:300]


def run(node_id: str, code: str, inputs: dict[str, Any]) -> tuple[bool, str]:
    """The block's answer; ``CodeError`` (or the code's own error) when it could not run."""

    found = problems(code)
    if found:
        raise CodeError("; ".join(found[:3]))
    key = hashlib.sha256(code.encode()).hexdigest()[:16]
    return pool(PREFIX).run(_evaluate, {"key": key, "code": code, "inputs": inputs})
