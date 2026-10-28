"""Dashboard variables (round 7, after Grafana's): one dashboard for many assets.

A variable is a picker at the top of the dashboard. Cards name it instead of a fixed value:
an item's ``asset_id`` ``$loop`` (an asset variable), ``${tag}`` inside a ``signal_id`` (a
list), a card's ``window`` ``$period`` (an interval), and ``${loop}`` in titles, labels and
texts. A variable may take several values (each item then shows each of them) or ``All``;
a card can repeat itself once per value.

- ``asset``: assets of one kind, optionally under the asset another variable picked (unit,
  then its loops).
- ``custom``: a list of values typed by the editor.
- ``interval``: a list of time windows (``1h``, ``8h``, ``7d``).

The old "dashboard's asset" (``context_kind`` and items ``$context``) is the asset variable
named ``asset``: ``legacy.upgrade_dashboard`` turns one into the other.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from dashcraft.i18n import t

NAME = r"^[A-Za-z][A-Za-z0-9_]{0,29}$"
ALL = "$__all"
MAX_VARIABLES = 10
MAX_OPTIONS = 200
# Values one variable may stand for in a read (All of a kind with hundreds of assets is cut).
MAX_VALUES = 24
# ``$name`` or ``${name}`` in a text.
REFERENCE = re.compile(r"\$\{([A-Za-z][A-Za-z0-9_]{0,29})\}|\$([A-Za-z][A-Za-z0-9_]{0,29})\b")
WHOLE = re.compile(r"^\$\{?([A-Za-z][A-Za-z0-9_]{0,29})\}?$")


class Variable(BaseModel):
    name: str = Field(pattern=NAME)
    label: str = Field(default="", max_length=60)
    type: Literal["asset", "custom", "interval"] = "asset"
    asset_kind: str | None = Field(default=None, max_length=60)
    # Another asset variable: this one lists only the assets under the one picked there.
    parent: str | None = Field(default=None, pattern=NAME)
    options: list[str] = Field(default_factory=list, max_length=MAX_OPTIONS)
    multi: bool = False
    include_all: bool = False
    default: str = Field(default="", max_length=300)

    @field_validator("options")
    @classmethod
    def _options(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = (value or "").strip()
            if len(value) > 120:
                raise ValueError(t("A value of a variable has at most 120 characters."))
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned

    @model_validator(mode="after")
    def _complete(self) -> Variable:
        from dashcraft.dashboards.model import check_window

        self.asset_kind = (self.asset_kind or "").strip() or None
        if self.type == "asset" and not self.asset_kind:
            raise ValueError(
                t("Variable {name}: choose the kind of asset it lists.", name=self.name)
            )
        if self.type != "asset":
            self.asset_kind = None
            self.parent = None
            if not self.options:
                raise ValueError(t("Variable {name}: type at least one value.", name=self.name))
        if self.type == "interval":
            self.options = [check_window(value) for value in self.options]
        if self.parent == self.name:
            raise ValueError(t("A variable cannot be its own parent."))
        return self

    def shown_name(self) -> str:
        return self.label or self.name


def referenced(text: str | None) -> set[str]:
    """The variables a text names (``$loop``, ``${loop}``)."""

    return {a or b for a, b in REFERENCE.findall(text or "")}


def whole(text: str | None) -> str | None:
    """The variable a value is entirely (``$loop`` or ``${loop}``), else None."""

    match = WHOLE.match(text or "")
    return match.group(1) if match else None


def interpolate(text: str, values: dict[str, list[str]]) -> str:
    """``${loop}`` replaced by the variable's value (several joined by commas); unknown names
    are left as typed."""

    if "$" not in (text or ""):
        return text

    def swap(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        found = values.get(name)
        return ", ".join(found) if found else match.group(0)

    return REFERENCE.sub(swap, text)


def check_references(variables: Iterable[Variable], cards: Iterable[object]) -> None:
    """Every variable a card names exists, with the type its place needs."""

    by_name = {variable.name: variable for variable in variables}
    for card in cards:
        repeat = getattr(card, "repeat", None)
        if repeat is not None and repeat.variable not in by_name:
            raise ValueError(
                t(
                    "A panel repeats for ${name}, a variable the dashboard does not have.",
                    name=repeat.variable,
                )
            )
        window = whole(getattr(card, "window", ""))
        if window is not None:
            found = by_name.get(window)
            if found is None or found.type != "interval":
                raise ValueError(
                    t("A panel's time span ${name} is not an interval variable.", name=window)
                )
        for item in getattr(card, "items", []):
            asset = whole(item.asset_id)
            if asset is not None:
                found = by_name.get(asset)
                if found is None or found.type != "asset":
                    raise ValueError(
                        t(
                            "A panel uses ${name}, which is not an asset variable of the dashboard.",
                            name=asset,
                        )
                    )
            for name in referenced(item.signal_id):
                if name not in by_name:
                    raise ValueError(
                        t(
                            "A panel's signal uses ${name}, a variable the dashboard does not have.",
                            name=name,
                        )
                    )
