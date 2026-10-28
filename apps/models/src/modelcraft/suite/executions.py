"""Models's runs on PlantCraft's Executions page (``PUT /api/v1/runs``)."""

from __future__ import annotations

from typing import Any

RUN_STATUSES = ("queued", "running", "done", "failed", "cancelled")


def run_name(run: dict[str, Any]) -> str:
    kind = "Simulation" if run["kind"] == "simulate" else "FMU export"
    return f"{kind} of {run['model'].rpartition('.')[2]}"


def put_run(client: Any, run: dict[str, Any], root_path: str) -> str:
    """Report one run; answers the name it was given."""

    name = run_name(run)
    status = run["status"] if run["status"] in RUN_STATUSES else "running"
    item = {
        "id": run["id"],
        "name": name[:200],
        "status": status,
        "trigger": "manual",
        "started_at": run.get("started_at") or run["created_at"],
        "finished_at": run.get("finished_at"),
        "subjects": [],
        "summary": (run.get("summary") or "")[:300],
        "url": f"{root_path}/runs/{run['id']}",
    }
    # For the suite's Queue (plantcraft-sdk 0.53.0, docs/quick-access.md): who started it, so
    # PlantCraft tells them when it ends, and Cancel while it waits or runs.
    if run.get("created_by"):
        item["by"] = run["created_by"]
    if status in ("queued", "running"):
        item["cancel"] = f"{root_path}/api/runs/{run['id']}/cancel"
    client.put_runs([item])
    return name
