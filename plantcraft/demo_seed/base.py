"""The seed's ground: the HTTP client, the suite it talks to, its log and the plant's loops it
names."""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEMO_MAP = "plantcraft-50-loops-map.json"
VISITOR = "demo"
# The four valves the Simulator simulates with stiction, and the loops that oscillate.
STICTION_LOOPS = ["FIC-1003", "FIC-1102", "FIC-1206", "FIC-1214"]
CRITICALITY = {
    "FIC-1001": "high",
    "FIC-1003": "high",
    "PIC-1002": "high",
    "PIC-1202": "high",
    "TIC-1104": "high",
    "TIC-1209": "high",
    "LIC-1004": "medium",
    "FIC-1102": "medium",
    "PIC-1103": "medium",
}
# Averaging levels: the team gave them the surge-level protocol (hold a band, dampen the feed),
# instead of the level protocol that asks them to hold their setpoint tightly.
SURGE_LEVELS = ["LIC-1105", "LIC-1107", "LIC-1208", "LIC-1211", "LIC-1218", "LIC-1225"]


class SeedError(RuntimeError):
    pass


class _InsidePolicy(http.cookiejar.DefaultCookiePolicy):
    """Sends the session cookie over plain HTTP too: the seed talks to the containers directly,
    behind the proxy that terminates HTTPS (the cookie is ``Secure`` there)."""

    def return_ok_secure(self, cookie, request):  # noqa: ANN001
        return True


@dataclass
class Http:
    """A tiny JSON client with a cookie jar (the PlantCraft session) and a bearer token."""

    base: str
    token: str = ""
    jar: http.cookiejar.CookieJar = field(
        default_factory=lambda: http.cookiejar.CookieJar(policy=_InsidePolicy())
    )
    timeout: float = 120.0

    def __post_init__(self) -> None:
        self.base = self.base.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        ok: tuple[int, ...] = (),
        raw: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, Any]:
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", content_type)
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.status, _decode(response.read())
        except urllib.error.HTTPError as error:
            payload = _decode(error.read())
            if error.code in ok:
                return error.code, payload
            raise SeedError(
                f"{method} {self.base}{path}: {error.code} {_detail(payload)}"
            ) from None
        except urllib.error.URLError as error:
            raise SeedError(f"{method} {self.base}{path}: {error.reason}") from None

    def get(self, path: str, **kw: Any) -> Any:
        return self.call("GET", path, **kw)[1]

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("POST", path, body, **kw)[1]

    def put(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("PUT", path, body, **kw)[1]

    def patch(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("PATCH", path, body, **kw)[1]


def _decode(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")


def _detail(payload: Any) -> str:
    if isinstance(payload, dict) and "detail" in payload:
        return json.dumps(payload["detail"])[:400]
    return str(payload)[:400]


_STARTED = time.monotonic()


def log(message: str) -> None:
    # Seconds since the seed started: the install log shows which step takes the time.
    print(f"[demo +{time.monotonic() - _STARTED:.0f}s] {message}", flush=True)


def _day(ahead: int = 0) -> str:
    """A day where the plant is (``YYYY-MM-DD``), ``ahead`` days from today: the demo's to-dos,
    appointments and due dates fall on the plant's calendar, never on UTC's."""

    from datetime import datetime, timedelta

    from plantcraft.config import plant_timezone

    return (datetime.now(plant_timezone()) + timedelta(days=ahead)).date().isoformat()


def wait_until(what: str, check: Any, seconds: float, every: float = 3.0) -> Any:
    deadline = time.monotonic() + seconds
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            answer = check()
            if answer:
                return answer
        except SeedError as error:
            last = error
        time.sleep(every)
    raise SeedError(f"timed out waiting for {what}" + (f" ({last})" if last else ""))


@dataclass
class Suite:
    processcraft: str
    apps: dict[str, str]
    admin: str
    password: str
    visitor_password: str
    demo_map: Path
    wait: float = 600.0

    def session(self, username: str, password: str) -> Http:
        client = Http(self.processcraft)
        client.post("/api/login", {"username": username, "password": password})
        return client

    def app(self, session: Http, app_id: str) -> Http | None:
        base = self.apps.get(app_id)
        if not base:
            return None
        token = session.post("/api/v1/auth/token")["token"]
        return Http(base, token=token)


def _ident(item: dict[str, Any]) -> Any:
    for key in ("id", "dashboard_id", "twin_id", "schedule_id", "action_id", "conversation_id"):
        if item.get(key) is not None:
            return item[key]
    raise SeedError(f"no id in {str(item)[:200]}")


def _items(answer: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(answer, dict):
        for name in (key, "items", "results"):
            if isinstance(answer.get(name), list):
                return answer[name]
        return []
    return answer or []
