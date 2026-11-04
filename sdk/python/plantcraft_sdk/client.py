"""Typed client for PlantCraft API v1 (``docs/api-v1.md``).

For a user request, forward the user's token::

    client = PlantCraftClient(os.environ["PLANTCRAFT_URL"], token=user.token)
    frame = client.series_frame(["FIC-101.PV", "FIC-101.SP"], start, end, step=60)

For background work, give the app id and its key; the client asks for a
service token and renews it before it expires::

    client = PlantCraftClient(url, app="linkcraft", key=os.environ["PLANTCRAFT_APP_KEY"])

Many signals at once take one request per 500 signals (``POST /api/v1/series``)::

    batch = client.series_many(["FIC-101.PV", "FIC-101.MODE"], start, end)
    columns, errors = client.series_many_pandas(["FIC-101.PV", "FIC-101.MODE"], start, end)

Computed series go back as derived signals of the app (``app-<app id>:<name>``), read like
any other signal; only a service token writes them::

    client.put_series([{"signal": "app-linkcraft:health.fic-101", "t": [...], "v": [...],
                        "unit": "/100", "subject": "asset:fic-101", "result": "loop_health"}])
    client.signals(app="linkcraft", subject="asset:fic-101")

Apps link through results and events, and report their runs and schedules::

    client.put_results([{"subject": "asset:fic-101", "kind": "loop_health", "status": "ok"}])
    client.results(["asset:fic-101"], kind="linkcraft.signal_quality")
    client.post_event("linkcraft.finding.opened", "asset:fic-101", summary="Valve sticks")
    client.post_events([{"kind": "linkcraft.finding.opened", "subject": "asset:fic-101"}, ...])

Signal and series reads can go straight to the Historian, which serves the same routes, shapes
and access rules as API v1 (its ``/api/v1/reads``): give ``historian_url`` or set
``PLANTCRAFT_HISTORIAN_URL`` (the suite sets it when the Historian is the data layer). The
client asks the Historian once whether it serves them, and reads through PlantCraft whenever
it does not or cannot be reached::

    client = PlantCraftClient(url, app="linkcraft", key=key, historian_url="http://histcraft:8100/hist")

Audit records carry the app id when the client knows it: given as ``app``
(kept by ``with_token``), or read from a service token (``sub: app:<id>``).

Reads are retried on connection errors and 5xx answers; every failure raises
a ``PlantCraftError`` subclass carrying the server's ``detail``.
"""

from __future__ import annotations

import json as json_module
import os
import threading
import time
from collections.abc import Mapping
from typing import Any, cast

try:
    import httpx
except ImportError:  # An app's notebook runtime (server/objects.py) reads only the errors here.
    httpx = None  # type: ignore[assignment]
from plantcraft_sdk import wire
from plantcraft_sdk._client.base import (  # noqa: F401 (the names this module has always had)
    DEMO_READS,
    LLM_TIMEOUT,
    SERIES_TIMEOUT,
    BadRequest,
    DemoVisitWrite,
    Forbidden,
    NotFound,
    PlantCraftError,
    Unauthorized,
    Unavailable,
    _demo_visit_write,
    _error,
    _expiry,
    _time,
    _token_app,
    error_for,
)
from plantcraft_sdk._client.links import (  # noqa: F401 (the names this module has always had)
    _LinksCalls,
)
from plantcraft_sdk._client.plant import (  # noqa: F401 (the names this module has always had)
    _PlantCalls,
)
from plantcraft_sdk._client.writes import (  # noqa: F401 (the names this module has always had)
    _WriteCalls,
)
from plantcraft_sdk.contract import (
    MAX_PAGE,
    NEXT_CURSOR,
    App,
    Jwk,
    Me,
    TokenGrant,
)

DEFAULT_TIMEOUT = 15.0
# Renew a service token this long before it expires.
RENEW_MARGIN_SECONDS = 120
RETRY_STATUSES = {500, 502, 503, 504}
# Lists come in pages of this many (``plantcraft_sdk.server.paging``); a server before
# SDK 0.42 answers the whole list at once, which ends the walk too.
PAGE_SIZE = MAX_PAGE
# The answers kept with their ETag, so asking again for a list that did not change is a 304
# with no body (per client: one identity, one cache).
ETAG_ENTRIES = 32
ETAG_MAX_BYTES = 64 * 2**20
# Where signal and series reads go when they skip PlantCraft (the Historian's root URL).
HISTORIAN_URL_ENV = "PLANTCRAFT_HISTORIAN_URL"
BINARY_READS_ENV = "PLANTCRAFT_BINARY_READS"
# The Historian's reads API this client speaks (``GET /api/v1/reads`` answers ``{"api": 1}``).
HISTORIAN_READS_API = 1
# After the Historian could not answer (or does not serve reads), PlantCraft serves the reads
# for this long before the Historian is asked again.
HISTORIAN_RETRY_SECONDS = 60.0


class _Historian:
    """Whether signal and series reads go straight to the Historian; shared by ``with_token``
    clients, so one probe serves every person's calls."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.state: bool | None = None  # None: not asked yet
        # The answers it writes besides JSON (``GET /api/v1/reads`` ``formats``).
        self.formats: frozenset[str] = frozenset()
        self.until = 0.0
        self.lock = threading.Lock()

    def wanted(self) -> bool | None:
        """True: read there. False: through PlantCraft for now. None: ask it first."""

        with self.lock:
            if self.state is False and time.monotonic() >= self.until:
                self.state = None
            return self.state

    def set(self, serves: bool) -> None:
        with self.lock:
            self.state = serves
            self.until = time.monotonic() + HISTORIAN_RETRY_SECONDS


class PlantCraftClient(_PlantCalls, _WriteCalls, _LinksCalls):
    """API v1 client. Thread-safe; share one per process (``with_token`` for user calls)."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        app: str | None = None,
        key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = 2,
        backoff: float = 0.3,
        http_client: httpx.Client | None = None,
        historian_url: str | None = None,
    ):
        if token is None and not (app and key):
            raise ValueError("Give a user token, or an app id and its key for a service token.")
        self.base_url = base_url.rstrip("/")
        self.app = app or _token_app(token)
        self._key = key
        self._token = token
        self._expires = float("inf") if token else 0.0
        self.retries = max(0, retries)
        self.backoff = backoff
        self._own_http = http_client is None
        self.http = http_client or httpx.Client(timeout=timeout)
        self._lock = threading.Lock()
        self._etags: dict[tuple[Any, ...], tuple[str, bytes]] = {}
        # False once PlantCraft answered that it has no POST /api/v1/series (before 0.2).
        self._batch = True
        if historian_url is None:
            historian_url = os.environ.get(HISTORIAN_URL_ENV, "")
        historian_url = historian_url.strip()
        self._historian = _Historian(historian_url) if historian_url else None
        # Series read as pandas come in the binary answer when the Historian writes it
        # (``plantcraft_sdk.wire``); PLANTCRAFT_BINARY_READS=0 keeps JSON (comparisons).
        self.binary_reads = os.environ.get(BINARY_READS_ENV, "1").strip() != "0"

    # Lifecycle --------------------------------------------------------------

    def close(self) -> None:
        if self._own_http:
            self.http.close()

    def __enter__(self) -> PlantCraftClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def with_token(self, token: str, *, app: str | None = None) -> PlantCraftClient:
        """A client acting as the user of ``token``, sharing this one's connections and app id."""

        client = PlantCraftClient(
            self.base_url,
            token,
            app=app or self.app,
            retries=self.retries,
            backoff=self.backoff,
            http_client=self.http,
        )
        client._batch = self._batch
        client._historian = self._historian
        client.binary_reads = self.binary_reads
        return client

    # Transport --------------------------------------------------------------

    def _url(self, path: str, base: str | None = None) -> str:
        return f"{base or self.base_url}{path}"

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        auth: bool = True,
        idempotent: bool = True,
        base: str | None = None,
        timeout: float | None = None,
        accept: str = "application/json",
    ) -> Any:
        return self._exchange(
            method, path, params=params, json=json, auth=auth, idempotent=idempotent,
            base=base, timeout=timeout, accept=accept,
        )[0]  # fmt: skip

    def _exchange(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        auth: bool = True,
        idempotent: bool = True,
        base: str | None = None,
        timeout: float | None = None,
        accept: str = "application/json",
    ) -> tuple[Any, httpx.Headers]:
        """The answer and its headers. A GET sends the ETag of the answer kept for it, and a
        304 gives that answer back."""

        if method != "GET" and auth and self._key is not None and _demo_visit_write(method, path):
            raise DemoVisitWrite(
                "A public demo visit's changes stay in the visit: not sent to PlantCraft.",
                status_code=403,
            )
        params = {key: value for key, value in (params or {}).items() if value is not None}
        cache_key = (base, path, tuple(sorted((k, str(v)) for k, v in params.items())))
        kept = self._etags.get(cache_key) if method == "GET" else None
        renewed = False
        attempt = 0
        while True:
            headers = {"Accept": accept}
            if auth:
                headers["Authorization"] = f"Bearer {self.token()}"
            if kept is not None:
                headers["If-None-Match"] = kept[0]
            try:
                extra = {} if timeout is None else {"timeout": timeout}
                response = self.http.request(
                    method,
                    self._url(path, base),
                    params=params,
                    json=json,
                    headers=headers,
                    **extra,
                )
            except httpx.TransportError as exc:
                # A request that never reached the server is safe to send again.
                retry = idempotent or isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                if retry and attempt < self.retries:
                    attempt += 1
                    time.sleep(self.backoff * 2 ** (attempt - 1))
                    continue
                raise Unavailable(f"PlantCraft could not be reached: {exc}") from exc
            if response.status_code in RETRY_STATUSES and idempotent and attempt < self.retries:
                attempt += 1
                time.sleep(self.backoff * 2 ** (attempt - 1))
                continue
            if response.status_code == 401 and auth and self._key and not renewed:
                # The service token was rejected (keys rotated, clock skew): ask again once.
                renewed = True
                self._expires = 0.0
                continue
            if response.status_code == 304 and kept is not None:
                # Read again from the bytes: no caller shares (and changes) another's answer.
                return json_module.loads(kept[1]), response.headers
            if response.is_error:
                raise _error(response)
            if response.headers.get("content-type", "").startswith(wire.MEDIA_TYPE):
                try:
                    series, errors = wire.read_binary(response.content)
                except wire.WireError as exc:
                    raise Unavailable(f"PlantCraft answered with broken series: {exc}") from exc
                return {"series": series, "errors": errors}, response.headers
            try:
                answer = response.json()
            except ValueError as exc:
                raise Unavailable("PlantCraft answered with something that is not JSON.") from exc
            etag = response.headers.get("ETag")
            if method == "GET" and etag and len(response.content) <= ETAG_MAX_BYTES:
                with self._lock:
                    self._etags.pop(cache_key, None)
                    self._etags[cache_key] = (etag, response.content)
                    while len(self._etags) > ETAG_ENTRIES:
                        self._etags.pop(next(iter(self._etags)))
            return answer, response.headers

    def token(self) -> str:
        """The bearer token: the user's, or a service token renewed before it expires."""

        if self._key is None:
            return cast(str, self._token)
        with self._lock:
            if self._token is None or time.time() > self._expires - RENEW_MARGIN_SECONDS:
                grant = self.service_token(cast(str, self.app), self._key)
                self._token, self._expires = grant["token"], _expiry(grant)
            return self._token

    def _read(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> Any:
        """A signal or series read: from the Historian when it serves them, else PlantCraft.

        Only a Historian that could not be reached (or answered something that is not JSON)
        sends the read to PlantCraft, and the next ones for a minute; its own answers (an
        unknown signal, a bad window, a refused token, a plant source that failed) are the
        answer, as PlantCraft's would be, since PlantCraft would forward to it.
        """

        return self._read_exchange(method, path, params=params, json=json, timeout=timeout)[0]

    def _read_exchange(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> tuple[Any, httpx.Headers]:
        historian = self._historian
        if historian is not None and self._historian_serves(historian):
            try:
                return self._exchange(
                    method, path, params=params, json=json, base=historian.url, timeout=timeout
                )
            except Unavailable as exc:
                if exc.status_code is not None:
                    raise  # the Historian's own answer (a source that failed: 502)
                historian.set(False)
        return self._exchange(method, path, params=params, json=json, timeout=timeout)

    def _all_pages(self, exchange: Any, path: str, params: Mapping[str, Any]) -> list[Any]:
        """A list route read page by page (``plantcraft_sdk.server.paging``): never more than
        ``PAGE_SIZE`` items in one answer. A server that answers the whole list (no
        ``X-Next-Cursor``) ends the walk at once."""

        found: list[Any] = []
        cursor: str | None = None
        for _ in range(100_000):
            answer, headers = exchange(
                "GET", path, params={**params, "limit": PAGE_SIZE, "cursor": cursor}
            )
            found.extend(answer or [])
            cursor = headers.get(NEXT_CURSOR)
            if not cursor:
                break
        return found

    def _historian_serves(self, historian: _Historian) -> bool:
        wanted = historian.wanted()
        if wanted is not None:
            return wanted
        try:
            answer = self._send("GET", "/api/v1/reads", base=historian.url)
            serves = isinstance(answer, dict) and answer.get("api") == HISTORIAN_READS_API
            if serves:
                historian.formats = frozenset(str(item) for item in answer.get("formats") or [])
        except PlantCraftError:
            # An older Historian (404), one that cannot be reached, or a token it refuses.
            serves = False
        historian.set(serves)
        return serves

    # Identity ---------------------------------------------------------------

    def keys(self) -> list[Jwk]:
        """``GET /api/v1/auth/keys``: the public keys tokens are signed with."""

        return self._send("GET", "/api/v1/auth/keys", auth=False)["keys"]

    def service_token(self, app: str, key: str) -> TokenGrant:
        """``POST /api/v1/auth/service-token``: a token for background work of ``app``."""

        return self._send(
            "POST",
            "/api/v1/auth/service-token",
            json={"app": app, "key": key},
            auth=False,
            idempotent=False,
        )

    def renew_browser_token(self, cookies: Mapping[str, str]) -> TokenGrant:
        """``POST /api/v1/auth/token`` with a browser's session cookies (normally the browser calls it)."""

        response = self.http.post(self._url("/api/v1/auth/token"), cookies=dict(cookies))
        if response.is_error:
            raise _error(response)
        return response.json()

    def me(self) -> Me:
        return self._send("GET", "/api/v1/me")

    def apps(self) -> list[App]:
        return self._send("GET", "/api/v1/apps")

    def installation_id(self) -> str | None:
        """``GET /api/v1/installation``: which installation (plant or site) this is, a UUID that
        never changes; exports and files an app writes carry it so a company's plants can be
        told apart. None for a PlantCraft before 0.5."""

        cached = getattr(self, "_installation_id", None)
        if cached:
            return cached
        try:
            found = self._send("GET", "/api/v1/installation").get("id")
        except NotFound:
            return None
        self._installation_id = str(found) if found else None
        return self._installation_id

    def app_license(self) -> bytes | None:
        """``GET /api/v1/apps/self/license``: the ``.pclicense`` an administrator added for this
        app (Apps › Licences), as its bytes, or None. The app checks its signature itself with
        its publisher's key (``plantcraft_sdk.licensing``). None for a PlantCraft before 0.6."""

        import json as _json

        try:
            found = self._send("GET", "/api/v1/apps/self/license").get("license")
        except NotFound:
            return None
        return _json.dumps(found).encode() if found else None

    def platform_version(self) -> str | None:
        """The PlantCraft version this app runs on (``GET /api/v1/installation``), or None."""

        try:
            return self._send("GET", "/api/v1/installation").get("version") or None
        except NotFound:
            return None

    def installation_time_zone(self) -> str:
        """``GET /api/v1/installation``: the installation's IANA time zone, what "local" means
        in a schedule (cached for a minute; UTC when PlantCraft is older than 0.5)."""

        now = time.monotonic()
        cached = getattr(self, "_zone_cache", None)
        if cached and now - cached[0] < 60:
            return cached[1]
        try:
            zone = str(self._send("GET", "/api/v1/installation").get("time_zone") or "UTC")
        except NotFound:
            zone = "UTC"
        self._zone_cache = (now, zone)
        return zone

    def features(self) -> set[str]:
        """``GET /api/v1/installation``: the tables of ``[contributes]`` this PlantCraft draws
        (``plantcraft_sdk.contributes.FEATURES``); empty for a PlantCraft before SDK 0.31.0, so
        an app hides what its platform lacks."""

        try:
            answer = self._send("GET", "/api/v1/installation")
        except NotFound:
            return set()
        return {str(item) for item in answer.get("features") or []}

    # Plant ------------------------------------------------------------------

    # Derived series -----------------------------------------------------------

    # Audit ------------------------------------------------------------------

    # People, groups and notifications (plantcraft_sdk.people) -------------

    # Results, events, runs and schedules (plantcraft_sdk.links) ----------

    # Desk: calendar feeds and to-dos (plantcraft_sdk.desk) ---------------------------------


__all__ = [
    "BadRequest",
    "error_for",
    "DemoVisitWrite",
    "Forbidden",
    "NotFound",
    "PlantCraftClient",
    "PlantCraftError",
    "Unauthorized",
    "Unavailable",
]
