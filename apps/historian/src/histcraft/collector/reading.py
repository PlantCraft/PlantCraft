"""One value read from a source, as every reader hands it to the collector."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# A source timestamp further ahead than this is a wrong clock: the read time is used.
FUTURE_MS = 5 * 60 * 1000
# The qualities a value is archived with (OPC UA Part 4 status classes, plus "substituted" for a
# value a person or a source entered by hand). A source that reports none gives "good".
QUALITIES = ("good", "uncertain", "substituted", "bad")


@dataclass
class Reading:
    at_ms: int
    value: Any  # None when the value is missing or bad
    good: bool  # a value to archive (good, uncertain or substituted)
    detail: str = ""
    quality: str = "good"


def to_ms(stamp: datetime | None) -> int | None:
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return int(stamp.timestamp() * 1000)


def now_ms() -> int:
    return int(time.time() * 1000)
