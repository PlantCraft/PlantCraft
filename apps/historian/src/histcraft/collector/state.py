"""The collector's sizes and periods, each point's state while it is collected, and the small
checks the collector's parts share."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from histcraft.archive.compression import Compressor
from histcraft.catalog.store import CatalogStore
from histcraft.collector.reading import Reading
from histcraft.i18n import t
from histcraft.sparkplug import Births
from histcraft.vault import Vault

# The collector's log keeps its name from before the split.
LOGGER = logging.getLogger("histcraft.collector.service")
COMPACT_SECONDS = 3600
# What the archive keeps of each point (pages read it, never the whole archive) is counted again
# this often.
TOTALS_SECONDS = 300
# Chunks are merged once they are this old (the newest hour stays in small, fresh chunks).
COMPACT_AGE_MS = 3600 * 1000
# How often the values counted per point and hour reach the archive (``ArchiveStore.settle``).
COUNT_SECONDS = 600.0
# How often the data lake feeds are checked for a period that ended (``export.lake``).
LAKE_SECONDS = 60
REQUEST_WINDOW_MS = 10 * 60 * 1000
MAX_BACKOFF = 60.0
# Good text readings in a row that make a number point a text one (a MODE reading AUTO).
TEXT_READS = 3
# Hours of the source's history a point made text reads again (its old archive held no value).
TEXT_BACKFILL_HOURS = 48
# A gateway source with no value for this long (or three of its intervals) is disconnected.
GATEWAY_STALE_SECONDS = 60.0
# How often a subscribed OPC UA source is checked to answer (seconds).
SUBSCRIPTION_CHECK_SECONDS = 5.0
# How often a Sparkplug B source's messages are taken (seconds).
SPARKPLUG_TICK = 0.2
# Series the gateway sent that no point archives, kept per source for Browse.
SEEN_LIMIT = 20_000
# Values a point keeps in memory while the archive cannot be written (a day at one per second);
# past it the oldest go first.
HELD_LIMIT = 86_400


@dataclass
class PointState:
    point: dict[str, Any]
    compressor: Compressor
    pending: list[tuple[int, Any]] = field(default_factory=list)
    reads: int = 0
    archived: int = 0
    status: str = "waiting"
    detail: str = ""
    last: tuple[int, Any] | None = None
    # Good readings in a row that were text while the point is a number (see ``reads_text``).
    texts: int = 0
    # The quality of the values archived now, and its changes not written yet ``(ms, quality)``.
    quality: str = "good"
    # The source's whole status code with it (OPC UA sub-code and LimitBits), None when Good.
    code: int | None = None
    changes: list[tuple] = field(default_factory=list)

    @property
    def id(self) -> int:
        return int(self.point["id"])

    def configure(self, point: dict[str, Any]) -> None:
        self.point = point
        self.compressor.deviation = float(point["deviation"])
        self.compressor.percent = point.get("deviation_percent")
        self.compressor.exception = float(point.get("exception") or 0.0)
        self.compressor.exception_percent = point.get("exception_percent")
        self.compressor.max_seconds = float(point["max_seconds"])
        self.compressor.min_seconds = float(point.get("min_seconds") or 0.0)

    @property
    def reads_text(self) -> bool:
        """A number point whose source keeps answering text: it was added as the wrong kind."""

        return self.point["kind"] == "number" and self.texts >= TEXT_READS

    def take(self, reading: Reading) -> None:
        self.reads += 1
        if self.point["kind"] == "number":
            self.texts = self.texts + 1 if reading.good and _text(reading.value) else 0
        quality = reading.quality if reading.good else "bad"
        # A new sub-code or limit is a change too (H6): kept where the archive has a value.
        changed = quality != self.quality or reading.status != self.code
        if reading.good:
            self.status = "ok" if quality == "good" else quality
            self.detail = reading.detail if quality != "good" else ""
            self.last = (reading.at_ms, reading.value)
            out = self.compressor.feed(reading.at_ms, reading.value, keep=changed)
        else:
            self.status, self.detail = "bad", reading.detail
            out = self.compressor.gap(reading.at_ms)
        if changed and (out or not reading.good):
            # Kept only where the archive has a value (or the gap marker) at that time.
            self.quality, self.code = quality, reading.status
            self.changes.append(
                (reading.at_ms, quality, reading.status, reading.status_name or None)
            )
        self.pending.extend(out)
        self.archived += len(out)

    def lost(self, at_ms: int, detail: str) -> None:
        self.status, self.detail = "disconnected", detail
        out = self.compressor.gap(at_ms)
        self.pending.extend(out)
        self.archived += len(out)


def _compressor(point: dict[str, Any]) -> Compressor:
    return Compressor(
        deviation=float(point["deviation"]),
        max_seconds=float(point["max_seconds"]),
        min_seconds=float(point.get("min_seconds") or 0.0),
        percent=point.get("deviation_percent"),
        exception=float(point.get("exception") or 0.0),
        exception_percent=point.get("exception_percent"),
        kind=point["kind"],
        step=bool(point["step"]),
    )


def _text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


def _identity(point: dict[str, Any]) -> tuple:
    return (point["source_id"], point["address"], point["kind"], bool(point["step"]))


def _births_detail(births: Births, dropped: int) -> str:
    notes = []
    if births.unknown_aliases:
        notes.append(
            t(
                "{count} values by an alias no birth named: they are read from the node's next"
                " birth.",
                count=births.unknown_aliases,
            )
        )
    if births.sequence_gaps:
        notes.append(t("{count} gaps in the nodes' sequence.", count=births.sequence_gaps))
    if births.unreadable:
        notes.append(t("{count} messages that are not Sparkplug B.", count=births.unreadable))
    if dropped:
        notes.append(t("{count} messages dropped (the collector fell behind).", count=dropped))
    return " ".join(notes)


def _pushed_value(value: Any, kind: str) -> Any:
    if kind == "number" and isinstance(value, bool | int):
        return float(value)
    return value


def _describe(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return t("No answer from the server in time.")
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def source_password(source: dict[str, Any], catalog: CatalogStore, vault: Vault) -> str:
    """A source's password: its ``HISTCRAFT_SECRET_<NAME>`` variable, else the stored one."""

    if source.get("password_env"):
        return os.environ.get(source["password_env"], "")
    return vault.decrypt(catalog.secret(source["id"]))
