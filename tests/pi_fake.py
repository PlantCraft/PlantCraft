"""A small PI Web API stand-in for tests: the endpoints, paging and errors the source uses.

It answers like PI Web API 2019+ does for path WebIDs, point lookup, recorded,
interpolated and recordedattime reads, and can inject the failures seen on
plant networks (503 bursts, refused path WebIDs, missing tags, bad values).
"""

from __future__ import annotations

import base64
import json
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np
import pandas as pd

SERVER = "PI-ARCHIVE-01"


def _stamp(value: pd.Timestamp) -> str:
    # PI Web API writes 7 fractional digits when the time has any.
    text = value.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.%f")
    return text + "0Z" if value.microsecond else text[:-7] + "Z"


class FakePi:
    def __init__(
        self,
        *,
        tags: dict[str, list[tuple[pd.Timestamp, object, bool]]] | None = None,
        user: tuple[str, str] | None = ("svc_processcraft", "segredo"),
        max_items: int = 150000,
        path_web_ids: bool = True,
    ):
        self.tags = tags if tags is not None else demo_tags()
        self.user = user
        self.max_items = max_items
        self.path_web_ids = path_web_ids
        self.fail_next: Counter[str] = Counter()
        self.calls: Counter[str] = Counter()
        self._lock = threading.Lock()
        handler = type("Handler", (_Handler,), {"pi": self})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}/piwebapi"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FakePi":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def tag_of(self, web_id: str) -> str | None:
        if web_id.startswith("F1DP"):
            return web_id[4:]
        if web_id.startswith("P1DP") and self.path_web_ids:
            encoded = web_id[4:].replace("-", "+").replace("_", "/")
            path = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
            server, _, tag = path.partition("\\")
            if server != SERVER:
                return None
            return next((name for name in self.tags if name.upper() == tag), None)
        return None


def demo_tags(hours: float = 96) -> dict[str, list[tuple[pd.Timestamp, object, bool]]]:
    """PV/SP/OP and MODE of one loop, plus a tag with an I/O failure in the middle."""

    end = pd.Timestamp.now(tz="UTC").floor("s") + pd.Timedelta(minutes=30)
    start = end - pd.Timedelta(hours=hours)
    rng = np.random.default_rng(7)
    # Irregular archive events, as exception/compression leave them.
    steps = rng.integers(5, 25, size=int(hours * 3600 / 5))
    stamps = start + pd.to_timedelta(np.cumsum(steps), unit="s")
    stamps = stamps[stamps <= end]
    t = (stamps - start).total_seconds().to_numpy()
    sp = 50 + 5 * (np.floor(t / 7200) % 2)
    pv = sp + np.sin(t / 300) + rng.normal(0, 0.2, len(t))
    op = 40 + 2 * np.cos(t / 300)
    pv_events = [(s, float(v), True) for s, v in zip(stamps, pv)]
    sp_events = [
        (stamps[i], float(sp[i]), True) for i in range(len(t)) if i == 0 or sp[i] != sp[i - 1]
    ]
    mode_events = [
        (start + pd.Timedelta(hours=h), {"Name": name, "Value": code, "IsSystem": False}, True)
        for h, name, code in [(0, "AUTO", 1), (hours / 2, "MAN", 0), (hours / 2 + 1, "AUTO", 1)]
    ]
    bad_input = {"Name": "Bad Input", "Value": 307, "IsSystem": True}
    flaky = [
        (s, bad_input, False)
        if hours * 0.4 < (s - start).total_seconds() / 3600 < hours * 0.45
        else (s, float(v), True)
        for s, v in zip(stamps, op)
    ]
    return {
        "FIC4241004": pv_events,
        "FIC4241004S": sp_events,
        "FIC4241004O": [(s, float(v), True) for s, v in zip(stamps, op)],
        "FIC4241004M": mode_events,
        "PIC4241048": flaky,
    }


class _Handler(BaseHTTPRequestHandler):
    pi: FakePi

    def log_message(self, *args) -> None:  # keep test output quiet
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

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        pi = self.pi
        url = urlparse(self.path)
        path = url.path.removeprefix("/piwebapi").strip("/")
        query = {key: values[-1] for key, values in parse_qs(url.query).items()}
        kind = path.rsplit("/", 1)[-1] if path.startswith("streams/") else path
        with pi._lock:
            pi.calls[kind] += 1
            if pi.fail_next[kind] > 0:
                pi.fail_next[kind] -= 1
                return self._send(503, {"Message": "Service Unavailable"})
        if pi.user is not None:
            header = self.headers.get("Authorization", "")
            expected = "Basic " + base64.b64encode(":".join(pi.user).encode()).decode()
            if header != expected:
                return self._send(
                    401,
                    {"Message": "Authorization denied."},
                    {"WWW-Authenticate": "Negotiate, Basic"},
                )
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            return self._send(403, {"Errors": ["CSRF header missing."]})

        if path == "dataservers":
            return self._send(
                200,
                {
                    "Items": [
                        {
                            "Name": SERVER.lower(),
                            "ServerVersion": "3.4.440.477",
                            "IsConnected": True,
                        }
                    ]
                },
            )
        if path == "system/userinfo":
            return self._send(200, {"Name": f"EXAMPLE\\{pi.user[0] if pi.user else 'anon'}"})
        if path == "points":
            server, _, tag = unquote(query.get("path", "")).lstrip("\\").partition("\\")
            name = next((n for n in pi.tags if n.upper() == tag.upper()), None)
            if server.upper() != SERVER or name is None:
                return self._send(404, {"Errors": [f"PI Point not found '{query.get('path')}'."]})
            digital = isinstance(pi.tags[name][0][1], dict) and not pi.tags[name][0][1].get(
                "IsSystem"
            )
            return self._send(
                200,
                {
                    "WebId": "F1DP" + name,
                    "Name": name,
                    "Descriptor": f"Descrição de {name}",
                    "EngineeringUnits": "" if digital else "m3/h",
                    "PointType": "Digital" if digital else "Float32",
                    "Step": name.endswith(("S", "M")),
                },
            )
        if path.startswith("streams/"):
            _, web_id, endpoint = path.split("/", 2)
            tag = pi.tag_of(web_id)
            if tag is None:
                return self._send(400, {"Errors": [f"Unknown or invalid WebID '{web_id}'."]})
            return self._stream(pi.tags[tag], endpoint, query)
        return self._send(404, {"Message": "No HTTP resource was found."})

    def _stream(self, events, endpoint: str, query: dict[str, str]) -> None:
        def item(stamp, value, good):
            return {"Timestamp": _stamp(stamp), "Value": value, "Good": good}

        if endpoint == "recorded":
            start, end = pd.Timestamp(query["startTime"]), pd.Timestamp(query["endTime"])
            count = int(query.get("maxCount", 1000))
            if count > self.pi.max_items:
                return self._send(
                    400,
                    {
                        "Errors": [
                            f"maxCount exceeds MaxReturnedItemsPerCall ({self.pi.max_items})."
                        ]
                    },
                )
            inside = [e for e in events if start <= e[0] <= end][:count]
            return self._send(200, {"Items": [item(*e) for e in inside]})
        if endpoint == "recordedattime":
            at = pd.Timestamp(query["time"])
            before = [e for e in events if e[0] <= at]
            if not before:
                return self._send(200, {"Timestamp": None, "Value": None, "Good": False})
            return self._send(200, item(*before[-1]))
        if endpoint == "interpolated":
            start, end = pd.Timestamp(query["startTime"]), pd.Timestamp(query["endTime"])
            grid = pd.date_range(start, end, freq=query["interval"].replace("s", "s"))
            if len(grid) > self.pi.max_items:
                return self._send(400, {"Errors": ["Too many values requested."]})
            stamps = pd.DatetimeIndex([e[0] for e in events])
            out = []
            for at in grid:
                position = stamps.searchsorted(at, side="right") - 1
                if position < 0:
                    out.append(item(at, {"Name": "No Data", "Value": 248, "IsSystem": True}, False))
                else:
                    out.append(item(at, *events[position][1:]))
            return self._send(200, {"Items": out})
        return self._send(404, {"Message": "No HTTP resource was found."})
