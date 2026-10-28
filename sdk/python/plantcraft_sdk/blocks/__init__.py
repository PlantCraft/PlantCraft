"""Blocks and algorithms: the suite's dataflow contract (Link first, Models later).

A **block** is one calculation with typed, described inputs, outputs and parameters
(``contract``). An **algorithm** is a diagram of blocks wired output to input, checked before
it runs and run in order on a window of data (``graph``). Every block and algorithm is
described in one format that people read and the suite's assistants answer from (``docs``).

::

    from plantcraft_sdk.blocks import Block, BlockDocs, BlockSpec, compile_diagram, execute
    from plantcraft_sdk.blocks import inport, outport

    spec = BlockSpec(
        "demo.spread", "1.0", "demo", "Spread",
        BlockDocs(summary="...", description="...", reading="..."),
        inputs=(inport("x", "series", "Signal", "The values to measure."),),
        outputs=(outport("value", "number", "Spread", "Standard deviation of the window."),),
    )
    catalog = {spec.block_id: Block(spec, lambda i, p, ctx: {"value": float(i["x"].std())})}
    plan = compile_diagram(diagram, catalog)       # plan.errors, plan.node_errors
    values = execute(plan, catalog, Context(...))  # values.get(node_id, port_id)

The app owns its catalog, what an output does (publish a result, write a series) and where the
diagram is stored; the editor (``BlockEditor`` of ``@plantcraft/ui``) reads
``describe_block`` and the ``Plan`` report.
"""

from plantcraft_sdk.blocks.contract import (
    COERCIONS,
    PORT_TYPES,
    SEVERITY,
    STATUSES,
    TYPE_DESCRIPTIONS,
    Block,
    BlockDocs,
    BlockSpec,
    Context,
    NoData,
    NoParameters,
    Port,
    Result,
    accepts,
    inport,
    outport,
    parameter_unit,
)
from plantcraft_sdk.blocks.docs import (
    ALGORITHM_FIELDS,
    AlgorithmDocs,
    algorithm_markdown,
    block_image_path,
    block_markdown,
    check_algorithm,
    check_block,
    check_catalog,
    describe_block,
    parameters_of,
)
from plantcraft_sdk.blocks.graph import (
    VERSION,
    Plan,
    Values,
    Wire,
    compile_diagram,
    execute,
    label_of,
)

__all__ = [
    "ALGORITHM_FIELDS",
    "COERCIONS",
    "PORT_TYPES",
    "SEVERITY",
    "STATUSES",
    "TYPE_DESCRIPTIONS",
    "VERSION",
    "AlgorithmDocs",
    "Block",
    "BlockDocs",
    "BlockSpec",
    "Context",
    "NoData",
    "NoParameters",
    "Plan",
    "Port",
    "Result",
    "Values",
    "Wire",
    "accepts",
    "algorithm_markdown",
    "block_image_path",
    "block_markdown",
    "check_algorithm",
    "check_block",
    "check_catalog",
    "compile_diagram",
    "describe_block",
    "execute",
    "inport",
    "label_of",
    "outport",
    "parameter_unit",
    "parameters_of",
]
