"""The control-loop monitor: the periodic round over every loop, and single jobs.

A round reads the loops' signals from PlantCraft in batches (a few
``POST /api/v1/series`` requests per batch of loops, in parallel) and hands each
loop's computation to the process pool, so reading the next batch and computing
the previous one overlap.
Results go to ``LatestStore``; nothing per loop is kept in memory, which is
what lets a portfolio grow to thousands of loops.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, CancelledError, Future, wait
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from plantcraft_sdk.utc import utc_iso

from linkcraft.blocks import compile_algorithm
from linkcraft.blocks.algorithms import DEFAULT
from linkcraft.blocks.convert import diagram_of
from linkcraft.blocks.stored import convert_stored, system_rows
from linkcraft.catalog.presets import PresetStore
from linkcraft.config import AnalysisConfig, LoopConfig
from linkcraft.data.frames import build_loop_frame, loop_signal_ids
from linkcraft.data.plant import PlantData, utc_timestamp
from linkcraft.data.suite import SuiteClient
from linkcraft.db import Database
from linkcraft.engine.compute import ComputePool, task_timeout
from linkcraft.engine.dispatcher import RetryLater, unreachable
from linkcraft.engine.jobs import JobStore
from linkcraft.engine.latest import LatestStore
from linkcraft.engine.samples import ROUND_SCOPE, loop_run_key
from linkcraft.i18n import t
from linkcraft.loops.analysis import analyze_loop, analyze_loop_task, loop_priority, loop_summary
from linkcraft.loops.store import LoopStore
from linkcraft.loops.suite import SuitePublisher

logger = logging.getLogger(__name__)

APPLICATION_ID = "cpm"
SUBJECT_KIND = "loop"
# Loops whose signals are read together during a round.
READ_BATCH = 50
# Loops whose task is out at once: a round reads the next batch only when fewer are open, so a
# plant of thousands of loops never holds every loop's data (and its encoded task) at once.
OPEN_LOOPS = 4 * READ_BATCH
# How long a schedule's period is, for the expiry of what its runs publish.
CADENCE_MINUTES = {"hourly": 60.0, "daily": 1440.0, "weekly": 10080.0}

STATUS_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "incomplete": 3,
    "inactive": 4,
    "no_data": 5,
    "no_score": 6,
    "normal": 7,
}


def _error(future: Future) -> BaseException | None:
    try:
        return future.exception()
    except CancelledError as exc:
        return exc


class MonitorService:
    """Run the loops' algorithms and keep the latest result of each loop."""

    def __init__(
        self,
        db: Database,
        plant: PlantData,
        *,
        analysis: AnalysisConfig | None = None,
        compute: ComputePool | None = None,
        suite: SuiteClient | None = None,
        root_path: str = "/link",
        quality: Callable[[list[LoopConfig]], dict[str, dict[str, Any]]] | None = None,
    ):
        self.db = db
        # The suite contract (results, events, runs): off without it.
        self.suite = suite
        # The Signal quality algorithm's word on a list of loops (``quality_verdicts``).
        self.quality = quality
        self.publisher = SuitePublisher(db, suite, root_path=root_path) if suite else None
        self.interval_minutes = 10.0
        self.plant = plant
        self.analysis = analysis or AnalysisConfig()
        self.compute = compute or ComputePool(0)
        self.presets = PresetStore(db)
        self.presets.seed_system_algorithms(system_rows())
        converted = convert_stored(self.presets)
        if converted:
            logger.info("Converted %d protocols of version 0.2 into algorithms", converted)
        self.loop_store = LoopStore(db, self.presets)
        self.jobs = JobStore(db)
        self.latest = LatestStore(db)
        self._lock = threading.RLock()
        self._run_lock = threading.Lock()
        self._snapshot: dict[str, Any] = {"status": "idle", "summary": {}, "failed_tags": []}
        self.progress: dict[str, Any] = {"done": 0, "total": 0}
        self._overview_cache: tuple[Any, list[dict[str, Any]]] | None = None
        self.last_error: str | None = None
        self.running = False

    @property
    def loops(self) -> list[LoopConfig]:
        return self.loop_store.list_loops(enabled_only=True)

    @property
    def snapshot(self) -> dict[str, Any]:
        """The last round's header: state, period, duration and portfolio counts."""

        with self._lock:
            return deepcopy(self._snapshot)

    def has_results(self) -> bool:
        return self.latest.count(APPLICATION_ID, SUBJECT_KIND) > 0

    def restore(self, header: dict[str, Any]) -> None:
        """Show the last saved round after a restart, without analysing again."""

        with self._lock:
            self._snapshot = deepcopy(header)

    # The round ----------------------------------------------------------

    def _task(
        self,
        loop: LoopConfig,
        raw: pd.DataFrame,
        *,
        method_ids: list[str] | None = None,
        parameter_overrides: dict[str, dict[str, Any]] | None = None,
        parameter_defaults: dict[str, dict[str, Any]] | None = None,
        diagram: dict[str, Any] | None = None,
        algorithm_id: str | None = None,
        external_quality: dict[str, Any] | None = None,
        compute: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        columns = [column for column in loop_signal_ids(loop) if column in raw.columns]
        return {
            # Where it runs on the suite's compute workers (the algorithm's environment, size).
            "compute": compute,
            "analysis": self.analysis.model_dump(mode="json"),
            "loop": loop.model_dump(mode="json"),
            "raw": raw[columns],
            "method_ids": method_ids,
            "parameter_overrides": parameter_overrides,
            "parameter_defaults": parameter_defaults,
            "diagram": diagram,
            "algorithm_id": algorithm_id,
            "external_quality": external_quality,
        }

    @staticmethod
    def _text_signals(loops: list[LoopConfig]) -> set[str]:
        return {loop.signals.mode for loop in loops if loop.signals.mode}

    def _read(
        self, plant: PlantData, loops: list[LoopConfig], start: Any, end: Any
    ) -> pd.DataFrame:
        tags = sorted({tag for loop in loops for tag in loop_signal_ids(loop)})
        return plant.read_range(
            start,
            end,
            self.analysis.resample_seconds,
            tags=tags,
            text_signals=self._text_signals(loops),
        )

    def round_end(self, loops: list[LoopConfig], plant: PlantData | None = None) -> pd.Timestamp:
        """Now for a live source; the last sample for a recorded one (asked to PlantCraft)."""

        plant = plant or self.plant
        return plant.data_end([loop.signals.pv for loop in loops], self.analysis.window_minutes)

    def _verdicts(self, loops: list[LoopConfig]) -> dict[str, dict[str, Any]]:
        """Signal quality's word on these loops' data; nothing (built-in gate) without it."""

        if self.quality is None:
            return {}
        try:
            return self.quality(loops)
        except Exception:  # an odd verdict must not stop the round
            logger.warning("Signal quality verdicts not read", exc_info=True)
            return {}

    def run_once(self, run_id: str | None = None) -> dict[str, Any]:
        """One monitoring round over every enabled loop.

        Returns the round header plus ``loops`` (summary and results per loop);
        only the header stays in memory. Results and finding events then go to
        PlantCraft (``run_id`` names the run they came from).
        """

        if not self._run_lock.acquire(blocking=False):
            return self.snapshot
        self.running = True
        started = datetime.now(UTC)
        try:
            analysis = self.analysis
            loops = self.loops
            self.progress = {
                "done": 0,
                "total": len(loops),
                "started_at": started.isoformat(timespec="seconds"),
            }
            end = self.round_end(loops) if loops else utc_timestamp(started)
            start = end - pd.Timedelta(minutes=analysis.window_minutes)
            futures: dict[Future, LoopConfig] = {}  # the ones still out
            payloads: dict[str, Any] = {}

            def settle(finished: Iterable[tuple[Future, BaseException | None]]) -> None:
                for future, error in finished:
                    loop = futures.pop(future)
                    if error is None:
                        payloads[loop.loop_id] = future.result()
                    else:
                        logger.error("Analysis of loop %s failed", loop.loop_id, exc_info=error)
                        payloads[loop.loop_id] = self._failed_payload(loop, error)
                    self.progress["done"] += 1

            versions: dict[str, int | None] = {}
            algorithms: dict[Any, Any] = {}  # algorithms and method defaults, read once per round
            failed_tags: list[tuple[str, str]] = []
            first: pd.Timestamp | None = None
            last: pd.Timestamp | None = None
            pv_found = False
            read_errors: list[str] = []
            unread = 0
            for offset in range(0, len(loops), READ_BATCH):
                batch = loops[offset : offset + READ_BATCH]
                try:
                    raw = self._read(self.plant, batch, start, end)
                except Exception as exc:  # one bad batch must not stop the round
                    # Unknown is not "no data": these loops keep their last result.
                    logger.warning(
                        "Reading %d loops failed; keeping the last result: %s", len(batch), exc
                    )
                    read_errors.append(f"{type(exc).__name__}: {exc}")
                    unread += len(batch)
                    self.progress["total"] -= len(batch)
                    continue
                failed_tags.extend(raw.attrs.get("failed_tags") or [])
                if not raw.empty:
                    first = raw.index.min() if first is None else min(first, raw.index.min())
                    last = raw.index.max() if last is None else max(last, raw.index.max())
                verdicts = self._verdicts(batch)
                for loop in batch:
                    pv_found = pv_found or loop.signals.pv in raw.columns
                    config = self._round_config(loop, algorithms)
                    versions[loop.loop_id] = config.get("version")
                    task = self._task(
                        loop,
                        raw,
                        **_layers(config),
                        diagram=config.get("diagram"),
                        algorithm_id=config.get("profile_id"),
                        external_quality=verdicts.get(loop.loop_id),
                        compute=config.get("compute"),
                    )
                    futures[self.compute.submit(analyze_loop_task, task)] = loop
                while len(futures) >= OPEN_LOOPS:
                    done, _ = wait(futures, timeout=task_timeout(), return_when=FIRST_COMPLETED)
                    if not done:  # the rest time out below, as ever
                        break
                    settle((future, _error(future)) for future in done)
            # No enabled loop is an empty portfolio, not a source failure.
            if loops and not pv_found:
                if read_errors and unread >= len(loops):
                    raise RuntimeError(read_errors[0])
                raise RuntimeError(
                    t(
                        "PlantCraft returned no data for any loop's PV between {start} and {end}.",
                        start=str(start),
                        end=str(end),
                    )
                )

            settle(self.compute.as_completed(list(futures)))

            completed = datetime.now(UTC)
            source_start, source_end = (
                (str(first), str(last)) if first is not None else (None, None)
            )
            for loop_id, payload in payloads.items():
                payload["summary"].setdefault("active_alarms", 0)
                if versions.get(loop_id):
                    # The version that ran, as on a job (the Last run tab draws that diagram).
                    payload["summary"]["algorithm_version"] = versions[loop_id]
            snapshot: dict[str, Any] = {
                "status": "ok",
                "started_at": started.isoformat(timespec="seconds"),
                "completed_at": completed.isoformat(timespec="seconds"),
                "duration_seconds": round((completed - started).total_seconds(), 3),
                "source_start": source_start,
                "source_end": source_end,
                "failed_tags": failed_tags[:200],
                "failed_tag_count": len(failed_tags),
                "unread_loops": unread,
                "summary": self._portfolio_summary(payloads),
                "loops": payloads,
            }
            self._save_latest(payloads, source_start, source_end)
            snapshot["published"] = self._publish(payloads, completed, run_id)
            header = {key: value for key, value in snapshot.items() if key != "loops"}
            with self._lock:
                self._snapshot = header
            self.last_error = None
            return snapshot
        except Exception as exc:
            logger.exception("CPM round failed")
            self.last_error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._snapshot = {
                    **self._snapshot,
                    "status": "error",
                    "completed_at": utc_iso(),
                    "error": self.last_error,
                }
            return self.snapshot
        finally:
            self.running = False
            self._run_lock.release()

    def _publish(
        self, payloads: dict[str, Any], completed: datetime, run_id: str | None
    ) -> dict[str, int]:
        if self.publisher is None:
            return {}
        try:
            return self.publisher.publish_round(
                payloads,
                self.loop_store.origins(),
                completed_at=completed,
                interval_minutes=self.interval_minutes,
                run_id=run_id,
            )
        except Exception:  # publishing never fails the round
            logger.exception("Publishing the round to PlantCraft failed")
            return {}

    def _publish_job_outputs(
        self, job: dict[str, Any], loop: LoopConfig, payload: dict[str, Any]
    ) -> None:
        """An algorithm run's outputs (diagram result, series and message blocks) to the suite.

        Results expire after two of the schedule's periods (a day for one-off runs).
        """

        if self.publisher is None or not (payload.get("summary") or {}).get("outputs"):
            return
        schedule = self.jobs.get_schedule(job["schedule_id"]) if job.get("schedule_id") else None
        schedule = schedule or {}
        interval = schedule.get("interval_minutes") or CADENCE_MINUTES.get(
            str(schedule.get("cadence")), 1440.0
        )
        try:
            self.publisher.publish_outputs(
                {loop.loop_id: {**payload, "config": loop.model_dump(mode="json")}},
                self.loop_store.origins(),
                completed_at=datetime.now(UTC),
                interval_minutes=float(interval),
            )
        except Exception:  # publishing never fails the run
            logger.exception("Publishing the outputs of run %s failed", job.get("job_id"))

    def _failed_payload(self, loop: LoopConfig, exc: BaseException) -> dict[str, Any]:
        summary = loop_summary(pd.DataFrame(columns=["timestamp", "pv"]), [])
        summary["operating_state_reason"] = t(
            "Analysis failed: {error}", error=f"{type(exc).__name__}: {exc}"
        )
        summary["data_quality"] = {"apt": False, "reasons": [], "checked": False}
        return {"config": loop.model_dump(mode="json"), "summary": summary, "results": []}

    def _save_latest(
        self, payloads: dict[str, Any], source_start: str | None, source_end: str | None
    ) -> None:
        rows, kept = [], []
        for loop_id, payload in payloads.items():
            summary = payload["summary"]
            metadata = (payload.get("config") or {}).get("metadata") or {}
            if summary.get("samples") and source_end:
                # This round on the loop, with what its wires carried: its Runs tab draws it
                # for the last ones (``engine.samples``).
                kept.append(
                    {
                        "run_key": loop_run_key(loop_id, source_end),
                        "scope": ROUND_SCOPE,
                        "subject_id": loop_id,
                        "at": source_end,
                        "detail": {
                            "version": summary.get("algorithm_version"),
                            "blocks": summary.get("blocks") or {},
                            "wires": summary["samples"],
                            "outputs": summary.get("outputs") or [],
                            "signals": summary.get("signals") or {},
                            "window": {"start": source_start, "end": source_end},
                        },
                    }
                )
            rows.append(
                {
                    "subject_id": loop_id,
                    "status": summary.get("status"),
                    "health": summary.get("health"),
                    "priority": loop_priority(
                        summary.get("health"), metadata.get("criticality", "medium")
                    ),
                    "summary": {key: value for key, value in summary.items() if key != "samples"},
                    "results": payload.get("results") or [],
                    "source_start": source_start,
                    "source_end": source_end,
                }
            )
        for offset in range(0, len(rows), 500):
            self.latest.save_many(APPLICATION_ID, SUBJECT_KIND, rows[offset : offset + 500])
        for offset in range(0, len(kept), 500):
            self.jobs.samples.save(kept[offset : offset + 500])
        self.latest.forget_missing(
            APPLICATION_ID, SUBJECT_KIND, [loop.loop_id for loop in self.loop_store.list_loops()]
        )

    def _round_config(self, loop: LoopConfig, cache: dict[Any, Any]) -> dict[str, Any]:
        """The loop's algorithm and parameters, resolved exactly as a job resolves them.

        An algorithm whose diagram no longer checks (a block removed in an update) falls back to
        Flow loop, so the portfolio keeps being analysed; the algorithm's page says what is
        wrong.
        """

        config = self.loop_store.effective_method_config(loop, cache=cache)
        key = ("diagram_ok", config["profile_id"])
        if key not in cache:
            cache[key] = compile_algorithm(config["diagram"]).valid
        if not cache[key]:
            logger.warning("Algorithm %s does not check; running Flow loop", config["profile_id"])
            config = self.loop_store.effective_method_config(loop, profile_id=DEFAULT, cache=cache)
        return config

    # Jobs ---------------------------------------------------------------

    def ensure_initial_jobs(self) -> None:
        """Create one immutable baseline job per loop that has none yet."""

        snapshot = self.snapshot
        if snapshot.get("status") != "ok":
            return
        with_jobs = self.jobs.subjects_with_jobs()
        latest = self.latest.results(APPLICATION_ID, SUBJECT_KIND)
        summaries = self.latest.summaries(APPLICATION_ID, SUBJECT_KIND)
        entries = []
        for loop in self.loop_store.list_loops(enabled_only=True):
            if loop.loop_id in with_jobs or loop.loop_id not in summaries:
                continue
            method_config = self.loop_store.effective_method_config(loop)
            entries.append(
                {
                    "loop_id": loop.loop_id,
                    "name": t("Initial analysis"),
                    "kind": "baseline",
                    "range_start": snapshot.get("source_start"),
                    "range_end": snapshot.get("source_end"),
                    "profile_id": method_config["profile_id"],
                    "method_config": method_config,
                    "created_by": "System",
                    "results": latest.get(loop.loop_id, []),
                    "summary": summaries[loop.loop_id]["summary"],
                    "config_snapshot": {
                        "loop": loop.model_dump(mode="json"),
                        "method_config": method_config,
                        "analysis": self.analysis.model_dump(mode="json"),
                    },
                    "source_start": snapshot.get("source_start"),
                    "source_end": snapshot.get("source_end"),
                }
            )
        # One transaction for the whole portfolio (thousands of loops on the first round).
        self.jobs.record_completed_jobs(entries)

    def frame_for_loop(
        self,
        loop_id: str,
        *,
        start: str | None = None,
        end: str | None = None,
        plant: PlantData | None = None,
    ) -> pd.DataFrame:
        """The loop's regular frame over a period, by default the last round's window."""

        loop = self.loop_store.get_loop(loop_id)
        if loop is None:
            return pd.DataFrame()
        if not (start and end):
            latest = self.latest.get(APPLICATION_ID, SUBJECT_KIND, loop_id)
            if latest is None or not latest.get("source_start") or not latest.get("source_end"):
                return pd.DataFrame()
            start, end = latest["source_start"], latest["source_end"]
        try:
            raw = self._read(plant or self.plant, [loop], start, end)
        except Exception:
            logger.warning("History of %s unavailable", loop_id, exc_info=True)
            return pd.DataFrame()
        return build_loop_frame(raw, loop, self.analysis.resample_seconds)

    def job_frame(self, job: dict[str, Any], plant: PlantData | None = None) -> pd.DataFrame | None:
        """The loop's samples over the exact period a finished job analysed."""

        loop = self.loop_store.get_loop(job["loop_id"])
        start = job.get("source_start") or job.get("range_start")
        end = job.get("source_end") or job.get("range_end")
        if loop is None or not start or not end:
            return None
        raw = self._read(plant or self.plant, [loop], start, end)
        if raw.empty:
            return None
        return build_loop_frame(raw, loop, self.analysis.resample_seconds)

    def _read_loop(
        self,
        loop: LoopConfig,
        start: Any = None,
        end: Any = None,
        lookback_minutes: int | None = None,
        plant: PlantData | None = None,
    ) -> pd.DataFrame:
        """The loop's raw samples over a period, or over the last minutes of data."""

        plant = plant or self.plant
        if not (start and end):
            end = self.round_end([loop], plant)
            minutes = int(lookback_minutes or self.analysis.window_minutes)
            start = end - pd.Timedelta(minutes=minutes)
        raw = self._read(plant, [loop], start, end)
        if raw.empty:
            raise RuntimeError(t("PlantCraft has no data for this loop in the requested range."))
        return raw

    def preview(
        self,
        loop_id: str,
        diagram: dict[str, Any],
        *,
        lookback_minutes: int | None = None,
        plant: PlantData | None = None,
        start: Any = None,
        end: Any = None,
    ) -> dict[str, Any]:
        """Run an algorithm's diagram on one loop's recent data without saving anything, or on
        ``start`` to ``end`` (a past run's window, drawn again with every sample).

        The answer carries what every wire carried (``trace``), for the editor to show.
        """

        loop = self.loop_store.get_loop(loop_id)
        if loop is None:
            raise ValueError(t("Loop not found: {loop_id}.", loop_id=loop_id))
        raw = self._read_loop(loop, start, end, lookback_minutes=lookback_minutes, plant=plant)
        config = self.loop_store.effective_method_config(loop)
        payload = analyze_loop(
            self.analysis,
            loop,
            raw,
            diagram=diagram,
            parameter_overrides=config.get("overrides"),
            parameter_defaults=config.get("defaults"),
            external_quality=self._verdicts([loop]).get(loop_id),
            with_trace=True,
        )
        return {
            "loop_id": loop_id,
            "source_start": str(raw.index.min()),
            "source_end": str(raw.index.max()),
            "summary": payload["summary"],
            "results": payload["results"],
            "trace": payload["trace"],
        }

    def _version_run(self, method_config: dict[str, Any], profile_id: str | None) -> int | None:
        """The algorithm version a run's diagram is: the one it carries, else the newest when
        the diagram is that version's (a schedule always runs the newest); none otherwise."""

        if method_config.get("version"):
            return int(method_config["version"])
        chosen = method_config.get("profile_id") or profile_id
        profile = self.presets.get_profile(chosen) if chosen else None
        if not profile:
            return None
        if diagram_of(method_config) != diagram_of(profile.get("method_config") or {}):
            return None
        return int(profile.get("version") or 1)

    def execute_job(
        self, job_id: str, *, publish: bool = True, claimed: bool = False, retry: bool = False
    ) -> dict[str, Any]:
        """Run one persisted job with an immutable method/config snapshot.

        ``publish=False`` keeps its outputs (results, series, messages) to itself: a run
        replayed over the archive (``loops.replay``) is history, not news. ``claimed``: a
        worker of the queue already took it (``JobStore.claim_next``). ``retry``: when the
        plant's data does not answer, raise ``RetryLater`` so the queue tries again later.
        """

        try:
            job = self.jobs.get_job(job_id)
            if job is None:
                raise ValueError(t("Run not found."))
            if job["status"] == "completed":
                return job
            if not claimed and not self.jobs.claim_job(job_id):
                return self.jobs.get_job(job_id) or job
            loop = self.loop_store.get_loop(job["loop_id"])
            if loop is None:
                raise ValueError(t("Loop not found: {loop_id}.", loop_id=job["loop_id"]))
            if loop.incomplete:
                raise ValueError(incomplete_reason(loop))
            method_config = job.get("method_config") or {}
            if not (method_config.get("diagram") or method_config.get("method_ids")):
                method_config = self.loop_store.effective_method_config(
                    loop, profile_id=job.get("profile_id")
                )
            try:
                raw = self._read_loop(
                    loop, job.get("range_start"), job.get("range_end"), job.get("lookback_minutes")
                )
            except Exception as exc:
                if retry and unreachable(str(exc)):
                    raise RetryLater(f"{type(exc).__name__}: {exc}") from exc
                raise
            verdict = self._verdicts([loop]).get(loop.loop_id)
            payload = self.compute.call(
                analyze_loop_task,
                self._task(
                    loop,
                    raw,
                    **_layers(method_config),
                    diagram=diagram_of(method_config),
                    algorithm_id=method_config.get("profile_id") or job.get("profile_id"),
                    external_quality=verdict,
                    compute=method_config.get("compute"),
                ),
            )
            version = self._version_run(method_config, job.get("profile_id"))
            if version:
                # The version that ran, as on an asset's run (its Last run draws that diagram).
                payload["summary"]["algorithm_version"] = version
            self.jobs.complete_job(
                job_id,
                results=payload["results"],
                summary=payload["summary"],
                config_snapshot={
                    "loop": loop.model_dump(mode="json"),
                    "method_config": method_config,
                    "analysis": self.analysis.model_dump(mode="json"),
                },
                source_start=str(raw.index.min()),
                source_end=str(raw.index.max()),
            )
            if publish:
                self._publish_job_outputs(job, loop, payload)
            return self.jobs.get_job(job_id) or {}
        except RetryLater:
            raise
        except Exception as exc:
            logger.exception("Run %s failed", job_id)
            self.jobs.fail_job(job_id, f"{type(exc).__name__}: {exc}")
            return self.jobs.get_job(job_id) or {}

    # Reading the portfolio ----------------------------------------------

    @staticmethod
    def _portfolio_summary(loop_payloads: dict[str, Any]) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for payload in loop_payloads.values():
            status = payload["summary"]["status"]
            statuses[status] = statuses.get(status, 0) + 1
        return {"loop_count": len(loop_payloads), "status_counts": statuses}

    def overview_rows(self) -> list[dict[str, Any]]:
        """One row per loop with its latest status, worst first."""

        key = (self.latest.version, self.loop_store.signature())
        cached = self._overview_cache
        if cached is not None and cached[0] == key:
            return list(cached[1])
        summaries = self.latest.summaries(APPLICATION_ID, SUBJECT_KIND)
        origins = self.loop_store.origins()
        rows = []
        # Incomplete records are listed (with what is missing) but never analysed.
        for loop in self.loop_store.list_loops():
            if not loop.enabled:
                continue
            latest = summaries.get(loop.loop_id)
            row = overview_row(loop, latest["summary"] if latest else None)
            row["origin"] = origins.get(loop.loop_id, "user")
            row["analyzed_at"] = latest.get("analyzed_at") if latest else None
            rows.append(row)
        rows.sort(
            key=lambda row: (
                STATUS_ORDER.get(row["status"], 9),
                row["health"] if row["health"] is not None else 101,
            )
        )
        self._overview_cache = (key, rows)
        return list(rows)

    def loop_payload(self, loop_id: str, plant: PlantData | None = None) -> dict[str, Any] | None:
        """The loop's latest analysis with the samples of that window."""

        loop = self.loop_store.get_loop(loop_id)
        if loop is None:
            return None
        latest = self.latest.get(APPLICATION_ID, SUBJECT_KIND, loop_id)
        if latest is None or loop.incomplete:
            return {
                "config": loop.model_dump(mode="json"),
                "summary": None,
                "results": [],
                "source_start": None,
                "source_end": None,
                "analyzed_at": None,
                "frame": pd.DataFrame(),
            }
        return {
            "config": loop.model_dump(mode="json"),
            "summary": latest["summary"],
            "results": latest["results"],
            "source_start": latest.get("source_start"),
            "source_end": latest.get("source_end"),
            "analyzed_at": latest.get("analyzed_at"),
            "frame": self.frame_for_loop(
                loop_id,
                start=latest.get("source_start"),
                end=latest.get("source_end"),
                plant=plant,
            ),
        }


def _layers(config: dict[str, Any]) -> dict[str, Any]:
    """The parameter layers a stored configuration gives a run.

    Today's configurations keep what sits under the diagram (``defaults``) apart from what
    sits over it (``overrides``); older ones hold everything merged in ``parameters``.
    """

    if "overrides" in config or "defaults" in config:
        return {
            "parameter_overrides": config.get("overrides") or {},
            "parameter_defaults": config.get("defaults") or {},
        }
    return {"parameter_overrides": config.get("parameters"), "parameter_defaults": None}


def missing_roles(loop: LoopConfig) -> list[str]:
    record = loop.asset_record
    missing = list(record.missing_roles) if record else []
    return missing if missing or loop.signals.pv else ["pv"]


def incomplete_reason(loop: LoopConfig) -> str:
    return t(
        "Incomplete record: no signal for {roles}. Bind them on the asset's page in "
        "PlantCraft; Analytics analyses the loop from the next sync.",
        roles=", ".join(role.upper() for role in missing_roles(loop)),
    )


def overview_row(loop: LoopConfig, summary: dict[str, Any] | None) -> dict[str, Any]:
    metadata = loop.metadata or {}
    criticality = metadata.get("criticality", "medium")
    record = loop.asset_record
    extra = {
        "loop_type": record.loop_type if record else None,
        "missing_roles": missing_roles(loop) if loop.incomplete else [],
    }
    if loop.incomplete:
        # An old result of a loop that lost a signal would be misleading: show what is missing.
        summary = {
            "status": "incomplete",
            "operating_state": "incomplete_record",
            "operating_state_reason": incomplete_reason(loop),
        }
    summary = summary or {}
    return {
        **extra,
        "loop_id": loop.loop_id,
        "name": loop.name,
        "area": loop.area,
        "service": loop.service,
        "unit": loop.unit,
        "profile_id": loop.profile_id or "all",
        "function_type": metadata.get("function_type", loop.profile_id or "all"),
        "criticality": criticality,
        "status": summary.get("status") or "pending",
        "state": summary.get("operating_state"),
        "state_reason": summary.get("operating_state_reason")
        or (t("Waiting for the first run.") if not summary else None),
        "health": summary.get("health"),
        "worst_method": summary.get("worst_method") or "—",
        "worst_score": summary.get("worst_score"),
        "limiting": summary.get("limiting") if summary.get("health") is not None else None,
        "context": summary.get("context") or [],
        "alerts": summary.get("alerts") or [],
        "coverage": round(float(summary.get("valid_fraction") or 0) * 100, 1),
        "priority": loop_priority(summary.get("health"), criticality),
    }
