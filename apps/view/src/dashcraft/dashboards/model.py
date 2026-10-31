"""The dashboard contract: a dashboard is a grid of cards; a card shows signals.

A card names each signal either directly (``signal_id``, a PlantCraft signal)
or through an asset and a role (``asset_id`` + ``role``: "the PV of FIC-101"),
so a card follows the asset when PlantCraft remaps its signals. ``asset_id``
``$loop`` names an asset variable the viewer picks at the top of the dashboard:
one dashboard then serves every asset of its kind (a loop page, a pump page;
``variables.py``). How values are shown (thresholds, colours, units) is the
card's ``field`` and ``overrides`` (``fields.py``); what each kind draws, its
``options``.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dashcraft.dashboards.fields import (
    DEFAULT_TABLE_COLUMNS,
    MAX_OVERRIDES,
    TABLE_COLUMNS,
    FieldConfig,
    Override,
)
from dashcraft.dashboards.legacy import place_cards, upgrade_card, upgrade_dashboard
from dashcraft.dashboards.variables import (
    MAX_VARIABLES,
    NAME,
    Variable,
    check_references,
)
from dashcraft.i18n import t

CONTEXT = "$context"
# Round 7: stat (one number per signal, with or without its line; was kpi and spark), gauge (a
# dial per signal), trend, bar, table, scatter (one signal against another: x, y) and text;
# 2026-10-27: diagram (a saved diagram of View › Diagrams, live, scaled to the panel).
KINDS = ("stat", "gauge", "trend", "bar", "table", "scatter", "text", "diagram")
# Kinds that show no signal of their own.
NO_ITEM_KINDS = ("text", "diagram")
AGGREGATIONS = ("last", "mean", "min", "max", "std")
# Columns of a table card, in order.
TABLE_AGGREGATIONS = ("last", "mean", "min", "max", "std")
REFRESH_SECONDS = (0, 15, 30, 60, 300)
# Full screen and public links turn to the next page every so many seconds (0: never).
PAGE_SECONDS = (0, 30, 60, 300)
MAX_PAGES = 10
# Cards per page, and in the whole dashboard.
MAX_CARDS = 30
MAX_TOTAL_CARDS = MAX_PAGES * MAX_CARDS
# The suite's grid (@plantcraft/ui CardGrid): 12 columns, rows of 91 px. A card spans 2 to 12
# columns and 1 to 12 rows at (x, y); a chart, a dial or a table needs 2 rows to stay readable.
MIN_WIDTH, MAX_WIDTH = 2, 12
MAX_HEIGHT = 12
ONE_ROW_KINDS = ("stat", "text")
# Grid version of saved dashboards: 1 had heights 1 (short) and 2 (tall) of a 196 px row; 2
# counts rows of half that (short = 2, tall = 4, the same pixels); 3 places every card at
# (x, y) and keeps round 7's card shape. ``DashboardStore`` migrates.
GRID_VERSION = 3
PAGE_ID = r"^[A-Za-z0-9_-]{1,40}$"
MAX_ITEMS = 12
MAX_TAGS, MAX_TAG_LENGTH = 10, 30
MAX_WINDOW_SECONDS = 366 * 86400
WINDOW_PATTERN = re.compile(r"^([1-9][0-9]{0,4})([smhd])$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

Kind = Literal["stat", "gauge", "trend", "bar", "table", "scatter", "text", "diagram"]
Aggregation = Literal["last", "mean", "min", "max", "std"]
# A role of an asset, or ``*``: every signal of the asset (round 7, D5).
ALL_ROLES = "*"


def window_seconds(window: str) -> int:
    """Seconds of a window like ``15m``, ``8h`` or ``7d``; ValueError outside 1 s to 366 days."""

    match = WINDOW_PATTERN.match(window or "")
    if not match:
        raise ValueError(t("A window is a number and one of s, m, h, d, like 8h or 7d."))
    seconds = int(match.group(1)) * UNIT_SECONDS[match.group(2)]
    if seconds > MAX_WINDOW_SECONDS:
        raise ValueError(t("A window is at most 366 days."))
    return seconds


def check_window(window: str) -> str:
    window = (window or "").strip()
    window_seconds(window)
    return window


# ``linkcraft.loop_health``: the producing app's id, then the result kind it publishes.
RESULT_KIND = r"^[a-z][a-z0-9_-]{0,39}\.[a-z][a-z0-9_]{0,59}$"
# A window, or an interval variable (``$period``).
WINDOW_OR_VARIABLE = re.compile(r"^\$\{?[A-Za-z][A-Za-z0-9_]{0,29}\}?$")


class Conflict(Exception):
    """Someone saved the dashboard after the editor opened it."""

    def __init__(self, current: dict[str, Any]):
        super().__init__("conflict")
        self.current = current


class CardItem(BaseModel):
    """One signal on a card: a signal id, or an asset (or an asset variable, ``$loop``) and a
    role, or every signal of the asset (role ``*``, optionally only ``roles``)."""

    signal_id: str | None = Field(default=None, max_length=300)
    asset_id: str | None = Field(default=None, max_length=300)
    role: str | None = Field(default=None, max_length=60)
    # With role ``*``: only these roles, in this order (none: every role the asset has).
    roles: list[str] = Field(default_factory=list, max_length=30)
    # Another app's result about the asset (or signal) instead of its data: ``<app>.<kind>``,
    # read from API v1 results (the suite's app standard, section 6); on a trend, the history
    # of that result the app archives in Historian (a derived signal).
    result: str | None = Field(default=None, max_length=100, pattern=RESULT_KIND)
    label: str = Field(default="", max_length=80)

    @field_validator("signal_id", "asset_id", "role", "result", mode="before")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        value = (value or "").strip() if isinstance(value, str) or value is None else value
        return value or None

    @field_validator("roles")
    @classmethod
    def _roles(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip().lower()
            if len(value) > 60:
                raise ValueError(t("A signal role has at most 60 characters."))
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    @model_validator(mode="after")
    def _names_a_signal(self) -> CardItem:
        if self.result is not None:
            if (self.signal_id is None) == (self.asset_id is None) or self.role is not None:
                raise ValueError(t("An app result is about one asset or one signal."))
            return self
        if self.signal_id is None and not (self.asset_id and self.role):
            raise ValueError(t("Pick a signal, or an asset and one of its signal roles."))
        if self.role == ALL_ROLES and self.signal_id is not None:
            raise ValueError(t("Every signal of an asset needs the asset, not a signal."))
        return self

    @property
    def every_role(self) -> bool:
        return self.role == ALL_ROLES


class CardOptions(BaseModel):
    """What each kind of card draws, after Grafana's panel options. One set for every kind,
    so changing a card's kind keeps what still applies."""

    # Stat: the line under the number, what the threshold colours, the name above it.
    graph: Literal["none", "area"] = "none"
    color_by: Literal["value", "background", "none"] = "value"
    show_name: bool = True
    # Stat, gauge and bars: how several values are laid out (auto: by the card's shape).
    orientation: Literal["auto", "horizontal", "vertical"] = "auto"
    # Bars: plain bars, or bars filled to the value in the threshold's colour (bar gauge).
    bar_style: Literal["bars", "gauge"] = "bars"
    value_labels: Literal["auto", "always", "never"] = "auto"
    sort: Literal["none", "asc", "desc"] = "none"
    # Trend: the legend and its values, the tooltip, stacking, gaps and the Y axis.
    legend: Literal["list", "table", "hidden"] = "list"
    legend_place: Literal["bottom", "right"] = "bottom"
    legend_values: list[Literal["last", "mean", "min", "max"]] = Field(default_factory=list)
    tooltip: Literal["all", "single", "hidden"] = "all"
    stack: Literal["none", "normal", "percent"] = "none"
    connect_gaps: bool = False
    y_scale: Literal["linear", "log"] = "linear"
    y_label: str = Field(default="", max_length=40)
    soft_min: float | None = None
    soft_max: float | None = None
    # Gauge: marks and numbers at the thresholds.
    threshold_markers: bool = True
    threshold_labels: bool = False
    # Table: the columns, how the last value is drawn, the row in its state's colour.
    columns: list[Literal["last", "mean", "min", "max", "std", "unit", "time", "state"]] = Field(
        default_factory=lambda: list(DEFAULT_TABLE_COLUMNS)
    )
    cell: Literal["text", "color_text", "color_background", "bar"] = "color_text"
    row_color: bool = False
    # Scatter: the points.
    point_size: int = Field(default=5, ge=2, le=20)

    @field_validator("soft_min", "soft_max")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError(t("A limit must be a finite number."))
        return value

    @field_validator("columns")
    @classmethod
    def _columns(cls, values: list[str]) -> list[str]:
        kept = [value for value in TABLE_COLUMNS if value in values]
        if not kept:
            raise ValueError(t("A table shows at least one column."))
        return kept


class Repeat(BaseModel):
    """A card drawn once for each value of a variable, side by side or one under the other."""

    variable: str = Field(pattern=NAME)
    direction: Literal["h", "v"] = "h"
    max_per_row: int = Field(default=4, ge=1, le=6)


class Card(BaseModel):
    card_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,40}$")
    title: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=300)
    kind: Kind = "stat"
    items: list[CardItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    # Text cards: the note (plain text, line breaks kept; ``${variable}`` filled in).
    text: str = Field(default="", max_length=2000)
    # Diagram cards: the saved diagram they show (read at every refresh, as its viewer may).
    diagram_id: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_-]{0,40}$")
    # The value shown by stats, gauges and bars. Trends and tables ignore it.
    agg: Aggregation = "last"
    # A window (``8h``), or an interval variable (``$period``).
    window: str = "1h"
    field: FieldConfig = Field(default_factory=FieldConfig)
    overrides: list[Override] = Field(default_factory=list, max_length=MAX_OVERRIDES)
    options: CardOptions = Field(default_factory=CardOptions)
    # Place and size on the grid (columns and rows); no place: after the cards before it.
    x: int | None = Field(default=None, ge=0, le=MAX_WIDTH - 1)
    y: int | None = Field(default=None, ge=0, le=10_000)
    width: int = Field(default=4, ge=MIN_WIDTH, le=MAX_WIDTH)
    height: int = Field(default=2, ge=1, le=MAX_HEIGHT)
    # The dashboard page the card is on; none: the first page.
    page_id: str | None = Field(default=None, pattern=PAGE_ID)
    repeat: Repeat | None = None

    @model_validator(mode="before")
    @classmethod
    def _older_cards(cls, value: object) -> object:
        return upgrade_card(value)

    @field_validator("window")
    @classmethod
    def _window(cls, value: str) -> str:
        value = (value or "").strip()
        if WINDOW_OR_VARIABLE.match(value):
            return value
        return check_window(value)

    @model_validator(mode="after")
    def _items_fit_the_kind(self) -> Card:
        if self.kind == "scatter" and len(self.items) != 2:
            raise ValueError(t("A scatter panel shows two signals: x, then y."))
        if self.kind == "scatter" and any(item.every_role for item in self.items):
            raise ValueError(t("A scatter panel shows two signals: x, then y."))
        if self.kind == "text" and self.items:
            raise ValueError(t("A text panel shows no signal."))
        if self.kind == "diagram" and self.items:
            raise ValueError(t("A process display panel shows its process display, not signals."))
        if self.kind == "diagram" and not self.diagram_id:
            raise ValueError(t("Pick the process display to show."))
        if self.kind not in NO_ITEM_KINDS and not self.items:
            raise ValueError(t("Pick at least one signal."))
        if self.kind == "text" and not self.text.strip():
            raise ValueError(t("Write the text of the panel."))
        if self.height < 2 and self.kind not in ONE_ROW_KINDS:
            raise ValueError(t("A chart, a dial or a table is at least 2 rows high."))
        if self.x is not None and self.x + self.width > MAX_WIDTH:
            self.x = MAX_WIDTH - self.width
        return self


class Page(BaseModel):
    """A page (tab) of a dashboard; its cards name it with ``page_id``."""

    page_id: str = Field(pattern=PAGE_ID)
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: str) -> str:
        return (value or "").strip() if isinstance(value, str) else value


class DashboardPayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    # The kind of the first asset variable (kept for older clients and the asset pages).
    context_kind: str | None = Field(default=None, max_length=60)
    # The pickers at the top (round 7): assets, lists and intervals the cards name.
    variables: list[Variable] = Field(default_factory=list, max_length=MAX_VARIABLES)
    refresh_seconds: int = 60
    # No pages: one page without a name (every dashboard before pages, and new ones).
    pages: list[Page] = Field(default_factory=list, max_length=MAX_PAGES)
    page_seconds: int = 0
    cards: list[Card] = Field(default_factory=list, max_length=MAX_TOTAL_CARDS)
    # The folder it is filed in ("" = General): its folder decides who sees and edits it.
    folder_id: str = Field(default="", max_length=40)
    # Words to find it by in the list (Grafana's tags).
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    # The time window it opens with (the Time picker's first value); None: each card's own.
    default_window: str | None = None
    # Hovering a chart marks the same moment on the dashboard's other time charts.
    shared_cursor: bool = False
    # Full screen shows the cards only, without the toolbar (a control room screen).
    kiosk: bool = False
    # The updated_at the editor started from: a newer save by someone else is a conflict.
    base_updated_at: str | None = Field(default=None, max_length=40)

    @model_validator(mode="before")
    @classmethod
    def _older_dashboards(cls, value: object) -> object:
        return upgrade_dashboard(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("The name is required."))
        return value

    @field_validator("context_kind")
    @classmethod
    def _context_kind(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("tags")
    @classmethod
    def _tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = " ".join((value or "").split())
            if not value:
                continue
            if len(value) > MAX_TAG_LENGTH:
                raise ValueError(t("A tag has at most {n} characters.", n=MAX_TAG_LENGTH))
            if value.lower() not in {tag.lower() for tag in cleaned}:
                cleaned.append(value)
        return cleaned

    @field_validator("default_window")
    @classmethod
    def _default_window(cls, value: str | None) -> str | None:
        return None if value in (None, "") else check_window(value)

    @field_validator("refresh_seconds")
    @classmethod
    def _refresh(cls, value: int) -> int:
        if value not in REFRESH_SECONDS:
            raise ValueError(t("Refresh every 0, 15, 30, 60 or 300 seconds."))
        return value

    @field_validator("page_seconds")
    @classmethod
    def _page_seconds(cls, value: int) -> int:
        if value not in PAGE_SECONDS:
            raise ValueError(t("Turn pages every 0, 30, 60 or 300 seconds."))
        return value

    @model_validator(mode="after")
    def _consistent(self) -> DashboardPayload:
        ids = [card.card_id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError(t("Two panels have the same id."))
        page_ids = [page.page_id for page in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError(t("Two pages have the same id."))
        first = page_ids[0] if page_ids else None
        per_page: dict[str | None, int] = {}
        for card in self.cards:
            if card.page_id is not None and card.page_id not in page_ids:
                raise ValueError(t("A panel is on a page the dashboard does not have."))
            page = card.page_id or first
            per_page[page] = per_page.get(page, 0) + 1
            if per_page[page] > MAX_CARDS:
                raise ValueError(t("A page has at most {n} panels.", n=MAX_CARDS))
        names = [variable.name for variable in self.variables]
        if len(names) != len(set(names)):
            raise ValueError(t("Two variables have the same name."))
        for index, variable in enumerate(self.variables):
            if variable.parent is None:
                continue
            parent = next(
                (item for item in self.variables[:index] if item.name == variable.parent), None
            )
            if parent is None or parent.type != "asset":
                raise ValueError(
                    t(
                        "Variable {name}: its parent must be an asset variable above it.",
                        name=variable.name,
                    )
                )
        check_references(self.variables, self.cards)
        if any(card.x is None or card.y is None for card in self.cards):
            placed = place_cards([card.model_dump() for card in self.cards], first)
            for card, where in zip(self.cards, placed, strict=True):
                card.x, card.y = where["x"], where["y"]
        assets = [variable for variable in self.variables if variable.type == "asset"]
        self.context_kind = assets[0].asset_kind if assets else None
        return self

    def stored(self) -> dict:
        return self.model_dump(exclude={"base_updated_at"})


class CardPreview(BaseModel):
    """An unsaved card, drawn while an editor builds it, with the draft's variables and the
    values picked at the top (``context``: the old single asset, the variable ``asset``)."""

    card: Card
    variables: list[Variable] = Field(default_factory=list, max_length=MAX_VARIABLES)
    values: dict[str, list[str]] = Field(default_factory=dict)
    context: str | None = Field(default=None, max_length=300)
    window: str | None = None

    @field_validator("window")
    @classmethod
    def _window(cls, value: str | None) -> str | None:
        return None if value in (None, "") else check_window(value)
