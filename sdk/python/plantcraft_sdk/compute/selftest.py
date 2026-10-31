"""An executor's handler to try a worker end to end (``--handler plantcraft_sdk.compute.selftest:answer``).

``job.json`` says what to do: ``{"do": "echo", "text": ...}`` writes the text back in
``out/echo.txt`` with the machine's name; ``sleep`` waits ``seconds``; ``fail`` raises;
``sum`` adds the numbers in ``numbers.json``. Used by the tests and by Settings › Compute's check
of a new worker.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from plantcraft_sdk.files import write_json


def answer(job_dir: Path) -> None:
    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    out = job_dir / "out"
    out.mkdir(exist_ok=True)
    action = job.get("do")
    if action == "echo":
        (out / "echo.txt").write_text(str(job.get("text", "")), encoding="utf-8")
        result = {"status": "done", "host": socket.gethostname()}
    elif action == "sleep":
        time.sleep(float(job.get("seconds") or 0))
        result = {"status": "done"}
    elif action == "fail":
        raise ValueError(str(job.get("text") or "asked to fail"))
    elif action == "sum":
        numbers = json.loads((job_dir / "numbers.json").read_text(encoding="utf-8"))
        result = {"status": "done", "sum": sum(float(value) for value in numbers)}
    else:
        result = {"status": "error", "error": f"unknown action {action!r}"}
    write_json(job_dir / "result.json", result)
