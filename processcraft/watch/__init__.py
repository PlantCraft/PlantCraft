"""The suite's watch: tells the administrators, in Messages, when a part of the suite stops.

Every 30 s it reads what the installer writes (``metrics.json``: Docker's view of every
container, whose health checks call each server's ``/healthz``; the free disk) and what the
operations driver writes (backups, the last drill, the last update), through
:class:`processcraft.apps.operations_desk.OperationsDesk`, and the work queues the servers
report (``queues``: Link's executions, Models' simulations), which must drain. It needs neither HistCraft nor
Dashboards, so it still speaks when they are the ones down.

A check that fails ``grace`` ticks in a row opens an incident: the robot user ``system``
("System") posts it in the conversation "Suite health" with every administrator. When the check
passes again it says so, with how long it lasted. A subject gets at most one message every
10 minutes: an incident opened sooner is kept, silently, with its recovery. Incidents are
stored, so a restart neither repeats nor forgets them. Each incident is also an event of the
platform (``processcraft.service.down`` ... start, then end; ``processcraft/events/catalog.py``),
written whether or not it was posted, so Alarms judges the suite's health with everything else. While the driver runs an operation
(a backup, a restore) or the installer stops writing, the services' checks hold still.
See docs/operations.md, section 4.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from plantcraft_sdk.utc import parse_instant
from processcraft.config import plant_clock
from processcraft.db import Database, Store, utc_text
from processcraft.events.catalog import PLATFORM_APP, SYSTEM, WATCH_EVENTS
from processcraft.i18n import t

LOGGER = logging.getLogger(__name__)

TICK_SECONDS = 30
# metrics.json older than this: the installer stopped writing.
STALE_SECONDS = 180
QUIET_SECONDS = 600
# An operation running longer than this no longer holds the checks still (a crashed driver).
MAINTENANCE_HOURS = 6
DISK_LOW_PCT = 10.0
DISK_OK_PCT = 12.0
# The disk forecast: one sample of the free bytes an hour, the last 7 days kept; a straight line
# through them (at least a day apart) says in how many days the disk fills. Under
# DISK_FULL_DAYS days it is an incident; DISK_FULL_OK_DAYS closes it (hysteresis).
DISK_SAMPLE_SECONDS = 3600
DISK_TREND_DAYS = 7
DISK_TREND_MIN_HOURS = 24
DISK_FULL_DAYS = 30
DISK_FULL_OK_DAYS = 45
BACKUP_HOURS = 26
SYSTEM_USER = "system"
# An update older than this is not announced any more.
UPDATE_NEWS_HOURS = 24
GRACE_DOWN = 3
GRACE_STARTING = 10
# A queue whose oldest item has waited longer than this does not drain.
QUEUE_WAIT_MINUTES = 30
GRACE_QUEUE = 2
_SEVERITY = {item["name"]: item["severity"] for item in SYSTEM}
# Checks of things that come and go with the apps installed (a certificate with its source).
APP_CHECKS = ("service:", "queue:", "cert:")
# Certificates are read once an hour (the Historian's over HTTP); told 30 days before, reminded 7.
CERT_SECONDS = 3600
CERT_SOON_DAYS = 7


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return t("{count} min", count=minutes)
    return t("{hours} h {minutes} min", hours=minutes // 60, minutes=minutes % 60)


def disk_forecast(samples: list[list[Any]], free_bytes: int) -> dict[str, Any] | None:
    """How fast the disk fills, from ``[iso time, free bytes]`` samples (least squares).

    None until the samples span ``DISK_TREND_MIN_HOURS``; ``days_left`` None while the free
    space does not shrink. ``bytes_per_day`` is what the disk loses a day.
    """

    points = [(moment.timestamp() / 86400, float(value)) for at, value in samples
              if (moment := parse_instant(at)) is not None]  # fmt: skip
    if len(points) < 2 or (points[-1][0] - points[0][0]) * 24 < DISK_TREND_MIN_HOURS:
        return None
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    spread = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread if spread else 0.0
    per_day = max(-slope, 0.0)
    days_left = free_bytes / per_day if per_day > 0 else None
    return {
        "bytes_per_day": round(per_day),
        "days_left": None if days_left is None else round(days_left, 1),
        "hours": round((points[-1][0] - points[0][0]) * 24, 1),
    }


@dataclass(frozen=True)
class Check:
    """One thing the watch looks at in a tick: ``bad`` with ``detail``, after ``grace`` ticks."""

    key: str
    subject: str
    bad: bool
    detail: str = ""
    grace: int = GRACE_DOWN


class WatchStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS watch_incidents (
        incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
        check_key TEXT NOT NULL,
        subject TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        -- 1 when "System" posted the incident (so it posts the recovery too).
        notified INTEGER NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_watch_incidents_open
    ON watch_incidents(check_key, closed_at);

    CREATE TABLE IF NOT EXISTS watch_state (
        name TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """

    def open_incidents(self) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watch_incidents WHERE closed_at IS NULL ORDER BY incident_id"
            ).fetchall()
        return {row["check_key"]: dict(row) for row in rows}

    def recent(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watch_incidents ORDER BY incident_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def open(self, check: Check, at: datetime, *, notified: bool) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                """
                INSERT INTO watch_incidents (check_key, subject, detail, opened_at, notified)
                VALUES (?, ?, ?, ?, ?)
                """,
                (check.key, check.subject, check.detail, utc_text(at), int(notified)),
            )

    def update(self, incident_id: int, detail: str) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE watch_incidents SET detail = ? WHERE incident_id = ?",
                (detail, incident_id),
            )

    def close(self, incident_id: int, at: datetime) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "UPDATE watch_incidents SET closed_at = ? WHERE incident_id = ?",
                (utc_text(at), incident_id),
            )

    def get(self, name: str, default: Any = None) -> Any:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM watch_state WHERE name = ?", (name,)
            ).fetchone()
        return self._loads(row["value"], default) if row else default

    def set(self, name: str, value: Any) -> None:
        with self._lock, self._write() as connection:
            connection.execute(
                "INSERT INTO watch_state (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (name, self._json(value)),
            )


class SuiteWatch:
    def __init__(
        self,
        db: Database,
        users: Any,
        messages: Any,
        desk: Any,
        admins: Callable[[], list[str]],
        *,
        queues: Callable[[], dict[str, dict[str, Any]]] | None = None,
        events: Any = None,
        certificates: Callable[[], list[dict[str, Any]]] | None = None,
        compute: Callable[[], list[dict[str, Any]]] | None = None,
        clock: Callable[[], datetime] = utcnow,
    ):
        """``desk`` reads the installer's status (``OperationsDesk``); ``admins`` names the
        administrators to tell, now (people are added to the conversation as they become one);
        ``queues`` answers ``{service: the queue its metrics carry}`` (``HealthRecorder``);
        ``events`` (``EventStore``) records each incident as an event;
        ``certificates`` the suite's certificates (``processcraft.certificates``);
        ``compute`` the apps whose tasks wait with no compute worker able to run them
        (``ComputeStore.waiting_without_worker``)."""

        self.store = WatchStore(db)
        self.users = users
        self.messages = messages
        self.desk = desk
        self.admins = admins
        self.queues = queues
        self.events = events
        self.certificates = certificates
        self.compute = compute
        self._certs: tuple[datetime, list[dict[str, Any]]] | None = None
        self._cert_soon: dict[str, str] = {}
        self.clock = clock
        self._bad: dict[str, int] = {}
        self._restarts: dict[str, int] = {}
        self._last: dict[str, Any] = {"at": None, "checks": [], "held": False}
        self._forecast: dict[str, Any] | None = None
        self._tick_lock = threading.Lock()

    # What is looked at ---------------------------------------------------------------------

    def checks(self, now: datetime) -> tuple[list[Check], bool] | None:
        """This tick's checks, and whether the services' checks hold still; None when there is
        no installer to read (a local run): nothing is watched."""

        metrics = self.desk.read("metrics.json")
        overview = self.desk.overview()
        if metrics is None and not overview["backups"] and overview["drill"] is None:
            return None
        found: list[Check] = []
        held = self._maintenance(overview.get("running"), now)
        at = parse_instant((metrics or {}).get("at"))
        if at is None or (now - at).total_seconds() > STALE_SECONDS:
            since = plant_clock(at, "%H:%M") if at else "?"
            found.append(
                Check("installer", t("Installer"), True,
                      t("no news from the installer since {time}", time=since))
            )  # fmt: skip
            held = True
        elif metrics.get("error"):
            found.append(Check("docker", t("Docker"), True, t("Docker does not answer")))
            held = True
        else:
            found += [
                Check("installer", t("Installer"), False),
                Check("docker", t("Docker"), False),
            ]
            found += self._services(metrics.get("services") or [])
            found += self._disk(metrics.get("disk"))
            found += self._disk_trend(metrics.get("disk"), now)
        found += self._queues()
        found += self._compute()
        found += self._certificates(now)
        found += self._backup(overview, now)
        drill = overview.get("drill") or {}
        if drill:
            problems = drill.get("problems") or []
            found.append(
                Check("drill", t("Restore drill"), drill.get("state") == "failed",
                      problems[0] if problems else t("the last restore drill failed"), grace=1)
            )  # fmt: skip
        return found, held

    @staticmethod
    def _maintenance(running: Any, now: datetime) -> bool:
        if not isinstance(running, dict):
            return False
        started = parse_instant(running.get("started_at"))
        return started is None or now - started < timedelta(hours=MAINTENANCE_HOURS)

    def _services(self, services: list[dict[str, Any]]) -> list[Check]:
        found = []
        for item in services:
            name = str(item.get("service") or "")
            if not name:
                continue
            state, health = str(item.get("state") or ""), str(item.get("health") or "")
            subject = t("Service {name}", name=name)
            restarts = item.get("restarts")
            before = self._restarts.get(name)
            if isinstance(restarts, int):
                self._restarts[name] = restarts
            if state == "created":
                found.append(
                    Check(f"service:{name}", subject, True, t("not started"), grace=GRACE_STARTING)
                )
            elif state != "running":
                code = item.get("exit_code")
                detail = t("{state} (exit code {code})", state=state or "?", code=code)
                found.append(Check(f"service:{name}", subject, True, detail))
            elif health == "unhealthy":
                found.append(Check(f"service:{name}", subject, True, t("its health check fails")))
            elif isinstance(restarts, int) and before is not None and restarts > before:
                detail = t("restarted {count} times", count=restarts)
                found.append(Check(f"service:{name}", subject, True, detail))
            elif health == "starting":
                found.append(
                    Check(f"service:{name}", subject, True, t("still starting"),
                          grace=GRACE_STARTING)
                )  # fmt: skip
            else:
                found.append(Check(f"service:{name}", subject, False))
        return found

    def _queues(self) -> list[Check]:
        if self.queues is None:
            return []
        try:
            queues = self.queues() or {}
        except Exception:  # the other checks go on
            LOGGER.exception("watch: reading the queues failed")
            return []
        found = []
        for service, queue in sorted(queues.items()):
            queued = int(queue.get("queued") or 0)
            wait = float(queue.get("delay_seconds") or 0.0)
            detail = t(
                "{count} items waiting, the oldest for {time}; {running} running on {workers} workers",
                count=queued,
                time=duration(wait),
                running=int(queue.get("running") or 0),
                workers=int(queue.get("workers") or 0),
            )
            bad = queued > 0 and wait > QUEUE_WAIT_MINUTES * 60
            subject = t("Queue of {name}", name=service)
            found.append(Check(f"queue:{service}", subject, bad, detail, grace=GRACE_QUEUE))
        return found

    def _compute(self) -> list[Check]:
        """Tasks that wait more than 2 minutes with no compute worker online able to run them."""

        if self.compute is None:
            return []
        try:
            waiting = self.compute() or []
        except Exception:  # the other checks go on
            LOGGER.exception("watch: reading the compute queue failed")
            return []
        found = []
        apps = {str(item["app"]) for item in waiting}
        details: dict[str, list[str]] = {}
        for item in waiting:
            details.setdefault(str(item["app"]), []).append(
                t(
                    "{count} tasks wait and no compute worker online runs them (version "
                    "{version}, environment {environment}, size {size})",
                    count=int(item.get("queued") or 0),
                    version=item.get("version") or "?",
                    environment=item.get("environment") or "standard",
                    size=item.get("size") or "small",
                )
            )
        for app, lines in sorted(details.items()):
            detail = "; ".join(lines) + t(": add or start one in Settings › Compute")
            subject = t("Compute for {app}", app=app)
            found.append(Check(f"compute:{app}", subject, True, detail, grace=1))
        # An app whose tasks found a worker again: its incident ends.
        opened = {key.removeprefix("compute:") for key in self.store.open_incidents()
                  if key.startswith("compute:")}  # fmt: skip
        for app in sorted(opened - apps):
            found.append(Check(f"compute:{app}", t("Compute for {app}", app=app), False))
        return found

    def certificate_list(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """The certificates with their state, read at most once an hour."""

        from processcraft.certificates import with_state

        now = now or self.clock()
        if self.certificates is None:
            return []
        if self._certs is None or (now - self._certs[0]).total_seconds() >= CERT_SECONDS:
            try:
                items = self.certificates()
            except Exception:  # noqa: BLE001 - a list that cannot be read never stops the watch
                LOGGER.exception("could not read the certificates")
                items = self._certs[1] if self._certs else []
            self._certs = (now, items)
        return with_state(self._certs[1], now)

    def forget_certificates(self) -> None:
        """Read the certificates again on the next look (one was just renewed); the list read
        last stays for when the next read fails."""

        if self._certs is not None:
            self._certs = (datetime.min.replace(tzinfo=timezone.utc), self._certs[1])

    def _certificates(self, now: datetime) -> list[Check]:
        found = []
        self._cert_soon = {}
        for item in self.certificate_list(now):
            if item["days_left"] is None:
                continue
            key = f"cert:{item.get('id')}"
            subject = t("Certificate {name}", name=item.get("name") or item.get("id"))
            date = str(item.get("not_after") or "")[:10]
            left = item["days_left"]
            detail = (
                t("expired on {date}", date=date)
                if left < 0
                else t("expires on {date}, in {days} days", date=date, days=max(0, int(left)))
            )
            bad = item["state"] in ("expiring", "expired")
            found.append(Check(key, subject, bad, detail, grace=1))
            if bad and left < CERT_SOON_DAYS:
                self._cert_soon[key] = t("{subject}: {detail}.", subject=subject, detail=detail)
            elif not bad and self.store.get(f"reminded:{key}"):
                self.store.set(f"reminded:{key}", None)
        return found

    def _remind_certificates(self, now: datetime) -> list[str]:
        """One reminder a week before, on the conversation that told it 30 days before."""

        posted: list[str] = []
        incidents = self.store.open_incidents()
        for key, text in self._cert_soon.items():
            if key in incidents and not self.store.get(f"reminded:{key}"):
                self.store.set(f"reminded:{key}", utc_text(now))
                posted += self._post("🟠 " + text)
        return posted

    def _disk(self, disk: Any) -> list[Check]:
        free = (disk or {}).get("free_pct")
        if not isinstance(free, (int, float)):
            return []
        limit = DISK_OK_PCT if "disk" in self.store.open_incidents() else DISK_LOW_PCT
        gigabytes = round(((disk or {}).get("free_bytes") or 0) / 2**30, 1)
        detail = t("{pct} % free ({gb} GB)", pct=round(free, 1), gb=gigabytes)
        return [Check("disk", t("Disk"), free < limit, detail, grace=1)]

    def _disk_trend(self, disk: Any, now: datetime) -> list[Check]:
        free = (disk or {}).get("free_bytes")
        if not isinstance(free, (int, float)):
            return []
        samples = [item for item in self.store.get("disk_samples", []) if parse_instant(item[0])]
        last = parse_instant(samples[-1][0]) if samples else None
        if last is None or (now - last).total_seconds() >= DISK_SAMPLE_SECONDS:
            samples.append([utc_text(now), int(free)])
        oldest = now - timedelta(days=DISK_TREND_DAYS)
        samples = [item for item in samples if (parse_instant(item[0]) or now) >= oldest]
        self.store.set("disk_samples", samples)
        forecast = disk_forecast(samples, int(free))
        self._forecast = forecast
        if forecast is None or forecast["days_left"] is None:
            return [Check("disk_trend", t("Disk forecast"), False)]
        days = forecast["days_left"]
        limit = DISK_FULL_OK_DAYS if "disk_trend" in self.store.open_incidents() else DISK_FULL_DAYS
        detail = t(
            "the disk fills in about {days} days at {gb} GB a day",
            days=max(1, round(days)),
            gb=round(forecast["bytes_per_day"] / 2**30, 1),
        )
        return [Check("disk_trend", t("Disk forecast"), days < limit, detail, grace=1)]

    def _backup(self, overview: dict[str, Any], now: datetime) -> list[Check]:
        if not (overview.get("schedule") or {}).get("enabled", True):
            return []
        good = [
            moment
            for item in overview.get("backups") or []
            if item.get("state") == "ok" and (moment := parse_instant(item.get("created_at")))
        ]
        first_seen = parse_instant(self.store.get("first_seen")) or now
        newest = max(good) if good else None
        hours = (now - (newest or first_seen)).total_seconds() / 3600
        if newest:
            detail = t("the last good backup is {hours} h old", hours=round(hours))
        else:
            detail = t("there is no good backup yet")
        return [Check("backup", t("Backups"), hours > BACKUP_HOURS, detail, grace=1)]

    # A tick ---------------------------------------------------------------------------------

    def tick(self) -> list[str]:
        """Looks once; returns the messages posted."""

        with self._tick_lock:
            now = self.clock()
            if self.store.get("first_seen") is None:
                self.store.set("first_seen", utc_text(now))
            looked = self.checks(now)
            if looked is None:
                self._last = {"at": utc_text(now), "checks": [], "held": False, "watching": False}
                self.store.set("last_tick", self._last)
                return []
            found, held = looked
            posted: list[str] = []
            incidents = self.store.open_incidents()
            seen = set()
            for check in found:
                seen.add(check.key)
                if held and check.key.startswith(APP_CHECKS):
                    continue
                posted += self._apply(check, incidents.get(check.key), now)
            for key, incident in incidents.items():
                # A service removed (an app uninstalled): its incident ends without a word.
                if key not in seen and key.startswith(APP_CHECKS) and not held:
                    self.store.close(incident["incident_id"], now)
                    self._event(key, "end", incident["subject"], t("removed"))
                    self._bad.pop(key, None)
            if not held:
                posted += self._remind_certificates(now)
            posted += self._announce_update()
            self._last = {
                "at": utc_text(now),
                "watching": True,
                "held": held,
                "checks": [
                    {"key": c.key, "subject": c.subject, "bad": c.bad, "detail": c.detail}
                    for c in found
                ],
            }
            # Kept in the database: with several workers, the one serving the Operations page
            # is not always the one whose watch ticks.
            self.store.set("last_tick", {**self._last, "disk_forecast": self._forecast})
            return posted

    def _apply(self, check: Check, incident: dict[str, Any] | None, now: datetime) -> list[str]:
        if not check.bad:
            self._bad.pop(check.key, None)
            if incident is None:
                return []
            self.store.close(incident["incident_id"], now)
            self._event(check.key, "end", check.subject, check.detail)
            if not incident["notified"]:
                return []
            opened = parse_instant(incident["opened_at"]) or now
            text = "✅ " + t(
                "{subject} is back to normal after {duration}.",
                subject=check.subject,
                duration=duration((now - opened).total_seconds()),
            )
            return self._post(text)
        count = self._bad[check.key] = self._bad.get(check.key, 0) + 1
        if incident is not None:
            if check.detail and check.detail != incident["detail"]:
                self.store.update(incident["incident_id"], check.detail)
            return []
        if count < check.grace:
            return []
        quiet = self.store.get(f"posted:{check.key}")
        last = parse_instant(quiet) if quiet else None
        loud = last is None or (now - last).total_seconds() >= QUIET_SECONDS
        text = "🔴 " + t(
            "{subject}: {detail} (since {time}).",
            subject=check.subject,
            detail=check.detail,
            time=plant_clock(now, "%H:%M"),
        )
        posted = self._post(text) if loud else []
        self.store.open(check, now, notified=bool(posted))
        self._event(check.key, "start", check.subject, check.detail)
        if posted:
            self.store.set(f"posted:{check.key}", utc_text(now))
        return posted

    def _announce_update(self) -> list[str]:
        update = self.desk.read("update.json")
        if not isinstance(update, dict) or not update.get("at"):
            return []
        if self.store.get("update_seen") == update["at"]:
            return []
        self.store.set("update_seen", update["at"])
        moment = parse_instant(update["at"])
        if moment is None or (self.clock() - moment).total_seconds() > UPDATE_NEWS_HOURS * 3600:
            return []  # old news (a database restored from before it)
        state, version = update.get("state"), update.get("to") or "?"
        severity = {"ok": "ok", "returned": "critical", "rolled-back": "info"}.get(str(state))
        if severity:
            self._publish(
                "update.finished",
                phase="instant",
                key="",
                severity=severity,
                summary=t("Update to {version}: {state}", version=version, state=state),
                payload={"state": state, "version": version},
            )
        if state == "ok":
            text = "ℹ️ " + t("The suite was updated to version {version}.", version=version)
        elif state == "returned":
            text = "🔴 " + t(
                "The update to version {version} failed; the suite went back to version "
                "{previous} with its data. {message}",
                version=version,
                previous=update.get("from") or "?",
                message=update.get("message") or "",
            )
        elif state == "rolled-back":
            text = "ℹ️ " + t(
                "The suite was rolled back to version {version}.", version=update.get("to") or "?"
            )
        else:
            return []
        return self._post(text.strip())

    # Events ---------------------------------------------------------------------------------

    def _event(self, key: str, phase: str, subject: str, detail: str) -> None:
        name = WATCH_EVENTS.get(key.split(":", 1)[0])
        if name is None:
            return
        summary = f"{subject}: {detail}" if detail else subject
        payload = {"check": key, "detail": detail}
        # The end of a condition is good news; its start has the catalog's severity.
        severity = "ok" if phase == "end" else _SEVERITY.get(name, "warning")
        self._publish(
            name, phase=phase, key=key, severity=severity, summary=summary, payload=payload
        )

    def _publish(self, name: str, **fields: Any) -> None:
        """One ``processcraft.<name>`` event; a failure is logged, never stops the tick."""

        if self.events is None:
            return
        try:
            self.events.publish(
                f"{PLATFORM_APP}.{name}",
                f"app:{PLATFORM_APP}",
                source=PLATFORM_APP,
                actor=SYSTEM_USER,
                category="system",
                **fields,
            )
        except Exception:
            LOGGER.exception("suite watch: could not record the event %s", name)

    # Messages -------------------------------------------------------------------------------

    def _post(self, text: str) -> list[str]:
        """Posts as "System" to the administrators; [] when there is nobody to tell."""

        try:
            conversation_id = self._conversation()
            if conversation_id is None:
                return []
            self.messages.post(conversation_id, SYSTEM_USER, text, meta={"kind": "watch"})
        except (ValueError, PermissionError) as exc:
            LOGGER.warning("suite watch: could not post: %s", exc)
            return []
        return [text]

    def _conversation(self) -> int | None:
        admins = [name for name in dict.fromkeys(self.admins()) if self.users.get_user(name)]
        if not admins:
            return None
        if (self.users.get_user(SYSTEM_USER) or {}).get("kind") != "system":
            self.users.upsert_user(SYSTEM_USER, t("System"), t("Suite monitor"), kind="system")
        known = self.store.get("conversation_id")
        if isinstance(known, int) and self.messages.get(known) is not None:
            self.messages.add_members(known, admins)
            return known
        started = self.messages.start(SYSTEM_USER, admins, title=t("Suite health"))
        conversation_id = int(started["conversation_id"])
        self.store.set("conversation_id", conversation_id)
        return conversation_id

    # What the Operations page shows ---------------------------------------------------------

    def overview(self) -> dict[str, Any]:
        last = self.store.get("last_tick") or {**self._last, "disk_forecast": self._forecast}
        return {
            **last,
            "open": list(self.store.open_incidents().values()),
            "recent": self.store.recent(),
            "metrics": self.desk.read("metrics.json"),
            "conversation_id": self.store.get("conversation_id"),
            "certificates": self.certificate_list(),
        }

    def run(self, stop: threading.Event, seconds: float = TICK_SECONDS) -> None:
        while not stop.wait(seconds):
            try:
                self.tick()
            except Exception:  # the watch never stops for one bad tick
                LOGGER.exception("suite watch: tick failed")
