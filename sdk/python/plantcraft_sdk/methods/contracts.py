"""Typed contracts shared by methodology blocks."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from plantcraft_sdk.i18n import t


class MethodStatus(StrEnum):
    """Execution status for a methodology block."""

    OK = "ok"
    WARNING = "warning"
    BAD = "bad"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_DATA = "insufficient_data"


class Severity(StrEnum):
    """Human-facing severity classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MethodMaturity(StrEnum):
    """Maturity level of a method implementation."""

    LITERATURE_BASED = "literature_based"
    ENGINEERING_HEURISTIC = "engineering_heuristic"
    EXPERIMENTAL = "experimental"
    CLIENT_CUSTOM = "client_custom"


class ScientificReference(BaseModel):
    """Reference used to justify or document a methodology."""

    title: str
    authors: list[str]
    year: int
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    reference_type: str = "article"
    notes: str | None = None


class MethodMetadata(BaseModel):
    """Scientific and operational metadata for a methodology block."""

    method_id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    maturity: MethodMaturity = MethodMaturity.EXPERIMENTAL
    references: list[ScientificReference] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    required_signals: list[str] = Field(default_factory=list)
    implemented_formula: str | None = None
    validation_notes: list[str] = Field(default_factory=list)

    # Texts are English constants; they are served in the request's language.
    @field_serializer("name", "description")
    def _translate_text(self, value: str) -> str:
        return t(value) if value else value

    @field_serializer("assumptions", "limitations")
    def _translate_list(self, value: list[str]) -> list[str]:
        return [t(item) for item in value]


class InputPort(BaseModel):
    """Declared input port for a methodology block."""

    port_id: str
    semantic_type: str
    dtype: str
    required: bool = True
    unit: str | None = None
    description: str | None = None

    @field_serializer("description")
    def _translate_description(self, value: str | None) -> str | None:
        return t(value) if value else value


class OutputPort(BaseModel):
    """Declared output port for a methodology block."""

    port_id: str
    semantic_type: str
    dtype: str
    unit: str | None = None
    description: str | None = None

    @field_serializer("description")
    def _translate_description(self, value: str | None) -> str | None:
        return t(value) if value else value


class MethodBlockSpec(BaseModel):
    """Inspectable block contract for a methodology."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    method_id: str
    version: str
    contract_version: str = "1.0"
    input_ports: list[InputPort]
    input_schema: type[BaseModel]
    parameter_schema: type[BaseModel]
    output_ports: list[OutputPort]
    output_schema: type[BaseModel]
    metadata: MethodMetadata


class DataQuality(BaseModel):
    """Quality information produced by preprocessing."""

    valid_fraction: float = Field(default=1.0, ge=0.0, le=1.0)
    missing_fraction: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_count: int = Field(default=0, ge=0)
    gap_count: int = Field(default=0, ge=0)
    notes: list[str] = Field(default_factory=list)


class LoopDataset(BaseModel):
    """Preprocessed loop dataset passed into methodology blocks."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    loop_id: str
    data: pd.DataFrame
    start_time: str | None = None
    end_time: str | None = None
    sample_time_seconds: float | None = None
    quality: DataQuality = Field(default_factory=DataQuality)
    # Samples as the source returned them (before resampling), indexed by
    # time, with the semantic column names (pv, sp, op, mode). Data quality
    # methods need them: resampling hides gaps and frozen values.
    raw: pd.DataFrame | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class MethodEvent(BaseModel):
    """Time-window event detected by a methodology."""

    start_time: str | None = None
    end_time: str | None = None
    label: str
    score: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    """Evidence behind a score or diagnostic."""

    label: str
    value: float | int | str | bool | None = None
    unit: str | None = None
    description: str | None = None
    timestamp: str | None = None


MetricValue = float | int | str | bool | None


class MethodResult(BaseModel):
    """Standard output envelope for methodology blocks."""

    schema_version: str = "1.0"
    method_id: str
    loop_id: str
    status: MethodStatus
    score: float = Field(ge=0.0, le=100.0)
    severity: Severity
    message: str
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    events: list[MethodEvent] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    references: list[ScientificReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
