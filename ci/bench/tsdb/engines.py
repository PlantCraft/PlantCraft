"""The databases under test (A4), one class each, same interface, each in its own Docker container.

    eng = ENGINES["clickhouse"]()
    eng.start()                     # docker run, limits CPUS / MEMORY, data in VOL/<key>
    eng.load_day(p, t, v)           # one dataset day, sorted by (point, t)
    eng.finish()                    # what a real install does in the background: merges, compression
    eng.raw_many(ids, t0, t1)       # {point: (t ms int64, v float64)} for t in [t0, t1)
    eng.grid(ids, t0, t1, step_ms)  # {point: (bucket ms, mean)} computed by the database
    eng.last(ids)                   # {point: (t, v)} newest value
    eng.stop()

Every read ends in numpy arrays in this Python process, through the fastest client protocol the
database offers (Arrow where it exists): that is what an app such as Analytics would pay.
A worker process attaches to a running container with ``ENGINES[key]()`` (no ``start``).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

VOL = Path(os.environ.get("TSDB_VOL", "/var/tmp/tsdb/vol"))
CPUS = os.environ.get("TSDB_CPUS", "4")
MEMORY = os.environ.get("TSDB_MEMORY", "4g")
HOST = os.environ.get("TSDB_HOST", "127.0.0.1")
EPOCH_2000_US = 946_684_800_000_000
CHUNK_VALUES = 10_000


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, check=check, capture_output=True, text=True).stdout


def http(
    url: str,
    data: bytes | None = None,
    headers: dict | None = None,
    method: str | None = None,
    timeout=600,
):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def wait(fn, seconds: float = 120.0):
    end = time.time() + seconds
    last = None
    while time.time() < end:
        try:
            if fn():
                return
        except Exception as exc:  # noqa: BLE001 - any failure means "not up yet"
            last = exc
        time.sleep(1)
    raise TimeoutError(f"not ready: {last}")


def split(p: np.ndarray):
    """(point, start, end) slices of an array sorted by point."""
    if len(p) == 0:
        return []
    cut = np.flatnonzero(np.diff(p)) + 1
    starts = np.concatenate([[0], cut])
    ends = np.concatenate([cut, [len(p)]])
    return [(int(p[s]), int(s), int(e)) for s, e in zip(starts, ends)]


def group(p: np.ndarray, t: np.ndarray, v: np.ndarray) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    order = np.lexsort((t, p))
    p, t, v = p[order], t[order], v[order]
    return {pt: (t[s:e], v[s:e]) for pt, s, e in split(p)}


def ints(col) -> np.ndarray:
    """A text/dictionary id column (QuestDB SYMBOL, InfluxDB tag) as int32, vectorised."""
    import pyarrow as pa
    import pyarrow.compute as pc

    col = col.combine_chunks() if hasattr(col, "combine_chunks") else col
    if pa.types.is_dictionary(col.type):
        col = col.dictionary_decode()
    return pc.cast(pc.cast(col, pa.string()), pa.int32()).to_numpy(zero_copy_only=False)


def bucket_means(t: np.ndarray, v: np.ndarray, t0: int, t1: int, step_ms: int):
    """Client-side grid (what today's Historian does after reading raw values)."""
    n = int(np.ceil((t1 - t0) / step_ms))
    idx = ((t - t0) // step_ms).astype(np.int64)
    ok = (idx >= 0) & (idx < n)
    s = np.bincount(idx[ok], weights=v[ok], minlength=n)
    c = np.bincount(idx[ok], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return t0 + np.arange(n, dtype=np.int64) * step_ms, s / c


class Engine:
    key = ""
    name = ""
    image = ""
    ports: list[str] = []
    data_dir = "/data"  # inside the container
    run_args: list[str] = []
    command: list[str] = []
    license = ""

    @property
    def container(self) -> str:
        return f"tsdb-{self.key}"

    @property
    def vol(self) -> Path:
        return VOL / self.key

    def start(self):
        self.stop()
        self.vol.mkdir(parents=True, exist_ok=True)
        os.chmod(self.vol, 0o777)
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            self.container,
            f"--cpus={CPUS}",
            f"--memory={MEMORY}",
            "-v",
            f"{self.vol}:{self.data_dir}",
        ]
        for port in self.ports:
            args += ["-p", f"{port}:{port}"]
        sh(*args, *self.run_args, self.image, *self.command)
        wait(self.ready)
        self.setup()

    def stop(self):
        sh("docker", "rm", "-f", self.container, check=False)
        if self.vol.exists():
            subprocess.run(["rm", "-rf", str(self.vol)], check=False)

    def ready(self) -> bool:
        raise NotImplementedError

    def setup(self):
        pass

    def finish(self):
        pass

    def size(self) -> int:
        out = sh("du", "-sb", str(self.vol))
        return int(out.split()[0])

    def ram(self) -> int:
        """Resident memory of the container (bytes), as docker stats reports it."""
        out = (
            sh("docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", self.container)
            .split("/")[0]
            .strip()
        )
        units = {
            "KiB": 1024,
            "MiB": 1024**2,
            "GiB": 1024**3,
            "B": 1,
            "kB": 1000,
            "MB": 1e6,
            "GB": 1e9,
        }
        for u, f in sorted(units.items(), key=lambda x: -len(x[0])):
            if out.endswith(u):
                return int(float(out[: -len(u)]) * f)
        return 0

    def image_bytes(self) -> int:
        out = sh("docker", "image", "inspect", self.image, "--format", "{{.Size}}")
        return int(out.strip() or 0)

    def version(self) -> str:
        return ""

    # reads ---------------------------------------------------------------------------------
    def raw_many(self, ids, t0, t1):
        raise NotImplementedError

    def grid(self, ids, t0, t1, step_ms):
        raw = self.raw_many(ids, t0, t1)
        return {p: bucket_means(t, v, t0, t1, step_ms) for p, (t, v) in raw.items()}

    def last(self, ids):
        raise NotImplementedError


# ---------------------------------------------------------------------------------------------
# PostgreSQL: today's Historian (chunks) and TimescaleDB share the binary COPY helpers.

PG_ARGS = [
    "-c",
    "shared_buffers=1GB",
    "-c",
    "effective_cache_size=2GB",
    "-c",
    "work_mem=16MB",
    "-c",
    "maintenance_work_mem=256MB",
    "-c",
    "max_connections=100",
    "-c",
    "max_wal_size=4GB",
    "-c",
    "checkpoint_completion_target=0.9",
    "-c",
    "synchronous_commit=off",
]


def pg_copy_rows(p, t_ms, v) -> bytes:
    n = len(p)
    dt = np.dtype(
        [
            ("nf", ">i2"),
            ("l1", ">i4"),
            ("p", ">i4"),
            ("l2", ">i4"),
            ("t", ">i8"),
            ("l3", ">i4"),
            ("v", ">f8"),
        ]
    )
    a = np.empty(n, dtype=dt)
    a["nf"], a["l1"], a["l2"], a["l3"] = 3, 4, 8, 8
    a["p"] = p
    a["t"] = t_ms.astype(np.int64) * 1000 - EPOCH_2000_US
    a["v"] = v
    return b"PGCOPY\n\xff\r\n\x00" + b"\x00" * 8 + a.tobytes() + b"\xff\xff"


def pg_parse_rows(buf: bytes, ts_kind: str = "ts"):
    """Binary COPY output of (int4 point, timestamptz|int8, float8 v) rows -> arrays. NULL v -> NaN."""
    body = memoryview(buf)[19:-2]
    rec = 2 + 4 + 4 + 4 + 8 + 4 + 8
    if len(body) % rec:
        # NULL values (avg of nothing) shorten a row; rare, parse slowly
        return _pg_parse_slow(bytes(body))
    dt = np.dtype(
        [
            ("nf", ">i2"),
            ("l1", ">i4"),
            ("p", ">i4"),
            ("l2", ">i4"),
            ("t", ">i8"),
            ("l3", ">i4"),
            ("v", ">f8"),
        ]
    )
    a = np.frombuffer(body, dtype=dt)
    t = a["t"].astype(np.int64)
    if ts_kind == "ts":
        t = (t + EPOCH_2000_US) // 1000
    return a["p"].astype(np.int32), t, a["v"].astype(np.float64)


def _pg_parse_slow(body: bytes):
    import struct

    ps, ts, vs, i = [], [], [], 0
    while i < len(body):
        i += 2
        _, p = struct.unpack_from(">ii", body, i)
        i += 8
        _, t = struct.unpack_from(">iq", body, i)
        i += 12
        (ln,) = struct.unpack_from(">i", body, i)
        i += 4
        if ln < 0:
            v = np.nan
        else:
            (v,) = struct.unpack_from(">d", body, i)
            i += 8
        ps.append(p), ts.append((t + EPOCH_2000_US) // 1000), vs.append(v)
    return np.array(ps, np.int32), np.array(ts, np.int64), np.array(vs)


class _Pg(Engine):
    port = 5432
    data_dir = "/var/lib/postgresql/data"
    run_args = ["-e", "POSTGRES_PASSWORD=x", "-e", "POSTGRES_DB=hist", "--shm-size=1g"]

    @property
    def dsn(self):
        return f"postgresql://postgres:x@{HOST}:{self.port}/hist"

    def ready(self):
        import psycopg

        with psycopg.connect(self.dsn, connect_timeout=2) as c:
            c.execute("SELECT 1")
        return True

    def conn(self):
        import psycopg

        if getattr(self, "_conn", None) is None or self._conn.closed:
            self._conn = psycopg.connect(self.dsn, autocommit=True)
        return self._conn

    def copy_out(self, sql: str, params=()) -> bytes:
        buf = io.BytesIO()
        with self.conn().cursor() as cur:
            with cur.copy(sql, params) as cp:
                for data in cp:
                    buf.write(data)
        return buf.getvalue()

    def version(self):
        return self.conn().execute("SELECT version()").fetchone()[0].split(" on ")[0]


class PgChunks(_Pg):
    """Today's Historian: zlib/zstd chunks of up to 10,000 values per point in monthly partitions,
    read by the real ``ArchiveStore.read_many`` (one query per 500 points)."""

    key = "pg-chunks"
    name = "PostgreSQL 17 + chunks (Historian atual)"
    image = "postgres:17"
    port = 55432
    ports = ["55432"]
    license = "PostgreSQL (permissiva)"

    def __init__(self):
        self._store = None

    @property
    def command(self):
        return ["postgres", "-p", str(self.port), *PG_ARGS]

    def store(self):
        if self._store is None:
            import sys

            repo = Path(__file__).resolve().parents[3]
            sys.path[:0] = [str(repo / "apps/historian/src"), str(repo / "sdk/python")]
            from histcraft.archive.store import ArchiveStore
            from histcraft.db import Database

            os.environ["PGPASSWORD"] = "x"
            self._store = ArchiveStore(
                Database(f"postgresql://postgres@{HOST}:{self.port}/hist", password="x")
            )
        return self._store

    def setup(self):
        self.store()

    def load_day(self, p, t, v):
        from histcraft.archive import codec

        st = self.store()
        st._ensure("chunks", [int(t.min()), int(t.max())])
        rows = []
        for pt, s, e in split(p):
            tt, vv = t[s:e], v[s:e]
            for i in range(0, len(tt), CHUNK_VALUES):
                ct, cv = tt[i : i + CHUNK_VALUES], vv[i : i + CHUNK_VALUES]
                rows.append(
                    (pt, int(ct[0]), int(ct[-1]), len(ct), codec.encode(ct, list(cv), "number"))
                )
        with self.conn().cursor() as cur:
            with cur.copy("COPY chunks (point, t0, t1, n, data) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)

    def finish(self):
        self.conn().execute("VACUUM ANALYZE chunks")

    def size(self):
        # the archive tables, not the WAL (the data directory holds up to max_wal_size of it)
        return int(
            self.conn()
            .execute(
                "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = 'public' AND c.relkind = 'r' AND (c.relname LIKE 'chunks%' OR c.relname LIKE 'rollups%')"
            )
            .fetchone()[0]
        )

    def raw_many(self, ids, t0, t1):
        st = self.store()
        out = {}
        for i in range(0, len(ids), 500):
            got = st.read_many(ids[i : i + 500], t0, t1 - 1)
            for pt, (tt, vv) in got.items():
                m = (tt >= t0) & (tt < t1)
                out[pt] = (tt[m], np.asarray(vv, dtype=float)[m])
        return out

    def last(self, ids):
        from histcraft.archive import codec

        self.store()
        rows = (
            self.conn()
            .execute(
                "SELECT i, c.data FROM unnest(%s::int[]) i, LATERAL (SELECT data FROM chunks WHERE point = i"
                " ORDER BY t0 DESC LIMIT 1) c",
                (list(ids),),
            )
            .fetchall()
        )
        out = {}
        for pt, data in rows:
            tt, vv = codec.decode(bytes(data))
            out[pt] = (int(tt[-1]), float(vv[-1]))
        return out


class Timescale(_Pg):
    """TimescaleDB 2 hypertable (1-day chunks), native compression segmentby point / orderby t,
    an hourly continuous aggregate (avg/min/max/count) for long trends."""

    key = "timescale"
    name = "TimescaleDB (PG 17)"
    image = "timescale/timescaledb:latest-pg17"
    port = 55433
    ports = ["55433"]
    license = "Timescale License (TSL) para compressão/cagg; Apache 2 só no núcleo"

    @property
    def command(self):
        return [
            "postgres",
            "-p",
            str(self.port),
            *PG_ARGS,
            "-c",
            "shared_preload_libraries=timescaledb",
            "-c",
            "timescaledb.telemetry_level=off",
            "-c",
            "max_locks_per_transaction=512",
        ]

    def setup(self):
        c = self.conn()
        c.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        c.execute("CREATE TABLE hist (point int NOT NULL, t timestamptz NOT NULL, v float8)")
        c.execute("SELECT create_hypertable('hist', by_range('t', INTERVAL '1 day'))")
        c.execute(
            "ALTER TABLE hist SET (timescaledb.compress, timescaledb.compress_segmentby='point',"
            " timescaledb.compress_orderby='t')"
        )
        c.execute("CREATE INDEX ON hist (point, t)")

    def load_day(self, p, t, v):
        with self.conn().cursor() as cur:
            with cur.copy("COPY hist (point, t, v) FROM STDIN (FORMAT binary)") as cp:
                data = pg_copy_rows(p, t, v)
                for i in range(0, len(data), 64 << 20):
                    cp.write(data[i : i + (64 << 20)])
        # compress finished days as the compression policy would
        self.conn().execute(
            "SELECT compress_chunk(c, if_not_compressed => true) FROM show_chunks('hist') c"
        )

    def finish(self):
        c = self.conn()
        c.execute(
            "CREATE MATERIALIZED VIEW hist_1h WITH (timescaledb.continuous) AS SELECT point,"
            " time_bucket('1 hour', t) AS b, avg(v) AS mean, min(v) AS lo, max(v) AS hi, count(*) AS n"
            " FROM hist GROUP BY point, b WITH NO DATA"
        )
        c.execute("CALL refresh_continuous_aggregate('hist_1h', NULL, NULL)")
        c.execute("VACUUM ANALYZE hist")

    def size(self):
        return int(
            self.conn()
            .execute(
                "SELECT hypertable_size('hist') + COALESCE((SELECT hypertable_size(format('%I.%I',"
                " materialization_hypertable_schema, materialization_hypertable_name)::regclass)"
                " FROM timescaledb_information.continuous_aggregates LIMIT 1), 0)"
            )
            .fetchone()[0]
        )

    def scan(self, ids, t0, t1):
        arr = "'{" + ",".join(map(str, ids)) + "}'::int[]"
        return (
            self.conn()
            .execute(
                f"SELECT count(*), sum(v) FROM hist WHERE point = ANY({arr})"
                f" AND t >= to_timestamp({t0 / 1000}) AND t < to_timestamp({t1 / 1000})"
            )
            .fetchone()[0]
        )

    def raw_many(self, ids, t0, t1):
        buf = self.copy_out(
            "COPY (SELECT point, t, v FROM hist WHERE point = ANY({}) AND t >= to_timestamp({}) AND t < to_timestamp({})"
            " ORDER BY point, t) TO STDOUT (FORMAT binary)".format(
                "'{" + ",".join(map(str, ids)) + "}'::int[]", t0 / 1000, t1 / 1000
            )
        )
        p, t, v = pg_parse_rows(buf)
        return {pt: (t[s:e], v[s:e]) for pt, s, e in split(p)}

    def grid(self, ids, t0, t1, step_ms):
        arr = "'{" + ",".join(map(str, ids)) + "}'::int[]"
        if step_ms >= 3_600_000 and step_ms % 3_600_000 == 0:
            sql = (
                f"COPY (SELECT point, time_bucket('{step_ms // 1000} s', b) AS x, avg(mean) FROM hist_1h"
                f" WHERE point = ANY({arr}) AND b >= to_timestamp({t0 / 1000}) AND b < to_timestamp({t1 / 1000})"
                " GROUP BY point, x ORDER BY point, x) TO STDOUT (FORMAT binary)"
            )
        else:
            sql = (
                f"COPY (SELECT point, time_bucket('{step_ms // 1000} s', t) AS x, avg(v) FROM hist"
                f" WHERE point = ANY({arr}) AND t >= to_timestamp({t0 / 1000}) AND t < to_timestamp({t1 / 1000})"
                " GROUP BY point, x ORDER BY point, x) TO STDOUT (FORMAT binary)"
            )
        p, t, v = pg_parse_rows(self.copy_out(sql))
        return {pt: (t[s:e], v[s:e]) for pt, s, e in split(p)}

    def last(self, ids):
        rows = (
            self.conn()
            .execute(
                "SELECT i, x.t, x.v FROM unnest(%s::int[]) i, LATERAL (SELECT t, v FROM hist WHERE point = i"
                " ORDER BY t DESC LIMIT 1) x",
                (list(ids),),
            )
            .fetchall()
        )
        return {int(i): (int(t.timestamp() * 1000), v) for i, t, v in rows}


# ---------------------------------------------------------------------------------------------


class ClickHouse(Engine):
    """ClickHouse MergeTree ORDER BY (point, t), monthly partitions, DoubleDelta/Gorilla + ZSTD."""

    key = "clickhouse"
    name = "ClickHouse"
    image = "clickhouse/clickhouse-server:latest"
    ports = ["8123"]
    data_dir = "/var/lib/clickhouse"
    run_args = ["-e", "CLICKHOUSE_SKIP_USER_SETUP=1"] + (
        ["--ulimit", "nofile=262144:262144"] if os.environ.get("TSDB_ULIMIT") else []
    )
    license = "Apache 2.0"

    def client(self):
        import clickhouse_connect

        if getattr(self, "_c", None) is None:
            self._c = clickhouse_connect.get_client(
                host=HOST, port=8123, username="default", password="", send_receive_timeout=600
            )
        return self._c

    def ready(self):
        return http(f"http://{HOST}:8123/ping") == b"Ok.\n"

    def setup(self):
        self.client().command(
            "CREATE TABLE hist (point UInt32, t DateTime64(3, 'UTC') CODEC(DoubleDelta, ZSTD(1)),"
            " v Float64 CODEC(Gorilla, ZSTD(1))) ENGINE = MergeTree PARTITION BY toYYYYMM(t) ORDER BY (point, t)"
        )

    def version(self):
        return self.client().command("SELECT version()")

    def load_day(self, p, t, v):
        import pyarrow as pa

        tab = pa.table(
            {
                "point": pa.array(p.astype(np.uint32)),
                "t": pa.array(t, pa.timestamp("ms", "UTC")),
                "v": v,
            }
        )
        for i in range(0, len(p), 5_000_000):
            self.client().insert_arrow("hist", tab.slice(i, 5_000_000))

    def finish(self):
        self.client().command("OPTIMIZE TABLE hist FINAL", settings={"receive_timeout": 3600})

    def _arrow(self, sql):
        return self.client().query_arrow(sql, use_strings=False)

    def scan(self, ids, t0, t1):
        return (
            self.client()
            .query(
                f"SELECT count(), sum(v) FROM hist WHERE point IN ({','.join(map(str, ids))})"
                f" AND t >= fromUnixTimestamp64Milli({t0}) AND t < fromUnixTimestamp64Milli({t1})"
            )
            .result_rows[0][0]
        )

    def raw_many(self, ids, t0, t1):
        tab = self._arrow(
            f"SELECT point, toUnixTimestamp64Milli(t) AS tm, v FROM hist WHERE point IN ({','.join(map(str, ids))})"
            f" AND t >= fromUnixTimestamp64Milli({t0}) AND t < fromUnixTimestamp64Milli({t1}) ORDER BY point, t"
        )
        p = tab.column("point").to_numpy()
        t = tab.column("tm").to_numpy()
        v = tab.column("v").to_numpy()
        return {pt: (t[s:e], v[s:e]) for pt, s, e in split(p)}

    def grid(self, ids, t0, t1, step_ms):
        tab = self._arrow(
            f"SELECT point, intDiv(toUnixTimestamp64Milli(t) - {t0}, {step_ms}) * {step_ms} + {t0} AS b, avg(v) AS m"
            f" FROM hist WHERE point IN ({','.join(map(str, ids))}) AND t >= fromUnixTimestamp64Milli({t0})"
            f" AND t < fromUnixTimestamp64Milli({t1}) GROUP BY point, b ORDER BY point, b"
        )
        p, t, v = (tab.column(c).to_numpy() for c in ("point", "b", "m"))
        return {pt: (t[s:e], v[s:e]) for pt, s, e in split(p)}

    def last(self, ids):
        tab = self._arrow(
            f"SELECT point, toUnixTimestamp64Milli(max(t)) AS tm, argMax(v, t) AS vl FROM hist"
            f" WHERE point IN ({','.join(map(str, ids))}) GROUP BY point"
        )
        return {
            int(a): (int(b), float(c))
            for a, b, c in zip(*(tab.column(x).to_pylist() for x in ("point", "tm", "vl")))
        }

    def size(self):
        return int(
            self.client().command(
                "SELECT sum(bytes_on_disk) FROM system.parts WHERE table = 'hist' AND active"
            )
        )


class QuestDB(Engine):
    """QuestDB: SYMBOL point (indexed), partition by day, WAL table, ILP over HTTP to load."""

    key = "questdb"
    name = "QuestDB"
    image = "questdb/questdb:latest"
    ports = ["9000", "8812"]
    data_dir = "/var/lib/questdb"
    run_args = ["-e", "QDB_TELEMETRY_ENABLED=false", "-e", "QDB_PG_SELECT_CACHE_ENABLED=false"]
    license = "Apache 2.0 (Open Source); Enterprise comercial"

    def ready(self):
        http(f"http://{HOST}:9000/exec?query=" + urllib.parse.quote("SELECT 1"))
        return True

    def exec(self, sql):
        return json.loads(http(f"http://{HOST}:9000/exec?query=" + urllib.parse.quote(sql)))

    def setup(self):
        self.exec(
            "CREATE TABLE hist (point SYMBOL CAPACITY 4096 INDEX, v DOUBLE, t TIMESTAMP) TIMESTAMP(t)"
            " PARTITION BY DAY WAL"
        )

    def version(self):
        return str(self.exec("SELECT build()")["dataset"][0][0])[:60]

    def load_day(self, p, t, v):
        import pandas as pd
        from questdb.ingress import Sender, TimestampNanos  # noqa: F401

        df = pd.DataFrame(
            {
                "point": pd.Categorical(p.astype(str)),
                "v": v,
                "t": pd.to_datetime(t, unit="ms", utc=True).as_unit("ns"),
            }
        )
        conf = f"http::addr={HOST}:9000;auto_flush_rows=off;request_timeout=600000;"
        with Sender.from_conf(conf) as s:
            for i in range(0, len(df), 2_000_000):
                s.dataframe(
                    df.iloc[i : i + 2_000_000], table_name="hist", symbols=["point"], at="t"
                )
                s.flush()

    def finish(self):
        # wait until the WAL is applied
        def applied():
            r = self.exec("SELECT writerTxn, sequencerTxn FROM wal_tables() WHERE name = 'hist'")[
                "dataset"
            ][0]
            return r[0] == r[1]

        wait(applied, 3600)

    def conn(self):
        import psycopg

        if getattr(self, "_conn", None) is None or self._conn.closed:
            self._conn = psycopg.connect(
                f"postgresql://admin:quest@{HOST}:8812/qdb", autocommit=True
            )
        return self._conn

    def _rows(self, sql):
        with self.conn().cursor(binary=True) as cur:
            cur.execute(sql)
            return cur.fetchall()

    def scan(self, ids, t0, t1):
        names = ",".join(f"'{i}'" for i in ids)
        return self.exec(
            f"SELECT count(), sum(v) FROM hist WHERE point IN ({names}) AND t >= {t0 * 1000}"
            f" AND t < {t1 * 1000}"
        )["dataset"][0][0]

    def raw_many(self, ids, t0, t1):
        names = ",".join(f"'{i}'" for i in ids)
        # Parquet export over HTTP (QuestDB 9) when available, else PG wire rows.
        sql = (
            f"SELECT point, t, v FROM hist WHERE point IN ({names}) AND t >= {t0 * 1000} AND t < {t1 * 1000}"
            " ORDER BY point, t"
        )
        tab = self._parquet(sql)
        if tab is not None:
            p = ints(tab.column("point"))
            t = tab.column("t").cast("int64").to_numpy() // 1000
            v = tab.column("v").to_numpy()
            return group(p, t, v)
        rows = self._rows(sql)
        p = np.fromiter((int(r[0]) for r in rows), np.int32, len(rows))
        t = np.fromiter((r[1].timestamp() * 1000 for r in rows), np.float64, len(rows)).astype(
            np.int64
        )
        v = np.fromiter((r[2] for r in rows), np.float64, len(rows))
        return group(p, t, v)

    def _parquet(self, sql):
        if getattr(self, "_no_parquet", False):
            return None
        import pyarrow.parquet as pq

        try:
            body = http(f"http://{HOST}:9000/exp?fmt=parquet&query=" + urllib.parse.quote(sql))
            return pq.read_table(io.BytesIO(body))
        except Exception as exc:  # noqa: BLE001
            print("questdb parquet export failed, PG wire instead:", exc)
            self._no_parquet = True
            return None

    def grid(self, ids, t0, t1, step_ms):
        names = ",".join(f"'{i}'" for i in ids)
        sql = (
            f"SELECT point, t, avg(v) AS m FROM hist WHERE point IN ({names}) AND t >= {t0 * 1000} AND t < {t1 * 1000}"
            f" SAMPLE BY {step_ms // 1000}s ALIGN TO CALENDAR WITH OFFSET '00:00'"
        )
        tab = self._parquet(sql)
        if tab is not None:
            p = ints(tab.column("point"))
            return group(
                p, tab.column("t").cast("int64").to_numpy() // 1000, tab.column("m").to_numpy()
            )
        rows = self._rows(sql)
        p = np.array([int(r[0]) for r in rows], np.int32)
        t = np.array([r[1].timestamp() * 1000 for r in rows]).astype(np.int64)
        v = np.array([r[2] for r in rows], float)
        return group(p, t, v)

    def last(self, ids):
        names = ",".join(f"'{i}'" for i in ids)
        rows = self._rows(
            f"SELECT point, t, v FROM hist WHERE point IN ({names}) LATEST ON t PARTITION BY point"
        )
        return {int(r[0]): (int(r[1].timestamp() * 1000), r[2]) for r in rows}


class Influx3(Engine):
    """InfluxDB 3 Core: table h, tag id, field v; line protocol over HTTP, SQL over Flight (Arrow)."""

    key = "influxdb3"
    name = "InfluxDB 3 Core"
    image = "influxdb:3-core"
    ports = ["8181"]
    data_dir = "/var/lib/influxdb3"
    license = "MIT/Apache 2.0 (Core); compactação e históricos longos só no Enterprise"
    file_limit = int(os.environ.get("INFLUX_QUERY_FILE_LIMIT", "432"))

    @property
    def command(self):
        return [
            "influxdb3",
            "serve",
            "--node-id",
            "n1",
            "--object-store",
            "file",
            "--data-dir",
            self.data_dir,
            "--without-auth",
            "--query-file-limit",
            str(self.file_limit),
            "--http-bind",
            "0.0.0.0:8181",
            "--disable-telemetry-upload",
        ]

    def ready(self):
        http(f"http://{HOST}:8181/health")
        return True

    def setup(self):
        http(
            f"http://{HOST}:8181/api/v3/configure/database",
            json.dumps({"db": "hist"}).encode(),
            {"Content-Type": "application/json"},
        )

    def version(self):
        try:
            return json.loads(http(f"http://{HOST}:8181/ping")).get("version", "")
        except Exception:  # noqa: BLE001
            return ""

    def load_day(self, p, t, v):
        import pyarrow as pa
        import pyarrow.compute as pc

        step = 200_000
        for i in range(0, len(p), step):
            pp, tt, vv = p[i : i + step], t[i : i + step], v[i : i + step]
            lines = pc.binary_join_element_wise(
                "h,id=",
                pa.array(pp).cast(pa.string()),
                " v=",
                pa.array(vv).cast(pa.string()),
                " ",
                pa.array(tt).cast(pa.string()),
                "",
            )
            body = "\n".join(lines.to_pylist()).encode()
            http(
                f"http://{HOST}:8181/api/v3/write_lp?db=hist&precision=millisecond&no_sync=true",
                body,
            )

    def finish(self):
        time.sleep(15)  # one WAL flush + snapshot interval

    def client(self):
        from influxdb_client_3 import InfluxDBClient3

        if getattr(self, "_c", None) is None:
            self._c = InfluxDBClient3(host=f"http://{HOST}:8181", database="hist", token="x")
        return self._c

    def _sql(self, sql):
        return self.client().query(sql, language="sql", mode="all")

    def scan(self, ids, t0, t1):
        names = ",".join(f"'{i}'" for i in ids)
        return (
            self._sql(
                f"SELECT count(*) AS n, sum(v) AS s FROM h WHERE id IN ({names}) AND time >= to_timestamp_millis({t0})"
                f" AND time < to_timestamp_millis({t1})"
            )
            .column("n")[0]
            .as_py()
        )

    def raw_many(self, ids, t0, t1):
        names = ",".join(f"'{i}'" for i in ids)
        tab = self._sql(
            f"SELECT id, time, v FROM h WHERE id IN ({names}) AND time >= to_timestamp_millis({t0})"
            f" AND time < to_timestamp_millis({t1})"
        )
        p = ints(tab.column("id"))
        t = tab.column("time").cast("int64").to_numpy() // 1_000_000
        v = tab.column("v").to_numpy()
        return group(p, t, v)

    def grid(self, ids, t0, t1, step_ms):
        names = ",".join(f"'{i}'" for i in ids)
        tab = self._sql(
            f"SELECT id, date_bin(INTERVAL '{step_ms // 1000} seconds', time, to_timestamp_millis({t0})) AS b, avg(v) AS m"
            f" FROM h WHERE id IN ({names}) AND time >= to_timestamp_millis({t0}) AND time < to_timestamp_millis({t1})"
            " GROUP BY id, b"
        )
        p = ints(tab.column("id"))
        return group(
            p, tab.column("b").cast("int64").to_numpy() // 1_000_000, tab.column("m").to_numpy()
        )

    def last(self, ids):
        names = ",".join(f"'{i}'" for i in ids)
        tab = self._sql(
            f"SELECT id, max(time) AS t, last_value(v ORDER BY time) AS v FROM h WHERE id IN ({names})"
            " AND time >= now() - INTERVAL '400 days' GROUP BY id"
        )
        return {
            int(a): (int(b.timestamp() * 1000) if hasattr(b, "timestamp") else b, c)
            for a, b, c in zip(*(tab.column(x).to_pylist() for x in ("id", "t", "v")))
        }


class TDengine(Engine):
    """TDengine 3 (OSS): supertable h(ts, v) TAGS(id), one subtable per signal; schemaless line
    protocol to load, websocket client (taosws) to read."""

    key = "tdengine"
    name = "TDengine 3 OSS"
    image = "tdengine/tdengine:latest"
    ports = ["6030", "6041"]
    data_dir = "/var/lib/taos"
    license = "AGPL 3.0 (OSS); licença comercial para embutir sem abrir"

    def ready(self):
        r = json.loads(
            http(
                f"http://{HOST}:6041/rest/sql",
                b"SELECT SERVER_VERSION()",
                {"Authorization": "Basic cm9vdDp0YW9zZGF0YQ=="},
            )
        )
        if r.get("code") != 0:
            return False
        return self.rest("SHOW DNODES")["data"][0][4] == "ready"

    def rest(self, sql):
        r = json.loads(
            http(
                f"http://{HOST}:6041/rest/sql",
                sql.encode(),
                {"Authorization": "Basic cm9vdDp0YW9zZGF0YQ=="},
            )
        )
        if r.get("code") != 0:
            raise RuntimeError(r)
        return r

    def setup(self):
        self.rest(
            "CREATE DATABASE IF NOT EXISTS hist PRECISION 'ms' KEEP 3650 DURATION 10 BUFFER 256 CACHEMODEL 'last_row'"
        )
        self.rest("CREATE STABLE IF NOT EXISTS hist.h (ts TIMESTAMP, v DOUBLE) TAGS (id INT)")

    def version(self):
        return self.rest("SELECT SERVER_VERSION()")["data"][0][0]

    def conn(self):
        import taosws

        if getattr(self, "_c", None) is None:
            self._c = taosws.connect(f"taosws://root:taosdata@{HOST}:6041/hist")
        return self._c

    def load_day(self, p, t, v):
        # one INSERT per batch of subtables, values as text: TDengine's SQL bulk insert path
        c = self.conn()
        for pt, s, e in split(p):
            tt, vv = t[s:e], v[s:e]
            for i in range(0, len(tt), 20000):
                vals = " ".join(
                    f"({a},{b!r})"
                    for a, b in zip(tt[i : i + 20000].tolist(), vv[i : i + 20000].tolist())
                )
                c.execute(f"INSERT INTO hist.t{pt} USING hist.h TAGS ({pt}) VALUES {vals}")

    def finish(self):
        self.rest("FLUSH DATABASE hist")
        try:
            self.rest("COMPACT DATABASE hist")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(10)

    def _query(self, sql):
        c = self.conn()
        cur = c.cursor()
        cur.execute(sql)
        return cur.fetchall()

    def scan(self, ids, t0, t1):
        return self._query(
            f"SELECT count(*), sum(v) FROM hist.h WHERE id IN ({','.join(map(str, ids))})"
            f" AND ts >= {t0} AND ts < {t1}"
        )[0][0]

    def raw_many(self, ids, t0, t1):
        rows = self._query(
            f"SELECT id, ts, v FROM hist.h WHERE id IN ({','.join(map(str, ids))}) AND ts >= {t0}"
            f" AND ts < {t1}"
        )
        n = len(rows)
        p = np.fromiter((r[0] for r in rows), np.int32, n)
        t = np.fromiter((_ms(r[1]) for r in rows), np.int64, n)
        v = np.fromiter((r[2] for r in rows), np.float64, n)
        return group(p, t, v)

    def grid(self, ids, t0, t1, step_ms):
        rows = self._query(
            f"SELECT id, _wstart, avg(v) FROM hist.h WHERE id IN ({','.join(map(str, ids))})"
            f" AND ts >= {t0} AND ts < {t1} PARTITION BY id INTERVAL({step_ms}a)"
        )
        p = np.array([r[0] for r in rows], np.int32)
        t = np.array([_ms(r[1]) for r in rows], np.int64)
        v = np.array([r[2] for r in rows], float)
        return group(p, t, v)

    def last(self, ids):
        rows = self._query(
            f"SELECT id, LAST_ROW(ts), LAST_ROW(v) FROM hist.h WHERE id IN ({','.join(map(str, ids))})"
            " PARTITION BY id"
        )
        return {int(a): (_ms(b), c) for a, b, c in rows}


def _ms(x):
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, str):
        import pandas as pd

        return int(pd.Timestamp(x).value // 1_000_000)
    return int(x.timestamp() * 1000)


class Victoria(Engine):
    """VictoriaMetrics single node: series h{id="..."}, JSON-lines import/export."""

    key = "victoria"
    name = "VictoriaMetrics"
    image = "victoriametrics/victoria-metrics:latest"
    ports = ["8428"]
    data_dir = "/storage"
    command = [
        "-storageDataPath=/storage",
        "-retentionPeriod=100y",
        "-search.maxPointsPerTimeseries=1000000",
        "-search.maxExportSeries=100000",
        "-search.maxSamplesPerQuery=10000000000",
        "-search.latencyOffset=0s",
        "-search.disableCache",
    ]
    license = "Apache 2.0 (single node); Enterprise comercial"

    def ready(self):
        return http(f"http://{HOST}:8428/health") == b"OK"

    def version(self):
        return http(f"http://{HOST}:8428/api/v1/status/buildinfo").decode()[:200]

    def load_day(self, p, t, v):
        import orjson

        lines = []
        for pt, s, e in split(p):
            lines.append(
                orjson.dumps(
                    {
                        "metric": {"__name__": "h", "id": str(pt)},
                        "values": v[s:e],
                        "timestamps": t[s:e],
                    },
                    option=orjson.OPT_SERIALIZE_NUMPY,
                )
            )
            if len(lines) >= 200:
                http(f"http://{HOST}:8428/api/v1/import", b"\n".join(lines))
                lines = []
        if lines:
            http(f"http://{HOST}:8428/api/v1/import", b"\n".join(lines))

    def finish(self):
        http(f"http://{HOST}:8428/internal/force_flush")
        http(f"http://{HOST}:8428/internal/force_merge")
        time.sleep(30)

    @staticmethod
    def _match(ids):
        return 'h{id=~"' + "|".join(map(str, ids)) + '"}'

    def scan(self, ids, t0, t1):
        import orjson

        span = (t1 - t0) // 1000
        q = urllib.parse.urlencode(
            {
                "query": f"sum(count_over_time({self._match(ids)}[{span}s]))",
                "time": (t1 - 1) / 1000,
                "nocache": "1",
            }
        )
        return orjson.loads(http(f"http://{HOST}:8428/api/v1/query?{q}"))["data"]["result"][0][
            "value"
        ][1]

    def raw_many(self, ids, t0, t1):
        import orjson

        q = urllib.parse.urlencode(
            {"match[]": self._match(ids), "start": t0 / 1000, "end": (t1 - 1) / 1000}
        )
        body = http(f"http://{HOST}:8428/api/v1/export?{q}")
        out = {}
        for line in body.splitlines():
            d = orjson.loads(line)
            out[int(d["metric"]["id"])] = (
                np.asarray(d["timestamps"], np.int64),
                np.asarray(d["values"], float),
            )
        return out

    def grid(self, ids, t0, t1, step_ms):
        import orjson

        s = step_ms // 1000
        # avg_over_time over the step that ENDS at each grid time; shift by one step so b = bucket start
        q = urllib.parse.urlencode(
            {
                "query": f"avg_over_time({self._match(ids)}[{s}s])",
                "start": (t0 + step_ms) / 1000,
                "end": t1 / 1000,
                "step": f"{s}s",
                "nocache": "1",
            }
        )
        d = orjson.loads(http(f"http://{HOST}:8428/api/v1/query_range?{q}"))
        out = {}
        for r in d["data"]["result"]:
            a = np.asarray(r["values"], dtype=object)
            out[int(r["metric"]["id"])] = (
                (a[:, 0].astype(float) * 1000).astype(np.int64) - step_ms,
                a[:, 1].astype(float),
            )
        return out

    def last(self, ids):
        import orjson

        q = urllib.parse.urlencode(
            {"query": f"tlast_over_time({self._match(ids)}[400d])", "nocache": "1"}
        )
        d = orjson.loads(http(f"http://{HOST}:8428/api/v1/query?{q}"))
        return {
            int(r["metric"]["id"]): (int(float(r["value"][1]) * 1000), None)
            for r in d["data"]["result"]
        }


class DuckParquet(Engine):
    """DuckDB 1.x over Parquet files: one file per day sorted by (point, t), 100k-row groups with
    min/max statistics (the reader skips row groups of other points). No server."""

    key = "duckdb"
    name = "DuckDB + Parquet"
    image = ""
    license = "MIT"

    def start(self):
        self.stop()
        self.vol.mkdir(parents=True, exist_ok=True)

    def stop(self):
        if self.vol.exists():
            subprocess.run(["rm", "-rf", str(self.vol)], check=False)

    def ram(self):
        return 0

    def image_bytes(self):
        return 0

    def version(self):
        import duckdb

        return duckdb.__version__

    def load_day(self, p, t, v):
        import pyarrow as pa
        import pyarrow.parquet as pq

        n = len(list(self.vol.glob("*.parquet")))
        pq.write_table(
            pa.table({"point": p, "t": t, "v": v}),
            self.vol / f"d{n:04d}.parquet",
            compression="zstd",
            row_group_size=100_000,
            use_dictionary=False,
            column_encoding={"t": "DELTA_BINARY_PACKED", "point": "DELTA_BINARY_PACKED"},
        )

    def con(self):
        import duckdb

        if getattr(self, "_c", None) is None:
            self._c = duckdb.connect()
            self._c.execute(f"SET threads TO {CPUS}")
            self._c.execute(
                f"CREATE VIEW hist AS SELECT * FROM read_parquet('{self.vol}/*.parquet')"
            )
        return self._c

    def scan(self, ids, t0, t1):
        return (
            self.con()
            .execute(
                f"SELECT count(*), sum(v) FROM hist WHERE point IN ({','.join(map(str, ids))})"
                f" AND t >= {t0} AND t < {t1}"
            )
            .fetchall()[0][0]
        )

    def raw_many(self, ids, t0, t1):
        tab = (
            self.con()
            .sql(
                f"SELECT point, t, v FROM hist WHERE point IN ({','.join(map(str, ids))}) AND t >= {t0} AND t < {t1}"
                " ORDER BY point, t"
            )
            .arrow()
        )
        if hasattr(tab, "read_all"):
            tab = tab.read_all()
        p, t, v = (tab.column(c).to_numpy() for c in ("point", "t", "v"))
        return {pt: (t[s:e], v[s:e]) for pt, s, e in split(p)}

    def grid(self, ids, t0, t1, step_ms):
        tab = (
            self.con()
            .sql(
                f"SELECT point, (t - {t0}) // {step_ms} * {step_ms} + {t0} AS b, avg(v) AS m FROM hist"
                f" WHERE point IN ({','.join(map(str, ids))}) AND t >= {t0} AND t < {t1} GROUP BY ALL ORDER BY point, b"
            )
            .arrow()
        )
        if hasattr(tab, "read_all"):
            tab = tab.read_all()
        p, t, v = (tab.column(c).to_numpy() for c in ("point", "b", "m"))
        return {pt: (t[s:e], v[s:e]) for pt, s, e in split(p)}

    def last(self, ids):
        rows = (
            self.con()
            .execute(
                f"SELECT point, max(t), arg_max(v, t) FROM hist WHERE point IN ({','.join(map(str, ids))}) GROUP BY point"
            )
            .fetchall()
        )
        return {int(a): (int(b), c) for a, b, c in rows}


ENGINES = {
    e.key: e
    for e in (PgChunks, Timescale, ClickHouse, QuestDB, Influx3, TDengine, Victoria, DuckParquet)
}
