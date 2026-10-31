"""A3: PostgreSQL layouts "keyed by tag", on the same dense dataset (source plant: 2000 points x
2 days, 61.8 M values from the Historian's real compressor).

  build: python layouts.py build      (reads the Historian archive once, writes the layouts)
  bench: python layouts.py bench      (cold and warm reads, JSON lines)

Layouts (schema lay):
  chunks  A3.1 today's archive (zstd chunks per point, PK (point, t0), monthly partitions)
  rows    A3.2 one row per value (tag, t, v), B-tree (tag, t) INCLUDE (v), CLUSTERed
  brin    A3.3 the same rows, BRIN (tag, t) only
  hpart   A3.4 rows partitioned by HASH(tag) into 16 tables, B-tree (tag, t) INCLUDE (v)
  blobs   A3.5 one row per tag and hour: raw int64 times + float64 values (bytea, no codec)
Queries: 200 tags x 24 h, 2000 tags x 24 h, 1 tag x 48 h, into numpy arrays in Python.
"""
import io, json, sys, time
import numpy as np, psycopg
DB = "postgresql://postgres@/hist?host=/tmp&port=55432"

def conn():
    return psycopg.connect(DB, autocommit=True)

def build():
    from histcraft.archive.store import ArchiveStore
    from histcraft.catalog.store import CatalogStore
    from histcraft.db import Database
    cat = CatalogStore(Database(DB)); arch = ArchiveStore(Database(DB))
    pts = sorted(cat.points(source_id="plant"), key=lambda p: p["tag"])
    ids = [int(p["id"]) for p in pts]
    c = conn()
    c.execute("DROP SCHEMA IF EXISTS lay CASCADE; CREATE SCHEMA lay")
    c.execute("CREATE TABLE lay.blobs (tag int, hour bigint, n int, t bytea, v bytea, PRIMARY KEY (tag, hour))")
    c.execute("CREATE UNLOGGED TABLE lay.stage (tag int, t bigint, v float8)")
    t0 = time.perf_counter(); total = 0
    for off in range(0, len(ids), 100):
        got = arch.read_many(ids[off:off + 100], -(2**62), 2**62)
        buf = io.StringIO(); blobs = []
        for pid, (t, v) in got.items():
            v = np.asarray(v, dtype=float); total += len(t)
            np.savetxt(buf, np.column_stack([np.full(len(t), pid), t, v]), fmt=["%d", "%d", "%.9g"], delimiter="\t")
            hours = t // 3_600_000
            for h in np.unique(hours):
                m = hours == h
                blobs.append((pid, int(h) * 3_600_000, int(m.sum()), t[m].astype("<i8").tobytes(), v[m].astype("<f8").tobytes()))
        with c.cursor() as cur:
            with cur.copy("COPY lay.stage FROM STDIN") as cp:
                cp.write(buf.getvalue())
            cur.executemany("INSERT INTO lay.blobs VALUES (%s,%s,%s,%s,%s)", blobs)
        print("exported", off + 100, total, round(time.perf_counter() - t0), flush=True)
    steps = [
        "CREATE TABLE lay.rows AS SELECT * FROM lay.stage ORDER BY tag, t",
        "CREATE INDEX rows_tag_t ON lay.rows (tag, t) INCLUDE (v)",
        "CLUSTER lay.rows USING rows_tag_t",
        "CREATE TABLE lay.brin AS SELECT * FROM lay.stage ORDER BY tag, t",
        "CREATE INDEX brin_tag_t ON lay.brin USING brin (tag, t) WITH (pages_per_range = 16)",
        "CREATE TABLE lay.hpart (tag int, t bigint, v float8) PARTITION BY HASH (tag)",
        *[f"CREATE TABLE lay.hpart_{i} PARTITION OF lay.hpart FOR VALUES WITH (MODULUS 16, REMAINDER {i})" for i in range(16)],
        "INSERT INTO lay.hpart SELECT * FROM lay.stage ORDER BY tag, t",
        "CREATE INDEX hpart_tag_t ON lay.hpart (tag, t) INCLUDE (v)",
        "DROP TABLE lay.stage",
        "VACUUM ANALYZE lay.rows", "VACUUM ANALYZE lay.brin", "VACUUM ANALYZE lay.hpart", "VACUUM ANALYZE lay.blobs",
        "VACUUM ANALYZE",
    ]
    for sql in steps:
        t1 = time.perf_counter(); c.execute(sql); print(round(time.perf_counter() - t1, 1), "s", sql[:70], flush=True)
    print(json.dumps({"values": total, "ids": len(ids)}))

def sizes(c):
    out = {}
    for name, rel in [("chunks", "chunks"), ("rows", "lay.rows"), ("brin", "lay.brin"), ("hpart", "lay.hpart"), ("blobs", "lay.blobs")]:
        if name in ("chunks", "hpart"):
            q = f"SELECT sum(pg_total_relation_size(inhrelid)) FROM pg_inherits WHERE inhparent = '{rel}'::regclass"
        else:
            q = f"SELECT pg_total_relation_size('{rel}')"
        out[name] = int(c.execute(q).fetchone()[0] or 0)
    return out

def read_rows(c, table, tags, start, end):
    rows = c.execute(f"SELECT tag, t, v FROM {table} WHERE tag = ANY(%s) AND t >= %s AND t <= %s ORDER BY tag, t",
                     (tags, start, end)).fetchall()
    a = np.array(rows, dtype=float) if rows else np.zeros((0, 3))
    return len(a)

def read_rows_copy(c, table, tags, start, end):
    """The same rows through COPY ... TO STDOUT (BINARY would be faster still), parsed by numpy."""
    buf = io.BytesIO()
    q = f"COPY (SELECT tag, t, v FROM {table} WHERE tag = ANY('{{{','.join(map(str, tags))}}}') AND t >= {start} AND t <= {end} ORDER BY tag, t) TO STDOUT"
    with c.cursor().copy(q) as cp:
        for block in cp:
            buf.write(block)
    buf.seek(0)
    a = np.loadtxt(buf, dtype=float, ndmin=2) if buf.getbuffer().nbytes else np.zeros((0, 3))
    return len(a)

def read_blobs(c, tags, start, end):
    rows = c.execute("SELECT tag, n, t, v FROM lay.blobs WHERE tag = ANY(%s) AND hour >= %s AND hour <= %s ORDER BY tag, hour",
                     (tags, start // 3_600_000 * 3_600_000, end)).fetchall()
    n = 0
    for _, cnt, t, v in rows:
        tt = np.frombuffer(t, "<i8"); vv = np.frombuffer(v, "<f8"); m = (tt >= start) & (tt <= end); n += int(m.sum())
    return n

def read_chunks(arch, tags, start, end):
    got = arch.read_many(tags, start, end)
    return sum(int(((t >= start) & (t <= end)).sum()) for t, _ in got.values())

def drop_caches(c):
    # Cold-ish: PostgreSQL's buffers emptied by a restart is not possible here; pg_buffercache-free way:
    # read a big unrelated table? We report warm (second run) numbers and first-run numbers.
    pass

def bench():
    from histcraft.archive.store import ArchiveStore
    from histcraft.db import Database
    arch = ArchiveStore(Database(DB))
    c = conn()
    ids = [r[0] for r in c.execute("SELECT DISTINCT tag FROM lay.blobs ORDER BY tag").fetchall()]
    end = c.execute("SELECT max(hour) FROM lay.blobs").fetchone()[0] + 3_600_000
    print(json.dumps({"sizes_MB": {k: round(v / 1e6) for k, v in sizes(c).items()}}), flush=True)
    queries = [("200 x 24 h", ids[:200], end - 86_400_000), ("2000 x 24 h", ids, end - 86_400_000),
               ("1 x 48 h", ids[:1], end - 2 * 86_400_000), ("200 x 1 h", ids[:200], end - 3_600_000)]
    for label, tags, start in queries:
        for name, fn in [("chunks (today, decoded)", lambda: read_chunks(arch, tags, start, end)),
                         ("rows btree, fetchall", lambda: read_rows(c, "lay.rows", tags, start, end)),
                         ("rows btree, COPY", lambda: read_rows_copy(c, "lay.rows", tags, start, end)),
                         ("rows brin, fetchall", lambda: read_rows(c, "lay.brin", tags, start, end)),
                         ("hash partitions, fetchall", lambda: read_rows(c, "lay.hpart", tags, start, end)),
                         ("blobs per hour", lambda: read_blobs(c, tags, start, end))]:
            times = []
            for _ in range(3):
                t0 = time.perf_counter(); n = fn(); times.append(time.perf_counter() - t0)
            print(json.dumps({"query": label, "layout": name, "values": n, "first_s": round(times[0], 3),
                              "warm_s": round(min(times[1:]), 3)}), flush=True)

if __name__ == "__main__":
    {"build": build, "bench": bench}[sys.argv[1]]()
