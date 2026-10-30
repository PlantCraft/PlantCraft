"""PlantCraft from a notebook: signals, series, assets and results as pandas tables.

Everything is read through PlantCraft's API v1 with your own access, so a notebook never sees
more than you may. Times are the plant's local time (the installation's time zone,
``pc.zone()``): every table's index is a time in that zone, and a time written without an offset
means that zone too. ``pc.use_zone("UTC")`` shows them in UTC instead.

In PlantCraft's Notebooks (in the browser) there is nothing to set up. In Jupyter on your
computer, call ``connect(url, token=...)`` once, or set ``PLANTCRAFT_URL`` and
``PLANTCRAFT_TOKEN`` (an access token from Notebooks › Run on your computer).

    import plantcraft_notebook as pc
    pc.signals("FIC")
    data = pc.series(["plant:FIC-101.PV", "plant:FIC-101.SP"], "-7d", "now", step=60)
    pc.assets(type="loop")
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

__version__ = "0.2.0"
__all__ = [
    "PlantCraftError",
    "app",
    "apps",
    "asset",
    "asset_types",
    "assets",
    "connect",
    "events",
    "me",
    "results",
    "series",
    "signal",
    "signals",
    "sync",
    "use_zone",
    "value",
    "zone",
]

IN_BROWSER = sys.platform == "emscripten"
# Over its limits PlantCraft answers 429 with Retry-After: wait (at most MAX_WAIT s) and retry.
RETRIES = 4
MAX_WAIT = 30.0
# API v1 limits (docs/api-v1.md): ids per series request, days per request.
BATCH = 500
SPAN = timedelta(days=366)
_RELATIVE = re.compile(r"^\s*-\s*(\d+(?:\.\d+)?)\s*(s|m|h|d|w)\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_USER_DEFINED = {0xF780 + byte: 0x80 + byte for byte in range(128)}


class PlantCraftError(RuntimeError):
    """PlantCraft refused a request: ``status`` is the HTTP status, the message says why."""

    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


def _detail(text: str) -> str:
    """What PlantCraft said: its ``detail``, else the first characters of its answer."""

    try:
        detail = json.loads(text).get("detail")
    except (ValueError, AttributeError):
        detail = None
    return str(detail or text[:300] or "no answer")


_zone: str | None = None


def use_zone(name: str | None) -> None:
    """Show times in ``name`` (an IANA zone such as ``"UTC"`` or ``"America/Sao_Paulo"``);
    ``None`` goes back to the plant's local time."""

    global _zone
    if name is not None:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)  # an unknown name fails here, not in the middle of a read
    _zone = name


def zone() -> str:
    """The time zone the tables' times are in: the installation's (PlantCraft's Settings ›
    Installation) unless ``use_zone`` chose another; UTC when PlantCraft does not say."""

    global _zone
    if _zone is None:
        try:
            _zone = str(client().get("/api/v1/installation").get("time_zone") or "UTC")
        except PlantCraftError:
            return "UTC"
    return _zone


def moment(value: Any, *, now: datetime | None = None) -> datetime:
    """A UTC time from a datetime, a pandas Timestamp, an ISO text, ``"now"`` or ``"-7d"``; a
    time without an offset is the plant's local time (``zone()``)."""

    now = now or datetime.now(timezone.utc)
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value).strip()
        if text.lower() == "now":
            return now
        relative = _RELATIVE.match(text)
        if relative:
            return now - timedelta(seconds=float(relative.group(1)) * _UNITS[relative.group(2)])
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        from zoneinfo import ZoneInfo

        stamp = stamp.replace(tzinfo=ZoneInfo(zone()))
    return stamp.astimezone(timezone.utc)


def iso(stamp: datetime) -> str:
    return stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Client:
    """One PlantCraft: in the browser the page's own server and session, else a URL and token."""

    def __init__(self, url: str | None = None, token: str | None = None, ca: Any = None):
        self.url = (url or os.environ.get("PLANTCRAFT_URL") or "").rstrip("/")
        self.token = token or os.environ.get("PLANTCRAFT_TOKEN") or ""
        if not self.token and not IN_BROWSER and self.url:
            # The kit keeps the person's token in the system's vault ("Configure token").
            from plantcraft_notebook.kit import stored_token

            self.token = stored_token(self.url)
        self.ca = ca if ca is not None else os.environ.get("PLANTCRAFT_CA") or None
        if IN_BROWSER and not self.url:
            import js  # type: ignore[import-not-found]

            self.url = str(js.location.origin)
        if not self.url:
            raise PlantCraftError(
                0, "Say which PlantCraft: pc.connect('https://<server>', token='pcat_...')"
            )

    # Transport ------------------------------------------------------------------------

    def _browser(self, method: str, path: str, body: bytes | None) -> tuple[int, str, str]:
        """A synchronous request from the kernel's worker: the browser sends the session."""

        import js  # type: ignore[import-not-found]

        request = js.XMLHttpRequest.new()
        request.open(method, self.url + path, False)
        request.setRequestHeader("Accept", "application/json")
        if body is not None:
            request.setRequestHeader("Content-Type", "application/json")
        request.send(body.decode("utf-8") if body is not None else None)
        retry = request.getResponseHeader("Retry-After")
        return int(request.status), str(request.responseText), str(retry or "")

    def _context(self) -> ssl.SSLContext | None:
        if self.ca is False:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        if isinstance(self.ca, str) and self.ca:
            return ssl.create_default_context(cafile=self.ca)
        try:
            # The certificates this computer trusts (a company's own authority included).
            import truststore

            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            return None

    def _computer(self, method: str, path: str, body: bytes | None) -> tuple[int, str, str]:
        if not self.token:
            import getpass

            self.token = getpass.getpass("PlantCraft access token (pcat_...): ").strip()
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.token}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120, context=self._context()) as answer:
                return answer.status, answer.read().decode("utf-8"), ""
        except urllib.error.HTTPError as error:
            retry = error.headers.get("Retry-After") if error.headers else None
            return error.code, error.read().decode("utf-8", "replace"), str(retry or "")
        except urllib.error.URLError as error:
            # No answer at all: say why in one line instead of a traceback.
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                raise PlantCraftError(
                    0,
                    f"this computer does not trust {self.url}'s certificate "
                    f"({error.reason.verify_message}). Download the kit again from Notebooks > "
                    "Run on your computer, or ask the administrator for the local CA.",
                ) from None
            raise PlantCraftError(0, f"could not reach {self.url}: {error.reason}") from None

    def _send(self, method: str, path: str, body: bytes | None) -> tuple[int, str]:
        """One request; when PlantCraft asks to slow down (429) it waits and asks again."""

        send = self._browser if IN_BROWSER else self._computer
        for attempt in range(RETRIES + 1):
            status, text, retry = send(method, path, body)
            if status != 429 or attempt == RETRIES:
                return status, text
            try:
                wait = min(MAX_WAIT, max(1.0, float(retry)))
            except ValueError:
                wait = 2.0
            warnings.warn(
                f"PlantCraft asked to slow down: waiting {wait:.0f} s ({_detail(text)})",
                stacklevel=4,
            )
            time.sleep(wait)
        return status, text

    def request(self, method: str, path: str, payload: Any = None, **params: Any) -> Any:
        query = {key: value for key, value in params.items() if value is not None}
        if query:
            path += "?" + urllib.parse.urlencode(query, doseq=True)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        status, text = self._send(method, path, body)
        if status == 401 and IN_BROWSER:
            # The browser's token lasts 15 minutes: the session renews it.
            self._browser("POST", "/api/v1/auth/token", b"{}")
            status, text = self._send(method, path, body)
        if status >= 400 or status == 0:
            raise PlantCraftError(status, _detail(text))
        return json.loads(text) if text else None

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, **params)

    def download(self, path: str) -> bytes:
        """A file (an app's runtime): its bytes."""

        if IN_BROWSER:
            import js  # type: ignore[import-not-found]

            for attempt in range(2):
                request = js.XMLHttpRequest.new()
                request.open("GET", self.url + path, False)
                # Bytes as they are (a synchronous request takes no arraybuffer outside a worker).
                request.overrideMimeType("text/plain; charset=x-user-defined")
                request.send(None)
                if int(request.status) == 401 and attempt == 0:
                    self._browser("POST", "/api/v1/auth/token", b"{}")
                    continue
                break
            text = str(request.responseText)
            if int(request.status) >= 400:
                raise PlantCraftError(int(request.status), _detail(text))
            # x-user-defined gives the bytes 0x80-0xFF as U+F780-U+F7FF.
            return text.translate(_USER_DEFINED).encode("latin-1")
        if not self.token:
            self._computer("GET", "/api/v1/me", None)
        request = urllib.request.Request(
            self.url + path, method="GET", headers={"Authorization": f"Bearer {self.token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=300, context=self._context()) as answer:
                return answer.read()
        except urllib.error.HTTPError as error:
            raise PlantCraftError(
                error.code, _detail(error.read().decode("utf-8", "replace"))
            ) from None
        except urllib.error.URLError as error:
            raise PlantCraftError(0, f"could not reach {self.url}: {error.reason}") from None


_client: Client | None = None


def connect(url: str | None = None, token: str | None = None, ca: Any = None) -> Client:
    """Read from this PlantCraft from now on. ``ca`` is the path of your company's certificate
    authority (PEM) when the server's certificate is not one your computer trusts already."""

    global _client
    _client = Client(url, token, ca)
    return _client


def client() -> Client:
    return _client or connect()


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _table(rows: list[dict[str, Any]], index: str = "id") -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    return frame.set_index(index) if index in frame.columns else frame


# Reads --------------------------------------------------------------------------------


def me() -> dict[str, Any]:
    """Who the notebook reads as: name, access level and apps."""

    return client().get("/api/v1/me")


def signals(q: str | None = None) -> pd.DataFrame:
    """Signals whose id, name or description holds ``q`` (all of them without it)."""

    return _table(client().get("/api/v1/signals", q=q or None))


def signal(signal_id: str) -> dict[str, Any]:
    return client().get(f"/api/v1/signals/{_quote(signal_id)}")


def value(signal_id: str, agg: str = "last", window: str = "1h") -> Any:
    """One number: ``agg`` is last, mean, min, max or std over ``window`` (30m, 24h, 7d)."""

    found = client().get(f"/api/v1/signals/{_quote(signal_id)}/value", agg=agg, window=window)
    return found.get("value")


def _columns(answer: dict[str, Any]) -> list[pd.Series]:
    for error in answer.get("errors") or []:
        warnings.warn(f"{error.get('signal')}: {error.get('detail')}", stacklevel=3)
    columns = []
    for item in answer.get("series") or []:
        # Times come with and without a fraction of a second: ISO8601 reads both forms.
        index = pd.to_datetime(item.get("t") or [], utc=True, format="ISO8601")
        numbers = item.get("kind") != "text"
        values = pd.to_numeric(item.get("v") or [], errors="coerce") if numbers else item.get("v")
        column = pd.Series(values, index=index, name=item["signal"])
        columns.append(column[~column.index.duplicated(keep="last")])
    return columns


def series(
    signal_ids: str | list[str], start: Any = "-24h", end: Any = "now", step: float | None = None
) -> pd.DataFrame:
    """The signals' values from ``start`` to ``end``: one column per signal, indexed by time in
    the plant's local time (``zone()``).

    ``step`` (seconds) gives one mean per step (text signals: the last label); without it, the
    values as recorded. ``start`` and ``end`` take a datetime, an ISO text, ``"now"`` or a time
    back from now like ``"-7d"``. Long periods and many signals are read in parts.
    """

    ids = [signal_ids] if isinstance(signal_ids, str) else list(signal_ids)
    now = datetime.now(timezone.utc)
    begin, finish = moment(start, now=now), moment(end, now=now)
    if begin >= finish:
        raise ValueError("start must come before end")
    parts: list[pd.Series] = []
    piece = begin
    while piece < finish:
        until = min(finish, piece + SPAN)
        for first in range(0, len(ids), BATCH):
            payload = {
                "signals": ids[first : first + BATCH],
                "start": iso(piece),
                "end": iso(until),
            }
            if step:
                payload["step"] = step
            parts += _columns(client().request("POST", "/api/v1/series", payload))
        piece = until
    if not parts:
        return pd.DataFrame(index=pd.DatetimeIndex([], tz=zone(), name="time"), columns=ids)
    joined: dict[str, pd.Series] = {}
    for column in parts:
        before = joined.get(str(column.name))
        joined[str(column.name)] = column if before is None else pd.concat([before, column])
    frame = pd.concat(
        [joined[name][~joined[name].index.duplicated(keep="last")] for name in joined], axis=1
    ).sort_index()
    frame.index = frame.index.tz_convert(zone())
    frame.index.name = "time"
    return frame[[name for name in ids if name in frame.columns]]


def assets(
    kind: str | None = None, type: str | None = None, parent: str | None = None
) -> pd.DataFrame:
    """The plant tree: ``kind`` an exact type, ``type`` a type and its subtypes, ``parent`` an id."""

    return _table(client().get("/api/v1/assets", kind=kind, type=type, parent_id=parent))


def asset(asset_id: str) -> dict[str, Any]:
    """One asset: name, type, attributes, signals by role and relations."""

    return client().get(f"/api/v1/assets/{_quote(asset_id)}")


def asset_types() -> pd.DataFrame:
    return _table(client().get("/api/v1/asset-types"))


def results(
    subject: str | None = None, app: str | None = None, kind: str | None = None
) -> pd.DataFrame:
    """What the apps published last (loop health, signal quality, alarms...), per subject."""

    return pd.DataFrame(client().get("/api/v1/results", subject=subject, app=app, kind=kind))


def events(ref: str | None = None, kind: str | None = None, limit: int = 100) -> pd.DataFrame:
    """Findings, alarms raised and cleared, and the other events about ``ref``."""

    return pd.DataFrame(client().get("/api/v1/events", ref=ref, kind=kind, limit=limit))


from plantcraft_notebook.apps import app, apps  # noqa: E402 - built on the client above


def sync() -> dict[str, Any]:
    """In the Notebooks kit: refreshes ``Examples`` and copies the notebooks PlantCraft wrote for
    you into ``My notebooks``, never over one you edited. The browser has both folders already."""

    if IN_BROWSER:
        raise PlantCraftError(0, "In the browser, Examples and My notebooks are already here.")
    from plantcraft_notebook.kit import sync as kit_sync

    return kit_sync()
