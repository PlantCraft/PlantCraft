"""Values as the report PDF writes them: numbers, units, labels, instants on the report's clock,
and text escaped for a ``Paragraph``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors

from dashcraft.dashboards.fields import FieldConfig, finite_number
from dashcraft.reports.pdf_style import NO_VALUE, PALETTE, STATE_COLORS
from dashcraft.reports.schedule import zone

# Values ------------------------------------------------------------------------------------


def _color(name: str | None, fallback: colors.Color) -> colors.Color:
    if not name:
        return fallback
    if name.startswith("#"):
        return colors.HexColor(name)
    if name in PALETTE:
        return colors.HexColor(PALETTE[name])
    return STATE_COLORS.get(name, fallback)


def number_text(value: Any, decimals: int | None = None) -> str:
    """A value as people read it: thousands separated, decimals as the card says or by size."""

    number = finite_number(value)
    if number is None:
        return str(value) if isinstance(value, str) and value else NO_VALUE
    if decimals is None:
        size = abs(number)
        decimals = 0 if size >= 1000 else 1 if size >= 100 else 2 if size >= 1 else 3
        if number == int(number) and size < 1e15:
            decimals = 0
    return f"{number:,.{decimals}f}"


def shown(config: FieldConfig, value: Any) -> str:
    """The value with the card's mappings ("1" reads "Running"), decimals and empty text."""

    for mapping in config.mappings or []:
        if mapping.matches(value) and mapping.text:
            return mapping.text
    if value is None:
        return config.no_value or NO_VALUE
    return number_text(value, config.decimals)


def unit_of(config: FieldConfig, row: dict[str, Any]) -> str:
    return config.unit if config.unit is not None else str(row.get("unit") or "")


def _label(config: FieldConfig, row: dict[str, Any]) -> str:
    return config.display_name or str(row.get("label") or row.get("signal") or "")


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


class Clock:
    """Instants on the installation's wall clock."""

    def __init__(self, zone_name: str | None):
        self.zone = zone(zone_name)
        self.name = zone_name or "UTC"

    def local(self, value: Any) -> datetime | None:
        moment = _instant(value)
        return moment.astimezone(self.zone) if moment else None

    def text(self, value: Any, form: str = "%d %b %Y %H:%M") -> str:
        moment = self.local(value)
        return moment.strftime(form) if moment else NO_VALUE


def _esc(value: Any) -> str:
    return escape(str(value or ""))
