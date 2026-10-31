"""Writes the browser sends from another site are refused, as the platform does.

``SameSite=Lax`` keeps the session cookie off a form posted from an unrelated site, but a sibling
server of the company's domain (same site, other origin) may still post with it. Browsers say
where a request comes from in ``Sec-Fetch-Site``: a write with the cookie and a value other than
``same-origin`` (or ``none``, typed by the person) is refused. A request with its own bearer
token (scripts, other apps) carries no cookie risk and passes. Clients that send no
``Sec-Fetch-Site`` (old browsers, tools) pass as before.
"""

from __future__ import annotations

import json
from typing import Any

from plantcraft_sdk.i18n import t

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SAME_ORIGIN = {b"same-origin", b"none"}


class SameSiteWrites:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("method", "GET") not in SAFE_METHODS:
            headers = dict(scope.get("headers") or ())
            site = headers.get(b"sec-fetch-site", b"same-origin")
            if site not in SAME_ORIGIN and not headers.get(b"authorization"):
                body = json.dumps(
                    {"detail": t("This change must come from PlantCraft's own pages.")}
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 403,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
