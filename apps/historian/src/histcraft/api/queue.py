"""The Historian's work queue: the CSV imports waiting, being written and just written.

The suite's Queue asks every app ``GET <prefix>api/queue`` (format
``plantcraft-queue/1``, ``plantcraft_sdk.server.queue``). The Historian holds no app key and
never calls the suite, so it answers there only: the numbers of now and their history, ``url``
(its Imports page, where the panel links) and ``items``, each file of an import: waiting,
written (with its step and progress), done, failed or cancelled in the last 24 hours. The
collector writes the progress in the archive state ``import:<id>`` (``collector.imports``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from plantcraft_sdk.server.queue import QueueNow

from histcraft.archive.store import ArchiveStore
from histcraft.catalog.models import IMPORT_KIND
from histcraft.catalog.store import CatalogStore
from histcraft.clock import now_ms
from histcraft.collector import imports
from histcraft.config import IMPORTS_DIR

# Finished items listed, in milliseconds.
KEEP_MS = 24 * 3600 * 1000
HOUR_MS = 3600 * 1000
# The queue's status for an import's state (``collector.imports``).
_STATUS = {"running": "running", "done": "done", "error": "failed", "cancelled": "cancelled"}


def _iso(ms: Any) -> str | None:
    if ms is None:
        return None
    return (
        datetime.fromtimestamp(int(ms) / 1000, UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def waiting_file(data_dir: Path, import_id: str) -> Path:
    return Path(data_dir) / IMPORTS_DIR / f"{import_id}.csv"


def import_status(state: dict[str, Any], waiting: bool) -> str:
    """An import's queue status: queued while its file waits and nothing runs, else its state's."""

    if state.get("status") == "running":
        return "running"
    if waiting:
        return "queued"
    return _STATUS.get(str(state.get("status") or ""), "done")


def items(
    catalog: CatalogStore, archive: ArchiveStore, data_dir: Path, root: str = "/hist"
) -> list[dict[str, Any]]:
    """Each import's file in the queue now or finished in the last 24 hours, newest first."""

    states = archive.state()
    now = now_ms()
    out = []
    for source in catalog.sources():
        if source["kind"] != IMPORT_KIND:
            continue
        state = states.get(imports.state_key(source["id"])) or {}
        path = waiting_file(data_dir, source["id"])
        waiting = path.exists()
        status = import_status(state, waiting)
        if status in ("done", "failed", "cancelled"):
            if not state or now - int(state.get("finished") or 0) > KEEP_MS:
                continue
        total = int(state.get("total") or 0)
        progress = None
        if status == "running" and total:
            progress = round(min(1.0, int(state.get("done") or 0) / total), 3)
        elif status == "done":
            progress = 1.0
        queued_at = int(path.stat().st_mtime * 1000) if status == "queued" else None
        item = {
            "id": source["id"],
            "name": source["name"],
            "by": state.get("by") or source["options"].get("imported_by") or "",
            "status": status,
            "progress": progress,
            "step": state.get("step") if status == "running" else state.get("detail") or "",
            "file_name": state.get("file_name") or source["options"].get("file_name") or "",
            "url": f"{root}/sources/{source['id']}",
            "started_at": _iso(state.get("started")) if status != "queued" else None,
            "finished_at": _iso(state.get("finished"))
            if status in ("done", "failed", "cancelled")
            else None,
            "queued_at": _iso(queued_at),
        }
        if status == "queued":
            item["cancel"] = {
                "label": "Cancel",
                "method": "POST",
                "href": f"{root}/api/imports/{source['id']}/cancel",
            }
        out.append(item)
    order = {"running": 0, "queued": 1}
    return sorted(
        out,
        key=lambda item: (
            order.get(item["status"], 2),
            -(datetime.fromisoformat(stamp).timestamp())
            if (stamp := item["finished_at"] or item["started_at"] or item["queued_at"])
            else 0,
        ),
    )


def queue_now(
    catalog: CatalogStore,
    archive: ArchiveStore,
    data_dir: Path,
    since: datetime | None = None,
) -> QueueNow:
    """The numbers of now: files waiting and written, done and failed since ``since`` (the
    sampler's last sample) and in the last hour, the oldest file's wait."""

    now = now_ms()
    since_ms = int(since.timestamp() * 1000) if since else now - 15_000
    found = items(catalog, archive, data_dir)
    queued = [item for item in found if item["status"] == "queued"]
    running = [item for item in found if item["status"] == "running"]

    def finished(status: str, after: int) -> list[dict[str, Any]]:
        return [
            item
            for item in found
            if item["status"] == status
            and item["finished_at"]
            and datetime.fromisoformat(item["finished_at"]).timestamp() * 1000 > after
        ]

    done = finished("done", since_ms)
    times = [
        datetime.fromisoformat(item["finished_at"]).timestamp()
        - datetime.fromisoformat(item["started_at"]).timestamp()
        for item in done
        if item["started_at"]
    ]
    oldest = min(
        (datetime.fromisoformat(item["queued_at"]).timestamp() for item in queued), default=None
    )
    return QueueNow(
        queued=len(queued),
        running=len(running),
        workers=1,
        busy=min(1, len(running)),
        done=len(done),
        failed=len(finished("failed", since_ms)),
        cancelled=len(finished("cancelled", since_ms)),
        done_hour=len(finished("done", now - HOUR_MS)),
        failed_hour=len(finished("failed", now - HOUR_MS)),
        cancelled_hour=len(finished("cancelled", now - HOUR_MS)),
        delay_seconds=round(max(0.0, now / 1000 - oldest), 1) if oldest is not None else 0.0,
        average_seconds=round(sum(times) / len(times), 3) if times else None,
    )
