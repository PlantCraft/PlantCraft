"""Operations › Logs: the logs of every server of the suite, in one list, with filters.

Each server reads its own file back (``GET /api/ops/logs``, :mod:`plantcraft_sdk.server.logread`)
with a short token of the ``ops`` scope, the same way the recorder reads the metrics; PlantCraft
reads its own in-process. The servers are asked in parallel, each with the same filters and
limit, and the answers are merged newest first and cut at the limit. A server that is down or
does not answer is named in ``missing`` (its records are still on its disk, and in the
diagnostic bundle), never an error of the whole read. ``top`` counts the messages that come back
most often among the records found (numbers and ids folded, so ``worker 3 killed`` and ``worker
7 killed`` are one line), the first thing to look at when a server logs a burst of errors.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import httpx

from plantcraft_sdk.server import logread
from plantcraft_sdk.server.logs import current_file

OWN = "processcraft"
TOKEN_SECONDS = 60
TOP = 10
# Numbers, hex ids and quoted values vary between lines that say the same thing.
_VARIES = re.compile(r"0x[0-9a-f]+|\b[0-9a-f]{8,}\b|\d+(?:[.,]\d+)?|'[^']*'|\"[^\"]*\"", re.I)


def shape(message: str) -> str:
    """A message with what varies between lines folded to ``#``."""

    return _VARIES.sub("#", message.strip())[:160]


class SuiteLogs:
    def __init__(
        self,
        issuer: Any,
        urls: dict[str, str],
        *,
        running: Callable[[], set[str] | None] = lambda: None,
        own_file: Callable[[], Any] = current_file,
        http: httpx.Client | None = None,
    ):
        """``urls`` are the servers (``plantcraft.watch.recorder.server_urls``); ``running``
        names the services Docker runs (None: unknown, ask them all)."""

        self.issuer = issuer
        self.urls = urls
        self.running = running
        self.own_file = own_file
        self.http = http or httpx.Client(timeout=8.0)

    def services(self) -> list[str]:
        """The servers whose logs can be read, PlantCraft first."""

        running = self.running()
        others = sorted(name for name in self.urls if running is None or name in running)
        return [OWN, *others]

    def _remote(self, service: str, params: dict[str, Any]) -> dict[str, Any] | None:
        token, _ = self.issuer.issue(
            "app:processcraft",
            ttl=TOKEN_SECONDS,
            audience=service,
            name="PlantCraft monitor",
            apps={service: "viewer"},
            scope="ops",
        )
        try:
            response = self.http.get(
                f"{self.urls[service]}/api/ops/logs",
                params={key: value for key, value in params.items() if value not in (None, "")},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None  # an app older than this route answers 404: its logs are not read here
        try:
            body = response.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def read(
        self,
        *,
        services: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        level: str | None = None,
        text: str | None = None,
        request_id: str | None = None,
        logger: str | None = None,
        limit: int = logread.DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        known = self.services()
        wanted = [name for name in (services or known) if name in known]
        limit = max(1, min(int(limit), logread.MAX_LIMIT))
        params = {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "level": level,
            "text": text,
            "request_id": request_id,
            "logger": logger,
            "limit": limit,
        }
        answers: dict[str, dict[str, Any] | None] = {}
        remote = [name for name in wanted if name != OWN]
        if remote:
            with ThreadPoolExecutor(max_workers=min(8, len(remote))) as pool:
                for name, answer in zip(
                    remote, pool.map(lambda name: self._remote(name, params), remote), strict=True
                ):
                    answers[name] = answer
        if OWN in wanted:
            answers[OWN] = logread.read_logs(
                self.own_file(),
                since=since,
                until=until,
                level=level,
                text=text,
                request_id=request_id,
                logger=logger,
                limit=limit,
            )
        records: list[dict[str, Any]] = []
        truncated = False
        for name, answer in answers.items():
            if answer is None:
                continue
            truncated = truncated or bool(answer.get("truncated"))
            for item in answer.get("records") or []:
                if isinstance(item, dict):
                    records.append({**item, "service": name})
        records.sort(key=lambda item: str(item.get("time") or ""), reverse=True)
        if len(records) > limit:
            records, truncated = records[:limit], True
        top = Counter(
            (item["service"], str(item.get("level") or ""), shape(str(item.get("message") or "")))
            for item in records
            if str(item.get("level") or "") in ("WARNING", "ERROR", "CRITICAL")
        )
        return {
            "records": records,
            "truncated": truncated,
            "services": known,
            "read": sorted(name for name, answer in answers.items() if answer is not None),
            "missing": sorted(name for name, answer in answers.items() if answer is None),
            "top": [
                {"service": service, "level": level_name, "message": message, "count": count}
                for (service, level_name, message), count in top.most_common(TOP)
            ],
        }
