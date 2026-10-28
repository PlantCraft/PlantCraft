"""The bench loops' past in Analytics (LinkCraft); run inside its container by ci/bench/age.py.

    docker compose exec -T -e DAYS=91 linkcraft python - < link_age.py      # age to 91 days
    docker compose exec -T -e MEASURE=1 linkcraft python - < link_age.py    # time the reads

Analytics keeps a row per loop for every monitoring round (``subject_health``, every
``LINKCRAFT_ROUND_MINUTES``, 10 by default) and a row per signal for every signal check
(``quality_history`` and ``quality_rounds``, every 15 minutes), for 90 days (``HISTORY_DAYS``).
This copies the newest round of the bench loops (``LC-*``) and the newest check of the bench
signals back in time, one copy per round, from ``DAYS`` ago (at most 91: the hourly pruning would
delete the rest) up to the oldest row there, so the tables hold what months of rounds leave.
Times keep their stored format. Running it again adds only the older rounds. Prints one JSON line.

``MEASURE=1`` writes nothing: it times the hourly maintenance (``Runtime.tick``: pruning of each
table, detail thinning) and the reads behind the pages that read this history (a loop's health
over 30 days, the portfolio's health per day over 30 days and per hour over 7 days, the signal
checks per day over 7 days and one signal's over 30 days), and gives the row counts and the
database's size.
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from linkcraft.api.runtime import DETAIL_KEPT, HISTORY_DAYS
from linkcraft.config import Settings
from linkcraft.db import Database
from linkcraft.engine.jobs import JobStore
from linkcraft.engine.latest import LatestStore
from linkcraft.signals.store import QualityResultStore

DAYS = min(float(os.environ.get("DAYS", 91)), HISTORY_DAYS + 1)
ROUND_MINUTES = float(os.environ.get("LINKCRAFT_ROUND_MINUTES") or 10)
CHECK_MINUTES = float(
    os.environ.get("CHECK_MINUTES") or os.environ.get("LINKCRAFT_SIGNAL_ROUND_MINUTES") or 15
)
BATCH = 50_000
LOOP_PREFIX = "LC-"
SIGNAL_PREFIX = "bench:"

settings = Settings.from_environment()
path = settings.database_path


def parse(text: str) -> datetime:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def shifter(sample: str):
    """A function giving a stored time ``delta`` earlier, written as ``sample`` is written."""

    zulu = sample.endswith("Z")
    offset = not zulu and ("+" in sample[19:] or "-" in sample[19:])
    separator = "T" if "T" in sample else " "
    fraction = sample[20:].rstrip("Z").split("+")[0].split("-")[0] if sample[19:20] == "." else ""
    spec = {0: "seconds", 3: "milliseconds"}.get(len(fraction), "microseconds")

    def shift(text: str, delta: timedelta) -> str:
        moment = parse(text) - delta
        if not (zulu or offset):
            moment = moment.replace(tzinfo=None)
        out = moment.isoformat(sep=separator, timespec=spec)
        return out.replace("+00:00", "Z") if zulu else out

    return shift


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=120)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 120000")
    return connection


def checkpoint(connection: sqlite3.Connection) -> None:
    """Fold the write-ahead log back into the database after each batch: written this fast, with
    the app reading all along, it would otherwise grow by gigabytes."""

    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def age_health(start: datetime) -> dict:
    with connect() as connection:
        rows = connection.execute(
            "SELECT h.* FROM subject_health h JOIN (SELECT application_id, subject_kind, subject_id,"
            " MAX(source_end) AS newest, MIN(source_end) AS oldest FROM subject_health"
            " WHERE subject_id LIKE ? GROUP BY 1, 2, 3) n USING (application_id, subject_kind,"
            " subject_id) WHERE h.source_end = n.newest",
            (LOOP_PREFIX + "%",),
        ).fetchall()
        oldest = connection.execute(
            "SELECT MIN(source_end) FROM subject_health WHERE subject_id LIKE ?",
            (LOOP_PREFIX + "%",),
        ).fetchone()[0]
    if not rows:
        return {"subject_health": 0, "note": "no round of the bench loops yet"}
    period = timedelta(minutes=ROUND_MINUTES)
    shift = shifter(rows[0]["source_end"])
    newest = max(parse(row["source_end"]) for row in rows)
    first = int((newest - parse(oldest)) / period) + 1  # the rounds already there
    last = int((newest - start) / period)
    written = 0
    pending = []
    with connect() as connection:
        for n in range(first, last + 1):
            delta = period * n
            pending += [
                (
                    r["application_id"],
                    r["subject_kind"],
                    r["subject_id"],
                    shift(r["source_end"], delta),
                    r["status"],
                    r["health"],
                )
                for r in rows
            ]
            if len(pending) >= BATCH or n == last:
                connection.executemany(
                    "INSERT OR IGNORE INTO subject_health (application_id, subject_kind,"
                    " subject_id, source_end, status, health) VALUES (?, ?, ?, ?, ?, ?)",
                    pending,
                )
                connection.commit()
                checkpoint(connection)
                written += len(pending)
                pending = []
    return {"subject_health": written, "loops": len(rows), "rounds": max(0, last - first + 1)}


def age_quality(start: datetime) -> dict:
    with connect() as connection:
        rows = connection.execute(
            "SELECT h.* FROM quality_history h JOIN (SELECT signal_id, MAX(checked_at) AS newest"
            " FROM quality_history WHERE signal_id LIKE ? GROUP BY signal_id) n"
            " ON h.signal_id = n.signal_id AND h.checked_at = n.newest",
            (SIGNAL_PREFIX + "%",),
        ).fetchall()
        oldest = connection.execute(
            "SELECT MIN(checked_at) FROM quality_history WHERE signal_id LIKE ?",
            (SIGNAL_PREFIX + "%",),
        ).fetchone()[0]
        last_round = connection.execute(
            "SELECT * FROM quality_rounds WHERE status != 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not rows:
        return {"quality_history": 0, "note": "no signal check of the bench signals yet"}
    period = timedelta(minutes=CHECK_MINUTES)
    shift = shifter(rows[0]["checked_at"])
    newest = max(parse(row["checked_at"]) for row in rows)
    first = int((newest - parse(oldest)) / period) + 1
    last = int((newest - start) / period)
    written = rounds = 0
    pending, pending_rounds = [], []
    with connect() as connection:
        for n in range(first, last + 1):
            delta = period * n
            pending += [
                (r["signal_id"], shift(r["checked_at"], delta), r["status"], r["quality"])
                for r in rows
            ]
            if last_round is not None:
                round_shift = shifter(last_round["started_at"])
                pending_rounds.append(
                    (
                        round_shift(last_round["started_at"], delta),
                        last_round["finished_at"] and round_shift(last_round["finished_at"], delta),
                        last_round["status"],
                        last_round["trigger"],
                        last_round["started_by"],
                        last_round["window_start"]
                        and round_shift(last_round["window_start"], delta),
                        last_round["window_end"] and round_shift(last_round["window_end"], delta),
                        last_round["signals"],
                        last_round["counts"],
                        last_round["duration_seconds"],
                        last_round["error"],
                    )
                )
            if len(pending) >= BATCH or n == last:
                connection.executemany(
                    "INSERT INTO quality_history (signal_id, checked_at, status, quality)"
                    " VALUES (?, ?, ?, ?)",
                    pending,
                )
                connection.executemany(
                    "INSERT INTO quality_rounds (started_at, finished_at, status, trigger,"
                    " started_by, window_start, window_end, signals, counts, duration_seconds,"
                    " error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    pending_rounds,
                )
                connection.commit()
                checkpoint(connection)
                written += len(pending)
                rounds += len(pending_rounds)
                pending, pending_rounds = [], []
    return {"quality_history": written, "signals": len(rows), "check_rounds": rounds}


def sizes() -> dict:
    with connect() as connection:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
            for table in (
                "subject_health",
                "quality_history",
                "quality_rounds",
                "analysis_jobs",
                "analysis_job_results",
                "run_samples",
            )
        }
    files = {
        name: os.path.getsize(f"{path}{name}")
        for name in ("", "-wal", "-shm", "-journal")
        if os.path.exists(f"{path}{name}")
    }
    return {"rows": counts, "database_bytes": files}


def timed(function, *args, **kwargs) -> tuple[float, object]:
    began = time.perf_counter()
    result = function(*args, **kwargs)
    return round(time.perf_counter() - began, 3), result


def measure() -> dict:
    db = Database(path)
    latest, quality, jobs = LatestStore(db), QualityResultStore(db), JobStore(db)
    out = {}
    maintenance = {}
    maintenance["health_prune_s"], _ = timed(latest.prune_history, days=HISTORY_DAYS)
    maintenance["quality_prune_s"], _ = timed(quality.prune, HISTORY_DAYS)
    maintenance["jobs_prune_s"], _ = timed(jobs.prune_jobs, days=HISTORY_DAYS)
    maintenance["detail_prune_s"], _ = timed(jobs.prune_detail, keep=DETAIL_KEPT)
    maintenance["total_s"] = round(sum(maintenance.values()), 3)
    out["maintenance"] = maintenance
    now = datetime.now(timezone.utc)
    with connect() as connection:
        sample = connection.execute(
            "SELECT application_id, subject_kind, source_end FROM subject_health"
            " WHERE subject_id LIKE ? ORDER BY source_end DESC LIMIT 1",
            (LOOP_PREFIX + "%",),
        ).fetchone()
    reads = {}
    if sample:
        shift = shifter(sample["source_end"])
        app, kind = sample["application_id"], sample["subject_kind"]
        end = shift(now.isoformat(), timedelta(0))
        reads["loop_health_30d_s"], rows = timed(
            latest.history, app, kind, f"{LOOP_PREFIX}00000", days=30
        )
        reads["loop_health_30d_points"] = len(rows)
        month = shift(now.isoformat(), timedelta(days=30))
        week = shift(now.isoformat(), timedelta(days=7))
        reads["portfolio_daily_30d_s"], rows = timed(
            latest.health_buckets, app, kind, month, end, 86400
        )
        reads["portfolio_daily_30d_rows"] = len(rows)
        reads["portfolio_hourly_7d_s"], rows = timed(
            latest.health_buckets, app, kind, week, end, 3600
        )
        reads["portfolio_hourly_7d_rows"] = len(rows)
    reads["checks_daily_7d_s"], _ = timed(quality.daily, 7)
    reads["signal_checks_30d_s"], rows = timed(quality.history, f"{SIGNAL_PREFIX}LC-00000.PV", 30)
    reads["signal_checks_30d_points"] = len(rows)
    out["reads"] = reads
    out.update(sizes())
    return out


def age() -> dict:
    start = datetime.now(timezone.utc) - timedelta(days=DAYS)
    began = time.perf_counter()
    result = {"days": DAYS, "round_minutes": ROUND_MINUTES, "check_minutes": CHECK_MINUTES}
    result.update(age_health(start))
    result.update(age_quality(start))
    result["seconds"] = round(time.perf_counter() - began, 1)
    result.update(sizes())
    return result


print(json.dumps(measure() if os.environ.get("MEASURE") else age()))
