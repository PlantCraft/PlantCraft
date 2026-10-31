"""Request bodies accepted by the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from plantcraft_sdk.utc import LOCAL
from pydantic import AfterValidator, BaseModel, BeforeValidator, Field, model_validator

from linkcraft.assets.run import AssetTiming
from linkcraft.engine.recurrence import Recurrence
from linkcraft.i18n import t

AssetId = Annotated[str, Field(min_length=1, max_length=200)]


class _SelectorRule(BaseModel):
    """A selection rule: every loop, a list of ids, or filters re-evaluated at each run."""

    mode: Literal["all", "list", "filter"] = "all"
    ids: list[str] | None = Field(default=None, max_length=20_000)
    areas: list[str] | None = None
    function_types: list[str] | None = None
    criticalities: list[str] | None = None
    statuses: list[str] | None = None
    q: str | None = Field(default=None, max_length=200)


def _selector(value: Any) -> Any:
    if value is None:
        return None
    return _SelectorRule.model_validate(value).model_dump(exclude_none=True)


# Stored and passed around as a plain dict, checked here once.
Selector = Annotated[dict[str, Any], BeforeValidator(_selector)]


def _timezone(value: str) -> str:
    if value == LOCAL:  # the installation's zone, resolved where it is used
        return value
    try:
        ZoneInfo(value)
    except (KeyError, ValueError) as exc:
        raise ValueError(t("Unknown time zone.")) from exc
    return value


def _iso_datetime(value: str | None) -> str | None:
    if value:
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                t("Invalid date: use the format YYYY-MM-DD or YYYY-MM-DDTHH:MM.")
            ) from exc
    return value or None


Timezone = Annotated[str, AfterValidator(_timezone)]
IsoDatetime = Annotated[str | None, AfterValidator(_iso_datetime)]
SignalId = Annotated[str, Field(min_length=1, max_length=300)]


class SignalsPayload(BaseModel):
    pv: SignalId
    sp: SignalId | None = None
    op: SignalId | None = None
    mode: SignalId | None = None
    secondary: SignalId | None = None


class LoopPayload(BaseModel):
    """A loop defined in Analytics, by PlantCraft signal ids."""

    loop_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:\-]+$")
    name: str = Field(min_length=1, max_length=200)
    area: str = Field(default="No area", max_length=200)
    service: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=200)
    signals: SignalsPayload
    profile_id: str = Field(default="all", max_length=120)
    criticality: Literal["critical", "high", "medium", "low"] = "medium"


class LoopPatchPayload(BaseModel):
    """CPM settings of any loop; name and signals only for loops defined here."""

    enabled: bool | None = None
    profile_id: str | None = Field(default=None, max_length=120)
    criticality: Literal["critical", "high", "medium", "low"] | None = None
    method_parameters: dict[str, dict[str, Any]] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    area: str | None = Field(default=None, max_length=200)
    service: str | None = Field(default=None, max_length=500)
    signals: SignalsPayload | None = None
    # Give these settings back to the asset record (PlantCraft loops only).
    reset: list[Literal["profile_id", "criticality"]] | None = Field(default=None, max_length=2)


class JobPayload(BaseModel):
    loop_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=180)
    kind: str = "manual"
    lookback_minutes: int = Field(default=1440, ge=5, le=525600)
    profile_id: str | None = Field(default=None, max_length=120)
    method_ids: list[str] | None = None
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)


class BatchPayload(BaseModel):
    name: str = Field(default="Portfolio run", min_length=1, max_length=180)
    loop_ids: list[str] = Field(default_factory=list, max_length=20_000)
    selector: Selector | None = None
    kind: str = "manual"
    lookback_minutes: int = Field(default=1440, ge=5, le=525600)
    profile_id: str | None = Field(default=None, max_length=120)


class RetryPayload(BaseModel):
    """What a schedule does when an execution cannot read the plant or finds no data."""

    enabled: bool = True
    count: int = Field(default=2, ge=1, le=5)
    wait_minutes: float = Field(default=5, ge=0.5, le=240)
    abort_on_next: bool = True


class SchedulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    # One loop, or a selection rule re-evaluated at every run.
    loop_id: str | None = Field(default=None, max_length=120)
    selector: Selector | None = None
    interval_minutes: float | None = Field(default=None, gt=0, le=60 * 24 * 7)
    cadence: str = "daily"
    timezone: Timezone = "UTC"
    lookback_minutes: int = Field(default=1440, ge=5, le=525600)
    profile_id: str | None = Field(default=None, max_length=120)
    method_ids: list[str] | None = None
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    time_local: str | None = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int | None = Field(default=None, ge=0, le=6)
    scheduled_for: IsoDatetime = None
    # Its place in the queue among the schedules (a person's request is 100, a replay 10).
    priority: int = Field(default=50, ge=20, le=80)
    # Its executions spread over this many minutes after each occurrence, not all at once.
    spread_minutes: float = Field(default=0, ge=0, le=24 * 60)
    owner: str | None = Field(default=None, max_length=120)
    # cadence "calendar": when it runs (``linkcraft.engine.recurrence``).
    recurrence: Recurrence | None = None
    retry: RetryPayload | None = None
    # An algorithm on assets: what each execution records, ``{output: {"record", "keep"}}``
    # (``linkcraft.assets.outputs``).
    outputs: dict[str, Any] | None = None
    # An algorithm on assets: the monitor's own parameter values, ``{node id: {name: value}}``,
    # on top of the algorithm's (and the block's defaults).
    node_parameters: dict[str, dict[str, Any]] | None = None


class SchedulePatchPayload(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=180)
    cadence: str | None = None
    profile_id: str | None = Field(default=None, max_length=120)
    interval_minutes: float | None = Field(default=None, gt=0, le=60 * 24 * 7)
    time_local: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekday: int | None = Field(default=None, ge=0, le=6)
    lookback_minutes: int | None = Field(default=None, ge=5, le=525600)
    selector: Selector | None = None
    timezone: Timezone | None = None
    priority: int | None = Field(default=None, ge=20, le=80)
    spread_minutes: float | None = Field(default=None, ge=0, le=24 * 60)
    owner: str | None = Field(default=None, max_length=120)
    recurrence: Recurrence | None = None
    retry: RetryPayload | None = None
    # An algorithm on assets: what each execution records, ``{output: {"record", "keep"}}``
    # (``linkcraft.assets.outputs``).
    outputs: dict[str, Any] | None = None
    # An algorithm on assets: the monitor's own parameter values, ``{node id: {name: value}}``,
    # on top of the algorithm's (and the block's defaults).
    node_parameters: dict[str, dict[str, Any]] | None = None


class AlgorithmDocsPayload(BaseModel):
    """What an algorithm is for (``plantcraft_sdk.blocks.AlgorithmDocs``), written by people.

    A field left empty is generated from the diagram (``linkcraft.knowledge``).
    """

    purpose: str = Field(default="", max_length=400)
    assets: str = Field(default="", max_length=4000)
    when: str = Field(default="", max_length=4000)
    reading: str = Field(default="", max_length=4000)
    assistant: str = Field(default="", max_length=4000)


class ComputePlacementPayload(BaseModel):
    """Where an algorithm's work runs on the suite's compute workers (PlantCraft
    docs/compute.md): the executor's environment and the size of machine it needs."""

    environment: str = Field(
        default="standard", max_length=40, pattern=r"^[a-z0-9][a-z0-9-]{0,39}$"
    )
    size: Literal["small", "medium", "large"] = "small"


class AlgorithmPayload(BaseModel):
    algorithm_id: str = Field(
        min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,79}$"
    )
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    subject_kind: Literal["loop", "signal", "asset"] = "loop"
    diagram: dict[str, Any]
    docs: AlgorithmDocsPayload = Field(default_factory=AlgorithmDocsPayload)
    # An algorithm on assets: when it runs and on which assets.
    timing: AssetTiming = Field(default_factory=AssetTiming)
    assets: list[AssetId] = Field(default_factory=list, max_length=500)
    # Where its work runs on the suite's compute workers.
    compute: ComputePlacementPayload = Field(default_factory=ComputePlacementPayload)
    # Free tags and the user group that may edit it (None keeps what the algorithm had).
    tags: list[str] | None = Field(default=None, max_length=20)
    group_id: str | None = Field(default=None, max_length=120)
    # The version this save makes: a short name and what changed (D19).
    version_name: str = Field(default="", max_length=120)
    version_note: str = Field(default="", max_length=2000)


class AlgorithmMetaPayload(BaseModel):
    """Who answers for an algorithm, its tags and its group: not a new version."""

    owner: str | None = Field(default=None, max_length=120)
    owner_name: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=20)
    group_id: str | None = Field(default=None, max_length=120)


class RepeatedRemovePayload(BaseModel):
    """The repeated algorithms to delete, as the list showed them."""

    algorithm_ids: list[str] = Field(max_length=200)


class DiagramPayload(BaseModel):
    diagram: dict[str, Any]
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)


class TestPayload(BaseModel):
    diagram: dict[str, Any]
    # The algorithm's environment and size: the Test runs where its runs will.
    compute: ComputePlacementPayload | None = None
    loop_id: str | None = Field(default=None, max_length=120)
    lookback_minutes: int | None = Field(default=None, gt=0, le=60 * 24 * 31)
    # A test of an algorithm on assets: on this asset, with this timing.
    asset_id: str | None = Field(default=None, max_length=200)
    timing: AssetTiming | None = None
    # The end of the window tested (a past upset, say); now when not given.
    end: datetime | None = None
    # With ``end``, a loop's window from here (a past run's window run again).
    start: datetime | None = None


class CalibratePayload(BaseModel):
    """Calibrate a Deviation (T²) block of a diagram on one asset over a period."""

    diagram: dict[str, Any]
    node_id: str = Field(min_length=1, max_length=120)
    asset_id: str = Field(min_length=1, max_length=200)
    timing: AssetTiming | None = None
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _period(self) -> CalibratePayload:
        if self.end <= self.start:
            raise ValueError("the period ends after it starts")
        return self


class MethodDefaultsPayload(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Saving defaults is a new version, and a version says what changed.
    description: str = Field(min_length=1, max_length=500)
