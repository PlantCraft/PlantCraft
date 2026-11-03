"""``Collector``'s Sparkplug B sources: listening, the births that make points, and Browse.
Part of ``Collector`` (``collector.service``)."""

from __future__ import annotations

import asyncio
from typing import Any

from histcraft.archive.store import now_ms
from histcraft.catalog.models import PointIn
from histcraft.collector.reading import FUTURE_MS, Reading
from histcraft.collector.state import (
    LOGGER,
    SEEN_LIMIT,
    SPARKPLUG_TICK,
    _births_detail,
    _pushed_value,
)
from histcraft.i18n import t
from histcraft.sparkplug import Births


class SparkplugIntake:
    """``Collector``'s Sparkplug B sources."""

    # Sparkplug B ---------------------------------------------------------------------------

    async def _listen(self, source_id: str, listener: Any) -> None:
        """Take what a Sparkplug B source receives until its connection drops (it raises)."""

        births = self.births.setdefault(source_id, Births(SEEN_LIMIT))
        seeded = learnt = -1
        while True:
            messages = listener.messages()
            for topic, payload, at in messages:
                self.take_sparkplug(source_id, births.take(topic, payload, at))
            options = (self.sources.get(source_id) or {}).get("options") or {}
            # New metrics (a birth, or data before one) become points once, not on every tick.
            if options.get("add_on_birth") and births.known != learnt:
                try:
                    await asyncio.to_thread(self._add_born, source_id, births)
                except Exception:  # noqa: BLE001 - collection goes on; tried at the next metric
                    LOGGER.exception("Sparkplug source %s: points not added", source_id)
                learnt = births.known
            if seeded != self._version:
                seeded = self._version
                self._seed(source_id, births)
            self.source_status[source_id] = {
                "status": "connected",
                "detail": _births_detail(births, listener.dropped),
                "since": (self.source_status.get(source_id) or {}).get("since") or now_ms(),
                **births.summary(),
            }
            if not listener.connected:
                raise ConnectionError(listener.failure or t("The broker closed the connection."))
            await asyncio.sleep(SPARKPLUG_TICK)

    def take_sparkplug(self, source_id: str, values: list[Any]) -> int:
        """Values of a Sparkplug B source at their points; the archive only moves forward."""

        taken = 0
        now = now_ms()
        with self._lock:
            for item in values:
                at = item.at_ms if item.at_ms <= now + FUTURE_MS else now
                for state in self._pushed.get((source_id, item.address), []):
                    if state.last is not None and at <= state.last[0]:
                        continue
                    if not item.good:
                        state.take(Reading(at, None, False, item.detail, "bad"))
                        continue
                    value = _pushed_value(item.value, state.point["kind"])
                    state.take(Reading(at, value, True, item.detail, item.quality))
                    taken += 1
        return taken

    def _seed(self, source_id: str, births: Births) -> None:
        """A point added after its birth starts from the value the birth (or data) gave."""

        from histcraft.sparkplug import Value

        with self._lock:
            waiting = {
                address
                for (source, address), states in self._pushed.items()
                if source == source_id and any(state.last is None for state in states)
            }
        values = [
            Value(item["address"], int(item["at"] or now_ms()), item["value"])
            for item in births.variables()
            if item["address"] in waiting and item["value"] is not None
        ]
        self.take_sparkplug(source_id, values)

    def _add_born(self, source_id: str, births: Births) -> int:
        """Add a point for each metric a birth described that the source has none for."""

        with self._lock:
            have = {address for source, address in self._pushed if source == source_id}
        fresh = [
            item for item in births.variables() if item["kind"] and item["address"] not in have
        ]
        known = {p["address"] for p in self.catalog.points() if p["source_id"] == source_id}
        fresh = [item for item in fresh if item["address"] not in known]
        if not fresh:
            return 0
        result = self.catalog.add_points(
            [
                PointIn(
                    tag=item["tag"][:300],
                    source_id=source_id,
                    address=item["address"],
                    name=item["name"][:200],
                    description=item["description"],
                    unit=item["unit"],
                    kind=item["kind"],
                    step=item["step"],
                )
                for item in fresh
            ]
        )
        added = len(result.get("added") or [])
        if added:
            LOGGER.info("Sparkplug source %s: %d metrics added from births", source_id, added)
        return added

    def _answer_sparkplug(self, source: dict[str, Any], request: dict[str, Any]) -> tuple[str, Any]:
        """Browse or test a Sparkplug B source: what its births described so far."""

        births = self.births.get(source["id"])
        status = self.source_status.get(source["id"]) or {}
        if births is None or status.get("status") != "connected":
            detail = status.get("detail") or t("Not connected to the broker yet.")
            return "error", {"detail": detail}
        if request["kind"] == "test":
            return "ok", births.summary()
        variables = births.variables()
        if not variables:
            return "error", {
                "detail": t(
                    "Connected, no birth yet. Metrics appear when an edge node is born (it"
                    " connects or restarts); Historian never asks for a rebirth."
                )
            }
        return "ok", {"variables": variables, "truncated": False, "limit": SEEN_LIMIT}
