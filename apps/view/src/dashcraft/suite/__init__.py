"""The only place View talks to PlantCraft on its own behalf (PlantCraft
``docs/app-standard.md``, section 5): what it tells the suite about its reports. ``Suite`` joins
the parts for the runtime (``reports.py``: notifications, events, runs, schedules and the
calendar feed).

Everything here goes through the app's service client (``PLANTCRAFT_APP_KEY``). Without one (a
development run), nothing is sent and nothing fails: the report is still made and kept. Pages
reading the plant (dashboards, cards, the sections of a report) read through ``query`` with the
reader the runtime gives them, not through here.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dashcraft.suite import llm, reports


class Suite:
    """What View sends to PlantCraft; ``client`` answers the service client or None."""

    def __init__(self, client: Callable[[], Any]):
        self._client = client

    @property
    def connected(self) -> bool:
        return self._client() is not None

    def time_zone(self) -> str:
        return reports.time_zone(self._client())

    def deliver(self, report: dict[str, Any], run: dict[str, Any], url: str, period: str) -> int:
        return reports.deliver(self._client(), report, run, url, period)

    def sent(self, report: dict[str, Any], run: dict[str, Any], delivered: int, url: str) -> None:
        reports.sent(self._client(), report, run, delivered, url)

    def failed(self, report: dict[str, Any], run: dict[str, Any], url: str) -> None:
        reports.failed(self._client(), report, run, url)

    def runs(self, runs: list[dict[str, Any]], root: str) -> None:
        reports.publish_runs(self._client(), runs, root)

    def schedules(self, items: list[dict[str, Any]], root: str) -> None:
        reports.publish_schedules(self._client(), items, root)

    def calendar(self, items: list[dict[str, Any]]) -> None:
        reports.publish_calendar(self._client(), items)

    def ask_model(self, use: str, text: str, *, system: str = "") -> str:
        """One answer of the model PlantCraft gives ``use`` (``llm.NoModel`` when none)."""

        return llm.ask(self._client(), use, text, system=system)


__all__ = ["Suite"]
