"""PlantCraft Simulator: the benchmark API here; the 50-loop portfolio is `simcraft.loops`."""

from importlib.metadata import version

from .catalog import Catalog, load_catalog
from .contracts import build_benchmark_manifest
from .engine import Observation, PlantSimulator, SimulationFrame, TruthEvent
from .profiles import RuntimeProfile, get_runtime_profile, load_runtime_profiles

__all__ = [
    "Catalog",
    "Observation",
    "PlantSimulator",
    "RuntimeProfile",
    "SimulationFrame",
    "TruthEvent",
    "build_benchmark_manifest",
    "get_runtime_profile",
    "load_catalog",
    "load_runtime_profiles",
]

__version__ = version("simcraft")
