"""The 50-loop portfolio: small deterministic closed loops for the PlantCraft demo.

Each loop is a discrete PI controller on a first-order process with dead time and one
known behaviour (healthy, oscillation, stiction, saturation, manual, noise, setpoint activity,
sensor drift, disturbance, interaction). `simcraft loops serve` publishes them through
OPC UA; `simcraft loops catalog` prints them as JSON for whoever configures the loops.
"""

from .dynamics import (
    LOOP_DEFINITIONS,
    LoopDefinition,
    LoopState,
    initial_state,
    loop_catalog,
    simulate_step,
)

__all__ = [
    "LOOP_DEFINITIONS",
    "LoopDefinition",
    "LoopState",
    "initial_state",
    "loop_catalog",
    "simulate_step",
]
