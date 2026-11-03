"""What the assistant's parts share: the sizes of a chat's history, rounds, charts and tool
answers, the settings read from the environment, and the error a refused question raises."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import timedelta
from typing import Any

# The engine's log keeps its name from before the split.
LOGGER = logging.getLogger("plantcraft.assistant_chat.engine")

HISTORY = 30
ROUNDS = 8
CHART_POINTS = 600
# How far past now a chart may end before its window is taken as written on the wrong clock.
FUTURE_SLACK = timedelta(minutes=15)
CHART_SIGNALS = 6
MAX_REFS = 40
# What a tool answer may weigh in the model's context.
TOOL_TEXT = 12_000
# How often the text being written is kept for the page that polls it.
STREAM_SECONDS = 0.4
# A question shorter than this ("ok", "and?") is not searched before the model answers.
PREFETCH_MIN = 8
ANSWER_LANGUAGE = {"pt-BR": "Brazilian Portuguese", "es": "Spanish", "en": "English"}
CHART = "show_chart"
HELP = "read_help"

# A raw read of this process's own API v1 as the person: (method, path, query or body) to
# (status, JSON answer). The HTTP layer makes it (``api/routers/assistant_chat.py``).
Reader = Callable[[str, str, dict[str, Any]], tuple[int, Any]]


def _usage(model: Any) -> dict[str, int]:
    """The tokens the model's latest answer spent (``ChatModel.usage``), when it counts them."""

    found = getattr(model, "usage", None)
    return {key: int(value) for key, value in found.items()} if isinstance(found, dict) else {}


class Refused(ValueError):
    """A question the assistant does not take now (limits); ``status`` is the HTTP answer."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return max(low, min(high, value))


# The assistant on each chart (a trial, 2026-11-02, off by default): "icon" puts the assistant's
# mark in each chart's buttons, which opens a small popover over the chart that asks and answers
# in place (ui ChartAssistant.tsx).
CHART_MODES = ("off", "icon")


def chart_mode() -> str:
    value = os.environ.get("PLANTCRAFT_ASSISTANT_CHARTS", "").strip().lower()
    return value if value in CHART_MODES else "off"
