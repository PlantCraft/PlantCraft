"""Lists in pages, and answers that did not change (scale review E2, 2026-10-25).

A list route of API v1 (signals, assets) can hold tens of thousands of items: 50,000 signals in
one plant. ``list_response`` gives every such route the same two answers:

- **Pages.** ``?limit=<n>`` (1 to ``MAX_PAGE``) answers the first ``n`` items in ``key`` order
  and, when more are left, an ``X-Next-Cursor`` header; ``?cursor=<that value>`` answers the
  next page. Without ``limit`` and ``cursor`` the whole list comes, as before.
- **Not modified.** Every answer has an ``ETag``; a request whose ``If-None-Match`` names it
  gets ``304`` and no body, so an app asking again for a list that did not change moves bytes
  only for the header.

The answer stays a JSON list: pages are additive to API v1. The SDK's client walks the pages
and keeps the ``ETag`` (``plantcraft_sdk.client``).
"""

from __future__ import annotations

import base64
import binascii
import bisect
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from plantcraft_sdk.contract import MAX_PAGE, NEXT_CURSOR, TOTAL_COUNT

__all__ = ["MAX_PAGE", "NEXT_CURSOR", "TOTAL_COUNT", "json_response", "list_response"]


def encode_cursor(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True).decode(
            "utf-8"
        )
    except (ValueError, binascii.Error, UnicodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor.") from exc


def etag_of(body: bytes) -> str:
    return f'W/"{hashlib.sha256(body).hexdigest()[:32]}"'


def not_modified(request: Request, etag: str) -> bool:
    wanted = request.headers.get("if-none-match") or ""
    return any(part.strip() in (etag, "*") for part in wanted.split(","))


def json_response(
    request: Request, content: Any, headers: Mapping[str, str] | None = None
) -> Response:
    """``content`` as JSON with an ``ETag``; ``304`` when the caller already holds it."""

    answer = JSONResponse(content, headers=dict(headers or {}))
    etag = etag_of(bytes(answer.body))
    if not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag, **dict(headers or {})})
    answer.headers["ETag"] = etag
    return answer


def list_response(
    request: Request,
    items: Sequence[Mapping[str, Any]],
    *,
    limit: int | None = None,
    cursor: str | None = None,
    key: str = "id",
) -> Response:
    """A list route's answer: the whole list, or one page of it in ``key`` order."""

    if limit is None and not cursor:
        return json_response(request, list(items))
    size = MAX_PAGE if limit is None else limit
    if not 1 <= size <= MAX_PAGE:
        raise HTTPException(status_code=422, detail=f"limit is 1 to {MAX_PAGE}.")
    keys = [str(item.get(key) or "") for item in items]
    if all(keys[index] <= keys[index + 1] for index in range(len(keys) - 1)):
        ordered = list(items)  # most routes answer in key order already: no sort per page
    else:
        pairs = sorted(zip(keys, items, strict=True), key=lambda pair: pair[0])
        keys, ordered = [pair[0] for pair in pairs], [pair[1] for pair in pairs]
    start = bisect.bisect_right(keys, decode_cursor(cursor)) if cursor else 0
    page = ordered[start : start + size]
    headers = {TOTAL_COUNT: str(len(items))}
    if len(ordered) > start + size:
        headers[NEXT_CURSOR] = encode_cursor(keys[start + size - 1])
    return json_response(request, list(page), headers)
