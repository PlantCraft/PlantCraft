"""PI Web API over the plant: the endpoints, paging and failures Historian's source uses.

Answers as PI Web API 2019+ does for the data server, point lookup by path, path WebIDs,
recorded, interpolated and recordedattime reads; MODE tags are digital (``{"Name": "AUTO"}``).
It only reads (any other method is 405 and counted) and can fail the way plant networks do:
``fail_next["recorded"] = 3`` answers 503 three times, ``delay_seconds`` slows every answer.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self
from urllib.parse import parse_qs, unquote, urlparse

from .plant import Series

SERVER = "PISRV"
SERVER_WEB_ID = "F1DSPISRV"
USER = ("svc_historian", "secret")
STATES = {"MAN": 0, "AUTO": 1, "CAS": 2, "REMOTE": 3}


def _stamp(ms: int) -> str:
    moment = datetime.fromtimestamp(ms / 1000, UTC)
    text = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{text}.{moment.microsecond:06d}0Z" if moment.microsecond else f"{text}Z"


def _ms(text: str) -> int:
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def _seconds(interval: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return float(interval[:-1]) * units[interval[-1]]


class PiWebApi:
    """``with PiWebApi(series) as pi: pi.base_url`` (127.0.0.1, a free port unless given)."""

    def __init__(
        self,
        series: dict[str, Series],
        *,
        user: tuple[str, str] | None = USER,
        port: int = 0,
        max_items: int = 150_000,
    ):
        self.series = series
        self.user = user
        self.max_items = max_items
        self.delay_seconds = 0.0
        self.fail_next: Counter[str] = Counter()
        self.calls: Counter[str] = Counter()
        self.methods: Counter[str] = Counter()
        self.lock = threading.Lock()
        handler = type("Handler", (_Handler,), {"pi": self})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}/piwebapi"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def tag_of(self, web_id: str) -> str | None:
        if web_id.startswith("F1DP"):
            return web_id[4:] if web_id[4:] in self.series else None
        if web_id.startswith("P1DP"):
            encoded = web_id[4:].replace("-", "+").replace("_", "/")
            path = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
            server, _, tag = path.partition("\\")
            if server != SERVER:
                return None
            return next((name for name in self.series if name.upper() == tag), None)
        return None

    def value(self, tag: str, value: float | str) -> Any:
        if self.series[tag].kind == "text":
            return {"Name": value, "Value": STATES.get(str(value), 9), "IsSystem": False}
        return value

    def point(self, tag: str) -> dict[str, Any]:
        item = self.series[tag]
        digital = item.kind == "text"
        return {
            "WebId": "F1DP" + tag,
            "Name": tag,
            "Descriptor": f"{tag} of the Simulator's plant",
            "EngineeringUnits": "" if digital else item.unit,
            "PointType": "Digital" if digital else "Float64",
            "Step": tag.endswith((".SP", ".MODE")),
        }


class _Handler(BaseHTTPRequestHandler):
    pi: PiWebApi

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, status: int, body: object, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _refuse(self) -> None:
        with self.pi.lock:
            self.pi.methods[self.command] += 1
        self._send(405, {"Message": "This PI Web API only reads."})

    do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

    def do_GET(self) -> None:
        pi = self.pi
        url = urlparse(self.path)
        path = url.path.removeprefix("/piwebapi").strip("/")
        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        kind = path.rsplit("/", 1)[-1] if path.startswith("streams/") else path
        with pi.lock:
            pi.methods["GET"] += 1
            pi.calls[kind] += 1
            failing = pi.fail_next[kind] > 0
            if failing:
                pi.fail_next[kind] -= 1
        if pi.delay_seconds:
            time.sleep(pi.delay_seconds)
        if failing:
            return self._send(503, {"Message": "Service Unavailable"})
        if pi.user is not None:
            expected = "Basic " + base64.b64encode(":".join(pi.user).encode()).decode()
            if self.headers.get("Authorization", "") != expected:
                return self._send(
                    401, {"Message": "Authorization denied."}, {"WWW-Authenticate": "Basic"}
                )
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            return self._send(403, {"Errors": ["CSRF header missing."]})
        if path == "dataservers":
            server = {"WebId": SERVER_WEB_ID, "Name": SERVER.lower(), "IsConnected": True}
            return self._send(200, {"Items": [{**server, "ServerVersion": "3.4.440.477"}]})
        if path == "system/userinfo":
            return self._send(200, {"Name": f"PLANT\\{pi.user[0] if pi.user else 'anonymous'}"})
        if path == f"dataservers/{SERVER_WEB_ID}/points":
            pattern = query.get("nameFilter", "*").upper()
            names = [n for n in pi.series if fnmatch.fnmatchcase(n.upper(), pattern)]
            first, count = int(query.get("startIndex", 0)), int(query.get("maxCount", 1000))
            return self._send(200, {"Items": [pi.point(n) for n in names[first : first + count]]})
        if path == "points":
            server, _, tag = unquote(query.get("path", "")).lstrip("\\").partition("\\")
            name = next((n for n in pi.series if n.upper() == tag.upper()), None)
            if server.upper() != SERVER or name is None:
                return self._send(404, {"Errors": [f"PI Point not found '{query.get('path')}'."]})
            return self._send(200, pi.point(name))
        if path.startswith("streams/") and path.count("/") == 2:
            _, web_id, endpoint = path.split("/")
            tag = pi.tag_of(web_id)
            if tag is None:
                return self._send(400, {"Errors": [f"Unknown or invalid WebID '{web_id}'."]})
            return self._stream(tag, endpoint, query)
        return self._send(404, {"Message": "No HTTP resource was found."})

    def _stream(self, tag: str, endpoint: str, query: dict[str, str]) -> None:
        pi = self.pi
        item = pi.series[tag]
        events = list(zip(item.times, item.values, strict=True))

        def answer(ms: int, value: float | str) -> dict[str, Any]:
            return {"Timestamp": _stamp(ms), "Value": pi.value(tag, value), "Good": True}

        if endpoint == "recorded":
            start, end = _ms(query["startTime"]), _ms(query["endTime"])
            count = int(query.get("maxCount", 1000))
            if count > pi.max_items:
                message = f"maxCount exceeds MaxReturnedItemsPerCall ({pi.max_items})."
                return self._send(400, {"Errors": [message]})
            inside = [answer(*e) for e in events if start <= e[0] <= end][:count]
            return self._send(200, {"Items": inside})
        if endpoint == "recordedattime":
            before = [e for e in events if e[0] <= _ms(query["time"])]
            if not before:
                return self._send(200, {"Timestamp": None, "Value": None, "Good": False})
            return self._send(200, answer(*before[-1]))
        if endpoint == "interpolated":
            start, end = _ms(query["startTime"]), _ms(query["endTime"])
            step = int(_seconds(query["interval"]) * 1000)
            grid = list(range(start, end + 1, step))
            if len(grid) > pi.max_items:
                return self._send(400, {"Errors": ["Too many values requested."]})
            out = []
            for at in grid:
                before = [e for e in events if e[0] <= at]
                if not before:
                    no_data = {"Name": "No Data", "Value": 248, "IsSystem": True}
                    out.append({"Timestamp": _stamp(at), "Value": no_data, "Good": False})
                else:
                    out.append(answer(at, before[-1][1]))
            return self._send(200, {"Items": out})
        return self._send(404, {"Message": "No HTTP resource was found."})
