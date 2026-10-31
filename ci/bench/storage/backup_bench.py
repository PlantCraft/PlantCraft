"""The suite's backup with every app writing: how long, and which instant each database holds.

Report 13 (storage), 2026-10-31. Builds an install folder with one SQLite per app (sizes like a
year-old installation), starts one writer per app (``--rate`` commits a second, Analytics ten
times more), and runs ``plantcraft.ops.snapshot.take`` on it, as ``install.sh --backup`` does.
Each writer stamps every commit with the time, so the copy of each database tells the instant
it holds; the spread between the earliest and the latest is the backup's skew between apps.

    python ci/bench/storage/backup_bench.py --scale 1.0 --rate 20
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from plantcraft.ops import snapshot  # noqa: E402

# Megabytes per database at scale 1 (a year of a mid-size plant, estimated).
APPS = {
    "processcraft/processcraft.sqlite3": 300,
    "linkcraft/linkcraft.sqlite3": 600,
    "doccraft/doccraft.sqlite3": 300,
    "dashcraft/dashcraft.sqlite3": 80,
    "alarmcraft/alarmcraft.sqlite3": 150,
    "modelcraft/modelcraft.sqlite3": 80,
    "histcraft/queue.sqlite3": 20,
}
ROW = os.urandom(3000)


def build(install: Path, scale: float) -> None:
    for relative, megabytes in APPS.items():
        path = install / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE objects (id INTEGER PRIMARY KEY, body BLOB)")
        con.execute("CREATE TABLE ticks (id INTEGER PRIMARY KEY, at REAL)")
        rows = int(megabytes * scale * 1e6 / len(ROW))
        con.executemany("INSERT INTO objects (body) VALUES (?)", ((ROW,) for _ in range(rows)))
        con.commit()
        con.close()
    (install / ".env").write_text("X=1\n")


def writer(path: str, rate: float, stop) -> None:
    con = sqlite3.connect(path, timeout=60, isolation_level=None)
    con.execute("PRAGMA busy_timeout=60000")
    pause = 1 / rate
    while not stop.is_set():
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO objects (body) VALUES (?)", (ROW[:500],))
        con.execute("INSERT INTO ticks (at) VALUES (?)", (time.time(),))
        con.execute("COMMIT")
        time.sleep(pause)


def instants(folder: Path) -> dict[str, float]:
    found = {}
    with tempfile.TemporaryDirectory() as scratch, tarfile.open(folder / snapshot.ARCHIVE) as tar:
        tar.extractall(scratch, filter="data")
        for relative in APPS:
            con = sqlite3.connect(Path(scratch) / "data" / relative)
            found[relative.split("/")[0]] = con.execute("SELECT max(at) FROM ticks").fetchone()[0]
            con.close()
    return found


def run(root: Path, scale: float, rate: float, label: str) -> dict:
    install = root / "install"
    out = root / f"backup-{label}"
    shutil.rmtree(out, ignore_errors=True)
    stop = mp.Event()
    procs = [
        mp.Process(
            target=writer,
            args=(str(install / "data" / rel), rate * (10 if "link" in rel else 1), stop),
        )
        for rel in APPS
    ]
    if rate:
        for p in procs:
            p.start()
        time.sleep(2)
    t0 = time.time()
    manifest = snapshot.take(install, out, reason="manual")
    took = time.time() - t0
    stop.set()
    if rate:
        for p in procs:
            p.join()
    result = {"label": label, "scale": scale, "rate": rate, "seconds": round(took, 1),
              "archive_mb": round(manifest["archive"]["size"] / 1e6)}  # fmt: skip
    if rate:
        at = instants(out)
        result["skew_s"] = round(max(at.values()) - min(at.values()), 1)
        result["instant_after_start_s"] = {k: round(v - t0, 1) for k, v in at.items()}
    t0 = time.time()
    problems = snapshot.verify(out)
    result["verify_s"] = round(time.time() - t0, 1)
    result["verify_ok"] = not problems
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/var/tmp/storage-bench/backup")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--rate", type=float, default=20)
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    root = Path(args.root)
    if not (root / "install").exists():
        build(root / "install", args.scale)
    results = [run(root, args.scale, 0, "idle"), run(root, args.scale, args.rate, "writing")]
    for r in results:
        print(json.dumps(r), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
