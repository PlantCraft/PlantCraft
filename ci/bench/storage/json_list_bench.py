"""Filters that look inside a JSON list: an asset's runs and the texts about a reference.

Report 13 (storage), 2026-10-31. ``ResultStore.runs(subject=...)`` (the asset page, the
assistant's facts) and ``KnowledgeStore.about(ref)`` (the assistant) keep the rows whose
``subjects_json`` list holds a value. This fills the real tables (``--runs`` runs over 90 days,
each on 1 to 20 of ``--assets`` assets; ``--texts`` texts on 1 to 5 each) and times the real
methods, and ``put_runs`` for the cost on writes.

    python ci/bench/storage/json_list_bench.py --runs 200000 --texts 20000
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from plantcraft.db import Database  # noqa: E402
from plantcraft.knowledge import KnowledgeStore  # noqa: E402
from plantcraft.results import ResultStore  # noqa: E402

NOW = "2026-10-31T00:00:00.000Z"
CUTOFF = "2026-08-01T00:00:00.000Z"


def run_item(i: int, rng: random.Random, assets: int) -> dict:
    subjects = [f"asset:a{rng.randrange(assets)}" for _ in range(rng.randint(1, 20))]
    return {"app": rng.choice(["linkcraft", "alarmcraft", "modelcraft"]), "id": f"r{i}",
            "name": "Round", "status": "done", "trigger": "schedule",
            "started_at": f"2026-{rng.randint(8, 10):02d}-{rng.randint(1, 28):02d}T10:00:00.000Z",
            "finished_at": None, "subjects": subjects, "summary": "ok", "url": None}  # fmt: skip


def timed(fn, args) -> dict:
    lat = []
    for a in args:
        t0 = time.perf_counter()
        fn(a)
        lat.append(time.perf_counter() - t0)
    lat.sort()
    return {"p50_ms": round(statistics.median(lat) * 1000, 2),
            "p95_ms": round(lat[int(len(lat) * 0.95)] * 1000, 2)}  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200_000)
    ap.add_argument("--texts", type=int, default=20_000)
    ap.add_argument("--assets", type=int, default=2000)
    args = ap.parse_args()
    rng = random.Random(9)
    with tempfile.TemporaryDirectory() as folder:
        db = Database(Path(folder) / "processcraft.sqlite3")
        results, knowledge = ResultStore(db), KnowledgeStore(db)
        t0 = time.perf_counter()
        for start in range(0, args.runs, 5000):
            batch = [
                run_item(i, rng, args.assets) for i in range(start, min(args.runs, start + 5000))
            ]
            results.put_runs(batch, now=NOW, cutoff=CUTOFF)
        fill_s = time.perf_counter() - t0
        texts = [{"app": "linkcraft", "ref": f"loop:l{i}", "kind": "loop", "title": "t", "text": "x" * 400,
                  "subjects": [f"asset:a{rng.randrange(args.assets)}" for _ in range(rng.randint(1, 5))]}
                 for i in range(args.texts)]  # fmt: skip
        knowledge.put(texts, now=NOW, cutoff=CUTOFF)
        with db.connect() as c:
            c.execute("ANALYZE")
            c.commit()
        asks = [f"asset:a{rng.randrange(args.assets)}" for _ in range(40)]
        one = [run_item(args.runs + i, rng, args.assets) for i in range(200)]
        out = {
            "runs": args.runs, "texts": args.texts,
            "fill_runs_s": round(fill_s, 1),
            "runs_by_subject": timed(lambda s: results.runs(subject=s, limit=8), asks),
            "knowledge_about": timed(knowledge.about, asks),
            "put_one_run": timed(lambda r: results.put_runs([r], now=NOW, cutoff=CUTOFF), one),
            "found": len(results.runs(subject=asks[0], limit=8)),
        }  # fmt: skip
        with db.connect() as c:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        out["db_mb"] = round(db.path.stat().st_size / 1e6, 1)
        print(json.dumps(out))


if __name__ == "__main__":
    main()
