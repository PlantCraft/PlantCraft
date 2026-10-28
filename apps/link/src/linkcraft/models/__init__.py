"""Process models in PlantCraft Analytics: FMU files, running them, and judging how far the plant is
from them.

- ``fmu``: what an FMU is, read from its description without running it;
- ``store``: the published models (built-in FMUs and those people publish from PlantCraft
  Models or upload);
- ``simulate``: running an FMU, only ever in a separate worker process with a timeout;
- ``stats``: residual statistics: calibration, Hotelling's T², its limit and contributions.

The blocks that use them are in ``linkcraft.blocks.models``. Came from PlantCraft Twin.
"""
