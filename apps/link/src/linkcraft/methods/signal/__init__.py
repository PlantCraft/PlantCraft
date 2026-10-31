"""Signal data quality checks: one ``@method`` per check, each judging one
signal's raw samples. The Signal quality algorithm runs them (``signals/``)."""

from linkcraft.methods.signal.availability import availability
from linkcraft.methods.signal.drift import drift
from linkcraft.methods.signal.freshness import freshness
from linkcraft.methods.signal.frozen import frozen
from linkcraft.methods.signal.ne43 import ne43
from linkcraft.methods.signal.noise import noise
from linkcraft.methods.signal.range import out_of_range
from linkcraft.methods.signal.rate import rate
from linkcraft.methods.signal.resolution import resolution
from linkcraft.methods.signal.source_quality import source_quality
from linkcraft.methods.signal.spikes import spikes

# The order they run in and are listed.
METHOD_BLOCKS = [
    availability,
    source_quality,
    freshness,
    frozen,
    spikes,
    out_of_range,
    ne43,
    rate,
    noise,
    resolution,
    drift,
]

__all__ = ["METHOD_BLOCKS"]
