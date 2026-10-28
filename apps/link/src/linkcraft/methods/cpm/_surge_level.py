"""Which loops the surge-level methods apply to.

``disturbance_attenuation`` and ``operating_band_fraction`` judge a level that is meant to
buffer disturbances: it may wander inside a band so the outflow stays smooth. On a loop that
must hold its setpoint (flow, pressure, temperature, composition) a moving output is the
control working, not a failure to absorb, and a 20-80 band in % has no meaning, so there the
methods do not apply. They return ``not_applicable`` (left out of the score, with the reason),
never a zero.

The loop type comes from the asset record (``dataset.metadata["loop_type"]``). Without one the
data cannot tell a surge level from a tight one, so the methods apply only when the algorithm
says the loop is a surge level (``assume_surge_level``, set by the Surge level algorithm).
"""

from __future__ import annotations

from plantcraft_sdk.methods import LoopDataset

from linkcraft.i18n import t

SURGE_LEVEL_TYPES = {"level"}


def not_a_surge_level(dataset: LoopDataset, assume_surge_level: bool) -> str | None:
    """Why the method does not apply to this loop, or ``None`` when it does."""

    loop_type = (dataset.metadata or {}).get("loop_type")
    loop_type = loop_type.strip().lower() if isinstance(loop_type, str) else ""
    if loop_type:
        if loop_type in SURGE_LEVEL_TYPES:
            return None
        return t(
            "Applies to surge levels that buffer disturbances; the asset record says this is a "
            "{loop_type} loop, which must hold its setpoint.",
            loop_type=loop_type,
        )
    if assume_surge_level:
        return None
    return t(
        "Applies to surge levels that buffer disturbances; the asset record gives no loop type, "
        "so Analytics cannot tell. Set the loop type to level in PlantCraft, or choose the "
        "Surge level algorithm."
    )
