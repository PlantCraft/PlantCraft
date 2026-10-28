import { describe, expect, it } from "vitest";
import { algorithmOf, contents, copyName, editorPath, newAlgorithmId, tagOptions, traceOfBlocks, withTags } from "./algorithms";

const CATALOG = {
  libraries: [
    { library: "input", name: "Inputs", description: "" },
    { library: "dq", name: "Data quality", description: "" },
    { library: "cpm", name: "Control loop performance", description: "" },
    { library: "output", name: "Outputs", description: "" },
  ],
  blocks: ["input.signal", "dq.frozen", "cpm.stiction_screening", "output.loop_health"].map((id) => ({
    block_id: id,
    library: id.split(".")[0],
    name: id,
    summary: "",
    description: "",
    reading: "",
    assumptions: [],
    limitations: [],
    references: [],
    inputs: [],
    outputs: id.startsWith("input") ? [{ port: "value", types: ["series"], type: "series", label: "Value", description: "", unit: "", required: false, multiple: false, record: false }]
      : [{ port: "index", types: ["number"], type: "number", label: "Index", description: "", unit: "", required: false, multiple: false, record: true },
        { port: "verdict", types: ["result"], type: "result", label: "Verdict", description: "", unit: "", required: false, multiple: false, record: false }],
    parameters: [],
  })),
};

describe("algorithms", () => {
  it("opens an algorithm by its id or by the 0.2 protocol id it replaced", () => {
    const items = [{ algorithm_id: "loop_health", aliases: ["all", "flow_control"] }, { algorithm_id: "control_valve", aliases: ["valve"] }];
    expect(algorithmOf(items, "control_valve")?.algorithm_id).toBe("control_valve");
    expect(algorithmOf(items, "flow_control")?.algorithm_id).toBe("loop_health");
    expect(algorithmOf(items, "nope")).toBeUndefined();
    expect(algorithmOf(items, null)).toBeUndefined();
  });

  it("names a copy and gives it a free id", () => {
    expect(copyName("Control valve")).toBe("Control valve (copy)");
    expect(newAlgorithmId("Control valve (copy)", [])).toBe("control_valve_copy");
    expect(newAlgorithmId("Válvula de controle", ["valvula_de_controle"])).toBe("valvula_de_controle_2");
    expect(newAlgorithmId("!!!", [])).toBe("algorithm");
  });

  it("opens the editor's window on an algorithm, a new one or a copy", () => {
    expect(editorPath("loop_health")).toBe("/editor/loop_health");
    expect(editorPath(null)).toBe("/editor/new");
    expect(editorPath(null, "control_valve")).toBe("/editor/new?from=control_valve");
    expect(editorPath(null, undefined, "reactor-loop")).toBe("/editor/new?model=reactor-loop");
  });

  it("draws what each block said in a run on its verdict output", () => {
    const nodes = [{ id: "pv", block: "input.signal" }, { id: "frozen", block: "dq.frozen" }, { id: "stiction", block: "cpm.stiction_screening" }];
    const trace = traceOfBlocks(CATALOG, nodes, { frozen: { status: "bad", value: 20, message: "Frozen for 3 h." } });
    expect(trace).toEqual({ frozen: { verdict: { type: "result", status: "bad", value: 20, message: "Frozen for 3 h." } } });
  });

  it("sums a diagram up by library, leaving inputs and outputs out", () => {
    const nodes = [{ block: "input.signal" }, { block: "dq.frozen" }, { block: "dq.frozen" }, { block: "cpm.stiction_screening" }, { block: "output.loop_health" }];
    expect(contents(CATALOG, nodes)).toBe("2 data quality · 1 control loop performance");
  });
});

describe("the algorithms' tags", () => {
  const items = [{ tags: ["control loop"] }, { tags: ["data quality"] }, { tags: ["control loop", "fouling"] }, { tags: [] }];
  it("lists every tag once, by name, with how many carry it", () => {
    expect(tagOptions(items)).toEqual([
      { id: "control loop", label: "control loop", count: 2 },
      { id: "data quality", label: "data quality", count: 1 },
      { id: "fouling", label: "fouling", count: 1 },
    ]);
  });
  it("keeps the algorithms with any tag ticked, and all when none is", () => {
    expect(withTags(items, ["fouling", "data quality"])).toHaveLength(2);
    expect(withTags(items, [])).toHaveLength(4);
  });
});

describe("algorithmRoute", () => {
  it("reads the tab after the algorithm's id", async () => {
    const { algorithmRoute } = await import("./AlgorithmsPage");
    expect(algorithmRoute("level_loop")).toEqual({ algorithmId: "level_loop", tab: "overview" });
    expect(algorithmRoute("level_loop/diagram")).toEqual({ algorithmId: "level_loop", tab: "diagram" });
    expect(algorithmRoute("level_loop/used-by")).toEqual({ algorithmId: "level_loop", tab: "used-by" });
    expect(algorithmRoute("level_loop/nothing")).toEqual({ algorithmId: "level_loop", tab: "overview" });
  });
});
