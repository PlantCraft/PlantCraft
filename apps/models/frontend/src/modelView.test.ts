import type { BlockCatalog, BlockSpec } from "@plantcraft/ui/blockEditor";
import { describe, expect, it } from "vitest";
import { modelPorts } from "./ModelPage";
import { modelView } from "./modelView";
import type { ModelDetail } from "./types";

const port = (name: string, unit = "") => ({ port: name, types: ["real"], type: "real", label: name, description: name, unit, required: true, multiple: false, record: false });
const spec = (block_id: string, inputs: string[], outputs: string[]): BlockSpec => ({
  block_id, library: "lib", name: block_id, summary: "", description: "", reading: "", assumptions: [], limitations: [], references: [],
  inputs: inputs.map((name) => port(name)), outputs: outputs.map((name) => port(name, "m")), parameters: [],
});
const CATALOG = { libraries: [], blocks: [spec("Step", [], ["y"]), spec("Lag", ["u"], ["y"]), spec("Scope", ["u"], [])] } as unknown as BlockCatalog;
const SETTINGS = { start: 0, stop: 10, interval: 0.1, tolerance: 1e-6, solver: "dassl" };

function detail(change: Partial<ModelDetail>): ModelDetail {
  return {
    project_id: "p", project: "p", group: "", example: false, model: "M", name: "Tank", description: "", file: "M.mo",
    updated_at: null, updated_by: null, diagram: { version: 1, nodes: [], edges: [] }, settings: SETTINGS, problems: [], editable: true, ...change,
  };
}

describe("one kind of model", () => {
  it("draws a diagram model as it is", () => {
    const diagram = {
      version: 1,
      nodes: [{ id: "step", block: "Step" }, { id: "lag", block: "Lag", label: "Tank" }, { id: "scope", block: "Scope" }],
      edges: [{ source: "step", source_port: "y", target: "lag", target_port: "u" }, { source: "lag", source_port: "y", target: "scope", target_port: "u" }],
    };
    const view = modelView(detail({ diagram }), CATALOG);
    expect(view.code).toBe(false);
    expect(view.diagram).toBe(diagram);
    const { reads, gives } = modelPorts(diagram, CATALOG);
    expect(reads.map((item) => item.name)).toEqual(["step"]);
    expect(gives.map((item) => [item.name, item.label, item.unit])).toEqual([["lag.y", "Tank · y", "m"]]);
  });

  it("draws a model written as code as its one block", () => {
    const block = spec("modelica:Pkg.Furnaces", ["fuel"], ["T", "P"]);
    const view = modelView(detail({ editable: false, code_block: block, name: "Furnaces" }), CATALOG);
    expect(view.code).toBe(true);
    expect(view.diagram.nodes).toEqual([{ id: "model", block: "modelica:Pkg.Furnaces", label: "Furnaces", parameters: {}, x: 0, y: 0 }]);
    expect(view.catalog.blocks.at(-1)).toBe(block);
    const { reads, gives } = modelPorts(view.diagram, view.catalog);
    expect(reads.map((item) => item.name)).toEqual(["fuel"]);
    expect(gives.map((item) => item.name)).toEqual(["T", "P"]);
  });
});
