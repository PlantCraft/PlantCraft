"""Write an analysis method once; PlantCraft and every app of the suite run it the same way.

::

    from plantcraft_sdk.methods import Finding, method, param

    @method("pv_spread", name="PV spread", describe="PV deviation of {std:.2}.")
    def pv_spread(pv, *, tolerance: float = param(1.0, gt=0, help="Acceptable deviation")):
        \"\"\"PV standard deviation compared with a tolerance.\"\"\"
        std = float(pv.std())
        return Finding(score=100 * std / tolerance, metrics={"std": std})

``contracts`` holds the typed shapes (``LoopDataset``, ``MethodResult``...),
``utils`` the helpers hand-written methods share and ``findings`` the number
formatting used when a finding is worded for people.
"""

from plantcraft_sdk.methods.contracts import (
    DataQuality,
    EvidenceItem,
    InputPort,
    LoopDataset,
    MethodBlockSpec,
    MethodEvent,
    MethodMaturity,
    MethodMetadata,
    MethodResult,
    MethodStatus,
    OutputPort,
    ScientificReference,
    Severity,
)
from plantcraft_sdk.methods.decorator import (
    Finding,
    MethodBlock,
    NotEnoughData,
    method,
    param,
)

__all__ = [
    "DataQuality",
    "EvidenceItem",
    "Finding",
    "InputPort",
    "LoopDataset",
    "MethodBlock",
    "MethodBlockSpec",
    "MethodEvent",
    "MethodMaturity",
    "MethodMetadata",
    "MethodResult",
    "MethodStatus",
    "NotEnoughData",
    "OutputPort",
    "ScientificReference",
    "Severity",
    "method",
    "param",
]
