"""The diagram contract: a process graphic of a unit, drawn on a fixed canvas.

A diagram is a list of elements on a canvas of ``width`` x ``height`` pixels (scaled to fit the
screen): **symbols** from the library (``symbols.py``: a pump, a tank, a valve), **lines**
between their ports (process piping, signal lines, utilities), **values** (one signal as a
number with its unit) and **texts**. Every binding to plant data is a card item
(``dashboards.model.CardItem``): a signal id, an asset and a role ("the PV of FIC-101", which
follows the asset when its tags change), or another app's result about an asset or a signal
(``alarmcraft.alarm_state``, ``linkcraft.loop_health``).

What a binding drives:

- a symbol's ``state``: its colour, from the producing app's status (results) or from limits
  on a signal;
- a symbol's ``level``: the share of its ``pc-level`` part that is filled (a tank's level, a
  valve's opening), between ``min`` and ``max``;
- a symbol's ``running`` and a line's ``flow``: on above a threshold (a pump running, flow in a
  pipe, drawn as moving dashes);
- a value element: the number itself, coloured by its limits.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dashcraft.dashboards.model import CardItem, check_window
from dashcraft.i18n import t

ELEMENT_ID = r"^[A-Za-z0-9_-]{1,40}$"
SYMBOL_ID = r"^[a-z0-9][a-z0-9_-]{0,39}(\.[a-z0-9][a-z0-9_-]{0,39}){0,3}$"
PORT_ID = r"^[A-Za-z0-9_-]{1,20}$"
MAX_ELEMENTS = 2000
# A page drawn at once (from assets, by the assistant) keeps to this many elements.
PAGE_ELEMENTS = 600
MAX_PAGES = 30
MAX_POINTS = 60
# The canvas: big enough for a whole unit, small enough to draw on a phone.
MIN_SIZE, MAX_SIZE = 200, 8000
DEFAULT_WIDTH, DEFAULT_HEIGHT = 1600, 900
REFRESH_SECONDS = (0, 5, 15, 30, 60)
MAX_TAGS, MAX_TAG_LENGTH = 10, 30
# Element boxes may stick out of the canvas a little while being dragged.
MARGIN = 2000
Coordinate = Annotated[float, Field(ge=-MARGIN, le=MAX_SIZE + MARGIN)]


def _finite(value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError(t("A limit must be a finite number."))
    return value


class Limits(BaseModel):
    """Warning and alarm limits on a signal's value (any may be left out)."""

    low_alarm: float | None = None
    low_warning: float | None = None
    high_warning: float | None = None
    high_alarm: float | None = None

    _check = field_validator("low_alarm", "low_warning", "high_warning", "high_alarm")(
        classmethod(lambda cls, value: _finite(value))
    )

    @model_validator(mode="after")
    def _ordered(self) -> Limits:
        given = [
            value
            for value in (self.low_alarm, self.low_warning, self.high_warning, self.high_alarm)
            if value is not None
        ]
        if given != sorted(given):
            raise ValueError(
                t("Limits go from low alarm to low warning to high warning to high alarm.")
            )
        return self

    def state(self, value: Any) -> str:
        """ok, warning or alarm for a number; unknown for anything else."""

        if isinstance(value, bool) or not isinstance(value, int | float):
            return "unknown"
        if not math.isfinite(value):
            return "unknown"
        if (self.low_alarm is not None and value <= self.low_alarm) or (
            self.high_alarm is not None and value >= self.high_alarm
        ):
            return "alarm"
        if (self.low_warning is not None and value <= self.low_warning) or (
            self.high_warning is not None and value >= self.high_warning
        ):
            return "warning"
        return "ok"


class StateBinding(BaseModel):
    """A symbol's colour: an app's result (its own status) or a signal against ``limits``."""

    item: CardItem
    limits: Limits = Field(default_factory=Limits)


class LevelBinding(BaseModel):
    """How full a symbol's ``pc-level`` part is: the signal between ``min`` and ``max``."""

    item: CardItem
    min: float = 0.0
    max: float = 100.0

    _check = field_validator("min", "max")(classmethod(lambda cls, value: _finite(value)))

    @model_validator(mode="after")
    def _range(self) -> LevelBinding:
        if self.item.result is not None:
            raise ValueError(t("A level reads a signal, not an app's result."))
        if self.min >= self.max:
            raise ValueError(t("The level's minimum must be below its maximum."))
        return self


class OnBinding(BaseModel):
    """On (a pump running, flow in a line) while the signal is above ``above``."""

    item: CardItem
    above: float = 0.5

    _check = field_validator("above")(classmethod(lambda cls, value: _finite(value)))

    @model_validator(mode="after")
    def _signal(self) -> OnBinding:
        if self.item.result is not None:
            raise ValueError(t("Running and flow read a signal, not an app's result."))
        return self


class Link(BaseModel):
    """Where a click on the element goes: another page of the same diagram, a part of this page
    (``area``, "x,y,w,h" in canvas units: the viewer zooms to it), another diagram, a dashboard,
    an asset or a trend of the element's signals."""

    kind: Literal["page", "area", "diagram", "dashboard", "asset", "trend"]
    target: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _target(self) -> Link:
        self.target = self.target.strip()
        if self.kind != "trend" and not self.target:
            raise ValueError(t("Pick what the link opens."))
        if self.kind == "area":
            self.target = _area(self.target)
        return self


def _area(target: str) -> str:
    """A part of the drawing, "x,y,w,h" in canvas units, checked and trimmed."""

    parts = [part.strip() for part in target.split(",")]
    try:
        x, y, w, h = (float(part) for part in parts)
    except ValueError:
        raise ValueError(t("A part of the drawing is x, y, width, height.")) from None
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise ValueError(t("A part of the drawing is x, y, width, height."))
    return target.strip()


class _Element(BaseModel):
    id: str = Field(pattern=ELEMENT_ID)
    # The page it is drawn on ("": the first page).
    page: str = Field(default="", max_length=40)
    link: Link | None = None


class Page(BaseModel):
    """One page of a diagram: a unit or an area of the plant, drawn on the diagram's canvas size."""

    id: str = Field(pattern=ELEMENT_ID)
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("A page needs a name."))
        return value


class Part(Page):
    """A named part of a large page: the viewer shows the parts as tabs
    after "Overview", and a tab zooms to its part, so a plant drawn on one page still has
    its overview and a way to each unit."""

    area: str = Field(max_length=80)

    @field_validator("area")
    @classmethod
    def _area(cls, value: str) -> str:
        return _area(value)


class SymbolElement(_Element):
    type: Literal["symbol"] = "symbol"
    symbol: str = Field(pattern=SYMBOL_ID)
    x: Coordinate = 0
    y: Coordinate = 0
    w: float = Field(default=60, ge=4, le=MAX_SIZE)
    h: float = Field(default=60, ge=4, le=MAX_SIZE)
    rotate: Literal[0, 90, 180, 270] = 0
    flip: bool = False
    label: str = Field(default="", max_length=80)
    # Where the label goes round the drawing; "inside" writes it over a vessel or a block.
    label_position: Literal["below", "above", "left", "right", "inside", "none"] = "below"
    # The asset this symbol draws (P-101): its page opens on a click when no link is set, and
    # the editor offers its signals first.
    asset_id: str | None = Field(default=None, max_length=300)
    state: StateBinding | None = None
    level: LevelBinding | None = None
    running: OnBinding | None = None


class ValueElement(_Element):
    type: Literal["value"] = "value"
    x: Coordinate = 0
    y: Coordinate = 0
    item: CardItem
    label: str = Field(default="", max_length=80)
    show_label: bool = True
    show_unit: bool = True
    # None: as many decimals as the value's size calls for.
    decimals: int | None = Field(default=None, ge=0, le=6)
    size: int = Field(default=14, ge=8, le=72)
    limits: Limits = Field(default_factory=Limits)


class Endpoint(BaseModel):
    """One end of a line on a symbol's port (the line follows the symbol when it moves)."""

    element: str = Field(pattern=ELEMENT_ID)
    port: str = Field(default="", max_length=20)

    @field_validator("port")
    @classmethod
    def _port(cls, value: str) -> str:
        value = value.strip()
        if value and not __import__("re").match(PORT_ID, value):
            raise ValueError(t("A port id has letters, digits, - and _ only."))
        return value


class LineElement(_Element):
    type: Literal["line"] = "line"
    kind: Literal["process", "signal", "utility"] = "process"
    # What runs in it (water, steam, gas, oil...): the line's colour and the legend's entry.
    medium: str = Field(default="", max_length=30)
    # The corners between its ends: the first and last points when an end is on no port.
    points: list[tuple[Coordinate, Coordinate]] = Field(default_factory=list, max_length=MAX_POINTS)
    start: Endpoint | None = None
    end: Endpoint | None = None
    arrow: Literal["none", "end", "start", "both"] = "end"
    label: str = Field(default="", max_length=80)
    flow: OnBinding | None = None

    @model_validator(mode="after")
    def _drawable(self) -> LineElement:
        ends = (self.start is not None) + (self.end is not None)
        if len(self.points) + ends < 2:
            raise ValueError(t("A line needs two ends: ports or points."))
        return self


class TextElement(_Element):
    type: Literal["text"] = "text"
    x: Coordinate = 0
    y: Coordinate = 0
    text: str = Field(min_length=1, max_length=400)
    size: int = Field(default=14, ge=8, le=72)
    align: Literal["start", "middle", "end"] = "start"
    bold: bool = False

    @field_validator("align", mode="before")
    @classmethod
    def _css_words(cls, value: Any) -> Any:
        # The words of CSS and drawing tools mean the same: left, center, right.
        return {"left": "start", "center": "middle", "centre": "middle", "right": "end"}.get(
            value, value
        )


Element = Annotated[
    SymbolElement | ValueElement | LineElement | TextElement, Field(discriminator="type")
]


class DiagramPayload(BaseModel):
    """A diagram as an editor saves it."""

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=400)
    folder_id: str = Field(default="", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)
    width: int = Field(default=DEFAULT_WIDTH, ge=MIN_SIZE, le=MAX_SIZE)
    height: int = Field(default=DEFAULT_HEIGHT, ge=MIN_SIZE, le=MAX_SIZE)
    grid: int = Field(default=10, ge=0, le=100)
    refresh_seconds: int = 15
    default_window: str = Field(default="1h", max_length=8)
    # The pages, in order; none is one page. Every element names its page (or the first).
    pages: list[Page] = Field(default_factory=list, max_length=MAX_PAGES)
    # Named parts of the first page, shown as tabs that zoom to each.
    parts: list[Part] = Field(default_factory=list, max_length=MAX_PAGES)
    elements: list[Element] = Field(default_factory=list, max_length=MAX_ELEMENTS)
    # The ``updated_at`` the editor opened; a save after someone else's is refused (409).
    base_updated_at: str | None = Field(default=None, max_length=40)

    @field_validator("folder_id", "description", mode="before")
    @classmethod
    def _none_is_empty(cls, value: Any) -> Any:
        return "" if value is None else value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(t("A process display needs a name."))
        return value

    @field_validator("tags")
    @classmethod
    def _tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip()
            if len(value) > MAX_TAG_LENGTH:
                raise ValueError(t("A tag has at most {n} characters.", n=MAX_TAG_LENGTH))
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    @field_validator("refresh_seconds")
    @classmethod
    def _refresh(cls, value: int) -> int:
        if value not in REFRESH_SECONDS:
            raise ValueError(t("Refresh every 0, 5, 15, 30 or 60 seconds."))
        return value

    @field_validator("default_window")
    @classmethod
    def _window(cls, value: str) -> str:
        return check_window(value)

    @model_validator(mode="after")
    def _references(self) -> DiagramPayload:
        ids = [element.id for element in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError(t("Two elements of the process display have the same id."))
        pages = [page.id for page in self.pages]
        if len(pages) != len(set(pages)):
            raise ValueError(t("Two pages of the process display have the same id."))
        parts = [part.id for part in self.parts]
        if len(parts) != len(set(parts)):
            raise ValueError(t("Two parts of the process display have the same id."))
        first = pages[0] if pages else ""
        for element in self.elements:
            if not element.page or element.page == first:
                element.page = first
            elif element.page not in pages:
                raise ValueError(
                    t(
                        "{element} is on a page the process display does not have.",
                        element=element.id,
                    )
                )
            if (
                element.link is not None
                and element.link.kind == "page"
                and element.link.target not in pages
            ):
                raise ValueError(
                    t(
                        "{element} opens a page the process display does not have.",
                        element=element.id,
                    )
                )
        symbols = {
            element.id: element.page for element in self.elements if element.type == "symbol"
        }
        for element in self.elements:
            if element.type != "line":
                continue
            for end in (element.start, element.end):
                if end is not None and symbols.get(end.element, None) != element.page:
                    raise ValueError(
                        t(
                            "A line ends on {element}, which is not a symbol on its page.",
                            element=end.element,
                        )
                    )
        return self

    def stored(self) -> dict[str, Any]:
        """What the store keeps: everything but the conflict check."""

        return self.model_dump(exclude={"base_updated_at"}, exclude_none=True)


def on_page(diagram: dict[str, Any], page: str | None) -> dict[str, Any]:
    """The stored diagram with only the elements of ``page`` (its id; "" or None: every page)."""

    if not page:
        return diagram
    pages = [item.get("id") for item in diagram.get("pages") or []]
    first = pages[0] if pages else ""
    elements = [
        item for item in diagram.get("elements") or [] if (item.get("page") or first) == page
    ]
    return {**diagram, "elements": elements}


def bindings(diagram: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Every binding of a stored diagram: (element id, slot, binding), in drawing order.

    Slots: ``state``, ``level`` and ``running`` of a symbol, ``value`` of a value element and
    ``flow`` of a line. A value element's binding is ``{"item": ..., "limits": ...}`` like the
    others.
    """

    found: list[tuple[str, str, dict[str, Any]]] = []
    for element in diagram.get("elements") or []:
        kind = element.get("type")
        if kind == "symbol":
            for slot in ("state", "level", "running"):
                if element.get(slot):
                    found.append((element["id"], slot, element[slot]))
        elif kind == "value":
            found.append(
                (element["id"], "value", {"item": element["item"], "limits": element.get("limits")})
            )
        elif kind == "line" and element.get("flow"):
            found.append((element["id"], "flow", element["flow"]))
    return found
