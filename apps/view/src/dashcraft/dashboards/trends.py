"""Trends: a quick look at signals over a period, saved to open again.

A trend is a stack of plots; each plot draws one or more signals on a shared time axis. The period
is relative (the last ``window``, ending now or at the newest data) or fixed (``start`` to
``end``). The values are one per ``step_seconds`` interval, ``0`` for the samples as recorded,
``None`` for a step chosen from the period (about 600 points per line). Each line chooses how its
interval is summarised (``agg``: mean, last, first, min, max) and how it is drawn (``style``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from plantcraft_sdk.server.store import Store
from pydantic import BaseModel, Field, field_validator, model_validator

from dashcraft.dashboards.model import MAX_WINDOW_SECONDS, check_window
from dashcraft.i18n import t

MAX_PLOTS = 6
MAX_LINES = 8
MAX_STEP_SECONDS = 86400


AGGREGATIONS = ("mean", "last", "first", "min", "max")


class LineStyle(BaseModel):
    """How a line is drawn: lines, points or both; straight, steps or smooth; colour and axis."""

    mode: Literal["lines", "markers", "lines+markers"] = "lines"
    shape: Literal["linear", "hv", "spline"] = "linear"
    # Empty: the suite's next series colour.
    color: str = Field(default="", pattern=r"^(#[0-9a-fA-F]{6})?$")
    width: float = Field(default=2.0, ge=0.5, le=8)
    dash: Literal["solid", "dot", "dash", "dashdot"] = "solid"
    marker_size: int = Field(default=6, ge=2, le=16)
    axis: Literal["left", "right"] = "left"


class TrendLine(BaseModel):
    signal_id: str = Field(min_length=1, max_length=300)
    label: str = Field(default="", max_length=80)
    # Each value of the line over its interval: the time-weighted mean, or the last, first,
    # lowest or highest sample (ignored when the trend shows the samples as recorded).
    agg: Literal["mean", "last", "first", "min", "max"] = "mean"
    # The line's own interval in seconds (0 = as recorded); None: the trend's.
    step_seconds: int | None = Field(default=None, ge=0, le=MAX_STEP_SECONDS)
    style: LineStyle = Field(default_factory=LineStyle)


class TrendPlot(BaseModel):
    title: str = Field(default="", max_length=80)
    lines: list[TrendLine] = Field(min_length=1, max_length=MAX_LINES)


class TrendPeriod(BaseModel):
    mode: Literal["relative", "fixed"] = "relative"
    window: str = Field(default="2h", max_length=8)
    start: datetime | None = None
    end: datetime | None = None

    @field_validator("window")
    @classmethod
    def _window(cls, value: str) -> str:
        return check_window(value)

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @model_validator(mode="after")
    def _fixed(self) -> TrendPeriod:
        if self.mode == "fixed":
            if self.start is None or self.end is None:
                raise ValueError(t("A fixed period needs a start and an end."))
            if self.start >= self.end:
                raise ValueError(t("The start must be before the end."))
            if (self.end - self.start).total_seconds() > MAX_WINDOW_SECONDS:
                raise ValueError(t("A period is at most 366 days."))
        return self


# Earlier periods drawn over the trend's own, each line dotted in its colour (V11, dataPARC's
# period comparison): the period just before, the same period a day, a week or four weeks back.
COMPARISONS = ("previous", "1d", "7d", "28d")
MAX_COMPARISONS = 3


class TrendView(BaseModel):
    """What a trend shows: the plots, the period, the step and the earlier periods it compares."""

    plots: list[TrendPlot] = Field(min_length=1, max_length=MAX_PLOTS)
    period: TrendPeriod = Field(default_factory=TrendPeriod)
    step_seconds: int | None = Field(default=None, ge=0, le=MAX_STEP_SECONDS)
    compare: list[Literal["previous", "1d", "7d", "28d"]] = Field(
        default_factory=list, max_length=MAX_COMPARISONS
    )

    @field_validator("compare")
    @classmethod
    def _compare(cls, value: list[str]) -> list[str]:
        return [item for item in COMPARISONS if item in value]


class TrendPayload(TrendView):
    """A saved trend."""

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("A trend needs a name."))
        return value


class TrendStore(Store):
    """Saved trends, shared by everyone in the installation."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS trends (
        trend_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        view_json TEXT NOT NULL,
        created_by TEXT,
        created_at TEXT NOT NULL,
        updated_by TEXT,
        updated_at TEXT NOT NULL
    );
    """

    def _row(self, row: Any) -> dict[str, Any]:
        item = dict(row)
        view = self._loads(item.pop("view_json"), {})
        return {**item, **view}

    def list(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM trends ORDER BY updated_at DESC").fetchall()
        return [self._row(row) for row in rows]

    def get(self, trend_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM trends WHERE trend_id = ?", (trend_id,)
            ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _view(payload: TrendPayload) -> dict[str, Any]:
        return payload.model_dump(
            mode="json", include={"plots", "period", "step_seconds", "compare"}
        )

    def create(self, payload: TrendPayload, user: str | None) -> dict[str, Any]:
        trend_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO trends (trend_id, name, description, view_json, created_by, "
                "created_at, updated_by, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trend_id,
                    payload.name,
                    payload.description,
                    self._json(self._view(payload)),
                    user,
                    now,
                    user,
                    now,
                ),
            )
        return self.get(trend_id) or {}

    def update(self, trend_id: str, payload: TrendPayload, user: str | None) -> dict | None:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE trends SET name = ?, description = ?, view_json = ?, updated_by = ?, "
                "updated_at = ? WHERE trend_id = ?",
                (
                    payload.name,
                    payload.description,
                    self._json(self._view(payload)),
                    user,
                    self._now(),
                    trend_id,
                ),
            )
        return self.get(trend_id) if cursor.rowcount else None

    def delete(self, trend_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM trends WHERE trend_id = ?", (trend_id,))
        return bool(cursor.rowcount)
