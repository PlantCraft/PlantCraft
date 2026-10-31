"""What the runner's answers become (messages, results, diagrams, the library) and the runner's
own refusals: every omc script is written by the runner from checked fields."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from modelcraft.omc import results, runner
from modelcraft.omc.diagram import reduce
from modelcraft.omc.library import LibraryIndex, parse_index
from modelcraft.omc.messages import parse, simulation_log

FIXTURES = Path(__file__).parent / "fixtures"


def test_messages_name_the_project_file_and_hide_the_runner_folders():
    text = (
        "[/jobs/work/20261021-ab/files/Pkg/Tank.mo:7:1-7:8:writable] Error: Expected token\n"
        "  of type SEMICOLON\n"
        "[/opt/modelica/Modelica/Blocks/package.mo:3:1-3:2:readonly] Warning: a library warning\n"
        "Notification: Automatically loaded package Complex 4.0.0 due to uses annotation from Modelica.\n"
    )
    first, second, third = parse(text)
    assert first == {
        **first,
        "level": "error",
        "file": "Pkg/Tank.mo",
        "own": True,
        "line": 7,
        "column": 1,
        "end_column": 8,
    }
    assert first["text"] == "Expected token\nof type SEMICOLON"
    assert second["file"] == "Modelica/Blocks/package.mo" and not second["own"]
    assert third["level"] == "info" and third["file"] is None


def test_the_simulation_log_keeps_what_matters():
    log = (
        "LOG_SUCCESS       | info    | The initialization finished successfully without homotopy method.\n"
        "LOG_ASSERT        | warning | [/opt/modelica/Modelica/Blocks/Continuous.mo:768:5-768:63:readonly]\n"
        "|                 | |       | The following assertion has been violated at time 0.000000\n"
        "LOG_ASSERT        | debug   | Model error: Argument of sqrt(h) was -0.005 should be >= 0\n"
    )
    found = simulation_log(log)
    assert [m["level"] for m in found] == ["info", "warning"]
    assert "assertion has been violated" in found[1]["text"] and "sqrt(h)" in found[1]["text"]
    assert "/opt/" not in found[1]["text"]


def test_results_are_stored_once_and_plotted_without_losing_spikes(tmp_path):
    summary = results.store(FIXTURES / "tlc_res.csv", FIXTURES / "tlc_init.xml", tmp_path)
    assert summary["rows"] > 80 and summary["start"] == 0 and summary["stop"] > 890
    variables = {v["name"]: v for v in results.variables(tmp_path)}
    assert (
        variables["tank.level"]["description"] == "Level" and variables["tank.Cv"]["column"] is None
    )
    plotted = results.series(tmp_path, ["tank.level"], max_points=30)["series"][0]
    full = results.series(tmp_path, ["tank.level"], max_points=20_000)["series"][0]
    assert len(plotted["time"]) <= 40 < len(full["time"])
    assert max(v for v in plotted["values"] if v is not None) == max(
        v for v in full["values"] if v is not None
    )
    assert results.csv_text(tmp_path, ["tank.level"]).splitlines()[0] == '"time","tank.level"'


def test_a_damaged_result_is_no_crash(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text('"time","x"\n0,1\n0.5,nan\n1,inf\n2\n')
    results.store(bad, None, tmp_path / "run")
    assert results.series(tmp_path / "run", ["x"])["series"][0]["values"] == [1.0, None, None, None]
    assert results.series(tmp_path / "nothing", ["x"]) == {"series": [], "missing": ["x"]}


def test_diagram_reduces_the_instance_to_what_is_drawn():
    instance = json.loads((FIXTURES / "instance-TankLevelControl.json").read_text())
    diagram = reduce(instance)
    assert len(json.dumps(diagram)) < len(json.dumps(instance)) / 2
    tank = next(c for c in diagram["components"] if c["name"] == "tank")
    assert tank["type"] == "ProcessExamples.Tank" and tank["placement"]["extent"] == [
        [40.0, -20.0],
        [80.0, 20.0],
    ]
    assert {g["kind"] for g in tank["icon"]["graphics"]} >= {"Rectangle", "Text"}
    opening = next(c for c in tank["connectors"] if c["name"] == "opening")
    assert opening["placement"]["rotation"] == 90 and opening["icon"]["graphics"]
    assert diagram["diagram"]["extent"] == [[-120.0, -80.0], [120.0, 80.0]]
    assert "PI controller" in diagram["documentation"]["info"]


def test_diagram_survives_anything_omc_might_answer():
    for junk in (
        {},
        {"elements": "x"},
        {"elements": [{"$kind": "component", "type": 3, "annotation": {"Placement": 1}}]},
        {
            "annotation": {
                "Icon": {"graphics": [{"$kind": "record", "name": "Line", "elements": [True, "x"]}]}
            }
        },
    ):
        reduce(junk)


def test_library_index_parses_comments_on_several_lines():
    text = "Modelica\tpackage\tfalse\tMSL\nModelica.A\tmodel\tfalse\tOne line\ncontinues\nModelica.UsersGuide\tpackage\tfalse\tDocs\n"
    classes = parse_index(text)
    assert classes[1]["comment"] == "One line continues"
    index = LibraryIndex(classes, "v")
    assert [c["name"] for c in index.list("Modelica")] == ["Modelica.A"]
    assert len(parse_index((FIXTURES / "index-Modelica.tsv").read_text())) > 150


def job(tmp_path, **fields):
    (tmp_path / "files").mkdir(exist_ok=True)
    (tmp_path / "files" / "A.mo").write_text("model A end A;")
    return runner.script_for(
        {"kind": "simulate", "model": "A", **fields}, tmp_path, Path("/opt/modelica")
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"model": 'A"); system("id'},
        {"model": "A;B"},
        {"kind": "script"},
        {"options": {"method": "dassl; rm"}},
        {"options": {"stop": "1e3)"}},
        {"options": {"stop": float("nan")}},
        {"options": {"overrides": {"k=1 -o": 1}}},
        {"options": {"overrides": {"k": "1,a=2"}}},
        {"options": {"inputs_file": "../../etc/passwd"}},
        {"options": {"start": 5, "stop": 1}},
        {"libraries": ["../../x"]},
    ],
)
def test_the_runner_refuses_any_field_it_did_not_check(tmp_path, fields):
    with pytest.raises(runner.JobError):
        job(tmp_path, **fields)


def test_the_runner_writes_the_script_itself(tmp_path):
    script = job(
        tmp_path, options={"stop": 10, "overrides": {"tank.A": 3, "on": True}, "method": "cvode"}
    )
    assert 'loadFile("' + str(tmp_path / "files" / "A.mo") + '", uses=false)' in script
    assert "checkModel(A)" in script
    assert 'method="cvode"' in script and "-override=tank.A=3.0,on=true" in script


def test_a_sweep_varies_the_simulation_settings_and_each_variant_its_inputs(tmp_path):
    """Round 9 M6/M7: ``@method``, ``@tolerance``, ``@stop`` and ``@intervals`` become the
    variant's own integrator and experiment overrides; each variant reads its own inputs."""

    for index in range(2):
        (tmp_path / f"inputs_{index}.csv").write_text("time,u\n0,1\n10,1\n")
    variants = [
        {"@method": "ida", "@tolerance": 1e-4, "k": 2},
        {"@stop": 100, "@intervals": 50, "k": 3},
    ]
    script = job(
        tmp_path,
        kind="sweep",
        options={"start": 0, "stop": 10, "intervals": 10},
        variants=variants,
        inputs_files=["inputs_0.csv", "inputs_1.csv"],
    )
    first, second = [line for line in script.splitlines() if "./model" in line]
    assert "-s=ida" in first and "tolerance=0.0001" in first and "k=2.0" in first
    assert f"-csvInput={tmp_path / 'inputs_0.csv'}" in first
    assert "-s=dassl" in second and "stopTime=100.0" in second and "stepSize=2.0" in second
    assert f"-csvInput={tmp_path / 'inputs_1.csv'}" in second and "@" not in second
    for bad in (
        {"variants": [{"@method": "rm -rf"}]},
        {"variants": [{"@tolerance": 1}]},
        {"variants": [{"@stop": -1}]},
        {"variants": [{"k": 1}], "inputs_files": ["../etc/passwd"]},
        {"variants": [{"k": 1}], "inputs_files": ["missing.csv"]},
        {"variants": [{"k": 1}, {"k": 2}], "inputs_files": ["inputs_0.csv"]},
    ):
        with pytest.raises(runner.JobError):
            job(tmp_path, kind="sweep", options={"stop": 10}, **bad)


def test_each_variant_of_a_sweep_has_its_own_time(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for name, at in (("build.err", 100.0), ("variant-0.ok", 101.5), ("variant-1.ok", 104.0)):
        (out / name).write_text("0")
        os.utime(out / name, (at, at))
    assert runner.variant_seconds(out, 3) == [1.5, 2.5, None]


def test_the_runner_answers_a_refused_job_without_running_omc(tmp_path):
    (tmp_path / "job.json").write_text(json.dumps({"kind": "simulate", "model": "A;rm"}))
    answer = runner.execute(tmp_path, omc="/nonexistent/omc", libraries=Path("/opt/modelica"))
    assert answer["status"] == "refused"
    assert json.loads((tmp_path / "result.json").read_text())["status"] == "refused"


def _stand_in_omc(tmp_path: Path, *, sleep: float = 0.0) -> Path:
    """An omc that writes the steps' answers (after ``sleep`` seconds), on this interpreter."""

    import shlex
    import stat
    import sys

    # The stand-in runs on this interpreter, named in full: the runner hands omc a bare
    # environment, and a CI toolcache Python needs LD_LIBRARY_PATH to find libpython.
    stand_in = tmp_path / "omc.py"
    stand_in.write_text(
        "import re, sys, time\n"
        "if sys.argv[1] == '--version': print('OpenModelica 0 (stand-in)'); sys.exit()\n"
        f"time.sleep({sleep})\n"
        'for path in re.findall(r\'writeFile\\("([^"]+)"\', open(sys.argv[1]).read()):\n'
        "    open(path, 'w').write('Check of A completed successfully.' if path.endswith('check.ok') else '')\n"
    )
    omc = tmp_path / "omc"
    omc.write_text(
        "#!/bin/sh\n"
        f"LD_LIBRARY_PATH={shlex.quote(os.environ.get('LD_LIBRARY_PATH', ''))} "
        f'exec {shlex.quote(sys.executable)} {shlex.quote(str(stand_in))} "$@"\n'
    )
    omc.chmod(omc.stat().st_mode | stat.S_IEXEC)
    return omc


def test_the_queue_hands_jobs_to_a_runner_and_takes_answers_back(tmp_path):
    """The runner and the queue executor through a real folder, with a stand-in omc."""

    import threading

    from modelcraft.omc.jobs import QueueExecutor

    omc = _stand_in_omc(tmp_path)
    jobs = tmp_path / "jobs"
    worker = runner.Runner(jobs, omc=str(omc), libraries=tmp_path, workers=1, memory_mb=1024)
    worker.heartbeat()
    executor = QueueExecutor(jobs, poll_seconds=0.01)
    assert executor.state()["available"]
    # The runner polls until stopped: a fixed number of empty polls could all pass before the
    # job is queued on a busy machine, and the job would then never be taken.
    thread = threading.Thread(target=worker.work, daemon=True)
    thread.start()
    try:
        answer = executor.run(
            {"kind": "check", "model": "A"}, {"A.mo": "model A end A;"}, timeout=30
        )
    finally:
        worker.stop.set()
    try:
        assert answer.status == "done" and "completed successfully" in answer.text("check")
        assert not any((jobs / "queue").iterdir()) and not any((jobs / "work").iterdir())
    finally:
        answer.close()
    thread.join(timeout=5)
    assert os.listdir(jobs / "collected") == []


class FakeCompute:
    """PlantCraft's compute and one worker's gateway, in a folder: each task goes to the
    runner's queue as the gateway puts it, and its answer comes back as the gateway packs it."""

    def __init__(self, jobs: Path, *, workers: int = 1):
        from plantcraft_sdk.compute import folder

        self.folder = folder
        self.jobs = jobs
        self.workers = workers
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []
        folder.prepare(jobs)

    def capacity(self) -> dict:
        beat = self.folder.heartbeat(self.jobs) or {}
        able = self.workers if beat.get("version") == self.version else 0
        return {"workers": able, "slots": beat.get("workers") if able else 0, "queued": 0}

    def submit(self, files, **options) -> str:
        task_id = f"task-{len(self.submitted) + 1}"
        self.submitted.append({"id": task_id, "names": sorted(files), **options})
        incoming = self.jobs / f".incoming-{task_id}"
        self.folder.unpack(self.folder.pack(files), incoming)
        self.folder.write_json(incoming / self.folder.TASK, {"id": task_id})
        incoming.rename(self.jobs / self.folder.QUEUE / task_id)
        return task_id

    def cancel(self, task_id: str) -> dict:
        self.cancelled.append(task_id)
        (self.jobs / self.folder.WORK / task_id / self.folder.CANCEL).touch()
        return {"id": task_id}

    def answers(self, ids, *, timeout=None):
        import time

        from plantcraft_sdk.compute.client import Answer

        (task_id,) = ids
        done = self.jobs / self.folder.DONE / task_id
        deadline = time.monotonic() + 30
        while not (done / self.folder.RESULT).is_file():
            assert time.monotonic() < deadline, "the runner gave no answer"
            time.sleep(0.01)
        files = self.folder.read(self.folder.pack_answer(done))
        result = json.loads(files.pop(self.folder.RESULT))
        out = {name[4:]: content for name, content in files.items() if name.startswith("out/")}
        yield Answer(task_id, "done", result, out)


def test_the_compute_workers_run_models_jobs_with_the_runner_as_it_is(tmp_path, monkeypatch):
    """With ``MODELCRAFT_RUNNER=suite`` each job is a compute task: the runner behind a
    worker's gateway takes it from its folder (its heartbeat names the version Models asks for)
    and the answer comes back to Models' collected folder."""

    import threading

    from modelcraft.omc import jobs as jobs_module

    omc = _stand_in_omc(tmp_path)
    jobs = tmp_path / "worker" / "modelcraft"
    worker = runner.Runner(jobs, omc=str(omc), libraries=tmp_path, workers=1, memory_mb=1024)
    worker.heartbeat()
    beat = json.loads((jobs / "runner.json").read_text())
    assert beat["app"] == "modelcraft" and beat["version"] == jobs_module.SUITE_VERSION
    # Its room per task, so PlantCraft sends it only the sizes that fit (the Mac mini, 2026-10-27).
    assert beat["memory_mb"] == 1024
    compute = FakeCompute(jobs)

    def client(_client, version):
        compute.version = version
        return compute

    monkeypatch.setattr(jobs_module, "ComputeClient", client)
    executor = jobs_module.SuiteExecutor(tmp_path / "models-jobs", lambda: object())
    assert executor.state()["available"]
    thread = threading.Thread(target=worker.work, daemon=True)
    thread.start()
    try:
        answer = executor.run(
            {
                "kind": "check",
                "model": "A",
                "compute": {"environment": "standard", "size": "medium"},
            },
            {"Pkg/A.mo": "model A end A;"},
            timeout=30,
            job_id="run-1",
        )
    finally:
        worker.stop.set()
    try:
        assert answer.status == "done" and "completed successfully" in answer.text("check")
        assert answer.folder == tmp_path / "models-jobs" / "collected" / "run-1"
        sent = compute.submitted[0]
        assert sent["names"] == ["files/Pkg/A.mo", "job.json"]
        assert sent["kind"] == "check" and sent["run"] == "run-1"
        assert sent["timeout_seconds"] == 90
        # Where it runs goes with the task, not into the runner's job.
        assert (sent["environment"], sent["size"]) == ("standard", "medium")
        assert executor.output("run-1", "res_0.csv") is None
    finally:
        answer.close()
    thread.join(timeout=5)


def test_models_says_why_no_worker_runs_its_jobs(tmp_path, monkeypatch):
    from modelcraft.omc import jobs as jobs_module

    executor = jobs_module.SuiteExecutor(tmp_path, lambda: None)
    state = executor.state()
    assert not state["available"] and "app key" in state["reason"]
    with pytest.raises(jobs_module.RunnerUnavailable):
        executor.run({"kind": "check", "model": "A"}, {}, timeout=10)
    compute = FakeCompute(tmp_path / "worker")  # no runner: no heartbeat
    monkeypatch.setattr(
        jobs_module,
        "ComputeClient",
        lambda _client, version: setattr(compute, "version", version) or compute,
    )
    executor = jobs_module.SuiteExecutor(tmp_path, lambda: object())
    state = executor.state()
    assert not state["available"] and "Settings › Compute" in state["reason"]


def test_cancelling_a_run_cancels_its_compute_task(tmp_path, monkeypatch):
    import threading
    import time

    from modelcraft.omc import jobs as jobs_module

    omc = _stand_in_omc(tmp_path, sleep=20)
    jobs = tmp_path / "worker" / "modelcraft"
    worker = runner.Runner(jobs, omc=str(omc), libraries=tmp_path, workers=1, memory_mb=1024)
    worker.heartbeat()
    compute = FakeCompute(jobs)
    monkeypatch.setattr(
        jobs_module,
        "ComputeClient",
        lambda _client, version: setattr(compute, "version", version) or compute,
    )
    executor = jobs_module.SuiteExecutor(tmp_path / "models-jobs", lambda: object())
    thread = threading.Thread(target=worker.work, daemon=True)
    thread.start()
    found = {}
    running = threading.Thread(
        target=lambda: found.setdefault(
            "answer",
            executor.run({"kind": "check", "model": "A"}, {"A.mo": ""}, timeout=60, job_id="r"),
        )
    )
    started = time.monotonic()
    running.start()
    try:
        while not any((jobs / "work").iterdir()):
            time.sleep(0.01)
        executor.cancel("r")
        running.join(timeout=30)
    finally:
        worker.stop.set()
    answer = found["answer"]
    try:
        assert compute.cancelled == ["task-1"]
        assert answer.status == "cancelled" and time.monotonic() - started < 15
    finally:
        answer.close()
    thread.join(timeout=5)


def _building_omc(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in omc that also "builds": a buildModel in the script writes out/model and
    counts the builds in a file."""

    import shlex
    import stat
    import sys

    builds = tmp_path / "builds.txt"
    stand_in = tmp_path / "omc-build.py"
    stand_in.write_text(
        "import re, sys\n"
        "script = open(sys.argv[1]).read()\n"
        'out = re.search(r\'cd\\("([^"]+)"\\)\', script).group(1)\n'
        "if 'buildModel(' in script:\n"
        "    open(out + '/model', 'w').write('#!/bin/sh\\n')\n"
        "    open(out + '/model_init.xml', 'w').write('<init/>')\n"
        f"    open({str(builds)!r}, 'a').write('x')\n"
        'for path in re.findall(r\'writeFile\\("([^"]+)"\', script):\n'
        "    open(path, 'w').write('0' if 'variant-' in path else '')\n"
    )
    omc = tmp_path / "omc"
    omc.write_text(
        "#!/bin/sh\n"
        f"LD_LIBRARY_PATH={shlex.quote(os.environ.get('LD_LIBRARY_PATH', ''))} "
        f'exec {shlex.quote(sys.executable)} {shlex.quote(str(stand_in))} "$@"\n'
    )
    omc.chmod(omc.stat().st_mode | stat.S_IEXEC)
    return omc, builds


def test_a_sweep_takes_its_built_model_from_the_cache(tmp_path):
    """The same files and settings build once: the next sweeps only run their variants (an
    optimization asks for one simulation at a time); another file builds again."""

    omc, builds = _building_omc(tmp_path)
    cache = tmp_path / "cache"

    def sweep(name: str, text: str = "model A end A;", stop: float = 10) -> dict:
        folder = tmp_path / name
        (folder / "files").mkdir(parents=True)
        (folder / "files" / "A.mo").write_text(text)
        job = {"kind": "sweep", "model": "A", "options": {"stop": stop}, "variants": [{"k": 1}]}
        (folder / "job.json").write_text(json.dumps(job))
        answer = runner.execute(folder, omc=str(omc), libraries=tmp_path, cache=cache)
        assert answer["status"] == "done" and answer["steps"]["variant-0.ok"] == "0"
        assert (folder / "out" / "model_init.xml").is_file()
        assert not (folder / "out" / "model").exists()  # build files never leave the runner
        return {**answer, "script": (folder / "job.mos").read_text()}

    first = sweep("one")
    again = sweep("two")
    assert first["built"] == "now" and again["built"] == "cache"
    assert "buildModel(" not in again["script"] and "loadModel(" not in again["script"]
    assert "check.ok" in again["steps"]  # the build's answers come with the cached model
    assert sweep("three", "model A Real x; end A;")["built"] == "now"
    assert sweep("four", stop=20)["built"] == "now"
    assert builds.read_text() == "xxx"
    # A runner without a cache builds every time.
    folder = tmp_path / "five"
    (folder / "files").mkdir(parents=True)
    (folder / "files" / "A.mo").write_text("model A end A;")
    (folder / "job.json").write_text(
        json.dumps({"kind": "sweep", "model": "A", "variants": [{"k": 1}]})
    )
    assert runner.execute(folder, omc=str(omc), libraries=tmp_path)["built"] == "now"
