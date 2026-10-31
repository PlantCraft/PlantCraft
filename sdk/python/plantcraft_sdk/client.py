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
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import quote

import numpy as np
import pandas as pd

try:
    import httpx
except ImportError:  # An app's notebook runtime (server/objects.py) reads only the errors here.
    httpx = None  # type: ignore[assignment]
from plantcraft_sdk import wire
from plantcraft_sdk.assets import MAX_RESULT_ASSETS
from plantcraft_sdk.contract import (
    BATCH_FULL_STATUS,
    MAX_BATCH_SIGNALS,
    MAX_PAGE,
    NEXT_CURSOR,
    App,
    Asset,
    AssetType,
    AuditReceipt,
    Jwk,
    Me,
    Series,
    SeriesBatch,
    SeriesError,
    Signal,
    TokenGrant,
    Value,
    series_to_pandas,
    unique_signals,
)
from plantcraft_sdk.derived import (
    MAX_DERIVED_ITEMS,
    MAX_DERIVED_VALUES,
    MAX_RUN_ITEMS,
    DerivedReceipt,
)
from plantcraft_sdk.links import (
    MAX_EVENTS,
    MAX_ITEMS,
    MAX_SUBJECTS,
    Event,
    EventsReceipt,
    PutReceipt,
    Result,
    ResultChange,
    Run,
    Schedule,
)
from plantcraft_sdk.llm import messages_body
from plantcraft_sdk.people import Group, NotificationReceipt, NotificationResolution, Person

DEFAULT_TIMEOUT = 15.0
# A series read waits its turn for the Historian's read budget (``HISTCRAFT_QUERY_TIMEOUT``, 30 s)
# and may then run as long again, and PlantCraft waits 75 s for the Historian: a client that gave
# up at 15 s asked again while its first read still ran, and a busy Historian never caught up
# (Analytics rounds failing with "timed out" on the demo, 2026-10-29).
SERIES_TIMEOUT = 90.0
# A language model may take a while to write its answer.
LLM_TIMEOUT = 120.0
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


class PlantCraftError(Exception):
    """PlantCraft answered with an error, or could not be reached."""

    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail if detail is not None else message


class BadRequest(PlantCraftError):
    """4xx other than the ones below: the request breaks the contract (bad window, step...)."""


class Unauthorized(PlantCraftError):
    """401: no token, or it expired or was not accepted."""


class Forbidden(PlantCraftError):
    """403: the user (or app) may not do this."""


class NotFound(PlantCraftError):
    """404: no such asset or signal."""


class Unavailable(PlantCraftError):
    """PlantCraft or its data source could not answer (connection error, timeout, 5xx)."""


def error_for(status_code: int, detail: Any, reason: str = "") -> PlantCraftError:
    """The typed error for an HTTP status and the server's ``detail`` (also per batch signal)."""

    if isinstance(detail, list):
        text = "; ".join(str(item.get("msg", item)) for item in detail if isinstance(item, dict))
    else:
        text = str(detail) if detail else reason or "error"
    message = f"PlantCraft answered {status_code}: {text}"
    kind = {401: Unauthorized, 403: Forbidden, 404: NotFound}.get(status_code)
    if kind is None:
        kind = Unavailable if status_code >= 500 else BadRequest
    return kind(message, status_code=status_code, detail=detail)


def _error(response: httpx.Response) -> PlantCraftError:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    return error_for(response.status_code, detail, response.reason_phrase)


def _token_app(token: str | None) -> str | None:
    """The app a token belongs to, read without verifying it (only to tag audit records)."""

    if not token:
        return None
    from plantcraft_sdk import jwt

    try:
        claims = jwt.unverified_claims(token)
    except (jwt.TokenError, ValueError):
        return None
    subject = str(claims.get("sub") or "")
    return subject[4:] if subject.startswith("app:") and len(subject) > 4 else None


def _time(value: str | datetime | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _expiry(grant: Mapping[str, Any]) -> float:
    try:
        stamp = datetime.fromisoformat(str(grant.get("expires_at")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()
    except ValueError:
        return time.time() + 300


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


class PlantCraftClient:
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

    def assets(
        self,
        *,
        kind: str | None = None,
        type: str | None = None,
        parent_id: str | None = None,
        results: bool = False,
    ) -> list[Asset]:
        """The asset tree; ``kind`` is the exact type, ``type`` also takes its subtypes.

        Result assets (what apps record about assets) come with ``results=True`` or
        ``kind="result"``.
        """

        params: dict[str, Any] = {"kind": kind, "type": type, "parent_id": parent_id}
        if results:
            params["results"] = "true"
        return self._all_pages(self._exchange, "/api/v1/assets", params)

    def sync_result_assets(self, assets: Iterable[Mapping[str, Any]]) -> dict[str, int]:
        """``PUT /api/v1/assets/results``: the app's whole set of result assets.

        Each is ``{"id": "<app id>.<name>", "parent_id", "name", "description", "made_by",
        "points": [{"role", "signal": "app-<app id>:<name>", "name", "unit"}]}``; those the app
        listed before and not now are ended, not removed. Needs a service token.
        ``{"saved", "ended"}``.
        """

        return self._send(
            "PUT", "/api/v1/assets/results", json={"assets": [dict(item) for item in assets]}
        )

    def remove_result_assets(self, ids: Iterable[str]) -> dict[str, int]:
        """``POST /api/v1/assets/results/remove``: drop result assets of the app. ``{"removed"}``."""

        wanted = list(dict.fromkeys(ids))
        removed = 0
        for start in range(0, len(wanted), MAX_RESULT_ASSETS):
            answer = self._send(
                "POST",
                "/api/v1/assets/results/remove",
                json={"ids": wanted[start : start + MAX_RESULT_ASSETS]},
            )
            removed += int((answer or {}).get("removed") or 0)
        return {"removed": removed}

    def asset_types(self) -> list[AssetType]:
        """The type catalog, inherited attributes and roles resolved."""

        return self._send("GET", "/api/v1/asset-types")

    def asset(self, asset_id: str) -> Asset:
        return self._send("GET", f"/api/v1/assets/{quote(asset_id, safe='')}")

    def signals(
        self,
        q: str | None = None,
        *,
        app: str | None = None,
        subject: str | None = None,
        result: str | None = None,
    ) -> list[Signal]:
        """Every signal; ``app``, ``subject`` and ``result`` keep the derived signals that have them."""

        params = {"q": q, "app": app, "subject": subject, "result": result}
        return self._all_pages(self._read_exchange, "/api/v1/signals", params)

    def signal(self, signal_id: str) -> Signal:
        return self._read("GET", f"/api/v1/signals/{quote(signal_id, safe='')}")

    def series(
        self,
        signal_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
    ) -> Series:
        """Recorded values (``step`` None) or one mean per ``step`` seconds. Naive datetimes are UTC."""

        return self._read(
            "GET",
            f"/api/v1/signals/{quote(signal_id, safe='')}/series",
            params={"start": _time(start), "end": _time(end), "step": step},
            timeout=SERIES_TIMEOUT,
        )

    def series_runs(
        self, signal_id: str, *, run: str | datetime | None = None, last: int | None = None
    ) -> list[dict[str, Any]]:
        """The executions of a runs point, newest first: ``[{"run_at", "t", "v"}]``.

        The run at ``run`` (its time), else the ``last`` newest (1 to 50), else the latest.
        """

        answer = self._send(
            "GET",
            f"/api/v1/signals/{quote(signal_id, safe='')}/series",
            params={"run": _time(run) if run is not None else None, "runs": last},
        )
        return list((answer or {}).get("runs") or [])

    def series_run_list(self, signal_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """What a runs point keeps: ``[{"run_at", "start", "end", "n"}]``, newest first."""

        answer = self._send(
            "GET", f"/api/v1/signals/{quote(signal_id, safe='')}/runs", params={"limit": limit}
        )
        return list((answer or {}).get("runs") or [])

    def series_pandas(
        self,
        signal_id: str,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
    ) -> pd.Series:
        """``series`` as a float ``pandas.Series`` with a UTC DatetimeIndex."""

        return series_to_pandas(self.series(signal_id, start, end, step))

    def series_many(
        self,
        signal_ids: Iterable[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
        *,
        binary: bool = False,
        quality: bool = False,
        extremes: bool = False,
    ) -> SeriesBatch:
        """Many signals' series: ``{"series": [...], "errors": [{signal, status, detail}]}``.

        ``binary``: a Historian that writes the binary answer (``plantcraft_sdk.wire``) sends
        it, and its series hold numpy arrays (``t`` int64 ms, ``v`` floats) instead of lists;
        ``series_many_pandas`` uses it.

        ``quality``: each series also lists where its samples were not good,
        ``"quality": [{"t", "quality"}]`` (the quality from ``t`` to the next change:
        ``uncertain``, ``substituted``, ``bad``, or ``good`` again). Without it a bad sample is
        just a null value and an uncertain one looks good. A server that keeps no quality
        leaves the list out.

        ``extremes`` (with ``step``): each number series also holds every step's lowest and
        highest value, ``"low"`` and ``"high"`` beside the means in ``"v"`` (``None`` where a
        step had none), so a min or max trend needs no raw samples. A server that cannot tell
        them (a source read live, a span past what it keeps) leaves them out.

        One ``POST /api/v1/series`` per 500 signals; signals a request had no
        room for (413) are asked for again in the next one, so ``errors`` holds
        only real failures (404 unknown signal, 422 too many points, 502 source
        failed). Series come back in the order asked. A PlantCraft without the
        batch route is read one signal at a time, with the same result.
        """

        pending = unique_signals(item for item in signal_ids if item)
        found: dict[str, Series] = {}
        errors: dict[str, SeriesError] = {}
        while pending:
            chunk, pending = pending[:MAX_BATCH_SIGNALS], pending[MAX_BATCH_SIGNALS:]
            answer = self._series_batch(
                chunk, start, end, step, binary=binary, quality=quality, extremes=extremes
            )
            for item in answer.get("series") or []:
                item.setdefault("kind", "number")
                found[item["signal"]] = item
            postponed = []
            for error in answer.get("errors") or []:
                if error.get("status") == BATCH_FULL_STATUS:
                    postponed.append(error["signal"])
                else:
                    errors[error["signal"]] = error
            if postponed and len(postponed) == len(chunk):
                # Nothing fitted: never loop forever on a server that serves none.
                for signal_id in postponed:
                    errors[signal_id] = {
                        "signal": signal_id,
                        "status": BATCH_FULL_STATUS,
                        "detail": "PlantCraft had no room for this signal.",
                    }
                postponed = []
            pending = postponed + pending
        order = unique_signals(item for item in signal_ids if item)
        return {
            "series": [found[item] for item in order if item in found],
            "errors": [errors[item] for item in order if item in errors],
        }

    def _series_batch(
        self,
        signal_ids: list[str],
        start: str | datetime | None,
        end: str | datetime | None,
        step: float | None,
        *,
        binary: bool = False,
        quality: bool = False,
        extremes: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "signals": signal_ids,
            "start": _time(start),
            "end": _time(end),
            "step": step,
        }
        if quality:
            body["quality"] = True
        if extremes and step:
            body["extremes"] = True
        historian = self._historian
        if historian is not None and self._historian_serves(historian):
            accept = (
                f"{wire.MEDIA_TYPE}, application/json;q=0.5"
                if binary and wire.FORMAT in historian.formats
                else "application/json"
            )
            try:
                return self._send(
                    "POST",
                    "/api/v1/series",
                    json=body,
                    base=historian.url,
                    timeout=SERIES_TIMEOUT,
                    accept=accept,
                )
            except Unavailable as exc:
                if exc.status_code is not None:
                    raise
                historian.set(False)
        if self._batch:
            try:
                return self._send("POST", "/api/v1/series", json=body, timeout=SERIES_TIMEOUT)
            except (NotFound, BadRequest) as exc:
                if exc.status_code not in (404, 405):
                    raise
                self._batch = False
        series: list[Series] = []
        errors: list[SeriesError] = []
        for signal_id in signal_ids:
            try:
                series.append(self.series(signal_id, start, end, step))
            except (BadRequest, NotFound, Unavailable) as exc:
                if exc.status_code is None:
                    raise
                errors.append(
                    {"signal": signal_id, "status": exc.status_code, "detail": str(exc.detail)}
                )
        return {"series": series, "errors": errors}

    def series_many_pandas(
        self,
        signal_ids: Iterable[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
        *,
        quality: bool = False,
    ) -> tuple[dict[str, pd.Series], list[SeriesError]]:
        """``series_many`` as ``({signal id: pandas.Series}, errors)``; text signals hold labels.

        ``quality``: each series' ``attrs["quality"]`` holds its quality changes, as
        ``series_many`` gives them.
        """

        batch = self.series_many(
            signal_ids, start, end, step, binary=self.binary_reads, quality=quality
        )
        columns = {
            item["signal"]: (
                wire.binary_to_pandas(item)
                if isinstance(item.get("t"), np.ndarray)
                else series_to_pandas(item)
            )
            for item in batch["series"]
        }
        return columns, batch["errors"]

    def series_frame(
        self,
        signal_ids: Iterable[str],
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        step: float | None = None,
    ) -> pd.DataFrame:
        """Several signals side by side, one column each (outer join on time).

        Read with ``series_many``; the first signal that failed raises its typed error.
        """

        columns, errors = self.series_many_pandas(signal_ids, start, end, step)
        if errors:
            first = errors[0]
            raise error_for(first["status"], first["detail"])
        if not columns:
            return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC"))
        return pd.concat(columns, axis=1).sort_index()

    def value(self, signal_id: str, agg: str = "last", window: str = "1h") -> Value:
        return self._read(
            "GET",
            f"/api/v1/signals/{quote(signal_id, safe='')}/value",
            params={"agg": agg, "window": window},
        )

    # Derived series -----------------------------------------------------------

    def put_series(self, items: Iterable[Mapping[str, Any]]) -> DerivedReceipt:
        """``PUT /api/v1/series``: the app's computed series, as derived signals.

        Each item is ``{"signal": "app-<app id>:<name>", "t": [iso...], "v": [...]}`` with
        optional ``name``, ``unit`` (``"/100"`` for a score), ``kind``, ``subject``
        (``asset:<id>``) and ``result`` (the result kind it comes from). Needs a service token.
        Sent in requests of at most 500 items and 100,000 values (a longer series is split);
        ``errors`` carry the index in the whole list. A write at an instant already written
        replaces that value, so sending again is safe.
        """

        pieces: list[tuple[int, dict[str, Any]]] = []
        for index, item in enumerate(items):
            body = dict(item)
            stamps, values = list(body.get("t") or []), list(body.get("v") or [])
            if len(values) <= MAX_DERIVED_VALUES:
                pieces.append((index, body))
                continue
            for start in range(0, len(values), MAX_DERIVED_VALUES):
                part = {
                    **body,
                    "t": stamps[start : start + MAX_DERIVED_VALUES],
                    "v": values[start : start + MAX_DERIVED_VALUES],
                }
                pieces.append((index, part))
        written, errors = 0, []
        batch: list[tuple[int, dict[str, Any]]] = []
        size = 0

        def send() -> None:
            nonlocal written, batch, size
            if not batch:
                return
            answer = self._send("PUT", "/api/v1/series", json=[body for _, body in batch])
            written += int(answer.get("written") or 0)
            for error in answer.get("errors") or []:
                local = int(error.get("index", 0))
                original = batch[local][0] if 0 <= local < len(batch) else local
                errors.append({**error, "index": original})
            batch, size = [], 0

        for index, body in pieces:
            count = len(body.get("v") or [])
            if len(batch) >= MAX_DERIVED_ITEMS or size + count > MAX_DERIVED_VALUES:
                send()
            batch.append((index, body))
            size += count
        send()
        return {"written": written, "errors": errors}

    def put_series_runs(self, items: Iterable[Mapping[str, Any]]) -> DerivedReceipt:
        """``PUT /api/v1/series/runs``: one whole series per execution, on runs points.

        Each item is ``{"signal": "app-<app id>:<name>", "run_at": iso, "t": [iso...], "v":
        [number...]}`` with optional ``keep_runs`` (default 10), ``keep_days``, ``managed_by``,
        ``name``, ``unit``, ``description``, ``subject`` and ``result``. A run sent again at
        the same ``run_at`` replaces it. Sent 500 runs per request; ``errors`` carry the index
        in the whole list. Needs a service token.
        """

        wanted = [dict(item) for item in items]
        written, errors = 0, []
        for start in range(0, len(wanted), MAX_RUN_ITEMS):
            answer = self._send(
                "PUT", "/api/v1/series/runs", json=wanted[start : start + MAX_RUN_ITEMS]
            )
            written += int((answer or {}).get("written") or 0)
            for error in (answer or {}).get("errors") or []:
                errors.append({**error, "index": int(error.get("index", 0)) + start})
        return {"written": written, "errors": errors}

    def retire_series(self, signals: Iterable[str]) -> dict[str, Any]:
        """``POST /api/v1/series/retire``: the app's derived series it no longer writes.

        Only its own (``app-<app id>:...``); at most 500 per request (longer lists are split).
        A retired series is no longer listed nor read. ``{"retired": [ids], "errors": [...]}``.
        """

        wanted = list(dict.fromkeys(signals))
        retired: list[str] = []
        errors: list[Any] = []
        for start in range(0, len(wanted), 500):
            answer = self._send(
                "POST", "/api/v1/series/retire", json={"signals": wanted[start : start + 500]}
            )
            retired.extend((answer or {}).get("retired") or [])
            errors.extend((answer or {}).get("errors") or [])
        return {"retired": retired, "errors": errors}

    # Audit ------------------------------------------------------------------

    def audit(
        self, action: str, subject: str, detail: Any = None, *, app: str | None = None
    ) -> AuditReceipt:
        """Record a user's change in PlantCraft's audit log.

        Tagged with ``app``, else with this client's app id when it knows it.
        """

        body: dict[str, Any] = {"action": action, "subject": subject, "detail": detail}
        if app or self.app:
            body["app"] = app or self.app
        return self._send("POST", "/api/v1/audit", json=body, idempotent=False)

    # People, groups and notifications (plantcraft_sdk.people) -------------

    def people(self) -> list[Person]:
        """``GET /api/v1/people``: the active people, with their groups (no email or phone)."""

        return self._send("GET", "/api/v1/people")

    def groups(self) -> list[Group]:
        """``GET /api/v1/groups``: every group with its members."""

        return self._send("GET", "/api/v1/groups")

    def notification_settings(self) -> dict[str, bool]:
        """``GET /api/v1/notifications``: ``{"email": bool}``, whether the platform can send
        email now (an administrator set up its server), so an app offers email only then."""

        return self._send("GET", "/api/v1/notifications")

    def notify(
        self,
        recipients: Iterable[str],
        title: str,
        text: str = "",
        *,
        priority: str = "medium",
        url: str | None = None,
        email: bool = False,
        refs: Iterable[str] = (),
        key: str | None = None,
        category: str | None = None,
        actions: Iterable[dict[str, str]] = (),
    ) -> NotificationReceipt:
        """``POST /api/v1/notifications`` (a service token): a message to each person named
        (``user:<username>``) or in each group (``group:<id>``), and an email when ``email`` and
        the platform and the person allow it. Not retried: a repeat would notify twice.

        In Messages' Notifications the same ``key`` from the same app is one thread (an alarm's
        "alarm:12:3": fired, reminded, cleared), unread again on each send; ``category`` (alarm,
        run, action, info) chooses its icon and filter; ``actions`` are up to three buttons beside
        Open: ``{"label": "Open the rule", "href": "/alarm/rules/4"}`` opens a page of the suite,
        ``{"label": "Acknowledge", "href": "/alarm/api/alarms/12/ack", "method": "POST"}`` runs
        the call in this app as the person who clicks (a path under this app's own prefix).
        When it is settled, :meth:`resolve_notification` takes it off everyone's count."""

        body: dict[str, Any] = {
            "recipients": list(recipients),
            "title": title,
            "text": text,
            "priority": priority,
            "email": email,
            "refs": list(refs),
        }
        if url:
            body["url"] = url
        if key:
            body["key"] = key
        if category:
            body["category"] = category
        buttons = [
            {"label": item["label"], "href": item["href"]}
            | ({"method": "POST"} if item.get("method") == "POST" else {})
            for item in actions
        ]
        if buttons:
            body["actions"] = buttons
        return self._send("POST", "/api/v1/notifications", json=body, idempotent=False)

    def resolve_notification(self, key: str, note: str = "") -> NotificationResolution:
        """``POST /api/v1/notifications/resolve`` (a service token, platform with SDK 0.53.0):
        what this app notified under ``key`` is settled (an alarm acknowledged, here or from the
        notification's button, or cleared). The thread leaves the unread count of everyone who
        received it and shows ``note`` ("Acknowledged by Ana") instead of its buttons; a later
        :meth:`notify` with the same key opens it again. Safe to repeat."""

        body = {"key": key, "note": note}
        return self._send("POST", "/api/v1/notifications/resolve", json=body)

    # Results, events, runs and schedules (plantcraft_sdk.links) ----------

    def _for_app(self, items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Items as sent: with a person's token each names the app (this client's, if not given)."""

        found = []
        for item in items:
            body = dict(item)
            if self.app and not body.get("app"):
                body["app"] = self.app
            found.append(body)
        return found

    def put_results(self, results: Iterable[Mapping[str, Any]]) -> PutReceipt:
        """``PUT /api/v1/results``: one item per (subject, kind), up to 500 per request.

        Larger lists are sent in several requests; ``errors`` (with the index in the
        whole list) name the items that were not saved, such as unknown subjects (404).
        """

        return self._put_chunks("/api/v1/results", self._for_app(results))

    def results(
        self,
        subjects: Iterable[str] | str | None = None,
        *,
        app: str | None = None,
        kind: str | None = None,
    ) -> list[Result]:
        """``GET /api/v1/results``: the latest results about ``subjects`` (expired ones stale).

        Each subject is its own ``subject`` parameter (ids may hold commas), up to 500
        per request; more are asked in several requests. Each request is read page by page
        (``X-Next-Cursor``, PlantCraft 2026-10-27), so no result is left out.
        """

        wanted = [subjects] if isinstance(subjects, str) else list(subjects or [])
        wanted = list(dict.fromkeys(item for item in wanted if item))
        found: list[Result] = []
        for start in range(0, max(1, len(wanted)), MAX_SUBJECTS):
            chunk = wanted[start : start + MAX_SUBJECTS]
            params = {"subject": chunk or None, "app": app, "kind": kind}
            found.extend(self._all_pages(self._exchange, "/api/v1/results", params))
        return found

    def result_history(
        self,
        subject: str,
        *,
        app: str | None = None,
        kind: str | None = None,
        after: str | datetime | None = None,
        limit: int | None = None,
    ) -> list[ResultChange]:
        """``GET /api/v1/results/history``: status changes about ``subject``, oldest first."""

        params = {"subject": subject, "app": app, "kind": kind, "after": _time(after)}
        params["limit"] = limit
        return self._send("GET", "/api/v1/results/history", params=params)

    def post_event(
        self,
        kind: str,
        subject: str,
        *,
        summary: str = "",
        refs: Iterable[str] = (),
        payload: Mapping[str, Any] | None = None,
        app: str | None = None,
        severity: str | None = None,
        key: str | None = None,
        phase: str | None = None,
        category: str | None = None,
    ) -> Event:
        """``POST /api/v1/events``: ``kind`` is ``<app id>.<noun>.<verb>``.

        ``severity`` (info, ok, warning, critical), ``category`` and an ``instant`` phase default
        to the app's catalog; a condition is sent as ``phase="start"`` then ``"end"`` with the
        same ``key`` (``plantcraft_sdk.events``).
        """

        body: dict[str, Any] = {
            "kind": kind,
            "subject": subject,
            "summary": summary,
            "refs": list(refs),
            "payload": dict(payload or {}),
        }
        for field, value in (
            ("severity", severity),
            ("key", key),
            ("phase", phase),
            ("category", category),
        ):
            if value is not None:
                body[field] = value
        if app or self.app:
            body["app"] = app or self.app
        return self._send("POST", "/api/v1/events", json=body, idempotent=False)

    def put_event_catalog(
        self, events: Iterable[Mapping[str, Any]], *, app: str | None = None
    ) -> dict[str, Any]:
        """``PUT /api/v1/events/catalog``: the app's declared events, replaced
        (``EventCatalog.to_json()``; the SDK's server sends it when the app starts)."""

        body: dict[str, Any] = {"events": [dict(item) for item in events]}
        if app or self.app:
            body["app"] = app or self.app
        return self._send("PUT", "/api/v1/events/catalog", json=body)

    def put_contributions(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """``PUT /api/v1/contributions``: what the app adds to PlantCraft, replaced
        (``contributes.contributions(manifest)``; the SDK's server sends it when the app starts,
        and PlantCraft puts its events in the catalog too)."""

        body = dict(body)
        if self.app and not body.get("app"):
            body["app"] = self.app
        return self._send("PUT", "/api/v1/contributions", json=body)

    def contributions(self) -> dict[str, Any]:
        """``GET /api/v1/contributions``: what every installed app adds, and the ``features``
        this PlantCraft draws."""

        return self._send("GET", "/api/v1/contributions")

    def llm(
        self,
        use: str,
        messages: list[Mapping[str, str]] | str,
        *,
        system: str = "",
        timeout: float = LLM_TIMEOUT,
    ) -> dict[str, Any]:
        """``POST /api/v1/llm/{use}``: one answer from the model PlantCraft gives one of the
        app's uses (``[[contributes.llm]]``): ``{"use", "model", "text"}``.

        ``messages`` is a question, or the turns of a chat (``role`` user or assistant). A use
        with no model now (off, or nothing set up) raises ``BadRequest`` with status 409: say
        so, and that an administrator chooses one in Setup › Language models."""

        return self._send(
            "POST",
            f"/api/v1/llm/{quote(use, safe=':')}",
            json=messages_body(messages, system=system),
            idempotent=False,
            timeout=timeout,
        )

    # Desk: calendar feeds and to-dos (plantcraft_sdk.desk) ---------------------------------

    def put_calendar(self, feed: str, items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """``PUT /api/v1/calendar/<feed>``: the feed's whole list of dated items
        (``desk.CalendarItemIn``), replaced; the feed is one of the app's
        ``[[contributes.calendar]]``."""

        return self._send(
            "PUT", f"/api/v1/calendar/{quote(feed, safe='')}", params=self._own(), json=list(items)
        )

    def put_todo(self, todo: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /api/v1/todos``: a to-do for ``user:<name>`` or ``group:<id>``
        (``desk.TodoIn``: key, kind, title, for, due, ref, url, detail), made or changed by its
        ``key``; a done one stays done."""

        return self._send("POST", "/api/v1/todos", params=self._own(), json=dict(todo))

    def todos(self, state: str = "all") -> list[dict[str, Any]]:
        """``GET /api/v1/todos``: the app's own to-dos (``open``, ``done`` or ``all``), with
        ``done_by`` and ``done_at`` once a person ticked them in Desk."""

        return self._send("GET", "/api/v1/todos", params={**self._own(), "state": state})

    def close_todos(self, keys: Iterable[str]) -> dict[str, Any]:
        """``POST /api/v1/todos/close``: the app's to-dos with these keys are gone from every
        Desk; answers ``{"closed"}``, how many there were."""

        return self._send(
            "POST", "/api/v1/todos/close", params=self._own(), json={"keys": list(keys)}
        )

    def _own(self) -> dict[str, Any]:
        """``?app=`` for a person's token writing for an app; a service token names its own."""

        return {"app": self.app} if self.app else {}

    def app_settings(self) -> dict[str, Any]:
        """``GET /api/v1/contributions/settings``: this app's installation settings
        (``[[contributes.settings]]``) as the administrator set them in Setup › Apps, else their
        defaults, by key. An app's service token only."""

        return dict(self._send("GET", "/api/v1/contributions/settings").get("values") or {})

    def explore(self, asset: str | None = None, *, q: str = "") -> dict[str, Any]:
        """``GET /api/v1/explore``: the plant's top assets, one ``asset`` opened (its signals,
        the series apps computed about it, the events that named it, its children), or with
        ``q`` the assets, signals and series matching (``{"hits": [...]}``), each with its
        path (``plantcraft_sdk.explore``)."""

        params = {key: value for key, value in (("asset", asset), ("q", q)) if value}
        return self._send("GET", "/api/v1/explore", params=params or None)

    def event_catalog(self) -> list[dict[str, Any]]:
        """``GET /api/v1/events/catalog``: every app's declared events, PlantCraft's first."""

        return self._send("GET", "/api/v1/events/catalog")

    def post_events(self, events: Iterable[Mapping[str, Any]]) -> EventsReceipt:
        """``POST /api/v1/events`` with lists of up to 1,000 events per request.

        Each item has ``post_event``'s fields (``kind``, ``subject``, ``summary``,
        ``refs``, ``payload``; ``app`` defaults to this client's). ``ids[i]`` is
        item ``i``'s new event id, None when it is in ``errors`` (index in the whole
        list), such as an unknown subject (404). Not retried: a request that may
        have reached PlantCraft is not sent again.
        """

        items = self._for_app(events)
        saved, ids, errors, repeated = 0, [], [], 0
        for start in range(0, len(items), MAX_EVENTS):
            answer = self._send(
                "POST", "/api/v1/events", json=items[start : start + MAX_EVENTS], idempotent=False
            )
            saved += int(answer.get("saved") or 0)
            repeated += int(answer.get("repeated") or 0)
            ids.extend(answer.get("ids") or [])
            for error in answer.get("errors") or []:
                errors.append({**error, "index": int(error.get("index", 0)) + start})
        return {"saved": saved, "ids": ids, "errors": errors, "repeated": repeated}

    def events(
        self,
        *,
        ref: str | None = None,
        kind: str | None = None,
        after: int | None = None,
        limit: int | None = None,
        key: str | None = None,
    ) -> list[Event]:
        """``GET /api/v1/events``: oldest first; after the event id ``after``, else the latest.
        ``key`` keeps the events of one condition."""

        params = {"ref": ref, "kind": kind, "after": after, "limit": limit, "key": key}
        return self._send("GET", "/api/v1/events", params=params)

    def put_runs(self, runs: Iterable[Mapping[str, Any]]) -> PutReceipt:
        """``PUT /api/v1/runs``: one item per run id, replaced on every PUT."""

        return self._put_chunks("/api/v1/runs", self._for_app(runs))

    def put_knowledge(self, items: Iterable[Mapping[str, Any]]) -> PutReceipt:
        """``PUT /api/v1/knowledge``: the app's texts about its own objects (protocols, runs),
        one per ref, replaced on every PUT; specialists read them as context."""

        return self._put_chunks("/api/v1/knowledge", self._for_app(items))

    def delete_knowledge(self, refs: Iterable[str]) -> dict[str, Any]:
        """``POST /api/v1/knowledge/delete``: the app's texts about these refs are removed."""

        return self._send("POST", "/api/v1/knowledge/delete", json={"refs": list(refs)})

    def knowledge(
        self,
        *,
        ref: str | None = None,
        q: str | None = None,
        app: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """``GET /api/v1/knowledge``: texts about ``ref``, or matching ``q``."""

        params = {"ref": ref, "q": q, "app": app, "limit": limit}
        return self._send("GET", "/api/v1/knowledge", params=params)

    def runs(
        self,
        *,
        app: str | None = None,
        status: str | None = None,
        subject: str | None = None,
        by: str | None = None,
        limit: int | None = None,
    ) -> list[Run]:
        """``GET /api/v1/runs``, newest first; ``by`` the runs a person started."""

        params = {"app": app, "status": status, "subject": subject, "by": by, "limit": limit}
        return self._send("GET", "/api/v1/runs", params=params)

    def put_schedules(
        self, schedules: Iterable[Mapping[str, Any]], *, app: str | None = None
    ) -> PutReceipt:
        """``PUT /api/v1/schedules``: the app's whole list (an empty list clears it)."""

        params = {"app": app or self.app}
        return self._send(
            "PUT", "/api/v1/schedules", params=params, json=[dict(item) for item in schedules]
        )

    def schedules(self, *, app: str | None = None) -> list[Schedule]:
        return self._send("GET", "/api/v1/schedules", params={"app": app})

    def _put_chunks(self, path: str, items: list[dict[str, Any]]) -> PutReceipt:
        saved, errors = 0, []
        for start in range(0, len(items), MAX_ITEMS):
            answer = self._send("PUT", path, json=items[start : start + MAX_ITEMS])
            saved += int(answer.get("saved") or 0)
            for error in answer.get("errors") or []:
                errors.append({**error, "index": int(error.get("index", 0)) + start})
        return {"saved": saved, "errors": errors}


__all__ = [
    "BadRequest",
    "error_for",
    "Forbidden",
    "NotFound",
    "PlantCraftClient",
    "PlantCraftError",
    "Unauthorized",
    "Unavailable",
]
