#!/usr/bin/env python3
"""People at once on an installed suite: how many it serves before pages slow down (never in CI).

::

    python3 ci/bench/load_users.py --prefix dist/e2e-bundle/install            # 10, 30, 60, 100
    python3 ci/bench/load_users.py --prefix ~/PlantCraft-bench --users 30,100,150 --minutes 5

    python3 ci/bench/load_users.py --visitor --heavy 0.3 --users 10,50   # the public demo's visitors

Each simulated person signs in with their own session and walks the suite's pages in a random
order, as a browser does: a page is the API calls it makes when it opens
(``ci/bench/load_pages.json``, recorded on the demo story by ``record_pages.py``), six at a
time, then a pause of ``--think`` seconds (5 to 15 by default) before the next page. The people
arrive in steps (``--users``), each step held ``--minutes``; a step whose pages take over
``--slow`` seconds at p95, or with more than ``--max-failed`` of calls failing (1 %), is the last
one. The recorded pages name objects of the install they were recorded on: before the first step
each call is asked once, and a call that answers 404 or 403 here is left out (the report says how
many), so a failure is the server's, not a missing id.

``--heavy`` is the share of pages after which the person also asks a heavy question of the
data, as an engineer digging into a problem does: a trend of 2 to 8 signals over a week to 90
days (View), a signal's 30 or 90 days in the Historian, a dashboard's every panel over 7 or 30
days, a report's sections over 30 days. The signals are the bench's (``suite_bench.py`` and
``--seed-days``, so months of history exist) when there are, else the plant's. Each kind of
question has its own p50/p95 in the report. ``--visitor`` signs everyone in as the public
demo's read-only visitor (``PLANTCRAFT_PUBLIC_DEMO_USER``) instead of the administrator.

For each step the report gives the pages and calls per second, the p50/p95/max of a page and
of a call, the failures, and each container's peak CPU and memory (``docker stats``, as
``suite_bench.py``). It is written to ``docs/bench/results/<host>-<UTC time>-users.json``
(and ``.md``). Every call is a read: nothing in the suite changes (``--seed-days`` excepted).
A public demo limits each address to ``PLANTCRAFT_PUBLIC_DEMO_RATE`` requests a minute, and
here every person comes from one address: raise that rate for the test. Only the Python
standard library is used.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from suite_bench import RESULTS, Sampler, Suite, import_map, machine, seed_histcraft  # noqa: E402

PAGES = Path(__file__).resolve().parent / "load_pages.json"
PARALLEL = 6  # what a browser opens at once to one host
NOW = re.compile(r"\{now-(\d+)\}")
# Ids in a route, so the report groups calls by route.
ROUTE = re.compile(r"/[^/]*[\d%:][^/]*(?=/|$)")
# The bench signals given months of history by --seed-days (suite_bench's naming).
SEED_LOOPS, SEED_EXTRA = 20, 100


def log(message: str) -> None:
    print(f"[users] {message}", flush=True)


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


class Step:
    """What the people of one step did: page and call times, failures."""

    def __init__(self, users: int) -> None:
        self.users = users
        self.pages: list[float] = []
        self.calls: list[float] = []
        self.failures: dict[str, int] = {}
        self.queries: dict[str, list[float]] = {}
        self.by_path: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def add(
        self, page: float, calls: list[tuple[str, float]], failed: list[str], kind: str = ""
    ) -> None:
        with self.lock:
            if kind:
                self.queries.setdefault(kind, []).append(page)
            else:
                self.pages.append(page)
            for path, seconds in calls:
                self.calls.append(seconds)
                self.by_path.setdefault(ROUTE.sub("/<id>", path.split("?")[0]), []).append(seconds)
            for reason in failed:
                self.failures[reason] = self.failures.get(reason, 0) + 1

    def summary(self, seconds: float) -> dict:
        failed = sum(self.failures.values())
        total = len(self.calls) + failed
        return {
            "users": self.users,
            "seconds": round(seconds),
            "pages": len(self.pages),
            "pages_per_s": round(len(self.pages) / seconds, 2),
            "calls_per_s": round(total / seconds, 1),
            "page_p50_s": round(statistics.median(self.pages), 3) if self.pages else 0,
            "page_p95_s": round(percentile(self.pages, 0.95), 3),
            "page_max_s": round(max(self.pages, default=0), 3),
            "call_p50_s": round(statistics.median(self.calls), 3) if self.calls else 0,
            "call_p95_s": round(percentile(self.calls, 0.95), 3),
            "failed_share": round(failed / total, 4) if total else 0,
            "failures": dict(sorted(self.failures.items(), key=lambda item: -item[1])[:10]),
            "queries": {
                kind: {
                    "n": len(times),
                    "p50_s": round(statistics.median(times), 3),
                    "p95_s": round(percentile(times, 0.95), 3),
                    "max_s": round(max(times), 3),
                }
                for kind, times in sorted(self.queries.items())
            },
            # Where the server's time goes: the routes with the most seconds in all.
            "slowest_routes": [
                {
                    "route": route,
                    "calls": len(times),
                    "total_s": round(sum(times), 1),
                    "p95_s": round(percentile(times, 0.95), 3),
                }
                for route, times in sorted(self.by_path.items(), key=lambda item: -sum(item[1]))[
                    :12
                ]
            ],
        }


class Catalog:
    """What the heavy questions are about: signals with history, dashboards, reports."""

    def __init__(self, suite: Suite) -> None:
        bench = [f"bench:LC-{n:05d}.{r}" for n in range(SEED_LOOPS) for r in ("PV", "SP", "OP")]
        bench += [f"bench:AI-{n:05d}" for n in range(SEED_EXTRA)]
        known = []
        try:
            answer = suite.call("GET", "/api/v1/signals?limit=1000", timeout=60)[0]
            items = answer.get("items", answer) if isinstance(answer, dict) else answer
            known = [item.get("id") or item.get("signal_id") for item in items or []]
        except RuntimeError as exc:
            log(f"signals: {exc}")
        self.signals = [s for s in bench if s in set(known)] or [
            s for s in known if s and not s.startswith("app-")
        ]
        self.cards: list[tuple[str, str]] = []
        self.sections: list[tuple[str, str]] = []
        try:
            for item in suite.call("GET", "/dash/api/dashboards", timeout=60)[0] or []:
                board = suite.call("GET", f"/dash/api/dashboards/{item['dashboard_id']}")[0]
                self.cards += [
                    (item["dashboard_id"], card["card_id"])
                    for card in board.get("cards") or []
                    if card.get("kind", card.get("type")) != "text"
                ]
            for item in suite.call("GET", "/dash/api/reports", timeout=60)[0] or []:
                report = suite.call("GET", f"/dash/api/reports/{item['report_id']}")[0]
                self.sections += [
                    (item["report_id"], section["section_id"])
                    for section in report.get("sections") or []
                ]
        except (RuntimeError, KeyError, TypeError) as exc:
            log(f"dashboards and reports: {exc}")
        log(
            f"heavy questions over {len(self.signals)} signals, {len(self.cards)} panels, "
            f"{len(self.sections)} report sections"
        )

    def question(self) -> tuple[str, list]:
        """A heavy question as (kind, calls): what the browser asks for it."""

        kinds = ["trend", "history"]
        if self.cards:
            kinds.append("dashboard")
        if self.sections:
            kinds.append("report")
        kind = random.choice(kinds)
        if kind == "trend":
            window = random.choice(["7d", "30d", "30d", "90d"])
            lines = random.sample(self.signals, min(len(self.signals), random.randint(2, 8)))
            body = {
                "plots": [{"lines": [{"signal_id": signal} for signal in lines]}],
                "period": {"mode": "relative", "window": window},
            }
            return f"trend {window}", [
                {"method": "POST", "path": "/dash/api/trends/data", "body": body}
            ]
        if kind == "history":
            # The Historian's signal page: averages with each cell's extremes (about 1,500
            # cells), or a day as recorded when the person asks for the raw values.
            days = random.choice([1, 30, 90])
            signal = quote(random.choice(self.signals), safe="")
            span = f"start={{now-{days * 86400}}}&end={{now-0}}"
            grid = "" if days == 1 else f"&step={days * 86400 // 1500}&extremes=true"
            label = "history 1d raw" if days == 1 else f"history {days}d"
            return label, [f"/hist/api/points/{signal}/series?{span}{grid}"]
        if kind == "dashboard":
            window = random.choice(["7d", "30d"])
            board = random.choice(self.cards)[0]
            return f"dashboard {window}", [
                f"/dash/api/dashboards/{board}/cards/{card}?window={window}"
                for dashboard, card in self.cards
                if dashboard == board
            ]
        report = random.choice(self.sections)[0]
        return "report 30d", [
            f"/dash/api/reports/{report}/sections/{section}?period=30d"
            for owner, section in self.sections
            if owner == report
        ]


def person(
    suite: Suite, pages: dict, step: Step, until: float, args, pool, catalog: Catalog | None
) -> None:
    order = list(pages)
    while time.time() < until:
        random.shuffle(order)
        for page in order:
            if time.time() >= until:
                return
            visits = [("", pages[page])]
            if catalog and catalog.signals and random.random() < args.heavy:
                visits.append(catalog.question())
            for kind, wanted in visits:
                began = time.perf_counter()
                calls, failed = [], []
                for result in pool.map(lambda call: one_call(suite, call), wanted):
                    (calls if isinstance(result, tuple) else failed).append(result)
                step.add(time.perf_counter() - began, calls, failed, kind)
                time.sleep(random.uniform(args.think_min, args.think_max))


def resolved(text: str, now: float) -> str:
    """A recorded call's ``{now-<seconds>}`` as a time ending at this moment."""

    def moment(match: re.Match) -> str:
        at = datetime.fromtimestamp(now - int(match.group(1)), timezone.utc)
        return at.strftime("%Y-%m-%dT%H:%M:%SZ")

    return NOW.sub(moment, text)


def one_call(suite: Suite, call: str | dict) -> tuple[str, float] | str:
    now = time.time()
    if isinstance(call, str):
        method, path, body = "GET", resolved(call, now), None
    else:
        method, path = call.get("method", "GET"), resolved(call["path"], now)
        body = call.get("body")
        if body is not None:
            body = json.loads(resolved(json.dumps(body), now))
    try:
        _, seconds, _ = suite.call(method, path, body, timeout=60, retry=False)
        return f"{method} {path}", seconds
    except RuntimeError as exc:
        # "<method> <path>: <status> <detail>"
        status = str(exc)[len(method) + len(path) + 3 :][:3]
        return f"{status} {path.split('?')[0]}"
    except OSError as exc:
        return f"{type(exc).__name__} {path.split('?')[0]}"


def sign_in(suite: Suite, visitor: bool) -> None:
    if not visitor:
        suite.login()
        return
    user = suite.env.get("PLANTCRAFT_PUBLIC_DEMO_USER") or "demo"
    password = suite.env.get("PLANTCRAFT_PUBLIC_DEMO_PASSWORD") or "plantcraft-demo"
    suite.call("POST", "/api/login", {"username": user, "password": password})
    # The Suite signs in again on a 401 as the administrator: keep the visitor instead.
    suite.login = lambda: suite.call("POST", "/api/login", {"username": user, "password": password})


def known_here(suite: Suite, pages: dict) -> tuple[dict, int]:
    """The recorded pages without the calls whose objects this install does not have."""
    answers: dict[str, bool] = {}
    kept, dropped = {}, 0
    for page, calls in pages.items():
        here = []
        for call in calls:
            key = json.dumps(call, sort_keys=True)
            if key not in answers:
                result = one_call(suite, call)
                answers[key] = isinstance(result, tuple) or result[:3] not in ("403", "404")
            if answers[key]:
                here.append(call)
            else:
                dropped += 1
        if here:
            kept[page] = here
    return kept, dropped


def run_step(
    prefix: Path, url: str | None, pages: dict, users: int, args, catalog: Catalog | None
) -> dict:
    step = Step(users)
    sessions = []
    for _ in range(users):
        suite = Suite(prefix, url)
        sign_in(suite, args.visitor)
        sessions.append(suite)
    until = time.time() + args.minutes * 60
    began = time.time()
    threads = []
    for number, suite in enumerate(sessions):
        pool = ThreadPoolExecutor(PARALLEL)
        thread = threading.Thread(
            target=person,
            args=(suite, pages, step, until, args, pool, catalog),
            daemon=True,
        )
        # the people arrive over the step's first half minute, not all on one tick
        time.sleep(min(30.0, args.minutes * 60 / 4) / max(users, 1))
        thread.start()
        threads.append((thread, pool))
        if number == 0:
            log(f"{users} people: walking for {args.minutes} min")
    for thread, pool in threads:
        thread.join()
        pool.shutdown()
    return step.summary(time.time() - began)


def report_md(report: dict) -> str:
    lines = [
        f"# People at once: {report['machine']['host']}, {report['started']}",
        "",
        f"Machine: {report['machine']}. Think time {report['think_s']} s; "
        f"{report['pages_known']} pages, {report['calls_per_page']} calls each on average"
        f" ({report.get('calls_left_out', 0)} recorded calls left out: not on this install).",
        "",
        "| People | Pages/s | Calls/s | Page p50 | Page p95 | Page max | Call p95 | Failed |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for step in report["steps"]:
        lines.append(
            f"| {step['users']} | {step['pages_per_s']} | {step['calls_per_s']} "
            f"| {step['page_p50_s']} s | {step['page_p95_s']} s | {step['page_max_s']} s "
            f"| {step['call_p95_s']} s | {step['failed_share'] * 100:.2f} % |"
        )
    kinds = sorted({kind for step in report["steps"] for kind in step.get("queries", {})})
    if kinds:
        lines += [
            "",
            f"Heavy questions after {report['heavy'] * 100:.0f} % of pages (p50 / p95 / max):",
            "",
            "| People | " + " | ".join(kinds) + " |",
            "|---:|" + "---:|" * len(kinds),
        ]
        for step in report["steps"]:
            cells = []
            for kind in kinds:
                found = step["queries"].get(kind)
                cells.append(
                    f"{found['p50_s']} / {found['p95_s']} / {found['max_s']} s ({found['n']})"
                    if found
                    else "-"
                )
            lines.append(f"| {step['users']} | " + " | ".join(cells) + " |")
    last = report["steps"][-1] if report["steps"] else {}
    if last.get("slowest_routes"):
        lines += [
            "",
            f"Where the time goes with {last['users']} people (routes with most seconds):",
            "",
            "| Route | Calls | Seconds | p95 |",
            "|---|---:|---:|---:|",
        ]
        lines += [
            f"| `{item['route']}` | {item['calls']} | {item['total_s']} | {item['p95_s']} s |"
            for item in last["slowest_routes"]
        ]
    lines += ["", "| Container | Peak CPU | Peak memory |", "|---|---:|---:|"]
    for service, peak in sorted(report["peak"].items()):
        lines.append(f"| {service} | {peak['cpu_percent']:.0f} % | {peak['mem_mib']:.0f} MiB |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prefix", type=Path, default=Path("dist/e2e-bundle/install"))
    parser.add_argument("--url", help="the suite's address (default from the prefix's .env)")
    parser.add_argument("--users", default="10,30,60,100", help="people at once, by step")
    parser.add_argument("--minutes", type=float, default=3.0, help="how long each step lasts")
    parser.add_argument("--think-min", type=float, default=5.0)
    parser.add_argument("--think-max", type=float, default=15.0)
    parser.add_argument("--slow", type=float, default=3.0, help="page p95 that ends the test")
    parser.add_argument(
        "--max-failed", type=float, default=0.01, help="share of failed calls that ends the test"
    )
    parser.add_argument(
        "--heavy", type=float, default=0.0, help="share of pages with a heavy question"
    )
    parser.add_argument("--visitor", action="store_true", help="as the public demo's visitor")
    parser.add_argument(
        "--seed-days",
        type=float,
        default=0,
        help="first give the bench signals this many days of history (once per installation)",
    )
    parser.add_argument("--pages", type=Path, default=PAGES)
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args()

    pages = json.loads(args.pages.read_text())
    probe = Suite(args.prefix, args.url)
    probe.login()
    sign_in(probe, args.visitor)
    pages, dropped = known_here(probe, pages)
    log(f"{len(pages)} pages; {dropped} recorded calls left out (404 or 403 here)")
    probe.login()
    if args.seed_days:
        seeded: dict = {}
        log(f"seeding {SEED_LOOPS * 3 + SEED_EXTRA} bench signals with {args.seed_days} days")
        seed_histcraft(probe, SEED_LOOPS, SEED_EXTRA, args.seed_days * 24, seeded)
        import_map(probe, SEED_LOOPS, SEED_EXTRA, seeded)
    catalog = None
    if args.heavy:
        sign_in(probe, args.visitor)
        catalog = Catalog(probe)
        probe.login()
    started = datetime.now(timezone.utc)
    sampler = Sampler(probe.env.get("COMPOSE_PROJECT_NAME", "processcraft"))
    sampler.start()
    steps = []
    for users in (int(value) for value in args.users.split(",")):
        sampler.phase = f"{users} people"
        step = run_step(args.prefix, args.url, pages, users, args, catalog)
        steps.append(step)
        log(
            f"{users} people: {step['pages_per_s']} pages/s, {step['calls_per_s']} calls/s, "
            f"page p95 {step['page_p95_s']} s, failed {step['failed_share'] * 100:.2f} %"
        )
        for kind, found in step["queries"].items():
            log(f"  {kind}: p50 {found['p50_s']} s, p95 {found['p95_s']} s ({found['n']})")
        if step["page_p95_s"] > args.slow or step["failed_share"] > args.max_failed:
            log(f"stopping: past {args.slow} s at p95 or {args.max_failed * 100:g} % failed")
            break
    sampler.stop()
    report = {
        "started": started.strftime("%Y-%m-%d %H:%M UTC"),
        "machine": machine(),
        "think_s": [args.think_min, args.think_max],
        "visitor": args.visitor,
        "heavy": args.heavy,
        "pages_known": len(pages),
        "calls_left_out": dropped,
        "calls_per_page": round(sum(len(calls) for calls in pages.values()) / len(pages), 1),
        "seeded": seeded if args.seed_days else None,
        "steps": steps,
        "peak": sampler.peak,
        "cpu_by_step": sampler.by_phase,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    name = f"{report['machine']['host']}-{started.strftime('%Y%m%dT%H%M')}-users"
    (args.out / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n")
    (args.out / f"{name}.md").write_text(report_md(report))
    log(f"report: {args.out / name}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
