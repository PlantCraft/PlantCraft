import { describe, expect, it } from "vitest";
import { sketchDiagram } from "./algorithmSketch";

const port = (name: string, type: string, extra: Record<string, unknown> = {}) => ({ port: name, types: [type], type, label: name, description: "", unit: "", required: false, multiple: false, record: false, ...extra });
const block = (block_id: string, name: string, inputs: ReturnType<typeof port>[], outputs: ReturnType<typeof port>[], parameters: string[] = []) => ({
  block_id, library: block_id.split(".")[0], name, summary: "", description: "", reading: "", assumptions: [], limitations: [], references: [],
  inputs, outputs, parameters: parameters.map((item) => ({ name: item, title: item, description: "", unit: "", default: null, schema: {} })),
});
const CATALOG = {
  blocks: [
    block("input.signal", "Signal", [], [port("value", "series")]),
    block("dq.frozen", "Frozen signal", [port("series", "series")], [port("index", "number", { record: true }), port("verdict", "result")], ["hours"]),
    block("output.loop_health", "Loop health", [port("checks", "result", { multiple: true })], []),
  ],
};

describe("a diagram written as text", () => {
  it("places, wires and sets the blocks the assistant wrote", () => {
    const { diagram, problems } = sketchDiagram(["pv = input.signal", "frozen = Frozen signal", "- out: output.loop_health", "pv -> frozen", "frozen.verdict -> out.checks", "frozen.hours = 3"].join("\n"), CATALOG);
    expect(problems).toEqual([]);
    expect(diagram.nodes.map((node) => [node.id, node.block])).toEqual([["pv", "input.signal"], ["frozen", "dq.frozen"], ["out", "output.loop_health"]]);
    expect(diagram.edges).toEqual([
      { source: "pv", source_port: "value", target: "frozen", target_port: "series" },
      { source: "frozen", source_port: "verdict", target: "out", target_port: "checks" },
    ]);
    expect(diagram.nodes[1].parameters).toEqual({ hours: 3 });
    expect(diagram.nodes[1].record).toEqual(["index"]);
    // Arranged left to right.
    expect(diagram.nodes[0].x).toBeLessThan(diagram.nodes[1].x ?? 0);
  });

  it("keeps what it can and says what it could not read", () => {
    const { diagram, problems } = sketchDiagram("pv = input.signal\nx = nowhere.block\nk = 1\npv -> x\npv.value -> pv.value\npv.speed = 2\nplease wire it", CATALOG);
    expect(diagram.nodes).toHaveLength(1);
    expect(problems).toEqual(["Unknown block: nowhere.block", "k = 1: a constant is a block's parameter, not a block.", "Not understood: please wire it", "Unknown block in: pv -> x", "pv.value -> pv.value: No port fits.", "Unknown parameter: pv.speed = 2"]);
  });

  it("reads a block written as a call, and a port it does not have as any port that fits", () => {
    const { diagram, problems } = sketchDiagram("pv = input.signal\nfrozen = dq.frozen(series = pv, hours = 3)\nout = output.loop_health\nfrozen.value -> out", CATALOG);
    expect(problems).toEqual([]);
    expect(diagram.edges).toEqual([
      { source: "pv", source_port: "value", target: "frozen", target_port: "series" },
      { source: "frozen", source_port: "verdict", target: "out", target_port: "checks" },
    ]);
    expect(diagram.nodes.find((node) => node.id === "frozen")?.parameters).toEqual({ hours: 3 });
  });

  it("finds a block named by its id instead of its node, when the diagram has one of it", () => {
    const { diagram, problems } = sketchDiagram("pv = input.signal\nf = dq.frozen\npv -> f\nf.verdict -> output.checks\nh = output.loop_health", CATALOG);
    expect(problems).toEqual([]);
    expect(diagram.edges.at(-1)).toEqual({ source: "f", source_port: "verdict", target: "h", target_port: "checks" });
  });
});
