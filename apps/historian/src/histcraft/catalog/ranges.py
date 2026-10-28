"""Where a number point's range comes from, and the range suggested from its first day (D2).

Every number point has a range, which its compression is a share of. In order:

- ``source``: the server's (OPC UA ``EURange``, PI ``Zero`` and ``Span``), taken when the
  point is added;
- ``edited``: set by a person (the point page, a points CSV);
- ``suggested``: none of these, so the collector's housekeeping proposes one once the point
  has a day of values (``suggest``), for a person to confirm (saving it makes it ``edited``).

Empty (``""``) means no range yet. A suggestion never replaces a range already there.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

ORIGINS = ("source", "edited", "suggested")
# The values a suggestion is made from: the point's first day.
SUGGEST_AFTER_MS = 86_400_000
# Room on each side of what the first day saw, as a share of its width.
MARGIN = 0.1


def suggest(values: Iterable[float]) -> tuple[float, float] | None:
    """A range for the values of a first day: their extremes with a margin, rounded outward
    to two significant digits of the width; never below 0 for values that never were. None
    when there is no finite value."""

    finite = [float(value) for value in values if math.isfinite(value)]
    if not finite:
        return None
    least, most = min(finite), max(finite)
    width = most - least
    if width <= 0:
        width = max(abs(most) * MARGIN * 2, 1.0)
        low, high = least - width / 2, most + width / 2
    else:
        low, high = least - width * MARGIN, most + width * MARGIN
    unit = 10.0 ** (math.floor(math.log10(high - low)) - 1)
    low, high = math.floor(low / unit) * unit, math.ceil(high / unit) * unit
    if least >= 0 > low:
        low = 0.0
    return _tidy(low, unit), _tidy(high, unit)


def _tidy(value: float, unit: float) -> float:
    """``value`` without the float noise of the rounding (0.30000000000000004 is 0.3)."""

    digits = max(0, -math.floor(math.log10(unit)))
    return round(value, digits) + 0.0
