"""Everything one LinkCraft server holds: settings, stores, PlantCraft clients and workers.

Two ways to reach PlantCraft:

- **as the user** (``user_plant(user)``): a request a person makes (open a loop
  page, test an algorithm, run one loop now) forwards that person's token;
- **as the app** (``self.plant``): background work (rounds, schedules, queued
  runs) uses a service token obtained with ``PLANTCRAFT_APP_KEY``.

Without an app key the interface still works for people; background work
reports that the key is missing instead of failing silently.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from plantcraft_sdk.auth import TokenVerifier, User
from plantcraft_sdk.client import PlantCraftClient, PlantCraftError, Unauthorized
from plantcraft_sdk.refs import asset_ref
from plantcraft_sdk.server import ops
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.utc import utc_iso

from linkcraft import APP_ID
from linkcraft.api.compute import RemoteCodePool, site_blocks
from linkcraft.api.events import ScheduleEvents
from linkcraft.api.subjects import ROUND_ID, SIGNAL_APPLICATION_ID, SIGNAL_ROUND_ID
from linkcraft.assets import AssetRunStore, AssetService, examples
from linkcraft.assets.outputs import recording, result_assets
from linkcraft.blocks import register_models, sandbox, site
from linkcraft.blocks.models import ModelRuntime
from linkcraft.blocks.store import BlockStore
from linkcraft.catalog.folders import FolderStore
from linkcraft.catalog.presets import SHIPPED_AUTHOR
from linkcraft.config import Settings
from linkcraft.data.plant import PlantData
from linkcraft.data.samples import SignalReader
from linkcraft.data.suite import SuiteClient
from linkcraft.db import Database
from linkcraft.engine.compute import ComputePool
from linkcraft.engine.jobs import schedule_work
from linkcraft.engine.service import Engine
from linkcraft.engine.suite_compute import SuitePool
from linkcraft.engine.zones import use_installation_zone
from linkcraft.i18n import t
from linkcraft.knowledge import (
    NEW_BLOCK,
    SIGNAL_RUN_PREFIX,
    algorithm_item,
    block_items,
    job_item,
    new_block_item,
    overview_item,
    signal_run_item,
)
from linkcraft.loops.monitor import APPLICATION_ID, SUBJECT_KIND, MonitorService
from linkcraft.loops.replay import HistoryReplay
from linkcraft.loops.suite import (
    ASSET_SERIES_MARK,
    OLD_SERIES_MARK,
    quality_verdicts,
    retire_old_series,
)
from linkcraft.loops.sync import loops_from_processcraft, rename_signal_ids
from linkcraft.models.builtin import register_builtins
from linkcraft.models.simulate import SimulationPool
from linkcraft.models.store import ModelStore
from linkcraft.signals.engine import QualityEngine
from linkcraft.signals.models import SignalQualitySettings
from linkcraft.signals.publish import QualityPublisher
from linkcraft.signals.store import QualityResultStore, SettingsStore, SignalStore

LOGGER = logging.getLogger(__name__)
# A schedule tells PlantCraft at most this many of its assets (API v1 schedules ``subjects``).
MAX_SCHEDULE_ASSETS = 2000
# Marks the demo plant's example twins as added once (``Runtime.add_model_examples``).
EXAMPLES_MARK = "model-examples"
EXAMPLES_RETRY_SECONDS = 600
# Runs per subject and schedule that keep their full detail.
DETAIL_KEPT = 50
# How often Link looks for schedules that stopped running (``ScheduleEvents.check_stalled``).
STALL_CHECK_SECONDS = 300
# The schedules Link once made by itself for each algorithm on assets; they become ordinary
# schedules at start (``migrate_asset_schedules``), at least this far apart.
ASSET_SCHEDULE_KIND = "cycle"
MIN_MIGRATED_MINUTES = 15.0
# Health points older than this (measured from the newest data) are pruned hourly.
HISTORY_DAYS = 90
# How a run started, in the suite's words (app standard, section 6).
RUN_TRIGGERS = ("manual", "schedule", "api")


class MissingAppKey(Unauthorized):
    pass


class _NoServiceClient:
    """Stands in for the service client when no app key is configured."""

    app = APP_ID

    def _fail(self, *_args: Any, **_kwargs: Any) -> Any:
        raise MissingAppKey(
            t(
                "Background work needs an app key: an admin creates one in PlantCraft and "
                "sets PLANTCRAFT_APP_KEY for Analytics."
            ),
            status_code=401,
        )

    series = series_many = series_many_pandas = value = assets = asset = _fail
    signals = signal = audit = me = _fail

    def with_token(self, token: str) -> Any:
        raise NotImplementedError


class Runtime(PlatformRuntime):
    def __init__(
        self,
        settings: Settings,
        *,
        verifier: TokenVerifier | None = None,
        service_client: PlantCraftClient | None = None,
        http_client: httpx.Client | None = None,
        compute: ComputePool | None = None,
        simulations: Any = None,
    ):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        # Before any worker process starts: they read the site blocks' versions from there.
        site.set_folder(settings.blocks_dir)
        self.db = Database(settings.database_path)
        self.connect(
            APP_ID,
            settings,
            verifier=verifier,
            service_client=service_client,
            http_client=http_client,
        )
        self.service_client: Any = self.service_client or _NoServiceClient()
        # "Local time" in a schedule is the installation's zone, as PlantCraft says it.
        reader = getattr(self.service_client, "installation_time_zone", None)
        if callable(reader):
            use_installation_zone(reader)
        self.compute = compute or self._compute_pool()
        self.plant = PlantData(self.service_client)
        self.suite = SuiteClient(self.service_client)
        # Signal quality: the signals, their verdicts, the algorithm's settings and engine.
        self.signal_reader = SignalReader(self.service_client)
        self.signal_store = SignalStore(self.db)
        self.quality_results = QualityResultStore(self.db)
        self.quality_settings = SettingsStore(
            self.db, SignalQualitySettings(window_hours=settings.signal_window_hours)
        )
        self.quality_publisher = QualityPublisher(
            self.suite if self.has_service_key else None, settings.root_path
        )
        self.quality_engine = QualityEngine(
            self.signal_store,
            self.quality_results,
            compute=self.compute,
            publisher=self.quality_publisher,
        )
        self.monitor = MonitorService(
            self.db,
            self.plant,
            analysis=settings.analysis,
            compute=self.compute,
            suite=self.suite,
            root_path=settings.root_path,
            quality=self.loop_quality,
        )
        self.loops = self.monitor.loop_store
        self.jobs = self.monitor.jobs
        self.presets = self.monitor.presets
        self.latest = self.monitor.latest
        # Blocks written on the site, every version in the catalog.
        self.blocks = BlockStore(self.db)
        # Folders for the site's blocks, algorithms and schedules (round 9, D14).
        self.folders = FolderStore(self.db)
        self.blocks.register()
        # Process models (FMUs) and the algorithms that run on assets with them.
        self.models = ModelStore(self.db, settings.models_dir)
        register_builtins(self.models)
        self.simulations = simulations or SimulationPool(
            settings.simulation_workers, settings.simulation_timeout
        )
        self.refresh_models()
        self._catalog_lock = threading.Lock()
        self._catalog_stamp = (self.models.signature(), self.blocks.signature())
        self.asset_runs = AssetRunStore(self.db)
        self.assets = AssetService(
            self.presets,
            self.asset_runs,
            client=lambda: self.service_client,
            models=ModelRuntime(self.models, self.simulations),
            publish=lambda payload, at, minutes: self.publisher_call(
                "publish_asset_run", payload, at, minutes
            ),
        )
        self.replay = HistoryReplay(
            self.monitor,
            resolve_selector=self.resolve_selector,
            publish_run=lambda run: self.publisher_call("publish_run", run),
        )
        # The schedules, the queue and its workers (``engine.service``); in a process of their
        # own unless ``settings.engine`` is "inline" (``start``).
        self.engine = Engine(self, slots=settings.workers or None)
        # What the Alarms app hears about the schedules.
        self.events = ScheduleEvents(self, self.db)
        self._engine_process: Any = None
        self.jobs.ensure_round_schedule(
            APPLICATION_ID,
            name=t("Control loop performance"),
            subject_kind=SUBJECT_KIND,
            interval_minutes=settings.analysis.interval_minutes,
            timezone=settings.timezone,
        )
        self.jobs.ensure_round_schedule(
            SIGNAL_APPLICATION_ID,
            name=t("Signal quality"),
            subject_kind="signal",
            interval_minutes=settings.signal_interval_minutes,
            timezone=settings.timezone,
        )
        self.last_sync: dict[str, Any] = {}
        self._last_prune = 0.0
        self._summaries_thin = False
        self._last_stall_check = 0.0
        self._examples_tried = -float(EXAMPLES_RETRY_SECONDS)
        self._series_tried = -float(EXAMPLES_RETRY_SECONDS)
        self._series_retired = False
        self._started = False

    def own_series(self, signal: str, start: str | None) -> dict[str, Any]:
        """One of Link's own series in the Historian, up to now, read with the app's key."""

        if self.service_client is None:
            raise PlantCraftError("Link has no app key yet.")
        return self.service_client.series(
            signal, start=start, end=utc_iso(datetime.now(timezone.utc))
        )

    def refresh_models(self) -> list[str]:
        """One block per published model in the catalog (at start and after every change)."""

        return register_models(self.models.list())

    def sync_catalog(self) -> None:
        """Bring into this process's catalog the models and site blocks another process saved.

        The web process registers what people save as they save it; the engine runs in a process
        of its own, so before each execution it checks the stores and catches up when they moved.
        """

        stamp = (self.models.signature(), self.blocks.signature())
        if stamp == self._catalog_stamp:
            return
        with self._catalog_lock:
            if stamp == self._catalog_stamp:
                return
            self.blocks.sync()
            self.refresh_models()
            self._catalog_stamp = stamp

    def model_runtime(self) -> ModelRuntime:
        return ModelRuntime(self.models, self.simulations)

    # PlantCraft as the user -------------------------------------------------

    def user_plant(self, user: User) -> PlantData:
        return self.plant.with_client(self.user_client(user))

    def user_signal_reader(self, user: User) -> SignalReader:
        return SignalReader(self.user_client(user))

    @property
    def has_service_key(self) -> bool:
        return not isinstance(self.service_client, _NoServiceClient)

    # Loops ---------------------------------------------------------------------

    def sync_loops(self, client: Any = None) -> dict[str, Any]:
        """Read the loop assets from PlantCraft into the loop table."""

        try:
            loops = loops_from_processcraft(
                client or self.service_client, self.settings.loop_asset_kind
            )
        except PlantCraftError as exc:
            self.last_sync = {"status": "error", "error": str(exc), "at": _now()}
            return self.last_sync
        counts = self.loops.sync_from_assets(loops)
        renamed = rename_signal_ids(self.loops, client or self.service_client)
        self.last_sync = {
            "status": "ok",
            "found": len(loops),
            **counts,
            "signal_ids_renamed": renamed["renamed"],
            "at": _now(),
        }
        return self.last_sync

    def run_scheduled_round(
        self, schedule: dict[str, Any], trigger: str, started_by: str = ""
    ) -> dict[str, Any]:
        """The round a round schedule names: the loops' monitoring round or Signal quality."""

        if self.is_signal_round(schedule):
            return self.run_signal_quality(trigger, started_by)
        return self.run_round(trigger)

    @staticmethod
    def is_signal_round(schedule: dict[str, Any]) -> bool:
        return schedule.get("schedule_id") == SIGNAL_ROUND_ID

    # The queue -------------------------------------------------------------------------------

    def queued(self) -> None:
        """Something was queued: the engine takes it (here, or in its own process soon)."""

        self.queue_changed()
        if self.settings.engine == "inline":
            self.engine.ensure_workers()

    def queue_changed(self) -> None:
        """The queue's answer kept for a few seconds (``GET /api/queue``) is read again."""

        self.__dict__.pop("queue_answers", None)

    def queue_round(self, schedule_id: str, *, user: str = "", kind: str = "manual") -> str | None:
        """Queue a round now (a person's "Run now"); ``None`` when one is already waiting or
        running."""

        schedule = self.jobs.get_schedule(schedule_id)
        if schedule is None or self.jobs.open_work("round", "*", schedule_id):
            return None
        job_id = self.jobs.create_job(
            loop_id="*",
            name=schedule["name"],
            kind=kind,
            schedule_id=schedule_id,
            created_by=user or "System",
            application_id=schedule.get("application_id") or APPLICATION_ID,
            subject_kind=schedule.get("subject_kind") or SUBJECT_KIND,
            work="round",
        )
        if kind == "manual":
            self.jobs.mark_manual_run(schedule_id)
        self.queued()
        return job_id

    def queue_replay(
        self, hours: float, step_minutes: float, user: str = "", schedule_id: str | None = None
    ) -> str | None:
        """Queue a replay of the past (every schedule, or one); ``None`` while one is open."""

        if self.jobs.open_work("replay"):
            return None
        schedule = self.jobs.get_schedule(schedule_id) if schedule_id else None
        name = t("Replay of the last {hours} hours", hours=f"{hours:g}")
        job_id = self.jobs.create_job(
            loop_id="*",
            name=f"{name}: {schedule['name']}" if schedule else name,
            kind="replay",
            created_by=user or "System",
            schedule_id=schedule_id if schedule else None,
            work="replay",
            payload={"hours": hours, "step_minutes": step_minutes, "schedule_id": schedule_id},
        )
        self.queued()
        return job_id

    def replay_state(self) -> dict[str, Any]:
        """How far the latest replay of the past got (``GET /api/history/replay``)."""

        job = self.jobs.latest_work("replay")
        if job is None:
            return {"running": False}
        if self.replay.running:
            return {**self.replay.state, "job_id": job["job_id"]}
        payload = job.get("payload") or {}
        state = {
            **(job.get("summary") or {}),
            "running": job["status"] in {"queued", "running"},
            "status": job["status"],
            "hours": payload.get("hours"),
            "step_minutes": payload.get("step_minutes"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("completed_at"),
            "done": int(job.get("progress_done") or 0),
            "total": int(job.get("progress_total") or 0),
            "job_id": job["job_id"],
        }
        if job.get("error_message"):
            state["error"] = job["error_message"]
        return state

    def queue_asset_runs(self, profile: dict[str, Any], user: str = "") -> list[str]:
        """One execution of an algorithm per asset it runs on, now (its "Run now")."""

        config = profile.get("method_config") or {}
        ids = [
            self.jobs.create_job(
                loop_id=asset_id,
                name=profile.get("name") or profile["profile_id"],
                kind="manual",
                profile_id=profile["profile_id"],
                created_by=user or "System",
                application_id=profile["profile_id"],
                subject_kind="asset",
                work="asset",
            )
            for asset_id in config.get("assets") or []
        ]
        if ids:
            self.queued()
        return ids

    def wait_for(self, job_ids: list[str], timeout: float) -> bool:
        """Wait until these executions end; ``False`` when time ran out first."""

        deadline = time.monotonic() + timeout
        pending = list(job_ids)
        delay = 0.05
        while pending:
            pending = [
                job_id
                for job_id in pending
                if (self.jobs.get_job(job_id) or {}).get("status") in {"queued", "running"}
            ]
            if not pending:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(delay)
            delay = min(0.5, delay * 1.5)
        return True

    def migrate_asset_schedules(self) -> int:
        """Schedules and algorithms are independent (owner, 2026-10-24): a schedule chooses the
        algorithm and its assets. The schedules Link once made by itself for each algorithm on
        assets (kind "cycle", every ``timing.cycle_seconds``) become ordinary schedules on the
        assets the algorithm named, at least every ``MIN_MIGRATED_MINUTES``. Returns how many
        changed (none after the first start)."""

        changed = 0
        for schedule in self.jobs.list_schedules(kind=ASSET_SCHEDULE_KIND):
            profile = self.presets.get_profile(schedule.get("profile_id") or "") or {}
            assets = [
                str(item) for item in (profile.get("method_config") or {}).get("assets") or []
            ]
            if not profile or not assets:
                self.jobs.delete_schedule(schedule["schedule_id"])
                changed += 1
                continue
            minutes = max(MIN_MIGRATED_MINUTES, float(schedule.get("interval_minutes") or 0))
            self.jobs.update_schedule(
                schedule["schedule_id"],
                kind="protocol",
                selector={"mode": "list", "ids": assets},
                interval_minutes=minutes,
            )
            changed += 1
        return changed

    def schedule_overlap(
        self, profile_id: str | None, subjects: list[str], *, exclude: str | None = None
    ) -> dict[str, Any] | None:
        """Another schedule that already runs this algorithm on one of these subjects (each
        asset runs an algorithm in one schedule only, so each of its signals has one origin):
        ``{"schedule": ..., "subjects": [...]}``, or ``None``."""

        if not profile_id or not subjects:
            return None
        wanted = set(subjects)
        for schedule in self.jobs.list_schedules():
            if (
                schedule["schedule_id"] == exclude
                or schedule.get("kind") == "round"
                or schedule.get("profile_id") != profile_id
            ):
                continue
            taken = (
                set(self.schedule_subjects(schedule))
                if schedule.get("selector") is not None
                else {schedule["loop_id"]}
            )
            shared = sorted(wanted & taken)
            if shared:
                return {"schedule": schedule, "subjects": shared}
        return None

    def capacity(self, executions: int, schedule: dict[str, Any]) -> dict[str, Any]:
        """Whether the queue keeps up with a schedule: how long one occurrence takes to run
        with the engine's workers, measured from the latest executions, against its period."""

        work = schedule_work(schedule)
        each = self.jobs.mean_seconds(work)
        workers = max(1, self.engine.live().workers)
        period = PERIOD_SECONDS.get(schedule.get("cadence") or "")
        if schedule.get("cadence") in {"interval", "calendar"}:
            # A calendar every N minutes or hours names its step; one on days has no fixed period.
            period = float(schedule.get("interval_minutes") or 0) * 60 or None
        drain = executions * each / workers if each is not None else None
        warning = ""
        if drain is not None and period and drain > period:
            warning = t(
                "Each occurrence takes about {time} with {workers} workers, longer than the time "
                "between occurrences: the queue would not empty and occurrences would be skipped.",
                time=_duration(drain),
                workers=workers,
            )
        return {
            "seconds_each": round(each, 2) if each is not None else None,
            "workers": workers,
            "drain_seconds": round(drain, 1) if drain is not None else None,
            "period_seconds": period,
            "warning": warning,
        }

    def schedule_subjects(self, schedule: dict[str, Any]) -> list[str]:
        """The subjects a schedule's rule matches now: loops, or an algorithm's assets."""

        selector = schedule.get("selector") or {}
        if selector.get("mode") == "algorithm":
            profile = self.presets.get_profile(schedule.get("profile_id") or "") or {}
            return list((profile.get("method_config") or {}).get("assets") or [])
        if schedule.get("subject_kind") == "asset":
            # Assets are PlantCraft's: the schedule names them (a list); none are looked up here.
            return [str(item) for item in selector.get("ids") or []]
        return self.resolve_selector(selector)

    # Signal quality --------------------------------------------------------------

    def signal_interval_minutes(self) -> float:
        schedule = self.jobs.get_schedule(SIGNAL_ROUND_ID) or {}
        return float(schedule.get("interval_minutes") or self.settings.signal_interval_minutes)

    def loop_quality(self, loops: list[Any]) -> dict[str, dict[str, Any]]:
        """The Signal quality algorithm's latest word on these loops' signals."""

        wanted = sorted(
            {signal for loop in loops for signal in loop.signals.model_dump().values() if signal}
        )
        latest = self.quality_results.latest_many(wanted) if wanted else {}
        return quality_verdicts(
            latest, loops, max_age_minutes=max(60.0, 2 * self.signal_interval_minutes())
        )

    def run_signal_quality(self, trigger: str = "manual", started_by: str = "") -> dict[str, Any]:
        """One execution of the Signal quality algorithm, published as a run."""

        self.quality_engine.interval_minutes = self.signal_interval_minutes()
        try:
            result = self.quality_engine.run_round(
                self.signal_reader,
                self.quality_settings.get(),
                trigger=trigger,
                started_by=started_by,
                sync=self.has_service_key,
            )
        finally:
            self.publish_schedules()
        return {
            **result,
            "subjects": result.get("signals", 0),
            "status_counts": result.get("counts", {}),
            "duration_seconds": result.get("duration_seconds"),
        }

    def run_round(self, trigger: str = "manual") -> dict[str, Any]:
        """One monitoring round, reported to PlantCraft as a run (manual, schedule or api)."""

        started = datetime.now(timezone.utc)
        run_id = f"round-{started.strftime('%Y%m%dT%H%M%S%fZ')}"
        schedule = self.jobs.get_schedule(ROUND_ID) or {}
        self.monitor.interval_minutes = float(
            schedule.get("interval_minutes") or self.settings.analysis.interval_minutes
        )
        run = {
            "id": run_id,
            "name": t("Control loop performance"),
            "trigger": trigger if trigger in RUN_TRIGGERS else "api",
            "started_at": started.isoformat(timespec="seconds"),
        }
        self.publisher_call("publish_run", {**run, "status": "running", "finished_at": None})
        if self.has_service_key:
            self.sync_loops()
        snapshot = self.monitor.run_once(run_id)
        header = {key: value for key, value in snapshot.items() if key != "loops"}
        if header.get("status") == "ok":
            self.monitor.ensure_initial_jobs()
        summary = header.get("summary") or {}
        loops = snapshot.get("loops") or {}
        origins = self.loops.origins()
        self.publisher_call(
            "publish_run",
            {
                **run,
                "status": "done" if header.get("status") == "ok" else "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "subjects": [
                    asset_ref(loop_id)
                    for loop_id in loops
                    if origins.get(loop_id) == "processcraft"
                ],
                "summary": header.get("error")
                or t(
                    "{count} loops analysed: {counts}.",
                    count=summary.get("loop_count", 0),
                    counts=", ".join(
                        f"{key} {value}"
                        for key, value in sorted((summary.get("status_counts") or {}).items())
                    )
                    or "—",
                ),
            },
        )
        self.publish_schedules()
        return {
            "status": header.get("status"),
            "subjects": summary.get("loop_count", 0),
            "status_counts": summary.get("status_counts", {}),
            "duration_seconds": header.get("duration_seconds"),
            "source_start": header.get("source_start"),
            "source_end": header.get("source_end"),
            "error": header.get("error"),
            "header": header,
        }

    def publisher_call(self, name: str, *args: Any) -> Any:
        """Call the suite publisher; publishing never fails the work it reports."""

        publisher = self.monitor.publisher
        if publisher is None:
            return None
        try:
            return getattr(publisher, name)(*args)
        except Exception:
            LOGGER.exception("Publishing to PlantCraft (%s) failed", name)
            return None

    # What LinkCraft explains to the suite's assistants (linkcraft.knowledge) ----------

    @property
    def root_path(self) -> str:
        publisher = self.monitor.publisher
        return publisher.root if publisher is not None else "/link"

    def publish_algorithms(self, profiles: list[dict[str, Any]] | None = None) -> Any:
        """The algorithms' documentation; all of them, with every block's, when not given."""

        root = self.root_path
        if profiles is None:
            items = block_items(root)
            profiles = self.presets.list_profiles()
        else:
            items = []
        for profile in profiles:
            try:
                items.append(algorithm_item(profile, root))
            except Exception:  # one algorithm that cannot be explained never stops the others
                LOGGER.exception("Explaining algorithm %s failed", profile.get("profile_id"))
        return self.publisher_call("publish_knowledge", items)

    def explain(self, ref: str) -> dict[str, Any] | None:
        """The text about one of LinkCraft's objects, freshly written; None for others."""

        kind, _, rest = ref.partition(":")
        if kind == "app" and rest == APP_ID:
            return self.overview_item()
        app, _, item_id = rest.partition("/")
        if app != APP_ID or not item_id:
            return None
        root = self.root_path
        if kind in {"algorithm", "protocol"}:
            # A protocol of 0.2 is explained by the algorithm that replaced it.
            profile = self.presets.get_profile(item_id)
            return algorithm_item(profile, root) if profile else None
        if kind == "block" and item_id == NEW_BLOCK:
            return new_block_item(root)
        if kind == "block":
            return next((item for item in block_items(root) if item["ref"] == ref), None)
        if kind != "run":
            return None
        if item_id.startswith(SIGNAL_RUN_PREFIX):
            number = item_id[len(SIGNAL_RUN_PREFIX) :]
            found = self.quality_results.round(int(number)) if number.isdigit() else None
            if found is None:
                return None
            latest = self.quality_results.summaries()
            worst = [
                {"signal": key, **value}
                for key, value in latest.items()
                if value.get("status") in {"bad", "suspect"}
            ]
            return signal_run_item(found, worst, root)
        job = self.jobs.get_job(item_id)
        if job is None:
            return None
        job["results"] = self.jobs.job_results(item_id)
        asset = self.loops.origins().get(job["loop_id"]) == "processcraft"
        return job_item(job, root, asset=asset)

    def overview_item(self) -> dict[str, Any]:
        """Everything Link judged, worst first, with its algorithms and latest runs."""

        from linkcraft.api.routers.results import BUILDERS, _key  # the Results page's rows

        rows = sorted((row for build in BUILDERS.values() for row in build(self)), key=_key)
        algorithms = [
            {
                "profile_id": item["profile_id"],
                "name": item["name"],
                "description": item["description"],
            }
            for item in self.presets.list_profiles()
        ]
        return overview_item(rows, algorithms, self.jobs.list_jobs(limit=15), self.root_path)

    def publish_explanation(self, ref: str) -> bool:
        """Write the text about ``ref`` before someone asks the assistant about it."""

        item = self.explain(ref)
        return bool(item and self.publisher_call("publish_knowledge", [item]))

    def recording(self, schedule: dict[str, Any], profile: dict[str, Any]) -> Any:
        """What an execution of ``schedule`` records (``assets.outputs.recording``)."""

        return recording(schedule, profile)

    def publish_schedules(self) -> Any:
        """LinkCraft's whole schedule list, as PlantCraft's Executions page shows it."""

        schedules = [
            {**item, "subjects": self.schedule_assets(item)} for item in self.jobs.list_schedules()
        ]
        names = {row["asset_id"]: row.get("asset_name") for row in self.asset_runs.list()}
        results = result_assets(
            schedules,
            lambda profile_id: (
                (self.presets.get_profile(profile_id) or {}).get("method_config") or {}
            ),
            names,
        )
        return self.publisher_call("publish_schedules", schedules, results)

    def schedule_assets(self, schedule: dict[str, Any]) -> list[str]:
        """The assets a schedule runs on (``asset:<id>``), so a rule of Alarms can cover an
        execution's assets; none when they cannot be told now."""

        from linkcraft.api.events import _subject
        from linkcraft.api.subjects import kind_of, subjects_of

        try:
            found = subjects_of(self, schedule)
        except Exception:  # noqa: BLE001 - the schedule is still listed, without its assets
            LOGGER.exception("Assets of schedule %s not read", schedule.get("schedule_id"))
            return []
        refs = [_subject(str(item), kind_of(schedule)) for item in found]
        return list(dict.fromkeys(ref for ref in refs if ref))[:MAX_SCHEDULE_ASSETS]

    def resolve_selector(self, selector: dict[str, Any]) -> list[str]:
        """Loops a selection rule matches now (every enabled loop by default)."""

        mode = selector.get("mode") or "all"
        enabled = self.loops.list_loops(enabled_only=True)
        if mode == "list":
            known = {loop.loop_id for loop in enabled}
            return [item for item in selector.get("ids") or [] if item in known]
        statuses = set(selector.get("statuses") or [])
        query = str(selector.get("q") or "").strip().lower()
        latest = self.latest.summaries(APPLICATION_ID, SUBJECT_KIND) if statuses else {}
        matched = []
        for loop in enabled:
            metadata = loop.metadata or {}
            checks = (
                (selector.get("areas"), loop.area),
                (selector.get("function_types"), metadata.get("function_type", loop.profile_id)),
                (selector.get("criticalities"), metadata.get("criticality", "medium")),
            )
            if any(values and value not in values for values, value in checks):
                continue
            if statuses and (latest.get(loop.loop_id) or {}).get("status") not in statuses:
                continue
            if query and query not in f"{loop.loop_id} {loop.name} {loop.service}".lower():
                continue
            matched.append(loop.loop_id)
        return matched

    # Background ----------------------------------------------------------------

    def tick(self) -> None:
        self.add_model_examples()
        self.retire_old_series()
        if not self._summaries_thin:
            # Summaries kept before 0.4.1 carried every recorded point: thinned a batch a tick.
            self._summaries_thin = self.jobs.thin_summaries() == 0
        if time.monotonic() - self._last_prune >= 3600:
            self._last_prune = time.monotonic()
            self.latest.prune_history(days=HISTORY_DAYS)
            self.quality_results.prune(HISTORY_DAYS)
            self.jobs.prune_jobs(days=HISTORY_DAYS)
            self.jobs.prune_detail(keep=DETAIL_KEPT)
        if time.monotonic() - self._last_stall_check >= STALL_CHECK_SECONDS:
            self._last_stall_check = time.monotonic()
            try:
                self.events.check_stalled()
            except Exception:  # PlantCraft away: said at the next check
                LOGGER.warning("The stalled schedules were not checked", exc_info=True)

    def retire_old_series(self) -> None:
        """Once PlantCraft answers: retire the series Link stopped writing in 0.4."""

        if self._series_retired or not self.has_service_key:
            return
        now = time.monotonic()
        if now - self._series_tried < EXAMPLES_RETRY_SECONDS:
            return
        self._series_tried = now
        try:
            loops = {loop.loop_id for loop in self.monitor.loop_store.list_loops()}
            retire_old_series(self.suite, self.presets, loops)
        except Exception:  # PlantCraft away: try again later
            LOGGER.warning("The series Link no longer writes were not retired yet", exc_info=True)
        self._series_retired = all(
            self.presets.marked(mark) is not None for mark in (OLD_SERIES_MARK, ASSET_SERIES_MARK)
        )

    def add_model_examples(self) -> None:
        """On the Simulator demo plant, its example twins once: calibrated on the last hours and
        scheduled on their assets, so the models run without anyone pressing a button. Done once
        (a person who deletes one keeps it deleted); another plant is looked at every ten minutes
        in case the Simulator is added later."""

        if self.presets.marked(EXAMPLES_MARK) is not None:
            return
        now = time.monotonic()
        if now - self._examples_tried < EXAMPLES_RETRY_SECONDS:
            return
        self._examples_tried = now
        try:
            created = examples.create_examples(
                self,
                self.service_client,
                self.plant,
                owner="",
                owner_name=SHIPPED_AUTHOR,
                names=examples.DEMO_EXAMPLES,
            )
        except Exception:  # PlantCraft away or no app key: try again later
            LOGGER.warning("The demo plant's example twins could not be added yet", exc_info=True)
            return
        if created or self._has_examples():
            self.presets.mark(EXAMPLES_MARK, ",".join(item["algorithm_id"] for item in created))
            if created:
                LOGGER.info("Added the demo plant's example twins: %s", created)

    def _has_examples(self) -> bool:
        return any(
            (profile.get("author") == SHIPPED_AUTHOR and not profile.get("system"))
            for profile in self.presets.list_profiles()
        )

    def start(self) -> None:
        """Show the last round again and start the engine where ``settings.engine`` says:
        here ("inline"), in a process of its own ("process") or nowhere ("external": the
        ``linkcraft engine`` command runs it, in a container of its own, say)."""

        if self._started:
            return
        self._started = True
        header = self.round_header()
        if self.monitor.has_results() and header:
            self.monitor.restore(header)
        if self.settings.scheduler_enabled:
            self.publish_schedules()
            self.publish_algorithms()
        # PlantCraft's monitor records the queue and tells the admins when it does not drain.
        ops.report_queue(self.engine.live)
        if self.settings.engine == "inline":
            self.start_engine()
        elif self.settings.engine == "process":
            from linkcraft.engine.process import EngineProcess

            self._engine_process = EngineProcess(self.settings)
            self._engine_process.start()

    def start_engine(self) -> None:
        """The schedules and the queue's workers, in this process (``engine.service``)."""

        self.quality_results.interrupt_running()
        self.migrate_asset_schedules()
        self.engine.start(scheduler=self.settings.scheduler_enabled)

    def _compute_pool(self) -> Any:  # noqa: ANN401
        """Where the analyses and the blocks' code run: worker processes here (``local``, the
        default) or the suite's compute workers (``LINKCRAFT_COMPUTE=suite``; docs/compute.md)."""

        if os.environ.get("LINKCRAFT_COMPUTE", "local").strip().lower() != "suite":
            return ComputePool()
        if not self.has_service_key:
            LOGGER.warning("LINKCRAFT_COMPUTE=suite needs the app key; analysing here instead.")
            return ComputePool()
        from plantcraft_sdk.compute.client import ComputeClient

        from linkcraft import __version__

        pool = SuitePool(
            ComputeClient(self.service_client, version=__version__),
            processes=int(os.environ.get("LINKCRAFT_COMPUTE_SLOTS", "") or 8),
            extras=site_blocks,
        )
        sandbox.use_pool(
            RemoteCodePool(
                pool,
                timeout=float(
                    os.environ.get("LINKCRAFT_BLOCK_TIMEOUT_SECONDS", "")
                    or sandbox.DEFAULT_TIMEOUT_SECONDS
                ),
            )
        )
        LOGGER.info("Analyses and blocks' code run on the suite's compute workers.")
        return pool

    def compute_offer(self) -> dict[str, Any]:
        """The environments and sizes the suite's compute workers offer Analytics now, for where
        an algorithm runs (PlantCraft docs/compute.md)."""

        offer: dict[str, Any] = {
            "suite": False,
            "environments": ["standard"],
            "sizes": ["small", "medium", "large"],
            "workers": 0,
        }
        client = getattr(self.compute, "compute", None)
        if client is None:
            return offer
        try:
            found = client.capacity()
        except Exception as exc:  # PlantCraft restarting: the defaults, and why
            return {**offer, "suite": True, "error": str(exc)}
        return {
            "suite": True,
            "environments": found.get("environments") or ["standard"],
            "sizes": found.get("sizes") or ["small"],
            "workers": int(found.get("workers") or 0),
        }

    def cancel_compute(self, run: str) -> None:
        """An execution cancelled here: its tasks on the suite's compute workers too."""

        cancel = getattr(self.compute, "cancel_run", None)
        if not callable(cancel):
            return
        try:
            cancel(run)
        except Exception:  # the tasks end on their own; the execution is cancelled here
            LOGGER.warning("The compute tasks of %s were not cancelled", run, exc_info=True)

    def shutdown(self) -> None:
        ops.report_queue(None)
        if self._engine_process is not None:
            self._engine_process.stop()
            self._engine_process = None
        self.simulations.shutdown()
        self.engine.stop()
        self.compute.shutdown()
        sandbox.shutdown()
        self.close_platform()

    def round_header(self) -> dict[str, Any]:
        """The last monitoring round's header, wherever the engine ran it."""

        schedule = self.jobs.get_schedule(ROUND_ID) or {}
        return (schedule.get("last_summary") or {}).get("header") or self.monitor.snapshot

    def round_state(self, schedule_id: str, here: Any) -> tuple[bool, dict[str, Any]]:
        """Whether a round is running and how far it got: from ``here`` (the round's engine
        in this process) or from its open execution in the queue."""

        if here.running:
            return True, dict(here.progress)
        job = self.jobs.open_work("round", "*", schedule_id)
        if job is None or job.get("status") != "running":
            return False, dict(here.progress)
        return True, {
            "done": int(job.get("progress_done") or 0),
            "total": int(job.get("progress_total") or 0),
            "started_at": job.get("started_at"),
        }

    def status(self) -> dict[str, Any]:
        schedule = self.jobs.get_schedule(ROUND_ID) or {}
        running, progress = self.round_state(ROUND_ID, self.monitor)
        signals_running, signals_progress = self.round_state(SIGNAL_ROUND_ID, self.quality_engine)
        return {
            "round": self.round_header(),
            "progress": progress,
            "running": running,
            "schedule": {
                key: schedule.get(key)
                for key in ("enabled", "interval_minutes", "next_run_at", "last_run_at")
            },
            "sync": self.last_sync,
            "service_key": self.has_service_key,
            "loop_count": len(self.loops.list_loops(enabled_only=True)),
            "signal_quality": {
                "running": signals_running,
                "progress": signals_progress,
                "last_run": next(iter(self.quality_results.rounds(1)), None),
                "signal_count": self.signal_store.count(),
            },
        }


PERIOD_SECONDS = {"hourly": 3600.0, "daily": 86_400.0, "weekly": 604_800.0}


def _duration(seconds: float) -> str:
    if seconds < 90:
        return t("{n} s", n=round(seconds))
    if seconds < 5400:
        return t("{n} min", n=round(seconds / 60))
    return t("{n} h", n=f"{seconds / 3600:.1f}")


def _now() -> str:
    return utc_iso()
