"""The method SDK works on its own, without PlantCraft installed."""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pandas as pd

from plantcraft_sdk.methods import (
    Finding,
    LoopDataset,
    MethodStatus,
    NotEnoughData,
    method,
    param,
)


@method("pv_spread_sdk", name="PV spread", describe="Deviation {std:.2}.")
def pv_spread(pv, *, tolerance: float = param(1.0, gt=0, help="Acceptable deviation")):
    """PV standard deviation compared with a tolerance."""
    if len(pv) < 5:
        raise NotEnoughData("Need five samples.")
    std = float(pv.std())
    return Finding(score=100 * std / tolerance, metrics={"std": std})


def test_a_method_runs_and_words_its_finding():
    frame = pd.DataFrame({"pv": [1.0, 2.0, 1.0, 2.0, 1.0, 2.0]})
    dataset = LoopDataset(loop_id="FIC-1", data=frame)
    spec = pv_spread.METHOD_SPEC
    result = pv_spread.run(spec.input_schema(dataset=dataset), spec.parameter_schema(tolerance=2.0))
    assert result.status in {MethodStatus.OK, MethodStatus.WARNING, MethodStatus.BAD}
    assert pv_spread.describe(result.metrics).startswith("Deviation 0.")
    short = LoopDataset(loop_id="FIC-1", data=frame.head(3))
    assert (
        pv_spread.run(spec.input_schema(dataset=short), spec.parameter_schema()).status
        == "insufficient_data"
    )
    missing = LoopDataset(loop_id="FIC-1", data=pd.DataFrame({"op": [1.0] * 6}))
    assert (
        pv_spread.run(spec.input_schema(dataset=missing), spec.parameter_schema()).status
        == "insufficient_data"
    )


def test_the_sdk_imports_nothing_from_processcraft():
    code = textwrap.dedent(
        """
        import sys
        sys.modules["processcraft"] = None  # any import of it fails
        import pandas as pd
        from plantcraft_sdk import auth, client, contract, jwt, testing
        from plantcraft_sdk.methods import Finding, LoopDataset, method

        @method("x", name="X")
        def x(pv):
            return Finding(score=0)

        spec = x.METHOD_SPEC
        data = LoopDataset(loop_id="L", data=pd.DataFrame({"pv": [1.0, 2.0, 3.0]}))
        print(x.run(spec.input_schema(dataset=data), spec.parameter_schema()).status)
        """
    )
    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert output.stdout.strip() == "ok"


def test_the_host_can_install_its_translator():
    from plantcraft_sdk import i18n

    try:
        i18n.install(lambda text, **values: "T:" + text.format(**values), lambda: "xx")
        assert i18n.t("a {b}", b=1) == "T:a 1" and i18n.current_language() == "xx"
    finally:
        i18n._translate = i18n._language = None
    assert i18n.t("a {b}", b=1) == "a 1" and i18n.current_language() == "en"
