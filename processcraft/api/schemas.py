"""Request bodies shared by the session routes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginPayload(BaseModel):
    username: str
    password: str


class SwitchUserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=80)
