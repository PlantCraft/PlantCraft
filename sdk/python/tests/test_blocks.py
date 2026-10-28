"""plantcraft_sdk.blocks: the block contract, diagram checks, runs and descriptions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import BaseModel, Field

from plantcraft_sdk.blocks import (
    AlgorithmDocs,
    Block,
    BlockDocs,
    BlockSpec,
    Context,
    NoData,
    Result,
    accepts,
    algorithm_markdown,
    block_markdown,
    check_algorithm,
    check_block,
    check_catalog,
    compile_diagram,
    describe_block,
    execute,
    inport,
    outport,
    parameters_of,
)

INDEX = pd.date_range("2026-10-22", periods=600, freq="5s")
DATA = {
    "pv": pd.Series(np.sin(np.arange(600) / 20) + 50, INDEX),
    "op": pd.Series(np.clip(np.arange(600) / 5, 0, 100), INDEX),
}


def _docs(name: str) -> BlockDocs:
    return BlockDocs(
        summary=f"Measures the {name} of the window so a person sees it at a glance.",
        description=(
            f"Computes the {name} over the samples of the analysed window and gives it on its "
            "outputs, in the units of its input."
        ),
        reading="Ok when the value stays inside the limits, bad when it leaves them.",
    )


class Role(BaseModel):
    role: str = Field(default="pv", description="Which of the asset's signals to read.")


class Tau(BaseModel):
    tau: float = Field(default=30.0, gt=0, description="Filter time constant, in seconds.")


class Hi(BaseModel):
    hi: float = Field(default=95.0, description="Output above which the valve is saturated.")


def _read(inputs, params, ctx):
    value = ctx.extra["data"][params.role]
    if value is None:
        raise ValueError("no samples")
    return {"value": value}


def _stiction(inputs, _params, _ctx):
    index = float((inputs["op"].diff().abs() < 0.01).mean())
    status = "warning" if index > 0.2 else "ok"
    return {"result": Result(status, 100 - 100 * index, "Valve check."), "index": index}


def _saturation(inputs, params, _ctx):
    share = float((inputs["op"] > params.hi).mean())
    return {"result": Result("bad" if share > 0.1 else "ok", 100 - 100 * share, "Saturation.")}


def _worst(inputs, _params, _ctx):
    judged = [item for item in inputs["in"] if isinstance(item, Result) and item.value is not None]
    if not judged:
        return {"result": Result.unknown("Nothing to judge.")}
    return {"result": min(judged, key=lambda item: item.value)}


CAUGHT: list = []


def _sink(inputs, _params, _ctx):
    CAUGHT.append(inputs["in"])
    return {}


SERIES_OUT = outport("value", "series", "Value", "The signal over the window.")
RESULT_OUT = outport("result", "result", "Result", "The block's judgement of the window.")
CATALOG = {
    block.spec.block_id: block
    for block in (
        Block(
            BlockSpec(
                "input.signal",
                "1",
                "input",
                "Signal",
                _docs("signal"),
                outputs=(SERIES_OUT,),
                parameters=Role,
            ),
            _read,
        ),
        Block(
            BlockSpec(
                "transform.lowpass",
                "1",
                "transform",
                "Low-pass filter",
                _docs("filter"),
                inputs=(inport("x", "series", "Signal", "The signal to smooth."),),
                outputs=(SERIES_OUT,),
                parameters=Tau,
            ),
            lambda i, p, _c: {"value": i["x"].ewm(alpha=1 - np.exp(-5 / p.tau)).mean()},
        ),
        Block(
            BlockSpec(
                "cpm.stiction",
                "1",
                "cpm",
                "Valve stiction",
                _docs("stiction"),
                inputs=(
                    inport("pv", "series", "PV", "The measured process value."),
                    inport("op", "series", "OP", "The controller output.", unit="%"),
                ),
                outputs=(
                    RESULT_OUT,
                    outport(
                        "index",
                        "number",
                        "Index",
                        "Share of stuck samples.",
                        record=True,
                        better="lower",
                    ),
                ),
            ),
            _stiction,
        ),
        Block(
            BlockSpec(
                "cpm.saturation",
                "1",
                "cpm",
                "Saturation",
                _docs("saturation"),
                inputs=(inport("op", "series", "OP", "The controller output.", unit="%"),),
                outputs=(RESULT_OUT,),
                parameters=Hi,
            ),
            _saturation,
        ),
        Block(
            BlockSpec(
                "logic.worst",
                "1",
                "logic",
                "Worst of",
                _docs("worst result"),
                inputs=(
                    inport(
                        "in",
                        ("result", "number"),
                        "Results",
                        "The results to compare.",
                        multiple=True,
                    ),
                ),
                outputs=(RESULT_OUT,),
                runs_on_missing=True,
            ),
            _worst,
        ),
        Block(
            BlockSpec(
                "output.result",
                "1",
                "output",
                "Result on the asset",
                _docs("result"),
                inputs=(inport("in", "result", "Result", "The result to publish."),),
                runs_on_missing=True,
            ),
            _sink,
        ),
        Block(
            BlockSpec(
                "output.number",
                "1",
                "output",
                "Number out",
                _docs("number"),
                inputs=(inport("in", "number", "Number", "The number to publish."),),
                runs_on_missing=True,
            ),
            _sink,
        ),
    )
}


def _valve() -> dict:
    nodes = [
        {"id": "pv", "block": "input.signal", "parameters": {"role": "pv"}},
        {"id": "op", "block": "input.signal", "parameters": {"role": "op"}},
        {"id": "f1", "block": "transform.lowpass", "parameters": {"tau": 30}},
        {"id": "f2", "block": "transform.lowpass", "parameters": {"tau": 120}},
        {"id": "st", "block": "cpm.stiction", "record": ["index"]},
        {"id": "sat", "block": "cpm.saturation"},
        {"id": "w", "block": "logic.worst"},
        {"id": "out", "block": "output.result"},
    ]
    wires = [
        ("pv", "value", "f1", "x"),
        ("f1", "value", "f2", "x"),
        ("f2", "value", "st", "pv"),
        ("op", "value", "st", "op"),
        ("op", "value", "sat", "op"),
        ("st", "result", "w", "in"),
        ("sat", "result", "w", "in"),
        ("w", "result", "out", "in"),
    ]
    edges = [dict(zip(("source", "source_port", "target", "target_port"), item)) for item in wires]
    return {"version": 2, "nodes": nodes, "edges": edges}


def _context(**data) -> Context:
    return Context(extra={"data": {**DATA, **data}})


def test_a_valve_diagram_compiles_and_runs_in_order():
    plan = compile_diagram(_valve(), CATALOG)
    assert plan.valid, plan.errors
    assert plan.warnings == []
    assert plan.order.index("f1") < plan.order.index("f2") < plan.order.index("st")
    assert plan.recorded["st"] == ["index"]
    run = execute(plan, CATALOG, _context())
    worst = run.get("w", "result")
    assert worst.status == "bad" and worst.value == pytest.approx(79.3, abs=0.1)
    assert run.get("st", "index") == pytest.approx(0.165)
    assert run.missing == {}


def test_wires_must_join_ports_of_the_same_type():
    diagram = _valve()
    diagram["edges"].append(
        {"source": "sat", "source_port": "result", "target": "f1", "target_port": "x"}
    )
    diagram["edges"] = [
        edge
        for edge in diagram["edges"]
        if edge != {"source": "pv", "source_port": "value", "target": "f1", "target_port": "x"}
    ]
    plan = compile_diagram(diagram, CATALOG)
    assert not plan.valid
    assert any("takes series" in error for error in plan.node_errors["f1"])


def test_a_result_feeds_a_number_input_with_its_score():
    assert accepts(("number",), "result") and not accepts(("series",), "result")
    diagram = _valve()
    diagram["nodes"].append({"id": "n", "block": "output.number"})
    diagram["edges"].append(
        {"source": "sat", "source_port": "result", "target": "n", "target_port": "in"}
    )
    CAUGHT.clear()
    execute(compile_diagram(diagram, CATALOG), CATALOG, _context())
    assert pytest.approx(79.3, abs=0.1) in CAUGHT


def test_loops_unwired_inputs_and_double_wires_are_errors():
    diagram = _valve()
    diagram["edges"].append(
        {"source": "f2", "source_port": "value", "target": "f1", "target_port": "x"}
    )
    plan = compile_diagram(diagram, CATALOG)
    assert any("Input Signal of Low-pass filter receives two wires" in e for e in plan.errors)
    diagram = _valve()
    diagram["edges"] = [edge for edge in diagram["edges"] if edge["target"] != "f1"]
    diagram["edges"].append(
        {"source": "f2", "source_port": "value", "target": "f1", "target_port": "x"}
    )
    plan = compile_diagram(diagram, CATALOG)
    assert any("wiring loop" in error for error in plan.errors)
    assert {"f1", "f2"} <= set(plan.node_errors)
    diagram = _valve()
    diagram["edges"] = [edge for edge in diagram["edges"] if edge["target_port"] != "op"]
    plan = compile_diagram(diagram, CATALOG)
    assert "Input OP of Valve stiction is not wired." in plan.node_errors["st"]


def test_unknown_blocks_parameters_and_records_are_reported_on_their_block():
    diagram = _valve()
    diagram["nodes"][2]["parameters"] = {"tau": -1}
    diagram["nodes"][5]["record"] = ["nothing"]
    diagram["nodes"].append({"id": "x", "block": "no.such"})
    plan = compile_diagram(diagram, CATALOG)
    assert "parameter tau is not valid" in plan.node_errors["f1"][0]
    assert "no output nothing" in plan.node_errors["sat"][0]
    assert plan.node_errors["x"] == ["Unknown block: no.such."]


def test_a_diagram_needs_an_output_and_warns_about_dead_ends():
    diagram = _valve()
    diagram["nodes"] = [node for node in diagram["nodes"] if node["id"] != "out"]
    diagram["edges"] = [edge for edge in diagram["edges"] if edge["target"] != "out"]
    assert any("no output" in error for error in compile_diagram(diagram, CATALOG).errors)
    diagram = _valve()
    diagram["nodes"].append({"id": "lost", "block": "cpm.saturation"})
    diagram["edges"].append(
        {"source": "op", "source_port": "value", "target": "lost", "target_port": "op"}
    )
    plan = compile_diagram(diagram, CATALOG)
    assert plan.valid
    assert plan.node_warnings["lost"] == ["Saturation leads to no output and records nothing."]
    assert "lost" not in plan.node_warnings.get("st", [])


def test_a_failing_block_leaves_only_the_blocks_after_it_without_a_value():
    plan = compile_diagram(_valve(), CATALOG)
    run = execute(plan, CATALOG, _context(op=None))
    assert isinstance(run.get("op", "value"), NoData)
    assert "no samples" in run.missing["op"].reason
    assert isinstance(run.get("st", "index"), NoData)
    assert isinstance(run.get("sat", "result"), NoData)
    # The PV branch still ran; the worst-of block runs on what it has.
    assert isinstance(run.get("f2", "value"), pd.Series)
    assert run.get("w", "result").status == "unknown"


def test_an_optional_input_without_a_value_counts_as_not_wired():
    seen: list = []

    def read(inputs, _params, _ctx):
        seen.append(dict(inputs))
        return {"result": Result("ok", 100, "read")}

    spec = BlockSpec(
        "cpm.both",
        "1",
        "cpm",
        "Both signals",
        _docs("pair"),
        inputs=(
            inport("pv", "series", "PV", "The measured process value."),
            inport("sp", "series", "SP", "The setpoint, when the loop has one.", required=False),
        ),
        outputs=(RESULT_OUT,),
    )
    catalog = {**CATALOG, "cpm.both": Block(spec, read)}
    diagram = {
        "nodes": [
            {"id": "pv", "block": "input.signal", "parameters": {"role": "pv"}},
            {"id": "sp", "block": "input.signal", "parameters": {"role": "sp"}},
            {"id": "b", "block": "cpm.both"},
            {"id": "out", "block": "output.result"},
        ],
        "edges": [
            {"source": "pv", "source_port": "value", "target": "b", "target_port": "pv"},
            {"source": "sp", "source_port": "value", "target": "b", "target_port": "sp"},
            {"source": "b", "source_port": "result", "target": "out", "target_port": "in"},
        ],
    }
    plan = compile_diagram(diagram, catalog)
    run = execute(plan, catalog, _context(sp=None))
    assert run.get("b", "result").message == "read"
    assert seen[-1]["sp"] is None and isinstance(seen[-1]["pv"], pd.Series)
    # Nothing it is wired to has a value: the block does not run.
    run = execute(plan, catalog, _context(sp=None, pv=None))
    assert isinstance(run.get("b", "result"), NoData)


def test_preset_outputs_are_not_computed_again():
    plan = compile_diagram(_valve(), CATALOG)
    run = execute(plan, CATALOG, _context(), preset={("sat", "result"): Result("ok", 100, "x")})
    assert run.get("sat", "result").message == "x"


def test_block_state_is_kept_per_node():
    def count(_inputs, _params, ctx):
        ctx.state["runs"] = ctx.state.get("runs", 0) + 1
        return {"value": float(ctx.state["runs"])}

    spec = BlockSpec(
        "demo.counter",
        "1",
        "demo",
        "Counter",
        _docs("count"),
        outputs=(outport("value", "number", "Runs", "How many runs so far."),),
    )
    catalog = {**CATALOG, "demo.counter": Block(spec, count)}
    diagram = {
        "nodes": [{"id": "c", "block": "demo.counter"}, {"id": "n", "block": "output.number"}],
        "edges": [{"source": "c", "source_port": "value", "target": "n", "target_port": "in"}],
    }
    plan = compile_diagram(diagram, catalog)
    context = Context()
    execute(plan, catalog, context)
    assert execute(plan, catalog, context).get("c", "value") == 2.0
    assert context.states == {"c": {"runs": 2}}


def test_descriptions_are_held_to_one_format():
    assert check_catalog(CATALOG) == []
    thin = BlockSpec(
        "cpm.thin",
        "1",
        "cpm",
        "T",
        BlockDocs(summary="Short", description="x", reading=""),
        inputs=(inport("PV", "series", "PV", "pv"),),
        parameters=Tau,
    )
    problems = check_block(thin)
    assert any("name of" in item for item in problems)
    assert any("summary is one sentence" in item for item in problems)
    assert any("description of at least" in item for item in problems)
    assert any("input PV: the id" in item for item in problems)
    assert any("input PV: describe it" in item for item in problems)
    wrong = BlockSpec("other.x", "1", "cpm", "Wrong library", _docs("x"))
    assert check_block(wrong) == ["other.x: the id starts with its library (cpm)"]
    assert check_algorithm("Valve", AlgorithmDocs(purpose="Is the valve sticking?")) == [
        "Valve: assets of at least 40 characters",
        "Valve: when of at least 40 characters",
        "Valve: reading of at least 40 characters",
        "Valve: assistant of at least 40 characters",
    ]


def test_blocks_and_algorithms_are_written_for_people_and_assistants():
    spec = CATALOG["cpm.stiction"].spec
    described = describe_block(spec)
    assert [port["port"] for port in described["outputs"]] == ["result", "index"]
    assert described["outputs"][1]["record"] is True
    text = block_markdown(CATALOG["transform.lowpass"].spec)
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings == [
        "## Low-pass filter (`transform.lowpass`)",
        "### What it does",
        "### How to read it",
        "### Inputs",
        "### Outputs",
        "### Parameters",
    ]
    assert "- **Tau** (`tau`) (default 30.0, exclusiveMinimum 0): Filter time constant" in text
    plan = compile_diagram(_valve(), CATALOG)
    docs = AlgorithmDocs(purpose="Is the valve the cause of a loop's poor control?")
    text = algorithm_markdown("Control valve", docs, plan, CATALOG)
    assert text.startswith("# Control valve\n\n## Purpose\n\nIs the valve")
    assert "- **Valve stiction** (`cpm.stiction`)" in text
    assert "pv ← Low-pass filter › value" in text
    assert "Recorded in the historian: index." in text


def test_a_parameter_with_a_default_factory_shows_its_default():
    class Labels(BaseModel):
        labels: list[str] = Field(default_factory=lambda: ["man", "manual"])

    found = parameters_of(Labels)
    assert found[0]["default"] == ["man", "manual"]
