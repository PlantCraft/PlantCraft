import { describe, expect, it } from "vitest";
import {
  accepts,
  addNode,
  arrange,
  byId,
  compatiblePorts,
  connect,
  copy,
  palette,
  blockLight,
  inputTraces,
  seriesPath,
  stateRuns,
  parameterValue,
  paste,
  record,
  redo,
  removeNodes,
  setParameter,
  snakeCase,
  newNodeId,
  startHistory,
  toggleRecord,
  traceText,
  undo,
  wireProblem,
  type BlockCatalog,
  type BlockSpec,
  type Diagram,
  type PortSpec,
} from "./blockModel";

function port(id: string, types: string[], extra: Partial<PortSpec> = {}): PortSpec {
  return { port: id, types, type: types[0], label: id.toUpperCase(), description: `${id} port.`, unit: "", required: true, multiple: false, record: false, ...extra };
}

function block(id: string, library: string, inputs: PortSpec[], outputs: PortSpec[]): BlockSpec {
  return {
    block_id: id,
    library,
    name: id,
    summary: `${id} summary.`,
    description: "",
    reading: "",
    assumptions: [],
    limitations: [],
    references: [],
    inputs,
    outputs,
    parameters: [{ name: "gain", title: "Gain", description: "", unit: "", default: 1, schema: { type: "number" } }],
  };
}

const CATALOG: BlockCatalog = {
  libraries: [
    { library: "input", name: "Inputs", description: "" },
    { library: "cpm", name: "Loop performance", description: "" },
    { library: "logic", name: "Logic", description: "" },
    { library: "output", name: "Outputs", description: "" },
  ],
  blocks: [
    block("input.signal", "input", [], [port("value", ["series"])]),
    block("cpm.stiction", "cpm", [port("pv", ["series"]), port("op", ["series"])], [port("result", ["result"]), port("index", ["number"], { record: true })]),
    block("logic.worst", "logic", [port("in", ["result"], { multiple: true })], [port("result", ["result"])]),
    block("logic.limits", "logic", [port("x", ["number"])], [port("result", ["result"])]),
    block("output.result", "output", [port("in", ["result"])], []),
  ],
};
const BLOCKS = byId(CATALOG);

function diagram(): Diagram {
  return {
    version: 2,
    nodes: [
      { id: "pv", block: "input.signal" },
      { id: "op", block: "input.signal" },
      { id: "st", block: "cpm.stiction" },
      { id: "worst", block: "logic.worst" },
      { id: "out", block: "output.result" },
    ],
    edges: [
      { source: "pv", source_port: "value", target: "st", target_port: "pv" },
      { source: "op", source_port: "value", target: "st", target_port: "op" },
      { source: "st", source_port: "result", target: "worst", target_port: "in" },
      { source: "worst", source_port: "result", target: "out", target_port: "in" },
    ],
  };
}

describe("wires", () => {
  it("joins ports of matching types, and a verdict feeds a number with its score", () => {
    expect(accepts(["series"], "series")).toBe(true);
    expect(accepts(["number"], "result")).toBe(true);
    expect(accepts(["series"], "result")).toBe(false);
  });

  it("says why a wire cannot be drawn", () => {
    const d = diagram();
    expect(wireProblem(d, BLOCKS, { source: "st", source_port: "result", target: "st", target_port: "pv" })).toMatch("itself");
    expect(wireProblem(d, BLOCKS, { source: "st", source_port: "result", target: "out", target_port: "in" })).toBe("");
    expect(wireProblem(d, BLOCKS, { source: "pv", source_port: "value", target: "worst", target_port: "in" })).toMatch("takes result");
    // worst -> stiction's PV would be a loop (and a type mismatch); a result into limits is fine.
    expect(wireProblem(d, BLOCKS, { source: "out", source_port: "x", target: "pv", target_port: "y" })).toBe("Unknown port.");
  });

  it("refuses a loop", () => {
    const d = addNode(diagram(), BLOCKS, "logic.worst", { x: 0, y: 0 }).diagram;
    const looped = connect(d, BLOCKS, { source: "worst", source_port: "result", target: "worst_2", target_port: "in" });
    expect(wireProblem(looped, BLOCKS, { source: "worst_2", source_port: "result", target: "worst", target_port: "in" })).toMatch("loop");
  });

  it("lets a simulation model close a loop (feedback), when the app allows it", () => {
    const d = addNode(diagram(), BLOCKS, "logic.worst", { x: 0, y: 0 }).diagram;
    const looped = connect(d, BLOCKS, { source: "worst", source_port: "result", target: "worst_2", target_port: "in" });
    const back = { source: "worst_2", source_port: "result", target: "worst", target_port: "in" };
    expect(wireProblem(looped, BLOCKS, back, { loops: true })).toBe("");
    expect(connect(looped, BLOCKS, back, { loops: true }).edges).toContainEqual(back);
    expect(connect(looped, BLOCKS, back).edges).not.toContainEqual(back);
    expect(compatiblePorts(looped, BLOCKS, { node: "worst_2", port: "result", side: "source" }, { loops: true }).has("worst:in")).toBe(true);
  });

  it("replaces the wire of a single input and adds to a multiple one", () => {
    const d = diagram();
    const replaced = connect(d, BLOCKS, { source: "op", source_port: "value", target: "st", target_port: "pv" });
    expect(replaced.edges.filter((edge) => edge.target === "st" && edge.target_port === "pv").map((edge) => edge.source)).toEqual(["op"]);
    const limits = addNode(d, BLOCKS, "logic.limits", { x: 0, y: 0 });
    const both = connect(connect(limits.diagram, BLOCKS, { source: "st", source_port: "index", target: limits.id, target_port: "x" }), BLOCKS, {
      source: limits.id,
      source_port: "result",
      target: "worst",
      target_port: "in",
    });
    expect(both.edges.filter((edge) => edge.target === "worst")).toHaveLength(2);
  });

  it("lights the inputs a wire can enter while it is drawn", () => {
    const found = compatiblePorts(diagram(), BLOCKS, { node: "st", port: "result", side: "source" });
    // Not the Worst of: that wire is already there.
    expect([...found].sort()).toEqual(["out:in"]);
    const back = compatiblePorts(diagram(), BLOCKS, { node: "st", port: "pv", side: "target" });
    expect([...back].sort()).toEqual(["op:value"]);
  });
});

describe("editing", () => {
  it("adds blocks with unique ids and their recorded outputs", () => {
    const first = addNode(diagram(), BLOCKS, "cpm.stiction", { x: 10.4, y: 20.6 });
    expect(first.id).toBe("stiction");
    const second = addNode(first.diagram, BLOCKS, "cpm.stiction", { x: 0, y: 0 });
    expect(second.id).toBe("stiction_2");
    const node = second.diagram.nodes.find((item) => item.id === "stiction");
    expect(node).toMatchObject({ x: 10, y: 21, record: ["index"] });
  });

  it("removes blocks with their wires", () => {
    const d = removeNodes(diagram(), ["worst"]);
    expect(d.nodes.map((node) => node.id)).not.toContain("worst");
    expect(d.edges.some((edge) => edge.source === "worst" || edge.target === "worst")).toBe(false);
  });

  it("sets a parameter, and gives it back to its default", () => {
    const parameter = BLOCKS["cpm.stiction"].parameters[0];
    const set = setParameter(diagram(), "st", "gain", 3);
    const node = set.nodes.find((item) => item.id === "st")!;
    expect(parameterValue(node, parameter)).toBe(3);
    const reset = setParameter(set, "st", "gain", undefined).nodes.find((item) => item.id === "st")!;
    expect(parameterValue(reset, parameter)).toBe(1);
    expect(reset.parameters).toEqual({});
  });

  it("switches the recording of an output", () => {
    const on = toggleRecord(diagram(), "st", "index");
    expect(on.nodes.find((node) => node.id === "st")!.record).toEqual(["index"]);
    expect(toggleRecord(on, "st", "index").nodes.find((node) => node.id === "st")!.record).toBeUndefined();
  });

  it("copies and pastes blocks with the wires between them, under new ids", () => {
    const clip = copy(diagram(), ["st", "worst"]);
    expect(clip.edges).toHaveLength(1);
    const pasted = paste(diagram(), clip);
    expect(pasted.ids).toEqual(["st_2", "worst_2"]);
    expect(pasted.diagram.edges).toContainEqual({ source: "st_2", source_port: "result", target: "worst_2", target_port: "in" });
  });

  it("undoes and redoes", () => {
    const start = diagram();
    let history = startHistory(start);
    const next = removeNodes(start, ["out"]);
    history = record(history, next);
    expect(undo(history).present).toBe(start);
    expect(redo(undo(history)).present).toBe(next);
    expect(undo(undo(history)).present).toBe(start);
  });
});

describe("arrange", () => {
  it("lays blocks out in columns from inputs to outputs", () => {
    const placed = Object.fromEntries(arrange(diagram()).nodes.map((node) => [node.id, node]));
    expect(placed.pv.x).toBe(placed.op.x);
    expect(placed.st.x).toBeGreaterThan(placed.pv.x!);
    expect(placed.worst.x).toBeGreaterThan(placed.st.x!);
    expect(placed.out.x).toBeGreaterThan(placed.worst.x!);
    expect(placed.pv.y).not.toBe(placed.op.y);
  });

  it("never lays a block over another, whatever their heights", () => {
    const tall = (id: string) => ({ id, block: "logic.worst" });
    const wire = (source: string, target: string) => ({ source, source_port: "result", target, target_port: "in" });
    const fan: Diagram = {
      nodes: [{ id: "pv", block: "logic.worst" }, ...["a", "b", "c", "d"].map(tall), { id: "out", block: "output.result" }],
      edges: [wire("pv", "a"), wire("pv", "b"), wire("pv", "c"), wire("pv", "d"), wire("a", "out"), wire("d", "out")],
    };
    const sizes = Object.fromEntries(fan.nodes.map((node) => [node.id, { width: 220, height: node.id === "b" ? 400 : 120 }]));
    const placed = arrange(fan, { blocks: BLOCKS, sizes }).nodes;
    for (const one of placed) {
      for (const other of placed) {
        if (one === other || one.x !== other.x) continue;
        const [top, bottom] = one.y! < other.y! ? [one, other] : [other, one];
        expect(bottom.y!).toBeGreaterThanOrEqual(top.y! + sizes[top.id].height);
      }
    }
    // An input sits level with what it feeds, not above it all.
    expect(Math.min(...placed.map((node) => node.y!))).toBe(40);
  });

  it("keeps a feedback loop left to right from where it is entered", () => {
    // setpoint -> controller -> plant -> sensor -> back into the controller.
    const block = (id: string) => ({ id, block: "logic.worst" });
    const wire = (source: string, target: string) => ({ source, source_port: "result", target, target_port: "in" });
    const looped: Diagram = {
      nodes: ["sensor", "plant", "controller", "setpoint"].map(block),
      edges: [wire("setpoint", "controller"), wire("controller", "plant"), wire("plant", "sensor"), wire("sensor", "controller")],
    };
    const x = Object.fromEntries(arrange(looped).nodes.map((node) => [node.id, node.x!]));
    expect(x.setpoint).toBeLessThan(x.controller);
    expect(x.controller).toBeLessThan(x.plant);
    expect(x.plant).toBeLessThan(x.sensor);
  });
});

describe("node ids", () => {
  it("are block names in snake case, whatever case the block's id has", () => {
    expect(snakeCase("ControlValve")).toBe("control_valve");
    expect(snakeCase("PID")).toBe("pid");
    expect(snakeCase("PIDController")).toBe("pid_controller");
    expect(snakeCase("stiction_screening")).toBe("stiction_screening");
    expect(newNodeId("PlantCraftEquipment.ControlValve", [])).toBe("control_valve");
    expect(newNodeId("PlantCraftSources.Step", ["step"])).toBe("step_2");
    expect(newNodeId("cpm.stiction", [])).toBe("stiction");
  });
});

describe("palette and trace", () => {
  it("filters the palette by words, library by library", () => {
    expect(palette(CATALOG, "").map((item) => item.library.library)).toEqual(["input", "cpm", "logic", "output"]);
    expect(palette(CATALOG, "worst").flatMap((item) => item.blocks.map((b) => b.block_id))).toEqual(["logic.worst"]);
  });

  it("writes what a wire carried in a few characters", () => {
    expect(traceText({ type: "result", status: "bad", value: 12.345, message: "x" })).toBe("bad 12.35");
    expect(traceText({ type: "series", count: 120, t: [], v: [], last: 41.25 })).toBe("120 pts · 41.25");
    expect(traceText({ type: "missing", reason: "no PV" })).toBe("—");
    expect(traceText({ type: "number", value: 3 })).toBe("3");
  });
});

describe("a test run in the inspector", () => {
  const block = {
    ...CATALOG.blocks[0],
    outputs: [
      { port: "index", types: ["number"], type: "number", label: "Index", description: "", unit: "", required: false, multiple: false, record: false },
      { port: "verdict", types: ["result"], type: "result", label: "Verdict", description: "", unit: "", required: false, multiple: false, record: false },
    ],
  } as BlockSpec;

  it("lights a block with its first verdict, grey when its outputs had no data", () => {
    expect(blockLight(block, undefined)).toBeNull();
    expect(blockLight(block, { verdict: { type: "result", status: "bad", value: 3, message: "Stuck." } })).toEqual({ status: "bad", text: "Stuck." });
    expect(blockLight(block, { index: { type: "missing", reason: "No OP." } })).toEqual({ status: "unknown", text: "No OP." });
    expect(blockLight(block, { index: { type: "number", value: 2 } })).toBeNull();
  });

  it("finds what reached an input on each of its wires", () => {
    const diagram = {
      nodes: [{ id: "a", block: "x" }, { id: "b", block: "x" }, { id: "c", block: "y" }],
      edges: [
        { source: "a", source_port: "out", target: "c", target_port: "in" },
        { source: "b", source_port: "out", target: "c", target_port: "in" },
      ],
    };
    const trace = { a: { out: { type: "number", value: 1 } as const } };
    expect(inputTraces(diagram, trace, "c", "in")).toEqual([{ source: diagram.edges[0], value: { type: "number", value: 1 } }]);
    expect(inputTraces(diagram, null, "c", "in")).toEqual([]);
  });

  it("draws a series in its box and breaks the line on gaps", () => {
    expect(seriesPath([0, 10, 5], 100, 10)).toEqual({ d: "M0.0,10.0L50.0,0.0L100.0,5.0", min: 0, max: 10 });
    expect(seriesPath([1, "x", 1], 100, 10)?.d).toBe("M0.0,5.0M100.0,5.0");
    expect(seriesPath(["a"], 100, 10)).toBeNull();
  });

  it("cuts a mode signal into runs", () => {
    expect(stateRuns(["AUTO", "AUTO", "MAN", "AUTO"])).toEqual([
      { value: "AUTO", start: 0, share: 0.5 },
      { value: "MAN", start: 0.5, share: 0.25 },
      { value: "AUTO", start: 0.75, share: 0.25 },
    ]);
  });
});
