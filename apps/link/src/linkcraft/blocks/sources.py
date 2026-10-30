"""The code behind a block Link ships, as people read it on the block's Code tab, and the copy
a site block starts from when someone duplicates a shipped one."""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from typing import Any

from plantcraft_sdk.blocks import Block

from linkcraft.blocks.catalog import method_of
from linkcraft.blocks.files import DEFAULT_LIBRARY, file_of_spec, slug
from linkcraft.catalog.registry import get_method_module
from linkcraft.catalog.signal_checks import CHECKS as SIGNAL_CHECKS
from linkcraft.i18n import t

PACKAGE_DIR = Path(__file__).resolve().parents[1]
# Libraries whose blocks run from their inputs alone, so a copy can start by running the original.
COPYABLE = frozenset({"dq", "transform", "stats", "equipment", "logic", "cpm"})


def _relative(path: Path | None, fallback: str) -> str:
    if path is None:
        return fallback
    try:
        return str(path.resolve().relative_to(PACKAGE_DIR.parent))
    except ValueError:
        return path.name


def _readable(source: str) -> str:
    """A function's source as people read it: no decorator, and a lambda written as a def."""

    source = textwrap.dedent(source).strip()
    if source.startswith("@"):
        lines = source.splitlines()
        first = next((n for n, line in enumerate(lines) if line.startswith("def ")), 0)
        source = "\n".join(lines[first:])
    if source.startswith("lambda"):
        node = None
        text = source.rstrip(", \n")
        while text and node is None:  # the lambda may close its caller's parentheses too
            try:
                node = ast.parse(text, mode="eval").body
            except SyntaxError:
                text = text[:-1].rstrip(", \n")
        if isinstance(node, ast.Lambda):
            return (
                f"def calculate({ast.unparse(node.args)}):\n    return {ast.unparse(node.body)}\n"
            )
    return source + "\n"


def _function_source(function: Any) -> tuple[Path | None, str, int]:  # noqa: ANN401
    """A function's own source (not its whole module), the file it is in and its first line."""

    function = inspect.unwrap(getattr(function, "function", function))  # an SDK method's function
    lines, first = inspect.getsourcelines(function)
    path_text = inspect.getsourcefile(function)
    return (Path(path_text) if path_text else None), _readable("".join(lines)), int(first or 1)


def _calculation(block: Block) -> Any:  # noqa: ANN401
    """The function that calculates a shipped block: its method's ``run``, its check, or the
    function its library wraps (``compute``); the block's own ``run`` when there is none."""

    spec = block.spec
    method_id = method_of(spec.block_id)
    if method_id:
        try:
            module = get_method_module(method_id)
        except KeyError:
            module = None
        if module is not None and callable(getattr(module, "run", None)):
            return module.run
    check_id = spec.block_id.removeprefix("dq.") if spec.block_id.startswith("dq.") else None
    for key in (f"sq_{check_id}", check_id) if check_id else ():
        if key in SIGNAL_CHECKS:
            return SIGNAL_CHECKS[key]
    for cell in getattr(block.run, "__closure__", None) or ():
        value = cell.cell_contents
        if inspect.isfunction(value) and value.__module__.startswith("linkcraft."):
            return value
    return block.run


def shipped_sources(block: Block) -> list[dict[str, Any]]:
    """The calculation of a shipped block, alone: the one function that turns its inputs and
    parameters into its outputs (one code, isolated and easy to read; the
    block's declaration is its contract, on the Overview)."""

    spec = block.spec
    try:
        path, source, first = _function_source(_calculation(block))
    except (OSError, TypeError):
        return []
    return [
        {
            "title": t("Calculation"),
            "filename": _relative(path, f"{spec.library}.py"),
            "source": source,
            "line": 1,
            "first_line": first,
        }
    ]


def copy_code(block_id: str, name: str) -> str:
    return (
        f'"""Copy of {name} ({block_id}), a block Link ships.\n\n'
        "It starts by running the original and returning its outputs; change it as you need.\n"
        "The original's code is on its Code tab.\n"
        '"""\n'
        "from linkcraft.blocks.base import shipped\n\n\n"
        "def run(inputs, params, ctx):\n"
        f'    outputs = shipped("{block_id}", inputs, params, ctx)\n'
        "    return outputs\n"
    )


def edit_code(block_id: str, name: str) -> str:
    return (
        f'"""{name} ({block_id}), this site\'s version of a block Link ships.\n\n'
        "It starts by running Link's calculation (version 1, on the Code tab) and returning its\n"
        "outputs; write your own calculation here. The algorithms that use version 1 keep it.\n"
        '"""\n'
        "from linkcraft.blocks.base import shipped\n\n\n"
        "def run(inputs, params, ctx):\n"
        f'    outputs = shipped("{block_id}", inputs, params, ctx)\n'
        "    return outputs\n"
    )


def edit_file(block: Block) -> dict[str, Any]:
    """A shipped block as the start of its next version on the site, under the same id."""

    spec = block.spec
    return file_of_spec(
        spec,
        edit_code(spec.block_id, spec.name),
        block_id=spec.block_id,
        name=spec.name,
        library=spec.library,
        origin="user",
    )


def copy_file(block: Block, *, name: str | None = None) -> dict[str, Any]:
    """A shipped block as the start of a site block (not saved)."""

    spec = block.spec
    title = name or t("{name} (copy)", name=spec.name)
    return file_of_spec(
        spec,
        copy_code(spec.block_id, spec.name),
        block_id=f"{DEFAULT_LIBRARY}.{slug(title)}",
        name=title,
        library=DEFAULT_LIBRARY,
        origin="user",
    )


__all__ = ["COPYABLE", "copy_code", "copy_file", "edit_code", "edit_file", "shipped_sources"]
