"""A Modelica runner for tests: answers jobs from recorded omc answers (``tests/fixtures``).

The fixtures were recorded from the real runner (OpenModelica 1.24.4, MSL 4.0.0) on the example
``PlantCraftExamples.TankLevelControl``. A project file holding ``BROKEN`` fails its check and its
runs, with an error on that line, as omc reports one. A sweep answers every variant with the
recorded results, the level scaled by the variant's ``controller.k`` (so variants differ); a
variant with ``fail`` set to true fails. ``hold`` (an Event) keeps jobs running until it is set,
and a cancelled job answers "cancelled", as the runner does.
"""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

from modelcraft.omc.jobs import JobAnswer, RunnerUnavailable

FIXTURES = Path(__file__).parent / "fixtures"


class FakeExecutor:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(tempfile.mkdtemp(prefix="fake-runner-"))
        self.root.mkdir(parents=True, exist_ok=True)
        self.available = True
        self.jobs: list[dict[str, Any]] = []
        self.extras: list[dict[str, bytes]] = []
        self.hold: threading.Event | None = None
        self.cancelled: set[str] = set()
        self.folders: dict[str, Path] = {}

    def cancel(self, job_id: str) -> None:
        self.cancelled.add(job_id)

    def output(self, job_id: str, name: str) -> Path | None:
        folder = self.folders.get(job_id)
        path = folder / "out" / name if folder else None
        return path if path is not None and path.is_file() else None

    def state(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "reason": "" if self.available else "The Modelica runner has not started.",
            "omc": "OpenModelica 1.24.4 (fake)",
            "libraries": {"Modelica": "4.0.0"},
            "workers": 2,
            "queued": 0,
            "running": 0,
        }

    def _broken(self, files: dict[str, str]) -> tuple[str, int] | None:
        for path, text in files.items():
            for number, line in enumerate(text.splitlines(), start=1):
                if "BROKEN" in line:
                    return path, number
        return None

    def run(
        self,
        job: dict[str, Any],
        files: dict[str, str],
        *,
        timeout: float,
        extra=None,
        job_id: str | None = None,
    ) -> JobAnswer:
        if not self.available:
            raise RunnerUnavailable("The Modelica runner has not started.")
        self.jobs.append(job)
        self.extras.append(dict(extra or {}))
        folder = Path(tempfile.mkdtemp(dir=self.root))
        out = folder / "out"
        out.mkdir()
        job_id = job_id or folder.name
        self.folders[job_id] = folder
        if self.hold is not None:
            # A half-written results file, as while the runner simulates.
            (out / ("res_0.csv" if job["kind"] == "sweep" else "model_res.csv")).write_text(
                '"time","tank.level"\n0,1\n450,1.2\n'
            )
            while not self.hold.is_set() and job_id not in self.cancelled:
                self.hold.wait(0.02)
            for name in ("res_0.csv", "model_res.csv"):
                (out / name).unlink(missing_ok=True)
        if job_id in self.cancelled:
            steps = {
                "load-Modelica.ok": "true",
                "check.ok": f"Check of {job.get('model')} completed successfully.",
            }
            return JobAnswer(status="cancelled", seconds=0.1, steps=steps, folder=folder)
        kind, model = job["kind"], job.get("model", "")
        steps: dict[str, str] = {"load-Modelica.ok": "true", "load-Modelica.err": ""}
        broken = self._broken(files)
        error = (
            f"[/jobs/work/x/files/{broken[0]}:{broken[1]}:3-{broken[1]}:9:writable] Error: "
            "Variable BROKEN not found in scope.\n"
            if broken
            else ""
        )
        if kind in ("check", "simulate", "sweep", "fmu"):
            steps["check.ok"] = (
                ""
                if broken
                else f"Check of {model} completed successfully.\nClass {model} has 12 equation(s) and 12 variable(s)."
            )
            steps["check.err"] = error
        if kind == "library_index":
            shutil.copyfile(FIXTURES / "index-Modelica.tsv", out / "index-Modelica.tsv")
            steps["index.err"] = ""
        elif kind == "instance":
            instance = json.loads((FIXTURES / "instance-TankLevelControl.json").read_text())
            if not model.startswith("Modelica.") and model != "PlantCraftExamples.TankLevelControl":
                # The model's own top-level inputs, as omc lists them (a model written as code).
                short = model.rpartition(".")[2]
                text = next((v for k, v in files.items() if k.endswith(f"{short}.mo")), "")
                instance = {
                    "name": model,
                    "restriction": "model",
                    "elements": [
                        {
                            "$kind": "component",
                            "name": name,
                            "type": "Real",
                            "prefixes": {"direction": "input"},
                        }
                        for name in re.findall(r"^\s*input Real (\w+)", text, re.MULTILINE)
                    ],
                    "connections": [],
                }
            elif model.startswith("Modelica."):
                instance = {**instance, "name": model}
                (out / "source.mo").write_text(
                    f"block {model.rpartition('.')[2]}\nend {model.rpartition('.')[2]};\n"
                )
            if not broken:
                (out / "instance.json").write_text(json.dumps(instance))
            steps["instance.err"] = error
        elif kind == "simulate" and not broken:
            shutil.copyfile(FIXTURES / "tlc_res.csv", out / "model_res.csv")
            shutil.copyfile(FIXTURES / "tlc_init.xml", out / "model_init.xml")
            steps["simulate.ok"] = "/jobs/work/x/out/model_res.csv"
            steps["simulate.msg"] = (
                "LOG_SUCCESS       | info    | The initialization finished successfully without homotopy method.\n"
                "LOG_SUCCESS       | info    | The simulation finished successfully.\n"
            )
            steps["simulate.err"] = ""
        elif kind == "sweep" and not broken:
            shutil.copyfile(FIXTURES / "tlc_init.xml", out / "model_init.xml")
            steps["build.err"] = ""
            for index, variant in enumerate(job.get("variants") or []):
                if variant.get("fail"):
                    steps[f"variant-{index}.ok"] = "1"
                    (out / f"log_{index}.txt").write_text(
                        "LOG_ASSERT        | error   | The simulation failed: division by zero.\n"
                    )
                    continue
                (out / f"res_{index}.csv").write_text(
                    _scaled(FIXTURES / "tlc_res.csv", _factor(variant))
                )
                (out / f"log_{index}.txt").write_text(
                    "LOG_SUCCESS       | info    | The simulation finished successfully.\n"
                )
                steps[f"variant-{index}.ok"] = "0"
        elif kind == "fmu" and not broken:
            version = (job.get("options") or {}).get("version", "2.0")
            with zipfile.ZipFile(out / "model.fmu", "w") as archive:
                archive.writestr(
                    "modelDescription.xml",
                    f'<fmiModelDescription fmiVersion="{version}" modelName="{model}" guid="{{fake}}">'
                    "<ModelVariables>"
                    '<ScalarVariable name="u" causality="input"><Real/></ScalarVariable>'
                    '<ScalarVariable name="y" causality="output"><Real/></ScalarVariable>'
                    '<ScalarVariable name="k" causality="parameter"><Real/></ScalarVariable>'
                    "</ModelVariables></fmiModelDescription>",
                )
                archive.writestr("binaries/linux64/model.so", b"\x7fELF")
            steps["fmu.ok"] = "/jobs/work/x/out/model.fmu"
            steps["fmu.err"] = ""
        (folder / "result.json").write_text(
            json.dumps({"status": "done", "seconds": 0.5, "steps": steps, "log": ""})
        )
        # Each variant of a sweep its own time, as the runner measures it.
        timings = [round(0.1 * (index + 1), 3) for index in range(len(job.get("variants") or []))]
        return JobAnswer(
            status="done", seconds=0.5, steps=steps, folder=folder, variant_seconds=timings
        )


def _factor(variant: dict[str, Any]) -> float:
    """How far a variant moves ``tank.level`` from the recording: 1 with the model's own values
    (controller.k 4, tank.A 2, tank.Cv 0.05), so a study's runs differ as its parameters do."""

    return (
        float(variant.get("controller.k", 4))
        / 4
        * (2 / float(variant.get("tank.A", 2))) ** 0.5
        * float(variant.get("tank.Cv", 0.05))
        / 0.05
    )


def _scaled(path: Path, factor: float) -> str:
    """The recorded results with ``tank.level`` multiplied by ``factor``."""

    rows = list(csv.reader(path.read_text().splitlines()))
    column = rows[0].index("tank.level")
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(rows[0])
    for row in rows[1:]:
        row = list(row)
        row[column] = repr(float(row[column]) * factor)
        writer.writerow(row)
    return out.getvalue()
