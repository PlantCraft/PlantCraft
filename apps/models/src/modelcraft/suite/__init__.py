"""The only place Models talks to PlantCraft on its own behalf (PlantCraft
``docs/app-standard.md``, section 5): its runs on the Executions page, the events it writes,
its installation settings and the installation's time zone.
``Suite`` joins them for the runtime.

Everything here goes through the app's service client (``PLANTCRAFT_APP_KEY``); without one
(a development run) nothing is sent and nothing fails.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plantcraft_sdk.client import PlantCraftError

from modelcraft.suite import events, executions


class Suite:
    """What Models sends to PlantCraft; ``client`` answers the service client or None."""

    def __init__(self, client: Callable[[], Any], root_path: str):
        self._client = client
        self.root_path = root_path

    def run_finished(self, run: dict[str, Any]) -> None:
        """A run queued, started or ended: on the suite's Queue and Executions page, and
        ``run.failed`` when it failed."""

        client = self._client()
        if client is None:
            return
        name = executions.put_run(client, run, self.root_path)
        if run["status"] == "failed":
            events.run_failed(client, run, name, self.root_path)

    def setting(self, key: str) -> Any:
        """One of Models' installation settings (Setup › Apps › Models); None when PlantCraft
        cannot say (no app key, not answering): a switch read as None stays off."""

        client = self._client()
        if client is None:
            return None
        try:
            return client.app_settings().get(key)
        except PlantCraftError:
            return None

    def time_zone(self) -> str:
        """The installation's IANA zone (the plant's clock, what a person's day is); UTC when
        PlantCraft cannot say (no app key, not answering)."""

        client = self._client()
        if client is None:
            return "UTC"
        try:
            return client.installation_time_zone()
        except Exception:  # noqa: BLE001 - PlantCraft away: the days stay on UTC
            return "UTC"

    def study_finished(self, study: dict[str, Any], counts: dict[str, int]) -> None:
        client = self._client()
        if client is not None:
            events.study_finished(client, study, counts, self.root_path)


__all__ = ["Suite"]
