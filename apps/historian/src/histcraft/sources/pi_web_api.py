"""PI Web API source: recorded or interpolated reads, hardened for a plant network.

What it handles so the pilot does not stall on the first day:

- transient failures (429, 5xx, dropped connections) are retried with backoff;
- tags are read in parallel, each thread with its own authenticated session;
- recorded reads are paged past ``MaxReturnedItemsPerCall`` and interpolated
  reads are split into chunks, so long windows and short intervals both work;
- times go to the server in UTC, so the host clock's zone does not matter;
- bad values and system digital states ("Bad Input", "I/O Timeout") become
  gaps, and controller modes come back as labels (AUTO, MAN), not state codes;
- a tag whose path WebID is refused is looked up once by path;
- errors are worded for the engineer: what failed and what to check.

Ported from PlantCraft (``industrial_data/pi_web_api.py``). Read-only: every call is
a GET (``tests/test_source_history.py`` checks the stand-in server sees nothing else).
"""

from __future__ import annotations

import logging
import threading
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from histcraft.i18n import t
from histcraft.sources.config import NO_VALUE, SignalInfo, SourceConfig, asset_from_tag

logger = logging.getLogger(__name__)

# PI Web API needs this header to accept requests that are not from a browser
# form (CSRF defence); without it some installations answer 403.
_HEADERS = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
_FIELDS = "Items.Timestamp;Items.Value;Items.Good"
# Recorded paging stops here even if the server keeps answering full pages.
_MAX_PAGES = 500
# Points listed per call when browsing a Data Archive.
_SEARCH_PAGE = 1000


class PiError(RuntimeError):
    """A PI Web API failure with a message meant for the engineer."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def make_web_id(server: str, tag: str) -> str:
    """Path-only WebID 2.0 of a PI Point (``P1DP`` + base64url of ``SERVER\\TAG``)."""

    path = f"{server}\\{tag}".upper()
    encoded = b64encode(path.encode()).decode().rstrip("=").replace("+", "-").replace("/", "_")
    return "P1DP" + encoded


def normalize_value(value: Any, good: bool = True) -> Any:
    """A PI value as the platform reads it: a number, a label or ``None`` for a gap."""

    if not good:
        return None
    if isinstance(value, dict):
        # Digital state: {"Name": "AUTO", "Value": 1, "IsSystem": false}.
        if value.get("IsSystem"):
            return None
        if "Name" in value:
            return value["Name"]
        if "Value" in value:
            return normalize_value(value["Value"])
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


class PiWebApiSource:
    """Read PI Points through PI Web API."""

    def __init__(self, config: SourceConfig):
        self.config = config
        self.failed_tags: list[tuple[str, str]] = []
        self.base_url = config.base_url.rstrip("/")
        self._local = threading.local()
        self._web_ids: dict[str, str] = {}
        self._points: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        # Long-lived workers keep their authenticated sessions between reads.
        self._pool = ThreadPoolExecutor(max_workers=config.max_workers, thread_name_prefix="pi")

    # --- HTTP ---------------------------------------------------------------

    def _auth(self):
        auth_type = self.config.auth_type
        if auth_type in {"basic", "ntlm"}:
            password = self.config.secret()
            if not self.config.username or not password:
                raise PiError(
                    t(
                        "{auth} authentication needs the user name and the password of the source.",
                        auth=auth_type,
                    )
                )
            if auth_type == "basic":
                return requests.auth.HTTPBasicAuth(self.config.username, password)
            try:
                from requests_ntlm import HttpNtlmAuth
            except ImportError as exc:
                raise PiError(
                    t(
                        "NTLM authentication needs the requests-ntlm package: "
                        "python3 -m pip install requests-ntlm"
                    )
                ) from exc
            return HttpNtlmAuth(self.config.username, password)
        try:
            from requests_kerberos import OPTIONAL, HTTPKerberosAuth
        except ImportError as exc:
            raise PiError(
                t(
                    "A PI source with Kerberos needs the requests-kerberos package: "
                    "python3 -m pip install -e '.[pi]'"
                )
            ) from exc
        return HTTPKerberosAuth(mutual_authentication=OPTIONAL)

    def _session(self) -> requests.Session:
        """One session per thread: sessions and Kerberos contexts are not thread-safe."""

        session = getattr(self._local, "session", None)
        if session is not None:
            return session
        session = requests.Session()
        session.auth = self._auth()
        session.verify = self.config.ca_bundle or self.config.verify_ssl
        session.headers.update(_HEADERS)
        retry = Retry(
            total=self.config.retries,
            connect=self.config.retries,
            read=self.config.retries,
            status=self.config.retries,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=self.config.max_workers)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        self._local.session = session
        return session

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``path`` under the base URL and return the JSON body, or raise ``PiError``."""

        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        host = urlparse(self.base_url).hostname or self.base_url
        try:
            response = self._session().get(url, params=params, timeout=self.config.timeout_seconds)
        except PiError:
            raise
        except requests.exceptions.SSLError as exc:
            raise PiError(
                t(
                    "The TLS certificate of {host} is not accepted by this server. Install the "
                    "corporate CA chain and point 'ca_bundle' to the PEM file. Detail: {error}",
                    host=host,
                    error=_short(exc),
                )
            ) from exc
        except requests.exceptions.ConnectTimeout as exc:
            raise PiError(
                t(
                    "Timed out connecting to {host}. Check the route, the firewall and whether the "
                    "address must bypass the proxy (NO_PROXY).",
                    host=host,
                )
            ) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise PiError(
                t(
                    "{host} accepted the connection but did not answer in {seconds} s. "
                    "Increase 'timeout_seconds' or shorten the window read.",
                    host=host,
                    seconds=f"{self.config.timeout_seconds:g}",
                )
            ) from exc
        except requests.exceptions.ProxyError as exc:
            raise PiError(
                t(
                    "The proxy refused the connection to {host}. Add the address to NO_PROXY.",
                    host=host,
                )
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise PiError(
                t(
                    "No connection to {host}: {error}. Check DNS, route and firewall.",
                    host=host,
                    error=_short(exc),
                )
            ) from exc
        except requests.exceptions.RetryError as exc:
            raise PiError(
                t(
                    "{host} kept failing after {count} attempts: {error}",
                    host=host,
                    count=self.config.retries,
                    error=_short(exc),
                )
            ) from exc
        return self._payload(response)

    def _payload(self, response: requests.Response) -> Any:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        errors = _errors(payload)
        status = response.status_code
        if status == 401:
            offered = response.headers.get("WWW-Authenticate", "")
            hint = t(" The server accepts: {offered}.", offered=offered) if offered else ""
            kerberos = (
                t(
                    " With Kerberos, check the service user's ticket (klist) and the HTTP/ SPN "
                    "of the PI Web API server."
                )
                if self.config.auth_type == "kerberos"
                else ""
            )
            raise PiError(
                t("PI Web API refused the {auth} authentication.", auth=self.config.auth_type)
                + hint
                + kerberos,
                status=status,
            )
        if status == 403:
            raise PiError(
                t("The authenticated user has no permission for this read in PI Web API.")
                + (f" {errors}" if errors else ""),
                status=status,
            )
        if status >= 400 or (errors and not _items(payload)):
            detail = errors or response.reason or t("no detail")
            raise PiError(
                t("PI Web API answered {status}: {detail}", status=status, detail=detail),
                status=status,
            )
        if payload is None:
            raise PiError(
                t(
                    "Unexpected answer from PI Web API (not JSON) at {url}. "
                    "Check that the address ends in /piwebapi.",
                    url=response.url,
                ),
                status=status,
            )
        return payload

    # --- Points -------------------------------------------------------------

    def _point_path(self, tag: str) -> str:
        return f"\\\\{self.config.server}\\{tag}"

    def point(self, tag: str) -> dict[str, Any]:
        """The PI Point's attributes (WebId, unit, descriptor, step), looked up by path."""

        with self._lock:
            if tag in self._points:
                return self._points[tag]
        try:
            point = self.get(
                "points",
                {
                    "path": self._point_path(tag),
                    "selectedFields": "WebId;Name;Descriptor;EngineeringUnits;PointType;Step",
                },
            )
        except PiError as exc:
            if exc.status in {400, 404}:
                raise PiError(
                    t(
                        "tag {tag} does not exist on server {server}",
                        tag=tag,
                        server=self.config.server,
                    ),
                    status=exc.status,
                ) from exc
            raise
        with self._lock:
            self._points[tag] = point
            if point.get("WebId"):
                self._web_ids[tag] = point["WebId"]
        return point

    def _web_id(self, tag: str) -> str:
        with self._lock:
            return self._web_ids.get(tag) or make_web_id(self.config.server or "", tag)

    def _stream(self, tag: str, endpoint: str, params: dict[str, Any]) -> Any:
        """Read one stream endpoint; when the path WebID is refused, look the tag up once."""

        try:
            return self.get(f"streams/{self._web_id(tag)}/{endpoint}", params)
        except PiError as exc:
            with self._lock:
                looked_up = tag in self._points
            if exc.status not in {400, 404} or looked_up:
                raise
        web_id = self.point(tag)["WebId"]
        return self.get(f"streams/{web_id}/{endpoint}", params)

    # --- Reads --------------------------------------------------------------

    def _utc(self, value: str | datetime | pd.Timestamp) -> pd.Timestamp:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize(self.config.timezone)
        return stamp.tz_convert("UTC")

    def _local_index(self, stamps: list[Any]) -> pd.DatetimeIndex:
        index = pd.to_datetime(stamps, utc=True, errors="coerce", format="ISO8601")
        return index.tz_convert(self.config.timezone).tz_localize(None)

    def _series(self, items: list[dict[str, Any]], name: str) -> pd.Series:
        if not items:
            return pd.Series(dtype=object, name=name)
        index = self._local_index([item.get("Timestamp") for item in items])
        values = [normalize_value(item.get("Value"), item.get("Good", True)) for item in items]
        series = pd.Series(np.asarray(values, dtype=object), index=index, name=name)
        series = series.loc[~series.index.isna()]
        return series.loc[~series.index.duplicated(keep="last")].sort_index()

    def recorded(self, tag: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
        """Archived events of ``tag`` in [start, end], paged past the per-call limit."""

        pages: list[dict[str, Any]] = []
        cursor = start
        for _ in range(_MAX_PAGES):
            payload = self._stream(
                tag,
                "recorded",
                {
                    "startTime": _iso(cursor),
                    "endTime": _iso(end),
                    "boundaryType": "Inside",
                    "maxCount": self.config.page_size,
                    "selectedFields": _FIELDS,
                },
            )
            items = _items(payload)
            pages.extend(items)
            if len(items) < self.config.page_size:
                break
            last = pd.Timestamp(items[-1]["Timestamp"]).tz_convert("UTC")
            if last <= cursor:
                # A full page on one timestamp: step past it rather than loop.
                last = cursor + pd.Timedelta(milliseconds=1)
            cursor = last
        else:
            logger.warning("Read of %s stopped after %d pages", tag, _MAX_PAGES)
        return self._series(pages, tag)

    def interpolated(
        self, tag: str, start: pd.Timestamp, end: pd.Timestamp, sample_seconds: int
    ) -> pd.Series:
        """Values every ``sample_seconds``, in chunks small enough for one call each."""

        chunk = pd.Timedelta(seconds=sample_seconds * (self.config.page_size - 1))
        pieces: list[dict[str, Any]] = []
        cursor = start
        while cursor < end:
            stop = min(cursor + chunk, end)
            payload = self._stream(
                tag,
                "interpolated",
                {
                    "startTime": _iso(cursor),
                    "endTime": _iso(stop),
                    "interval": f"{sample_seconds}s",
                    "selectedFields": _FIELDS,
                },
            )
            pieces.extend(_items(payload))
            cursor = stop
        return self._series(pieces, tag)

    def value_before(self, tag: str, start: pd.Timestamp) -> pd.Series:
        """The last archived value at or before ``start`` (step signals: SP, MODE)."""

        payload = self._stream(
            tag,
            "recordedattime",
            {"time": _iso(start), "retrievalMode": "AtOrBefore"},
        )
        return self._series([payload] if payload.get("Timestamp") else [], tag)

    def recorded_with_boundary(
        self,
        tag: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        *,
        boundary_at_start: bool = False,
    ) -> pd.Series:
        """Recorded events in [start, end] and the last value before ``start``.

        That value keeps its own time unless ``boundary_at_start`` moves it to ``start``
        (what the DataFrame reads do, so step signals are known from the first row).
        """

        series = self.recorded(tag, start, end)
        # A tag with nothing before start answers an empty value; any other failure is the
        # read's failure, never a silently missing first value.
        before = self.value_before(tag, start).dropna()
        local_start = start.tz_convert(self.config.timezone).tz_localize(None)
        if not before.empty:
            stamp = local_start if boundary_at_start else before.index[-1]
            if stamp not in series.index:
                series = pd.concat(
                    [pd.Series([before.iloc[-1]], index=[stamp], dtype=object), series]
                )
        return series

    def _read_tag(
        self,
        tag: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        sample_seconds: int,
        include_boundary: bool,
    ) -> pd.Series:
        if self.config.read_mode == "interpolated":
            series = self.interpolated(tag, start, end, sample_seconds)
        elif include_boundary:
            series = self.recorded_with_boundary(tag, start, end, boundary_at_start=True)
        else:
            series = self.recorded(tag, start, end)
        if series.dropna().empty:
            raise PiError(NO_VALUE + " in the requested interval")
        return series

    def read_recorded(
        self, tags: list[str], start: pd.Timestamp, end: pd.Timestamp
    ) -> dict[str, pd.Series | str]:
        """Per tag, its recorded events with the earlier boundary value, or why it failed.

        ``start`` and ``end`` are aware timestamps. Bad values stay in the series as ``None``.
        """

        start_utc, end_utc = self._utc(start), self._utc(end)

        def read(tag: str) -> tuple[str, pd.Series | str]:
            try:
                return tag, self.recorded_with_boundary(tag, start_utc, end_utc)
            except Exception as exc:  # one tag must not sink the others
                return tag, str(exc) or type(exc).__name__

        return dict(self._pool.map(read, tags))

    def read_window(self, minutes: int, sample_seconds: int) -> pd.DataFrame:
        end = pd.Timestamp.now(tz="UTC")
        return self.read_range(end - pd.Timedelta(minutes=minutes), end, sample_seconds)

    def read_range(
        self,
        start: str | datetime,
        end: str | datetime,
        sample_seconds: int,
        *,
        tags: list[str] | None = None,
        include_boundary: bool = True,
    ) -> pd.DataFrame:
        start_utc, end_utc = self._utc(start), self._utc(end)
        if start_utc >= end_utc:
            raise ValueError(t("The start of the PI read must come before the end."))
        wanted = list(tags if tags is not None else self.config.tags)

        def read(tag: str) -> tuple[str, pd.Series | None, str | None]:
            try:
                series = self._read_tag(tag, start_utc, end_utc, sample_seconds, include_boundary)
                return tag, series, None
            except Exception as exc:  # one tag must not sink the others
                return tag, None, str(exc) or type(exc).__name__

        results = list(self._pool.map(read, wanted))

        series: dict[str, pd.Series] = {}
        failures: list[tuple[str, str]] = []
        for tag, values, error in results:
            if error:
                quiet = error.startswith(NO_VALUE)
                logger.log(logging.DEBUG if quiet else logging.WARNING, "PI %s: %s", tag, error)
                failures.append((tag, error))
            elif values is not None:
                column = self.config.mapping.get(tag, tag)
                series[column] = values.rename(column)
        self.failed_tags = failures
        if not series:
            details = "; ".join(f"{tag}: {reason}" for tag, reason in failures[:5])
            raise RuntimeError(t("No tag was loaded from PI. {details}", details=details))
        frame = pd.concat(series.values(), axis=1).sort_index()
        return frame.loc[~frame.index.duplicated(keep="last")]

    # --- Catalogue and status -----------------------------------------------

    def list_signals(self) -> list[SignalInfo]:
        def describe(tag: str):
            try:
                point = self.point(tag)
            except Exception:  # an unreachable server still lists the configured tags
                point = {}
            text = str(point.get("PointType") or "").lower() in {"digital", "string"}
            return SignalInfo(
                tag=tag,
                name=tag,
                asset=asset_from_tag(tag),
                unit=str(point.get("EngineeringUnits") or ""),
                description=str(point.get("Descriptor") or ""),
                data_type="text" if text else "number",
                step=bool(point.get("Step")),
            )

        return list(self._pool.map(describe, self.config.tags))

    def search_points(self, name_filter: str, limit: int) -> tuple[list[dict[str, Any]], bool]:
        """Points of the Data Archive whose name matches ``name_filter`` (``*`` and ``?``).

        Returns at most ``limit`` points and whether more were left out.
        """

        server = self.data_server()
        web_id = server.get("WebId")
        if not web_id:
            raise PiError(
                t(
                    "PI Web API did not give the WebId of server {server}.",
                    server=self.config.server,
                )
            )
        found: list[dict[str, Any]] = []
        start_index = 0
        while len(found) <= limit:
            count = min(_SEARCH_PAGE, self.config.page_size, limit + 1 - len(found))
            payload = self.get(
                f"dataservers/{web_id}/points",
                {
                    "nameFilter": name_filter or "*",
                    "startIndex": start_index,
                    "maxCount": count,
                    "selectedFields": "Items.Name;Items.Descriptor;Items.EngineeringUnits;"
                    "Items.PointType;Items.Step;Items.Zero;Items.Span",
                },
            )
            items = _items(payload)
            found.extend(items)
            start_index += len(items)
            if len(items) < count:
                break
        return found[:limit], len(found) > limit

    def data_server(self) -> dict[str, Any]:
        """The configured Data Archive as PI Web API lists it, or raise."""

        payload = self.get(
            "dataservers",
            {"selectedFields": "Items.WebId;Items.Name;Items.ServerVersion;Items.IsConnected"},
        )
        servers = _items(payload)
        wanted = (self.config.server or "").lower()
        for item in servers:
            if str(item.get("Name", "")).lower() == wanted:
                if item.get("IsConnected") is False:
                    raise PiError(
                        t(
                            "PI Web API has no connection to server {server}.",
                            server=self.config.server,
                        )
                    )
                return item
        names = ", ".join(str(item.get("Name")) for item in servers) or t("none")
        raise PiError(
            t(
                "PI server {server} does not appear in PI Web API (servers: {names}).",
                server=self.config.server,
                names=names,
            )
        )

    def user(self) -> dict[str, Any]:
        """Who the PI Web API sees (``system/userinfo``), useful to debug Kerberos."""

        return self.get("system/userinfo")

    def test_connection(self) -> str:
        server = self.data_server()
        version = server.get("ServerVersion")
        message = t("Server {name}", name=server.get("Name"))
        if version:
            message += f" (PI Data Archive {version})"
        try:
            name = self.user().get("Name")
        except PiError:
            name = None
        if name:
            message += t(", user {name}", name=name)
        return message + "."


def _iso(stamp: pd.Timestamp) -> str:
    return stamp.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return payload.get("Items") or []
    return []


def _errors(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    errors = payload.get("Errors") or []
    if isinstance(payload.get("Message"), str):
        errors = [*errors, payload["Message"]]
    return "; ".join(str(error) for error in errors)


def _short(exc: Exception) -> str:
    text = str(exc)
    return text if len(text) <= 240 else text[:237] + "..."
