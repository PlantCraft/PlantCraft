"""Files split into modules by subject (PlantCraft refactor F5) keep every name they had: each
old import path still gives every top-level name of the file before the split, and each class
split into parts still has every method it had. The lists were taken from the files before their
split."""

from __future__ import annotations

import importlib

import pytest

SPLIT = {
    "dashcraft.reports.pdf": {
        "names": [
            "INK",
            "TEXT2",
            "MUTED",
            "GRID",
            "AXIS",
            "PALE",
            "BRAND",
            "SERIES",
            "STATE_COLORS",
            "STATE_WORDS",
            "SEVERITY_COLORS",
            "PALETTE",
            "PAGE_WIDTH",
            "PAGE_HEIGHT",
            "MARGIN",
            "FRAME_PAD",
            "CONTENT",
            "GUTTER",
            "NO_VALUE",
            "_style",
            "STYLES",
            "_color",
            "number_text",
            "shown",
            "unit_of",
            "_label",
            "_instant",
            "Clock",
            "_esc",
            "spans_markup",
            "inline",
            "Heading",
            "_md_table",
            "markdown",
            "_Rule",
            "nice_ticks",
            "_time_ticks",
            "_segments",
            "_steps_of",
            "trend_drawing",
            "_axes",
            "_empty",
            "_legend",
            "_state",
            "tiles",
            "_range",
            "_meter",
            "bars",
            "TABLE_HEADS",
            "value_table",
            "_problems",
            "card_flowables",
            "events_flowables",
            "_plain_table",
            "alarms_flowables",
            "_groups_table",
            "_section_flowables",
            "_cover",
            "_numbered",
            "_Outlined",
            "render",
            "__all__",
        ],
        "classes": {},
    },
}


@pytest.mark.parametrize("module", sorted(SPLIT))
def test_a_split_module_keeps_its_names(module: str) -> None:
    loaded = importlib.import_module(module)
    names = SPLIT[module]
    assert [name for name in names["names"] if not hasattr(loaded, name)] == []
    for cls, methods in names["classes"].items():
        assert [method for method in methods if not hasattr(getattr(loaded, cls), method)] == []
