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

| Table | Holds |
|---|---|
| ``philosophy`` | the one philosophy of the installation (``PhilosophyDraft``), who changed it and when |
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from plantcraft_sdk.server.store import Store
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from alarmcraft.alarms.model import Priority
from alarmcraft.alarms.notices import CLOCK, LIMIT_PER_HOUR, LOCAL, minutes_of, valid_zone, zone_of


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

    @field_validator("digest_times")
    @classmethod
    def _times(cls, value: list[str]) -> list[str]:
        found = []
        for item in value:
            item = (item or "").strip()
            if not CLOCK.match(item) or item == "24:00":
                raise ValueError("times of day as HH:MM, like 07:00")
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
            raise ValueError("a priority goes at once or waits for the summary, not both")
        if "critical" in self.digest:
            raise ValueError("critical alarms never wait for the summary")
        if abs(self.target_high + self.target_medium + self.target_low - 100.0) > 0.5:
            raise ValueError("the target shares of the priorities add up to 100 %")
        if self.chatter_hour < self.chatter_minute:
            raise ValueError("chattering in an hour counts at least as many as in a minute")
        return self

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
