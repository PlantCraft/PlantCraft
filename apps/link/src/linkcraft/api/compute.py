"""The blocks' side of the suite's compute workers, and the executor's handler (docs/compute.md).

``RemoteCodePool`` takes the place of the block workers (``blocks.sandbox.CodePool``) for the
diagrams that run in this container: the editor's Test and the runs on assets. Each call of a
block's code goes to a worker through the ``SuitePool``. ``site_blocks`` gives each task the
files of the site's block versions its diagrams use, since a worker has no blocks folder.

``answer`` is the handler of ``linkcraft-executor``::

    python -m plantcraft_sdk.compute executor --app linkcraft \\
        --handler linkcraft.api.compute:answer

It runs each item of a task through the function the task names (one of
``suite_compute.CALLS``, nothing else) and writes the answers to ``out/answers.json``.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import tempfile
from collections.abc import Callable, Iterator
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from plantcraft_sdk.files import write_atomic, write_json

from linkcraft.blocks import sandbox, site
from linkcraft.engine.suite_compute import ANSWERS, CALLS, ComputeTaskError, SuitePool
from linkcraft.engine.wire import decode, encode
from linkcraft.i18n import t

# How long a block's code may wait in the queue beyond its own time limit.
QUEUE_MARGIN_SECONDS = 120.0


class RemoteCodePool:
    """``blocks.sandbox.CodePool``'s interface: each call of a block's code runs on a worker."""

    crashes = 0

    def __init__(self, pool: SuitePool, timeout: float):
        self.pool = pool
        self.timeout = float(timeout)

    def run(self, call: sandbox.Call) -> tuple[dict[str, Any], dict[str, Any]]:
        future = self.pool.submit(run_block_code, dataclasses.asdict(call))
        try:
            given, state = future.result(timeout=self.timeout + QUEUE_MARGIN_SECONDS)
        except FutureTimeout as exc:
            future.cancel()
            raise sandbox.BlockCodeError(
                t(
                    "The block's code did not finish in {seconds} s and was stopped.",
                    seconds=f"{self.timeout:g}",
                )
            ) from exc
        except ComputeTaskError as exc:
            raise sandbox.BlockCodeError(str(exc)) from exc
        return given, state

    def shutdown(self) -> None:
        return None


def _strings(value: Any) -> Iterator[str]:  # noqa: ANN401
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def site_blocks(arguments: list[Any]) -> dict[str, Any]:
    """``{"blocks": {pinned id: file}}`` for the site's block versions the items' diagrams use
    (immutable, by their pinned id); nothing when they use none."""

    found: dict[str, str] = {}
    for argument in arguments:
        diagram = argument.get("diagram") if isinstance(argument, dict) else None
        for text in _strings(diagram):
            if text in found or len(text) > 200:
                continue
            path = site.path_of(text)
            if path is not None and path.is_file():
                found[text] = path.read_text(encoding="utf-8")
    return {"blocks": found} if found else {}


# On the worker -------------------------------------------------------------------------------


def run_block_code(fields: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """A block's code, on the worker (already in a sandbox: run here, not in another process)."""

    return sandbox.execute(sandbox.Call(**fields))


def _function(name: str) -> Callable[[Any], Any]:
    if name not in CALLS:
        raise ValueError(f"{name} does not run on the suite's compute workers")
    module, _, attribute = name.partition(":")
    return getattr(importlib.import_module(module), attribute)


def _keep_blocks(blocks: dict[str, str]) -> None:
    """The site's block versions a task carries, in this worker's own blocks folder."""

    if not blocks:
        return
    if site.folder() is None:
        site.set_folder(Path(tempfile.gettempdir()) / "linkcraft-blocks")
    for block_id, text in blocks.items():
        path = site.path_of(str(block_id))  # a pinned id or a draft's, never a path
        if path is None or path.is_file():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, str(text))


def answer(job_dir: Path) -> None:
    """The executor's handler: each item of ``job.json`` through its function, in order."""

    # The executor's process is the sandbox: blocks' code runs in it, not in more processes.
    if not isinstance(sandbox.pool(), sandbox.InlinePool):
        sandbox.use_pool(sandbox.InlinePool())
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    function = _function(str(job.get("call")))
    _keep_blocks(job.get("blocks") or {})
    answers: list[dict[str, Any]] = []
    for item in job.get("items") or []:
        try:
            answers.append({"ok": True, "value": encode(function(decode(item)))})
        except Exception as exc:  # noqa: BLE001 - each item answers alone
            if isinstance(exc, sandbox.BlockCodeError):
                error = str(exc)
            else:
                error = f"{type(exc).__name__}: {exc}"
            answers.append({"ok": False, "error": error[:4000]})
    out = job_dir / "out"
    out.mkdir(exist_ok=True)
    write_json(out / ANSWERS, answers, separators=(",", ":"))


__all__ = ["ANSWERS", "RemoteCodePool", "answer", "run_block_code", "site_blocks"]
