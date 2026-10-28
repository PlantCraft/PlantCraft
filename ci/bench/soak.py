#!/usr/bin/env python3
"""The suite left running for days on one build: does it stay up, flat and fresh?

::

    python3 ci/bench/soak.py --prefix ~/PlantCraft --hours 72    # start (or resume)
    python3 ci/bench/soak.py --prefix ~/PlantCraft --report      # the report so far, any time
    python3 ci/bench/soak.py --prefix ~/PlantCraft --release     # end early, deploys again

Nothing is added to the suite: the soak watches the installation as it is, usually right after
``suite_bench.py --scale target --keep`` so the bench loops, dashboard and model algorithm keep
Link and the Historian busy at plant scale (``suite_bench.py --cleanup`` removes them after).

While it runs:

1. **One build.** ``data/deploy-hold`` holds the Mac mini's automatic deploys
   (``ci/macmini/suite-deploy`` skips while it is there and in date), so a merge does not restart
   a container in the middle of the soak; the end of the soak removes it. CI keeps running.
2. **Probes** every ``--every`` seconds (60 by default), as a person would use the suite: sign-in
   check (``/api/session``), a batch read of up to 500 signals over the last hour through API v1, the
   newest value of up to 20 live signals (how old it is: is the collector keeping up?) and, when
   the bench left it, one card of the "Bench scale" dashboard. Each probe is a line of
   ``data/soak/probes.jsonl``, so a stopped soak loses nothing and ``--report`` reads it any time.
3. **The suite's own health**, which PlantCraft already writes every minute to the Historian's
   ``system`` source (docs/operations.md, section 4): each container's up, restarts, memory, CPU,
   p95 latency, errors logged, the work queues and the free disk. The report reads them back.

The report (``data/soak/report.md`` and ``.json``, and a copy in ``docs/bench/results/`` in a
checkout) gives a verdict per check: no restart, up 99.5 % of the time, memory flat (the slope
after the first hour, as a share of the mean per day), queues that drain, the disk not filling,
probes that answer, and live values that stay fresh. Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from suite_bench import RESULTS, Suite, iso, log, machine, versions  # noqa: E402

HOLD = Path("data") / "deploy-hold"
STATE = Path("data") / "soak"
BENCH_DASHBOARD = "Bench scale"
BATCH = 500
FRESH = 20
STEP = 300  # the system signals read back on a 5-minute grid
WARM_UP_HOURS = 1.0

# The verdict's limits.
UP_MIN_PCT = 99.5
MEM_WARN_PCT_DAY = 10.0
MEM_FAIL_PCT_DAY = 25.0
QUEUE_WAIT_MAX_MIN = 30.0
DISK_WARN_DAYS = 30.0
PROBE_FAIL_MAX_PCT = 0.5
FRESH_WARN_SECONDS = 120.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def signal_ids(suite: Suite) -> list[str]:
    found, _, _ = suite.call("GET", "/api/v1/signals")
    return [str(item["id"]) for item in found or [] if item.get("id")]


# --- probes ---------------------------------------------------------------------------------


class Prober:
    """What a person does with the suite, timed; each probe one JSON line."""

    def __init__(self, suite: Suite, log_path: Path):
        self.suite = suite
        self.log_path = log_path
        self.read_ids: list[str] = []
        self.live_ids: list[str] = []
        self.dashboard: tuple[str, str] | None = None

    def discover(self) -> None:
        plant = [
            signal
            for signal in signal_ids(self.suite)
            if not signal.startswith(("system:", "app-"))
        ]
        self.read_ids = plant[:BATCH]
        # Live: a value in the last 10 minutes now (lab and file sources are not polled).
        now = utcnow()
        for signal in [signal for signal in plant if not signal.startswith("bench:")][:400]:
            if len(self.live_ids) >= FRESH:
                break
            try:
                answer, _, _ = self.suite.call(
                    "GET", f"/api/v1/signals/{signal}/value?agg=last&window=1h", timeout=60
                )
            except (RuntimeError, OSError):
                continue
            if answer and answer.get("at") and (now - when(answer["at"])).total_seconds() < 600:
                self.live_ids.append(signal)
        try:
            boards, _, _ = self.suite.call("GET", "/dash/api/dashboards")
            rows = boards.get("dashboards", boards) if isinstance(boards, dict) else boards
            for row in rows or []:
                if row.get("name") == BENCH_DASHBOARD:
                    detail, _, _ = self.suite.call(
                        "GET", f"/dash/api/dashboards/{row['dashboard_id']}"
                    )
                    cards = detail.get("cards") or []
                    if cards:
                        self.dashboard = (row["dashboard_id"], cards[0]["card_id"])
                    break
        except (RuntimeError, OSError, KeyError, TypeError):
            self.dashboard = None
        log(
            f"probes: {len(self.read_ids)} signals read, {len(self.live_ids)} live signals"
            f" watched, bench dashboard {'yes' if self.dashboard else 'no'}"
        )

    def _timed(self, name: str, method: str, path: str, body=None) -> tuple[dict, object]:
        began = time.perf_counter()
        try:
            answer, _, _ = self.suite.call(method, path, body, timeout=120)
            return {
                "probe": name,
                "ok": True,
                "ms": round(1000 * (time.perf_counter() - began)),
            }, answer
        except (RuntimeError, OSError) as exc:  # TimeoutError and URLError are OSErrors
            took = round(1000 * (time.perf_counter() - began))
            return {"probe": name, "ok": False, "ms": took, "error": str(exc)[:300]}, None

    def tick(self) -> list[dict]:
        now = utcnow().replace(microsecond=0)
        rows = [self._timed("me", "GET", "/api/session")[0]]
        if self.read_ids:
            body = {
                "signals": self.read_ids,
                "start": iso(now - timedelta(hours=1)),
                "end": iso(now),
            }
            row, answer = self._timed("batch_read", "POST", "/api/v1/series", body)
            if answer is not None:
                row["errors"] = len(answer.get("errors") or [])
            rows.append(row)
        ages = []
        for signal in self.live_ids:
            row, answer = self._timed(
                "latest", "GET", f"/api/v1/signals/{signal}/value?agg=last&window=1h"
            )
            rows.append(row if row["ok"] else {**row, "signal": signal})
            if answer and answer.get("at"):
                ages.append((now - when(answer["at"])).total_seconds())
        if ages:
            rows.append({"probe": "freshness", "ok": True, "age_s": round(max(ages), 1)})
        if self.dashboard:
            board, card = self.dashboard
            rows.append(
                self._timed("dashboard_card", "GET", f"/dash/api/dashboards/{board}/cards/{card}")[
                    0
                ]
            )
        with self.log_path.open("a") as out:
            for row in rows:
                row["at"] = iso(now)
                out.write(json.dumps(row) + "\n")
        return rows


# --- analysis (pure: tests/test_soak.py) ----------------------------------------------------


def slope_per_day(times: list[float], values: list[float]) -> float | None:
    """Least squares slope of ``values`` over ``times`` (seconds), per day; None under 3 points."""

    pairs = [(t, v) for t, v in zip(times, values) if v is not None and not math.isnan(v)]
    if len(pairs) < 3:
        return None
    mean_t = sum(t for t, _ in pairs) / len(pairs)
    mean_v = sum(v for _, v in pairs) / len(pairs)
    spread = sum((t - mean_t) ** 2 for t, _ in pairs)
    if spread == 0:
        return None
    return 86400 * sum((t - mean_t) * (v - mean_v) for t, v in pairs) / spread


def _clean(values: list) -> list[float]:
    return [float(v) for v in values if isinstance(v, (int, float)) and not math.isnan(v)]


def health_checks(series: dict[str, tuple[list[float], list]], warm_up_s: float) -> list[dict]:
    """The verdict on the ``system`` signals: ``{signal: (seconds since start, values)}``."""

    checks: list[dict] = []
    services = sorted({name.split(":", 1)[1].rsplit(".", 1)[0] for name in series})
    for service in services:

        def get(metric: str, service: str = service) -> tuple[list[float], list]:
            return series.get(f"system:{service}.{metric}", ([], []))

        up = _clean(get("up")[1])
        if up:
            pct = 100 * sum(up) / len(up)
            checks.append(_check(service, "up", f"{pct:.2f} %", pct >= UP_MIN_PCT, warn=False))
        restarts = _clean(get("restarts")[1])
        if restarts:
            grew = max(restarts) - restarts[0]
            checks.append(_check(service, "restarts", f"+{grew:.0f}", grew == 0, warn=False))
        times, mem = get("mem_mb")
        kept = [(t, v) for t, v in zip(times, mem) if t >= warm_up_s]
        values = _clean([v for _, v in kept])
        if len(values) >= 3:
            slope = slope_per_day([t for t, _ in kept], [v for _, v in kept]) or 0.0
            mean = sum(values) / len(values)
            share = 100 * slope / mean if mean else 0.0
            detail = f"{mean:.0f} MiB, {slope:+.1f} MiB/day ({share:+.1f} %/day)"
            if share > MEM_FAIL_PCT_DAY:
                checks.append(_check(service, "memory", detail, False, warn=False))
            else:
                checks.append(_check(service, "memory", detail, share <= MEM_WARN_PCT_DAY))
        wait = _clean(get("queue_wait_min")[1])
        if wait:
            top = max(wait)
            checks.append(
                _check(
                    service,
                    "queue wait",
                    f"max {top:.1f} min",
                    top <= QUEUE_WAIT_MAX_MIN,
                    warn=False,
                )
            )
        latency = _clean(get("latency_ms")[1])
        if latency:
            ordered = sorted(latency)
            median = ordered[len(ordered) // 2]
            checks.append(
                _check(
                    service,
                    "p95 latency",
                    f"median {median:.0f} ms, max {ordered[-1]:.0f} ms",
                    True,
                )
            )
        errors = _clean(get("errors")[1])
        if errors:
            total = sum(errors) * STEP / 60  # per-minute means on a 5-minute grid
            checks.append(_check(service, "errors logged", f"about {total:.0f}", total < 1))
    times, free = series.get("system:host.disk_free_gb", ([], []))
    values = _clean(free)
    if len(values) >= 3:
        slope = slope_per_day(times, free) or 0.0
        days = values[-1] / -slope if slope < 0 else math.inf
        detail = f"{values[-1]:.1f} GB free, {slope:+.2f} GB/day" + (
            f", full in {days:.0f} days" if math.isfinite(days) else ""
        )
        checks.append(_check("host", "disk", detail, days >= DISK_WARN_DAYS))
    return checks


def probe_checks(rows: list[dict]) -> list[dict]:
    checks: list[dict] = []
    for name in sorted({row["probe"] for row in rows if row["probe"] != "freshness"}):
        mine = [row for row in rows if row["probe"] == name]
        failed = [row for row in mine if not row["ok"]]
        times = sorted(row["ms"] for row in mine if row["ok"])
        pct = 100 * len(failed) / len(mine)
        p95 = times[min(len(times) - 1, int(0.95 * len(times)))] if times else 0
        detail = f"{len(mine)} probes, {len(failed)} failed ({pct:.2f} %), p95 {p95} ms"
        if failed:
            detail += f"; last error: {failed[-1].get('error', '')[:120]}"
        checks.append(_check("probe", name, detail, pct <= PROBE_FAIL_MAX_PCT, warn=False))
    ages = sorted(row["age_s"] for row in rows if row["probe"] == "freshness")
    if ages:
        p95 = ages[min(len(ages) - 1, int(0.95 * len(ages)))]
        detail = f"oldest live value p95 {p95:.0f} s, max {ages[-1]:.0f} s"
        checks.append(_check("probe", "freshness", detail, p95 <= FRESH_WARN_SECONDS))
    return checks


def _check(subject: str, check: str, detail: str, ok: bool, warn: bool = True) -> dict:
    return {
        "subject": subject,
        "check": check,
        "detail": detail,
        "result": "ok" if ok else ("warn" if warn else "FAIL"),
    }


def verdict(checks: list[dict]) -> str:
    results = {check["result"] for check in checks}
    return "FAIL" if "FAIL" in results else ("WARN" if "warn" in results else "PASS")


# --- the run ----------------------------------------------------------------------------------


def system_series(
    suite: Suite, start: datetime, end: datetime
) -> dict[str, tuple[list[float], list]]:
    ids = sorted(signal for signal in signal_ids(suite) if signal.startswith("system:"))
    out: dict[str, tuple[list[float], list]] = {}
    for offset in range(0, len(ids), BATCH):
        body = {
            "signals": ids[offset : offset + BATCH],
            "start": iso(start),
            "end": iso(end),
            "step": STEP,
        }
        answer, _, _ = suite.call("POST", "/api/v1/series", body)
        for item in answer.get("series") or []:
            seconds = [(when(t) - start).total_seconds() for t in item.get("t") or []]
            out[item["signal"]] = (seconds, list(item.get("v") or []))
    return out


def report(suite: Suite, folder: Path, state: dict, out: Path | None) -> str:
    start = when(state["started_at"])
    end = min(utcnow(), when(state["until"]))
    rows = [json.loads(line) for line in (folder / "probes.jsonl").read_text().splitlines() if line]
    try:
        series = system_series(suite, start, end)
    except RuntimeError as exc:
        log(f"the system signals could not be read: {exc}")
        series = {}
    checks = health_checks(series, WARM_UP_HOURS * 3600) + probe_checks(rows)
    hours = (end - start).total_seconds() / 3600
    result = {
        **state,
        "report_at": iso(utcnow()),
        "hours_run": round(hours, 1),
        "verdict": verdict(checks),
        "checks": checks,
    }
    if not series:
        result["note"] = "no system signals (the Historian is not the data layer, or they are off)"
    lines = [
        f"# Soak on {state['machine']['host']}: {result['verdict']}",
        "",
        f"{hours:.1f} h of {state['hours']} h, from {state['started_at']}; "
        f"{state['machine']['cpus']} CPUs, {state['machine']['memory_gib']} GiB. "
        f"Versions: `{json.dumps(state.get('versions'))}`.",
        "",
        "| Subject | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['subject']} | {check['check']} | {check['result']} | {check['detail']} |"
        )
    if "note" in result:
        lines += ["", result["note"]]
    text = "\n".join(lines) + "\n"
    (folder / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    (folder / "report.md").write_text(text)
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        name = f"{state['machine']['host']}-{start:%Y%m%d-%H%M}-soak"
        (out / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
        (out / f"{name}.md").write_text(text)
    return text


def hold(prefix: Path, until: datetime) -> None:
    path = prefix / HOLD
    path.write_text(f"{int(until.timestamp())} soak until {iso(until)} (ci/bench/soak.py)\n")


def release(prefix: Path) -> None:
    (prefix / HOLD).unlink(missing_ok=True)
    log(
        "automatic deploys are back (data/deploy-hold removed); the merges held deploy on the next push"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prefix", type=Path, required=True, help="the installation folder")
    parser.add_argument("--url", help="the suite's address (default from the prefix's .env)")
    parser.add_argument("--hours", type=float, default=72.0)
    parser.add_argument("--every", type=float, default=60.0, help="seconds between probes")
    parser.add_argument("--report", action="store_true", help="write the report so far and stop")
    parser.add_argument("--release", action="store_true", help="end the soak now")
    parser.add_argument("--no-hold", action="store_true", help="leave automatic deploys on")
    parser.add_argument("--out", type=Path, default=RESULTS, help=f"reports copy ({RESULTS})")
    args = parser.parse_args()
    prefix = args.prefix.expanduser().resolve()
    if not (prefix / ".env").exists():
        parser.error("--prefix must be an installation folder (with .env)")
    folder = prefix / STATE
    folder.mkdir(parents=True, exist_ok=True)
    state_file = folder / "soak.json"
    suite = Suite(prefix, args.url)
    suite.login()

    if args.report or args.release:
        if not state_file.exists():
            parser.error(f"no soak in {folder}")
        state = json.loads(state_file.read_text())
        if args.release:
            state["until"] = iso(min(utcnow(), when(state["until"])))
            state_file.write_text(json.dumps(state, indent=2) + "\n")
            release(prefix)
        print(report(suite, folder, state, args.out))
        return 0

    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    if state and when(state["until"]) > utcnow():
        log(f"resuming the soak started {state['started_at']}, until {state['until']}")
    else:
        started = utcnow().replace(microsecond=0)
        state = {
            "started_at": iso(started),
            "until": iso(started + timedelta(hours=args.hours)),
            "hours": args.hours,
            "machine": machine(),
            "versions": versions(suite),
            "hold": not args.no_hold,
        }
        (folder / "probes.jsonl").write_text("")
        state_file.write_text(json.dumps(state, indent=2) + "\n")
        log(f"soak of {args.hours:g} h on {suite.url}, until {state['until']}")
    until = when(state["until"])
    if state["hold"]:
        hold(prefix, until)
        log("automatic deploys held until the end (data/deploy-hold)")
    prober = Prober(suite, folder / "probes.jsonl")
    prober.discover()
    last_report = time.monotonic()
    try:
        while utcnow() < until:
            began = time.monotonic()
            failed = [row for row in prober.tick() if not row["ok"]]
            if failed:
                log(f"{len(failed)} probe(s) failed: {failed[0].get('error', '')[:160]}")
            if time.monotonic() - last_report > 6 * 3600:
                report(suite, folder, state, None)  # a fresh report.md every 6 h
                last_report = time.monotonic()
            time.sleep(max(1.0, args.every - (time.monotonic() - began)))
    except KeyboardInterrupt:
        log("stopped: run it again to resume, or --release to end it")
        return 1
    if state["hold"]:
        release(prefix)
    print(report(suite, folder, state, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
