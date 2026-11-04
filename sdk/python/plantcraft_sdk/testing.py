"""``FakePlantCraft``: API v1 in-process, so an app tests without the real PlantCraft.

::

    from plantcraft_sdk.testing import FakePlantCraft

    fake = FakePlantCraft()
    client = fake.client("engineer")            # PlantCraftClient acting as that user
    verifier = fake.verifier("linkcraft")        # TokenVerifier reading the fake's keys
    token = fake.token("operator")              # a signed user token (aud "processcraft")
    expired = fake.token("operator", ttl=-60)   # ...or one that is no longer valid

The fake signs real Ed25519 tokens, serves the same routes and shapes as
``docs/api-v1.md`` and fills series with a deterministic synthetic signal per
id, or with the ``pandas.Series`` given in ``series={id: values}`` (labels make
a text signal). Signal ids are ``<source id>:<tag>`` as in PlantCraft (the
default signals are ``fake:FIC-101.PV``...); like PlantCraft until API v1 is
frozen, a bare tag that exactly one signal has names that signal, and
``series`` and ``broken`` may be keyed by id or by bare tag. Given series are a recorded file: ``end`` and value windows
default to their last sample, as PlantCraft does for a recorded file. Writes
land in ``fake.audit_log``; ids in ``fake.broken`` fail as a dead source (502).
Assets carry ``type_path`` and ``relations`` like PlantCraft's; their types come from
``asset_types=`` (definitions as an admin writes them, default the starter types of
``plantcraft_sdk.assets``), served resolved by ``GET /api/v1/asset-types``.
The browser renewal (``POST /api/v1/auth/token``) takes the user name from the
``processcraft_session`` cookie. Derived series an app writes with ``PUT /api/v1/series``
become signals of ``app-<app id>`` (with ``app``, ``subject`` and ``result``, and the
``?app&subject&result`` filters), read back like the others; ``fake.derived`` holds them.

Two ways in, one implementation (``fake.handle``):

- ``fake.http_client()`` (default): an ``httpx.Client`` on an
  ``httpx.MockTransport``. In-process, no event loop, no sockets: fast.
- ``fake.app``: a real ASGI app (Starlette, from the ``server`` extra) to serve
  with uvicorn or ``fake.http_client(transport="asgi")`` (Starlette's TestClient).
"""

import copy
import math
import re
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from functools import cached_property
from typing import Any
from urllib.parse import parse_qsl

import httpx
import numpy as np
import pandas as pd

from plantcraft_sdk import derived as _derived
from plantcraft_sdk import jwt
from plantcraft_sdk import scopes as _scopes
from plantcraft_sdk._fake.assets import (  # noqa: F401 (the names this module has always had)
    _AssetRoutes,
)
from plantcraft_sdk._fake.defaults import (  # noqa: F401 (the names this module has always had)
    BASE_URL,
    DEFAULT_APP_KEYS,
    DEFAULT_APPS,
    DEFAULT_ASSETS,
    DEFAULT_GROUPS,
    DEFAULT_SIGNALS,
    DEFAULT_USERS,
    FAKE_SOURCE,
    SESSION_COOKIE,
    _signal,
    synthetic,
    synthetic_text,
)
from plantcraft_sdk._fake.links import (  # noqa: F401 (the names this module has always had)
    _CHANGE_FIELDS,
    _SHORT,
    FakeLinks,
    _LinksRoutes,
)
from plantcraft_sdk._fake.people import (  # noqa: F401 (the names this module has always had)
    _PeopleRoutes,
)
from plantcraft_sdk._fake.series import (  # noqa: F401 (the names this module has always had)
    _SeriesRoutes,
)
from plantcraft_sdk._fake.wire import (  # noqa: F401 (the names this module has always had)
    _TYPED_KINDS,
    FakeResponse,
    _Abort,
    _multi,
    _Request,
)
from plantcraft_sdk.assets import (
    STARTER_TYPES,
    type_path,
)
from plantcraft_sdk.contract import (
    CENTRAL_AUDIENCE,
    ISSUER,
    MAX_BATCH_POINTS,
    MAX_POINTS,
    TOKEN_COOKIE,
    USER_TOKEN_SECONDS,
    ContractError,
    iso,
    iso_many,
    kind_of,
    shape_values,
)
from plantcraft_sdk.refs import split_signal_id

_ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("GET", re.compile(r"^/api/v1/auth/keys$"), "keys"),
    ("GET", re.compile(r"^/api/v1/auth/revoked$"), "revoked"),
    ("POST", re.compile(r"^/api/v1/auth/token$"), "renew"),
    ("POST", re.compile(r"^/api/v1/auth/service-token$"), "service_token"),
    ("GET", re.compile(r"^/api/v1/me$"), "me"),
    ("GET", re.compile(r"^/api/v1/apps$"), "apps"),
    ("GET", re.compile(r"^/api/v1/installation$"), "installation"),
    ("GET", re.compile(r"^/api/v1/assets$"), "assets"),
    ("GET", re.compile(r"^/api/v1/explore$"), "explore"),
    ("PUT", re.compile(r"^/api/v1/assets/results$"), "put_result_assets"),
    ("POST", re.compile(r"^/api/v1/assets/results/remove$"), "remove_result_assets"),
    ("GET", re.compile(r"^/api/v1/assets/(?P<id>.+)$"), "asset"),
    ("GET", re.compile(r"^/api/v1/asset-types$"), "asset_types"),
    ("GET", re.compile(r"^/api/v1/signals$"), "signals"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)/series$"), "series"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)/value$"), "value"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)/runs$"), "run_list"),
    ("GET", re.compile(r"^/api/v1/signals/(?P<id>.+)$"), "signal"),
    ("POST", re.compile(r"^/api/v1/series$"), "series_batch"),
    ("PUT", re.compile(r"^/api/v1/series$"), "put_series"),
    ("POST", re.compile(r"^/api/v1/series/retire$"), "retire_series"),
    ("PUT", re.compile(r"^/api/v1/series/runs$"), "put_series_runs"),
    ("POST", re.compile(r"^/api/v1/audit$"), "audit"),
    ("GET", re.compile(r"^/api/v1/people$"), "people"),
    ("GET", re.compile(r"^/api/v1/groups$"), "groups"),
    ("GET", re.compile(r"^/api/v1/notifications$"), "notification_settings"),
    ("POST", re.compile(r"^/api/v1/notifications$"), "notify"),
    ("POST", re.compile(r"^/api/v1/notifications/resolve$"), "resolve_notification"),
]


# Results, events, runs and schedules (plantcraft_sdk.links) ------------------------
#
# The fake keeps them in memory, in ``fake.links``; the rules are the shared ones of
# ``plantcraft_sdk.links``, so a body the fake accepts PlantCraft accepts too.

_ROUTES.extend(
    [
        ("PUT", re.compile(r"^/api/v1/results$"), "put_results"),
        ("GET", re.compile(r"^/api/v1/results$"), "results"),
        ("GET", re.compile(r"^/api/v1/results/history$"), "result_history"),
        ("POST", re.compile(r"^/api/v1/events$"), "post_event"),
        ("GET", re.compile(r"^/api/v1/events$"), "events"),
        ("PUT", re.compile(r"^/api/v1/events/catalog$"), "put_event_catalog"),
        ("GET", re.compile(r"^/api/v1/events/catalog$"), "event_catalog"),
        ("PUT", re.compile(r"^/api/v1/contributions$"), "put_contributions"),
        ("GET", re.compile(r"^/api/v1/contributions$"), "contributions"),
        ("POST", re.compile(r"^/api/v1/llm/(?P<use>[^/]+)$"), "llm"),
        ("GET", re.compile(r"^/api/v1/contributions/settings$"), "contribution_settings"),
        ("PUT", re.compile(r"^/api/v1/calendar/(?P<feed>[^/]+)$"), "put_calendar"),
        ("POST", re.compile(r"^/api/v1/todos$"), "put_todo"),
        ("GET", re.compile(r"^/api/v1/todos$"), "todos"),
        ("POST", re.compile(r"^/api/v1/todos/close$"), "close_todos"),
        ("PUT", re.compile(r"^/api/v1/runs$"), "put_runs"),
        ("GET", re.compile(r"^/api/v1/runs$"), "runs"),
        ("PUT", re.compile(r"^/api/v1/knowledge$"), "put_knowledge"),
        ("POST", re.compile(r"^/api/v1/knowledge/delete$"), "delete_knowledge"),
        ("GET", re.compile(r"^/api/v1/knowledge$"), "knowledge"),
        ("PUT", re.compile(r"^/api/v1/schedules$"), "put_schedules"),
        ("GET", re.compile(r"^/api/v1/schedules$"), "schedules"),
    ]
)

# Each route's path as API v1 names it, for the permission it needs (plantcraft_sdk.scopes).
_TEMPLATES: dict[str, str] = {
    "asset": "/api/v1/assets/{asset_id}",
    "signal": "/api/v1/signals/{signal_id}",
    "series": "/api/v1/signals/{signal_id}/series",
    "value": "/api/v1/signals/{signal_id}/value",
    "run_list": "/api/v1/signals/{signal_id}/runs",
    "llm": "/api/v1/llm/{use}",
    "put_calendar": "/api/v1/calendar/{feed}",
}
# The permissions each app's own token used in every fake of this test run, by app id
# (``apptest.permission_problems`` holds them to the app's ``app.toml``).
PERMISSIONS_USED: dict[str, set[str]] = {}


def _template(name: str, pattern: re.Pattern[str]) -> str:
    return _TEMPLATES.get(name) or pattern.pattern.strip("^$").replace("\\", "")


class FakePlantCraft(_PeopleRoutes, _AssetRoutes, _SeriesRoutes, _LinksRoutes):
    """An in-process PlantCraft API v1 with its own key pair, users, assets and signals."""

    def __init__(
        self,
        *,
        users: dict[str, dict[str, Any]] | None = None,
        apps: list[dict[str, Any]] | None = None,
        app_keys: dict[str, str] | None = None,
        assets: list[dict[str, Any]] | None = None,
        asset_types: list[dict[str, Any]] | None = None,
        signals: list[dict[str, Any]] | None = None,
        series: dict[str, pd.Series] | None = None,
        sample_seconds: float = 10.0,
        now: datetime | None = None,
        recorded: bool | None = None,
        groups: list[dict[str, Any]] | None = None,
        time_zone: str = "UTC",
    ):
        self.users = copy.deepcopy(DEFAULT_USERS if users is None else users)
        # The installation's zone, as ``GET /api/v1/installation`` answers it ("local").
        self.time_zone = time_zone
        # Groups as GET /api/v1/groups answers them ({"id", "name", "kind", "members", ...}).
        self.groups = [
            {
                "description": "",
                "asset_id": None,
                "coordinator": None,
                "members": [],
                "parent_id": None,
                **item,
            }
            for item in copy.deepcopy(DEFAULT_GROUPS if groups is None else groups)
        ]
        # What apps sent with POST /api/v1/notifications: the body, the app and who received it.
        self.notifications: list[dict[str, Any]] = []
        # What apps settled with POST /api/v1/notifications/resolve: {(app, key): note}.
        self.resolved_notifications: dict[tuple[str, str], str] = {}
        # Whether the platform's email server is set up (GET /api/v1/notifications).
        self.email_ready = False
        self.apps_installed = copy.deepcopy(DEFAULT_APPS if apps is None else apps)
        self.app_keys = dict(DEFAULT_APP_KEYS if app_keys is None else app_keys)
        # Type definitions as an admin writes them (own attributes and roles only);
        # ``GET /api/v1/asset-types`` answers them resolved, as PlantCraft does.
        self.asset_types = copy.deepcopy(STARTER_TYPES if asset_types is None else asset_types)
        definitions = {item["id"]: item for item in self.asset_types}
        self.assets = [
            {
                "signals": {},
                "attributes": {},
                "relations": [],
                "type_path": type_path(definitions, item["kind"]),
                **item,
            }
            for item in copy.deepcopy(DEFAULT_ASSETS if assets is None else assets)
        ]
        self.signals = copy.deepcopy(DEFAULT_SIGNALS if signals is None else signals)
        self.series_data = dict(series or {})
        self.sample_seconds = sample_seconds
        self._now = now
        # Given series are a recorded file unless told otherwise.
        self.recorded = bool(self.series_data) if recorded is None else recorded
        # Signal ids whose reads fail as a dead data source would (502).
        self.broken: dict[str, str] = {}
        # Points one POST /api/v1/series answers before it postpones the rest (413).
        self.batch_points = MAX_BATCH_POINTS
        self.audit_log: list[dict[str, Any]] = []
        # Derived signal id -> {instant (UTC ISO): value}, as apps wrote them.
        self.derived: dict[str, dict[str, Any]] = {}
        # Runs points: signal id -> {run_at (UTC ISO): {"t", "v"}}, as apps wrote them.
        self.derived_runs: dict[str, dict[str, dict[str, list[Any]]]] = {}
        self.requests = 0
        # Tokens ended early (``revoke``), as ``GET /api/v1/auth/revoked`` lists them.
        self.revoked_users: dict[str, int] = {}
        self.revoked_keys: set[str] = set()
        # Sessions signed out (``end_session``): the ``sid`` claim of their tokens.
        self.ended_sessions: set[str] = set()
        self.private_key = jwt.generate_private_key()
        self.kid = jwt.key_id(self.private_key)
        self._public = [jwt.public_key_to_jwk(self.private_key, self.kid)]

    # Keys and tokens --------------------------------------------------------

    @property
    def now(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    @property
    def data_end(self) -> datetime:
        """Now; for a recorded file (given series), its last sample, as PlantCraft answers."""

        if self.recorded:
            ends = [
                pd.Timestamp(values.index.max())
                for values in self.series_data.values()
                if len(values) and not pd.isna(values.index.max())
            ]
            if ends:
                last = max(
                    stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
                    for stamp in ends
                )
                return last.to_pydatetime()
        return self.now

    @property
    def jwks(self) -> dict[str, Any]:
        return {"keys": list(self._public)}

    def revoke(self, username: str, *, at: int | None = None) -> None:
        """End the tokens ``username`` holds now (disabled, new password or access)."""

        self.revoked_users[username] = int(time.time()) + 1 if at is None else at

    def end_session(self, sid: str) -> None:
        """Sign out the browser session whose tokens carry ``sid`` (the session's digest)."""

        self.ended_sessions.add(sid)

    def rotate_key(self) -> str:
        """Sign with a new key from now on; the old public key stays listed."""

        self.private_key = jwt.generate_private_key()
        self.kid = jwt.key_id(self.private_key)
        self._public.append(jwt.public_key_to_jwk(self.private_key, self.kid))
        return self.kid

    def token(
        self,
        username: str = "admin",
        *,
        aud: str = CENTRAL_AUDIENCE,
        ttl: float = USER_TOKEN_SECONDS,
        **claims: Any,
    ) -> str:
        """A signed user token; ``claims`` override any claim (``apps={...}``, ``level=...``)."""

        user = self.users.get(username, {"name": username, "level": "viewer", "apps": {}})
        # Never older than the user's last revocation, as PlantCraft issues them.
        issued = max(int(time.time()), self.revoked_users.get(username, 0))
        body = {
            "iss": ISSUER,
            "sub": username,
            "name": user.get("name", username),
            "level": user.get("level", "viewer"),
            "apps": dict(user.get("apps") or {}),
            "aud": aud,
            "iat": issued,
            "exp": issued + int(ttl),
        }
        body.update(claims)
        return jwt.encode(body, self.private_key, self.kid)

    def _grant(self, token: str) -> dict[str, str]:
        claims = jwt.decode(token, self.jwks, None, issuer=None)
        return {"token": token, "expires_at": iso(pd.Timestamp(claims["exp"], unit="s"))}

    # Clients ----------------------------------------------------------------

    def http_client(self, transport: str = "mock") -> httpx.Client:
        """An ``httpx.Client`` wired to the fake.

        ``"mock"`` (default): an ``httpx.MockTransport`` calling ``handle`` in
        process. ``"asgi"``: Starlette's ``TestClient`` on ``fake.app``, to run
        the requests through a real ASGI stack.
        """

        if transport == "asgi":
            from starlette.testclient import TestClient

            return TestClient(self.app, base_url=BASE_URL)
        if transport != "mock":
            raise ValueError("transport is 'mock' or 'asgi'.")
        return httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(self._httpx))

    def client(
        self, username: str | None = "admin", *, transport: str = "mock", **options: Any
    ) -> Any:
        """A ``PlantCraftClient`` acting as ``username``, or as an app when given ``app`` and ``key``."""

        from plantcraft_sdk.client import PlantCraftClient

        token = self.token(username) if username and "key" not in options else None
        return PlantCraftClient(BASE_URL, token, http_client=self.http_client(transport), **options)

    def verifier(
        self, app_id: str = "linkcraft", *, transport: str = "mock", **options: Any
    ) -> Any:
        """A ``TokenVerifier`` for ``app_id`` that reads this fake's keys."""

        from plantcraft_sdk.auth import TokenVerifier

        return TokenVerifier(BASE_URL, app_id, http_client=self.http_client(transport), **options)

    # Data -------------------------------------------------------------------

    def _given(self, values: dict[str, Any], signal_id: str) -> Any:
        """What ``series`` or ``broken`` holds for a signal: by its id, else by its bare tag."""

        if signal_id in values:
            return values[signal_id]
        return values.get(split_signal_id(signal_id)[1])

    def kind(self, signal_id: str) -> str:
        """``"text"`` or ``"number"``: as the signal says, else from its given series."""

        found = next((item for item in self.signals if item["id"] == signal_id), None)
        if found is not None and found.get("kind") in _derived.POINT_KINDS:
            return str(found["kind"])
        if found is not None and found.get("kind"):
            return kind_of(found["kind"])
        given = self._given(self.series_data, signal_id)
        if given is not None and not pd.api.types.is_numeric_dtype(given.dtype):
            numbers = pd.to_numeric(given.dropna(), errors="coerce")
            if numbers.isna().any():
                return "text"
        return "number"

    def _signal_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "kind": self.kind(item["id"])}

    def _values(
        self, signal_id: str, start: datetime, end: datetime, step: float | None
    ) -> tuple[list[str], list[Any]]:
        broken = self._given(self.broken, signal_id)
        if broken is not None:
            raise _Abort(502, f"Failed to read history: {broken}")
        kind = self.kind(signal_id)
        if kind in _TYPED_KINDS:
            # Kept as written, read back as recorded values (no grid), as PlantCraft answers.
            low, high = iso(start), iso(end)
            kept = sorted(
                (stamp, value)
                for stamp, value in self.derived.get(signal_id, {}).items()
                if low <= stamp <= high
            )
            return [stamp for stamp, _ in kept], [value for _, value in kept]
        given = self._given(self.series_data, signal_id)
        if given is not None:
            return shape_values(given, start, end, step, kind, now=self.now, signal_id=signal_id)
        period = step or self.sample_seconds
        first = math.ceil(start.timestamp() / period) * period
        count = int(max(0, math.floor((end.timestamp() - first) / period) + 1))
        if step is None and count > MAX_POINTS:
            raise ContractError(
                f"Too many recorded values: at most {MAX_POINTS} per request. Give a step."
            )
        if step is not None:
            times = pd.date_range(start, end, freq=pd.Timedelta(seconds=step), inclusive="left")
        else:
            times = pd.DatetimeIndex(
                pd.to_datetime(first + period * np.arange(count), unit="s", utc=True)
            )
        if kind == "text":
            return iso_many(times), synthetic_text(signal_id, times)
        return iso_many(times), synthetic(signal_id, times).tolist()

    # Requests ---------------------------------------------------------------

    def handle(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str | list[str]] | None = None,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> FakeResponse:
        """Answer one API v1 request (``path`` decoded, ``headers`` with lowercase names).

        A repeated query parameter is given as a list (``{"subject": ["a", "b"]}``).
        """

        self.requests += 1
        lists = {
            key: [value] if isinstance(value, str) else [str(item) for item in value]
            for key, value in (query or {}).items()
        }
        single = {key: values[-1] for key, values in lists.items() if values}
        request = _Request(
            method.upper(), path, single, dict(headers or {}), dict(cookies or {}), body, lists
        )
        allowed = False
        for route_method, pattern, name in _ROUTES:
            match = pattern.match(path)
            if match is None:
                continue
            allowed = True
            if route_method != request.method:
                continue
            refused = self._app_refusal(request, route_method, _template(name, pattern))
            if refused is not None:
                return FakeResponse(403, {"detail": refused})
            try:
                answer = getattr(self, f"_route_{name}")(request, **match.groupdict())
            except _Abort as abort:
                return FakeResponse(abort.status, {"detail": abort.detail}, abort.headers)
            except ContractError as exc:
                return FakeResponse(422, {"detail": str(exc)})
            if isinstance(answer, FakeResponse):
                return answer
            status = 201 if name == "audit" else 200
            return FakeResponse(status, answer)
        if allowed:
            return FakeResponse(405, {"detail": "Method Not Allowed"})
        return FakeResponse(404, {"detail": "Not Found"})

    def _app_refusal(self, request: "_Request", method: str, route: str) -> str | None:
        """As PlantCraft: an app's own token is held to the ``[permissions]`` it declared in its
        contributions (none declared: not held); every permission used is recorded."""

        try:
            claims = self._caller(request)
        except _Abort:
            return None  # the route answers 401 itself
        subject = str(claims.get("sub") or "")
        if not subject.startswith("app:"):
            return None
        app = subject.removeprefix("app:")
        known, scope = _scopes.required(method, route)
        if not known:
            return f"{method} {route} is not open to an app's token"
        if scope is None:
            return None
        PERMISSIONS_USED.setdefault(app, set()).add(scope)
        declared = (self.links.contributions.get(app) or {}).get("permissions")
        if declared is not None and scope not in declared:
            return f"{app} did not ask for {scope} in its app.toml [permissions]"
        return None

    def _httpx(self, request: httpx.Request) -> httpx.Response:
        cookies: dict[str, str] = {}
        for part in (request.headers.get("cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name:
                cookies[name] = value
        answer = self.handle(
            request.method,
            request.url.path,
            query=_multi(parse_qsl(request.url.query.decode(), keep_blank_values=True)),
            headers={key.lower(): value for key, value in request.headers.items()},
            cookies=cookies,
            body=request.read(),
        )
        headers = [("content-type", "application/json"), *answer.headers.items()]
        headers += [("set-cookie", value) for value in answer.set_cookie_headers()]
        return httpx.Response(answer.status, headers=headers, content=answer.content())

    @cached_property
    def app(self) -> Any:
        """The fake as an ASGI app (Starlette), to serve over HTTP."""

        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Route

        fake = self

        async def endpoint(request: Any) -> Response:
            answer = fake.handle(
                request.method,
                request.scope["path"],
                query=_multi(request.query_params.multi_items()),
                headers={key.lower(): value for key, value in request.headers.items()},
                cookies=dict(request.cookies),
                body=await request.body(),
            )
            response = Response(
                answer.content(),
                status_code=answer.status,
                media_type="application/json",
                headers=answer.headers,
            )
            for name, value, max_age in answer.cookies:
                response.set_cookie(
                    name, value, max_age=max_age, path="/", httponly=True, samesite="lax"
                )
            return response

        methods = ["GET", "POST", "PUT", "PATCH", "DELETE"]
        return Starlette(routes=[Route("/{path:path}", endpoint, methods=methods)])

    # Access -----------------------------------------------------------------

    def _caller(self, request: "_Request") -> dict[str, Any]:
        header = request.headers.get("authorization") or ""
        scheme, _, value = header.partition(" ")
        token = value.strip() if scheme.lower() == "bearer" else ""
        token = token or request.cookies.get(TOKEN_COOKIE) or ""
        challenge = {"WWW-Authenticate": "Bearer"}
        if not token:
            raise _Abort(401, "Sign in to continue.", challenge)
        try:
            return jwt.decode(token, self.jwks, CENTRAL_AUDIENCE)
        except jwt.TokenError as exc:
            raise _Abort(401, f"The token was not accepted: {exc}", challenge) from exc

    def _reader(self, request: "_Request") -> dict[str, Any]:
        claims = self._caller(request)
        if claims.get("level") not in ("viewer", "editor", "admin"):
            raise _Abort(403, "Your access is limited to dashboards.")
        return claims

    def _known(self, signal_id: str) -> dict[str, Any] | None:
        """The signal of an id, or of a bare tag one signal has (deprecated, as in PlantCraft).

        A bare tag that two sources have is a 404 naming both ids.
        """

        found = next((item for item in self.signals if item["id"] == signal_id), None)
        if found is not None:
            return found
        same = [item for item in self.signals if split_signal_id(item["id"])[1] == signal_id]
        if len(same) > 1:
            ids = ", ".join(sorted(item["id"] for item in same))
            raise _Abort(
                404, f"Signal not found: {signal_id} is in more than one source; use {ids}."
            )
        return same[0] if same else None

    def _signal_or_404(self, signal_id: str) -> dict[str, Any]:
        found = self._known(signal_id)
        if found is None:
            raise _Abort(404, "Signal not found.")
        return found

    # Routes -----------------------------------------------------------------

    # People, groups and notifications (plantcraft_sdk.people) --------------


__all__ = [
    "BASE_URL",
    "DEFAULT_ASSETS",
    "DEFAULT_GROUPS",
    "DEFAULT_SIGNALS",
    "DEFAULT_USERS",
    "FakeLinks",
    "FakePlantCraft",
    "FakeResponse",
    "synthetic",
    "synthetic_text",
]
