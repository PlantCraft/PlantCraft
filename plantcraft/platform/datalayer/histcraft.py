"""The HistCraft data layer: every read, derived write and source change goes to HistCraft.

HistCraft is the suite's data layer and the only component that reaches plant data sources.
PlantCraft keeps people, tokens, assets and the plant map, checks the caller of each request,
and forwards to ``{HISTCRAFT_URL}/api/v1/data/...``:

| PlantCraft | HistCraft |
|---|---|
| ``GET /api/v1/signals?q&app&subject&result`` | ``GET /api/v1/data/signals`` (same query) |
| ``GET /api/v1/signals/{id}`` | ``GET /api/v1/data/signals/{id}`` |
| ``GET /api/v1/signals/{id}/series?start&end&step`` | ``GET /api/v1/data/signals/{id}/series`` |
| ``POST /api/v1/series`` | ``POST /api/v1/data/series`` (same body) |
| ``GET /api/v1/signals/{id}/value?agg&window`` | ``GET /api/v1/data/signals/{id}/value`` |
| ``PUT /api/v1/series`` (derived) | ``POST /api/v1/data/derived`` ``{"series": [item + app]}`` |
| The suite's health, every minute (``plantcraft.watch.recorder``) | ``POST /api/v1/data/system`` ``{"series": [...]}`` |
| Sources page and plant map: list, add, edit, remove | ``GET``/``POST /api/v1/data/sources``, ``PUT``/``DELETE /sources/{id}`` |
| Sources page: "Use" on signals | ``POST /api/v1/data/sources/{id}/signals`` ``{"signals": [tag...]}`` |
| Sources page: "Stop using" signals | ``PATCH /api/v1/data/signals/{source}:{tag}`` ``{"enabled": false}`` |
| Sources page: status, a source's variables | ``POST .../sources/{id}/test``, ``POST .../sources/{id}/browse`` |
| Sources page: test settings before saving | ``POST .../sources/test`` (the body of ``PUT /sources/{id}``) |

HistCraft tests saved sources (``POST /sources/{id}/test``) and settings not saved yet (``POST
/sources/test``: without a password it uses ``password_env`` or the stored password of that
id); its 502 with the source's own words is an ``ok: false`` test. It browses saved sources
(``POST /sources/{id}/browse`` ``{"root", "limit"}``). Stopping a signal keeps its history;
HistCraft refuses derived signals (422, passed on). ``/signals/{id}`` also takes a bare tag
that exactly one source has, and answers with the signal's canonical id.
Shapes are API v1's; signals carry ``mode`` (``source``, ``archive`` or ``both``) and ``app``,
``subject``, ``result`` (null for plant signals), passed through. PlantCraft authenticates with a token it issues to itself (``sub: app:processcraft``,
``aud: histcraft``, ``apps: {histcraft: editor}``, 5 minutes, renewed a minute before expiry).
HistCraft's 400, 404, 409, 413, 422 and 504 (a read past its time limit) answers reach the
caller as they are; any other failure is a 502, and no answer in time a 504.

HistCraft's sources (``docs/data-layer.md`` in the histcraft repository) have their own shape:
``{id, name, kind, endpoint, namespace_uri, username, password, password_env, options{}}``.
``source_body`` and ``source_item`` below map PlantCraft's source settings to and from it;
they are the one place to adapt when that shape changes.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx
import pandas as pd

from plantcraft.i18n import t
from plantcraft.industrial_data.thinning import thin_extremes
from plantcraft.platform.datalayer import DataLayer, DataLayerError

DATA = "/api/v1/data"
TOKEN_SECONDS = 300
# Ask for a new token this long before the current one expires.
RENEW_MARGIN = 60
# HistCraft answers that are the caller's own mistake reach the caller unchanged; 504 is a read
# longer than its time limit (HISTCRAFT_QUERY_TIMEOUT): "ask for a shorter period or a larger step".
PASS_THROUGH = {400, 404, 409, 413, 422, 504}
# How long PlantCraft waits for the Historian: longer than a read may take there (its turn in the
# read budget, up to 30 s, then its own read limit, 30 s), so a read past it ends with the
# Historian's advice (503, 504), not with "did not answer in time".
WAIT_SECONDS = 75.0
# PlantCraft settings HistCraft keeps in a source's ``options``.
OPTIONS = (
    "server",
    "auth_type",
    "verify_ssl",
    "ca_bundle",
    "read_mode",
    "max_workers",
    "retries",
    "page_size",
    "timeout_seconds",
    "timezone",
    "history_boundary_minutes",
)
# The options HistCraft accepts per source kind (its SOURCE_OPTIONS): any other is refused with
# "Unknown option", so an OPC UA source never sends PI's settings nor its own auth_type (the
# username and password say it).
KIND_OPTIONS = {
    "pi_web_api": set(OPTIONS),
    "opcua": {"timeout_seconds", "timezone", "history_boundary_minutes"},
    "csv": {"timezone"},
}
# The id a source not saved yet is tested under (HistCraft's test body needs one).
UNSAVED_ID = "unsaved"
# Variables one browse asks HistCraft for, at most.
BROWSE_MAX = 20000
# Where each source type keeps the address HistCraft calls ``endpoint``.
ENDPOINT_FIELD = {"opcua": "endpoint_url", "pi_web_api": "base_url", "csv": "path"}
SOURCE_TYPE_LABELS = {"opcua": "OPC UA", "pi_web_api": "PI Web API", "csv": "CSV file"}


def _quoted(signal_id: str) -> str:
    return quote(signal_id, safe="")


class HistCraftDataLayer(DataLayer):
    kind = "histcraft"
    manages_sources = True
    keeps_system = True

    def __init__(
        self,
        url: str,
        issuer: Any,
        *,
        timezone: str = "UTC",
        timeout: float | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.url = url.rstrip("/")
        self.issuer = issuer
        self.timezone = timezone
        if timeout is None:
            try:
                timeout = float(os.environ.get("HISTCRAFT_TIMEOUT_SECONDS", "") or WAIT_SECONDS)
            except ValueError:
                timeout = WAIT_SECONDS
            timeout = timeout if timeout > 0 else WAIT_SECONDS
        self.http = http_client or httpx.Client(timeout=timeout)
        self._own_http = http_client is None
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        if self._own_http:
            self.http.close()

    # Transport ------------------------------------------------------------------

    def token(self) -> str:
        """PlantCraft's own token for HistCraft, cached until a minute before it expires."""

        with self._lock:
            if self._token is None or time.time() > self._token[1] - RENEW_MARGIN:
                token, expires = self.issuer.issue(
                    "app:processcraft",
                    ttl=TOKEN_SECONDS,
                    audience="histcraft",
                    name="PlantCraft",
                    apps={"histcraft": "editor"},
                )
                self._token = (token, float(expires))
            return self._token[0]

    def call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        raw: bool = False,
    ) -> Any:
        """One request to HistCraft's data API; raises ``DataLayerError`` (status to answer).

        ``raw``: the answer's JSON as bytes, passed on unparsed (long series)."""

        params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self.token()}", "Accept": "application/json"}
            try:
                response = self.http.request(
                    method, f"{self.url}{DATA}{path}", params=params, json=json, headers=headers
                )
            except httpx.TimeoutException as exc:
                raise DataLayerError(504, t("The Historian did not answer in time.")) from exc
            except httpx.HTTPError as exc:
                raise DataLayerError(
                    502, t("The Historian could not be reached: {error}", error=exc)
                ) from exc
            if response.status_code == 401 and attempt == 0:
                # Keys rotated or a clock moved: one fresh token, then give up.
                with self._lock:
                    self._token = None
                continue
            break
        detail = _detail(response)
        if response.status_code in PASS_THROUGH:
            raise DataLayerError(response.status_code, detail)
        if response.is_error:
            raise DataLayerError(
                502,
                t(
                    "The Historian answered {status}: {detail}",
                    status=response.status_code,
                    detail=detail,
                ),
            )
        if raw:
            return response.content
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise DataLayerError(
                502, t("The Historian answered something that is not JSON.")
            ) from exc

    # API v1 reads ---------------------------------------------------------------

    def signals(
        self,
        q: str = "",
        *,
        app: str | None = None,
        subject: str | None = None,
        result: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"q": q, "app": app, "subject": subject, "result": result}
        return _list(self.call("GET", "/signals", params=params))

    def signal(self, signal_id: str) -> dict[str, Any]:
        return self.call("GET", f"/signals/{_quoted(signal_id)}")

    def lookup(self, signal_id: str) -> tuple[str | None, str]:
        try:
            found = self.signal(signal_id)
        except DataLayerError as exc:
            if exc.status == 404:
                return None, exc.detail
            raise
        return str(found.get("id") or signal_id), ""

    def series(
        self,
        signal_id: str,
        start: str | None,
        end: str | None,
        step: float | None,
        *,
        run: str | None = None,
        runs: int | None = None,
    ) -> dict[str, Any]:
        params = {"start": start, "end": end, "step": step, "run": run, "runs": runs}
        return self.call("GET", f"/signals/{_quoted(signal_id)}/series", params=params)

    def run_list(self, signal_id: str, limit: int = 50) -> dict[str, Any]:
        params = {"limit": limit}
        return self.call("GET", f"/signals/{_quoted(signal_id)}/runs", params=params)

    def series_batch(
        self,
        signals: list[str],
        start: str | None,
        end: str | None,
        step: float | None,
        *,
        quality: bool = False,
    ) -> dict[str, Any]:
        body = {"signals": signals, "start": start, "end": end, "step": step}
        if quality:
            body["quality"] = True
        return self.call("POST", "/series", json=body)

    # The same reads as JSON bytes: API v1 passes HistCraft's answer on without parsing it and
    # writing it again (a batch of 500 signals over a day is megabytes of JSON).

    def series_raw(
        self,
        signal_id: str,
        start: str | None,
        end: str | None,
        step: float | None,
        *,
        run: str | None = None,
        runs: int | None = None,
    ) -> bytes:
        params = {"start": start, "end": end, "step": step, "run": run, "runs": runs}
        return self.call("GET", f"/signals/{_quoted(signal_id)}/series", params=params, raw=True)

    def series_batch_raw(
        self,
        signals: list[str],
        start: str | None,
        end: str | None,
        step: float | None,
        *,
        quality: bool = False,
    ) -> bytes:
        body = {"signals": signals, "start": start, "end": end, "step": step}
        if quality:
            body["quality"] = True
        return self.call("POST", "/series", json=body, raw=True)

    def value(
        self, signal_id: str, agg: str, window: str, end: str | None = None
    ) -> dict[str, Any]:
        params = {"agg": agg, "window": window, **({"end": end} if end else {})}
        return self.call("GET", f"/signals/{_quoted(signal_id)}/value", params=params)

    # Derived series --------------------------------------------------------------

    def put_derived(self, app: str, items: list[Any]) -> dict[str, Any]:
        body = {"app": app, "series": [item.payload(app) for item in items]}
        return _receipt(self.call("POST", "/derived", json=body), items)

    def put_runs(self, app: str, items: list[Any]) -> dict[str, Any]:
        body = {"app": app, "series": [item.payload() for item in items]}
        return _receipt(self.call("POST", "/derived/runs", json=body), items)

    def retire_derived(self, app: str, signals: list[str]) -> dict[str, Any]:
        """Each signal retired in the Historian (archive kept for its retired days)."""

        retired, errors = [], []
        for index, signal in enumerate(signals):
            try:
                self.call("DELETE", f"/signals/{_quoted(signal)}")
            except DataLayerError as exc:
                if exc.status != 404:  # already gone: nothing to retire
                    errors.append(
                        {
                            "index": index,
                            "signal": signal,
                            "status": exc.status,
                            "detail": exc.detail,
                        }
                    )
                continue
            retired.append(signal)
        return {"retired": retired, "errors": errors}

    def put_system(self, series: list[dict[str, Any]]) -> dict[str, Any]:
        answer = self.call("POST", "/system", json={"series": series})
        return answer if isinstance(answer, dict) else {"written": 0, "errors": []}

    def _v1(self, method: str, path: str, token: str | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token or self.token()}", "Accept": "application/json"}
        return self.http.request(method, f"{self.url}/api/v1{path}", headers=headers)

    def certificates(self) -> list[dict[str, Any]]:
        """The Historian's OPC UA certificates (``GET /api/v1/certificates``); none when it is
        older than that list or does not answer: Health then shows only the suite's own."""

        try:
            response = self._v1("GET", "/certificates")
        except httpx.HTTPError:
            return []
        if response.is_error:
            return []
        try:
            answer = response.json()
        except ValueError:
            return []
        return (
            [item for item in answer if isinstance(item, dict)] if isinstance(answer, list) else []
        )

    def renew_certificate(self, certificate_id: str, token: str) -> dict[str, Any]:
        """A new client certificate for the Historian (``POST /api/v1/certificates/{id}/renew``),
        asked with the administrator's own token: PlantCraft's service token never writes there."""

        path = f"/certificates/{quote(certificate_id, safe='')}/renew"
        try:
            response = self._v1("POST", path, token)
        except httpx.HTTPError as exc:
            raise DataLayerError(
                502, t("The Historian could not be reached: {error}", error=exc)
            ) from exc
        if response.is_error:
            raise DataLayerError(
                response.status_code if response.status_code in PASS_THROUGH else 502,
                _detail(response),
            )
        return response.json()

    # The interface's own reads ---------------------------------------------------

    def _utc(self, stamp: Any) -> str:
        value = pd.Timestamp(stamp)
        if value.tzinfo is None:
            value = value.tz_localize(self.timezone)
        return value.tz_convert("UTC").isoformat()

    def history(
        self,
        tags: list[str],
        *,
        start: Any,
        end: Any,
        sample_seconds: int,
        max_points: int,
        source: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        wanted = [f"{source}:{tag}" if source and ":" not in tag else tag for tag in tags]
        answer = self.series_batch(wanted, self._utc(start), self._utc(end), None)
        series: dict[str, list[list[Any]]] = {}
        for tag, signal_id in zip(tags, wanted, strict=True):
            item = next(
                (s for s in answer.get("series") or [] if s.get("signal") == signal_id), None
            )
            if item is None:
                continue
            pairs = [
                [stamp, value]
                for stamp, value in zip(item.get("t") or [], item.get("v") or [], strict=False)
                if value is not None
            ]
            pairs = thin_extremes(pairs, max_points)
            series[tag] = [[_local_text(stamp, self.timezone), value] for stamp, value in pairs]
        failed = {error.get("signal") for error in answer.get("errors") or []}
        return {
            "start": pd.Timestamp(start).isoformat(),
            "end": pd.Timestamp(end).isoformat(),
            "series": series,
            "failed_tags": [
                tag for tag, signal_id in zip(tags, wanted, strict=True) if signal_id in failed
            ],
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
            "from_cache": False,
        }

    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            count = len(self.sources())
            result = {
                "ok": True,
                "message": t("The Historian answered: {count} sources.", count=count),
            }
        except DataLayerError as exc:
            result = {"ok": False, "message": exc.detail}
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["checked_at"] = pd.Timestamp.now(tz=self.timezone).isoformat(timespec="seconds")
        return result

    # Sources (kept in HistCraft) ----------------------------------------------------

    def sources(self) -> list[dict[str, Any]]:
        return [source_item(item) for item in _list(self.call("GET", "/sources"))]

    def source(self, source_id: str) -> dict[str, Any] | None:
        return next((item for item in self.sources() if item["source_id"] == source_id), None)

    def save_source(
        self,
        source_id: str,
        *,
        name: str,
        type: str,
        settings: dict[str, Any],
        password: str | None,
        create: bool,
    ) -> dict[str, Any]:
        body = source_body(source_id, name=name, type=type, settings=settings, password=password)
        if create:
            answer = self.call("POST", "/sources", json=body)
        else:
            body.pop("signals", None)
            answer = self.call("PUT", f"/sources/{_quoted(source_id)}", json=body)
        return source_item(answer if isinstance(answer, dict) else body)

    def remove_source(self, source_id: str) -> dict[str, Any]:
        """HistCraft keeps a source that still has signals (409, passed on)."""

        self.call("DELETE", f"/sources/{_quoted(source_id)}")
        return {"removed": source_id, "signals": 0}

    def add_signals(self, source_id: str, tags: list[str]) -> dict[str, Any]:
        """Signals of a source HistCraft starts collecting: ``{added: [ids], skipped}``."""

        answer = self.call(
            "POST", f"/sources/{_quoted(source_id)}/signals", json={"signals": list(tags)}
        )
        return answer if isinstance(answer, dict) else {"added": [], "skipped": []}

    def stop_signals(self, source_id: str, tags: list[str]) -> dict[str, Any]:
        """HistCraft stops using the source's signals and keeps their history: ``{updated}``.

        A tag HistCraft does not have was never used and is skipped; a derived signal is
        refused (422, passed on)."""

        updated = 0
        for tag in tags:
            signal_id = f"{source_id}:{tag}"
            try:
                self.call("PATCH", f"/signals/{_quoted(signal_id)}", json={"enabled": False})
            except DataLayerError as exc:
                if exc.status == 404:
                    continue
                raise
            updated += 1
        return {"updated": updated}

    def _test(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """A connection test: HistCraft's 502 (the source's own words) is ``ok: false``."""

        started = time.perf_counter()
        try:
            answer = self.call("POST", path, json=body)
            result = {"ok": bool((answer or {}).get("ok")), "message": _test_message(answer)}
        except DataLayerError as exc:
            if exc.status == 404:
                raise
            result = {"ok": False, "message": exc.detail}
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        result["checked_at"] = pd.Timestamp.now(tz=self.timezone).isoformat(timespec="seconds")
        return result

    def source_status(self, source_id: str) -> dict[str, Any]:
        """HistCraft tests the saved source's connection (``POST /sources/{id}/test``)."""

        return self._test(f"/sources/{_quoted(source_id)}/test", {})

    def test_source(
        self,
        source_id: str | None,
        *,
        type: str,
        settings: dict[str, Any],
        password: str | None,
    ) -> dict[str, Any]:
        """HistCraft tries settings not saved yet (``POST /sources/test``). Without a password
        it uses ``password_env`` or, for a saved ``source_id``, the stored one."""

        if not source_id and password is None and not settings.get("password_env"):
            password = ""  # nothing stored for a source not saved yet
        body = source_body(
            source_id or UNSAVED_ID,
            name=source_id or UNSAVED_ID,
            type=type,
            settings=settings,
            password=password,
        )
        body.pop("signals", None)
        return self._test("/sources/test", body)

    def browse_source(
        self, source_id: str, *, q: str = "", offset: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        """A page of the variables HistCraft finds on the source (``q`` is the browse root)."""

        wanted = min(BROWSE_MAX, offset + limit)
        body: dict[str, Any] = {"limit": max(1, wanted)}
        if q.strip():
            body["root"] = q.strip()
        answer = self.call("POST", f"/sources/{_quoted(source_id)}/browse", json=body)
        answer = answer if isinstance(answer, dict) else {}
        rows = [
            signal_row(item, source_id)
            for item in answer.get("variables") or []
            if isinstance(item, dict)
        ]
        return {
            "items": rows[offset : offset + limit],
            "total": len(rows),
            "offset": offset,
            "limit": limit,
            "truncated": bool(answer.get("truncated")),
        }


# Shapes (adapt here when HistCraft settles them) ------------------------------------


def source_body(
    source_id: str, *, name: str, type: str, settings: dict[str, Any], password: str | None
) -> dict[str, Any]:
    """PlantCraft's source settings (``DataSourceConfig`` fields) as HistCraft's source:
    ``{id, name, kind, endpoint, namespace_uri, username, password, password_env, options,
    signals}``. ``password`` None keeps the stored one."""

    allowed = KIND_OPTIONS.get(type, set(OPTIONS))
    options = {
        key: settings[key]
        for key in OPTIONS
        if key in allowed and settings.get(key) not in (None, "")
    }
    body: dict[str, Any] = {
        "id": source_id,
        "name": name,
        "kind": type,
        "endpoint": settings.get(ENDPOINT_FIELD.get(type, "endpoint_url")) or "",
        "username": settings.get("username") or "",
        "password": password,
        "password_env": settings.get("password_env") or "",
        "options": options,
        "signals": [str(tag) for tag in settings.get("tags") or []],
    }
    if type == "opcua" and settings.get("namespace_uri"):
        body["namespace_uri"] = settings["namespace_uri"]
    return body


def source_item(raw: dict[str, Any]) -> dict[str, Any]:
    """A HistCraft source as the Sources page lists one (``SourceRegistry.list`` shape)."""

    raw = raw if isinstance(raw, dict) else {}
    source_id = str(raw.get("id") or raw.get("source_id") or "")
    type = str(raw.get("kind") or raw.get("type") or "")
    options = raw.get("options") if isinstance(raw.get("options"), dict) else {}
    settings: dict[str, Any] = dict(options)
    endpoint = raw.get("endpoint") or None
    if endpoint:
        settings[ENDPOINT_FIELD.get(type, "endpoint_url")] = endpoint
    for key in ("namespace_uri", "username", "password_env"):
        if raw.get(key):
            settings[key] = raw[key]
    if raw.get("default_mode"):
        settings["mode"] = raw["default_mode"]
    added = raw.get("signals_added") if isinstance(raw.get("signals_added"), dict) else {}
    count = len(added.get("added") or []) if isinstance(added.get("added"), list) else 0
    return {
        "source_id": source_id,
        "name": str(raw.get("name") or source_id),
        "type": type,
        "type_label": t(SOURCE_TYPE_LABELS.get(type, type or "Historian")),
        "origin": "histcraft",
        "read_only": False,
        "endpoint": endpoint,
        "settings": settings,
        "has_password": bool(raw.get("has_password")),
        "configured_tags": count,
        "routed_signals": count,
        "monitored_signals": count,
        "updated_at": raw.get("updated_at"),
        "updated_by": raw.get("updated_by"),
        "enabled": raw.get("enabled", True) is not False,
        # The collector's view: {status: connected | disconnected, detail, since}; None for a
        # source it does not keep a connection to (a file) or before it first tried.
        "state": source_state(raw),
    }


def source_state(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The collector's view of a source. HistCraft's admin API names it ``state``, its data API
    (the one PlantCraft reads) ``status``; an ``{ok, message}`` answer is read the same way."""

    state = raw.get("state") if isinstance(raw.get("state"), dict) else raw.get("status")
    if not isinstance(state, dict):
        return None
    if "status" not in state and isinstance(state.get("ok"), bool):
        return {
            "status": "connected" if state["ok"] else "disconnected",
            "detail": str(state.get("message") or ""),
            "since": state.get("checked_at"),
        }
    return state


def signal_row(raw: dict[str, Any], source_id: str) -> dict[str, Any]:
    """A variable HistCraft browsed (``{address, tag, name, path, kind, step, unit, description,
    low, high}``) as the Sources page lists one."""

    tag = str(raw.get("tag") or raw.get("address") or "")
    path = str(raw.get("path") or "")
    return {
        "tag": tag,
        "name": str(raw.get("name") or tag),
        "asset": path,
        "path": path,
        "unit": str(raw.get("unit") or ""),
        "description": str(raw.get("description") or ""),
        "data_type": "text" if raw.get("kind") == "text" else "number",
        "address": raw.get("address"),
        "assets": [],
        "monitored": False,
        "read_from": source_id,
    }


def _test_message(answer: Any) -> str:
    detail = (answer or {}).get("detail") if isinstance(answer, dict) else None
    if isinstance(detail, dict):
        shown = ", ".join(
            f"{key}: {value}" for key, value in detail.items() if value not in (None, "")
        )
        return t("Connection established.") + (f" {shown}" if shown else "")
    return str(detail or t("Connection established."))


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, list):
        detail = "; ".join(str(item.get("msg", item)) for item in detail if isinstance(item, dict))
    return str(detail or response.reason_phrase or response.status_code)


def _local_text(stamp: str, timezone: str) -> str:
    """A UTC time from HistCraft as the naive local time the interface's charts use."""

    value = pd.Timestamp(stamp)
    if value.tzinfo is None:
        value = value.tz_localize("UTC")
    return value.tz_convert(timezone).tz_localize(None).isoformat()


def _receipt(answer: Any, items: list[Any]) -> dict[str, Any]:
    """HistCraft's ``{written, errors}``; API v1 also gives each error its index in the request."""

    if not isinstance(answer, dict):
        answer = {}
    first: dict[str, int] = {}
    for index, item in enumerate(items):
        first.setdefault(item.signal, index)
    errors = [
        {
            "index": error.get("index", first.get(error.get("signal"), 0)),
            "signal": error.get("signal"),
            "status": int(error.get("status") or 502),
            "detail": str(error.get("detail") or ""),
        }
        for error in answer.get("errors") or []
        if isinstance(error, dict)
    ]
    return {"written": int(answer.get("written") or 0), "errors": errors}
