"""The Modelica runner: runs OpenModelica (``omc``) on the jobs PlantCraft Models hands it.

This file is the whole program of the ``modelcraft-runner`` container and uses the Python
standard library only (Python 3.10 or later: the OpenModelica image is Ubuntu 22.04). The
runner is the suite's sandbox for Modelica: compiling and simulating a model runs code the
person wrote, so the runner container has no network at all, no app key, no access to
PlantCraft Models' data, a read-only root filesystem and CPU, memory, process and time limits.

Jobs travel through a shared folder (``--jobs``)::

    queue/<id>/job.json + files/   written by PlantCraft Models, then renamed into queue/
    work/<id>/                     claimed by the runner (an atomic rename)
    done/<id>/result.json + out/   the answer, renamed into done/ when complete
    runner.json                    the runner's heartbeat: versions, libraries, the time

This is also the protocol of the suite's compute workers (PlantCraft docs/compute.md): on a
worker, the gateway puts Models' tasks in the runner's folder and sends its answers back, and the
heartbeat names the app and the runner's version the tasks ask for (``runner-<version>``).

The runner writes every ``omc`` script itself from the job's fields, each one checked here
(class names, numbers, a fixed list of solvers): a job never carries a script.

Run: ``python3 runner.py --jobs /jobs`` (``--once`` answers the queued jobs and stops).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

RUNNER_VERSION = "3"
KINDS = ("check", "simulate", "sweep", "fmu", "instance", "library_index")
METHODS = ("dassl", "ida", "cvode", "euler", "heun", "rungekutta", "impeuler", "trapezoid")
CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A parameter to override: a component path with optional indices (``PI.k``, ``a[2].b``).
OVERRIDE_NAME = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\[[0-9]{1,6}\])?(\.[A-Za-z_][A-Za-z0-9_]*(\[[0-9]{1,6}\])?)*$"
)
# What a study may vary besides the model's own values (round 9 M7): the simulation's settings,
# named with an ``@`` so they never meet a parameter's name.
SETTINGS = ("@tolerance", "@method", "@stop", "@intervals")
FILE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,120}$")
NUMBER = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")
LIBRARIES = ("Modelica",)
LOG_LIMIT = 200_000
# A sweep: the model is built once, then its program runs once per variant.
MAX_VARIANTS = 100
# What a job hands back besides its step answers.
KEEP = re.compile(
    r"^(model_res\.csv|model_init\.xml|model\.fmu|instance\.json|source\.mo|index-[A-Za-z]+\.tsv"
    r"|res_[0-9]{1,3}\.csv|log_[0-9]{1,3}\.txt)$"
)
# A job whose folder holds this file is stopped (the person cancelled it).
CANCEL = "cancel"
# A sweep's built model kept for the next sweep of the same files and settings (an optimization
# asks for one simulation at a time; a study's batches follow each other): the program and the
# files it reads when it runs, and the answers of the steps that built it.
BUILT = re.compile(r"^(model|model_init\.xml|model_info\.json|model_[A-Za-z0-9_]+\.bin)$")
BUILD_STEPS = re.compile(r"^(load-[A-Za-z]+|file-[0-9]+|check|build)\.(ok|err)$")
CACHE_ENTRIES = 32


class JobError(ValueError):
    """A job whose fields the runner refuses (never run)."""


# Checking a job ----------------------------------------------------------------------------


def write_json(path: Path, value: object) -> None:
    """``value`` as JSON in ``path``, whole or not at all: the standard library's version of
    ``plantcraft_sdk.files.write_json`` (this runner imports nothing else)."""

    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.partial")
    try:
        with open(temporary, "x", encoding="utf-8") as file:
            file.write(json.dumps(value))
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def class_name(value: object) -> str:
    if not isinstance(value, str) or len(value) > 400 or not CLASS_NAME.match(value):
        raise JobError("not a Modelica class name")
    return value


def number(value: object, *, low: float | None = None, high: float | None = None) -> str:
    """A finite number written for omc (never anything else)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JobError("not a number")
    number_value = float(value)
    if number_value != number_value or number_value in (float("inf"), float("-inf")):
        raise JobError("not a finite number")
    if low is not None and number_value < low or high is not None and number_value > high:
        raise JobError("number out of range")
    text = repr(number_value)
    if not NUMBER.match(text):
        raise JobError("not a number")
    return text


def override_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return number(value)


def override_pairs(overrides: object) -> str:
    """``name=value,...`` for omc's ``-override`` from checked names and numbers."""

    if overrides is None:
        return ""
    if not isinstance(overrides, dict) or len(overrides) > 500:
        raise JobError("bad overrides")
    pairs = []
    for name, value in overrides.items():
        if not isinstance(name, str) or not OVERRIDE_NAME.match(name):
            raise JobError("bad override name")
        pairs.append(f"{name}={override_value(value)}")
    return ",".join(pairs)


def variant_flags(variant: object, options: dict) -> tuple[str | None, list[str], dict]:
    """A sweep's variant split into its integrator (``@method``), the experiment's own
    overrides (``stopTime``, ``stepSize``, ``tolerance``) and the model's values."""

    if not isinstance(variant, dict):
        raise JobError("bad variant")
    values = {name: value for name, value in variant.items() if name not in SETTINGS}
    method = variant.get("@method")
    if method is not None and method not in METHODS:
        raise JobError("unknown solver")
    experiment = []
    if "@tolerance" in variant:
        experiment.append(f"tolerance={number(variant['@tolerance'], low=1e-14, high=0.1)}")
    if "@stop" in variant or "@intervals" in variant:
        start = float(number(options.get("start", 0.0), low=-1e12, high=1e12))
        stop = float(number(variant.get("@stop", options.get("stop", 1.0)), low=-1e12, high=1e12))
        if stop <= start:
            raise JobError("the stop time must come after the start time")
        intervals = float(
            number(variant.get("@intervals", options.get("intervals", 500)), low=1, high=200_000)
        )
        experiment.append(f"stopTime={number(stop)}")
        experiment.append(f"stepSize={number((stop - start) / int(intervals))}")
    return method, experiment, values


def simulation_settings(job: dict, job_dir: Path) -> tuple[str, str, int, str, str, list[str]]:
    """(start, stop, intervals, tolerance, solver, flags) of a simulation, each one checked."""

    options = job.get("options") or {}
    start = number(options.get("start", 0.0), low=-1e12, high=1e12)
    stop = number(options.get("stop", 1.0), low=-1e12, high=1e12)
    if float(stop) <= float(start):
        raise JobError("the stop time must come after the start time")
    intervals = int(float(number(options.get("intervals", 500), low=1, high=200_000)))
    tolerance = number(options.get("tolerance", 1e-6), low=1e-14, high=0.1)
    method = options.get("method", "dassl")
    if method not in METHODS:
        raise JobError("unknown solver")
    flags = []
    inputs = options.get("inputs_file")
    if inputs:
        if not isinstance(inputs, str) or not FILE_NAME.match(inputs):
            raise JobError("bad inputs file")
        if not (job_dir / inputs).is_file():
            raise JobError("the inputs file is missing")
        flags.append(f"-csvInput={job_dir / inputs}")
    return start, stop, intervals, tolerance, method, flags


def project_files(job_dir: Path) -> list[str]:
    """The files to load: every top-level ``X.mo`` and every ``X/package.mo`` (loading a
    package.mo loads its whole folder), in name order."""

    root = job_dir / "files"
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if entry.is_symlink():
            continue
        if entry.is_file() and entry.suffix == ".mo":
            found.append(str(entry))
        elif entry.is_dir() and (entry / "package.mo").is_file():
            found.append(str(entry / "package.mo"))
    return found


def mos_string(text: str) -> str:
    """A path the runner built itself, as a Modelica string literal."""

    if '"' in text or "\\" in text or "\n" in text:
        raise JobError("unexpected character in a path")
    return f'"{text}"'


def script_for(job: dict, job_dir: Path, libraries: Path, *, built: bool = False) -> str:
    """The omc script of one job; every step writes its answer and its messages to out/.
    ``built``: a sweep whose model is already in out/ (from the cache) only runs its variants."""

    kind = job.get("kind")
    if kind not in KINDS:
        raise JobError("unknown job kind")
    out = job_dir / "out"
    lines = [
        f"setModelicaPath({mos_string(str(libraries))});",
        f"cd({mos_string(str(out))}); getErrorString();",
    ]

    def step(name: str, expression: str, text: bool = False) -> None:
        # One variable per step: an omc script variable keeps the type of its first value.
        variable = "r" + str(len(lines))
        lines.append(f"{variable} := {expression};")
        answer = variable if text else f"String({variable})"
        lines.append(f"writeFile({mos_string(str(out / (name + '.ok')))}, {answer});")
        lines.append(f"writeFile({mos_string(str(out / (name + '.err')))}, getErrorString());")

    libs = job.get("libraries", list(LIBRARIES))
    if not isinstance(libs, list) or any(lib not in LIBRARIES for lib in libs):
        raise JobError("unknown library")
    if built and kind != "sweep":
        raise JobError("only a sweep runs a built model")
    for lib in libs if not built else []:
        step(f"load-{lib}", f"loadModel({lib})")
    if kind == "library_index":
        for lib in libs:
            target = mos_string(str(out / f"index-{lib}.tsv"))
            lines.append(
                f"names := getClassNames({lib}, recursive=true, qualified=true, sort=false);"
            )
            lines.append(
                "for i in 1:size(names,1) loop "
                f'writeFile({target}, typeNameString(names[i]) + "\\t" + '
                'getClassRestriction(names[i]) + "\\t" + String(isPartial(names[i])) + '
                '"\\t" + getClassComment(names[i]) + "\\n", append=true); end for;'
            )
            lines.append(f"writeFile({mos_string(str(out / 'index.err'))}, getErrorString());")
        return "\n".join(lines) + "\n"
    for index, path in enumerate(project_files(job_dir) if not built else []):
        step(f"file-{index}", f"loadFile({mos_string(path)}, uses=false)")
    model = class_name(job.get("model"))
    if kind in ("check", "simulate", "sweep", "fmu") and not built:
        # simulate() and buildModelFMU() only say "failed to build": the check says why.
        step("check", f"checkModel({model})", text=True)
    if kind == "instance":
        lines.append(
            f"writeFile({mos_string(str(out / 'instance.json'))}, getModelInstance({model}));"
        )
        lines.append(f"writeFile({mos_string(str(out / 'instance.err'))}, getErrorString());")
        if job.get("source"):
            lines.append(f"writeFile({mos_string(str(out / 'source.mo'))}, list({model}));")
    elif kind == "simulate":
        start, stop, intervals, tolerance, method, flags = simulation_settings(job, job_dir)
        overrides = override_pairs((job.get("options") or {}).get("overrides"))
        if overrides:
            flags.append("-override=" + overrides)
        simflags = " ".join(flags)
        if '"' in simflags or "\\" in simflags:
            raise JobError("unexpected character in the flags")
        lines.append(
            f"sim := simulate({model}, startTime={start}, stopTime={stop}, "
            f'numberOfIntervals={intervals}, tolerance={tolerance}, method="{method}", '
            f'outputFormat="csv", fileNamePrefix="model", simflags="{simflags}");'
        )
        # A record's field is read into a variable first: omc refuses it as an argument.
        lines.append("simFile := sim.resultFile; simMessages := sim.messages;")
        lines.append(f"writeFile({mos_string(str(out / 'simulate.ok'))}, simFile);")
        lines.append(f"writeFile({mos_string(str(out / 'simulate.msg'))}, simMessages);")
        lines.append(f"writeFile({mos_string(str(out / 'simulate.err'))}, getErrorString());")
    elif kind == "sweep":
        # Built once; the model's own program then runs once per variant with its overrides
        # (the program is what simulate() runs too), each writing res_<n>.csv and log_<n>.txt.
        start, stop, intervals, tolerance, method, flags = simulation_settings(job, job_dir)
        variants = job.get("variants")
        if not isinstance(variants, list) or not 1 <= len(variants) <= MAX_VARIANTS:
            raise JobError("bad variants")
        options = job.get("options") or {}
        common = override_pairs(options.get("overrides"))
        # Each variant's own inputs (a study's step or ramp, round 9 M6), in place of the common.
        inputs = job.get("inputs_files") or []
        if not isinstance(inputs, list) or len(inputs) not in (0, len(variants)):
            raise JobError("bad inputs files")
        commands = []
        for index, variant in enumerate(variants):
            own, experiment, values = variant_flags(variant, options)
            pairs = ",".join(item for item in (common, *experiment, override_pairs(values)) if item)
            given = flags
            if inputs and inputs[index]:
                name = inputs[index]
                if not isinstance(name, str) or not FILE_NAME.match(name):
                    raise JobError("bad inputs file")
                if not (job_dir / name).is_file():
                    raise JobError("the inputs file is missing")
                given = [flag for flag in flags if not flag.startswith("-csvInput=")]
                given.append(f"-csvInput={job_dir / name}")
            command = " ".join(
                ["./model", *given, f"-s={own or method}", f"-r=res_{index}.csv"]
                + ([f"-override={pairs}"] if pairs else [])
            )
            if '"' in command or "\\" in command:
                raise JobError("unexpected character in the flags")
            commands.append(command)
        if not built:
            lines.append(
                f"built := buildModel({model}, startTime={start}, stopTime={stop}, "
                f'numberOfIntervals={intervals}, tolerance={tolerance}, method="{method}", '
                'outputFormat="csv", fileNamePrefix="model");'
            )
            lines.append(f"writeFile({mos_string(str(out / 'build.err'))}, getErrorString());")
        lines.append(f"if regularFileExists({mos_string(str(out / 'model'))}) then")
        for index, command in enumerate(commands):
            log = mos_string(str(out / f"log_{index}.txt"))
            lines.append(
                f"  writeFile({mos_string(str(out / f'variant-{index}.ok'))}, "
                f'String(system("{command}", {log})));'
            )
        lines.append("end if;")
    elif kind == "fmu":
        options = job.get("options") or {}
        version = options.get("version", "2.0")
        if version not in ("2.0", "3.0"):
            raise JobError("unknown FMI version")
        fmu_type = options.get("type", "cs")
        if fmu_type not in ("cs", "me", "me_cs"):
            raise JobError("unknown FMU type")
        if fmu_type != "me":
            # CVODE (SUNDIALS, BSD-3-Clause) inside the FMU: accurate at any communication step.
            lines.append('setCommandLineOptions("--fmiFlags=s:cvode"); getErrorString();')
        step(
            "fmu",
            f'buildModelFMU({model}, version="{version}", fmuType="{fmu_type}", '
            'fileNamePrefix="model", platforms={"static"})',
            text=True,
        )
    return "\n".join(lines) + "\n"


# The cache of built models ----------------------------------------------------------------


def build_key(job: dict, job_dir: Path) -> str:
    """What a sweep's build depends on: the model, the libraries, every project file (path and
    bytes) and the settings ``buildModel`` takes. The same key builds the same program."""

    options = job.get("options") or {}
    digest = hashlib.sha256()
    head = {
        "runner": RUNNER_VERSION,
        "model": job.get("model"),
        "libraries": job.get("libraries", list(LIBRARIES)),
        "settings": [options.get(name) for name in ("start", "stop", "intervals", "tolerance")],
        "method": options.get("method", "dassl"),
    }
    digest.update(json.dumps(head, sort_keys=True).encode("utf-8"))
    root = job_dir / "files"
    for path in sorted(root.rglob("*")) if root.is_dir() else []:
        if path.is_file() and not path.is_symlink():
            digest.update(b"\0" + str(path.relative_to(root)).encode("utf-8") + b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def cache_take(cache: Path, key: str, out: Path) -> bool:
    """Copy a built model into ``out``; whether the cache had it."""

    entry = cache / key
    if not (entry / "model").is_file():
        return False
    try:
        for path in entry.iterdir():
            shutil.copy2(path, out / path.name)
        os.utime(entry)  # the most recently used entries are kept
        # The variants' times count from the build's end: here, now.
        (out / "build.err").touch()
    except OSError:
        return False
    return True


def cache_keep(cache: Path, key: str, out: Path) -> None:
    """Keep the model just built (when it built), dropping the least recently used entries."""

    if not (out / "model").is_file() or "Error" in read(out / "build.err"):
        return
    temporary = cache / f".{key}.{os.getpid()}.{threading.get_ident()}"
    try:
        cache.mkdir(parents=True, exist_ok=True)
        temporary.mkdir()
        for path in out.iterdir():
            if path.is_file() and (BUILT.match(path.name) or BUILD_STEPS.match(path.name)):
                shutil.copy2(path, temporary / path.name)
        temporary.rename(cache / key)
    except OSError:
        shutil.rmtree(temporary, ignore_errors=True)  # another job kept it first, or no room
    entries = sorted(
        (path for path in cache.iterdir() if not path.name.startswith(".")),
        key=lambda path: path.stat().st_mtime,
    )
    for path in entries[:-CACHE_ENTRIES]:
        shutil.rmtree(path, ignore_errors=True)


# Running a job ------------------------------------------------------------------------------


def _limits(memory_mb: int, cpu_seconds: int) -> None:  # pragma: no cover - in the child
    import resource

    os.setsid()
    megabyte = 1024 * 1024
    for limit, value in (
        (resource.RLIMIT_AS, memory_mb * megabyte),
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_FSIZE, 2048 * megabyte),
        (resource.RLIMIT_CORE, 0),
    ):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass


def run_omc(omc: str, script: Path, cwd: Path, timeout: float, memory_mb: int) -> tuple[str, str]:
    """Run omc on ``script`` in its own process group; (its output, "" or why it was stopped:
    "timeout" or "cancelled")."""

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd / "home"),
        "LANG": "C.UTF-8",
        "OPENMODELICAHOME": os.environ.get("OPENMODELICAHOME", "/usr"),
    }
    (cwd / "home").mkdir(exist_ok=True)
    process = subprocess.Popen(
        [omc, str(script)],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        preexec_fn=lambda: _limits(memory_mb, int(timeout) + 30),
    )
    # Read the output in a thread: the loop below watches the clock and the cancel file.
    chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: chunks.append(process.stdout.read()), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    stopped = ""
    while process.poll() is None:
        if time.monotonic() > deadline:
            stopped = "timeout"
        elif (cwd / CANCEL).exists():
            stopped = "cancelled"
        if stopped:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            break
        time.sleep(0.2)
    process.wait()
    reader.join(timeout=5)
    output = b"".join(chunks).decode("utf-8", "replace")[-LOG_LIMIT:]
    return output, stopped


def read(path: Path, limit: int = LOG_LIMIT) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def variant_seconds(out: Path, count: int) -> list[float | None]:
    """How long each variant of a sweep ran: the variants run one after the other, each
    writing ``variant-<n>.ok`` when done, so each one's time is from the end of the one before
    (or of the build) to its own end."""

    def written(name: str) -> float | None:
        try:
            return (out / name).stat().st_mtime
        except OSError:
            return None

    found: list[float | None] = []
    before = written("build.err")
    for index in range(count):
        end = written(f"variant-{index}.ok")
        found.append(round(max(0.0, end - before), 3) if end and before else None)
        before = end or before
    return found


def execute(
    job_dir: Path, *, omc: str, libraries: Path, memory_mb: int = 4096, cache: Path | None = None
) -> dict:
    """Run the job in ``job_dir``; its answer (also written to result.json). With ``cache``, a
    sweep takes its model from there when the same files and settings were built before."""

    started = time.monotonic()
    out = job_dir / "out"
    out.mkdir(exist_ok=True)
    try:
        job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        if not isinstance(job, dict):
            raise JobError("the job is not an object")
        timeout = float(number(job.get("timeout", 120), low=1, high=86_400))
        key = build_key(job, job_dir) if cache is not None and job.get("kind") == "sweep" else ""
        built = bool(key) and cache_take(cache, key, out)
        script = job_dir / "job.mos"
        script.write_text(script_for(job, job_dir, libraries, built=built), encoding="utf-8")
    except (JobError, OSError, ValueError) as exc:
        result = {"status": "refused", "error": str(exc), "seconds": 0.0}
        write_json(job_dir / "result.json", result)
        return result
    log, stopped = run_omc(omc, script, job_dir, timeout, memory_mb)
    if key and not built and not stopped:
        cache_keep(cache, key, out)
    steps = {}
    for path in sorted(out.iterdir()):
        if path.suffix in (".ok", ".err", ".msg"):
            steps[path.name] = read(path)
        elif not KEEP.match(path.name):
            # Build files (C sources, objects, the executable) never leave the runner.
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    shutil.rmtree(job_dir / "home", ignore_errors=True)
    result = {
        "status": stopped or "done",
        "seconds": round(time.monotonic() - started, 3),
        "steps": steps,
        "log": log,
    }
    if job.get("kind") == "sweep":
        result["variant_seconds"] = variant_seconds(out, len(job.get("variants") or []))
        result["built"] = "cache" if built else "now"
    write_json(job_dir / "result.json", result)
    return result


# The queue -----------------------------------------------------------------------------------


def omc_version(omc: str) -> str:
    try:
        answer = subprocess.run(
            [omc, "--version"], capture_output=True, timeout=60, check=False, env={"HOME": "/tmp"}
        )
        return answer.stdout.decode("utf-8", "replace").strip()[:200]
    except (OSError, subprocess.SubprocessError):
        return ""


class Runner:
    def __init__(
        self,
        jobs: Path,
        *,
        omc: str,
        libraries: Path,
        workers: int,
        memory_mb: int,
        cache: Path | None = None,
    ):
        self.jobs = jobs
        self.cache = cache
        self.omc = omc
        self.libraries = libraries
        self.workers = max(1, workers)
        self.memory_mb = memory_mb
        for folder in ("queue", "work", "done"):
            (jobs / folder).mkdir(parents=True, exist_ok=True)
        self.version = omc_version(omc)
        self.stop = threading.Event()

    def heartbeat(self) -> None:
        state = {
            "app": "modelcraft",
            "version": f"runner-{RUNNER_VERSION}",
            "runner": RUNNER_VERSION,
            "omc": self.version,
            "libraries": {lib: "4.0.0" for lib in LIBRARIES},
            "workers": self.workers,
            # The memory one task may use: PlantCraft places by it (sizes, docs/compute.md).
            "memory_mb": self.memory_mb,
            "at": time.time(),
        }
        write_json(self.jobs / "runner.json", state)

    def claim(self) -> Path | None:
        for entry in sorted((self.jobs / "queue").iterdir(), key=lambda path: path.name):
            target = self.jobs / "work" / entry.name
            try:
                entry.rename(target)
            except OSError:
                continue  # another worker took it
            return target
        return None

    def answer(self, job_dir: Path) -> None:
        try:
            execute(
                job_dir,
                omc=self.omc,
                libraries=self.libraries,
                memory_mb=self.memory_mb,
                cache=self.cache,
            )
        except Exception as exc:  # noqa: BLE001 - a job never stops the runner
            write_json(
                job_dir / "result.json",
                {"status": "error", "error": f"runner error: {type(exc).__name__}"},
            )
        target = self.jobs / "done" / job_dir.name
        shutil.rmtree(target, ignore_errors=True)
        job_dir.rename(target)

    def work(self, once: bool = False) -> None:
        while not self.stop.is_set():
            job_dir = self.claim()
            if job_dir is None:
                if once:
                    return
                self.stop.wait(0.1)
                continue
            self.answer(job_dir)

    def clean(self, older_than: float = 3600) -> None:
        """Answers nobody collected (PlantCraft Models restarted mid-job) go after an hour."""

        limit = time.time() - older_than
        for entry in (self.jobs / "done").iterdir():
            try:
                if entry.stat().st_mtime < limit:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass

    def serve(self, once: bool = False) -> None:
        # Jobs a previous runner left half done are answered again.
        for entry in (self.jobs / "work").iterdir():
            try:
                entry.rename(self.jobs / "queue" / entry.name)
            except OSError:
                pass
        self.heartbeat()
        if once:
            self.work(once=True)
            return
        threads = [threading.Thread(target=self.work, daemon=True) for _ in range(self.workers)]
        for thread in threads:
            thread.start()
        while not self.stop.is_set():
            self.heartbeat()
            self.clean()
            self.stop.wait(10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="modelcraft-runner", description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", default=os.environ.get("MODELCRAFT_JOBS_DIR", "/jobs"))
    parser.add_argument("--omc", default=os.environ.get("MODELCRAFT_OMC", "omc"))
    parser.add_argument(
        "--libraries", default=os.environ.get("MODELCRAFT_LIBRARIES", "/opt/modelica")
    )
    parser.add_argument(
        "--workers", type=int, default=int(os.environ.get("MODELCRAFT_RUNNER_WORKERS", "2"))
    )
    parser.add_argument(
        "--memory-mb", type=int, default=int(os.environ.get("MODELCRAFT_JOB_MEMORY_MB", "4096"))
    )
    # Built models kept between sweeps, in a folder only this runner writes (its own /tmp; a
    # job copies the program into its folder to run it). Empty: every sweep builds its model.
    parser.add_argument(
        "--cache", default=os.environ.get("MODELCRAFT_RUNNER_CACHE", "/tmp/modelcraft-builds")
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    runner = Runner(
        Path(args.jobs),
        omc=args.omc,
        libraries=Path(args.libraries),
        workers=args.workers,
        memory_mb=args.memory_mb,
        cache=Path(args.cache) if args.cache else None,
    )
    signal.signal(signal.SIGTERM, lambda *_: runner.stop.set())
    print(f"modelcraft-runner {RUNNER_VERSION}: {runner.version or 'omc not found'}", flush=True)
    runner.serve(once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
