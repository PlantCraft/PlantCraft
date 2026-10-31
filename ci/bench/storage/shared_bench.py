"""One SQLite per app (today) vs one shared SQLite vs one PostgreSQL with a schema per app.

Saturday test day 2026-10-31, report 13 (storage). Six app processes run requests at the same
time for a fixed time. A read request does 30 point reads (PlantCraft asks its stores 20 to 40
times per request); a write request does 3 small writes in one transaction. "noisy" adds a
seventh process that keeps writing batches of 5,000 rows into app0's tables (a results save, an
import), the case where a shared file makes everyone wait.

    python ci/bench/storage/shared_bench.py --seconds 8
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import random
import shutil
import sqlite3
import time
from pathlib import Path

APPS = ["platform", "link", "historian", "view", "alarms", "models"]
ROWS = 50_000
PAYLOAD = json.dumps({"k": "x" * 250})


def sqlite_conn(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=60, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    return con


class SqliteApp:
    def __init__(self, path: Path, app: str):
        self.con, self.t = sqlite_conn(path), f"{app}_objects"

    def setup(self) -> None:
        self.con.execute(f"CREATE TABLE IF NOT EXISTS {self.t} (id INTEGER PRIMARY KEY, body TEXT)")
        self.con.execute("BEGIN IMMEDIATE")
        self.con.executemany(
            f"INSERT INTO {self.t} (id, body) VALUES (?, ?)", ((i, PAYLOAD) for i in range(ROWS))
        )
        self.con.execute("COMMIT")

    def read(self, ids) -> None:
        for i in ids:
            self.con.execute(f"SELECT body FROM {self.t} WHERE id = ?", (i,)).fetchone()

    def write(self, rows) -> None:
        self.con.execute("BEGIN IMMEDIATE")
        self.con.executemany(
            f"INSERT INTO {self.t} (body) VALUES (?)", ((PAYLOAD,) for _ in range(rows))
        )
        self.con.execute("COMMIT")


class PgApp:
    def __init__(self, dsn: str, app: str):
        import psycopg

        self.con = psycopg.connect(dsn, autocommit=True)
        self.t = f"{app}.objects"
        self.app = app

    def setup(self) -> None:
        self.con.execute(f"DROP SCHEMA IF EXISTS {self.app} CASCADE")
        self.con.execute(f"CREATE SCHEMA {self.app}")
        self.con.execute(f"CREATE TABLE {self.t} (id BIGSERIAL PRIMARY KEY, body TEXT)")
        with self.con.cursor() as cur, cur.copy(f"COPY {self.t} (id, body) FROM STDIN") as copy:
            for i in range(ROWS):
                copy.write_row((i, PAYLOAD))
        self.con.execute(f"SELECT setval('{self.t}_id_seq', {ROWS})")
        self.con.execute(f"ANALYZE {self.t}")

    def read(self, ids) -> None:
        for i in ids:
            self.con.execute(f"SELECT body FROM {self.t} WHERE id = %s", (i,)).fetchone()

    def write(self, rows) -> None:
        with self.con.transaction(), self.con.cursor() as cur:
            cur.executemany(f"INSERT INTO {self.t} (body) VALUES (%s)", [(PAYLOAD,)] * rows)


def open_app(layout: str, root: Path, dsn: str, tcp: str, app: str):
    if layout == "per-app":
        return SqliteApp(root / f"{app}.sqlite3", app)
    if layout == "shared-sqlite":
        return SqliteApp(root / "suite.sqlite3", app)
    return PgApp(tcp if layout == "pg-tcp" else dsn, app)


def app_worker(layout, root, dsn, tcp, app, seconds, start, out):
    store = open_app(layout, Path(root), dsn, tcp, app)
    rng = random.Random(app)
    lat_r, lat_w = [], []
    start.wait()
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        t0 = time.perf_counter()
        if rng.random() < 0.9:
            store.read([rng.randrange(ROWS) for _ in range(30)])
            lat_r.append(time.perf_counter() - t0)
        else:
            store.write(3)
            lat_w.append(time.perf_counter() - t0)
    out.put((app, lat_r, lat_w))


def noisy_worker(layout, root, dsn, tcp, seconds, start, out):
    store = open_app(layout, Path(root), dsn, tcp, APPS[0])
    start.wait()
    end, batches = time.perf_counter() + seconds, 0
    while time.perf_counter() < end:
        store.write(5000)
        batches += 1
    out.put(("noisy", batches, None))


def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * p))] * 1000, 2)


def run(layout, root, dsn, tcp, seconds, noisy):
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for app in APPS:
        open_app(layout, root, dsn, tcp, app).setup()
    start, out = mp.Event(), mp.Queue()
    procs = [
        mp.Process(target=app_worker, args=(layout, str(root), dsn, tcp, a, seconds, start, out))
        for a in APPS
    ]
    if noisy:
        procs.append(
            mp.Process(target=noisy_worker, args=(layout, str(root), dsn, tcp, seconds, start, out))
        )
    for p in procs:
        p.start()
    time.sleep(1)
    start.set()
    got = [out.get() for _ in procs]
    for p in procs:
        p.join()
    reads = [x for a, r, w in got if a != "noisy" for x in r]
    writes = [x for a, r, w in got if a != "noisy" for x in w]
    others_w = [x for a, r, w in got if a not in ("noisy", APPS[0]) for x in w]
    res = {
        "layout": layout,
        "noisy": noisy,
        "requests_s": round((len(reads) + len(writes)) / seconds),
        "read_req_p50_ms": pct(reads, 0.5),
        "read_req_p99_ms": pct(reads, 0.99),
        "write_req_p50_ms": pct(writes, 0.5),
        "write_req_p99_ms": pct(writes, 0.99),
        "other_apps_write_p99_ms": pct(others_w, 0.99),
    }
    if noisy:
        res["noisy_batches"] = next(r for a, r, w in got if a == "noisy")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=8)
    ap.add_argument("--root", default="/var/tmp/storage-bench/shared")
    ap.add_argument("--pg", default="host=/var/tmp/pgbench port=55432 user=postgres")
    ap.add_argument("--pg-tcp", default="host=127.0.0.1 port=55432 user=postgres")
    ap.add_argument("--layouts", default="per-app,shared-sqlite,pg-socket,pg-tcp")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    results = []
    for noisy in (False, True):
        for layout in args.layouts.split(","):
            r = run(layout, Path(args.root) / layout, args.pg, args.pg_tcp, args.seconds, noisy)
            print(json.dumps(r), flush=True)
            results.append(r)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
