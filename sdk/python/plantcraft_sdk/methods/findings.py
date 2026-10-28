"""Plain-language findings: what a method measured, in the user's language, with numbers.

A method module may define ``describe(metrics) -> str``. The registry calls it
when a result is shown; methods without one fall back to their own message.
"""

from __future__ import annotations

from typing import Any

from plantcraft_sdk.i18n import current_language, t


def fmt_number(value: Any, digits: int = 1) -> str:
    """Number in the current language's format, without trailing zeros.

    English: 1234.5 -> "1,234.5"; Brazilian Portuguese: 1234.5 -> "1.234,5".
    """

    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:,.{digits}f}".rstrip("0").rstrip(".") if digits else f"{number:,.0f}"
    if text in {"-0", ""}:
        text = "0"
    if current_language() == "en":
        return text
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_percent(fraction: Any) -> str:
    """A 0–1 fraction as a percentage: 0.734 -> "73%"."""

    if fraction is None:
        return "—"
    return f"{fmt_number(float(fraction) * 100, 0)}%"


def plural(count: Any, one: str, many: str) -> str:
    """ "1 change", "3 changes", "2.5 interventions" (``one``/``many`` already translated)."""

    number = float(count or 0)
    return f"{fmt_number(number)} {one if abs(number) == 1 else many}"


def counted(count: Any, one: str, many: str) -> str:
    """A count with its noun, translated: ``counted(3, "{count} gap", "{count} gaps")``.

    ``one`` and ``many`` are English templates with a ``{count}`` field; the
    pick follows English (1 is singular), which also holds for pt-BR.
    """

    number = float(count or 0)
    return t(one if abs(number) == 1 else many, count=fmt_number(number))
