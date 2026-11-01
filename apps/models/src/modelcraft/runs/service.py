"""The workbench: checks, diagrams, the library, simulations and FMU exports.

Everything that needs omc goes through the ``Executor`` (the runner container in the suite).
Checks and diagrams answer in the request; simulations and exports are runs: they wait in the
queue (``runs/queue.py``), are handed to the runner a few at a time and are kept with their
results, so a person can leave the page and come back to them. A study's sweep is many runs of
one model; the runner builds the model once and simulates each combination.

Before any job leaves for the runner the project's files pass the policy
(``modelica.source.policy``): no external C code, no file or system commands.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import zipfile
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from plantcraft_sdk.files import write_json

from modelcraft.i18n import t
from modelcraft.modelica.source import find, flatten, outline, policy
from modelcraft.omc import results
from modelcraft.omc.diagram import reduce
from modelcraft.omc.jobs import Executor, JobAnswer, RunnerUnavailable, new_job_id
from modelcraft.omc.library import LibraryIndex, parse_index
from modelcraft.omc.messages import simulation_log
from modelcraft.projects.store import ProjectStore
from modelcraft.runs import optimize, studies
from modelcraft.runs.queue import Dispatcher
from modelcraft.runs.store import PRIORITY_SINGLE, PRIORITY_SWEEP, RunStore

LOGGER = logging.getLogger(__name__)
LIBRARY_ROOTS = ("Modelica", "ModelicaServices", "Complex")
DIAGRAM_CACHE = 64
# The compilations a model keeps (Compile on its page); older ones are deleted.
KEEP_BUILDS = 3


class WorkbenchError(ValueError):
    """A request the workbench refuses, with words a person can act on."""


class RunnerDown(WorkbenchError):
    """The Modelica runner is not answering: nothing was run."""


class PolicyError(WorkbenchError):
    def __init__(self, problems: list[dict[str, Any]]):
        super().__init__(t("The model uses something this server does not run."))
        self.problems = problems


def is_library_class(name: str) -> bool:
    return name.split(".")[0] in LIBRARY_ROOTS


def project_classes(files: dict[str, str]) -> list[dict[str, Any]]:
    """Every class of the project: where it is, what it is, its experiment settings.

    Files come in the order a Modelica tool shows them: each folder's ``package.mo`` first,
    then its classes as ``package.order`` lists them, then the others by name.
    """

    orders = {
        path.rpartition("/")[0]: [line.strip() for line in text.splitlines() if line.strip()]
        for path, text in files.items()
        if path.rpartition("/")[2] == "package.order"
    }

    def place(path: str) -> tuple:
        folder, _, name = path.rpartition("/")
        stem = name.removesuffix(".mo")
        order = orders.get(folder, [])
        return (
            folder,
            0 if name == "package.mo" else 1,
            order.index(stem) if stem in order else len(order),
            name,
        )

    found = []
    for path in sorted(files, key=place):
        text = files[path]
        for item in flatten(outline(text)):
            found.append(
                {
                    "name": item.name,
                    "short": item.short,
                    "restriction": item.restriction,
                    "comment": item.comment,
                    "partial": item.partial,
                    "file": path,
                    "line": item.line,
                    "experiment": experiment(text[item.start : item.end])
                    if not item.short_class
                    else {},
                    "simulable": item.restriction in ("model", "block", "class")
                    and not item.partial,
                }
            )
    return found


def experiment(text: str) -> dict[str, float]:
    """The class's ``experiment(StartTime, StopTime, Interval, Tolerance)`` annotation."""

    import re

    match = re.search(r"\bexperiment\s*\(([^()]*)\)", text)
    if not match:
        return {}
    found = {}
    for key, value in re.findall(
        r"(StartTime|StopTime|Interval|Tolerance)\s*=\s*([-+0-9.eE]+)", match.group(1)
    ):
        try:
            found[key] = float(value)
        except ValueError:
            continue
    return found


def _digest(files: dict[str, str], *extra: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode())
        digest.update(b"\0")
        digest.update(files[path].encode())
        digest.update(b"\0")
    for item in extra:
        digest.update(item.encode())
    return digest.hexdigest()


def summary_of(answer: JobAnswer, messages: list[dict[str, Any]]) -> str:
    errors = [m for m in messages if m["level"] == "error"]
    if answer.status == "timeout":
        return t("Stopped at its time limit.")
    if errors:
        return errors[0]["text"].splitlines()[0][:300]
    return ""


class Workbench:
    def __init__(
        self,
        projects: ProjectStore,
        runs: RunStore,
        executor: Executor,
        data_dir: Path,
        *,
        allow_external: bool = False,
        check_timeout: float = 120,
        run_timeout: float = 600,
        workers: int = 2,
        publish: Callable[[dict[str, Any]], None] | None = None,
        publish_study: Callable[[dict[str, Any], dict[str, int]], None] | None = None,
        batch: int = 10,
        blocks: Callable[[], dict[str, str]] | None = None,
    ):
        self.projects = projects
        self.runs = runs
        self.executor = executor
        self.data_dir = data_dir
        self.allow_external = allow_external
        self.check_timeout = check_timeout
        self.run_timeout = run_timeout
        self.publish = publish
        self.publish_study = publish_study
        self._studies_told: set[str] = set()
        # Optimizations going on: study id -> the event that stops it.
        self._optimizing: dict[str, threading.Event] = {}
        self._closing = False
        # How often an optimization looks whether its simulation has ended.
        self.poll_seconds = 0.5
        self.blocks = blocks
        self.queue = Dispatcher(runs, self._execute, workers=workers, batch=batch)
        # Runs with the runner now: run id -> (job id, the result file it is writing).
        self._running: dict[str, tuple[str, str]] = {}
        self._cancel: set[str] = set()
        self._announcing = threading.Lock()
        self._diagrams: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._library: LibraryIndex | None = LibraryIndex.load(self.library_path)
        self._library_building = False
        self.library_error = ""
        (data_dir / "runs").mkdir(parents=True, exist_ok=True)
        (data_dir / "studies").mkdir(parents=True, exist_ok=True)
        (data_dir / "library").mkdir(parents=True, exist_ok=True)

    # Shared helpers --------------------------------------------------------------------

    @property
    def library_path(self) -> Path:
        return self.data_dir / "library" / "index.json"

    def runner(self) -> dict[str, Any]:
        return self.executor.state()

    def _files(self, project_id: str) -> dict[str, str]:
        """The project's files and, beside them, the shared blocks' libraries (a project's own
        package of the same name wins)."""

        if self.projects.get(project_id) is None:
            raise KeyError(project_id)
        files = self.projects.files(project_id)
        shared = self.blocks() if self.blocks is not None else {}
        if shared:
            mine = {path.split("/")[0].removesuffix(".mo") for path in files}
            files = {
                **{
                    path: text
                    for path, text in shared.items()
                    if path.split("/")[0].removesuffix(".mo") not in mine
                },
                **files,
            }
        return files

    def check_policy(self, files: dict[str, str]) -> None:
        problems = []
        for path, text in files.items():
            for problem in policy(text, allow_external=self.allow_external):
                problems.append(
                    {
                        "level": "error",
                        "file": path,
                        "own": True,
                        "column": problem["column"],
                        "line": problem["line"],
                        "end_line": None,
                        "end_column": None,
                        "text": t(problem["text"]),
                    }
                )
        if problems:
            raise PolicyError(problems)

    def _model(self, files: dict[str, str], model: str) -> None:
        if is_library_class(model):
            return
        if not any(find(text, model) for text in files.values()):
            raise WorkbenchError(t("{model} is not a class of this project.", model=model))

    def _run_job(
        self, job: dict[str, Any], files: dict[str, str], timeout: float, extra=None
    ) -> JobAnswer:
        try:
            return self.executor.run(job, files, timeout=timeout, extra=extra)
        except RunnerUnavailable as exc:
            raise RunnerDown(
                t("The Modelica runner is not available: {reason}", reason=t(str(exc)))
            ) from exc

    # Check and diagram -----------------------------------------------------------------

    def check(self, project_id: str, model: str) -> dict[str, Any]:
        files = self._files(project_id)
        self._model(files, model)
        try:
            self.check_policy(files)
        except PolicyError as exc:
            return {
                "ok": False,
                "model": model,
                "messages": exc.problems,
                "summary": str(exc),
                "seconds": 0,
            }
        answer = self._run_job({"kind": "check", "model": model}, files, self.check_timeout)
        try:
            messages = answer.messages()
            ok = answer.status == "done" and "completed successfully" in answer.text("check")
            summary = answer.text("check").strip().splitlines()
            return {
                "ok": ok,
                "model": model,
                "messages": messages,
                "summary": " ".join(summary[1:])
                if ok and len(summary) > 1
                else summary_of(answer, messages),
                "seconds": answer.seconds,
            }
        finally:
            answer.close()

    def diagram(
        self, project_id: str | None, model: str, *, source: bool = False
    ) -> dict[str, Any]:
        """The class's diagram, icon, parameters and documentation (library classes too)."""

        library = is_library_class(model)
        files = {} if library or project_id is None else self._files(project_id)
        if not library:
            self._model(files, model)
            self.check_policy(files)
        key = _digest(files, model, str(source), self.runner().get("omc", ""))
        cached_file = (
            self.data_dir / "library" / f"{hashlib.sha256(model.encode()).hexdigest()[:24]}.json"
        )
        with self._lock:
            if key in self._diagrams:
                self._diagrams.move_to_end(key)
                return self._diagrams[key]
        if library and cached_file.is_file():
            try:
                found = json.loads(cached_file.read_text(encoding="utf-8"))
                if found.get("name") == model and (found.get("source") is not None or not source):
                    return self._remember(key, found)
            except (OSError, json.JSONDecodeError):
                pass
        answer = self._run_job(
            {"kind": "instance", "model": model, "source": source}, files, self.check_timeout
        )
        try:
            instance_file = answer.file("instance.json")
            messages = answer.messages()
            if instance_file is None:
                raise WorkbenchError(
                    summary_of(answer, messages) or t("omc could not read {model}.", model=model)
                )
            try:
                instance = json.loads(instance_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise WorkbenchError(
                    summary_of(answer, messages) or t("omc could not read {model}.", model=model)
                ) from exc
            found = reduce(instance) if isinstance(instance, dict) else {}
            if not found.get("name"):
                raise WorkbenchError(
                    summary_of(answer, messages) or t("omc could not read {model}.", model=model)
                )
            source_file = answer.file("source.mo")
            found["source"] = (
                source_file.read_text(encoding="utf-8", errors="replace") if source_file else None
            )
            found["messages"] = [m for m in messages if m["level"] != "info"]
        finally:
            answer.close()
        if library:
            try:
                write_json(cached_file, found)
            except OSError:
                pass
        return self._remember(key, found)

    def _remember(self, key: str, found: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._diagrams[key] = found
            while len(self._diagrams) > DIAGRAM_CACHE:
                self._diagrams.popitem(last=False)
        return found

    # The library -------------------------------------------------------------------------

    def library(self) -> LibraryIndex | None:
        return self._library

    def library_state(self) -> dict[str, Any]:
        return {
            "ready": self._library is not None,
            "classes": len(self._library) if self._library else 0,
            "building": self._library_building,
            "error": self.library_error,
        }

    def ensure_library(self, *, wait: bool = False) -> None:
        """Build the library index once per runner version (in the background)."""

        state = self.runner()
        version = f"{state.get('omc', '')} {json.dumps(state.get('libraries', {}), sort_keys=True)}"
        if not state.get("available"):
            return
        if self._library is not None and self._library.version == version:
            return
        with self._lock:
            if self._library_building:
                return
            self._library_building = True

        def build() -> None:
            try:
                answer = self.executor.run(
                    {"kind": "library_index", "model": "Modelica"}, {}, timeout=600
                )
                try:
                    index_file = answer.file("index-Modelica.tsv")
                    if index_file is None:
                        self.library_error = summary_of(answer, answer.messages()) or t(
                            "omc did not list the library."
                        )
                        return
                    classes = parse_index(index_file.read_text(encoding="utf-8", errors="replace"))
                finally:
                    answer.close()
                index = LibraryIndex(classes, version)
                index.save(self.library_path)
                self._library = index
                self.library_error = ""
            except Exception as exc:  # noqa: BLE001 - the browser shows the reason
                LOGGER.warning("Library index not built: %s", exc)
                self.library_error = str(exc)
            finally:
                self._library_building = False

        if wait:
            build()
        else:
            threading.Thread(target=build, name="modelcraft-library", daemon=True).start()

    # Runs --------------------------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        return self.data_dir / "runs" / run_id

    def start(
        self,
        project_id: str,
        model: str,
        kind: str,
        options: dict[str, Any],
        *,
        by: str,
        label: str = "",
        extra: dict[str, bytes] | None = None,
        compare: dict[str, Any] | None = None,
        replace: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Queue one simulation (in the model's "Quick simulations" study) or one FMU export;
        ``replace``: files the run takes in place of the project's (an earlier version)."""

        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        files = {**self._files(project_id), **(replace or {})}
        self._ready(files, model)
        study = self.runs.quick_study(project, model, by=by) if kind == "simulate" else None
        run = self.runs.create(
            project=project,
            model=model,
            kind=kind,
            options=options,
            by=by,
            label=label,
            study_id=study["id"] if study else "",
            priority=PRIORITY_SINGLE,
        )
        folder = self.run_dir(run["id"])
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "files.json", files)
        for name, content in (extra or {}).items():
            (folder / name).write_bytes(content)
        if compare:
            write_json(folder / "compare.json", compare)
        self.queue.wake()
        # Off the request: a slow PlantCraft never holds the person's Run button.
        threading.Thread(target=self._announce, args=(run,), daemon=True).start()
        return run

    # Compiled models (2026-11-01) ---------------------------------------------------------

    def compile_files(self, project_id: str) -> dict[str, str]:
        """The files a compilation of the project's models takes (with the shared blocks)."""

        return self._files(project_id)

    def source_of(
        self,
        project_id: str,
        model: str,
        replace: dict[str, str] | None = None,
        *,
        files: dict[str, str] | None = None,
    ) -> str:
        """What a compilation of the model depends on: the project's files with the shared
        blocks' libraries beside them, and the class. A change to any of them makes a build out
        of date; ``replace``: files in place of the project's (an earlier version); ``files``:
        the project's, when the caller has read them already."""

        given = files if files is not None else self._files(project_id)
        return _digest({**given, **(replace or {})}, model)

    def compile(self, project_id: str, model: str, *, by: str) -> dict[str, Any]:
        """Compile the model as it is now into an FMU (FMI 2.0, co-simulation: what Analytics
        runs), kept with the model. The last ``KEEP_BUILDS`` compilations stay, older ones go."""

        run = self.start(
            project_id,
            model,
            "fmu",
            {
                "version": "2.0",
                "type": "cs",
                "compile": True,
                "source": self.source_of(project_id, model),
            },
            by=by,
            label=t("Compiled"),
        )
        for old in self.builds(project_id, model)[KEEP_BUILDS:]:
            if old["status"] not in ("queued", "running"):
                self.delete_run(old["id"])
        return run

    def builds(self, project_id: str, model: str) -> list[dict[str, Any]]:
        """The model's compilations, newest first (FMU exports made with Compile)."""

        found = self.runs.list(project_id=project_id, model=model, kind="fmu", limit=200)
        return [run for run in found if (run.get("options") or {}).get("compile")]

    def build_state(
        self, builds: list[dict[str, Any]], source: str
    ) -> tuple[str, dict[str, Any] | None]:
        """Whether a model is compiled, and its compiled version (the newest that built):
        ``compiling`` (in the queue or running), ``compiled`` (built from the files as they are
        now), ``failed`` (the last compilation failed), ``out_of_date`` (built, then changed) or
        ``not_compiled``."""

        latest = builds[0] if builds else None
        built = next((run for run in builds if run["status"] == "done"), None)
        if latest and latest["status"] in ("queued", "running"):
            return "compiling", built
        if built and built["options"].get("source") == source:
            return "compiled", built
        if latest and latest["status"] == "failed":
            return "failed", built
        if built:
            return "out_of_date", built
        return "not_compiled", None

    def start_study(
        self,
        project_id: str,
        model: str,
        *,
        name: str,
        description: str,
        spec: dict[str, Any],
        by: str,
        max_runs: int,
        extra: dict[str, bytes] | None = None,
        compare: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a study and queue its simulations: one per combination of the swept values."""

        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        files = self._files(project_id)
        self._ready(files, model)
        variants = studies.combinations(spec.get("sweep") or [])
        if len(variants) > max_runs:
            raise WorkbenchError(
                t(
                    "The study would make {count} simulations; the limit is {limit}.",
                    count=len(variants),
                    limit=max_runs,
                )
            )
        study = self.runs.create_study(
            project=project,
            model=model,
            name=name,
            kind="sweep" if spec.get("sweep") else "single",
            spec=spec,
            by=by,
            description=description,
        )
        folder = self.study_dir(study["id"])
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "files.json", files)
        for file_name, content in (extra or {}).items():
            (folder / file_name).write_bytes(content)
        if compare:
            write_json(folder / "compare.json", compare)
        self.runs.create_many(
            project=project,
            model=model,
            kind="simulate",
            options=spec["options"],
            by=by,
            labels=[_variant_label(variant) for variant in variants],
            study_id=study["id"],
            variants=variants,
            priority=PRIORITY_SWEEP if len(variants) > 1 else PRIORITY_SINGLE,
        )
        self.queue.wake()
        return study

    def start_optimization(
        self,
        project_id: str,
        model: str,
        *,
        name: str,
        description: str,
        spec: dict[str, Any],
        by: str,
        max_runs: int,
    ) -> dict[str, Any]:
        """Create an optimization study and start it: one simulation at a time, each point
        chosen from the results of those before (``runs/optimize.py``)."""

        project = self.projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        files = self._files(project_id)
        self._ready(files, model)
        optimize.check(spec["optimization"])
        if spec["optimization"]["max_simulations"] > max_runs:
            raise WorkbenchError(
                t(
                    "The study would make {count} simulations; the limit is {limit}.",
                    count=spec["optimization"]["max_simulations"],
                    limit=max_runs,
                )
            )
        study = self.runs.create_study(
            project=project,
            model=model,
            name=name,
            kind="optimization",
            spec=spec,
            by=by,
            description=description,
        )
        folder = self.study_dir(study["id"])
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "files.json", files)
        self._save_optimization(study["id"], {"status": "running", "evaluations": []})
        self._start_optimizer(study)
        return study

    def optimization(self, study_id: str) -> dict[str, Any] | None:
        """How an optimization study goes: every simulation's values and objective, the best."""

        path = self.study_dir(study_id) / "optimization.json"
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if found.get("status") == "running" and study_id not in self._optimizing:
            found["status"] = "waiting"
        return found

    def optimizing(self, study_id: str) -> bool:
        return study_id in self._optimizing

    def resume_optimizations(self) -> int:
        """Optimizations a restart interrupted start again: the simulations they already have
        answer at once (the optimizer asks for the same points), then they go on."""

        resumed = 0
        for study in self.runs.studies():
            if study.get("kind") != "optimization" or study["id"] in self._optimizing:
                continue
            if (self.optimization(study["id"]) or {}).get("status") in ("running", "waiting"):
                self._start_optimizer(self.runs.study(study["id"]) or study)
                resumed += 1
        return resumed

    def _start_optimizer(self, study: dict[str, Any]) -> None:
        with self._lock:
            if study["id"] in self._optimizing:
                return
            self._optimizing[study["id"]] = threading.Event()
        threading.Thread(
            target=self._optimize, args=(study,), name="modelcraft-optimize", daemon=True
        ).start()

    def _save_optimization(self, study_id: str, state: dict[str, Any]) -> None:
        path = self.study_dir(study_id) / "optimization.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, state)

    def _optimize(self, study: dict[str, Any]) -> None:
        """The optimizer's thread: it asks for one simulation at a time and waits for it."""

        study_id = study["id"]
        stop = self._optimizing[study_id]
        spec = study["spec"]
        started = (self.optimization(study_id) or {}).get("started_at") or _now()

        def save(state: dict[str, Any], status: str = "running") -> None:
            self._save_optimization(
                study_id,
                {
                    **state,
                    "status": status,
                    "method": spec["optimization"]["method"],
                    "started_at": started,
                    **({"finished_at": _now()} if status != "running" else {}),
                },
            )

        def evaluate(values: dict[str, float]) -> dict[str, Any]:
            if stop.is_set():
                raise optimize.Stop
            run = self._optimization_run(study, values)
            while run["status"] in ("queued", "running"):
                if stop.wait(self.poll_seconds):
                    raise optimize.Stop
                run = self.runs.get(run["id"]) or {**run, "status": "cancelled"}
            if run["status"] == "cancelled":
                raise optimize.Stop
            indicators = (
                (run.get("result") or {}).get("indicators") if run["status"] == "done" else None
            )
            return {"run_id": run["id"], "indicators": indicators}

        try:
            state = optimize.run(spec["optimization"], evaluate, on_step=save)
            if self._closing:
                # Stopped by the server shutting down: it goes on at the next start.
                return
            save(state, state["status"])
        except Exception as exc:  # noqa: BLE001 - an optimization always ends with a status
            LOGGER.exception("Optimization %s failed", study_id)
            found = self.optimization(study_id) or {}
            save({**found, "message": str(exc)[:300]}, "failed")
        finally:
            with self._lock:
                self._optimizing.pop(study_id, None)
            if not self._closing:
                self._study_ended({"study_id": study_id})

    def _optimization_run(self, study: dict[str, Any], values: dict[str, float]) -> dict[str, Any]:
        """The study's simulation with these values: the one it already has (an optimization
        started again after a restart), else a new one in the queue."""

        for run in self.runs.list(study_id=study["id"], limit=5000):
            if run.get("variant") == values and run["status"] != "cancelled":
                return run
        project = self.projects.get(study["project_id"])
        if project is None:
            raise WorkbenchError(t("The project of this study was deleted."))
        created = self.runs.create_many(
            project=project,
            model=study["model"],
            kind="simulate",
            options=study["spec"]["options"],
            by=study.get("created_by") or "",
            labels=[_variant_label(values)],
            study_id=study["id"],
            variants=[values],
            priority=PRIORITY_SWEEP,
        )
        self.queue.wake()
        return created[0]

    def _ready(self, files: dict[str, str], model: str) -> None:
        self._model(files, model)
        self.check_policy(files)
        if not self.runner().get("available"):
            raise RunnerDown(
                t(
                    "The Modelica runner is not available: {reason}",
                    reason=t(self.runner().get("reason", "")),
                )
            )

    def study_dir(self, study_id: str) -> Path:
        return self.data_dir / "studies" / study_id

    def _run_folder_file(self, run: dict[str, Any], name: str) -> Path | None:
        """A file of the run, kept in its folder or, for a study's runs, in the study's."""

        folders = [self.run_dir(run["id"])]
        if run.get("study_id"):
            folders.append(self.study_dir(run["study_id"]))
        return next((folder / name for folder in folders if (folder / name).is_file()), None)

    # The queue's work ------------------------------------------------------------------------

    def _execute(self, batch: list[dict[str, Any]]) -> None:
        """Run what the queue handed over: one run, or several runs of one sweep."""

        try:
            if len(batch) == 1 and not batch[0].get("variant"):
                self._execute_one(batch[0])
            else:
                self._execute_sweep(batch)
        finally:
            # Whatever happened, no run stays "running" with nobody on it.
            for run in batch:
                self._running.pop(run["id"], None)
                self._cancel.discard(run["id"])
                current = self.runs.get(run["id"])
                if current and current["status"] == "running":
                    self._finish(
                        current,
                        "failed",
                        [
                            {
                                "level": "error",
                                "text": t("Unexpected error; see the server log."),
                                "file": None,
                            }
                        ],
                        {},
                        t("Unexpected error; see the server log."),
                        None,
                    )

    def _job_inputs(self, run: dict[str, Any]) -> tuple[dict[str, str], dict[str, bytes]]:
        files_path = self._run_folder_file(run, "files.json")
        files = json.loads(files_path.read_text(encoding="utf-8")) if files_path else {}
        extra = {}
        inputs = self._run_folder_file(run, "inputs.csv")
        if inputs is not None:
            extra["inputs.csv"] = inputs.read_bytes()
        return files, extra

    def _execute_one(self, run: dict[str, Any]) -> None:
        run_id = run["id"]
        job_id = new_job_id()
        # Known as running here before the store says so, so a cancel always finds its job.
        self._running[run_id] = (job_id, "model_res.csv")
        self.runs.started([run_id], job_id)
        self._announce(self.runs.get(run_id) or run)
        options = dict(run["options"])
        plant = options.pop("plant", None)
        options.pop("compare", None)
        # What the model page reads of a compilation, not the runner's.
        options.pop("compile", None)
        options.pop("source", None)
        files, extra = self._job_inputs(run)
        if "inputs.csv" in extra:
            options["inputs_file"] = "inputs.csv"
        shapes = options.pop("inputs", None) or {}
        if shapes:
            extra["inputs.csv"] = studies.input_csv(shapes, run.get("variant") or {}, options)
            options["inputs_file"] = "inputs.csv"
        overrides = {**(options.get("overrides") or {}), **(run.get("variant") or {})}
        if overrides:
            options["overrides"] = overrides
        compute = options.pop("compute", None)
        job = {"kind": run["kind"], "model": run["model"], "options": options}
        if compute:
            job["compute"] = compute
        result: dict[str, Any] = {}
        messages: list[dict[str, Any]] = []
        status = "failed"
        seconds = None
        try:
            answer = self.executor.run(
                job, files, timeout=self._timeout(run), extra=extra, job_id=job_id
            )
        except RunnerUnavailable as exc:
            messages = [{"level": "error", "text": t(str(exc)), "file": None}]
            summary = t(str(exc))
        except Exception as exc:  # noqa: BLE001 - a run always ends with a status
            LOGGER.exception("Run %s failed", run_id)
            messages = [
                {"level": "error", "text": t("Unexpected error; see the server log."), "file": None}
            ]
            summary = str(exc)[:300]
        else:
            try:
                seconds = answer.seconds
                messages = answer.messages()
                folder = self.run_dir(run_id)
                if answer.status == "cancelled":
                    status = "cancelled"
                elif run["kind"] == "simulate":
                    csv_file = answer.file("model_res.csv")
                    if csv_file is not None and answer.text("simulate").strip():
                        result = results.store(csv_file, answer.file("model_init.xml"), folder)
                        self._measure(run, result, folder)
                        if plant:
                            result["plant"] = plant
                        status = "done"
                else:
                    fmu = answer.file("model.fmu")
                    if fmu is not None:
                        result = self._keep_fmu(fmu, folder, run["model"], options)
                        status = "done"
                summary = (
                    t("Cancelled.")
                    if status == "cancelled"
                    else summary_of(answer, messages)
                    if status == "failed"
                    else self._summary(run["kind"], result)
                )
                if status == "failed" and not summary:
                    summary = t("omc did not finish the simulation; see the messages.")
            finally:
                answer.close()
        self._finish(run, status, messages, result, summary, seconds)

    def _execute_sweep(self, batch: list[dict[str, Any]]) -> None:
        """Several runs of one study: the model is built once, each variant simulated in turn."""

        first = batch[0]
        job_id = new_job_id()
        ids = [run["id"] for run in batch]
        for index, run in enumerate(batch):
            self._running[run["id"]] = (job_id, f"res_{index}.csv")
        self.runs.started(ids, job_id)
        options = dict(first["options"])
        options.pop("plant", None)
        options.pop("compare", None)
        files, extra = self._job_inputs(first)
        if "inputs.csv" in extra:
            options["inputs_file"] = "inputs.csv"
        shapes = options.pop("inputs", None) or {}
        variants = [run.get("variant") or {} for run in batch]
        compute = options.pop("compute", None)
        job: dict[str, Any] = {"kind": "sweep", "model": first["model"], "options": options}
        if compute:
            job["compute"] = compute
        if shapes:
            # The study's own inputs (round 9 M6): a CSV for each variant, its swept values in it.
            job["inputs_files"] = []
            for index, variant in enumerate(variants):
                name = f"inputs_{index}.csv"
                extra[name] = studies.input_csv(shapes, variant, options)
                job["inputs_files"].append(name)
            variants = [
                {key: value for key, value in variant.items() if key not in shapes}
                for variant in variants
            ]
        job["variants"] = variants
        try:
            answer = self.executor.run(
                job,
                files,
                timeout=min(86_400.0, self._timeout(first) * len(batch) + 60),
                extra=extra,
                job_id=job_id,
            )
        except RunnerUnavailable as exc:
            message = [{"level": "error", "text": t(str(exc)), "file": None}]
            for run in batch:
                self._finish(run, "failed", message, {}, t(str(exc)), None)
            return
        try:
            common = [m for m in answer.messages() if m["level"] != "info"]
            per_run = answer.seconds / max(1, len(batch))
            timings = answer.variant_seconds
            for index, run in enumerate(batch):
                # Each variant's own time when the runner measured it, else the batch's average.
                seconds = timings[index] if index < len(timings) and timings[index] else per_run
                code = answer.text(f"variant-{index}").strip()
                csv_file = answer.file(f"res_{index}.csv")
                log = answer.file(f"log_{index}.txt")
                messages = common + (
                    simulation_log(log.read_text(encoding="utf-8", errors="replace")) if log else []
                )
                if code == "0" and csv_file is not None:
                    folder = self.run_dir(run["id"])
                    result = results.store(csv_file, answer.file("model_init.xml"), folder)
                    self._measure(run, result, folder)
                    self._finish(
                        run, "done", messages, result, self._summary("simulate", result), seconds
                    )
                elif run["id"] in self._cancel or (
                    answer.status == "cancelled" and run["id"] in self._cancel_targets(batch)
                ):
                    self._finish(run, "cancelled", messages, {}, t("Cancelled."), None)
                elif answer.status == "cancelled" and not code:
                    # Stopped with the rest of its batch: it waits in the queue again.
                    self.runs.requeue(run["id"])
                else:
                    summary = (
                        summary_of(answer, messages)
                        or (messages[-1]["text"].splitlines()[0][:300] if messages else "")
                        or t("omc did not finish the simulation; see the messages.")
                    )
                    self._finish(run, "failed", messages, {}, summary, None)
        finally:
            answer.close()

    def _cancel_targets(self, batch: list[dict[str, Any]]) -> set[str]:
        """Runs of a cancelled job that were cancelled themselves (or with their study)."""

        found = set()
        for run in batch:
            current = self.runs.get(run["id"])
            if run["id"] in self._cancel or (current and current["status"] == "cancelled"):
                found.add(run["id"])
        return found

    def _timeout(self, run: dict[str, Any]) -> float:
        limit = (run.get("options") or {}).get("time_limit")
        return float(limit) if isinstance(limit, (int, float)) and limit > 0 else self.run_timeout

    def _measure(self, run: dict[str, Any], result: dict[str, Any], folder: Path) -> None:
        """The study's indicators of this simulation, kept with its result."""

        study = self.runs.study(run.get("study_id") or "")
        wanted = list(((study or {}).get("spec") or {}).get("indicators") or [])
        if wanted:
            result["indicators"] = studies.indicators(folder, wanted)

    def _finish(
        self,
        run: dict[str, Any],
        status: str,
        messages: list[dict[str, Any]],
        result: dict[str, Any],
        summary: str,
        seconds: float | None,
    ) -> None:
        finished = self.runs.finished(
            run["id"],
            status=status,
            messages=messages,
            result=result,
            summary=summary,
            seconds=seconds,
        )
        self._running.pop(run["id"], None)
        self._announce(finished)
        self._study_ended(run)

    def _announce(self, run: dict[str, Any]) -> None:
        """The run on the suite's Queue and Executions: when it is queued, starts and ends
        (docs/quick-access.md). A sweep's simulations are not reported one by one."""

        if self.publish is None or run.get("priority", PRIORITY_SINGLE) == PRIORITY_SWEEP:
            return
        # One at a time and always the run as it is now: a late "queued" never follows "done".
        with self._announcing:
            try:
                self.publish(self.runs.get(run["id"]) or run)
            except Exception as exc:  # noqa: BLE001 - publishing never fails a run
                LOGGER.warning("Run %s not published: %s", run["id"], exc)

    def _study_ended(self, run: dict[str, Any]) -> None:
        """Once the last simulation of a study (not a quick one) ends, ``study.finished``."""

        study_id = run.get("study_id") or ""
        if self.publish_study is None or not study_id:
            return
        counts = self.runs.study_counts(study_id)
        if counts["queued"] or counts["running"] or study_id in self._optimizing:
            return
        study = self.runs.study(study_id) or {}
        with self._lock:
            if study.get("kind") == "quick" or study_id in self._studies_told:
                return
            self._studies_told.add(study_id)
        try:
            self.publish_study(study, counts)
        except Exception as exc:  # noqa: BLE001 - publishing never fails a run
            LOGGER.warning("Study %s not published: %s", study_id, exc)

    # Following and stopping runs -------------------------------------------------------------

    def progress(self, run: dict[str, Any]) -> float | None:
        """How far a running simulation is, 0 to 1, from the last time its results file holds."""

        if run.get("status") != "running" or run.get("kind") != "simulate":
            return None
        found = self._running.get(run["id"])
        if not found:
            return None
        path = self.executor.output(*found)
        options = run.get("options") or {}
        start, stop = float(options.get("start", 0.0)), float(options.get("stop", 1.0))
        if path is None or stop <= start:
            return 0.0
        moment = _last_time(path)
        if moment is None:
            return 0.0
        return max(0.0, min(1.0, (moment - start) / (stop - start)))

    def cancel(self, run_id: str) -> bool:
        """Cancel a waiting run, or stop a running one (its whole runner job)."""

        if self.runs.cancel_queued(run_id=run_id):
            return True
        found = self._running.get(run_id)
        if found is None:
            return False
        self._cancel.add(run_id)
        self.executor.cancel(found[0])
        return True

    def cancel_study(self, study_id: str) -> int:
        stop = self._optimizing.get(study_id)
        if stop is not None:
            stop.set()
        cancelled = self.runs.cancel_queued(study_id=study_id)
        jobs = set()
        for run in self.runs.list(study_id=study_id, statuses=("running",), limit=5000):
            found = self._running.get(run["id"])
            if found is not None:
                self._cancel.add(run["id"])
                jobs.add(found[0])
                cancelled += 1
        for job_id in jobs:
            self.executor.cancel(job_id)
        return cancelled

    def queue_state(self) -> dict[str, Any]:
        counts = self.runs.counts()
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "workers": self.queue.workers,
            "busy": self.queue.busy(),
        }

    @staticmethod
    def _summary(kind: str, result: dict[str, Any]) -> str:
        if kind == "simulate":
            return t(
                "{variables} variables, {rows} points.",
                variables=result.get("variables", 0),
                rows=result.get("rows", 0),
            )
        return t(
            "FMI {version} {type}, {size} kB.",
            version=result.get("fmi_version", ""),
            type=result.get("fmu_type", ""),
            size=round(result.get("size", 0) / 1024),
        )

    @staticmethod
    def _keep_fmu(fmu: Path, folder: Path, model: str, options: dict[str, Any]) -> dict[str, Any]:
        target = folder / f"{model}.fmu"
        shutil.copyfile(fmu, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        described: dict[str, Any] = {}
        try:
            with zipfile.ZipFile(target) as archive:
                root = ElementTree.fromstring(archive.read("modelDescription.xml"))
                platforms = sorted(
                    {
                        name.split("/")[1]
                        for name in archive.namelist()
                        if name.startswith("binaries/") and name.count("/") >= 2
                    }
                )
            variables = [
                item
                for item in root.iter()
                if item.tag
                in (
                    "ScalarVariable",
                    "Float64",
                    "Float32",
                    "Int32",
                    "Boolean",
                    "Int64",
                    "String",
                    "Enumeration",
                )
            ]
            described = {
                "fmi_version": root.get("fmiVersion", ""),
                "guid": root.get("guid") or root.get("instantiationToken") or "",
                "variables": len(variables),
                "inputs": sorted(
                    v.get("name", "") for v in variables if v.get("causality") == "input"
                )[:200],
                "outputs": sorted(
                    v.get("name", "") for v in variables if v.get("causality") == "output"
                )[:200],
                "parameters": sum(1 for v in variables if v.get("causality") == "parameter"),
                "platforms": platforms,
            }
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
            described = {"fmi_version": options.get("version", "")}
        return {
            **described,
            "file": target.name,
            "size": target.stat().st_size,
            "sha256": digest,
            "fmu_type": options.get("type", "cs"),
        }

    def fmu_path(self, run: dict[str, Any]) -> Path | None:
        name = (run.get("result") or {}).get("file")
        if run.get("kind") != "fmu" or not name:
            return None
        path = self.run_dir(run["id"]) / name
        return path if path.is_file() else None

    def run_files(self, run_id: str) -> dict[str, str]:
        run = self.runs.get(run_id)
        path = self._run_folder_file(run, "files.json") if run else None
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def compare(self, run_id: str) -> dict[str, Any]:
        run = self.runs.get(run_id)
        path = self._run_folder_file(run, "compare.json") if run else None
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def delete_run(self, run_id: str) -> None:
        self.runs.delete(run_id)
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def delete_study(self, study_id: str) -> None:
        for run_id in self.runs.delete_study(study_id):
            shutil.rmtree(self.run_dir(run_id), ignore_errors=True)
        shutil.rmtree(self.study_dir(study_id), ignore_errors=True)

    def shutdown(self) -> None:
        self._closing = True
        for stop in list(self._optimizing.values()):
            stop.set()
        self.queue.shutdown()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _variant_label(variant: dict[str, Any]) -> str:
    def show(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return f"{value:g}" if isinstance(value, float) else str(value)

    return ", ".join(
        f"{name.lstrip('@').rpartition('.')[2] or name}={show(value)}"
        for name, value in variant.items()
    )[:120]


def _last_time(path: Path) -> float | None:
    """The time of the last complete row of a results CSV being written."""

    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 8192))
            tail = handle.read().decode("utf-8", "replace")
    except OSError:
        return None
    lines = tail.split("\n")[:-1]  # the last piece may be half written
    for line in reversed(lines):
        first = line.split(",", 1)[0].strip().strip('"')
        try:
            return float(first)
        except ValueError:
            continue
    return None
