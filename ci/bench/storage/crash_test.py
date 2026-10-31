"""kill -9 in the middle of saves: what survives? (report 13, 2026-10-31)

A writer process saves the same 50 documents over and over; it is killed at a random moment,
200 times. After each kill every document must still read as valid JSON. Compared: a plain
``write_text`` (as Models writes files.json today), write-to-temporary + ``os.replace`` (as the
installer writes its state), SQLite (WAL) and PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import shutil
import signal
import sqlite3
import time
from pathlib import Path

DOC = {"cards": [{"id": i, "title": "x" * 200} for i in range(40)]}


def writer(kind: str, root: str, dsn: str) -> None:
    root = Path(root)
    n = 0
    if kind == "sqlite":
        con = sqlite3.connect(root / "d.sqlite3", isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
    if kind == "pg":
        import psycopg

        con = psycopg.connect(dsn, autocommit=True)
    while True:
        n += 1
        i = n % 50
        body = json.dumps(dict(DOC, n=n))
        if kind == "plain":
            (root / f"{i}.json").write_text(body)
        elif kind == "atomic":
            tmp = root / f"{i}.tmp"
            tmp.write_text(body)
            os.replace(tmp, root / f"{i}.json")
        elif kind == "sqlite":
            con.execute(
                "INSERT INTO d (id, body) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (i, body),
            )
        else:
            con.execute(
                "INSERT INTO crash (id, body) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET body=excluded.body",
                (i, body),
            )


def check(kind: str, root: Path, dsn: str) -> int:
    bad = 0
    if kind in ("plain", "atomic"):
        for p in root.glob("*.json"):
            try:
                json.loads(p.read_text())
            except ValueError:
                bad += 1
    elif kind == "sqlite":
        con = sqlite3.connect(root / "d.sqlite3")
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for (body,) in con.execute("SELECT body FROM d"):
            try:
                json.loads(body)
            except ValueError:
                bad += 1
        con.close()
    else:
        import psycopg

        with psycopg.connect(dsn) as con:
            for (body,) in con.execute("SELECT body FROM crash"):
                try:
                    json.loads(body)
                except ValueError:
                    bad += 1
    return bad


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kills", type=int, default=200)
    ap.add_argument("--root", default="/var/tmp/storage-bench/crash")
    ap.add_argument("--pg", default="host=/var/tmp/pgbench port=55432 user=postgres")
    args = ap.parse_args()
    for kind in ("plain", "atomic", "sqlite", "pg"):
        root = Path(args.root) / kind
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        if kind == "sqlite":
            sqlite3.connect(root / "d.sqlite3").execute(
                "CREATE TABLE d (id INTEGER PRIMARY KEY, body TEXT)"
            )
        if kind == "pg":
            import psycopg

            with psycopg.connect(args.pg, autocommit=True) as c:
                c.execute("DROP TABLE IF EXISTS crash")
                c.execute("CREATE TABLE crash (id INT PRIMARY KEY, body TEXT)")
        rng = random.Random(1)
        broken_runs = broken_docs = 0
        for _ in range(args.kills):
            p = mp.Process(target=writer, args=(kind, str(root), args.pg))
            p.start()
            time.sleep(rng.uniform(0.05, 0.25))
            os.kill(p.pid, signal.SIGKILL)
            p.join()
            bad = check(kind, root, args.pg)
            broken_docs += bad
            broken_runs += bool(bad)
            if kind == "plain" and bad:  # repair so the next round starts clean
                for q in root.glob("*.json"):
                    q.unlink()
        print(
            json.dumps(
                {
                    "kind": kind,
                    "kills": args.kills,
                    "kills_with_broken_doc": broken_runs,
                    "broken_docs_total": broken_docs,
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
