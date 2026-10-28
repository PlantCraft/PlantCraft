"""Who hears about an alarm: each rule's notifications, silences, the notifications waiting to
go and the limit per person.

Each rule says in its **notify** (``NotifyDraft``) which people and groups hear about its alarms
(``owner``: the alarm's responsible), whether by email too, how long to wait and gather before
sending (the alarms of one rule for the same people go out as one message), and how often to
remind while an alarm stays active and unacknowledged. It may hold **hours** (only inside them, a
day shift; or only outside them, the on-call nights and weekends), in its own time zone, and
**escalation steps**: when nobody acknowledges the alarm within so many minutes, tell more people
(the coordinator of the groups named, a supervisor). Escalation follows the occurrence announced,
so a shift change does not cut it short; acknowledging the alarm stops it.
A **silence** holds back the notifications of matching alarms for a while (a planned shutdown,
a turnaround); the alarms are still raised and shown, unlike shelving. **The limit**: a person
or group gets at most ``LIMIT_PER_HOUR`` messages an hour; past it, one message says how many
more are waiting in Alarms. The ideas follow the public documentation of Grafana Alerting
(notification policies, grouping, mute timings), Prometheus Alertmanager (grouping, inhibition)
and the ISA-18.2 distinction between suppressing an alarm and not paging about it.

| Table | Holds |
|---|---|
| ``silences`` | each silence: what it matches, from when to when, why and who |
| ``outbox`` | one row per alarm, rule (``policy_id`` ``rule:<id>``) and event (raised, cleared, reminder, escalation and its step): waiting, sent (in the notification of ``notice_key``, ``settled_at`` once the alarm is acknowledged or cleared), held by the limit or dropped; kept 30 days |
| ``sends`` | each message sent to each recipient (``message``), each one the limit held back (``held``) and each "limit reached" message (``limit``); kept 30 days |
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plantcraft_sdk.server.store import Migration, Store, add_columns
from plantcraft_sdk.utc import LOCAL
from plantcraft_sdk.utc import zone_of as sdk_zone_of
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alarmcraft.alarms.model import OWNER, Discipline

KEEP_DAYS = 30
MAX_SILENCE_MINUTES = 30 * 24 * 60
# A notification that could not be sent for this long is dropped (the alarm is long known).
GIVE_UP = timedelta(hours=24)
Event = Literal["raised", "cleared", "reminder", "escalation"]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HoursMode = Literal["always", "inside", "outside"]
CLOCK = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$|^24:00$")
# At most this many messages an hour reach one person or group; escalations always go.
LIMIT_PER_HOUR = 6
# Escalation recipients may also name ``coordinator``: the coordinators of the groups the policy
# (or the alarm's owner) names, read from PlantCraft when the step is due.
COORDINATOR = "coordinator"


def _ids(values: list[str], limit: int = 300) -> list[str]:
    found: list[str] = []
    for value in values:
        value = str(value or "").strip()
        if not value or len(value) > limit or any(ord(ch) < 32 for ch in value):
            raise ValueError("ids of 1 to 300 characters")
        if value not in found:
            found.append(value)
    return found


def _recipient_refs(value: list[str], extra: tuple[str, ...] = ("owner",)) -> list[str]:
    found = _ids(value, 110)
    for item in found:
        if item not in extra and not OWNER.match(item):
            raise ValueError(
                "recipients are user:<username>, group:<id>, " + " or ".join(extra) + " (the word)"
            )
    if not found:
        raise ValueError("at least one recipient")
    return found


def minutes_of(clock: str) -> int:
    hours, _, minutes = clock.partition(":")
    return int(hours) * 60 + int(minutes)


class Window(BaseModel):
    """Some days of the week, from a time to a time. A window that ends before it starts runs
    past midnight and belongs to the day it starts on (Friday 17:00 to 07:00 is Friday night)."""

    model_config = ConfigDict(extra="forbid")

    days: list[Day] = Field(min_length=1, max_length=7)
    start: str = "07:00"
    end: str = "17:00"

    @field_validator("start", "end")
    @classmethod
    def _clock(cls, value: str) -> str:
        value = (value or "").strip()
        if not CLOCK.match(value):
            raise ValueError("a time of day as HH:MM (00:00 to 24:00)")
        return value

    @model_validator(mode="after")
    def _span(self) -> Window:
        if self.start == "24:00":
            raise ValueError("a window starts at 23:59 at the latest")
        if minutes_of(self.start) == minutes_of(self.end):
            raise ValueError("a window ends at another time than it starts")
        self.days = sorted(dict.fromkeys(self.days), key=DAYS.index)
        return self


class EscalationStep(BaseModel):
    """When nobody acknowledges the alarm this long after the policy announced it, tell more people."""

    model_config = ConfigDict(extra="forbid")

    after_minutes: int = Field(ge=1, le=24 * 60)
    # ``user:<name>``, ``group:<id>``, ``owner`` or ``coordinator`` (see COORDINATOR).
    recipients: list[str] = Field(min_length=1, max_length=50)
    email: bool = False

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, value: list[str]) -> list[str]:
        return _recipient_refs(value, ("owner", COORDINATOR))


def zone_of(name: str | None) -> ZoneInfo:
    """The policy's time zone: ``local`` (or nothing) is the installation's, as PlantCraft says
    it (owner, 2026-10-27: times in the user's zone, never UTC by default); a name unknown here is
    the installation's too (no crash on an old image)."""

    return sdk_zone_of(name)


def valid_zone(value: str) -> str:
    """A saved zone: ``local`` (the default) or an IANA name this server knows."""

    value = (value or "").strip() or LOCAL
    if value == LOCAL:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("a time zone like America/Sao_Paulo, UTC or local") from exc
    return value


class Delivery(BaseModel):
    """How alarms reach people: who, by email too, how long to gather, reminders, hours and
    escalation. A rule's ``notify`` (``NotifyDraft``) and the policies of an older Alarms."""

    model_config = ConfigDict(extra="forbid")

    # Who: ``user:<name>``, ``group:<id>`` or ``owner`` (each alarm's responsible: the owner the
    # app named in its event, such as the schedule's owner in Link, else the rule's owner).
    recipients: list[str] = Field(default_factory=lambda: ["owner"], min_length=1, max_length=50)
    email: bool = False
    # Wait this long after the first alarm and send what gathered as one notification.
    group_seconds: int = Field(default=300, ge=0, le=3600)
    # Remind while the alarm stays active and unacknowledged; 0 never.
    repeat_minutes: int = Field(default=240, ge=0, le=7 * 24 * 60)
    notify_cleared: bool = False
    # When it sends: always, only inside ``hours`` or only outside them (on-call).
    hours_mode: HoursMode = "always"
    hours: list[Window] = Field(default_factory=list, max_length=14)
    timezone: str = Field(default=LOCAL, max_length=64)
    # Who else hears when nobody acknowledges: steps by minutes after the announcement.
    escalations: list[EscalationStep] = Field(default_factory=list, max_length=5)

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, value: list[str]) -> list[str]:
        return _recipient_refs(value)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        return valid_zone(value)

    @model_validator(mode="after")
    def _hours(self) -> Delivery:
        if self.hours_mode != "always" and not self.hours:
            raise ValueError("add the hours to send in, or send always")
        steps = [step.after_minutes for step in self.escalations]
        if steps != sorted(set(steps)):
            raise ValueError("escalation steps go from the shortest wait to the longest, once each")
        return self


class NotifyDraft(Delivery):
    """A rule's notifications; off: its alarms are shown in Alarms only. ``always_now``: its
    alarms go as they come even when the philosophy keeps their priority for the shift summary."""

    enabled: bool = True
    always_now: bool = False


class SilenceDraft(BaseModel):
    """Hold back the notifications of some alarms for a while."""

    model_config = ConfigDict(extra="forbid")

    areas: list[str] = Field(default_factory=list, max_length=50)
    disciplines: list[Discipline] = Field(default_factory=list, max_length=6)
    alarm_ids: list[str] = Field(default_factory=list, max_length=200)
    minutes: int = Field(ge=1, le=MAX_SILENCE_MINUTES)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("areas", "alarm_ids")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return _ids(value)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = (value or "").strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("say why, in one line")
        return value

    @model_validator(mode="after")
    def _something(self) -> SilenceDraft:
        if not (self.areas or self.disciplines or self.alarm_ids):
            raise ValueError("choose the areas, disciplines or alarms to silence")
        self.disciplines = list(dict.fromkeys(self.disciplines))
        return self


class NoticeStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS silences (
        silence_id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_json TEXT NOT NULL,
        starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        ended_by TEXT
    );
    CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alarm_id TEXT NOT NULL,
        name TEXT NOT NULL,
        policy_id TEXT NOT NULL,
        event TEXT NOT NULL,
        priority TEXT NOT NULL,
        at TEXT NOT NULL,
        value REAL,
        detail TEXT NOT NULL DEFAULT '',
        recipients_json TEXT NOT NULL,
        email INTEGER NOT NULL DEFAULT 0,
        occurrence INTEGER,
        step INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        sent_at TEXT,
        delivered INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        notice_key TEXT,
        settled_at TEXT
    );
    CREATE INDEX IF NOT EXISTS outbox_status ON outbox (status, at);
    CREATE INDEX IF NOT EXISTS outbox_alarm ON outbox (alarm_id, policy_id, at);
    CREATE TABLE IF NOT EXISTS sends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        recipient TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'message'
    );
    CREATE INDEX IF NOT EXISTS sends_recipient ON sends (recipient, at);
    """

    # Changes to tables already shipped: outboxes from before escalation (alarmcraft 0.2.0); the
    # notification policies of an older Alarms, gone since every alarm has a rule (round 11);
    # the notification each row went out in, settled for everyone once the alarm is.
    MIGRATIONS = (
        Migration("columns-before-0.5", add_columns("outbox", {"step": "INTEGER"})),
        Migration("drop-policies", "DROP TABLE IF EXISTS policies"),
        Migration(
            "notice-keys", add_columns("outbox", {"notice_key": "TEXT", "settled_at": "TEXT"})
        ),
    )

    # Silences --------------------------------------------------------------------------

    def _silence(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        return {**self._loads(item.pop("config_json"), {}), **item}

    def silences(self, now: datetime, *, include_ended: bool = False) -> list[dict[str, Any]]:
        """Silences in force at ``now`` (and, with ``include_ended``, those of the last week)."""

        since = (now - timedelta(days=7) if include_ended else now).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM silences WHERE ends_at > ? ORDER BY starts_at DESC", (since,)
            ).fetchall()
        return [self._silence(row) for row in rows]

    def add_silence(self, draft: SilenceDraft, *, now: datetime, by: str) -> dict[str, Any]:
        config = draft.model_dump(mode="json", include={"areas", "disciplines", "alarm_ids"})
        ends = now + timedelta(minutes=draft.minutes)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO silences (config_json, starts_at, ends_at, reason, created_by)"
                " VALUES (?,?,?,?,?)",
                (self._json(config), now.isoformat(), ends.isoformat(), draft.reason, by),
            )
            row = connection.execute(
                "SELECT * FROM silences WHERE silence_id = ?", (cursor.lastrowid,)
            ).fetchone()
        return self._silence(row)

    def end_silence(self, silence_id: int, *, now: datetime, by: str) -> dict | None:
        with self._lock, self._connect() as connection:
            changed = connection.execute(
                "UPDATE silences SET ends_at = ?, ended_by = ? WHERE silence_id = ? AND ends_at > ?",
                (now.isoformat(), by, silence_id, now.isoformat()),
            ).rowcount
            row = connection.execute(
                "SELECT * FROM silences WHERE silence_id = ?", (silence_id,)
            ).fetchone()
        if row is None:
            return None
        return {**self._silence(row), "changed": bool(changed)}

    # Outbox ----------------------------------------------------------------------------

    def queue(
        self,
        alarm: dict[str, Any],
        policy: dict[str, Any],
        event: str,
        *,
        at: str,
        recipients: list[str],
        value: float | None = None,
        detail: str = "",
        occurrence: int | None = None,
        step: int | None = None,
        email: bool | None = None,
        status: str = "pending",
        error: str = "",
    ) -> None:
        if email is None:
            email = bool(policy.get("email"))
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO outbox (alarm_id, name, policy_id, event, priority, at, value, detail,"
                " recipients_json, email, occurrence, step, status, error)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    alarm["alarm_id"],
                    alarm.get("name") or alarm["alarm_id"],
                    policy["policy_id"],
                    event,
                    alarm.get("priority") or "medium",
                    at,
                    value,
                    detail[:500],
                    self._json(sorted(recipients)),
                    1 if email else 0,
                    occurrence,
                    step,
                    status,
                    error[:300],
                ),
            )

    def waiting(self, status: str) -> list[dict[str, Any]]:
        """The rows kept for the shift summary (``digest``) or held as chattering (``chatter``)."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM outbox WHERE status = ? ORDER BY at, id", (status,)
            ).fetchall()
        return [self._outbox(row) for row in rows]

    def raised_for(self, recipient: str, since: str) -> int:
        """How many alarms were raised for ``recipient`` since ``since`` that do not wait for the
        summary (the flood count)."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(DISTINCT alarm_id) AS n FROM outbox, json_each(outbox.recipients_json)"
                " WHERE json_each.value = ? AND at >= ? AND event = 'raised'"
                " AND status NOT IN ('digest', 'chatter', 'dropped')",
                (recipient, since),
            ).fetchone()
        return int(row["n"]) if row else 0

    def pending(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM outbox WHERE status = 'pending' ORDER BY at, id"
            ).fetchall()
        return [self._outbox(row) for row in rows]

    def _outbox(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        item["recipients"] = self._loads(item.pop("recipients_json"), [])
        item["email"] = bool(item["email"])
        return item

    def finish(
        self,
        ids: list[int],
        status: str,
        *,
        at: str,
        delivered: int = 0,
        error: str = "",
        key: str | None = None,
    ) -> None:
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        cutoff = (datetime.fromisoformat(at) - timedelta(days=KEEP_DAYS)).isoformat()
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE outbox SET status = ?, sent_at = ?, delivered = ?, error = ?,"
                f" notice_key = ?, settled_at = NULL WHERE id IN ({marks})",
                (status, at, delivered, error[:300], key, *ids),
            )
            connection.execute("DELETE FROM outbox WHERE at < ? AND status != 'pending'", (cutoff,))

    def note_error(self, ids: list[int], error: str) -> None:
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE outbox SET error = ? WHERE id IN ({marks})", (error[:300], *ids)
            )

    def unsettled(self) -> dict[str, list[dict[str, Any]]]:
        """The rows of every notification sent and not yet settled, by its key."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM outbox WHERE status = 'sent' AND notice_key IS NOT NULL"
                " AND settled_at IS NULL ORDER BY id"
            ).fetchall()
        found: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = self._outbox(row)
            found.setdefault(item["notice_key"], []).append(item)
        return found

    def settle(self, key: str, at: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE outbox SET settled_at = ? WHERE notice_key = ? AND settled_at IS NULL",
                (at, key),
            )

    def last_queued(self, alarm_id: str, policy_id: str) -> str | None:
        """When the alarm last went into this policy's outbox (raised or reminded)."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(at) AS at FROM outbox WHERE alarm_id = ? AND policy_id = ?"
                " AND event IN ('raised', 'reminder') AND status != 'dropped'",
                (alarm_id, policy_id),
            ).fetchone()
        return row["at"] if row else None

    def announced(
        self, alarm_id: str, policy_id: str, occurrence: int | None
    ) -> tuple[str | None, set[int]]:
        """When this policy announced the occurrence (its raise, else its first reminder, as for an
        alarm handed over at a shift change) and the escalation steps already queued for it."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT MIN(at) AS at FROM outbox WHERE alarm_id = ? AND policy_id = ?"
                " AND occurrence IS ? AND event IN ('raised', 'reminder') AND status != 'dropped'",
                (alarm_id, policy_id, occurrence),
            ).fetchone()
            steps = connection.execute(
                "SELECT DISTINCT step FROM outbox WHERE alarm_id = ? AND policy_id = ?"
                " AND occurrence IS ? AND event = 'escalation'",
                (alarm_id, policy_id, occurrence),
            ).fetchall()
        return (row["at"] if row else None), {item["step"] for item in steps}

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM outbox ORDER BY at DESC, id DESC LIMIT ?",
                (max(1, min(limit, 2000)),),
            ).fetchall()
        return [self._outbox(row) for row in rows]

    # The limit per person --------------------------------------------------------------

    def sent_since(self, recipient: str, since: str, *, kind: str = "message") -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM sends WHERE recipient = ? AND at >= ? AND kind = ?",
                (recipient, since, kind),
            ).fetchone()
        return int(row["n"]) if row else 0

    def note_sent(self, recipients: list[str], at: str, *, kind: str = "message") -> None:
        cutoff = (datetime.fromisoformat(at) - timedelta(days=KEEP_DAYS)).isoformat()
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT INTO sends (at, recipient, kind) VALUES (?,?,?)",
                [(at, recipient, kind) for recipient in recipients],
            )
            connection.execute("DELETE FROM sends WHERE at < ?", (cutoff,))

    def limited(self, since: str) -> list[dict[str, Any]]:
        """Who reached the limit since ``since``, and how many messages it held back from them."""

        with self._connect() as connection:
            rows = connection.execute(
                "SELECT recipient, COUNT(*) AS n FROM sends WHERE at >= ? AND kind = 'held'"
                " GROUP BY recipient ORDER BY n DESC, recipient",
                (since,),
            ).fetchall()
        return [{"recipient": row["recipient"], "held": int(row["n"])} for row in rows]
