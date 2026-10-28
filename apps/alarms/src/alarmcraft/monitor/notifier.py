"""Telling people: each cycle, the alarms raised (and, where the rule asks, cleared) go into
the outbox of their rule's notifications; reminders join for alarms still active and
unacknowledged; and what waited its gathering time goes to PlantCraft as one notification per
rule and recipients (``POST /api/v1/notifications``). PlantCraft puts it in each person's
Messages and, when its email is set up and the person allows it, sends an email. One alarm's
notifications share one conversation in Messages (its ``key``, ``alarm:<id>:<occurrence>``);
a message gathering several alarms of a rule is the rule's conversation of that hour. Its
**Acknowledge** button POSTs the acknowledgement as the person who clicks; once every alarm it
told about is acknowledged, cleared or out of service, it is settled for everyone
(``POST /api/v1/notifications/resolve``, after the cycle's sends).

A rule with hours sends only inside them (or outside them, on-call): when a window opens on an
alarm still active and unacknowledged, it hands the alarm over with a reminder. Escalation steps
queue for an active, unacknowledged alarm as soon as their minutes since the announcement have
passed, and go out without gathering; acknowledging the alarm drops the reminders and
escalations still waiting.

What keeps the messages few (a flood of 50 loops is not 50 messages) follows the installation's
alarm philosophy (``alarms.philosophy``):

- **By priority**: critical alarms go at once, one by one; high ones as their rule gathers them;
  medium and low ones and every notice wait for the **shift summary** (one message a person at
  each summary time), unless the rule asks for "always at once".
- **Gathering**: the alarms of one rule for the same people within its gathering time (5 min by
  default) are one message.
- **The limit**: a person or group gets at most ``per_person_hour`` messages an hour (critical
  alarms and escalations always go); past it, one message says the rest is waiting in Alarms.
- **Flood**: more than ``flood_alarms`` alarms for one person within ``flood_minutes`` and that
  person gets one flood message (how many, how many critical) instead of each; the critical ones
  still go one by one.
- **Chattering**: an alarm raised ``chatter_minute`` times within a minute (or ``chatter_hour``
  within an hour) sends nothing more; the summary lists it, with what to change.
- **Stale**: an alarm active longer than ``stale_hours`` is no longer reminded; the summary lists
  it for review.
- **Inhibition**: while an app's run or schedule has failed (an active alarm on
  ``*.run.failed`` or ``*.schedule.stalled``), the alarms that came from that schedule's results
  send nothing: their cause is the failure, already announced. While the data does not flow (the
  suite watch reports the Historian or its collector down, the installer silent or Docker down;
  the Historian reports its collector stalled), "no data" alarms and failed runs send nothing
  either; while one source is disconnected (``histcraft.source.disconnected``), the "no data"
  alarms of its signals.

A notification that PlantCraft refuses stays in the outbox and is tried again next cycle; after
a day it is dropped. An alarm with ``notify`` off, a shelved alarm or a silenced one sends nothing.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.client import PlantCraftError
from plantcraft_sdk.utc import local_text

from alarmcraft import APP_ID
from alarmcraft.alarms.model import PRIORITIES
from alarmcraft.alarms.notices import (
    GIVE_UP,
    NoticeStore,
    NotifyDraft,
)
from alarmcraft.alarms.philosophy import PhilosophyDraft, PhilosophyStore
from alarmcraft.alarms.records import owner_of, status_of
from alarmcraft.alarms.rules import RuleStore
from alarmcraft.alarms.store import AlarmStore
from alarmcraft.engine import routing
from alarmcraft.i18n import t
from alarmcraft.monitor.reader import AssetTree, Directory

LOGGER = logging.getLogger(__name__)
# The event app.toml declares for a flood ([[publishes.events]]).
FLOOD_EVENT = "flood.started"
MAX_LINES = 20
FAILURES = (".run.failed", ".schedule.stalled")
# Open conditions (the suite watch's) under which plant data does not flow.
DATA_DOWN_KINDS = (
    "processcraft.installer.silent",
    "processcraft.docker.down",
    "histcraft.collector.stalled",
)
DATA_SERVICES = ("service:histcraft",)
# A source the Historian cannot read (key source:<id>): only its own signals' alarms wait.
SOURCE_DOWN_KIND = "histcraft.source.disconnected"
NO_DATA_KIND = "histcraft.point.no_data"
MAX_SUMMARY_LINES = 30
SUMMARY_MARK = "summary_at"


def _moment(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


def rule_policy(rule: dict[str, Any]) -> dict[str, Any]:
    """A rule's notifications in the shape the routing reads (a policy for its own alarms)."""

    try:
        notify = NotifyDraft.model_validate(rule.get("notify") or {}).model_dump(mode="json")
    except ValueError:
        notify = NotifyDraft().model_dump(mode="json")
    return {
        **notify,
        "policy_id": f"rule:{rule['rule_id']}",
        "name": rule.get("name") or rule["rule_id"],
        "enabled": bool(notify.get("enabled", True)) and bool(rule.get("enabled", True)),
        "min_priority": "low",
        "areas": [],
        "disciplines": [],
    }


def is_failure(alarm: dict[str, Any]) -> bool:
    """Whether the alarm is about an app's run or schedule failing (it inhibits the others)."""

    kinds = list(alarm.get("hears") or [])
    return any(kind.endswith(tail) for kind in kinds for tail in FAILURES)


class Notifier:
    def __init__(
        self,
        alarms: AlarmStore,
        notices: NoticeStore,
        client: Any | None,
        tree: AssetTree,
        *,
        root_path: str = "/alarm",
        directory: Directory | None = None,
        rules: RuleStore | None = None,
        philosophy: PhilosophyStore | None = None,
        conditions: Any = None,
    ):
        """``conditions`` answers the conditions open now (``IncomingStore.open_conditions``)."""

        self.alarms = alarms
        self.philosophy_store = philosophy
        self.conditions = conditions
        self.notices = notices
        self.rules = rules
        self.inhibited = 0
        self.client = client
        self.tree = tree
        self.root_path = root_path.rstrip("/")
        self.directory = directory
        self.last_error = ""
        self.sent = 0

    def context(self, alarm: dict[str, Any]) -> dict[str, Any]:
        chain, _area = self.tree.area_of(alarm)
        return routing.context(alarm, chain, owner=owner_of(alarm))

    def all_policies(self) -> dict[str, dict[str, Any]]:
        """Every rule's notifications by ``rule:<id>``."""

        found: dict[str, dict[str, Any]] = {}
        for rule in self.rules.list() if self.rules is not None else []:
            policy = rule_policy(rule)
            found[policy["policy_id"]] = policy
        return found

    @staticmethod
    def policies_for(alarm: dict[str, Any], policies: dict[str, dict[str, Any]]) -> list[dict]:
        rule_id = alarm.get("rule_id")
        if rule_id and f"rule:{rule_id}" in policies:
            return [policies[f"rule:{rule_id}"]]
        return []

    def failed_schedules(self) -> set[str]:
        """The schedules whose run or schedule failure is an active alarm right now."""

        found = set()
        for alarm in self.alarms.list():
            state = alarm.get("state") or {}
            if state.get("active") and state.get("schedule_id") and is_failure(alarm):
                found.add(str(state["schedule_id"]))
        return found

    def inhibits(self, alarm: dict[str, Any], failed: set[str]) -> bool:
        schedule = (alarm.get("state") or {}).get("schedule_id")
        return bool(schedule) and schedule in failed and not is_failure(alarm)

    def philosophy(self) -> PhilosophyDraft:
        return self.philosophy_store.get() if self.philosophy_store else PhilosophyDraft()

    def data_down(self, alarm: dict[str, Any] | None = None) -> str:
        """Why plant data does not flow now (an open condition of the suite watch, or the
        Historian's: its collector stalled, or the source of ``alarm``'s signal down), else ""."""

        if self.conditions is None:
            return ""
        try:
            opened = self.conditions() or []
        except Exception:  # noqa: BLE001 - no inhibition rather than no notification
            LOGGER.exception("Open conditions not read")
            return ""
        signal = str(((alarm or {}).get("state") or {}).get("signal") or "")
        source = f"source:{signal.split(':', 1)[0]}" if ":" in signal else ""
        for item in opened:
            kind, key = str(item.get("kind") or ""), str(item.get("key") or "")
            if (
                kind in DATA_DOWN_KINDS
                or (kind == "processcraft.service.down" and key.startswith(DATA_SERVICES))
                or (kind == SOURCE_DOWN_KIND and source and key == source)
            ):
                return str(item.get("summary") or key or kind)
        return ""

    @staticmethod
    def depends_on_data(alarm: dict[str, Any]) -> bool:
        """A "no data" alarm, or an app's failed run: what a stop of the data flow causes."""

        return NO_DATA_KIND in (alarm.get("hears") or []) or is_failure(alarm)

    def chattering(self, alarm: dict[str, Any], at: datetime, rules: PhilosophyDraft) -> bool:
        """Whether this raise makes the alarm chatter (too many raises in a minute or an hour)."""

        hour = [
            moment
            for item in self.alarms.occurrences(
                alarm_id=alarm["alarm_id"], start=(at - timedelta(hours=1)).isoformat()
            )
            if (moment := _moment(item.get("started_at"))) is not None
            and at - timedelta(hours=1) <= moment <= at
        ]
        minute = [moment for moment in hour if moment >= at - timedelta(minutes=1)]
        return len(minute) >= rules.chatter_minute or len(hour) >= rules.chatter_hour

    def stale(self, alarm: dict[str, Any], now: datetime, rules: PhilosophyDraft) -> bool:
        raised = _moment((alarm.get("state") or {}).get("raised_at"))
        active = bool((alarm.get("state") or {}).get("active"))
        return active and raised is not None and now - raised >= timedelta(hours=rules.stale_hours)

    def record(
        self,
        alarm: dict[str, Any],
        event: str,
        at: datetime,
        value,
        detail: str,
        *,
        now: datetime | None = None,
    ) -> None:
        """An alarm was raised or cleared (at the sample's time ``at``): queue it for every policy
        that routes it ``now``, the cycle's wall-clock time (hours and silences)."""

        if not alarm.get("notify", True):
            return
        now = now or at
        ctx = self.context(alarm)
        if routing.silenced_by(self.notices.silences(now), ctx, now):
            return
        if event == "raised" and self.inhibits(alarm, self.failed_schedules()):
            self.inhibited += 1
            return
        if event == "raised" and self.depends_on_data(alarm) and self.data_down(alarm):
            self.inhibited += 1
            return
        rules = self.philosophy()
        chatter = event == "raised" and self.chattering(alarm, at, rules)
        policies = self.policies_for(alarm, self.all_policies())
        for policy in routing.routes(policies, ctx, now):
            if event == "cleared" and not policy.get("notify_cleared"):
                continue
            people = routing.recipients(policy, ctx["owner"])
            if people:
                self.notices.queue(
                    alarm,
                    policy,
                    event,
                    at=at.isoformat(),
                    recipients=people,
                    value=value,
                    detail=detail,
                    occurrence=(alarm.get("state") or {}).get("occurrence"),
                    status="chatter" if chatter else "pending",
                    error=t("chattering: held for the shift summary") if chatter else "",
                )

    def remind(self, now: datetime) -> None:
        """Queue the reminders, hand-overs and escalation steps due for active, unacknowledged
        alarms."""

        every = self.all_policies()
        if not any(
            item.get("repeat_minutes") or item.get("hours") or item.get("escalations")
            for item in every.values()
        ):
            return
        silences = self.notices.silences(now)
        failed = self.failed_schedules()
        rules = self.philosophy()
        for alarm in self.alarms.list():
            if status_of(alarm, now) != "unacked" or not alarm.get("notify", True):
                continue
            if self.stale(alarm, now, rules):
                continue  # the shift summary lists it for review
            ctx = self.context(alarm)
            if routing.silenced_by(silences, ctx, now) or self.inhibits(alarm, failed):
                continue
            state = alarm.get("state") or {}
            policies = self.policies_for(alarm, every)
            for policy in routing.routes(policies, ctx, now):
                last = self.notices.last_queued(alarm["alarm_id"], policy["policy_id"])
                if last is None:
                    # A window opened on an alarm nobody acknowledged: hand it over.
                    if not policy.get("hours") or policy.get("hours_mode") == "always":
                        continue
                    detail = t("Still active and not acknowledged (handed over to this shift).")
                elif (
                    not policy.get("repeat_minutes")
                    or datetime.fromisoformat(last) + timedelta(minutes=policy["repeat_minutes"])
                    > now
                ):
                    continue
                else:
                    detail = t("Still active and not acknowledged.")
                self.notices.queue(
                    alarm,
                    policy,
                    "reminder",
                    at=now.isoformat(),
                    recipients=routing.recipients(policy, ctx["owner"]),
                    value=state.get("value"),
                    detail=detail,
                    occurrence=state.get("occurrence"),
                )
            self.escalate(alarm, ctx, policies, now)

    def escalate(
        self,
        alarm: dict[str, Any],
        ctx: dict[str, Any],
        policies: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        """Queue the escalation steps due: the policies that announced this occurrence, whatever
        their hours now (an alarm raised at 16:55 escalates at 17:10 all the same)."""

        state = alarm.get("state") or {}
        occurrence = state.get("occurrence")
        coordinators: dict[str, str | None] | None = None
        for policy in policies:
            steps = policy.get("escalations") or []
            if not steps or not policy.get("enabled", True):
                continue
            since, done = self.notices.announced(alarm["alarm_id"], policy["policy_id"], occurrence)
            if since is None:
                continue
            waited = now - datetime.fromisoformat(since)
            for number, step in enumerate(steps, start=1):
                if number in done or waited < timedelta(minutes=step["after_minutes"]):
                    continue
                if coordinators is None:
                    coordinators = self._coordinators()
                people = routing.escalation_recipients(step, policy, ctx["owner"], coordinators)
                self.notices.queue(
                    alarm,
                    policy,
                    "escalation",
                    at=now.isoformat(),
                    recipients=people,
                    value=state.get("value"),
                    detail=t(
                        "Not acknowledged in {minutes} min (escalation {step}).",
                        minutes=step["after_minutes"],
                        step=number,
                    ),
                    occurrence=occurrence,
                    step=number,
                    email=bool(step.get("email")),
                    status="pending" if people else "dropped",
                    error="" if people else t("nobody to escalate to (no group coordinator set)"),
                )

    def _coordinators(self) -> dict[str, str | None]:
        if self.directory is None:
            return {}
        return {str(group["id"]): group.get("coordinator") for group in self.directory.groups()}

    def flush(self, now: datetime) -> int:
        """Send what waited long enough: one notification per policy and set of recipients;
        then the shift summary when one is due."""

        if self.client is None:
            return 0
        rules = self.philosophy()
        policies = self.all_policies()
        silences = self.notices.silences(now)
        batches: dict[tuple[str, tuple[str, ...]], list[dict]] = defaultdict(list)
        for row in self.notices.pending():
            at = datetime.fromisoformat(row["at"])
            if now - at > GIVE_UP:
                self.notices.finish([row["id"]], "dropped", at=now.isoformat(), error="too old")
                continue
            policy = policies.get(row["policy_id"])
            alarm = self.alarms.get(row["alarm_id"])
            if policy is None or alarm is None:
                self.notices.finish([row["id"]], "dropped", at=now.isoformat(), error="gone")
                continue
            status = status_of(alarm, now)
            if row["event"] != "cleared" and (
                status == "shelved" or routing.silenced_by(silences, self.context(alarm), now)
            ):
                self.notices.finish([row["id"]], "dropped", at=now.isoformat(), error="silenced")
                continue
            if row["event"] in {"reminder", "escalation"} and status != "unacked":
                self.notices.finish(
                    [row["id"]], "dropped", at=now.isoformat(), error="acknowledged"
                )
                continue
            row["notice"] = alarm.get("creates") == "notice"
            if row["event"] != "escalation" and self._for_summary(row, policy, rules):
                self.notices.finish(
                    [row["id"]], "digest", at=now.isoformat(), error=t("in the shift summary")
                )
                continue
            batches[(row["policy_id"], tuple(row["recipients"]))].append(row)
        sent = 0
        flooding: dict[str, int] = {}
        for (policy_id, people), rows in batches.items():
            policy = policies[policy_id]
            oldest = datetime.fromisoformat(rows[0]["at"])
            critical = all(row["priority"] in rules.immediate for row in rows)
            urgent = critical or all(row["event"] == "escalation" for row in rows)
            if not urgent and now - oldest < timedelta(seconds=policy.get("group_seconds") or 0):
                continue
            ids = [row["id"] for row in rows]
            hour = (now - timedelta(hours=1)).isoformat()
            window = (now - timedelta(minutes=rules.flood_minutes)).isoformat()
            flood = []
            if not urgent:
                for person in people:
                    count = flooding.get(person)
                    if count is None:
                        count = flooding[person] = self.notices.raised_for(person, window)
                    if count > rules.flood_alarms:
                        flood.append(person)
            allowed = [
                person
                for person in people
                if person not in flood
                and (urgent or self.notices.sent_since(person, hour) < rules.per_person_hour)
            ]
            held = [person for person in people if person not in allowed and person not in flood]
            if not allowed:
                error = (
                    t("flood: told as one message")
                    if flood and not held
                    else t("limit of {count} messages an hour", count=rules.per_person_hour)
                )
                self.notices.finish(ids, "held", at=now.isoformat(), error=error)
                self._limit_reached(held, now, rules)
                self._flood(flood, flooding, now, rules)
                continue
            message = self._message(policy, rows)
            try:
                receipt = self._send(allowed, message)
            except (PlantCraftError, ValueError) as exc:
                self.last_error = t("notifications: {why}", why=exc)[:500]
                self.notices.note_error(ids, str(exc))
                LOGGER.warning("Alarm notification not sent: %s", exc)
                continue
            self.notices.note_sent(allowed, now.isoformat())
            self.notices.finish(
                ids,
                "sent",
                at=now.isoformat(),
                delivered=len(receipt.get("delivered") or []),
                error=t("held for {who}: limit per hour", who=", ".join(held)) if held else "",
                key=message["key"],
            )
            self._limit_reached(held, now, rules)
            self._flood(flood, flooding, now, rules)
            self.last_error = ""
            sent += 1
        sent += self.summarize(now, rules, policies)
        self.sent += sent
        self.settle(now)
        return sent

    def settle(self, now: datetime) -> int:
        """Settle for everyone each notification whose alarms are all acknowledged, cleared or
        out of service (``POST /api/v1/notifications/resolve``): it leaves their unread count and
        loses its Acknowledge button. Run after the sends, since a send under the same key opens
        the notification again; repeating it is harmless."""

        if self.client is None:
            return 0
        settled = 0
        for key, rows in self.notices.unsettled().items():
            notes = []
            for alarm_id in dict.fromkeys(row["alarm_id"] for row in rows):
                alarm = self.alarms.get(alarm_id)
                occurrences = {row.get("occurrence") for row in rows if row["alarm_id"] == alarm_id}
                note = self._settled(alarm, occurrences, now)
                if note is None:
                    break
                notes.append(note)
            else:
                note = notes[0] if len(set(notes)) == 1 else t("Settled in Alarms")
                try:
                    self.client.resolve_notification(key, note=note)
                except (PlantCraftError, ValueError) as exc:
                    LOGGER.warning("Notification %s not settled: %s", key, exc)
                    continue
                self.notices.settle(key, now.isoformat())
                settled += 1
        return settled

    @staticmethod
    def _settled(alarm: dict[str, Any] | None, occurrences: set, now: datetime) -> str | None:
        """What settled the alarm's occurrences the notification told about, or None while one
        still needs someone."""

        if alarm is None:
            return t("Removed from Alarms")
        current = (alarm.get("state") or {}).get("occurrence")
        status = status_of(alarm, now)
        if current in occurrences and status in {"unacked", "shelved"}:
            return None
        active = bool((alarm.get("state") or {}).get("active"))
        if current in occurrences and active and alarm.get("creates") == "notice":
            return None
        if status == "out_of_service":
            return t("Taken out of service")
        if alarm.get("acked_by") and current in occurrences and status != "rtn_unacked":
            return t("Acknowledged by {name}", name=alarm["acked_by"])
        return t("Cleared")

    @staticmethod
    def _for_summary(row: dict[str, Any], policy: dict[str, Any], rules: PhilosophyDraft) -> bool:
        if policy.get("always_now"):
            return False
        return bool(row.get("notice")) or row["priority"] in rules.digest

    def _flood(
        self, people: list[str], counts: dict[str, int], now: datetime, rules: PhilosophyDraft
    ) -> None:
        """One flood message a person each ``flood_minutes`` while the flood lasts."""

        window = (now - timedelta(minutes=rules.flood_minutes)).isoformat()
        for person in people:
            if self.notices.sent_since(person, window, kind="flood"):
                continue
            try:
                self._send(
                    [person],
                    {
                        "title": t(
                            "Alarm flood: {count} alarms in {minutes} min",
                            count=counts.get(person, 0),
                            minutes=rules.flood_minutes,
                        ),
                        "text": t(
                            "More than {limit} alarms reached you within {minutes} minutes, so"
                            " they are told as this one message. Critical alarms still come one"
                            " by one. Start from the critical ones in Alarms (Active).",
                            limit=rules.flood_alarms,
                            minutes=rules.flood_minutes,
                        ),
                        "priority": "high",
                        "url": f"{self.root_path}/alarms",
                        "email": False,
                        "key": f"alarms-flood:{person}:{now.strftime('%Y%m%d%H')}",
                        "category": "alarm",
                    },
                )
                self.notices.note_sent([person], now.isoformat(), kind="flood")
                self.client.post_event(
                    f"{APP_ID}.{FLOOD_EVENT}",
                    f"app:{APP_ID}",
                    summary=t("Alarm flood for {who}", who=person),
                    payload={
                        "recipient": person,
                        "alarms": counts.get(person, 0),
                        "minutes": rules.flood_minutes,
                    },
                )
            except (PlantCraftError, ValueError) as exc:
                LOGGER.warning("Flood message not sent: %s", exc)

    # The shift summary -------------------------------------------------------------------

    def summarize(
        self,
        now: datetime,
        rules: PhilosophyDraft,
        policies: dict[str, dict[str, Any]],
        *,
        force: bool = False,
    ) -> int:
        """At each summary time, one message a person: what waited (medium and low alarms,
        notices), the chattering alarms and the stale ones. Answers the messages sent."""

        if self.rules is None:
            return 0
        due = rules.last_digest(now)
        last = self.rules.meta(SUMMARY_MARK)
        if last is None:
            # A new Alarms: the first summary is the next one, not one for the past.
            self.rules.set_meta(SUMMARY_MARK, now.isoformat())
            return 0
        if not force and datetime.fromisoformat(last) >= due:
            return 0
        self.rules.set_meta(SUMMARY_MARK, now.isoformat())
        lines: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        ids: dict[str, list[int]] = defaultdict(list)
        for status, section in (("digest", "waiting"), ("chatter", "chattering")):
            seen: dict[str, set[str]] = defaultdict(set)
            for row in self.notices.waiting(status):
                ids[status].append(row["id"])
                for person in row["recipients"]:
                    if row["alarm_id"] in seen[person]:
                        continue
                    seen[person].add(row["alarm_id"])
                    lines[person][section].append(self._summary_line(row, section))
        for alarm in self.alarms.list():
            if not self.stale(alarm, now, rules) or not alarm.get("notify", True):
                continue
            ctx = self.context(alarm)
            for policy in self.policies_for(alarm, policies):
                for person in routing.recipients(policy, ctx["owner"]):
                    lines[person]["stale"].append(
                        f"- {alarm.get('name') or alarm['alarm_id']}"
                        f" ({t('active since {time}', time=local_text(alarm['state']['raised_at'], zone=rules.timezone))})"
                    )
        sent = 0
        for person, sections in sorted(lines.items()):
            try:
                self._send([person], self._summary(sections, now))
            except (PlantCraftError, ValueError) as exc:
                self.last_error = t("notifications: {why}", why=exc)[:500]
                LOGGER.warning("Shift summary not sent: %s", exc)
                continue
            self.notices.note_sent([person], now.isoformat(), kind="summary")
            sent += 1
        for status, found in ids.items():
            self.notices.finish(found, "sent", at=now.isoformat(), error=t("in the shift summary"))
        return sent

    @staticmethod
    def _summary_line(row: dict[str, Any], section: str) -> str:
        name = row["name"]
        if section == "chattering":
            return f"- {name}: " + t(
                "comes and goes; widen its deadband or add an on-delay, then acknowledge it"
            )
        priority = t(PRIORITIES.get(row["priority"], row["priority"]))
        return f"- [{priority}] {name}" + (f": {row['detail']}" if row["detail"] else "")

    def _summary(self, sections: dict[str, list[str]], now: datetime) -> dict[str, Any]:
        heads = {
            "waiting": t("Alarms and alerts since the last summary"),
            "chattering": t("Chattering alarms (held back; their rules need a look)"),
            "stale": t("Stale alarms (active for long; review them)"),
        }
        text, count = [], 0
        for section in ("waiting", "chattering", "stale"):
            found = sections.get(section) or []
            if not found:
                continue
            count += len(found)
            text.append(f"**{heads[section]}** ({len(found)})")
            text += found[:MAX_SUMMARY_LINES]
            if len(found) > MAX_SUMMARY_LINES:
                text.append(t("…and {count} more.", count=len(found) - MAX_SUMMARY_LINES))
            text.append("")
        return {
            "title": t("Shift summary: {count} alarms", count=count),
            "text": "\n".join(text).strip(),
            "priority": "low",
            "url": f"{self.root_path}/alarms",
            "email": False,
            "key": f"alarms-summary:{now.strftime('%Y%m%d%H%M')}",
            "category": "info",
        }

    def _limit_reached(self, held: list[str], now: datetime, rules: PhilosophyDraft) -> None:
        """Note what the limit held back; tell each one once an hour that more is waiting."""

        if not held:
            return
        self.notices.note_sent(held, now.isoformat(), kind="held")
        hour = (now - timedelta(hours=1)).isoformat()
        for person in held:
            if self.notices.sent_since(person, hour, kind="limit"):
                continue
            try:
                self._send(
                    [person],
                    {
                        "title": t("More alarm notifications are waiting in Alarms"),
                        "text": t(
                            "You received {count} alarm messages in the last hour. The next ones"
                            " wait in Alarms (Active, My alarms) until the hour is over, so this"
                            " inbox stays readable.",
                            count=rules.per_person_hour,
                        ),
                        "priority": "medium",
                        "url": f"{self.root_path}/alarms",
                        "email": False,
                        "key": f"alarms-limit:{person}:{now.strftime('%Y%m%d%H')}",
                        "category": "info",
                    },
                )
                self.notices.note_sent([person], now.isoformat(), kind="limit")
            except (PlantCraftError, ValueError) as exc:
                LOGGER.warning("Limit message not sent: %s", exc)

    def _send(self, people: list[str], message: dict[str, Any]) -> dict[str, Any]:
        return self.client.notify(list(people), **message)

    def _message(self, policy: dict[str, Any], rows: list[dict]) -> dict[str, Any]:
        rank = {priority: index for index, priority in enumerate(PRIORITIES)}
        rows = sorted(rows, key=lambda row: (rank.get(row["priority"], 9), row["at"]))
        top = rows[0]
        words = {
            "raised": t("raised"),
            "cleared": t("cleared"),
            "reminder": t("still active"),
            "escalation": t("not acknowledged, escalated"),
        }
        lines = [
            f"- [{t(PRIORITIES.get(row['priority'], row['priority']))}] {row['name']}: "
            f"{words.get(row['event'], row['event'])}"
            + (f", {row['detail']}" if row["detail"] else "")
            for row in rows[:MAX_LINES]
        ]
        if len(rows) > MAX_LINES:
            lines.append(t("…and {count} more.", count=len(rows) - MAX_LINES))
        rule_id = (
            policy["policy_id"].partition(":")[2] if policy["policy_id"].startswith("rule:") else ""
        )
        alarms = {row["alarm_id"] for row in rows}
        if len(alarms) == 1:
            title = f"{top['name']}: {words.get(top['event'], top['event'])}"
            url = f"{self.root_path}/alarms/{top['alarm_id']}"
            key = f"alarm:{top['alarm_id']}:{top.get('occurrence') or top['id']}"
            ack = f"{self.root_path}/api/alarms/{top['alarm_id']}/ack"
            actions = (
                [{"label": t("Acknowledge"), "href": ack, "method": "POST"}]
                if any(row["event"] != "cleared" and not row.get("notice") for row in rows)
                else []
            )
        else:
            title = t("{count} alarms: {rule}", count=len(alarms), rule=policy["name"])
            url = f"{self.root_path}/alarms" + (f"?rule={rule_id}" if rule_id else "")
            key = f"rule:{rule_id or policy['policy_id']}:{top['at'][:13]}"
            actions = []
        if rule_id:
            actions.append(
                {"label": t("Open the rule"), "href": f"{self.root_path}/rules/{rule_id}"}
            )
        footer = (
            t("Rule: {name}. Acknowledge in Alarms to stop the reminders.", name=policy["name"])
            if rule_id
            else t(
                "Policy: {name}. Acknowledge in Alarms to stop the reminders.", name=policy["name"]
            )
        )
        return {
            "title": title[:200],
            "text": "\n".join(lines) + "\n\n" + footer,
            "priority": top["priority"],
            "url": url,
            "email": any(row["email"] for row in rows),
            "key": key,
            "actions": actions[:3],
            "category": "info" if all(row.get("notice") for row in rows) else "alarm",
        }
