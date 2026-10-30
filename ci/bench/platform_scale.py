#!/usr/bin/env python3
"""PlantCraft with 50,000 signals and 50 apps at once, measured in one process (scale review E14).

::

    python ci/bench/platform_scale.py                     # 50,000 signals, 50 apps
    python ci/bench/platform_scale.py --signals 5000 --apps 10 --check   # the CI-sized run

Where ``ci/bench/suite_bench.py`` measures the installed stack (Historian, Link, View) on a
machine, this measures PlantCraft itself, from a checkout, with no Docker: a recorded source of
``--signals`` signals and ``--apps`` stub suite apps that each do what an app does when it
starts and on each round, all at once:

1. its service token from its app key, and its contributions with its ``[permissions]``;
2. the whole signal list in pages of 5,000 (API v1), then again with the ETags it kept (304);
3. ``/api/v1/apps``, ``/api/v1/installation`` and one asset;
4. one batch of 500 signals' last hour (``POST /api/v1/series``);
5. 100 results and one audit entry;
6. a route it did not ask for (``write.series``), which must answer 403.

The report (latency of each step, p50/p95/max, wall time, peak memory) is written to
``docs/bench/results/<host>-<UTC time>-platform-<signals>x<apps>.json`` (and ``.md``).
``--check`` fails when a step breaks or goes over its budget (``BUDGETS``, seconds at p95).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import socket
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import uvicorn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RESULTS = ROOT / "docs" / "bench" / "results"
ADMIN, PASSWORD = "root", "bench-password-123"
PAGE = 5000
# p95 budgets in seconds, per step, for --check (generous: a laptop or a shared CI runner).
BUDGETS = {
    "token": 2.0,
    "contributions": 3.0,
    "signals_full": 30.0,
    "signals_304": 10.0,
    "apps": 2.0,
    "series_batch_500": 20.0,
    "results_100": 5.0,
    "refused": 2.0,
}
PERMISSIONS = [
    "read.assets",
    "read.signals",
    "read.series",
    "read.results",
    "write.results",
    "write.audit",
]


def _plant(folder: Path, signals: int) -> Path:
    """A wide CSV: ``signals`` columns (loops of PV/SP/OP under units) over the last 2 hours."""

    loops = -(-signals // 3)
    tags = [
        f"U{loop // 500:03d}-L{loop:05d}.{role}"
        for loop in range(loops)
        for role in ("PV", "SP", "OP")
    ][:signals]
    index = pd.date_range(end=pd.Timestamp.now().floor("min"), periods=120, freq="1min")
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        rng.normal(50, 5, (len(index), len(tags))).round(3), index=index, columns=tags
    )
    path = folder / "plant.csv"
    frame.to_csv(path, index_label="timestamp")
    return path


def _scenario(folder: Path, csv: Path) -> Path:
    scenario = json.loads((ROOT / "scenarios" / "generic_demo.json").read_text())
    scenario["source"]["path"] = str(csv)
    scenario["storage"]["sqlite_path"] = str(folder / "workspace.sqlite3")
    scenario["loops"] = scenario["loops"][:0]
    path = folder / "scenario.json"
    path.write_text(json.dumps(scenario))
    return path


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Timings:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.steps: dict[str, list[float]] = {}
        self.errors: list[str] = []

    def time(self, step: str, call):
        started = time.perf_counter()
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - every failure is a finding of the bench
            with self.lock:
                self.errors.append(f"{step}: {exc}")
            return None
        finally:
            with self.lock:
                self.steps.setdefault(step, []).append(time.perf_counter() - started)

    def summary(self) -> dict[str, dict[str, float]]:
        out = {}
        for step, values in sorted(self.steps.items()):
            ordered = sorted(values)
            out[step] = {
                "n": len(ordered),
                "p50": round(statistics.median(ordered), 4),
                "p95": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 4),
                "max": round(ordered[-1], 4),
            }
        return out


def _check(response: httpx.Response, *expected: int) -> httpx.Response:
    if response.status_code not in (expected or (200,)):
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path}: "
            f"{response.status_code} {response.text[:200]}"
        )
    return response


def _app_round(url: str, app: str, key: str, timings: Timings) -> dict[str, int]:
    seen = {"signals": 0, "not_modified": 0}
    with httpx.Client(base_url=url, timeout=300) as http:
        grant = timings.time(
            "token",
            lambda: _check(http.post("/api/v1/auth/service-token", json={"app": app, "key": key})),
        )
        if grant is None:
            return seen
        http.headers["Authorization"] = f"Bearer {grant.json()['token']}"
        body = {"app": app, "version": "0.0.1", "permissions": PERMISSIONS}
        timings.time("contributions", lambda: _check(http.put("/api/v1/contributions", json=body)))

        etags: list[tuple[dict, str]] = []

        def walk() -> list[str]:
            ids: list[str] = []
            params: dict = {"limit": PAGE}
            while True:
                page = _check(http.get("/api/v1/signals", params=params))
                etags.append((dict(params), page.headers.get("etag", "")))
                ids += [item["id"] for item in page.json()]
                cursor = page.headers.get("x-next-cursor")
                if not cursor:
                    return ids
                params = {"limit": PAGE, "cursor": cursor}

        ids = timings.time("signals_full", walk) or []
        seen["signals"] = len(ids)

        def again() -> int:
            hits = 0
            for params, etag in etags:
                answer = _check(
                    http.get("/api/v1/signals", params=params, headers={"If-None-Match": etag}),
                    200,
                    304,
                )
                hits += answer.status_code == 304
            return hits

        seen["not_modified"] = timings.time("signals_304", again) or 0
        timings.time("apps", lambda: _check(http.get("/api/v1/apps")))
        timings.time("installation", lambda: _check(http.get("/api/v1/installation")))
        assets = timings.time(
            "assets_page", lambda: _check(http.get("/api/v1/assets", params={"limit": 100}))
        )
        if assets is not None and assets.json():
            first = assets.json()[0]["id"]
            timings.time("asset", lambda: _check(http.get(f"/api/v1/assets/{first}")))
        if ids:
            offset = (hash(app) % max(1, len(ids) - 500)) if len(ids) > 500 else 0
            batch = {"signals": ids[offset : offset + 500], "step": 60}
            timings.time(
                "series_batch_500", lambda: _check(http.post("/api/v1/series", json=batch))
            )
            results = [
                {
                    "subject": f"signal:{signal}",
                    "kind": f"{app}-check",
                    "status": "ok",
                    "summary": "ok",
                }
                for signal in ids[offset : offset + 100]
            ]
            timings.time("results_100", lambda: _check(http.put("/api/v1/results", json=results)))
        audit = {"action": "bench", "subject": app}
        timings.time("audit", lambda: _check(http.post("/api/v1/audit", json=audit), 201))
        refused = [{"signal": f"{app}:bench", "points": [{"t": "2026-01-01T00:00:00Z", "v": 1}]}]
        timings.time("refused", lambda: _check(http.put("/api/v1/series", json=refused), 403))
    return seen


def run(signals: int, apps: int) -> dict:
    folder = Path(tempfile.mkdtemp(prefix="platform-scale-"))
    started = time.perf_counter()
    csv = _plant(folder, signals)
    plant_seconds = time.perf_counter() - started
    secret = folder / "admin.secret"
    secret.write_text(PASSWORD)
    names = [f"stub{number:02d}" for number in range(1, apps + 1)]
    os.environ.update(
        PLANTCRAFT_SCENARIO=str(_scenario(folder, csv)),
        PLANTCRAFT_APPS=",".join(f"{name}=/{name}/" for name in names),
        PLANTCRAFT_BASIC_AUTH_ENABLED="true",
        PLANTCRAFT_BASIC_AUTH_USERNAME=ADMIN,
        PLANTCRAFT_BASIC_AUTH_PASSWORD_FILE=str(secret),
        PLANTCRAFT_PREWARM_HISTORY="false",
        PLANTCRAFT_WATCH="false",
        PLANTCRAFT_MAIL_OUTBOX="false",
    )
    sys.path.insert(0, str(ROOT))
    from plantcraft.api.app import create_app

    port = _free_port()
    started = time.perf_counter()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    start_seconds = time.perf_counter() - started
    url = f"http://127.0.0.1:{port}"
    timings = Timings()
    with httpx.Client(base_url=url, timeout=300) as admin:
        _check(admin.post("/api/login", json={"username": ADMIN, "password": PASSWORD}))
        keys = {}
        for name in names:
            created = timings.time(
                "app_key",
                lambda name=name: _check(
                    admin.post("/api/app-keys", json={"app_id": name, "label": "bench"}), 201
                ),
            )
            if created is not None:
                keys[name] = created.json()["key"]
        first = timings.time(
            "first_signal_list", lambda: _check(admin.get("/api/v1/signals", params={"limit": 1}))
        )
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=apps) as pool:
        rounds = list(
            pool.map(lambda name: _app_round(url, name, keys.get(name, ""), timings), names)
        )
    round_seconds = time.perf_counter() - started
    server.should_exit = True
    thread.join(timeout=30)
    total = int(first.headers.get("x-total-count", 0)) if first is not None else 0
    return {
        "host": socket.gethostname(),
        "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs",
        "python": platform.python_version(),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "signals": signals,
        "apps": apps,
        "signals_listed": total,
        "every_app_saw_every_signal": all(item["signals"] == total for item in rounds),
        "not_modified_answers": sum(item["not_modified"] for item in rounds),
        "seconds": {
            "write_plant_csv": round(plant_seconds, 2),
            "start_plantcraft": round(start_seconds, 2),
            "all_apps_round": round(round_seconds, 2),
        },
        "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "steps": timings.summary(),
        "errors": timings.errors[:50],
    }


def _markdown(report: dict) -> str:
    lines = [
        f"# PlantCraft at {report['signals']:,} signals and {report['apps']} apps",
        "",
        f"{report['machine']}, Python {report['python']}, {report['at']}.",
        "",
        f"- Signals listed: {report['signals_listed']:,}; every app saw them all: "
        f"{report['every_app_saw_every_signal']}; 304 answers: {report['not_modified_answers']}",
        f"- Start: {report['seconds']['start_plantcraft']} s; all apps' round at once: "
        f"{report['seconds']['all_apps_round']} s; peak memory {report['peak_memory_mb']} MB",
        f"- Errors: {len(report['errors'])}",
        "",
        "| Step | n | p50 (s) | p95 (s) | max (s) |",
        "|---|---|---|---|---|",
    ]
    for step, values in report["steps"].items():
        lines.append(
            f"| {step} | {values['n']} | {values['p50']} | {values['p95']} | {values['max']} |"
        )
    lines += [""] + [f"- {error}" for error in report["errors"]]
    return "\n".join(lines) + "\n"


def problems(report: dict) -> list[str]:
    found = list(report["errors"])
    if report["signals_listed"] < report["signals"]:
        found.append(f"listed {report['signals_listed']} of {report['signals']} signals")
    if not report["every_app_saw_every_signal"]:
        found.append("an app did not see every signal")
    for step, budget in BUDGETS.items():
        p95 = report["steps"].get(step, {}).get("p95")
        if p95 is None:
            found.append(f"{step}: never ran")
        elif p95 > budget:
            found.append(f"{step}: p95 {p95} s over its {budget} s budget")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--signals", type=int, default=50_000)
    parser.add_argument("--apps", type=int, default=50)
    parser.add_argument("--check", action="store_true", help="fail on an error or a budget")
    parser.add_argument("--no-save", action="store_true", help="print the report only")
    options = parser.parse_args()
    report = run(options.signals, options.apps)
    text = _markdown(report)
    print(text)
    if not options.no_save:
        RESULTS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        name = f"{report['host']}-{stamp}-platform-{options.signals}x{options.apps}"
        (RESULTS / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")
        (RESULTS / f"{name}.md").write_text(text)
    found = problems(report)
    for problem in found:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if options.check and found else 0


if __name__ == "__main__":
    sys.exit(main())
