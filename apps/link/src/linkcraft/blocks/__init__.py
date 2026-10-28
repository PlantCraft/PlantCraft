"""PlantCraft Analytics's blocks and algorithms (``plantcraft_sdk.blocks`` contract).

Every calculation Link makes is a block with typed, described inputs, outputs and parameters;
an algorithm is a diagram of them, checked before it runs. The libraries:

- ``input``: the asset's signals by role (``input.signal``, ``input.state``) and the Signal
  quality algorithm's verdicts (``input.verdict``);
- ``dq``: data quality, the signal checks (``dq.frozen``…) and the loop data check
  (``dq.loop_data``);
- ``transform``: signal arithmetic and filters;
- ``cpm``: the control loop performance methods (``cpm.<method id>``);
- ``model``: a block per published model (``model.fmu_<model id>``: the FMU run on the asset's
  signals, its predictions and residuals), the deviation of the plant from a model
  (``model.deviation``, Hotelling's T²) and when the unit is in operation (``model.operating``);
- ``logic``: worst of, average, rule, limit check;
- ``output``: loop health, result on the asset, message, signal verdict.

What a block reads besides its inputs is in ``Context.extra``: ``frame`` (the loop's regular
frame), ``raw`` (samples as recorded, one column per role), ``roles`` (the roles the asset has),
``dataset`` (the loop's ``LoopDataset`` without data), ``analysis``, ``external_quality`` and
``verdicts`` (Signal quality's word on the loop's signals), ``signal`` and ``checks_on`` /
``check_layers`` (one signal of the Signal quality algorithm). Output blocks leave what they
publish in ``extra["collected"]``; model blocks run their FMU through ``extra["models"]`` (a
``blocks.models.ModelRuntime``).
"""

from linkcraft.blocks.catalog import (
    CATALOG,
    GATE_ID,
    HEALTH_ID,
    SIGNAL_OUTPUT_ID,
    catalog_items,
    compile_algorithm,
    libraries,
    method_of,
    node_for_method,
    register_models,
)

__all__ = [
    "CATALOG",
    "GATE_ID",
    "HEALTH_ID",
    "SIGNAL_OUTPUT_ID",
    "catalog_items",
    "compile_algorithm",
    "libraries",
    "method_of",
    "node_for_method",
    "register_models",
]
