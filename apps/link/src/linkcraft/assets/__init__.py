"""Algorithms that run on assets: a unit, a piece of equipment, any asset of PlantCraft.

A loop algorithm runs on a loop's PV, SP, OP and mode in the monitoring round; a signal
algorithm on each signal. An algorithm on assets runs on the assets it names, each on its own
short cycle (from ten seconds), and reads what its signal blocks ask for: a role of the asset,
a role of another asset (a loop of the unit) or a signal by its id. What PlantCraft Twin did
is one of them: a model block and a deviation block (``blocks.models``).

- ``run``: one run of a diagram on one asset over a window (also the editor's test);
- ``store``: each algorithm and asset's latest run, its blocks' memory and what was written;
- ``service``: the cycle that runs every algorithm on its assets when due and publishes.
"""

from linkcraft.assets.run import AssetTiming, run_on_asset
from linkcraft.assets.service import AssetService
from linkcraft.assets.store import AssetRunStore

__all__ = ["AssetRunStore", "AssetService", "AssetTiming", "run_on_asset"]
