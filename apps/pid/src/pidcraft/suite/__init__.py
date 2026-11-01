"""The only place PlantCraft PID talks to PlantCraft on its own behalf (PlantCraft
``docs/app-standard.md``, section 5): the model it asks to read a scanned page again
(``pidcraft.plantmap.llm``) and its licence (``pidcraft.licence``), both through the app's
service client (``PLANTCRAFT_APP_KEY``). A page reading the plant as the person
(``rt.user_client(user)``) is not this: it stays in its router.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pidcraft.plantmap import llm as diagram_llm


class Suite:
    """What PlantCraft PID asks PlantCraft; ``client`` answers the service client or None."""

    def __init__(self, client: Callable[[], Any]):
        self._client = client

    @property
    def client(self) -> Any:
        return self._client()

    def read_with_model(self, png: bytes, result: dict[str, Any]) -> dict[str, Any]:
        return diagram_llm.ask(self._client(), png, result)


__all__ = ["Suite"]
