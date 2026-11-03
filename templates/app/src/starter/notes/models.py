"""What a person writes about an asset: the asset's id and the text. Every limit is here."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")


class NoteDraft(BaseModel):
    """The body of ``POST /api/notes`` and ``PUT /api/notes/{id}``; anything else is refused."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    asset_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("asset_id")
    @classmethod
    def _asset(cls, value: str) -> str:
        if not ASSET_ID.match(value):
            raise ValueError("an asset id of PlantCraft's asset tree")
        return value
