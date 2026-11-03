"""The installation's alarm philosophy: the targets an administrator sets once, that Alarms both
measures (the Performance page) and uses to hold back what reaches people.

The defaults are the public targets of ISA-18.2 and EEMUA 191: about 6 alarms an hour for one
person, a flood is more than 10 alarms in 10 minutes, a chattering alarm comes back 3 times in a
minute (or 10 in an hour), a stale one stays active over 24 hours, and the priorities split
about 5 % high, 15 % medium and 80 % low. Only an alarm that needs a person's action should reach
them, and at the pace its priority asks:

- ``immediate`` priorities (critical) go at once, one by one, past gathering and the limit;
- the others not in ``digest`` (high) go as the rule gathers them;
- ``digest`` priorities (medium and low) and every notice wait for the **shift summary**, sent at
  each ``digest_times`` in ``timezone``; a rule may ask for "always at once" (``always_now``).

**Consoles** (operator positions, ISA-18.2): the load targets are for one operator, so a plant
with several boards splits its alarms by console. A console covers areas of the asset tree (an
alarm's area chain, ``AssetTree.area_of``); an alarm goes to the console that names the deepest
asset of its chain (the first console on a tie), and to none when no console covers it. Each
console may set its own alarms-an-hour target for its operator; the others use
``per_person_hour``.

| Table | Holds |
|---|---|
| ``philosophy`` | the one philosophy of the installation (``PhilosophyDraft``), who changed it and when |
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.server.store import Store
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alarmcraft.alarms.model import Priority
from alarmcraft.alarms.notices import CLOCK, LIMIT_PER_HOUR, LOCAL, minutes_of, valid_zone, zone_of
from alarmcraft.i18n import t

CONSOLE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class Console(BaseModel):
    """One operator position: the areas whose alarms its operator answers."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    # Asset ids of the areas (any level of the tree) this console covers.
    areas: list[str] = Field(min_length=1, max_length=100)
    # Who sits at it (usernames): Performance opens on their console.
    operators: list[str] = Field(default_factory=list, max_length=100)
    # The alarms an hour its operator can answer; none: the philosophy's ``per_person_hour``.
    per_hour: int | None = Field(default=None, ge=1, le=60)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if not CONSOLE_ID.match(value):
            raise ValueError(
                t("a console id is lowercase letters, digits and dashes, like board-1")
            )
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join((value or "").split())
        if not value:
            raise ValueError(t("a console has a name"))
        return value

    @field_validator("areas", "operators")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))


class PhilosophyDraft(BaseModel):
    """The targets of the installation (the API's body)."""

    model_config = ConfigDict(extra="forbid")

    # The written philosophy: what an alarm is here, who answers, how priorities are chosen.
    statement: str = Field(default="", max_length=5000)
    per_person_hour: int = Field(default=LIMIT_PER_HOUR, ge=1, le=60)
    flood_alarms: int = Field(default=10, ge=2, le=500)
    flood_minutes: int = Field(default=10, ge=1, le=120)
    immediate: list[Priority] = Field(default_factory=lambda: ["critical"], max_length=4)
    digest: list[Priority] = Field(default_factory=lambda: ["medium", "low"], max_length=4)
    digest_times: list[str] = Field(
        default_factory=lambda: ["07:00", "19:00"], min_length=1, max_length=6
    )
    timezone: str = Field(default=LOCAL, max_length=64)
    chatter_minute: int = Field(default=3, ge=2, le=100)
    chatter_hour: int = Field(default=10, ge=2, le=1000)
    stale_hours: int = Field(default=24, ge=1, le=24 * 30)
    # The target share of alarms raised by priority (high counts critical too), in %.
    target_high: float = Field(default=5.0, ge=0, le=100)
    target_medium: float = Field(default=15.0, ge=0, le=100)
    target_low: float = Field(default=80.0, ge=0, le=100)
    # The longest an alarm may be shelved, by priority, in hours (ISA-18.2: shelving is
    # time-limited, and the more urgent the alarm the shorter).
    shelve_hours_critical: int = Field(default=1, ge=1, le=168)
    shelve_hours_high: int = Field(default=4, ge=1, le=168)
    shelve_hours_medium: int = Field(default=12, ge=1, le=168)
    shelve_hours_low: int = Field(default=24, ge=1, le=168)
    # The operator positions; none: the whole installation is one position.
    consoles: list[Console] = Field(default_factory=list, max_length=50)

    def shelve_minutes(self, priority: str | None) -> int:
        """The longest shelving allowed for an alarm of ``priority``, in minutes."""

        hours = getattr(self, f"shelve_hours_{priority or 'medium'}", self.shelve_hours_medium)
        return int(hours) * 60

    @field_validator("digest_times")
    @classmethod
    def _times(cls, value: list[str]) -> list[str]:
        found = []
        for item in value:
            item = (item or "").strip()
            if not CLOCK.match(item) or item == "24:00":
                raise ValueError(t("times of day as HH:MM, like 07:00"))
            if item not in found:
                found.append(item)
        return sorted(found, key=minutes_of)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str) -> str:
        return valid_zone(value)

    @field_validator("statement")
    @classmethod
    def _statement(cls, value: str) -> str:
        return "".join(ch for ch in value or "" if ch in "\n\t" or ord(ch) >= 32).strip()

    @model_validator(mode="after")
    def _consistent(self) -> PhilosophyDraft:
        self.immediate = list(dict.fromkeys(self.immediate))
        self.digest = list(dict.fromkeys(self.digest))
        if set(self.immediate) & set(self.digest):
            raise ValueError(t("a priority goes at once or waits for the summary, not both"))
        if "critical" in self.digest:
            raise ValueError(t("critical alarms never wait for the summary"))
        if abs(self.target_high + self.target_medium + self.target_low - 100.0) > 0.5:
            raise ValueError(t("the target shares of the priorities add up to 100 %"))
        if self.chatter_hour < self.chatter_minute:
            raise ValueError(t("chattering in an hour counts at least as many as in a minute"))
        ids = [console.id for console in self.consoles]
        if len(set(ids)) != len(ids):
            raise ValueError(t("each console has its own id"))
        names = [console.name.casefold() for console in self.consoles]
        if len(set(names)) != len(names):
            raise ValueError(t("each console has its own name"))
        return self

    def console(self, console_id: str) -> Console | None:
        return next((item for item in self.consoles if item.id == console_id), None)

    def console_of(self, chain: list[str]) -> Console | None:
        """The console of an alarm whose area chain (root first) is ``chain``: the one naming
        its deepest asset; the first one on a tie; None when no console covers it."""

        best, depth = None, -1
        for console in self.consoles:
            areas = set(console.areas)
            found = max((index for index, item in enumerate(chain) if item in areas), default=-1)
            if found > depth:
                best, depth = console, found
        return best

    def for_console(self, console: Console | None) -> PhilosophyDraft:
        """The targets as one console's operator is measured on them."""

        if console is None or console.per_hour is None:
            return self
        return self.model_copy(update={"per_person_hour": console.per_hour})

    def last_digest(self, now: datetime) -> datetime:
        """The latest summary time at or before ``now`` (UTC-aware, in the philosophy's zone)."""

        zone = zone_of(self.timezone)
        local = now.astimezone(zone)
        for days in range(0, 2):
            day = (local - timedelta(days=days)).date()
            for clock in reversed(self.digest_times):
                hours, minutes = divmod(minutes_of(clock), 60)
                moment = datetime(day.year, day.month, day.day, hours, minutes, tzinfo=zone)
                if moment <= local:
                    return moment.astimezone(now.tzinfo)
        return now  # unreachable: one time a day is always in the last two days

    def next_digest(self, now: datetime) -> datetime:
        zone = zone_of(self.timezone)
        local = now.astimezone(zone)
        for days in range(0, 2):
            day = (local + timedelta(days=days)).date()
            for clock in self.digest_times:
                hours, minutes = divmod(minutes_of(clock), 60)
                moment = datetime(day.year, day.month, day.day, hours, minutes, tzinfo=zone)
                if moment > local:
                    return moment.astimezone(now.tzinfo)
        return now + timedelta(days=1)

    def targets(self) -> dict[str, float]:
        return {"high": self.target_high, "medium": self.target_medium, "low": self.target_low}


class PhilosophyStore(Store):
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS philosophy (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        config_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );
    """

    def get(self) -> PhilosophyDraft:
        with self._connect() as connection:
            row = connection.execute("SELECT config_json FROM philosophy WHERE id = 1").fetchone()
        if row is None:
            return PhilosophyDraft()
        try:
            return PhilosophyDraft.model_validate(self._loads(row["config_json"], {}))
        except ValueError:
            return PhilosophyDraft()

    def record(self) -> dict[str, Any]:
        """The philosophy as the API answers it: the values, the defaults, who changed it."""

        with self._connect() as connection:
            row = connection.execute("SELECT * FROM philosophy WHERE id = 1").fetchone()
        return {
            **self.get().model_dump(mode="json"),
            "defaults": PhilosophyDraft().model_dump(mode="json"),
            "updated_at": row["updated_at"] if row else None,
            "updated_by": row["updated_by"] if row else None,
        }

    def put(self, draft: PhilosophyDraft, *, by: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO philosophy (id, config_json, updated_at, updated_by) VALUES (1,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET config_json = excluded.config_json,"
                " updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (self._json(draft.model_dump(mode="json")), self._now(), by),
            )
        return self.record()
