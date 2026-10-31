"""JSON documents: loose files vs SQLite TEXT (today) vs SQLite JSONB vs PostgreSQL JSONB.

Saturday test day 2026-10-31, report 13 (storage). Every app keeps its objects (dashboards, loops,
rules, studies) as JSON inside its SQLite file today; this measures the alternatives on the same
documents and the same operations, one transaction per save as a request does.

    python ci/bench/storage/docs_bench.py --docs 20000 --pg "host=/var/tmp/pgbench port=55432 user=postgres"
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path

OWNERS = [f"user{i}" for i in range(200)]


def make_doc(i: int, rng: random.Random) -> dict:
    """A dashboard-like object: about 4 KB, a dozen cards, tags and an owner."""

    cards = [
        {
            "id": f"c{j}",
            "kind": rng.choice(["trend", "kpi", "table", "gauge", "text"]),
            "title": f"Card {j} of dashboard {i}",
            "signals": [
                f"signal:opc:FIC{rng.randint(1000, 9999)}.PV" for _ in range(rng.randint(1, 6))
            ],
            "window": rng.choice(["1h", "8h", "24h", "7d"]),
            "layout": {"x": j % 4, "y": j // 4, "w": 1, "h": 1},
            "options": {
                "color": rng.choice(["blue", "teal", "amber"]),
                "decimals": rng.randint(0, 3),
            },
        }
        for j in range(rng.randint(6, 18))
    ]
    return {
        "id": f"d{i:07d}",
        "name": f"Dashboard {i}",
        "owner": rng.choice(OWNERS),
        "tags": rng.sample(
            ["unit-100", "unit-200", "boiler", "compressor", "energy", "quality"], 2
        ),
        "archived": rng.random() < 0.1,
        "cards": cards,
        "revision": 1,
    }


# ---------------------------------------------------------------- back ends


class Files:
    name = "files (atomic, fsync)"

    def __init__(self, root: Path):
        self.root = root / "files"
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, doc: dict) -> None:
        path = self.root / f"{doc['id']}.json"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def get(self, doc_id: str) -> dict:
        return json.loads((self.root / f"{doc_id}.json").read_text(encoding="utf-8"))

    def patch_owner(self, doc_id: str, owner: str) -> None:
        doc = self.get(doc_id)
        doc["owner"] = owner
        self.put(doc)

    def by_owner(self, owner: str) -> int:
        return sum(
            1 for p in self.root.glob("*.json") if json.loads(p.read_bytes())["owner"] == owner
        )

    def index(self) -> None:
        pass

    def size(self) -> int:
        return sum(p.stat().st_size for p in self.root.glob("*.json"))

    def backup(self, target: Path) -> None:
        with tarfile.open(target / "files.tar", "w") as tar:
            tar.add(self.root, arcname="files")

    def restore(self, target: Path, into: Path) -> None:
        with tarfile.open(target / "files.tar") as tar:
            tar.extractall(into, filter="data")

    def close(self) -> None:
        pass


class SqliteText:
    name = "SQLite TEXT (hoje)"
    column = "body TEXT NOT NULL"

    def __init__(self, root: Path, file: str = "docs.sqlite3"):
        self.path = root / file
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute(f"CREATE TABLE IF NOT EXISTS docs (id TEXT PRIMARY KEY, {self.column})")

    def enc(self) -> str:
        return "?"

    def put(self, doc: dict) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            f"INSERT INTO docs (id, body) VALUES (?, {self.enc()}) "
            "ON CONFLICT(id) DO UPDATE SET body = excluded.body",
            (doc["id"], json.dumps(doc, separators=(",", ":"))),
        )
        self.db.execute("COMMIT")

    def get(self, doc_id: str) -> dict:
        row = self.db.execute(f"SELECT {self.out()} FROM docs WHERE id = ?", (doc_id,)).fetchone()
        return json.loads(row[0])

    def out(self) -> str:
        return "body"

    def patch_owner(self, doc_id: str, owner: str) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(f"UPDATE docs SET body = {self.setter()} WHERE id = ?", (owner, doc_id))
        self.db.execute("COMMIT")

    def setter(self) -> str:
        return "json_set(body, '$.owner', ?)"

    def by_owner(self, owner: str) -> int:
        return self.db.execute(
            "SELECT count(*) FROM docs WHERE body ->> '$.owner' = ?", (owner,)
        ).fetchone()[0]

    def index(self) -> None:
        self.db.execute("CREATE INDEX IF NOT EXISTS docs_owner ON docs (body ->> '$.owner')")

    def size(self) -> int:
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return self.path.stat().st_size

    def backup(self, target: Path) -> None:
        dest = sqlite3.connect(target / self.path.name)
        self.db.backup(dest)
        dest.close()

    def restore(self, target: Path, into: Path) -> None:
        shutil.copy2(target / self.path.name, into / self.path.name)
        con = sqlite3.connect(into / self.path.name)
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        con.close()

    def close(self) -> None:
        self.db.close()


class SqliteJsonb(SqliteText):
    name = "SQLite JSONB"
    column = "body BLOB NOT NULL"

    def __init__(self, root: Path):
        super().__init__(root, "docs-jsonb.sqlite3")

    def enc(self) -> str:
        return "jsonb(?)"

    def out(self) -> str:
        return "json(body)"

    def setter(self) -> str:
        return "jsonb_set(body, '$.owner', ?)"


class Postgres:
    name = "PostgreSQL JSONB"

    def __init__(self, dsn: str, table: str = "docs"):
        import psycopg

        self.dsn, self.table = dsn, table
        self.db = psycopg.connect(dsn, autocommit=True)
        self.db.execute(
            f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, body JSONB NOT NULL)"
        )

    def put(self, doc: dict) -> None:
        self.db.execute(
            f"INSERT INTO {self.table} (id, body) VALUES (%s, %s::jsonb) "
            "ON CONFLICT (id) DO UPDATE SET body = excluded.body",
            (doc["id"], json.dumps(doc, separators=(",", ":"))),
        )

    def get(self, doc_id: str) -> dict:
        # body::text and json.loads, so the parse cost is counted the same way as SQLite's.
        row = self.db.execute(
            f"SELECT body::text FROM {self.table} WHERE id = %s", (doc_id,)
        ).fetchone()
        return json.loads(row[0])

    def patch_owner(self, doc_id: str, owner: str) -> None:
        self.db.execute(
            f"UPDATE {self.table} SET body = jsonb_set(body, '{{owner}}', to_jsonb(%s::text)) WHERE id = %s",
            (owner, doc_id),
        )

    def by_owner(self, owner: str) -> int:
        return self.db.execute(
            f"SELECT count(*) FROM {self.table} WHERE body @> %s::jsonb",
            (json.dumps({"owner": owner}),),
        ).fetchone()[0]

    def index(self) -> None:
        self.db.execute(
            f"CREATE INDEX IF NOT EXISTS {self.table}_gin ON {self.table} USING gin (body jsonb_path_ops)"
        )
        self.db.execute(f"ANALYZE {self.table}")

    def size(self) -> int:
        return self.db.execute(f"SELECT pg_total_relation_size('{self.table}')").fetchone()[0]

    def backup(self, target: Path) -> None:
        args = dict(p.split("=", 1) for p in self.dsn.split())
        subprocess.run(
            [
                "pg_dump",
                "-h",
                args["host"],
                "-p",
                args["port"],
                "-U",
                args["user"],
                "-Fc",
                "-t",
                self.table,
                "-f",
                str(target / "pg.dump"),
                "postgres",
            ],
            check=True,
        )

    def restore(self, target: Path, into: Path) -> None:
        args = dict(p.split("=", 1) for p in self.dsn.split())
        conn = ["-h", args["host"], "-p", args["port"], "-U", args["user"]]
        subprocess.run(["dropdb", *conn, "--if-exists", "restore_test"], check=True)
        subprocess.run(["createdb", *conn, "restore_test"], check=True)
        subprocess.run(
            ["pg_restore", *conn, "-d", "restore_test", str(target / "pg.dump")], check=True
        )

    def close(self) -> None:
        self.db.close()


# ---------------------------------------------------------------- runs


def timed(fn, items) -> dict:
    lat = []
    start = time.perf_counter()
    for item in items:
        t0 = time.perf_counter()
        fn(item)
        lat.append(time.perf_counter() - t0)
    total = time.perf_counter() - start
    lat.sort()
    return {
        "ops_s": round(len(items) / total),
        "p50_ms": round(lat[len(lat) // 2] * 1000, 3),
        "p99_ms": round(lat[int(len(lat) * 0.99)] * 1000, 3),
    }


def _worker(kind: str, root: str, dsn: str, ids: list[str], seed: int, out: mp.Queue) -> None:
    store = open_store(kind, Path(root), dsn)
    rng = random.Random(seed)
    t0 = time.perf_counter()
    for doc_id in ids:
        store.patch_owner(doc_id, rng.choice(OWNERS))
    out.put(time.perf_counter() - t0)
    store.close()


def open_store(kind: str, root: Path, dsn: str):
    return {
        "files": lambda: Files(root),
        "sqlite": lambda: SqliteText(root),
        "jsonb": lambda: SqliteJsonb(root),
        "pg": lambda: Postgres(dsn),
    }[kind]()


def run(kind: str, root: Path, dsn: str, n: int, procs: int) -> dict:
    rng = random.Random(7)
    docs = [make_doc(i, rng) for i in range(n)]
    ids = [d["id"] for d in docs]
    store = open_store(kind, root, dsn)
    result = {"backend": store.name, "docs": n}
    result["insert"] = timed(store.put, docs)
    sample = [rng.choice(ids) for _ in range(5000)]
    result["get"] = timed(store.get, sample)
    changed = []
    for d in random.Random(3).sample(docs, 2000):
        d = dict(d, revision=2, name=d["name"] + " v2")
        changed.append(d)
    result["update_whole"] = timed(store.put, changed)
    result["patch_field"] = timed(lambda i: store.patch_owner(i, "user1"), sample[:2000])
    q = OWNERS[:20]
    result["query_no_index"] = timed(store.by_owner, q[:5])
    store.index()
    result["query_index"] = timed(store.by_owner, q)
    result["size_mb"] = round(store.size() / 1e6, 1)
    # concurrency: `procs` processes, 500 field patches each, on disjoint documents
    queue: mp.Queue = mp.Queue()
    chunks = [ids[i * 500 : (i + 1) * 500] for i in range(procs)]
    t0 = time.perf_counter()
    workers = [
        mp.Process(target=_worker, args=(kind, str(root), dsn, c, i, queue))
        for i, c in enumerate(chunks)
    ]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    wall = time.perf_counter() - t0
    result[f"concurrent_{procs}p_writes_s"] = round(procs * 500 / wall)
    bk = root / "backup"
    bk.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    store.backup(bk)
    result["backup_s"] = round(time.perf_counter() - t0, 2)
    result["backup_mb"] = round(sum(p.stat().st_size for p in bk.iterdir()) / 1e6, 1)
    into = root / "restored"
    into.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    store.restore(bk, into)
    result["restore_s"] = round(time.perf_counter() - t0, 2)
    store.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", type=int, default=20000)
    parser.add_argument("--procs", type=int, default=4)
    parser.add_argument("--root", default="/var/tmp/storage-bench/docs")
    parser.add_argument("--pg", default="host=/var/tmp/pgbench port=55432 user=postgres")
    parser.add_argument("--only", default="files,sqlite,jsonb,pg")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    results = []
    for kind in args.only.split(","):
        root = Path(args.root) / kind
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        if kind == "pg":
            import psycopg

            with psycopg.connect(args.pg, autocommit=True) as c:
                c.execute("DROP TABLE IF EXISTS docs")
        r = run(kind, root, args.pg, args.docs, args.procs)
        print(json.dumps(r), flush=True)
        results.append(r)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
