"""Benchmark one monitoring round against an in-process PlantCraft.

::

    python -m linkcraft.bench --loops 2000 --processes 4 --latency-ms 2

Builds a ``FakePlantCraft`` (from ``plantcraft_sdk.testing``) with
``--loops`` loop assets of three signals each, serves it over HTTP on a local
port (uvicorn, as the real PlantCraft is served), adds ``--latency-ms`` to
every HTTP request Analytics sends, then times a cold round (loop sync, every
series read and analysed) and a warm one. Nothing leaves the host; the
database lives in a temporary folder.

Real HTTP is the default because it is the honest number: the series travel
as JSON through sockets and a separate server, as they do from PlantCraft.
``--transport mock`` runs the fake in process (``httpx.MockTransport``) to
time Analytics alone.
"""

from __future__ import annotations

import argparse
import json
import socket
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from linkcraft.api.runtime import Runtime
from linkcraft.config import AnalysisConfig, Settings
from linkcraft.engine.compute import ComputePool

LOOPS_PER_AREA = 50
# The source id of the bench plant's signals.
SOURCE = "bench"


def plant(loop_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Loop assets (one area per 50 loops) and their PV/SP/OP signals."""

    assets: list[dict[str, Any]] = [
        {"id": "site", "name": "Site", "kind": "site", "parent_id": None},
        {"id": "unit", "name": "Unit", "kind": "unit", "parent_id": "site"},
    ]
    signals: list[dict[str, Any]] = []
    for number in range(loop_count):
        area = f"area-{number // LOOPS_PER_AREA}"
        if number % LOOPS_PER_AREA == 0:
            assets.append({"id": area, "name": area.title(), "kind": "area", "parent_id": "unit"})
        tag = f"LC-{number:05d}"
        # API v1 signal ids name their source: ``<source id>:<tag>``.
        roles = {role: f"{SOURCE}:{tag}.{role.upper()}" for role in ("pv", "sp", "op")}
        assets.append(
            {
                "id": tag.lower(),
                "name": tag,
                "kind": "loop",
                "parent_id": area,
                "attributes": {"description": f"Bench loop {number}"},
                "signals": roles,
            }
        )
        signals += [
            {
                "id": signal_id,
                "name": signal_id,
                "source": SOURCE,
                "unit": "%",
                "low": 0.0,
                "high": 100.0,
            }
            for signal_id in roles.values()
        ]
    return assets, signals


# What Analytics publishes to the suite (results, events, runs, schedules and, with PUT, derived
# series), counted apart.
SUITE_PATHS = ("/api/v1/results", "/api/v1/events", "/api/v1/runs", "/api/v1/schedules")
SERIES_PATH = "/api/v1/series"


class RequestMeter:
    """An httpx request hook: counts every request and waits ``latency`` seconds before it.

    ``suite`` counts the requests to the suite endpoints among them, ``event_requests`` the
    event posts and ``events`` the events they carry (a list holds up to 1,000),
    ``series_requests`` the derived series writes (``PUT``; a ``POST`` there is a read).
    """

    def __init__(self, latency: float):
        self.latency = latency
        self.requests = self.suite = self.event_requests = self.events = 0
        self.series_requests = 0
        self._lock = threading.Lock()

    def __call__(self, request: Any) -> None:
        path = str(getattr(getattr(request, "url", None), "path", ""))
        carried = _event_count(request) if path == "/api/v1/events" else 0
        series = path == SERIES_PATH and getattr(request, "method", "") == "PUT"
        with self._lock:
            self.requests += 1
            self.suite += path.startswith(SUITE_PATHS) or series
            self.series_requests += series
            self.event_requests += path == "/api/v1/events"
            self.events += carried
        if self.latency:
            time.sleep(self.latency)


def _event_count(request: Any) -> int:
    """Events in a ``POST /api/v1/events`` body: a list's length, else one."""

    if getattr(request, "method", "") != "POST":
        return 0
    try:
        body = json.loads(request.content or b"null")
    except (ValueError, TypeError):
        return 0
    return len(body) if isinstance(body, list) else 1


def _serve(app: Any, sock: socket.socket) -> None:
    import uvicorn

    config = uvicorn.Config(app, log_level="warning", access_log=False)
    uvicorn.Server(config).run(sockets=[sock])


@contextmanager
def served(app: Any, processes: int = 1):
    """Serve an ASGI app on a free local port, from ``processes`` forked servers.

    The servers are forked after the app is built, so they share its keys and
    data: a token one of them signs is valid at the others.
    """

    import multiprocessing

    import httpx

    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1024)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    context = multiprocessing.get_context("fork")
    servers = [
        context.Process(target=_serve, args=(app, sock), daemon=True)
        for _ in range(max(1, processes))
    ]
    for server in servers:
        server.start()
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                httpx.get(f"{url}/api/v1/auth/keys", timeout=2)
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise RuntimeError("The fake PlantCraft did not start.") from None
                time.sleep(0.1)
        yield url
    finally:
        for server in servers:
            server.terminate()
        for server in servers:
            server.join(timeout=10)
        sock.close()


def run(
    loops: int,
    processes: int,
    latency_ms: float,
    hours: float = 6.0,
    folder: Path | None = None,
    server_processes: int = 4,
    transport: str = "http",
) -> dict[str, Any]:
    import httpx
    from plantcraft_sdk.client import PlantCraftClient
    from plantcraft_sdk.testing import BASE_URL, FakePlantCraft

    assets, signals = plant(loops)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fake = FakePlantCraft(
        assets=assets,
        signals=signals,
        now=now,
        apps=[
            {"id": "linkcraft", "name": "PlantCraft Analytics", "url": "/link/", "version": "0.1.0"}
        ],
        users={
            "engineer": {"name": "Engineer", "level": "editor", "apps": {"linkcraft": "editor"}}
        },
        app_keys={"linkcraft": "test-app-key"},
    )
    meter = RequestMeter(latency_ms / 1000)
    with ExitStack() as stack:
        if transport == "mock":
            url = BASE_URL
            http = fake.http_client()
            http.timeout = httpx.Timeout(60)
        else:
            url = stack.enter_context(served(fake.app, server_processes))
            http = httpx.Client(timeout=60, limits=httpx.Limits(max_connections=32))
        stack.callback(http.close)
        http.event_hooks["request"] = [meter]
        scratch = stack.enter_context(tempfile.TemporaryDirectory())
        service = PlantCraftClient(url, app="linkcraft", key="test-app-key", http_client=http)
        settings = Settings(
            processcraft_url=url,
            data_dir=folder or Path(scratch),
            scheduler_enabled=False,
            analysis=AnalysisConfig(window_minutes=int(hours * 60), resample_seconds=10),
        )
        runtime = Runtime(
            settings,
            verifier=fake.verifier("linkcraft"),
            service_client=service,
            http_client=http,
            compute=ComputePool(processes),
        )
        stack.callback(runtime.shutdown)
        rounds = []
        for label in ("cold", "warm"):
            started = time.perf_counter()
            requests, suite = meter.requests, meter.suite
            event_requests, events = meter.event_requests, meter.events
            series_requests = meter.series_requests
            outcome = runtime.run_round()
            seconds = time.perf_counter() - started
            if outcome["status"] != "ok":
                raise RuntimeError(f"{label} round failed: {outcome.get('error')}")
            rounds.append(
                {
                    "round": label,
                    "seconds": round(seconds, 2),
                    "loops": outcome["subjects"],
                    "loops_per_minute": round(60 * outcome["subjects"] / seconds),
                    "requests": meter.requests - requests,
                    "suite_requests": meter.suite - suite,
                    "event_requests": meter.event_requests - event_requests,
                    "events": meter.events - events,
                    "series_requests": meter.series_requests - series_requests,
                    "status_counts": outcome["status_counts"],
                }
            )
    return {
        "loops": loops,
        "processes": processes,
        "latency_ms": latency_ms,
        "window_hours": hours,
        "transport": transport,
        "fake_server_processes": server_processes if transport == "http" else 0,
        "rounds": rounds,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m linkcraft.bench", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--loops", type=int, default=200)
    parser.add_argument("--processes", type=int, default=4)
    parser.add_argument("--latency-ms", type=float, default=2.0)
    parser.add_argument("--hours", type=float, default=6.0, help="analysis window")
    parser.add_argument(
        "--server-processes", type=int, default=4, help="processes serving the fake PlantCraft"
    )
    parser.add_argument(
        "--transport",
        choices=("http", "mock"),
        default="http",
        help="http: the fake served by uvicorn (default); mock: in process (httpx.MockTransport)",
    )
    options = parser.parse_args(argv)
    report = run(
        options.loops,
        options.processes,
        options.latency_ms,
        options.hours,
        server_processes=options.server_processes,
        transport=options.transport,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
