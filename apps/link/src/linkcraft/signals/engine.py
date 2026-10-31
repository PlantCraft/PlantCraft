"""The Signal quality algorithm: sync the signals from PlantCraft, read a window of raw
samples, judge every signal with the data quality checks.

Signals are read and judged in batches (``BATCH`` at a time) so memory stays flat on a large
plant; the checks run in LinkCraft's compute pool (worker processes, ``LINKCRAFT_PROCESSES``).
One execution (a run) at a time.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import pandas as pd

from linkcraft.data.samples import SignalReader, iso_utc, naive_utc
from linkcraft.engine.compute import ComputePool
from linkcraft.i18n import t
from linkcraft.signals.assess import assess, plan
from linkcraft.signals.models import STATUSES, SignalQualitySettings
from linkcraft.signals.publish import QualityPublisher
from linkcraft.signals.store import QualityResultStore, SignalStore

LOGGER = logging.getLogger(__name__)
BATCH = 200


class RoundBusy(RuntimeError):
    pass


def usage_from_assets(assets: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """Signal id -> the roles it plays and the assets it belongs to."""

    found: dict[str, dict[str, list[str]]] = {}
    for asset in assets:
        for role, signal_id in (asset.get("signals") or {}).items():
            if not signal_id:
                continue
            entry = found.setdefault(str(signal_id), {"roles": [], "assets": []})
            entry["roles"].append(str(role))
            entry["assets"].append(str(asset.get("name") or asset.get("id")))
    return found


class QualityEngine:
    def __init__(
        self,
        signals: SignalStore,
        results: QualityResultStore,
        *,
        compute: ComputePool | None = None,
        publisher: QualityPublisher | None = None,
    ):
        self.signals = signals
        self.results = results
        self.compute = compute or ComputePool(0)
        self.publisher = publisher
        # PlantCraft's assets as of the last sync (id, name, signals by role).
        self.assets: list[dict[str, Any]] = []
        # Minutes between runs (from the algorithm's schedule): how long results stay valid.
        self.interval_minutes = 15.0
        self._lock = threading.Lock()
        self.progress: dict[str, Any] = {"running": False}
        self.last_sync: dict[str, Any] = {}

    # Pool ---------------------------------------------------------------------

    def _submit(self, tasks: list[dict[str, Any]]) -> Callable[[], list[dict[str, Any]]]:
        """Start judging ``tasks``; the returned function waits for the verdicts.

        With worker processes the next batch is read from PlantCraft while
        this one is judged.
        """

        processes = getattr(self.compute, "processes", 0) or 0
        if processes <= 0 or len(tasks) < 8:
            verdicts = [assess(task) for task in tasks]
            return lambda: verdicts
        # The suite's workers take one chunk per task (``chunks_per_process`` 1): enough chunks
        # to keep every slot busy, few enough that the trips to PlantCraft stay cheap.
        per_process = getattr(self.compute, "chunks_per_process", 4) or 4
        size = max(1, -(-len(tasks) // (processes * per_process)))
        chunks = [tasks[offset : offset + size] for offset in range(0, len(tasks), size)]
        futures = [self.compute.submit(_assess_many, chunk) for chunk in chunks]
        return lambda: [verdict for future in futures for verdict in future.result()]

    # Signals ------------------------------------------------------------------

    def sync(self, plant: SignalReader) -> dict[str, Any]:
        """PlantCraft's signals (and the roles assets give them) into the signal table."""

        signals = plant.signals()
        try:
            assets = plant.assets()
        except Exception as exc:  # Signals still sync when the asset tree cannot be read.
            LOGGER.warning("Assets not read: %s", exc)
            assets = None
        # PlantCraft names signals <source id>:<tag> (D2): rows kept under a bare tag move to
        # the new id with their settings, verdict and history, once.
        renames = self.signals.bare_tag_renames(signals)
        if renames:
            LOGGER.info(
                "Signals renamed by PlantCraft: %d moved to <source>:<tag> ids", len(renames)
            )
            self.results.rename(renames)
            self.signals.rename(renames)
        counts = self.signals.sync(signals, usage_from_assets(assets or []))
        if assets is not None:
            self.assets = assets
        self.last_sync = {
            "status": "ok",
            "found": len(signals),
            **counts,
            "renamed": len(renames),
            "at": pd.Timestamp.now(tz="UTC").isoformat(),
        }
        return self.last_sync

    # Checking -----------------------------------------------------------------

    def window(
        self, plant: SignalReader, signal_ids: list[str], settings: SignalQualitySettings
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        end = plant.data_end(signal_ids)
        return end - pd.Timedelta(hours=settings.window_hours), end

    def check(
        self,
        plant: SignalReader,
        rows: list[dict[str, Any]],
        start: Any,
        end: Any,
        settings: SignalQualitySettings,
        on_batch: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """Verdicts of ``rows`` (signal table rows) over ``[start, end]``."""

        start, end = naive_utc(start), naive_utc(end)
        step = max(1.0, (end - start).total_seconds() / 20000)
        verdicts: list[dict[str, Any]] = []
        # Batches judged while the next is read: one here, more on the suite's workers
        # (``in_flight``), so their slots do not wait for the last answers of a batch.
        depth = max(1, int(getattr(self.compute, "in_flight", 1) or 1))
        waiting: collections.deque[
            tuple[Callable[[], list[dict[str, Any]]], list[dict[str, Any]]]
        ] = collections.deque()

        def finish(
            pending: tuple[Callable[[], list[dict[str, Any]]], list[dict[str, Any]]],
        ) -> None:
            wait, failed = pending
            done = wait() + failed
            stamp = pd.Timestamp.now(tz="UTC").isoformat()
            for verdict in done:
                verdict["checked_at"] = stamp
            if on_batch:
                on_batch(done)
            verdicts.extend(done)

        for offset in range(0, len(rows), BATCH):
            batch = rows[offset : offset + BATCH]
            references = {
                row["id"]: str((row.get("settings") or {}).get("reference") or "") for row in batch
            }
            wanted = [row["id"] for row in batch] + [item for item in references.values() if item]
            samples = plant.read(wanted, start, end, fallback_step=step)
            tasks = []
            failed = []
            for row in batch:
                if row["id"] in samples.failed:
                    failed.append(_failed(row["id"], samples.failed[row["id"]], start, end))
                    continue
                tasks.append(
                    {
                        "signal": row,
                        "values": samples.series.get(row["id"]),
                        "reference": samples.series.get(references[row["id"]]),
                        "start": start,
                        "end": end,
                        "checks": plan(row, settings, samples.series.get(row["id"])),
                        "resampled": row["id"] in samples.resampled,
                        "quality": samples.quality.get(row["id"]),
                    }
                )
            waiting.append((self._submit(tasks), failed))
            if len(waiting) > depth:
                finish(waiting.popleft())
        while waiting:
            finish(waiting.popleft())
        return verdicts

    def run_round(
        self,
        plant: SignalReader,
        settings: SignalQualitySettings,
        *,
        trigger: str = "schedule",
        started_by: str = "",
        sync: bool = True,
    ) -> dict[str, Any]:
        if not self._lock.acquire(blocking=False):
            raise RoundBusy(t("The Signal quality algorithm is already running."))
        round_id = self.results.start_round(trigger, started_by)
        began = time.monotonic()
        verdicts: list[dict[str, Any]] = []
        # A round with nothing to check (no signal yet: a new installation) leaves no run.
        empty = False
        try:
            if sync:
                try:
                    self.sync(plant)
                except Exception as exc:
                    self.last_sync = {"status": "error", "error": str(exc)}
                    if not self.signals.count():
                        raise
            rows = self.signals.list(active_only=True)
            if not rows:
                empty = True
                self.results.discard_round(round_id)
                return {"round": None, "status": "ok", "signals": 0, "counts": {}}
            self.progress = {"running": True, "round": round_id, "done": 0, "total": len(rows)}
            self._publish_run(round_id)
            start, end = self.window(plant, [row["id"] for row in rows], settings)
            counts = dict.fromkeys(STATUSES, 0)

            def keep(batch: list[dict[str, Any]]) -> None:
                self.results.save(batch, round_id)
                verdicts.extend(batch)
                for verdict in batch:
                    counts[verdict["status"]] = counts.get(verdict["status"], 0) + 1
                self.progress["done"] += len(batch)

            self.check(plant, rows, start, end, settings, keep)
            duration = round(time.monotonic() - began, 2)
            self.results.finish_round(
                round_id,
                status="ok",
                window_start=iso_utc(start),
                window_end=iso_utc(end),
                signals=len(rows),
                counts=counts,
                duration_seconds=duration,
            )
            self.publish_results(verdicts, settings)
            return {
                "round": round_id,
                "status": "ok",
                "signals": len(rows),
                "counts": counts,
                "duration_seconds": duration,
            }
        except Exception as exc:
            LOGGER.warning("Signal quality run %s failed: %s", round_id, exc)
            self.results.finish_round(
                round_id,
                status="error",
                error=str(exc)[:500],
                duration_seconds=round(time.monotonic() - began, 2),
            )
            return {"round": round_id, "status": "error", "error": str(exc)}
        finally:
            self.progress = {"running": False}
            self._lock.release()
            if not empty:
                self._publish_run(round_id)

    # Publishing in PlantCraft -------------------------------------------------

    def publish_results(
        self, verdicts: list[dict[str, Any]], settings: SignalQualitySettings
    ) -> None:
        """Results of ``verdicts`` and of the assets holding those signals; never raises."""

        if self.publisher is None or not verdicts:
            return
        try:
            members = {
                str(signal_id)
                for asset in self.assets
                for signal_id in (asset.get("signals") or {}).values()
                if signal_id
            }
            latest = self.results.latest_many(sorted(members)) if members else {}
            self.publisher.results(verdicts, self.assets, latest, self.interval_minutes)
        except Exception:
            LOGGER.exception("Publishing quality results failed")

    def _publish_run(self, round_id: int) -> None:
        if self.publisher is None:
            return
        try:
            row = self.results.round(round_id)
            if row is not None:
                self.publisher.run(row)
        except Exception:
            LOGGER.exception("Publishing round %s failed", round_id)

    @property
    def running(self) -> bool:
        return self._lock.locked()


def _assess_many(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [assess(task) for task in tasks]


def _failed(signal_id: str, reason: str, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    return {
        "signal": signal_id,
        "status": "unknown",
        "quality": None,
        "apt": False,
        "limiting": None,
        "message": t("PlantCraft could not read this signal: {reason}", reason=reason),
        "checks": [],
        "window_start": iso_utc(start),
        "window_end": iso_utc(end),
        "samples": 0,
    }
