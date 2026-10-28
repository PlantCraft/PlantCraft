"""What a person may send: a folder, a document's fields, the assets it is about."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from doccraft.i18n import t

KINDS = (
    "Operating manual",
    "Control narrative",
    "P&ID",
    "Datasheet",
    "Procedure",
    "Troubleshooting guide",
    "Incident report",
    "Maintenance record",
    "Other",
)
MAX_ENTRIES = 100
ENTRY = re.compile(r"^(user|group):[A-Za-z0-9_.@-]{1,80}$")
ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
RESERVED = "general"


class FolderPayload(BaseModel):
    """A folder: who sees it and who changes it (``user:<name>``, ``group:<id>``; empty means
    everyone, the same rule as View's folders), and whether the assistant may read it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    viewers: list[str] = Field(default_factory=list, max_length=MAX_ENTRIES)
    editors: list[str] = Field(default_factory=list, max_length=MAX_ENTRIES)
    assistant: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if value.casefold() == RESERVED:
            raise ValueError(
                t("General holds what is outside every folder: give the folder another name.")
            )
        return value

    @field_validator("viewers", "editors")
    @classmethod
    def _entries(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip()
            if not ENTRY.match(value):
                raise ValueError(t("Name people as user:<username> and groups as group:<id>."))
            if value not in cleaned:
                cleaned.append(value)
        return cleaned


class DocumentFields(BaseModel):
    """A document's description; every field optional on a change."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    folder_id: str | None = Field(default=None, max_length=12)
    number: str | None = Field(default=None, max_length=60)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    kind: str | None = None
    unit: str | None = Field(default=None, max_length=60)
    language: str | None = Field(default=None, max_length=10)
    assistant: bool | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str | None) -> str | None:
        if value is not None and value not in KINDS:
            raise ValueError(t("One of: {kinds}.", kinds=", ".join(KINDS)))
        return value

    @field_validator("folder_id")
    @classmethod
    def _folder(cls, value: str | None) -> str | None:
        if value and not re.fullmatch(r"[a-f0-9]{12}", value):
            raise ValueError(t("A folder id."))
        return value


class DocumentAssets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("assets")
    @classmethod
    def _assets(cls, values: list[str]) -> list[str]:
        cleaned = []
        for value in values:
            value = value.strip().removeprefix("asset:")
            if not ASSET_ID.match(value):
                raise ValueError(t("An asset id of PlantCraft's asset tree."))
            if value not in cleaned:
                cleaned.append(value)
        return cleaned


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=500)
    asset: str | None = Field(default=None, max_length=126)
    kind: str | None = Field(default=None, max_length=40)
    folder: str | None = Field(default=None, max_length=12)
    limit: int = Field(default=8, ge=1, le=30)
