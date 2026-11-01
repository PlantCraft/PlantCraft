"""Trackings: a model run against the plant on a schedule, its error kept as a signal (M3).

A tracking names a model, the signals that feed its inputs and the signals its variables are
compared with, a window (the last hour by default) and how often it runs (every 15 minutes by
default). Each time it is due, Models reads the window through PlantCraft with its service token
(``runs/plant.py``) and queues a simulation like any other (labelled with the tracking). When
the simulation ends, the error of each compared variable (model minus plant, at the plant's
times) is written to the Historian as a derived signal, ``app-modelcraft:tracking-<id>.<variable>
.error``, so it trends, exports and alarms like any signal; its mean absolute error, bias, largest
and last error are kept on the tracking.

A tracking may set a limit on the mean absolute error of each variable: above it, the condition
``tracking.mismatch`` opens (one event per variable, key ``tracking:<id>:<variable>``) and it
closes when the error is back under the limit. Alarms decides whether anyone hears it. Only the
last ``KEEP_RUNS`` simulations of a tracking are kept: the signal is its history.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from plantcraft_sdk.server.store import Store

from modelcraft.i18n import t

LOGGER = logging.getLogger(__name__)
KEEP_RUNS = 20
TICK_SECONDS = 30.0
SIGNAL_PREFIX = "app-modelcraft:tracking-"
_PART = re.compile(r"[^A-Za-z0-9_.-]+")


def error_signal(tracking_id: str, variable: str) -> str:
    """The derived signal that holds a tracking's error of one variable."""

    return f"{SIGNAL_PREFIX}{tracking_id}.{_PART.sub('_', variable)}.error"


def errors(
    model_time: list[float],
    model_values: list[float | None],
    plant_time: list[float],
    plant_values: list[float],
) -> tuple[list[float], list[float]]:
    """Model minus plant at each plant time inside the simulated span (model interpolated)."""

    pairs = [(t, v) for t, v in zip(model_time, model_values, strict=False) if v is not None]
    if len(pairs) < 2 or not plant_time:
        return [], []
    mt = np.array([t for t, _ in pairs], dtype=float)
    mv = np.array([v for _, v in pairs], dtype=float)
    pt = np.array(plant_time, dtype=float)
    pv = np.array(plant_values, dtype=float)
    inside = (pt >= mt[0]) & (pt <= mt[-1]) & np.isfinite(pv)
    if not inside.any():
        return [], []
    at = pt[inside]
    return at.tolist(), (np.interp(at, mt, mv) - pv[inside]).tolist()


def summary(values: list[float]) -> dict[str, float | int | None]:
    """Mean absolute error, bias (mean error), largest absolute error, last error, count."""

    if not values:
        return {"mae": None, "bias": None, "max": None, "last": None, "n": 0}
    array = np.array(values, dtype=float)
    return {
        "mae": float(np.mean(np.abs(array))),
        "bias": float(np.mean(array)),
        "max": float(np.max(np.abs(array))),
        "last": float(array[-1]),
        "n": int(array.size),
    }


class TrackingStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS trackings (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        model TEXT NOT NULL,
        name TEXT NOT NULL,
        config_json TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        next_at TEXT NOT NULL,
        last_json TEXT NOT NULL DEFAULT '{}',
        open_json TEXT NOT NULL DEFAULT '[]',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS trackings_due ON trackings (enabled, next_at);
    """

    def create(
        self, project_id: str, model: str, name: str, config: dict[str, Any], *, by: str
    ) -> dict[str, Any]:
        now = self._now()
        tracking_id = uuid.uuid4().hex[:12]
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO trackings (id, project_id, model, name, config_json, next_at,"
                " created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tracking_id, project_id, model, name, self._json(config), now, by, now, now),
            )
        return self.get(tracking_id)  # type: ignore[return-value]

    def update(self, tracking_id: str, **fields: Any) -> dict[str, Any] | None:
        columns = {
            "name": fields.get("name"),
            "config_json": self._json(fields["config"]) if "config" in fields else None,
            "enabled": int(fields["enabled"]) if "enabled" in fields else None,
            "next_at": fields.get("next_at"),
            "last_json": self._json(fields["last"]) if "last" in fields else None,
            "open_json": self._json(fields["open"]) if "open" in fields else None,
        }
        changes = {key: value for key, value in columns.items() if value is not None}
        if changes:
            assignments = ", ".join(f"{key} = ?" for key in changes)
            with self._lock, self._connect() as connection:
                connection.execute(
                    f"UPDATE trackings SET {assignments}, updated_at = ? WHERE id = ?",
                    (*changes.values(), self._now(), tracking_id),
                )
        return self.get(tracking_id)

    def get(self, tracking_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM trackings WHERE id = ?", (tracking_id,)
            ).fetchone()
        return _row(row) if row else None

    def list(self, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if project_id:
                rows = connection.execute(
                    "SELECT * FROM trackings WHERE project_id = ? ORDER BY name", (project_id,)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM trackings ORDER BY name").fetchall()
        return [_row(row) for row in rows]

    def due(self, now: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trackings WHERE enabled = 1 AND next_at <= ? ORDER BY next_at",
                (now,),
            ).fetchall()
        return [_row(row) for row in rows]

    def delete(self, tracking_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM trackings WHERE id = ?", (tracking_id,))


def _row(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["config"] = json.loads(item.pop("config_json") or "{}")
    item["last"] = json.loads(item.pop("last_json") or "{}")
    item["open"] = json.loads(item.pop("open_json") or "[]")
    item["enabled"] = bool(item["enabled"])
    item["signals"] = {
        name: error_signal(item["id"], name) for name in (item["config"].get("compare") or {})
    }
    return item


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class Tracker:
    """Starts the trackings when due and turns their finished simulations into signals.

    ``start(tracking, start, end)`` queues the simulation and answers the run (it reads the
    plant); ``series(run_id, names)`` answers the run's results of ``names``; ``compare(run_id)``
    its plant series; ``client()`` the service client or None; ``events`` posts the mismatch
    conditions; ``delete_run`` removes an old simulation.
    """

    def __init__(
        self,
        store: TrackingStore,
        runs: Any,
        *,
        start: Callable[[dict[str, Any], datetime, datetime], dict[str, Any]],
        series: Callable[[str, list[str]], dict[str, Any]],
        compare: Callable[[str], dict[str, Any]],
        client: Callable[[], Any],
        events: Callable[[Any, list[dict[str, Any]]], None],
        delete_run: Callable[[str], None],
    ):
        self.store = store
        self.runs = runs
        self._start = start
        self._series = series
        self._compare = compare
        self._client = client
        self._events = events
        self._delete_run = delete_run
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # The schedule ----------------------------------------------------------------------

    def tick(self, now: datetime | None = None) -> int:
        """Start every tracking that is due; answers how many started."""

        now = now or datetime.now(UTC)
        started = 0
        for tracking in self.store.due(_stamp(now)):
            config = tracking["config"]
            every = timedelta(minutes=float(config.get("every_minutes") or 15))
            self.store.update(tracking["id"], next_at=_stamp(now + every))
            started += self.run_now(tracking, now)
        return started

    def run_now(self, tracking: dict[str, Any], now: datetime | None = None) -> int:
        """Queue one simulation of ``tracking`` over its window ending ``now``; 1 if queued."""

        now = now or datetime.now(UTC)
        window = timedelta(minutes=float(tracking["config"].get("window_minutes") or 60))
        try:
            run = self._start(tracking, now - window, now)
        except Exception as exc:  # noqa: BLE001 - said on the tracking, tried again when due
            LOGGER.warning("Tracking %s did not start: %s", tracking["id"], exc)
            self.store.update(
                tracking["id"],
                last={**tracking["last"], "status": "failed", "detail": str(exc)[:300],
                      "at": _stamp(now)},
            )  # fmt: skip
            return 0
        self.store.update(
            tracking["id"],
            last={**tracking["last"], "status": "queued", "run_id": run["id"], "at": _stamp(now),
                  "detail": ""},
        )  # fmt: skip
        return 1

    def begin(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="modelcraft-tracker", daemon=True)
        self._thread.start()

    def end(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the next tick tries again
                LOGGER.exception("Trackings not checked")

    # A finished simulation -------------------------------------------------------------

    def finished(self, run: dict[str, Any]) -> dict[str, Any] | None:
        """A run ended: when it belongs to a tracking, write its errors; the tracking."""

        tracking_id = (run.get("options") or {}).get("tracking")
        if not tracking_id or run.get("status") not in ("done", "failed", "cancelled"):
            return None
        tracking = self.store.get(str(tracking_id))
        if tracking is None:
            return None
        at = run.get("finished_at") or _stamp(datetime.now(UTC))
        if run["status"] != "done":
            last = {**tracking["last"], "status": run["status"], "run_id": run["id"], "at": at,
                    "detail": (run.get("summary") or "")[:300]}  # fmt: skip
            updated = self.store.update(tracking["id"], last=last)
            self._prune(tracking["id"])
            return updated
        origin = datetime.fromisoformat(
            str((run.get("options") or {}).get("plant", {}).get("start")).replace("Z", "+00:00")
        )
        compare = self._compare(run["id"])
        names = [name for name in tracking["config"].get("compare") or {} if name in compare]
        results = {item["name"]: item for item in self._series(run["id"], names).get("series", [])}
        metrics: dict[str, Any] = {}
        items = []
        for name in names:
            model = results.get(name) or {}
            plant = compare[name]
            times, values = errors(
                model.get("time") or [], model.get("values") or [], plant["time"], plant["values"]
            )
            metrics[name] = summary(values)
            if times:
                items.append(
                    {
                        "signal": error_signal(tracking["id"], name),
                        "name": f"{tracking['name']}: {name} error (model - plant)"[:200],
                        "t": [_stamp(origin + timedelta(seconds=s)) for s in times],
                        "v": values,
                    }
                )
        written, detail = 0, ""
        client = self._client()
        if client is not None and items:
            try:
                written = int(client.put_series(items).get("written") or 0)
            except Exception as exc:  # noqa: BLE001 - kept on the tracking; the next run writes
                detail = t("The error signals were not written: {error}", error=exc)[:300]
                LOGGER.warning("Tracking %s: %s", tracking["id"], detail)
        opened = self._judge(client, tracking, metrics)
        last = {"status": "done", "run_id": run["id"], "at": at, "metrics": metrics,
                "written": written, "detail": detail}  # fmt: skip
        updated = self.store.update(tracking["id"], last=last, open=opened)
        self._prune(tracking["id"])
        return updated

    def _judge(self, client: Any, tracking: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
        """Open or close ``tracking.mismatch`` per variable against its limit; still open."""

        limits = tracking["config"].get("limits") or {}
        before = set(tracking.get("open") or [])
        now: set[str] = set()
        for name, limit in limits.items():
            mae = (metrics.get(name) or {}).get("mae")
            if mae is None:
                if name in before:
                    now.add(name)  # no answer is not good news: it stays open
                continue
            if math.isfinite(mae) and mae > float(limit):
                now.add(name)
        changes = []
        for name in sorted(now - before):
            mae = metrics[name]["mae"]
            text = t(
                "{tracking}: {name} off the plant by {mae} on average (limit {limit})",
                tracking=tracking["name"],
                name=name,
                mae=f"{mae:.4g}",
                limit=f"{float(limits[name]):.4g}",
            )
            changes.append(("start", name, text, mae))
        for name in sorted(before - now):
            text = t("{tracking}: {name} back with the plant", tracking=tracking["name"], name=name)
            changes.append(("end", name, text, (metrics.get(name) or {}).get("mae")))
        if client is not None and changes:
            try:
                self._events(
                    client,
                    [
                        {
                            "phase": phase,
                            "key": f"tracking:{tracking['id']}:{name}",
                            "summary": text,
                            "payload": {
                                "tracking_id": tracking["id"],
                                "variable": name,
                                "mae": mae,
                                "limit": float(limits.get(name) or 0),
                                "signal": error_signal(tracking["id"], name),
                            },
                        }
                        for phase, name, text, mae in changes
                    ],
                )
            except Exception:  # noqa: BLE001 - said again at the next run
                LOGGER.warning("Mismatch of tracking %s not posted", tracking["id"], exc_info=True)
                return sorted(before)
        return sorted(now)

    def _prune(self, tracking_id: str) -> None:
        runs = [
            run
            for run in self.runs.list(kind="simulate", limit=2000)
            if (run.get("options") or {}).get("tracking") == tracking_id
            and run["status"] not in ("queued", "running")
        ]
        runs.sort(key=lambda run: run.get("created_at") or "", reverse=True)
        for run in runs[KEEP_RUNS:]:
            try:
                self._delete_run(run["id"])
            except Exception:  # noqa: BLE001 - tried again after the next run
                LOGGER.warning("Old simulation %s of a tracking not deleted", run["id"])
