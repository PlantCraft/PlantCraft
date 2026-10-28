"""The alarm contract: one rule's alarm on one subject, with its priority and the
rationalization a person writes for it (cause, consequence, corrective action).

People write **rules** (``alarms.rules.RuleDraft``): where (assets, a branch, an asset type, a
Link execution) and when (the rule's diagram, ``alarms.blocks``). Each rule makes one alarm per
subject it covers, configured by an ``AlarmDraft`` the rule writes; the alarm keeps its ISA-18.2
life in ``alarms.store``. Terms follow ISA-18.2 (public standard): an alarm is *raised* when its
condition holds, *clears* when it no longer does, and needs an operator's *acknowledgement*.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")
ROLE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# Who answers for an alarm: a person or a group of the platform (``user:<name>``, ``group:<id>``).
OWNER = re.compile(r"^(user|group):[A-Za-z0-9][A-Za-z0-9._@-]{0,99}$")
# An event kind as the apps publish it ("linkcraft.run.failed"); "linkcraft.finding.*" matches
# every kind that starts with "linkcraft.finding.".
EVENT_KIND = re.compile(r"^[a-z][a-z0-9_-]{0,39}(\.[a-z0-9_*-]{1,40}){1,4}$")
APP = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MAX_WINDOW_MINUTES = 7 * 24 * 60

# What a rule makes: an alarm (needs an acknowledgement, counts in the alarm performance, the
# ISA-18.2 sense) or a notice (a message and a line on screen, nothing to acknowledge).
Creates = Literal["alarm", "notice"]
Priority = Literal["critical", "high", "medium", "low"]
CREATES: dict[str, str] = {"alarm": "Alarm", "notice": "Alert"}
# Most to least urgent; the alarm summary sorts by this order.
PRIORITIES: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}
# The engineering discipline that answers for an alarm; notification policies route by it.
DISCIPLINES: dict[str, str] = {
    "operations": "Operations",
    "process": "Process",
    "instrumentation": "Instrumentation",
    "electrical": "Electrical",
    "mechanical": "Mechanical",
    "safety": "Safety and environment",
}
Discipline = Literal[
    "operations", "process", "instrumentation", "electrical", "mechanical", "safety"
]


def _text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit or any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise ValueError(f"at most {limit} characters, no control characters")
    return text


def kind_matches(patterns: list[str], kind: str) -> bool:
    for pattern in patterns:
        if pattern == kind or (pattern.endswith(".*") and kind.startswith(pattern[:-1])):
            return True
    return False


class AlarmDraft(BaseModel):
    """One rule's alarm on one subject, as the rule writes it (``rules.alarm_config``)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=120)
    rule_id: str = Field(max_length=63)
    # What it is about: the asset id, ``execution:<app>:<id>``, or "" (the rule's one alarm).
    subject: str = Field(default="", max_length=320)
    # The asset the alarm belongs to (its page lists it).
    asset_id: str | None = Field(default=None, max_length=300)
    label: str | None = Field(default=None, max_length=300)
    priority: Priority = "medium"
    creates: Creates = "alarm"
    # The rule's condition in words ("FIC-1001 › Link › Health < 50 for 5 values in a row").
    sentence: str = Field(default="", max_length=2000)
    # The event kinds the rule's event blocks hear (a failed run inhibits the others).
    hears: list[str] = Field(default_factory=list, max_length=40)
    # A fingerprint of the rule's diagram: a new one starts the alarm over.
    logic: str = Field(default="", max_length=64)
    cause: str = Field(default="", max_length=2000)
    consequence: str = Field(default="", max_length=2000)
    action: str = Field(default="", max_length=2000)
    enabled: bool = True
    # Off while its rule is off (the alarm's own ``enabled`` is its own out of service).
    rule_enabled: bool = True
    # Who answers for it (``user:<name>`` or ``group:<id>``); the creator when left out.
    owner: str | None = Field(default=None, max_length=110)
    # The plant area it belongs to (an asset); found up the asset tree when left out.
    area: str | None = Field(default=None, max_length=300)
    discipline: Discipline | None = None
    # Sent to people by its rule's Notify; off: shown in Alarms only.
    notify: bool = True
    # Shown on dashboards (its asset's colour, the Active alarms widgets); off: Alarms only.
    dashboards: bool = True

    @field_validator("owner")
    @classmethod
    def _owner(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        if value and not OWNER.match(value):
            raise ValueError("an owner is user:<username> or group:<id>")
        return value or None

    @field_validator("area", "asset_id", "label")
    @classmethod
    def _blank(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = (value or "").strip()
        if not NAME.match(value):
            raise ValueError("a name of 1 to 120 characters")
        return value

    @field_validator("cause", "consequence", "action", "sentence")
    @classmethod
    def _words(cls, value: str) -> str:
        return _text(value, 2000)

    @property
    def subject_asset(self) -> str | None:
        return self.asset_id

    def config(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def condition(self) -> str:
        return self.sentence
