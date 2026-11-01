#!/usr/bin/env python3
"""The suite at plant scale, measured end to end on an installed stack (never in GitHub CI).

::

    make bench-suite                                   # the stack of make e2e-bundle, target scale
    python3 ci/bench/suite_bench.py --prefix ~/PlantCraft-bench --scale target
    python3 ci/bench/suite_bench.py --compare          # every saved report side by side

What it does, against the installation in ``--prefix`` (its ``.env``, admin password, local CA
and ``docker compose``):

1. Historian: a source ``bench`` (disabled, so the collector leaves it alone) with ``loops`` x
   PV/SP/OP plus ``extra`` signals, and ``hours`` of archive written through the real
   compressors and PostgreSQL (``ci/bench/hist_seed.py``, run inside the Historian container).
2. PlantCraft: a plant map of one unit, an area per 50 loops and the loops with their roles,
   previewed and imported (``/api/map``).
3. Reads through PlantCraft's API v1 (forwarded to Historian): batches of 500 signals over the
   last hour and the whole window, one signal's raw week, and a 24 h trend of 100 signals; the
   same batches straight from the Historian (``/hist/api/v1/series``) when it serves them.
4. Analytics: the signal checks over every signal, then the monitoring round over every loop
   (sync, read, analyse, publish), twice; then ``--queue-jobs`` executions (1000 by default) put
   in its queue at once, a person's "run now" on bench loops: how long the queue takes to drain,
   the longest wait, failures, and that its metrics carry the queue for PlantCraft's watch.
5. View: a dashboard of 12 trend and 12 KPI cards on the bench loops, every card read.
6. Analytics models: the demo's FIC-1001 model algorithm (a process model beside the plant)
   copied onto ``twins`` bench loops; the share of them it ran on in the minutes watched.

CPU and memory of each container are sampled through the run. The report is written to
``docs/bench/results/<host>-<UTC time>-<scale>.json`` (and ``.md``) so runs on different
machines and days can be compared. ``--keep`` leaves the bench data in the stack; by default it
is removed at the end (dashboard, model algorithm, assets, the Historian source and its archive).

Only the Python standard library is used, so the system ``python3`` of any machine runs it.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
# In a PlantCraft checkout, its docs/bench/results; copied elsewhere, next to the script.
RESULTS = (
    ROOT / "docs" / "bench" / "results"
    if (ROOT / "docs" / "bench").is_dir()
    else HERE / "bench-results"
)
SCALES = {
    # loops (x3 signals), extra signals, archive hours, twins
    # 24 h so the signal checks (a day's window) see a full day: one value per 30 s is fed to
    # the compressors (seed cost grows with signals x hours / 30 s).
    "small": (200, 200, 24, 10),
    "target": (2000, 2000, 24, 50),
    "stress": (5000, 5000, 24, 100),
}
BATCH = 500  # plantcraft_sdk.contract.MAX_BATCH_SIGNALS
# The demo's model algorithm the bench copies (Link's plant model examples, install --demo).
MODEL_TEMPLATE = "example_fic_1001_process"
BENCH_MODEL = "bench_model"


def log(message: str) -> None:
    print(f"[bench] {message}", flush=True)


def env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"')
    return values


class Suite:
    """HTTP to the suite's proxy as the administrator (the session cookie every app accepts)."""

    def __init__(self, prefix: Path, url: str | None):
        self.prefix = prefix
        self.env = env_file(prefix / ".env")
        host = (self.env.get("PLANTCRAFT_HOSTNAME") or "localhost").split()[0].split(",")[0]
        port = self.env.get("PLANTCRAFT_HTTPS_PORT", "443")
        self.url = (url or f"https://{host}{'' if port == '443' else ':' + port}").rstrip("/")
        context = ssl.create_default_context()
        ca = prefix / "local-ca-root.crt"
        if ca.exists():
            context.load_verify_locations(str(ca))
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),  # the suite is local: never through a proxy
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def call(
        self, method: str, path: str, body=None, raw: bytes | None = None, timeout=900, retry=0
    ):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(self.url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        began = time.perf_counter()
        try:
            with self.opener.open(request, timeout=timeout) as response:
                content = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and retry is not False and int(retry) < 30:
                # A public demo limits requests per address (600 a minute): wait, then again.
                time.sleep(5)
                return self.call(method, path, body, raw, timeout, retry=int(retry) + 1)
            if exc.code == 401 and path != "/api/login" and retry is not False:
                self.login()  # the apps' browser token lasts minutes: sign in again once
                return self.call(method, path, body, raw, timeout, retry=False)
            detail = exc.read()[:500].decode(errors="replace")
            raise RuntimeError(f"{method} {path}: {exc.code} {detail}") from None
        seconds = time.perf_counter() - began
        answer = json.loads(content) if content else None
        return answer, seconds, len(content)

    def login(self) -> None:
        user = self.env.get("PLANTCRAFT_ADMIN_USERNAME") or "admin"
        password_file = self.prefix / "data" / "initial-admin-password"
        password = os.environ.get("PLANTCRAFT_ADMIN_PASSWORD") or password_file.read_text().strip()
        self.call("POST", "/api/login", {"username": user, "password": password})

    def compose(self, *args: str, stdin: bytes | None = None, env: dict | None = None) -> str:
        command = ["docker", "compose", "--project-directory", str(self.prefix)]
        command += ["--env-file", str(self.prefix / ".env"), *args]
        done = subprocess.run(
            command, input=stdin, capture_output=True, check=False, cwd=self.prefix
        )
        if done.returncode:
            raise RuntimeError(f"{' '.join(args[:3])}: {done.stderr.decode()[-800:]}")
        return done.stdout.decode()


class Sampler(threading.Thread):
    """``docker stats`` of the stack's containers every few seconds: peak CPU % and memory."""

    def __init__(self, project: str):
        super().__init__(daemon=True)
        self.project = project
        self.peak: dict[str, dict[str, float]] = {}
        self.phase = "start"
        self.by_phase: dict[str, dict[str, float]] = {}
        self._stop = threading.Event()

    def _services(self) -> dict[str, str]:
        """The stack's containers by compose label, so other projects on the machine (CI runners'
        own containers, a dev stack) that share the name prefix are left out."""

        done = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
                "--format",
                '{{.Names}}\t{{.Label "com.docker.compose.service"}}',
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        pairs = (line.split("\t") for line in done.stdout.decode().splitlines())
        return {name: service for name, service in pairs if name and service}

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                services = self._services()
                out = (
                    subprocess.run(
                        [
                            "docker",
                            "stats",
                            "--no-stream",
                            "--format",
                            "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}",
                            *services,
                        ],
                        capture_output=True,
                        timeout=30,
                        check=False,
                    ).stdout.decode()
                    if services
                    else ""
                )
            except (OSError, subprocess.SubprocessError, ValueError):
                services, out = {}, ""
            for line in out.splitlines():
                name, cpu, mem = (line.split("\t") + ["", ""])[:3]
                service = services.get(name)
                if not service:
                    continue
                cpu_value = _number(cpu.rstrip("%"))
                mem_value = _mib(mem.split("/")[0])
                peak = self.peak.setdefault(service, {"cpu_percent": 0.0, "mem_mib": 0.0})
                peak["cpu_percent"] = max(peak["cpu_percent"], cpu_value)
                peak["mem_mib"] = max(peak["mem_mib"], mem_value)
                phase = self.by_phase.setdefault(self.phase, {})
                phase[service] = max(phase.get(service, 0.0), cpu_value)
            self._stop.wait(3)

    def stop(self) -> None:
        self._stop.set()


def _number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


def _mib(text: str) -> float:
    text = text.strip()
    for unit, factor in (("GiB", 1024), ("MiB", 1), ("KiB", 1 / 1024), ("B", 1 / 1024 / 1024)):
        if text.endswith(unit):
            return round(_number(text[: -len(unit)]) * factor, 1)
    return 0.0


def plant_map(loops: int, extra: int) -> dict:
    assets = [{"asset_id": "BENCH", "name": "Bench unit", "kind": "unit", "parent_id": ""}]
    signals = []
    areas = max(1, (loops + 49) // 50)
    for number in range(loops):
        area = f"BENCH-A{number // 50:03d}"
        if number % 50 == 0:
            assets.append(
                {
                    "asset_id": area,
                    "name": f"Bench area {number // 50}",
                    "kind": "area",
                    "parent_id": "BENCH",
                }
            )
        loop = f"LC-{number:05d}"
        assets.append({"asset_id": loop, "name": loop, "kind": "loop", "parent_id": area})
        for role in ("pv", "sp", "op"):
            signals.append(
                {
                    "tag": f"{loop}.{role.upper()}",
                    "source_id": "bench",
                    "unit": "%",
                    "asset_id": loop,
                    "role": role,
                }
            )
    for number in range(extra):
        signals.append(
            {
                "tag": f"AI-{number:05d}",
                "source_id": "bench",
                "unit": "bar",
                "asset_id": f"BENCH-A{number * areas // max(extra, 1):03d}",
                "role": "measure",
            }
        )
    return {"assets": assets, "signals": signals}


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {}
    return {
        "n": len(ordered),
        "mean_ms": round(1000 * sum(ordered) / len(ordered), 1),
        "p95_ms": round(1000 * ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 1),
        "max_ms": round(1000 * ordered[-1], 1),
    }


def seed_histcraft(suite: Suite, loops: int, extra: int, hours: float, report: dict) -> None:
    out = suite.compose(
        "exec",
        "-T",
        "-e",
        f"LOOPS={loops}",
        "-e",
        f"EXTRA={extra}",
        "-e",
        f"HOURS={hours}",
        "histcraft",
        "python",
        "-",
        stdin=(HERE / "hist_seed.py").read_bytes(),
    )
    seeded = json.loads(out.strip().splitlines()[-1])
    report["histcraft_seed"] = seeded
    log(
        f"Historian: {seeded['points']} signals, {seeded['archived']:,} values archived in "
        f"{seeded['archive_seconds']} s ({seeded['values_per_second']:,}/s), compacted in "
        f"{seeded['compact_seconds']} s"
    )


def import_map(suite: Suite, loops: int, extra: int, report: dict) -> None:
    content = json.dumps(plant_map(loops, extra)).encode()
    preview, preview_s, _ = suite.call(
        "POST", "/api/map/preview?filename=bench-plant.json", raw=content
    )
    errors = [item for item in preview.get("issues") or [] if item.get("level") == "error"]
    if errors:
        raise RuntimeError(f"plant map preview: {errors[:3]}")
    applied, apply_s, _ = suite.call(
        "POST", "/api/map/apply?filename=bench-plant.json", raw=content
    )
    if not applied.get("applied"):
        raise RuntimeError(f"plant map not applied: {json.dumps(applied)[:500]}")
    report["plant_map"] = {
        "assets": len(plant_map(loops, extra)["assets"]),
        "signals": len(plant_map(loops, extra)["signals"]),
        "preview_seconds": round(preview_s, 1),
        "apply_seconds": round(apply_s, 1),
    }
    log(f"Plant map: preview {preview_s:.1f} s, import {apply_s:.1f} s")


def reads(suite: Suite, loops: int, extra: int, hours: float, report: dict) -> None:
    ids = [f"bench:LC-{n:05d}.{r}" for n in range(loops) for r in ("PV", "SP", "OP")]
    ids += [f"bench:AI-{n:05d}" for n in range(extra)]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    result: dict = {}
    # Through PlantCraft's API v1, and straight from the Historian when it serves the reads
    # (plantcraft-sdk 0.13.0 reads there): the same batches, labels ending in "_direct".
    routes = [("", "/api/v1/series")]
    try:
        if (suite.call("GET", "/hist/api/v1/reads")[0] or {}).get("api") == 1:
            routes.append(("_direct", "/hist/api/v1/series"))
    except RuntimeError as exc:
        log(f"Reads: the Historian serves no direct reads ({exc})")
    batches = [
        (f"{label}{suffix}", route, start, step)
        for suffix, route in routes
        for label, start, step in (
            ("batch_1h_raw", now - timedelta(hours=1), None),
            ("batch_window_60s", now - timedelta(hours=hours), 60),
        )
    ]
    for label, route, start, step in batches:
        times, values, errors = [], 0, 0
        began = time.perf_counter()
        for offset in range(0, len(ids), BATCH):
            body = {"signals": ids[offset : offset + BATCH], "start": iso(start), "end": iso(now)}
            if step:
                body["step"] = step
            answer, seconds, _ = suite.call("POST", route, body)
            times.append(seconds)
            errors += len(answer.get("errors") or [])
            values += sum(len(item.get("v") or []) for item in answer.get("series") or [])
        total = time.perf_counter() - began
        result[label] = {
            "signals": len(ids),
            "seconds": round(total, 1),
            "values": values,
            "errors": errors,
            "signals_per_second": round(len(ids) / total),
            "request": stats(times),
        }
        log(f"Reads {label}: {len(ids)} signals in {total:.1f} s ({errors} errors)")
    trend = []
    for number in range(min(100, loops)):
        _, seconds, _ = suite.call(
            "GET",
            f"/api/v1/signals/bench:LC-{number:05d}.PV/series?start={iso(now - timedelta(days=1))}"
            f"&end={iso(now)}&step=300",
        )
        trend.append(seconds)
    result["trend_24h_one_signal"] = stats(trend)
    report["reads"] = result


def signal_quality(suite: Suite, report: dict, timeout: float) -> None:
    """Link's signal checks over every signal, on the data just seeded (rounds use its verdicts)."""

    began = time.perf_counter()
    previous = None
    while True:
        status, _, _ = suite.call("GET", "/link/api/status")
        quality = status.get("signal_quality") or {}
        previous = (quality.get("last_run") or {}).get("id")
        if not quality.get("running"):
            try:
                if suite.call("POST", "/link/api/signal-quality/run")[0].get("started"):
                    break
            except RuntimeError as exc:
                if " 409 " not in str(exc):
                    raise
        if time.perf_counter() - began > timeout:
            raise RuntimeError(f"Link's signal checks could not start in {timeout:.0f} s")
        time.sleep(5)
    while True:
        time.sleep(5)
        quality = (suite.call("GET", "/link/api/status")[0].get("signal_quality")) or {}
        last = quality.get("last_run") or {}
        if not quality.get("running") and last.get("id") != previous:
            break
        if time.perf_counter() - began > timeout:
            raise RuntimeError(f"Link's signal checks did not end in {timeout:.0f} s")
    report["signal_quality"] = {
        key: last.get(key) for key in ("status", "signals", "duration_seconds", "counts", "error")
    }
    log(f"Signal checks: {last.get('signals')} signals in {last.get('duration_seconds')} s")


def link_round(suite: Suite, report: dict, timeout: float) -> None:
    rounds = []
    for label in ("first", "second"):
        before, _, _ = suite.call("GET", "/link/api/status")
        previous = (before.get("round") or {}).get("started_at")
        began = time.perf_counter()
        while not suite.call("POST", "/link/api/round")[0].get("started"):
            # A scheduled round is running: wait for it, then start ours.
            time.sleep(5)
            before, _, _ = suite.call("GET", "/link/api/status")
            previous = (before.get("round") or {}).get("started_at")
            if time.perf_counter() - began > timeout:
                raise RuntimeError(f"the Analytics round could not start in {timeout:.0f} s")
        began = time.perf_counter()
        while True:
            time.sleep(2)
            status, _, _ = suite.call("GET", "/link/api/status")
            current = status.get("round") or {}
            if current.get("started_at") != previous and current.get("completed_at"):
                break
            if time.perf_counter() - began > timeout:
                raise RuntimeError(f"the Analytics round did not end in {timeout:.0f} s")
        summary = current.get("summary") or {}
        rounds.append(
            {
                "round": label,
                "wall_seconds": round(time.perf_counter() - began, 1),
                "duration_seconds": current.get("duration_seconds"),
                "status": current.get("status"),
                "loops": summary.get("loop_count"),
                "status_counts": summary.get("status_counts"),
                "failed_tags": current.get("failed_tag_count"),
                "unread_loops": current.get("unread_loops"),
            }
        )
        log(
            f"Link round {label}: {current.get('duration_seconds')} s for "
            f"{summary.get('loop_count')} loops ({current.get('status')})"
        )
    report["link_rounds"] = rounds


def link_queue(suite: Suite, loops: int, jobs: int, report: dict, timeout: float) -> None:
    """``jobs`` executions queued at once on the bench loops; the time the queue takes to drain."""

    if jobs <= 0 or loops <= 0:
        return
    names = [f"LC-{index % loops:05d}" for index in range(jobs)]
    began = time.perf_counter()
    queued = 0
    for start in range(0, jobs, loops):
        answer, _, _ = suite.call(
            "POST",
            "/link/api/jobs/batch",
            {
                "name": "Bench queue",
                "loop_ids": names[start : start + loops],
                "lookback_minutes": 60,
            },
        )
        queued += int(answer.get("queued") or 0)
        workers = answer.get("workers")
    log(f"Link queue: {queued} executions queued in {time.perf_counter() - began:.1f} s")
    longest, peak_cpu, peak_memory = 0.0, 0.0, 0.0
    while True:
        now = suite.call("GET", "/link/api/queue?window=1h")[0].get("now") or {}
        longest = max(longest, float(now.get("delay_seconds") or 0))
        peak_cpu = max(peak_cpu, float(now.get("cpu_percent") or 0))
        peak_memory = max(peak_memory, float(now.get("memory_mb") or 0))
        if not now.get("queued") and not now.get("running"):
            break
        if time.perf_counter() - began > timeout:
            raise RuntimeError(f"Link's queue did not drain in {timeout:.0f} s")
        time.sleep(2)
    drained = time.perf_counter() - began
    hours = max(drained / 3600 + 0.05, 0.1)
    failed = suite.call("GET", f"/link/api/executions?status=failed&hours={hours:.2f}&limit=1")[0]
    metrics = suite.call("GET", "/link/api/ops/metrics")[0]
    report["link_queue"] = {
        "queued": queued,
        "workers": workers,
        "drain_seconds": round(drained, 1),
        "per_second": round(queued / drained, 1) if drained else None,
        "longest_wait_seconds": round(longest, 1),
        "failed": failed.get("total"),
        "engine_cpu_percent_peak": round(peak_cpu),
        "engine_memory_mb_peak": round(peak_memory),
        "metrics_carry_queue": "queue" in metrics,
    }
    log(
        f"Link queue: {queued} executions drained in {drained:.0f} s "
        f"({report['link_queue']['per_second']}/s, {failed.get('total')} failed)"
    )


def dashboards(suite: Suite, loops: int, report: dict) -> str:
    picks = [loops * k // 12 for k in range(12)]
    cards = []
    for index, number in enumerate(picks):
        loop = f"LC-{number:05d}"
        cards.append(
            {
                "card_id": f"t{index}",
                "title": f"{loop} trend",
                "kind": "trend",
                "agg": "mean",
                "window": "12h",
                "width": 6,
                "height": 2,
                "items": [
                    {"asset_id": loop, "role": role, "label": role.upper()}
                    for role in ("pv", "sp", "op")
                ],
            }
        )
        cards.append(
            {
                "card_id": f"k{index}",
                "title": f"{loop} health",
                "kind": "kpi",
                "agg": "last",
                "window": "1d",
                "width": 3,
                "height": 1,
                "items": [{"asset_id": loop, "result": "linkcraft.loop_health", "label": loop}],
            }
        )
    created, _, _ = suite.call(
        "POST",
        "/dash/api/dashboards",
        {"name": "Bench scale", "description": "suite bench", "cards": cards},
    )
    dashboard = created["dashboard_id"]
    times = []
    began = time.perf_counter()
    for card in cards:
        _, seconds, _ = suite.call(
            "GET", f"/dash/api/dashboards/{dashboard}/cards/{card['card_id']}"
        )
        times.append(seconds)
    total = time.perf_counter() - began
    report["dashboard"] = {
        "cards": len(cards),
        "all_cards_seconds": round(total, 2),
        "card": stats(times),
    }
    log(f"Dashboard: {len(cards)} cards read in {total:.2f} s one after another")
    return dashboard


def twins(suite: Suite, count: int, loops: int, report: dict, minutes: float) -> list[str]:
    """The demo's loop model algorithm on ``count`` bench loops; how many it ran on in time."""

    if count <= 0:
        return []
    try:
        template, _, _ = suite.call("GET", f"/link/api/algorithms/{MODEL_TEMPLATE}")
    except RuntimeError:
        report["twins"] = {"skipped": "no model example in this stack to copy (install --demo)"}
        return []
    assets = [f"LC-{index * loops // count:05d}" for index in range(count)]
    copy = {key: template[key] for key in ("subject_kind", "diagram", "timing") if key in template}
    copy.update(
        algorithm_id=BENCH_MODEL,
        name="Bench model",
        description="A copy of the FIC-1001 model algorithm on bench loops.",
        assets=assets,
    )
    suite.call("PUT", f"/link/api/algorithms/{BENCH_MODEL}", copy)
    cycle_seconds = float((template.get("timing") or {}).get("cycle_seconds") or 60)
    # An algorithm runs only where a schedule names it (Link 0.4, round 8): one on the bench loops.
    try:
        suite.call(
            "POST",
            "/link/api/schedules",
            {
                "name": "Bench model",
                "profile_id": BENCH_MODEL,
                "selector": {"mode": "list", "ids": assets},
                "cadence": "interval",
                "interval_minutes": cycle_seconds / 60,
                "lookback_minutes": 60,
            },
        )
    except RuntimeError as exc:
        report["twins"] = {"skipped": f"no schedule for the model algorithm: {exc}"}
        return [BENCH_MODEL]
    began = datetime.now(timezone.utc)
    log(f"Models: {count} loops under the model algorithm, watching {minutes:g} min of cycles")
    time.sleep(minutes * 60)
    rows, _, _ = suite.call("GET", f"/link/api/algorithms/{BENCH_MODEL}/runs")
    ran = sum(1 for row in rows if str(row.get("analyzed_at") or "") >= iso(began))
    report["twins"] = {
        "twins": count,
        "minutes": minutes,
        "cycle_seconds": cycle_seconds,
        "assets_run": ran,
        "assets_without_run": count - ran,
        "kept_up_percent": round(100 * ran / count),
    }
    log(f"Models: ran on {ran} of {count} loops ({count - ran} without a run)")
    return [BENCH_MODEL]


def cleanup(suite: Suite, dashboard: str | None, twin_ids: list[str], loops: int) -> None:
    log("removing the bench data (--keep leaves it)")
    schedules = _quiet(suite.call, "GET", "/link/api/schedules")
    for schedule in (schedules[0] if schedules else None) or []:
        if schedule.get("profile_id") in twin_ids:
            _quiet(suite.call, "DELETE", f"/link/api/schedules/{schedule['schedule_id']}")
    for algorithm_id in twin_ids:
        _quiet(suite.call, "DELETE", f"/link/api/algorithms/{algorithm_id}")
    if dashboard:
        _quiet(suite.call, "DELETE", f"/dash/api/dashboards/{dashboard}")
    # Children first: loops, areas, then the unit.
    for number in range(loops):
        _quiet(suite.call, "DELETE", f"/api/assets/LC-{number:05d}")
    for area in range((loops + 49) // 50):
        _quiet(suite.call, "DELETE", f"/api/assets/BENCH-A{area:03d}")
    _quiet(suite.call, "DELETE", "/api/assets/BENCH")
    _quiet(
        suite.compose,
        "exec",
        "-T",
        "-e",
        "CLEANUP=1",
        "histcraft",
        "python",
        "-",
        stdin=(HERE / "hist_seed.py").read_bytes(),
    )


def leftovers(suite: Suite) -> bool:
    """Whether an earlier run left its data (a run killed before its cleanup, or --keep)."""

    try:
        sources = suite.call("GET", "/hist/api/sources")[0] or []
    except RuntimeError:
        return False  # an older Historian: nothing to check
    return any(source.get("id") == "bench" for source in sources)


def _quiet(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except RuntimeError as exc:
        if ": 404 " not in str(exc):  # already gone
            log(f"cleanup: {exc}")
        return None


def markdown(report: dict) -> str:
    lines = [
        f"# Suite bench {report['scale']} on {report['machine']['host']} ({report['started_at']})",
        "",
        f"{report['machine']['cpus']} CPUs, {report['machine']['memory_gib']} GiB, "
        f"{report['machine']['system']}; {report['size']['loops']} loops, "
        f"{report['size']['signals']} signals, {report['size']['hours']} h of archive.",
        "",
        "| Step | Result |",
        "|---|---|",
    ]
    for key, label in (
        ("histcraft_seed", "Historian archive write"),
        ("plant_map", "Plant map import"),
        ("reads", "API v1 reads"),
        ("signal_quality", "Analytics signal checks"),
        ("link_rounds", "Analytics rounds"),
        ("link_queue", "Analytics queue (executions at once)"),
        ("dashboard", "Dashboard"),
        ("twins", "Model algorithm on loops"),
    ):
        if key in report:
            lines.append(f"| {label} | `{json.dumps(report[key], ensure_ascii=False)}` |")
    lines += [
        "",
        "Peak CPU % and memory per container:",
        "",
        "| Container | CPU % | MiB |",
        "|---|---|---|",
    ]
    for name, peak in sorted(report.get("containers", {}).items()):
        lines.append(f"| {name} | {peak['cpu_percent']:.0f} | {peak['mem_mib']:.0f} |")
    return "\n".join(lines) + "\n"


def compare(folder: Path) -> None:
    rows = []
    for path in sorted(folder.glob("*.json")):
        item = json.loads(path.read_text())
        if "size" not in item:
            continue  # a soak report (ci/bench/soak.py)
        rounds = item.get("link_rounds") or [{}]
        reads_ = item.get("reads", {})
        rows.append(
            (
                path.stem[:40],
                item["size"]["loops"],
                item.get("histcraft_seed", {}).get("values_per_second", "-"),
                item.get("plant_map", {}).get("apply_seconds", "-"),
                reads_.get("batch_window_60s", {}).get("seconds", "-"),
                reads_.get("batch_1h_raw", {}).get("request", {}).get("p95_ms", "-"),
                reads_.get("batch_1h_raw_direct", {}).get("request", {}).get("p95_ms", "-"),
                rounds[0].get("duration_seconds", "-"),
                rounds[-1].get("duration_seconds", "-"),
                item.get("dashboard", {}).get("all_cards_seconds", "-"),
                item.get("twins", {}).get("kept_up_percent", "-"),
            )
        )
    header = (
        "report",
        "loops",
        "archive v/s",
        "map s",
        "read s",
        "1h p95 ms",
        "direct p95 ms",
        "round1 s",
        "round2 s",
        "dash s",
        "twins %",
    )
    print(" | ".join(header))
    for row in rows:
        print(" | ".join(str(value) for value in row))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prefix", type=Path, help="the installation folder (install.sh --prefix)")
    parser.add_argument("--url", help="the suite's address (default from the prefix's .env)")
    parser.add_argument("--scale", choices=sorted(SCALES), default="target")
    parser.add_argument("--loops", type=int)
    parser.add_argument("--extra", type=int, help="signals beyond the loops' PV/SP/OP")
    parser.add_argument("--hours", type=float, help="hours of archive per signal")
    parser.add_argument("--twins", type=int)
    parser.add_argument("--twin-minutes", type=float, default=3.0)
    parser.add_argument("--round-timeout", type=float, default=3600.0)
    parser.add_argument("--queue-jobs", type=int, default=1000, help="executions queued at once")
    parser.add_argument("--skip-seed", action="store_true", help="Historian already seeded")
    parser.add_argument("--keep", action="store_true", help="leave the bench data in the stack")
    parser.add_argument(
        "--cleanup", action="store_true", help="only remove what a --keep run left, then stop"
    )
    parser.add_argument("--yes", action="store_true", help="do not ask before adding data")
    parser.add_argument("--out", type=Path, default=RESULTS, help=f"reports folder ({RESULTS})")
    parser.add_argument("--compare", action="store_true", help="print the saved reports and stop")
    args = parser.parse_args()
    if args.compare:
        compare(args.out)
        return 0
    if not args.prefix or not (args.prefix / ".env").exists():
        parser.error("--prefix must be an installation folder (with .env)")
    loops, extra, hours, twin_count = SCALES[args.scale]
    loops = args.loops if args.loops is not None else loops
    extra = args.extra if args.extra is not None else extra
    hours = args.hours if args.hours is not None else hours
    twin_count = args.twins if args.twins is not None else twin_count
    suite = Suite(args.prefix.resolve(), args.url)
    if args.cleanup:
        suite.login()
        boards = suite.call("GET", "/dash/api/dashboards")[0] or []
        bench = [b["dashboard_id"] for b in boards if b.get("name") == "Bench scale"]
        for board in bench[1:]:
            _quiet(suite.call, "DELETE", f"/dash/api/dashboards/{board}")
        cleanup(suite, bench[0] if bench else None, [BENCH_MODEL], loops)
        return 0
    if not args.yes:
        answer = input(
            f"This adds {loops} loops and {3 * loops + extra} signals to the suite at {suite.url}"
            f" (removed at the end{'' if not args.keep else ': no, --keep'}). Use a test"
            " installation, not production. Continue? [y/N] "
        )
        if answer.strip().lower() not in {"y", "yes", "s", "sim"}:
            return 1
    suite.login()
    if not args.skip_seed and leftovers(suite):
        log(
            "the bench data of an earlier run is still here (source 'bench' in the Historian):"
            " remove it first with --cleanup"
        )
        return 1
    started = datetime.now(timezone.utc)
    report: dict = {
        "scale": args.scale,
        "started_at": iso(started),
        "size": {"loops": loops, "signals": 3 * loops + extra, "hours": hours, "twins": twin_count},
        "machine": machine(),
        "versions": versions(suite),
    }
    sampler = Sampler(suite.env.get("COMPOSE_PROJECT_NAME", "processcraft"))
    sampler.start()
    dashboard, twin_ids = None, []
    try:
        for phase, run in (
            (
                "histcraft_seed",
                lambda: args.skip_seed or seed_histcraft(suite, loops, extra, hours, report),
            ),
            ("plant_map", lambda: import_map(suite, loops, extra, report)),
            ("reads", lambda: reads(suite, loops, extra, hours, report)),
            ("signal_quality", lambda: signal_quality(suite, report, args.round_timeout)),
            ("link_rounds", lambda: link_round(suite, report, args.round_timeout)),
            (
                "link_queue",
                lambda: link_queue(suite, loops, args.queue_jobs, report, args.round_timeout),
            ),
        ):
            sampler.phase = phase
            run()
        sampler.phase = "dashboard"
        dashboard = dashboards(suite, loops, report)
        sampler.phase = "twins"
        twin_ids = twins(suite, twin_count, loops, report, args.twin_minutes)
    except RuntimeError as exc:
        report["error"] = str(exc)
        log(f"ERROR: {exc}")
    finally:
        sampler.stop()
        report["containers"] = sampler.peak
        report["cpu_by_phase"] = sampler.by_phase
        report["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds())
        results = args.out
        results.mkdir(parents=True, exist_ok=True)
        name = f"{report['machine']['host']}-{started:%Y%m%d-%H%M}-{args.scale}"
        (results / f"{name}.json").write_text(json.dumps(report, indent=2) + "\n")
        (results / f"{name}.md").write_text(markdown(report))
        log(f"report: {results / name}.json (.md)")
        if not args.keep:
            cleanup(suite, dashboard, twin_ids, loops)
    return 1 if "error" in report else 0


def machine() -> dict:
    memory = 0.0
    try:
        if sys.platform == "darwin":
            memory = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) / 2**30
        else:
            memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    docker = ""
    try:
        docker = subprocess.check_output(
            ["docker", "info", "--format", "{{.NCPU}} CPUs {{.MemTotal}} {{.Architecture}}"],
            text=True,
            timeout=30,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "host": os.environ.get("BENCH_HOST") or socket.gethostname().split(".")[0],
        "system": f"{platform.system()} {platform.release()} {platform.machine()}",
        "cpus": os.cpu_count(),
        "memory_gib": round(memory, 1),
        "docker": docker,
    }


def versions(suite: Suite) -> dict:
    found = {}
    for app, path in (
        ("linkcraft", "/link/api/meta"),
        ("dashcraft", "/dash/api/meta"),
        ("histcraft", "/hist/api/meta"),
    ):
        try:
            meta, _, _ = suite.call("GET", path)
            found[app] = {k: meta.get(k) for k in ("version", "revision") if k in meta}
        except (RuntimeError, OSError):
            found[app] = None
    return found


if __name__ == "__main__":
    sys.exit(main())
