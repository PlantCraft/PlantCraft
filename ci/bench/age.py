#!/usr/bin/env python3
"""The suite months old in a few hours: age the bench plant in steps, measure each step (never in CI).

::

    python3 ci/bench/suite_bench.py --prefix P --scale target --keep --yes   # the bench plant
    python3 ci/bench/age.py --prefix P --months 0       # step 0: measure as it is
    python3 ci/bench/age.py --prefix P --months 3       # write the past up to 3 months, measure
    python3 ci/bench/age.py --prefix P --months 6       # adds only months 4 to 6, measure
    python3 ci/bench/age.py --compare                   # the steps side by side

A plant's problems of month 3 or month 12 do not show in a test of 72 hours, and the clock cannot
just run faster: the work grows with it (at 10x, a 106 s monitoring round of 2,000 loops is due
every minute). So the history comes first, written at the speed of the machine through the
apps' own stores, and then the suite is measured at the speed of the plant:

1. **Historian** (``hist_age.py`` in its container): the ``bench`` signals' values from the
   step's age up to their oldest, ``--rate`` per signal per day (what the compressors keep), one
   chunk per signal per hour, compacted per day, each month rewritten once closed, rollups built.
2. **Analytics** (``link_age.py`` in its container): the rows every monitoring round and signal
   check leaves (a loop's health, a signal's verdict), copied back for each past round, up to
   Analytics' 90 days.
3. **Measures**, the same at every step: the hourly maintenance of both (Historian housekeeping;
   Analytics pruning), the reads behind the history pages (a loop's month, the portfolio's week,
   the checks' week, a signal's month; the 1-year trend of a signal, a day raw, 500 signals at
   once), every page of ``load_pages.json`` once, a signal check and a monitoring round
   (``suite_bench.py``), ``--users`` people at once for ``--minutes`` (``load_users.py``), the
   size of each database and the memory of each container. ``--backup`` also times
   ``install.sh --backup`` (it stops the suite for the copy).

The state (the age written so far) is in ``<prefix>/data/age/state.json``; each step's report
in ``<prefix>/data/age/step-<months>m.json`` (and ``.md``) and in ``docs/bench/results/`` in a
checkout. Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from suite_bench import (  # noqa: E402
    RESULTS,
    Suite,
    iso,
    link_round,
    machine,
    signal_quality,
    stats,
    versions,
)

HERE = Path(__file__).resolve().parent
PAGES = HERE / "load_pages.json"
STATE = Path("data") / "age"
MONTH_DAYS = 30.44
BATCH = 500


def log(message: str) -> None:
    print(f"[age] {message}", flush=True)


def in_container(suite: Suite, service: str, script: str, env: dict[str, object]) -> dict:
    """Run ``script`` (next to this file) in ``service``'s container; its last JSON line."""

    command = ["docker", "compose", "--project-directory", str(suite.prefix)]
    command += ["--env-file", str(suite.prefix / ".env"), "exec", "-T"]
    for key, value in env.items():
        command += ["-e", f"{key}={value}"]
    command += [service, "python", "-"]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=suite.prefix,
    )
    process.stdin.write((HERE / script).read_bytes())
    process.stdin.close()
    last, shown = "", time.monotonic()
    for raw in process.stdout:
        line = raw.decode().strip()
        if line:
            last = line
            if time.monotonic() - shown > 60:  # progress, once a minute
                log(f"{service}: {line[:160]}")
                shown = time.monotonic()
    if process.wait():
        raise RuntimeError(f"{script} in {service}: {process.stderr.read().decode()[-1200:]}")
    return json.loads(last)


def write_past(suite: Suite, months: float, rate: float, state: dict) -> dict:
    days = round(months * MONTH_DAYS, 2)
    log(f"Historian: the bench signals' values back to {days} days ago ({rate:g} per day)")
    hist = in_container(suite, "histcraft", "hist_age.py", {"DAYS": days, "RATE": rate})
    log(
        f"Historian: {hist.get('written', 0):,} values in {hist.get('seconds', 0)} s, "
        f"archive {hist.get('archive_bytes', 0) / 1e9:.2f} GB"
    )
    log(f"Analytics: rounds and signal checks back to {min(days, 91)} days ago")
    link = in_container(suite, "linkcraft", "link_age.py", {"DAYS": days})
    log(
        f"Analytics: {link.get('subject_health', 0):,} loop health rows, "
        f"{link.get('quality_history', 0):,} signal check rows in {link.get('seconds')} s"
    )
    state.setdefault("written", []).append(
        {
            "at": iso(datetime.now(timezone.utc)),
            "months": months,
            "historian": hist,
            "analytics": link,
        }
    )
    state["months"] = max(months, float(state.get("months") or 0))
    return {"historian": hist, "analytics": link}


def timed_calls(suite: Suite, calls: list[str], tries: int = 1) -> dict:
    times, failed = [], 0
    for _ in range(tries):
        began = time.perf_counter()
        for path in calls:
            try:
                suite.call("GET", path, timeout=300)
            except RuntimeError:
                failed += 1
        times.append(time.perf_counter() - began)
    return {**stats(times), "failed": failed}


def http_reads(suite: Suite, months: float) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    span = max(1.0, months * MONTH_DAYS)
    out: dict = {}
    trend = (
        f"/api/v1/signals/bench:LC-{{n:05d}}.PV/series?start={{start}}&end={iso(now)}&step={{step}}"
    )
    whole = iso(now - timedelta(days=span))
    for label, start, step in (
        ("trend_whole_history_hourly", whole, 3600),
        ("trend_30d_hourly", iso(now - timedelta(days=30)), 3600),
        ("raw_day_month_ago", None, None),
    ):
        times = []
        for n in range(20):
            if start is None:  # one day, raw, a month back (or as far back as the history goes)
                back = now - timedelta(days=min(30, span))
                path = (
                    f"/api/v1/signals/bench:LC-{n:05d}.PV/series?start={iso(back - timedelta(days=1))}"
                    f"&end={iso(back)}"
                )
            else:
                path = trend.format(n=n, start=start, step=step)
            times.append(suite.call("GET", path, timeout=300)[1])
        out[label] = stats(times)
    ids = [f"bench:LC-{n:05d}.PV" for n in range(BATCH)]
    body = {"signals": ids, "start": iso(now - timedelta(hours=1)), "end": iso(now)}
    out["batch_500_last_hour"] = stats(
        [suite.call("POST", "/api/v1/series", body)[1] for _ in range(5)]
    )
    body = {"signals": ids[:100], "start": whole, "end": iso(now), "step": 86400}
    out["batch_100_whole_history_daily"] = stats(
        [suite.call("POST", "/api/v1/series", body, timeout=600)[1] for _ in range(3)]
    )
    analytics = {
        "overview": ["/link/api/overview"],
        "loop_page": ["/link/api/loops/LC-00000"],
        "signal_checks_30d": ["/link/api/signals/bench:LC-00000.PV/history?days=30"],
    }
    for label, calls in analytics.items():
        out[f"analytics_{label}"] = timed_calls(suite, calls, tries=5)
    pages = json.loads(PAGES.read_text())
    out["pages"] = {page: timed_calls(suite, calls) for page, calls in pages.items()}
    slowest = sorted(out["pages"].items(), key=lambda item: -item[1].get("max_ms", 0))[:3]
    log(
        "Slowest pages: " + ", ".join(f"{page} {value.get('max_ms')} ms" for page, value in slowest)
    )
    return out


def memory(suite: Suite) -> dict:
    project = suite.env.get("COMPOSE_PROJECT_NAME", "processcraft")
    names = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            '{{.Names}}\t{{.Label "com.docker.compose.service"}}',
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split("\n")
    services = dict(line.split("\t") for line in names if "\t" in line)
    out = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}", *services],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    found = {}
    for line in out.splitlines():
        name, usage = line.split("\t")
        found[services.get(name, name)] = usage.split("/")[0].strip()
    return found


def disk(suite: Suite) -> dict:
    found = {}
    for folder in sorted((suite.prefix / "data").iterdir()):
        if folder.is_dir():
            done = subprocess.run(["du", "-sb", str(folder)], capture_output=True, text=True)
            if done.returncode == 0:
                found[folder.name] = int(done.stdout.split()[0])
    volumes = subprocess.run(
        ["docker", "system", "df", "-v", "--format", "{{json .Volumes}}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    try:
        project = suite.env.get("COMPOSE_PROJECT_NAME", "processcraft")
        for volume in json.loads(volumes or "[]"):
            if volume.get("Name", "").startswith(project):
                found[f"volume:{volume['Name']}"] = volume.get("Size")
    except (ValueError, TypeError):
        pass
    return found


def backup(suite: Suite) -> dict:
    began = time.perf_counter()
    done = subprocess.run(
        ["./install.sh", "--backup", "--prefix", str(suite.prefix), "--yes"],
        cwd=suite.prefix,
        capture_output=True,
        text=True,
        check=False,
    )
    seconds = round(time.perf_counter() - began, 1)
    folders = sorted((suite.prefix / "backups").glob("*"))
    size = 0
    if folders:
        size = int(
            subprocess.run(
                ["du", "-sb", str(folders[-1])], capture_output=True, text=True
            ).stdout.split()[0]
        )
    return {
        "ok": done.returncode == 0,
        "seconds": seconds,
        "bytes": size,
        "tail": done.stdout[-300:],
    }


def measure(suite: Suite, months: float, args: argparse.Namespace) -> dict:
    report: dict = {"months": months}
    log("Historian: one pass of the hourly housekeeping")
    report["historian"] = in_container(suite, "histcraft", "hist_age.py", {"MEASURE": 1})
    log(f"Historian housekeeping: {report['historian']['housekeeping']}")
    log("Analytics: the hourly maintenance and the history reads")
    report["analytics"] = in_container(suite, "linkcraft", "link_age.py", {"MEASURE": 1})
    log(f"Analytics maintenance: {report['analytics']['maintenance']}")
    log(f"Analytics reads: {report['analytics']['reads']}")
    report["reads"] = http_reads(suite, months)
    if not args.skip_rounds:
        signal_quality(suite, report, timeout=3600)
        link_round(suite, report, timeout=3600)
    report["memory"] = memory(suite)
    if args.users:
        log(f"{args.users} people at once for {args.minutes:g} min")
        subprocess.run(
            [
                sys.executable,
                str(HERE / "load_users.py"),
                "--prefix",
                str(suite.prefix),
                "--users",
                str(args.users),
                "--minutes",
                str(args.minutes),
                "--out",
                str(args.out),
            ],
            check=False,
        )
        newest = sorted(Path(args.out).glob("*-users.json"))
        if newest:
            step = json.loads(newest[-1].read_text())["steps"][0]
            report["users"] = {
                key: step.get(key)
                for key in ("users", "pages_per_s", "page_p50_s", "page_p95_s", "failed_share")
            }
    report["disk"] = disk(suite)
    if args.backup:
        log("install.sh --backup (the suite stops for the copy)")
        report["backup"] = backup(suite)
    return report


def markdown(report: dict) -> str:
    hist, link = report["measure"]["historian"], report["measure"]["analytics"]
    reads = report["measure"]["reads"]
    lines = [
        f"# The suite at {report['months']:g} months ({report['started']})",
        "",
        f"Machine: {report['machine'].get('cpus')} CPUs, {report['machine'].get('memory_gib')} GB.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Historian archive | {hist.get('archive_bytes', 0) / 1e9:.2f} GB, {hist.get('chunks', 0):,} chunks |",
        f"| Historian hourly housekeeping | {hist['housekeeping']['total_s']} s {hist['housekeeping']} |",
        f"| Analytics database | {sum(link['database_bytes'].values()) / 1e9:.2f} GB |",
        f"| Analytics rows | {link['rows']} |",
        f"| Analytics hourly maintenance | {link['maintenance']['total_s']} s {link['maintenance']} |",
        f"| Analytics history reads | {link['reads']} |",
    ]
    for key in (
        "trend_whole_history_hourly",
        "trend_30d_hourly",
        "raw_day_month_ago",
        "batch_500_last_hour",
        "batch_100_whole_history_daily",
        "analytics_overview",
        "analytics_loop_page",
        "analytics_signal_checks_30d",
    ):
        value = reads.get(key) or {}
        lines.append(f"| {key} | mean {value.get('mean_ms')} ms, p95 {value.get('p95_ms')} ms |")
    measured = report["measure"]
    if "signal_quality" in measured:
        lines.append(f"| Signal check | {measured['signal_quality'].get('duration_seconds')} s |")
    for item in measured.get("link_rounds", []):
        lines.append(f"| Monitoring round ({item['round']}) | {item['duration_seconds']} s |")
    if "users" in measured:
        lines.append(f"| People at once | {measured['users']} |")
    if "backup" in measured:
        lines.append(
            f"| Backup | {measured['backup']['seconds']} s, {measured['backup']['bytes'] / 1e9:.2f} GB |"
        )
    lines.append(f"| Memory | {measured.get('memory')} |")
    return "\n".join(lines) + "\n"


def compare(folder: Path) -> None:
    rows = []
    for path in sorted(folder.glob("*-age-*m.json")):
        report = json.loads(path.read_text())
        hist, link = report["measure"]["historian"], report["measure"]["analytics"]
        reads = report["measure"]["reads"]
        rows.append(
            (
                path.stem,
                f"{hist.get('archive_bytes', 0) / 1e9:.2f}",
                hist["housekeeping"]["total_s"],
                f"{sum(link['database_bytes'].values()) / 1e9:.2f}",
                link["maintenance"]["total_s"],
                (reads.get("analytics_overview") or {}).get("mean_ms"),
                (reads.get("trend_whole_history_hourly") or {}).get("mean_ms"),
            )
        )
    print(
        "| Step | Historian GB | Housekeeping s | Analytics GB | Maintenance s | Overview ms | Whole trend ms |"
    )
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(str(value) for value in row) + " |")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--prefix", type=Path, help="the installation folder")
    parser.add_argument("--url", help="the suite's address (default from the prefix's .env)")
    parser.add_argument("--months", type=float, help="the age of this step (0: measure as it is)")
    parser.add_argument("--rate", type=float, default=940.0, help="values kept per signal per day")
    parser.add_argument("--users", type=int, default=30, help="people at once (0: none)")
    parser.add_argument("--minutes", type=float, default=3.0, help="how long the people stay")
    parser.add_argument("--skip-rounds", action="store_true", help="no signal check nor round")
    parser.add_argument("--backup", action="store_true", help="also time install.sh --backup")
    parser.add_argument("--compare", action="store_true", help="the saved steps side by side")
    parser.add_argument("--out", type=Path, default=RESULTS, help=f"reports copy ({RESULTS})")
    args = parser.parse_args()
    if args.compare:
        compare(args.out)
        return 0
    if args.prefix is None or args.months is None:
        parser.error("--prefix and --months are needed (or --compare)")
    prefix = args.prefix.expanduser().resolve()
    suite = Suite(prefix, args.url)
    suite.login()
    folder = prefix / STATE
    folder.mkdir(parents=True, exist_ok=True)
    state_file = folder / "state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    started = datetime.now(timezone.utc)
    report: dict = {
        "started": started.strftime("%Y-%m-%d %H:%M UTC"),
        "months": args.months,
        "machine": machine(),
        "versions": versions(suite),
        "rate_per_day": args.rate,
    }
    if args.months > float(state.get("months") or 0):
        report["written"] = write_past(suite, args.months, args.rate, state)
        state_file.write_text(json.dumps(state, indent=2) + "\n")
    report["measure"] = measure(suite, args.months, args)
    report["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds())
    name = f"{report['machine']['host']}-{started.strftime('%Y%m%dT%H%M')}-age-{args.months:g}m"
    text = markdown(report)
    for out in (folder, args.out):
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n")
        (out / f"{name}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
