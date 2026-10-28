"""Blocks written on the site: a block file (``blocks.files``) turned into a block of the catalog.

Every saved version is one block of the catalog, under its pinned id
(``custom.ua_drift.v3``), and its file is kept as ``<data dir>/blocks/<pinned id>.json``. The
files are immutable, so any process (the compute workers too) can load a version it has not
seen yet from that folder (``load``), and the catalog does that on its own (``catalog.Catalog``).
A draft being tested is kept the same way under ``drafts/``, named by its content.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from plantcraft_sdk.blocks import Block, NoData, Result

from linkcraft.blocks import sandbox
from linkcraft.blocks.files import BlockFile, read_file, spec_of, split_pinned
from linkcraft.i18n import t

LOGGER = logging.getLogger(__name__)
FOLDER_VARIABLE = "LINKCRAFT_BLOCKS_DIR"
DRAFT_LIBRARY = "draft"


def folder() -> Path | None:
    value = os.environ.get(FOLDER_VARIABLE, "").strip()
    return Path(value) if value else None


def set_folder(path: Path) -> None:
    """Where versions are kept; in the environment, so the worker processes see it too."""

    path.mkdir(parents=True, exist_ok=True)
    (path / "drafts").mkdir(exist_ok=True)
    os.environ[FOLDER_VARIABLE] = str(path)


def _checked_output(port_type: str, value: Any, port: str) -> Any:  # noqa: ANN401
    if isinstance(value, NoData):
        return value
    if value is None:
        return NoData(t("The block gave no {port}.", port=port))
    if port_type in ("series", "state", "intervals"):
        if not isinstance(value, pd.Series):
            raise sandbox.BlockCodeError(
                t(
                    "{port} must be a pandas Series (got {kind}).",
                    port=port,
                    kind=type(value).__name__,
                )
            )
        if port_type == "intervals":
            return value.fillna(False).astype(bool)
        return value
    if port_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise sandbox.BlockCodeError(t("{port} must be a number.", port=port)) from exc
    if port_type == "result":
        if isinstance(value, Result):
            return value
        if isinstance(value, dict) and "status" in value:
            return Result(
                str(value.get("status")),
                value.get("value"),
                str(value.get("message") or ""),
                str(value.get("label") or ""),
            )
        raise sandbox.BlockCodeError(t("{port} must be a Result.", port=port))
    return value


def code_block(file: BlockFile, block_id: str) -> Block:
    """The catalog block that runs ``file``'s code in the block workers."""

    spec = spec_of(file, block_id)
    types = {port.port_id: port.type for port in spec.outputs}
    key = file.code_key()
    code = file.code

    def run(inputs: dict[str, Any], parameters: Any, ctx: Any) -> dict[str, Any]:  # noqa: ANN401
        call = sandbox.Call(
            key=key,
            code=code,
            inputs=inputs,
            params=parameters.model_dump()
            if hasattr(parameters, "model_dump")
            else dict(parameters or {}),
            start=ctx.start,
            end=ctx.end,
            sample_seconds=ctx.sample_seconds,
            asset=dict(ctx.asset or {}),
            state=dict(ctx.state),
            node_id=ctx.node_id,
        )
        given, state = sandbox.pool().run(call)
        ctx.state.clear()
        ctx.state.update(state or {})
        unknown = sorted(set(given) - set(types))
        if unknown:
            raise sandbox.BlockCodeError(
                t(
                    "run returned ports the block does not declare: {ports}.",
                    ports=", ".join(unknown),
                )
            )
        return {port: _checked_output(types[port], value, port) for port, value in given.items()}

    return Block(spec, run)


DRAFT = re.compile(rf"^{DRAFT_LIBRARY}\.d[0-9a-f]{{16}}$")


def path_of(block_id: str) -> Path | None:
    """The file of a pinned version or a draft; ``None`` for any other id (never a path from
    arbitrary text)."""

    base = folder()
    if base is None:
        return None
    if DRAFT.match(block_id):
        return base / "drafts" / f"{block_id}.json"
    if split_pinned(block_id):
        return base / f"{block_id}.json"
    return None


def write(block_id: str, file: BlockFile) -> None:
    path = path_of(block_id)
    if path is None:
        return
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(".tmp")
    scratch.write_text(
        json.dumps(file.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    scratch.replace(path)


def load(block_id: str) -> Block | None:
    """A version (or draft) from the blocks folder, or ``None``."""

    path = path_of(block_id)
    if path is None or not path.is_file():
        return None
    try:
        return code_block(read_file(path.read_text(encoding="utf-8")), block_id)
    except (OSError, ValueError) as exc:
        LOGGER.warning("Block file %s is not readable: %s", path, exc)
        return None


def draft_id(file: BlockFile) -> str:
    """The id a draft is tested under: the same content, the same id."""

    digest = hashlib.sha256(
        json.dumps(file.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    return f"{DRAFT_LIBRARY}.d{digest[:16]}"


__all__ = ["code_block", "draft_id", "folder", "load", "path_of", "set_folder", "write"]
