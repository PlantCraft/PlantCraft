"""Bytes in and out of the compute queue: a request body saved to a file, never past a limit."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import HTTPException, Request

from plantcraft.i18n import t


async def save_body(request: Request, target: Path, limit: int) -> int:
    """Stream the body to ``target`` (renamed in whole); 413 past ``limit`` bytes."""

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=413, detail=_too_big(limit))
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.partial")
    size = 0
    try:
        with open(partial, "wb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=_too_big(limit))
                file.write(chunk)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return size


def _too_big(limit: int) -> str:
    return t("A task holds at most {size} MB.", size=limit // (1024 * 1024))
