"""What a person writes about an asset: the note, and the follow-up it may ask for."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
USERNAME = re.compile(r"^[A-Za-z0-9_.@-]{1,80}$")


class NoteDraft(BaseModel):
    """The asset and the text; with ``follow_up`` (a day) and ``follow_up_by`` (a person), the
    note is also on Desk's calendar and in that person's to-do."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    asset_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=4000)
    follow_up: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    follow_up_by: str | None = Field(default=None, max_length=80)

    @field_validator("asset_id")
    @classmethod
    def _asset(cls, value: str) -> str:
        if not ASSET_ID.match(value):
            raise ValueError("an asset id of PlantCraft's asset tree")
        return value

    @field_validator("follow_up_by")
    @classmethod
    def _person(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not USERNAME.match(value):
            raise ValueError("a username of PlantCraft")
        return value
