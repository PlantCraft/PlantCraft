#!/usr/bin/env python3
"""Extreme load on the Historian: the monitoring rounds and many methods at once, while people
use the suite (0.6.0 scenarios, never in GitHub CI).

::

    python3 ci/bench/extreme.py --prefix ~/PlantCraft --scenario C1         # today's demo load
    python3 ci/bench/extreme.py --prefix ~/PlantCraft --scenario C2         # 10x the methods
    python3 ci/bench/extreme.py --prefix ~/PlantCraft --scenario C2 --step 60   # read means
    python3 ci/bench/extreme.py --prefix ~/PlantCraft --scenario C5         # an import meanwhile
    python3 ci/bench/extreme.py --compare                                   # reports side by side

What one run does, against the installation in ``--prefix`` (as ``suite_bench.py``):

1. starts Analytics' loop round and its signal checks at the same moment, as their schedules
   do at the top of the hour (``--no-rounds`` leaves them out);
2. at that moment starts ``--methods`` other methods, each reading what a round reads: every
   signal (``--signals``, the plant's first numbers) over ``--hours``, raw or in means of
   ``--step`` seconds, in four requests at once straight from the Historian, as Analytics does;
3. meanwhile ``--people`` people open screens every few seconds (a trend, the newest values,
   Analytics' overview), each with its own session;
4. with ``--backfill VALUES``, imports a file of that many values (100 tags, one a minute,
   from before the archive's history) into the Historian at that moment and waits until the
   collector wrote it, then deletes the import;
5. with ``--restart-after S``, restarts the Historian S seconds into the work and measures how
   long it stayed away;
   with ``--own-accounts``, each person signs in with a viewer account of their own (created as
   bench-person-NN and turned off after the run), as PlantCraft counts API use per person;
6. samples CPU and memory of every container every 2 s.

The report says, per caller, how long the reads took and how many failed (503: the Historian's
read budget was full; 504: PlantCraft gave up), how long the Historian stayed at one full core
or more, and whether the rounds finished. It is written to
``docs/bench/results/<host>-<UTC time>-extreme-<scenario>.json`` (and ``.md``).

Scenarios (docs/bench/README.md): C1 today's load, C2 ten times the methods, C3 C2 with ten
times the values per read (240 h: the demo plant has 167 signals, so ten times the values stands
for ten times the signals), C4 C1 with 20 people, C5 C1 with a 2 million value import, C6 C2 with
the Historian restarted mid-round.
Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from suite_bench import RESULTS, Suite, _mib, _number, iso, log, machine, versions  # noqa: E402

SCENARIOS = {
    # methods besides the rounds, people, rounds on
    "C1": {"methods": 0, "people": 3, "rounds": True},
    "C2": {"methods": 9, "people": 3, "rounds": True},
    "C3": {"methods": 9, "people": 3, "rounds": True, "hours": 240},
    "C4": {"methods": 0, "people": 20, "rounds": True},
    "C5": {"methods": 0, "people": 3, "rounds": True, "backfill": 2_000_000},
    "C6": {"methods": 9, "people": 3, "rounds": True, "restart_after": 5},
}
# A backfill file: this many tags, one value a minute.
BACKFILL_TAGS = 100
# Analytics' PlantData: four requests at once, each at least 40 signals.
READ_THREADS = 4
# A core's worth of CPU in docker stats.
FULL_CORE = 95.0


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))] if ordered else 0.0


def summary(calls: list[dict]) -> dict:
    seconds = [item["seconds"] for item in calls]
    statuses: dict[str, int] = {}
    for item in calls:
        statuses[str(item["status"])] = statuses.get(str(item["status"]), 0) + 1
    return {
        "n": len(calls),
        "p50_s": round(percentile(seconds, 0.5), 2),
        "p95_s": round(percentile(seconds, 0.95), 2),
        "max_s": round(max(seconds, default=0.0), 2),
        "statuses": statuses,
    }


class Recorder:
    """Every call's time and status, by caller, thread-safe."""

    def __init__(self) -> None:
        self.calls: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def call(
        self, suite: Suite, caller: str, method: str, path: str, body=None, timeout=180, raw=None
    ):
        began = time.perf_counter()
        status, answer = 200, None
        try:
            answer, _, _ = suite.call(method, path, body, raw=raw, timeout=timeout, retry=False)
        except RuntimeError as exc:
            words = str(exc).split(": ", 1)[-1].split(" ", 1)
            status = int(words[0]) if words[0].isdigit() else 0
        except OSError:
            status = 0  # timed out or the connection dropped
        item = {"at": time.time(), "seconds": time.perf_counter() - began, "status": status}
        with self._lock:
            self.calls.setdefault(caller, []).append(item)
        return answer


class Stats(threading.Thread):
    """``docker stats`` of the stack every 2 s: each service's CPU % and memory over time."""

    def __init__(self, project: str):
        super().__init__(daemon=True)
        self.project = project
        self.series: dict[str, list[tuple[float, float, float]]] = {}
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            names = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    f"label=com.docker.compose.project={self.project}",
                    "--format",
                    '{{.Names}}\t{{.Label "com.docker.compose.service"}}',
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            ).stdout
            services = dict(line.split("\t") for line in names.splitlines() if "\t" in line)
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
                    text=True,
                    timeout=30,
                    check=False,
                ).stdout
                if services
                else ""
            )
            now = time.time()
            for line in out.splitlines():
                name, cpu, mem = (line.split("\t") + ["", ""])[:3]
                if name in services:
                    self.series.setdefault(services[name], []).append(
                        (now, _number(cpu.rstrip("%")), _mib(mem.split("/")[0]))
                    )
            self._stop.wait(2)

    def stop(self) -> None:
        self._stop.set()

    def report(self, since: float) -> dict:
        found = {}
        for service, points in sorted(self.series.items()):
            points = [item for item in points if item[0] >= since]
            if not points:
                continue
            cpu = [item[1] for item in points]
            gaps = [b[0] - a[0] for a, b in zip(points, points[1:], strict=False)]
            busy = sum(
                gap for gap, item in zip(gaps, points[1:], strict=False) if item[1] >= FULL_CORE
            )
            found[service] = {
                "cpu_peak": round(max(cpu), 1),
                "cpu_mean": round(sum(cpu) / len(cpu), 1),
                "seconds_at_full_core": round(busy),
                "mem_peak_mib": round(max(item[2] for item in points)),
            }
        return found


def plant_signals(suite: Suite, count: int) -> list[str]:
    """The plant's first ``count`` number signals (Analytics' loops' and checks' kind)."""

    # The whole list in one answer (no ``limit``): at plant scale a page in id order can hold
    # only apps' and the suite's own signals (pc-carga, 2026-11-01, read 0). The plant's own
    # signals only: not those apps write (app-*) nor the suite's health (system:).
    answer, _, _ = suite.call("GET", "/api/v1/signals", timeout=300)
    found = [
        item.get("id")
        for item in answer or []
        if (item.get("kind") or "number") == "number"
        and not item.get("app")
        and not str(item.get("id")).startswith(("app-", "system:"))
    ]
    return [item for item in found if item][:count]


def method(suite: Suite, rec: Recorder, name: str, signals: list[str], hours: float, step) -> dict:
    """One method's read, as Analytics' PlantData makes it: four requests at once."""

    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(hours=hours)
    size = -(-len(signals) // READ_THREADS)
    parts = [signals[n : n + size] for n in range(0, len(signals), size)]
    began = time.perf_counter()

    def read(part: list[str]) -> None:
        body = {"signals": part, "start": iso(start), "end": iso(end)}
        if step:
            body["step"] = step
        rec.call(suite, name, "POST", "/hist/api/v1/series", body, timeout=120)

    with ThreadPoolExecutor(len(parts)) as pool:
        list(pool.map(read, parts))
    return {"method": name, "seconds": round(time.perf_counter() - began, 1)}


def person(suite: Suite, rec: Recorder, signals: list[str], stop: threading.Event, pause: float):
    """Someone opening screens: a trend, the newest values of a display, Analytics' overview."""

    number = 0
    while not stop.is_set():
        end = datetime.now(timezone.utc).replace(microsecond=0)
        signal = signals[number % len(signals)]
        rec.call(
            suite,
            "person_trend_8h",
            "POST",
            "/hist/api/v1/series",
            {"signals": [signal], "start": iso(end - timedelta(hours=8)), "end": iso(end)},
        )
        rec.call(
            suite,
            "person_display_values",
            "POST",
            "/api/v1/series",
            {"signals": signals[:20], "start": iso(end - timedelta(minutes=5)), "end": iso(end)},
        )
        rec.call(suite, "person_analytics_overview", "GET", "/link/api/overview")
        number += 1
        stop.wait(pause)


def rounds(suite: Suite, rec: Recorder, timeout: float) -> dict:
    """Analytics' loop round and signal checks started together; how long each took."""

    before = suite.call("GET", "/link/api/status")[0]
    previous = {
        "round": (before.get("round") or {}).get("started_at"),
        "checks": ((before.get("signal_quality") or {}).get("last_run") or {}).get("id"),
    }
    started = {
        "round": (rec.call(suite, "start", "POST", "/link/api/round") or {}).get("started"),
        "checks": (rec.call(suite, "start", "POST", "/link/api/signal-quality/run") or {}).get(
            "started"
        ),
    }
    began, found = time.perf_counter(), {}
    while time.perf_counter() - began < timeout and len(found) < 2:
        time.sleep(3)
        status = suite.call("GET", "/link/api/status")[0]
        current = status.get("round") or {}
        if (
            "round" not in found
            and current.get("started_at") != previous["round"]
            and current.get("completed_at")
        ):
            found["round"] = {
                "seconds": current.get("duration_seconds"),
                "status": current.get("status"),
                "loops": (current.get("summary") or {}).get("loop_count"),
                "failed_tags": current.get("failed_tag_count"),
            }
        quality = status.get("signal_quality") or {}
        last = quality.get("last_run") or {}
        if (
            "checks" not in found
            and not quality.get("running")
            and last.get("id") != previous["checks"]
        ):
            found["checks"] = {
                "seconds": last.get("duration_seconds"),
                "status": last.get("status"),
                "signals": last.get("signals"),
                "error": last.get("error"),
            }
    for key in ("round", "checks"):
        found.setdefault(key, {"status": "not finished" if started[key] else "did not start"})
    return found


def backfill_csv(values: int) -> bytes:
    """A wide file of ``values`` values: 100 tags, one a minute, ending 400 days ago (before
    the archive's own history), different on each run (an import refuses the same file)."""

    rows = max(1, values // BACKFILL_TAGS)
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=400)
    start = end - timedelta(minutes=rows)
    seed = int(time.time()) % 997
    tags = [f"BENCH-BACKFILL-{n:03d}.PV" for n in range(BACKFILL_TAGS)]
    lines = ["time," + ",".join(tags)]
    for row in range(rows):
        at = (start + timedelta(minutes=row)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(
            at
            + ","
            + ",".join(f"{(row * 7 + n + seed) % 1000 / 10:g}" for n in range(BACKFILL_TAGS))
        )
    return ("\n".join(lines) + "\n").encode()


def backfill(suite: Suite, rec: Recorder, values: int, timeout: float) -> dict:
    """Import ``values`` values, wait until the collector wrote them, delete the import."""

    data = backfill_csv(values)
    began = time.perf_counter()
    checked = (
        rec.call(
            suite,
            "start",
            "POST",
            f"/hist/api/imports/check?name=bench-{int(time.time())}.csv",
            raw=data,
            timeout=600,
        )
        or {}
    )
    token = checked.get("token")
    if not token:
        return {"status": "check failed", "answer": str(checked)[:300]}
    made = rec.call(suite, "start", "POST", "/hist/api/imports", {"token": token}, timeout=600)
    import_id = (made or {}).get("id")
    if not import_id:
        return {"status": "confirm failed"}
    accepted = time.perf_counter() - began
    item: dict = {}
    while time.perf_counter() - began < timeout:
        time.sleep(3)
        try:
            found = suite.call("GET", "/hist/api/imports", timeout=60)[0] or []
        except (RuntimeError, OSError):
            continue  # the Historian is away (C6) or busy: ask again
        item = next((one for one in found if one.get("id") == import_id), {})
        if item.get("status") not in ("writing", None):
            break
    seconds = round(time.perf_counter() - began, 1)
    try:
        suite.call("DELETE", f"/hist/api/imports/{import_id}", timeout=600)
    except (RuntimeError, OSError) as exc:
        log(f"backfill: could not delete {import_id}: {exc}")
    return {
        "bytes": len(data),
        "accepted_s": round(accepted, 1),
        "seconds": seconds,
        "status": item.get("status"),
        "written": item.get("written"),
    }


def restart(suite: Suite, after: float) -> dict:
    """Restart the Historian ``after`` seconds in; how long until it answered again."""

    time.sleep(after)
    began = time.perf_counter()
    suite.compose("restart", "histcraft")
    while time.perf_counter() - began < 300:
        try:
            suite.call("GET", "/hist/api/imports", timeout=10, retry=False)
            break
        except (RuntimeError, OSError):
            time.sleep(1)
    return {"after_s": after, "away_s": round(time.perf_counter() - began, 1)}


def accounts(suite: Suite, count: int) -> list[tuple[str, str]]:
    """``count`` viewer accounts bench-person-NN with a password of this run (each person has
    their own: PlantCraft's per-person API limit counts one account's requests together)."""

    password = secrets.token_urlsafe(18)
    made = []
    for number in range(count):
        name = f"bench-person-{number + 1:02d}"
        person = {"display_name": f"Bench person {number + 1}", "access_level": "viewer"}
        try:
            suite.call("POST", "/api/users", {"username": name, "password": password, **person})
        except RuntimeError as exc:
            if ": 409 " not in str(exc):
                raise
            suite.call("PUT", f"/api/users/{name}", {**person, "active": True})
            suite.call("POST", f"/api/users/{name}/password", {"password": password})
        made.append((name, password))
    return made


def close_accounts(suite: Suite, made: list[tuple[str, str]]) -> None:
    for name, _ in made:
        body = {"display_name": name, "access_level": "viewer", "active": False}
        try:
            suite.call("PUT", f"/api/users/{name}", body)
        except (RuntimeError, OSError) as exc:
            log(f"could not turn {name} off: {exc}")


def run(args: argparse.Namespace) -> dict:
    preset = SCENARIOS.get(args.scenario, {})
    methods = preset.get("methods", 0) if args.methods is None else args.methods
    people = preset.get("people", 3) if args.people is None else args.people
    with_rounds = preset.get("rounds", True) and not args.no_rounds
    hours = preset.get("hours", 24) if args.hours is None else args.hours
    backfill_values = preset.get("backfill", 0) if args.backfill is None else args.backfill
    restart_after = (
        preset.get("restart_after") if args.restart_after is None else args.restart_after
    )
    prefix = Path(args.prefix).expanduser().resolve()
    suite = Suite(prefix, args.url)
    suite.login()
    project = suite.env.get("COMPOSE_PROJECT_NAME") or prefix.name.lower()
    signals = plant_signals(suite, args.signals)
    log(
        f"{args.scenario}: {len(signals)} signals, {methods} methods, {people} people, "
        f"rounds {'on' if with_rounds else 'off'}, {hours:g} h, step {args.step or 'raw'}"
        + (f", import of {backfill_values} values" if backfill_values else "")
        + (f", Historian restart at {restart_after:g} s" if restart_after else "")
    )
    rec, sampler, stop = Recorder(), Stats(project), threading.Event()
    sampler.start()
    time.sleep(args.settle)
    began = time.time()
    crowd = []
    made = accounts(suite, people) if args.own_accounts else []
    for number in range(people):
        own = Suite(prefix, args.url)
        if made:
            name, password = made[number]
            own.call("POST", "/api/login", {"username": name, "password": password})
        else:
            own.login()
        thread = threading.Thread(
            target=person, args=(own, rec, signals, stop, args.pause), daemon=True
        )
        thread.start()
        crowd.append(thread)
    with ThreadPoolExecutor(max(1, methods + 3)) as pool:
        work = [
            pool.submit(method, suite, rec, f"method_{n + 1:02d}", signals, hours, args.step)
            for n in range(methods)
        ]
        side = Suite(prefix, args.url)
        side.login()
        importing = (
            pool.submit(backfill, side, rec, backfill_values, args.timeout)
            if backfill_values
            else None
        )
        restarting = pool.submit(restart, suite, restart_after) if restart_after else None
        found_rounds = rounds(suite, rec, args.timeout) if with_rounds else {}
        method_times = [item.result() for item in work]
        found_backfill = importing.result() if importing else None
        found_restart = restarting.result() if restarting else None
    time.sleep(args.tail)
    stop.set()
    for thread in crowd:
        thread.join(timeout=200)
    sampler.stop()
    close_accounts(suite, made)
    ended = time.time()
    callers = {}
    for caller, calls in sorted(rec.calls.items()):
        if caller.startswith("method_"):
            callers.setdefault("methods", []).extend(calls)
        elif caller != "start":
            callers[caller] = calls
    report = {
        "scenario": args.scenario,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "label": args.label,
        "machine": machine(),
        "versions": versions(suite),
        "settings": {
            "signals": len(signals),
            "hours": hours,
            "step": args.step,
            "methods": methods,
            "people": people,
            "own_accounts": bool(made),
            "rounds": with_rounds,
            "limits": {k: v for k, v in suite.env.items() if k.endswith(("_CPUS", "_MEMORY"))},
        },
        "seconds": round(ended - began),
        "rounds": found_rounds,
        **({"backfill": found_backfill} if found_backfill else {}),
        **({"restart": found_restart} if found_restart else {}),
        "methods": {
            "each_s": [item["seconds"] for item in method_times],
            **(summary(callers.pop("methods")) if "methods" in callers else {}),
        },
        "people": {caller: summary(calls) for caller, calls in callers.items()},
        "containers": sampler.report(began),
    }
    return report


def markdown(report: dict) -> str:
    s = report["settings"]
    lines = [
        f"# Extreme load {report['scenario']} {report.get('label') or ''} ({report['at']})",
        "",
        f"Machine: {report['machine'].get('host')}, {report['machine'].get('docker')}. "
        f"Load: {s['methods']} methods besides the rounds, {s['people']} people, rounds "
        f"{'on' if s['rounds'] else 'off'}, {s['signals']} signals x {s['hours']:g} h, "
        f"{'raw' if not s['step'] else 'means of %g s' % s['step']}. Run {report['seconds']} s.",
        "",
        "| Work | Seconds | Status |",
        "|---|---|---|",
    ]
    for key, item in report["rounds"].items():
        lines.append(f"| Analytics {key} | {item.get('seconds')} | {item.get('status')} |")
    if report.get("backfill"):
        item = report["backfill"]
        lines.append(
            f"| Import of {item.get('written')} values | {item.get('seconds')} "
            f"(accepted in {item.get('accepted_s')}) | {item.get('status')} |"
        )
    if report.get("restart"):
        item = report["restart"]
        lines.append(f"| Historian restart at {item['after_s']:g} s | away {item['away_s']} | |")
    methods = report["methods"]
    if methods.get("each_s"):
        lines.append(
            f"| {len(methods['each_s'])} methods (slowest) | {max(methods['each_s'])} | "
            f"{methods.get('statuses')} |"
        )
    lines += [
        "",
        "| Caller | Calls | p50 s | p95 s | max s | Statuses |",
        "|---|---|---|---|---|---|",
    ]
    rows = dict(report["people"])
    if methods.get("n"):
        rows["method reads"] = methods
    for caller, item in rows.items():
        lines.append(
            f"| {caller} | {item['n']} | {item['p50_s']} | {item['p95_s']} | {item['max_s']} | "
            f"{item['statuses']} |"
        )
    lines += [
        "",
        "| Container | CPU peak % | CPU mean % | s at a full core | Memory peak MiB |",
        "|---|---|---|---|---|",
    ]
    for service, item in report["containers"].items():
        lines.append(
            f"| {service} | {item['cpu_peak']} | {item['cpu_mean']} | "
            f"{item['seconds_at_full_core']} | {item['mem_peak_mib']} |"
        )
    return "\n".join(lines) + "\n"


def compare(folder: Path) -> None:
    for path in sorted(folder.glob("*-extreme-*.json")):
        report = json.loads(path.read_text())
        hist = report["containers"].get("histcraft", {})
        person = report["people"].get("person_trend_8h", {})
        rounds = report.get("rounds") or {}
        print(
            f"{path.stem}: {report.get('label') or ''} methods {report['settings']['methods']} "
            f"step {report['settings']['step'] or 'raw'} | round "
            f"{(rounds.get('round') or {}).get('seconds')} s, checks "
            f"{(rounds.get('checks') or {}).get('seconds')} s | methods slowest "
            f"{max(report['methods'].get('each_s') or [0])} s | trend p95 {person.get('p95_s')} s "
            f"| Historian at a full core {hist.get('seconds_at_full_core')} s"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--prefix", default="dist/e2e-bundle/install")
    parser.add_argument("--url", help="the suite's address (default: from its .env)")
    parser.add_argument("--scenario", default="C1", help="C1 to C6 or a name of yours")
    parser.add_argument("--label", default="", help="a word for the report (before, after...)")
    parser.add_argument("--methods", type=int, help="methods besides the rounds")
    parser.add_argument("--people", type=int, help="people opening screens meanwhile")
    parser.add_argument("--signals", type=int, default=214, help="signals each method reads")
    parser.add_argument("--hours", type=float, help="the window each method reads (24 h)")
    parser.add_argument("--backfill", type=int, help="values to import meanwhile (C5)")
    parser.add_argument("--restart-after", type=float, help="restart the Historian S s in (C6)")
    parser.add_argument("--step", type=float, default=None, help="means of STEP s (default raw)")
    parser.add_argument(
        "--own-accounts", action="store_true", help="each person signs in as a viewer of their own"
    )
    parser.add_argument("--no-rounds", action="store_true", help="leave Analytics' rounds out")
    parser.add_argument("--pause", type=float, default=5, help="seconds between a person's screens")
    parser.add_argument("--settle", type=float, default=10, help="quiet seconds measured first")
    parser.add_argument("--tail", type=float, default=20, help="seconds measured after the work")
    parser.add_argument("--timeout", type=float, default=900, help="longest wait for the rounds")
    parser.add_argument("--compare", action="store_true", help="every saved report, one line each")
    args = parser.parse_args()
    if args.compare:
        compare(RESULTS)
        return 0
    report = run(args)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")
    name = f"{report['machine']['host']}-{stamp}-extreme-{args.scenario}"
    if args.label:
        name += f"-{args.label}"
    (RESULTS / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n")
    (RESULTS / f"{name}.md").write_text(markdown(report))
    print(markdown(report))
    log(f"report: {RESULTS / name}.json (.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
