"""The report contract: a report is a list of sections read over one period.

A section is a cell, as in a Jupyter notebook: a text (Markdown: headings ``#`` to ``####``,
lists, tables, bold; ``reports.markdown``), a card (the same card as a
dashboard's: stat, gauge, trend, bars, table, scatter), the events some apps wrote in the period
(alarms raised, runs failed), or a page break. Every card of a report reads the report's period,
not a window of its own, so the whole document speaks of the same hours.

The period is a window that ends when the report is made: a report made every day at 06:00 over
``24h`` covers 06:00 the day before to 06:00 (the shift's day, as plants report it). Who receives
it (``recipients``) gets a notification in Messages with the PDF one click away; the PDF of every
send is kept (``store.py``), so what was sent can always be read again as it was.

A report names fixed signals and assets: no variables (one report for each asset is a later step).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dashcraft.dashboards.folders import ENTRY
from dashcraft.dashboards.model import Card, check_window, window_seconds
from dashcraft.i18n import t
from dashcraft.reports.assistant import AssistantSpec

MAX_SECTIONS = 60
MAX_TEXT = 20000
MAX_RECIPIENTS = 50
MAX_EVENT_KINDS = 10
SECTION_ID = r"^[A-Za-z0-9_-]{1,40}$"
# ``alarmcraft.alarm.raised``: the app's id, then the event's name.
EVENT_KIND = re.compile(r"^[a-z][a-z0-9_-]{0,39}\.[a-z][a-z0-9_]{0,40}(\.[a-z][a-z0-9_]{0,40})*$")
CLOCK = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# The period a cadence suggests (the editor's default when the cadence changes).
PERIOD_FOR = {
    "off": "24h",
    "day": "24h",
    "week": "7d",
    "fortnight": "14d",
    "month": "30d",
    "quarter": "90d",
}
SectionKind = Literal["text", "card", "events", "break", "assistant", "alarms"]
ASSET_ID = r"^[^\s$]{1,200}$"
# What an events section may count its events by, instead of listing them: who they are about,
# their kind, their severity, or one field of their payload (``payload.method_id``).
GROUP_BY = re.compile(r"^(subject|kind|severity|payload\.[a-z][a-z0-9_]{0,40})$")


class EventTrigger(BaseModel):
    """Make the report when an event ends something: a batch, a start-up, a shutdown (V5).

    Each new event of ``end_kind`` (about ``subject``, or any subject) makes one report over
    the period it closes: from the newest ``start_kind`` event about the same subject before it,
    else from the ``start`` (or ``started_at``) in its payload, else the report's own period
    before it. A period is at most ``MAX_EVENT_DAYS`` long."""

    end_kind: str = Field(max_length=200)
    start_kind: str = Field(default="", max_length=200)
    subject: str = Field(default="", max_length=300)

    @field_validator("end_kind", "start_kind")
    @classmethod
    def _kind(cls, value: str, info: Any) -> str:
        value = (value or "").strip()
        if (value or info.field_name == "end_kind") and not EVENT_KIND.match(value):
            raise ValueError(t("Unknown kind of event: {kind}.", kind=value))
        return value

    @field_validator("subject")
    @classmethod
    def _subject(cls, value: str) -> str:
        return (value or "").strip()


class Schedule(BaseModel):
    """When the report is made and sent, in the installation's time zone (``PLANTCRAFT_TIMEZONE``):
    every day at ``at``, every week (or every other week) on ``weekday`` at ``at``, every month (or
    every quarter: January, April, July, October) on ``day`` at ``at``. The period the report
    covers is the report's own (``Report.period``): any window up to a year, whatever the cadence;
    or, with ``closed``, the last whole day, week, two weeks, month or quarter."""

    every: Literal["off", "day", "week", "fortnight", "month", "quarter"] = "off"
    at: str = "06:00"
    weekday: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] = "mon"
    # Up to the 28th, so every month has the day.
    day: int = Field(default=1, ge=1, le=28)
    # Cover the last whole calendar period of the cadence (yesterday, last Monday to Sunday,
    # last month, last quarter) instead of the report's period ending when it is made.
    closed: bool = False
    # Also (or only) when an event ends a batch or a start-up: a report over that period.
    on_event: EventTrigger | None = None

    @field_validator("at")
    @classmethod
    def _at(cls, value: str) -> str:
        value = (value or "").strip()
        if not CLOCK.match(value):
            raise ValueError(t("The time is hours and minutes, like 06:00."))
        return value

    @property
    def on(self) -> bool:
        return self.every != "off"


class EventsSpec(BaseModel):
    """Which events a section lists: the latest of these kinds within the period."""

    kinds: list[str] = Field(min_length=1, max_length=MAX_EVENT_KINDS)
    limit: int = Field(default=20, ge=1, le=100)
    # Count the period's events by this (``GROUP_BY``) and rank the groups, the most first
    # (``limit`` groups), instead of listing the latest events: "" lists them.
    group_by: str = Field(default="", max_length=60)

    @field_validator("group_by")
    @classmethod
    def _group_by(cls, value: str) -> str:
        value = (value or "").strip()
        if value and not GROUP_BY.match(value):
            raise ValueError(
                t("Count events by subject, kind, severity or payload.<field>, or list them.")
            )
        return value

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip()
            if not EVENT_KIND.match(value):
                raise ValueError(t("Name an event as <app>.<event>, like alarmcraft.alarm.raised."))
            if value not in cleaned:
                cleaned.append(value)
        return cleaned


class AlarmsSpec(BaseModel):
    """An alarm performance section (ISA-18.2): the asset (the site or an area) whose alarms it
    reads, from what Alarms publishes (``reports.alarm_performance``)."""

    asset_id: str = Field(pattern=ASSET_ID)


def text_with_heading(title: str, text: str) -> str:
    """A text section of before 2026-10-26 (a heading field above its Markdown) as one cell:
    the heading becomes the cell's first ``#`` line."""

    title, text = (title or "").strip(), text or ""
    if not title:
        return text
    return f"# {title}\n\n{text}".rstrip() + ("\n" if text.endswith("\n") else "")


class Section(BaseModel):
    section_id: str = Field(pattern=SECTION_ID)
    kind: SectionKind = "text"
    # An events section's title (a card keeps its own title; a text cell writes its headings
    # in its Markdown).
    title: str = Field(default="", max_length=120)
    text: str = Field(default="", max_length=MAX_TEXT)
    card: Card | None = None
    events: EventsSpec | None = None
    # What an assistant section reads and how the model writes it (``reports.assistant``).
    assistant: AssistantSpec | None = None
    # What an alarm performance section reads.
    alarms: AlarmsSpec | None = None
    # Two half sections in a row sit side by side on the page.
    width: Literal["full", "half"] = "full"

    @model_validator(mode="before")
    @classmethod
    def _one_cell(cls, value: object) -> object:
        if isinstance(value, dict) and value.get("kind", "text") == "text" and value.get("title"):
            text = text_with_heading(str(value["title"]), str(value.get("text") or ""))
            return {**value, "title": "", "text": text}
        return value

    @model_validator(mode="after")
    def _fits_its_kind(self) -> Section:
        if self.kind == "text" and not self.text.strip():
            raise ValueError(t("Write the text of the cell."))
        if self.kind == "card":
            if self.card is None:
                raise ValueError(t("A panel section needs its panel."))
            if self.card.kind == "text":
                raise ValueError(t("Write notes in a text section, not in a panel."))
            if self.card.kind in ("diagram", "apc"):
                raise ValueError(
                    t("A report shows panels of signals; process displays stay on screens.")
                )
            if self.card.repeat is not None or any(
                (item.asset_id or "").startswith("$") or "${" in (item.signal_id or "")
                for item in self.card.items
            ):
                raise ValueError(
                    t("A report names its signals and assets: pick them, not a variable.")
                )
            if self.card.window.startswith("$"):
                self.card.window = "1h"
        elif self.card is not None:
            self.card = None
        if self.kind == "events" and self.events is None:
            raise ValueError(t("Pick the events the section lists."))
        if self.kind != "events":
            self.events = None
        if self.kind == "assistant" and self.assistant is None:
            raise ValueError(t("Pick the assets and analyses the assistant reads."))
        if self.kind != "assistant":
            self.assistant = None
        if self.kind == "alarms" and self.alarms is None:
            raise ValueError(t("Pick the site or the area whose alarms the section reads."))
        if self.kind != "alarms":
            self.alarms = None
        if self.kind in ("text", "break", "assistant", "alarms"):
            self.width = "full"
        return self


class ReportPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    # The folder it is filed in ("" = General), shared with the dashboards: it decides who sees
    # and who changes the report (``dashboards.folders``).
    folder_id: str = Field(default="", max_length=40)
    # The window every section reads, ending when the report is made.
    period: str = "24h"
    schedule: Schedule = Field(default_factory=Schedule)
    # Who gets each scheduled send (``user:<name>``, ``group:<id>``) in Messages' Notifications.
    recipients: list[str] = Field(default_factory=list, max_length=MAX_RECIPIENTS)
    # Also by email, where the platform sends email and the person allows it.
    email: bool = False
    sections: list[Section] = Field(default_factory=list, max_length=MAX_SECTIONS)
    base_updated_at: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("The name is required."))
        return value

    @field_validator("period")
    @classmethod
    def _period(cls, value: str) -> str:
        value = check_window(value)
        if window_seconds(value) < 3600:
            raise ValueError(t("A report covers at least one hour."))
        return value

    @field_validator("recipients")
    @classmethod
    def _recipients(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip()
            if not ENTRY.match(value):
                raise ValueError(t("Name people as user:<username> and groups as group:<id>."))
            if value not in cleaned:
                cleaned.append(value)
        return cleaned

    @model_validator(mode="after")
    def _consistent(self) -> ReportPayload:
        ids = [section.section_id for section in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError(t("Two sections have the same id."))
        return self

    def stored(self) -> dict:
        return self.model_dump(exclude={"base_updated_at"})


class SectionPreview(BaseModel):
    """An unsaved section, drawn while an editor builds it, over ``period``."""

    section: Section
    period: str = "24h"

    @field_validator("period")
    @classmethod
    def _period(cls, value: str) -> str:
        return check_window(value)


__all__ = [
    "EVENT_KIND",
    "GROUP_BY",
    "MAX_TEXT",
    "MAX_SECTIONS",
    "PERIOD_FOR",
    "WEEKDAYS",
    "AlarmsSpec",
    "EventsSpec",
    "ReportPayload",
    "Schedule",
    "Section",
    "SectionPreview",
    "text_with_heading",
]
