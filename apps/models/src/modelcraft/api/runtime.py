"""Everything one PlantCraft Models server holds: settings, the stores, the workbench, the
Modelica runner and the PlantCraft clients.

Who reads plant data: plant inputs and comparisons of a simulation read with the person's own
token, so PlantCraft's permissions decide which signals they can use. Models' service token
(``PLANTCRAFT_APP_KEY``) only reports runs to PlantCraft's Executions page; without it,
runs are kept here and simply not reported.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any

import httpx
from plantcraft_sdk.auth import TokenVerifier
from plantcraft_sdk.client import PlantCraftClient
from plantcraft_sdk.server.folders import FolderStore
from plantcraft_sdk.server.platform import PlatformRuntime
from plantcraft_sdk.server.queue import SAMPLE_SECONDS, QueueMetrics, QueueNow, QueueSampler
from plantcraft_sdk.server.store import Database

from modelcraft import APP_ID
from modelcraft.config import Settings
from modelcraft.omc.jobs import Executor, LocalExecutor, QueueExecutor, SuiteExecutor
from modelcraft.projects.models import SYSTEM
from modelcraft.projects.store import ProjectStore
from modelcraft.runs.service import Workbench
from modelcraft.runs.store import RunStore
from modelcraft.suite import Suite

LOGGER = logging.getLogger(__name__)
# The example models every install shows, kept as Models ships them (a person duplicates one
# to change it): package -> (name, folder under examples/, description).
EXAMPLES = {
    "PlantCraftExamples": (
        "Examples",
        "models",
        "Process models drawn as block diagrams: a tank's level control, a heat exchanger and a "
        "loop with dead time.",
    ),
    "PlantCraftTwin": (
        "Analytics models",
        "",
        "The models Analytics ships for the Simulator's loops and furnaces, as Modelica classes "
        "and FMUs.",
    ),
}
# The study every install starts with, already run (owner, round 9, D13): how the tank's level
# answers to three controller gains, the way a person would compare them.
EXAMPLE_STUDY = {
    "model": "PlantCraftExamples.TankLevelControl",
    "name": "Example: controller gain",
    "description": "How the tank's level follows its setpoint with three controller gains. "
    "Made by Models as an example: open it to compare the runs, or make your own from the model.",
    "spec": {
        "options": {"start": 0.0, "stop": 900.0, "intervals": 450},
        "sweep": [{"name": "controller.k", "mode": "list", "values": [2, 4, 8]}],
        "indicators": ["tank.level"],
    },
}
# Example projects of earlier versions -> the package that took their place: the project is kept
# (its id, simulations and exports) and becomes that example; removed when there is none, or
# when the successor already exists.
RETIRED_EXAMPLES = {"ProcessExamples": "PlantCraftExamples"}
# The block libraries every install starts with: package -> (name, group, description).
BLOCK_EXAMPLES = {
    "PlantCraftSources": (
        "Sources",
        "Signals",
        "Constants, steps, ramps, sines, pulses and tables of values over time.",
    ),
    "PlantCraftMath": (
        "Math",
        "Signals",
        "Gains, sums, products, divisions, limits and rate limits.",
    ),
    "PlantCraftContinuous": (
        "Continuous",
        "Dynamics",
        "Integrators, derivatives, lags, transfer functions, state space and dead time.",
    ),
    "PlantCraftControl": (
        "Control",
        "Control",
        "A PID controller with limits and anti-windup, and an on/off controller.",
    ),
    "PlantCraftEquipment": (
        "Process equipment",
        "Equipment",
        "A tank, a pump, a control valve, a sensor, a heat exchanger and a reactor.",
    ),
    "PlantCraftSinks": (
        "Sinks",
        "Signals",
        "Scopes: the signals a model's results show on a chart.",
    ),
}


def example_files(package: str, folder: str = "") -> dict[str, str]:
    """The example package's Modelica files, as project paths (``Package/Model.mo``)."""

    root = resources.files("modelcraft") / "examples"
    if folder:
        root = root / folder
    root = root / package
    found: dict[str, str] = {}

    def walk(folder: Any, prefix: str) -> None:
        for entry in folder.iterdir():
            if entry.is_dir():
                walk(entry, f"{prefix}{entry.name}/")
            elif entry.name.endswith(".mo") or entry.name == "package.order":
                found[f"{prefix}{entry.name}"] = entry.read_text(encoding="utf-8")

    if root.is_dir():
        walk(root, f"{package}/")
    return found


# What the site files in folders (round 9, M5): ``<project>/<class>``, a block's class, a study.
FOLDER_KINDS = ("model", "block", "study")


class Runtime(PlatformRuntime):
    def __init__(
        self,
        settings: Settings,
        *,
        verifier: TokenVerifier | None = None,
        service_client: PlantCraftClient | None = None,
        http_client: httpx.Client | None = None,
        executor: Executor | None = None,
    ):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(settings.database_path)
        self.projects = ProjectStore(self.db)
        self.runs = RunStore(self.db)
        # Folders of the site's models, blocks and studies (round 9, M5), as Link's.
        self.folders = FolderStore(self.db, FOLDER_KINDS)
        self.connect(
            APP_ID,
            settings,
            verifier=verifier,
            service_client=service_client,
            http_client=http_client,
        )
        if executor is None:
            if settings.runner == "local":
                executor = LocalExecutor(
                    settings.jobs_path, omc=settings.omc, libraries=settings.libraries
                )
            elif settings.runner == "queue":
                executor = QueueExecutor(settings.jobs_path)
            else:
                executor = SuiteExecutor(settings.jobs_path, lambda: self.service_client)
        self.executor = executor
        self.suite = Suite(lambda: self.service_client, settings.root_path)
        self.workbench = Workbench(
            self.projects,
            self.runs,
            executor,
            settings.data_dir,
            allow_external=settings.allow_external,
            check_timeout=settings.check_seconds,
            run_timeout=settings.run_seconds,
            workers=settings.run_workers,
            publish=self.suite.run_finished,
            publish_study=self.suite.study_finished,
            batch=settings.run_batch,
            blocks=self.projects.library_files,
        )
        self.queue_metrics = QueueMetrics(self.db)
        self.queue_sampler = QueueSampler(self.queue_metrics, self.queue_now)
        if settings.examples:
            self.seed_examples()

    # The queue's numbers (the suite's queue panel, docs/app-standard.md section 10) ----------

    def queue_now(self, since: datetime | None = None) -> QueueNow:
        moment = datetime.now(UTC)
        since = since or moment - timedelta(seconds=SAMPLE_SECONDS)

        def stamp(value: datetime) -> str:
            return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        counts = self.runs.queue_counts(stamp(since), stamp(moment - timedelta(hours=1)))
        return QueueNow(
            **counts, workers=self.workbench.queue.workers, busy=self.workbench.queue.busy()
        )

    # Lifecycle -----------------------------------------------------------------------------

    def seed_examples(self) -> None:
        """The examples and block libraries as this version ships them: created when missing,
        brought up to date when they differ, removed when retired."""

        def package_of(project: dict[str, Any]) -> str:
            tops = {path.split("/")[0] for path in self.projects.files(project["id"])}
            return next(iter(tops)) if len(tops) == 1 else ""

        shipped = [
            (package, name, description, example_files(package, folder), "project", "")
            for package, (name, folder, description) in EXAMPLES.items()
        ] + [
            (package, name, description, example_files(package, "blocks"), "library", group)
            for package, (name, group, description) in BLOCK_EXAMPLES.items()
        ]
        existing = {
            kind: {package_of(p): p for p in self.projects.examples(kind)}
            for kind in ("project", "library")
        }
        for package, successor in RETIRED_EXAMPLES.items():
            project = existing["project"].pop(package, None)
            if project is None:
                continue
            if successor and successor not in existing["project"]:
                existing["project"][successor] = project
            else:
                self.projects.delete(project["id"], by=SYSTEM)
        for package, name, description, files, kind, group in shipped:
            if not files:
                continue
            project = existing[kind].get(package)
            if project is None:
                self.projects.create(
                    name,
                    by=SYSTEM,
                    description=description,
                    files=files,
                    example=True,
                    kind=kind,
                    group=group,
                )
                continue
            self.projects.replace_files(project["id"], files)
            if (project["name"], project["description"], project.get("block_group", "")) != (
                name,
                description,
                group,
            ):
                self.projects.update(
                    project["id"], by=SYSTEM, name=name, description=description, group=group
                )

    def seed_example_study(self) -> dict[str, Any] | None:
        """The example study, queued once (at the first start, or when it was deleted): its
        simulations run with the queue, so it is ready to read a moment after the install."""

        if any(
            study["name"] == EXAMPLE_STUDY["name"] and study.get("created_by") == SYSTEM
            for study in self.runs.studies(model=EXAMPLE_STUDY["model"])
        ):
            return None
        project = next(
            (
                p
                for p in self.projects.examples("project")
                if p["name"] == EXAMPLES["PlantCraftExamples"][0]
            ),
            None,
        )
        if project is None:
            return None
        try:
            return self.workbench.start_study(
                project["id"],
                EXAMPLE_STUDY["model"],
                name=EXAMPLE_STUDY["name"],
                description=EXAMPLE_STUDY["description"],
                spec=EXAMPLE_STUDY["spec"],
                by=SYSTEM,
                max_runs=self.settings.study_max_runs,
            )
        except Exception:  # an example never stops the app from starting
            LOGGER.exception("The example study could not be queued")
            return None

    def start(self) -> None:
        interrupted = self.runs.interrupted()
        if interrupted:
            LOGGER.info("%d runs waited in the queue again after the restart", interrupted)
        adopted = self.runs.adopt_loose_runs()
        if adopted:
            LOGGER.info("%d simulations joined their model's quick simulations", adopted)
        self.workbench.ensure_library()
        resumed = self.workbench.resume_optimizations()
        if resumed:
            LOGGER.info("%d optimizations went on after the restart", resumed)
        if self.settings.examples and self.settings.example_study:
            self.seed_example_study()
        self.workbench.queue.wake()
        self.queue_sampler.start()

    def shutdown(self) -> None:
        self.queue_sampler.stop()
        self.workbench.shutdown()
        self.close_platform()

    def status(self) -> dict[str, Any]:
        return {
            "service_key": self.has_service_key,
            "runner": self.workbench.runner(),
            "library": self.workbench.library_state(),
            "projects": len(self.projects.list()),
            "queue": self.workbench.queue_state(),
            "allow_external": self.settings.allow_external,
        }
