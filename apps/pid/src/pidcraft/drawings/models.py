"""What an editor sends with a drawing file."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

NUMBER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/-]{0,59}$")


class DrawingFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    number: str = Field(default="", max_length=60)
    title: str = Field(default="", max_length=200)
    unit: str = Field(default="", max_length=60)

    @field_validator("number")
    @classmethod
    def _number(cls, value: str) -> str:
        if value and not NUMBER.match(value):
            raise ValueError("a drawing number like PID-U200-001")
        return value


class DrawingChange(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=60)
