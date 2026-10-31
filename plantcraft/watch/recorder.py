"""The suite's health as signals: PlantCraft writes them to the Historian every minute.

Each minute it turns what the watch already reads (``metrics.json``: Docker's view of every
container and the free disk; the backups and the last drill) and what each server answers on
``GET /api/ops/metrics`` (latency, errors and warnings logged) into values of the Historian's
reserved source ``system`` ("System"), so the trends, the dashboards and the alarms of the
suite read the suite's own health like any plant signal:

- ``system:<service>.up`` (1 running and healthy, 0 otherwise), ``.cpu_pct`` (its CPU as a
  share of the CPUs it may use, 0-100, since 0.6.0; Docker's % of one core before), ``.mem_mb``,
  ``.mem_pct``, ``.restarts`` for every container;
- ``system:<service>.latency_ms`` (p95 of the last requests), ``.errors`` and ``.warnings``
  (logged per minute) for every server that answers its metrics;
- ``system:<service>.queue_items`` and ``.queue_wait_min`` (how long the oldest item has waited)
  for every server that reports a work queue (Link's executions, Models' simulations);
- ``system:host.cpu_pct``, ``.mem_pct`` (the machine's own), ``.disk_free_gb``, ``.disk_free_pct``;
- ``system:backup.age_h`` (the newest good backup), ``.ok`` (the newest backup is good),
  ``.drill_ok`` (the last restore drill passed).

While the Historian is down the values wait in memory, up to 24 h, and go on the next write
that succeeds. The watch (:mod:`plantcraft.watch`) never depends on this: it still tells the
administrators when the Historian is the one down. See docs/operations.md, section 4.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from plantcraft.i18n import t
from plantcraft_sdk.utc import parse_instant

LOGGER = logging.getLogger(__name__)

TICK_SECONDS = 60
# Values kept while the Historian does not answer: 24 h of minutes per signal.
KEEP_SAMPLES = 24 * 60
# What one write to the Historian carries at most (its limits are 500 series, 100,000 values).
WRITE_SERIES = 400
WRITE_VALUES = 80_000
_TAG = re.compile(r"[^A-Za-z0-9_.-]+")

# signal suffix -> (name, unit, low, high)
SERVICE_SIGNALS: dict[str, tuple[str, str, float | None, float | None]] = {
    "up": ("{service} up", "", 0.0, 1.0),
    "cpu_pct": ("{service} CPU of its limit", "%", 0.0, 100.0),
    "mem_mb": ("{service} memory", "MB", 0.0, None),
    "mem_pct": ("{service} memory of its limit", "%", 0.0, 100.0),
    "restarts": ("{service} restarts", "", 0.0, None),
    "latency_ms": ("{service} response time (p95)", "ms", 0.0, None),
    "errors": ("{service} errors logged", "/min", 0.0, None),
    "warnings": ("{service} warnings logged", "/min", 0.0, None),
    "queue_items": ("{service} items in its queue", "", 0.0, None),
    "queue_wait_min": ("{service} wait of the oldest queued item", "min", 0.0, None),
}
OTHER_SIGNALS: dict[str, tuple[str, str, float | None, float | None]] = {
    "host.cpu_pct": ("Machine CPU", "%", 0.0, 100.0),
    "host.mem_pct": ("Machine memory in use", "%", 0.0, 100.0),
    "host.disk_free_gb": ("Free disk", "GB", 0.0, None),
    "host.disk_free_pct": ("Free disk", "%", 0.0, 100.0),
    "backup.age_h": ("Age of the last good backup", "h", 0.0, None),
    "backup.ok": ("Last backup good", "", 0.0, 1.0),
    "backup.drill_ok": ("Last restore drill passed", "", 0.0, 1.0),
}


# Where each server of the suite answers inside the suite's network: its Compose service, port
# and prefix (deploy/compose.yaml). PLANTCRAFT_OPS_URLS (``service=url`` pairs) adds or
# replaces entries; an app installed from a package has only Docker's view (no latency).
SERVER_URLS = {
    "histcraft": "http://histcraft:8100/hist",
    "linkcraft": "http://linkcraft:8140/link",
    "dashcraft": "http://dashcraft:8080/dash",
    "alarmcraft": "http://alarmcraft:8110/alarm",
    "modelcraft": "http://modelcraft:8130/model",
    "doccraft": "http://doccraft:8150/doc",
}
OPS_TOKEN_SECONDS = 120


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def service_tag(name: str) -> str:
    """A container's service name as the start of a signal tag (``histcraft-db``)."""

    return _TAG.sub("-", name).strip("-")[:60]


class HealthRecorder:
    """Builds one sample a minute and writes what is waiting to the Historian."""

    def __init__(
        self,
        desk: Any,
        write: Callable[[list[dict[str, Any]]], dict[str, Any]],
        servers: Callable[[], dict[str, dict[str, Any]]],
        *,
        clock: Callable[[], datetime] = utcnow,
        conditions: Callable[[dict[str, dict[str, Any]]], Any] | None = None,
    ):
        """``desk`` reads the installer's status (``OperationsDesk``); ``write`` sends series
        to the Historian (``POST /api/v1/data/system``) and raises when it cannot; ``servers``
        answers ``{service: GET /api/ops/metrics}`` for the servers that answered;
        ``conditions`` gets, each minute, ``{app: metrics}`` of the apps whose metrics carry
        conditions or an event catalog (``plantcraft.events.conditions.ConditionRelay``)."""

        self.desk = desk
        self.write = write
        self.servers = servers
        self.clock = clock
        self.conditions = conditions
        # app -> its metrics, when they carry conditions or a catalog (last minute's)
        self.reported: dict[str, dict[str, Any]] = {}
        # signal -> [(iso time, value)], oldest first
        self.pending: dict[str, list[tuple[str, float | None]]] = {}
        # service -> (time, errors, warnings): the last counters, for rates
        self._counters: dict[str, tuple[datetime, int, int]] = {}
        # service -> the queue its metrics carried last minute (the watch reads it)
        self.queues: dict[str, dict[str, Any]] = {}
        # service -> errors it logged a minute, last measured (the watch's load checks read it)
        self.error_rates: dict[str, float] = {}
        self._lock = threading.Lock()
        self.last: dict[str, Any] = {"at": None, "written": 0, "error": None, "waiting": 0}

    # One sample -----------------------------------------------------------------------------

    def sample(self, now: datetime) -> dict[str, float | None]:
        """``{signal: value}`` for this minute; empty when there is nothing to read (a local
        run without the installer)."""

        values: dict[str, float | None] = {}
        metrics = self.desk.read("metrics.json")
        fresh = isinstance(metrics, dict) and not metrics.get("error")
        at = parse_instant((metrics or {}).get("at")) if fresh else None
        if at is not None and (now - at).total_seconds() <= 180:
            for item in metrics.get("services") or []:
                name = service_tag(str(item.get("service") or ""))
                if not name:
                    continue
                running = item.get("state") == "running"
                healthy = str(item.get("health") or "") in ("", "healthy")
                values[f"{name}.up"] = 1.0 if running and healthy else 0.0
                # The share of the CPUs it may use (0-100); an older installer wrote only
                # Docker's % of one core, which is kept as it is.
                load = item.get("cpu_load_pct")
                values[f"{name}.cpu_pct"] = _number(
                    load if load is not None else item.get("cpu_pct")
                )
                memory = _number(item.get("mem_bytes"))
                values[f"{name}.mem_mb"] = round(memory / 2**20, 1) if memory is not None else None
                values[f"{name}.mem_pct"] = _number(item.get("mem_pct"))
                values[f"{name}.restarts"] = _number(item.get("restarts"))
            host = metrics.get("host") or {}
            values["host.cpu_pct"] = _number(host.get("cpu_pct"))
            values["host.mem_pct"] = _number(host.get("mem_pct"))
            disk = metrics.get("disk") or {}
            free = _number(disk.get("free_bytes"))
            if free is not None:
                values["host.disk_free_gb"] = round(free / 2**30, 2)
            values["host.disk_free_pct"] = _number(disk.get("free_pct"))
        queues: dict[str, dict[str, Any]] = {}
        rates: dict[str, float] = {}
        reported: dict[str, dict[str, Any]] = {}
        for service, answer in self._servers().items():
            name = service_tag(service)
            if "conditions" in answer or "events" in answer:
                reported[str(answer.get("app") or service)] = answer
            requests = answer.get("requests") or {}
            values[f"{name}.latency_ms"] = _number(requests.get("p95_ms"))
            queue = answer.get("queue")
            if isinstance(queue, dict):
                queues[service] = queue
                values[f"{name}.queue_items"] = _number(queue.get("queued"))
                wait = _number(queue.get("delay_seconds"))
                values[f"{name}.queue_wait_min"] = round(wait / 60, 1) if wait is not None else None
            logs = answer.get("logs") or {}
            errors, warnings = int(logs.get("error") or 0), int(logs.get("warning") or 0)
            before = self._counters.get(name)
            self._counters[name] = (now, errors, warnings)
            if before is not None:
                minutes = max((now - before[0]).total_seconds() / 60, 1 / 60)
                # A restarted server counts from zero again: its new count is the rate's base.
                new_errors = errors - before[1] if errors >= before[1] else errors
                new_warnings = warnings - before[2] if warnings >= before[2] else warnings
                values[f"{name}.errors"] = rates[service] = round(new_errors / minutes, 2)
                values[f"{name}.warnings"] = round(new_warnings / minutes, 2)
        self.queues = queues
        self.error_rates = rates
        self.reported = reported
        values.update(self._backups(now))
        return {key: value for key, value in values.items() if key}

    def _servers(self) -> dict[str, dict[str, Any]]:
        try:
            found = self.servers()
        except Exception:  # a server that does not answer only misses its latency
            LOGGER.exception("health signals: reading the servers' metrics failed")
            return {}
        return {k: v for k, v in (found or {}).items() if isinstance(v, dict)}

    def _backups(self, now: datetime) -> dict[str, float | None]:
        overview = self.desk.overview()
        backups = [item for item in overview.get("backups") or [] if isinstance(item, dict)]
        if not backups and overview.get("drill") is None:
            return {}
        values: dict[str, float | None] = {}
        dated = [
            (moment, item) for item in backups if (moment := parse_instant(item.get("created_at")))
        ]
        good = [moment for moment, item in dated if item.get("state") == "ok"]
        if good:
            values["backup.age_h"] = round((now - max(good)).total_seconds() / 3600, 2)
        if dated:
            newest = max(dated, key=lambda pair: pair[0])[1]
            values["backup.ok"] = 1.0 if newest.get("state") == "ok" else 0.0
        drill = overview.get("drill") or {}
        if drill.get("state"):
            values["backup.drill_ok"] = 1.0 if drill.get("state") == "ok" else 0.0
        return values

    # A tick ---------------------------------------------------------------------------------

    def tick(self) -> int:
        """Samples once and writes everything waiting; the values written."""

        with self._lock:
            now = self.clock()
            stamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            for name, value in self.sample(now).items():
                if value is None:
                    continue  # nothing known this minute: a gap, never a made-up value
                waiting = self.pending.setdefault(name, [])
                if waiting and waiting[-1][0] >= stamp:
                    continue
                waiting.append((stamp, value))
                del waiting[:-KEEP_SAMPLES]
            written = self._flush()
            if self.conditions is not None and self.reported:
                try:
                    self.conditions(self.reported)
                except Exception:  # the signals are written all the same
                    LOGGER.exception("health signals: the apps' conditions were not written")
            self.last = {
                **self.last,
                "at": now.isoformat(),
                "waiting": sum(len(items) for items in self.pending.values()),
            }
            return written

    def _flush(self) -> int:
        written = 0
        for batch in self._batches():
            try:
                answer = self.write([self._series(name, items) for name, items in batch]) or {}
            except Exception as exc:  # the Historian is down: the values wait
                self.last = {**self.last, "error": str(exc)[:300]}
                LOGGER.warning("health signals: the Historian did not take them: %s", exc)
                return written
            refused = {
                str(error.get("signal")): error
                for error in answer.get("errors") or []
                if isinstance(error, dict)
            }
            for name, _ in batch:
                error = refused.get(f"system:{name}")
                if error is not None and int(error.get("status") or 0) >= 500:
                    continue  # kept for the next write
                if error is not None:
                    LOGGER.warning("health signals: %s refused: %s", name, error.get("detail"))
                self.pending.pop(name, None)
            written += int(answer.get("written") or 0)
            self.last = {**self.last, "error": None, "written": written}
        return written

    def _batches(self) -> list[list[tuple[str, list[tuple[str, float | None]]]]]:
        batches: list[list[tuple[str, list[tuple[str, float | None]]]]] = [[]]
        values = 0
        for name, items in sorted(self.pending.items()):
            if not items:
                continue
            if batches[-1] and (
                len(batches[-1]) >= WRITE_SERIES or values + len(items) > WRITE_VALUES
            ):
                batches.append([])
                values = 0
            batches[-1].append((name, items))
            values += len(items)
        return [batch for batch in batches if batch]

    @staticmethod
    def _series(name: str, items: list[tuple[str, float | None]]) -> dict[str, Any]:
        service, _, suffix = name.rpartition(".")
        if name in OTHER_SIGNALS:
            label, unit, low, high = OTHER_SIGNALS[name]
            title = t(label)
        else:
            label, unit, low, high = SERVICE_SIGNALS.get(
                suffix, ("{service} " + suffix, "", None, None)
            )
            title = t(label, service=service)
        return {
            "signal": f"system:{name}",
            "name": title,
            "unit": unit,
            "low": low,
            "high": high,
            "description": t("The suite's own health, written by PlantCraft every minute."),
            "t": [stamp for stamp, _ in items],
            "v": [value for _, value in items],
        }

    def run(self, stop: threading.Event, seconds: float = TICK_SECONDS) -> None:
        while not stop.wait(seconds):
            try:
                self.tick()
            except Exception:  # the recorder never stops for one bad minute
                LOGGER.exception("health signals: tick failed")


def server_urls(text: str | None = None) -> dict[str, str]:
    """The servers to read: ``SERVER_URLS`` with ``PLANTCRAFT_OPS_URLS`` over it."""

    urls = dict(SERVER_URLS)
    raw = os.environ.get("PLANTCRAFT_OPS_URLS", "") if text is None else text
    for entry in raw.split(","):
        name, _, url = entry.strip().partition("=")
        name, url = name.strip(), url.strip().rstrip("/")
        if not name:
            continue
        if url.startswith(("http://", "https://")):
            urls[name] = url
        elif not url:
            urls.pop(name, None)  # ``linkcraft=`` stops reading it
    return urls


class ServerMetrics:
    """``GET /api/ops/metrics`` of every server that runs, with a short token of the ``ops``
    scope (``plantcraft_sdk.server.ops``); PlantCraft's own counters in-process."""

    def __init__(
        self,
        issuer: Any,
        own: Callable[[], dict[str, Any]],
        *,
        urls: dict[str, str] | None = None,
        running: Callable[[], set[str] | None] = lambda: None,
        http: httpx.Client | None = None,
    ):
        """``running`` names the services Docker runs (None: unknown, try them all)."""

        self.issuer = issuer
        self.own = own
        self.urls = server_urls() if urls is None else urls
        self.running = running
        self.http = http or httpx.Client(timeout=5.0)

    def __call__(self) -> dict[str, dict[str, Any]]:
        found = {"processcraft": self.own()}
        running = self.running()
        for service, url in self.urls.items():
            if running is not None and service not in running:
                continue
            token, _ = self.issuer.issue(
                "app:processcraft",
                ttl=OPS_TOKEN_SECONDS,
                audience=service,
                name="PlantCraft monitor",
                apps={service: "viewer"},
                scope="ops",
            )
            try:
                response = self.http.get(
                    f"{url}/api/ops/metrics", headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 200:
                    found[service] = response.json()
            except (httpx.HTTPError, ValueError):
                continue  # down or not answering: Docker's view still says so
        return found
