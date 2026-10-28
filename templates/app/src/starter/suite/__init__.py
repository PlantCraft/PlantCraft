"""The only place StarterCraft talks to PlantCraft on its own behalf (PlantCraft
``docs/app-standard.md``, section 5): the events it writes, the follow-ups it puts in Desk and
the model it asks. Each part is one module; ``Suite`` joins them for the runtime.

Everything here goes through the app's service client (``PLANTCRAFT_APP_KEY``). Without one
(a development run), nothing is sent and nothing fails: the note is still saved. A page reading
the plant as the person (``rt.user_client(user)``) is not this: it stays in its router.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starter.suite import desk, events, llm


class Suite:
    """What StarterCraft sends to PlantCraft; ``client`` answers the service client or None."""

    def __init__(self, client: Callable[[], Any]):
        self._client = client

    def note_written(self, note: dict[str, Any], asset_name: str) -> None:
        events.note_written(self._client(), note, asset_name)

    def follow_ups(self, notes: list[dict[str, Any]]) -> None:
        desk.send_follow_ups(self._client(), notes)

    def follow_up_todo(self, note: dict[str, Any], asset_name: str) -> None:
        desk.follow_up_todo(self._client(), note, asset_name)

    def close_follow_up(self, note_id: str) -> None:
        desk.close_follow_up(self._client(), note_id)

    def summary(self, text: str) -> str:
        return llm.summary(self._client(), text)


__all__ = ["Suite"]
