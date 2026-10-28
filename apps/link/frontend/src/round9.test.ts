import { describe, expect, it } from "vitest";
import { ALGORITHM_FORMAT, algorithmFile, parseAlgorithmFile } from "./algorithmFile";
import { newEditorPath } from "./AlgorithmNew";
import { ALGORITHM_TABS, algorithmRoute, algorithmVersionItem } from "./AlgorithmsPage";
import { BLOCK_TABS, blockRoute, blockVersions, versionAddress } from "./BlocksPage";
import { chartedOutput, OUTPUT_WINDOWS, SUBJECT_TABS, subjectPlace, subjectQuery } from "./ExecutionGroups";
import { lastValues } from "./RunView";
import { chosenFolder, comparedVersions, inFolder, NO_FOLDER } from "@plantcraft/ui";
import { algorithmComparison, blockComparison, hasSamples } from "./Compare";
import type { Algorithm } from "./types";

const ALGORITHM = {
  algorithm_id: "level_loop", name: "Level loop", description: "Judges a level loop.", system: true, subject_kind: "loop",
  diagram: { version: 2, nodes: [{ id: "pv", block: "input.series", parameters: { role: "pv" }, x: 0, y: 0 }], edges: [] },
  docs: { purpose: "Why", assets: "", when: "", reading: "", assistant: "" }, tags: ["control loop"],
} as unknown as Algorithm;

describe("round 9: blocks and algorithms made, edited and versioned the same way", () => {
  it("an algorithm goes to a file and back, and a wrong file says what is wrong", () => {
    const file = algorithmFile(ALGORITHM);
    expect(file.format).toBe(ALGORITHM_FORMAT);
    const back = parseAlgorithmFile(JSON.stringify(file));
    expect(back.name).toBe("Level loop");
    expect(back.diagram.nodes).toHaveLength(1);
    expect(back.timing.window_seconds).toBeGreaterThan(0);
    expect(() => parseAlgorithmFile("{")).toThrow("not a JSON file");
    expect(() => parseAlgorithmFile(JSON.stringify({ ...file, format: "other" }))).toThrow("not an algorithm file");
    expect(() => parseAlgorithmFile(JSON.stringify({ ...file, subject_kind: "pump" }))).toThrow("works on");
    expect(() => parseAlgorithmFile(JSON.stringify({ ...file, diagram: null }))).toThrow("no diagram");
  });

  it("the New algorithm form opens the editor with its name, kind and start", () => {
    expect(newEditorPath({ from: "", kind: "asset", name: "Fouling", description: "" })).toBe("/editor/new?kind=asset&name=Fouling");
    expect(newEditorPath({ from: "flow_loop", kind: "loop", name: "", description: "A copy" })).toBe("/editor/new?from=flow_loop&description=A+copy");
  });

  it("versions and edit are tabs of a block and an algorithm", () => {
    expect(blockRoute("dq.spikes/versions")).toEqual({ blockId: "dq.spikes", tab: "versions" });
    expect(blockRoute("dq.spikes/edit")).toEqual({ blockId: "dq.spikes", tab: "edit" });
    expect(algorithmRoute("level_loop/versions")).toEqual({ algorithmId: "level_loop", tab: "versions" });
    expect(algorithmRoute("level_loop/edit")).toEqual({ algorithmId: "level_loop", tab: "edit" });
  });

  it("a block Analytics ships is one version; the site's edits are listed newest first as saved", () => {
    expect(blockVersions({ site: false, versions: [], number: null, version: "0.4.0" })).toEqual([
      expect.objectContaining({ number: 1, current: true, note: "ships with Analytics 0.4.0" }),
    ]);
    const site = blockVersions({ site: true, number: 2, version: "0.4.0", versions: [
      { number: 2, name: "Wider", description: "Window 30 min", author_name: "Ana", created_at: "2026-10-25T12:00:00Z", shipped: false },
      { number: 1, name: "Link's version", description: "", author_name: "PlantCraft", created_at: null, shipped: true },
    ] } as never);
    expect(site.map((item) => [item.number, item.current, item.description])).toEqual([[2, true, "Window 30 min"], [1, false, ""]]);
  });

  it("a block's tabs follow the owner's order and any version opens on the block's page (D15, D17)", () => {
    expect(BLOCK_TABS).toEqual(["inputs", "code", "test", "used-by", "versions"]);
    expect(versionAddress("/blocks/custom.smooth", 1, { in_use: 2 })).toBe("/blocks/custom.smooth?version=1");
    expect(versionAddress("/blocks/custom.smooth", 2, { in_use: 2 })).toBe("/blocks/custom.smooth");
    // The page of version 1 still marks version 2 as the one in use.
    const shown = blockVersions({ site: true, number: 1, in_use: 2, version: "0.4.0", versions: [
      { number: 2, name: "Five", description: "", author_name: "Ana", created_at: null },
      { number: 1, name: "First", description: "", author_name: "Ana", created_at: null },
    ] } as never);
    expect(shown.map((item) => [item.number, item.current])).toEqual([[2, true], [1, false]]);
  });

  it("an algorithm has a block's tabs and its versions carry their own name and note (D19)", () => {
    expect(ALGORITHM_TABS.slice(0, 5)).toEqual(["inputs", "diagram", "test", "used-by", "versions"]);
    const base = { version: 3, name: "Level loop", description: "Judges a level loop.", saved_at: null, saved_by: "Ana", current: true };
    expect(algorithmVersionItem({ ...base, version_name: "Wider", version_note: "Two hours." })).toMatchObject({ number: 3, name: "Wider", description: "Two hours." });
    expect(algorithmVersionItem(base)).toMatchObject({ name: "Level loop", description: "Judges a level loop." });
  });
});

describe("round 10: an execution's runs", () => {
  it("opens on the overview or its runs, a run (the last one too) inside the runs", () => {
    expect(SUBJECT_TABS).toEqual(["overview", "runs"]);
    expect(subjectQuery("")).toEqual({ tab: "overview", run: "", last: false });
    // The old Last run tab opens the last run, in the runs.
    expect(subjectQuery("?tab=last-run")).toEqual({ tab: "runs", run: "", last: true });
    expect(subjectQuery("?tab=runs&run=last")).toEqual({ tab: "runs", run: "", last: true });
    expect(subjectQuery("?run=abc")).toEqual({ tab: "runs", run: "abc", last: false });
    expect(subjectQuery("?tab=nope")).toEqual({ tab: "overview", run: "", last: false });
  });

  it("charts the output chosen while it exists, else the first", () => {
    const series = [{ id: "a.health" }, { id: "a.ua" }];
    expect(chartedOutput(series, "")).toBe("a.health");
    expect(chartedOutput(series, "a.ua")).toBe("a.ua");
    expect(chartedOutput(series, "gone")).toBe("a.health");
    expect(chartedOutput([], "x")).toBe("");
    expect(OUTPUT_WINDOWS).toEqual(["1h", "24h", "7d", "30d"]);
  });

  it("draws an old run's one-point series as its last value", () => {
    const trace = lastValues({ n: { out: { type: "series", count: 90, t: ["x"], v: [3], last: 3 }, ok: { type: "series", count: 2, t: ["x", "y"], v: [1, 2], last: 2 } } });
    expect(trace.n.out).toEqual({ type: "number", value: 3 });
    expect(trace.n.ok.type).toBe("series");
  });

  it("names the subject's own page for what it is, not 'Open the asset'", () => {
    expect(subjectPlace("/loops/fic-101")).toBe("Loop page");
    expect(subjectPlace("/signals/x")).toBe("Signal page");
    expect(subjectPlace("/assets/tic-104")).toBe("Asset page");
  });
});

describe("round 9: folders (D14)", () => {
  const list = { folders: [{ folder_id: "f1", kind: "algorithm" as const, name: "Valves", count: 1, created_by: "Ana", created_at: "" }], items: { a: { item_id: "a", folder_id: "f1", moved_by: "Ana", moved_at: "" } } };
  it("reads the folder a list shows from its address", () => {
    expect(chosenFolder("?folder=f1")).toBe("f1");
    expect(chosenFolder("")).toBe("");
  });
  it("shows everything, one folder's objects, or those in no folder", () => {
    expect(inFolder(list, "a", "")).toBe(true);
    expect(inFolder(list, "a", "f1")).toBe(true);
    expect(inFolder(list, "b", "f1")).toBe(false);
    expect(inFolder(list, "b", NO_FOLDER)).toBe(true);
    expect(inFolder(list, "a", NO_FOLDER)).toBe(false);
    expect(inFolder(null, "a", "f1")).toBe(false);
  });
});

describe("round 9: compare versions (D18)", () => {
  it("reads two or three distinct versions from the address", () => {
    expect(comparedVersions("?versions=3,1,3")).toEqual([1, 3]);
    expect(comparedVersions("?versions=4,2,1,3")).toEqual([1, 2, 3]);
    expect(comparedVersions("?versions=x,0")).toEqual([]);
  });

  it("shows a block's inputs once and each output per version", () => {
    const series = { type: "series" as const, count: 2, t: ["a", "b"], v: [1, 2], last: 2 };
    const found = blockComparison([
      { inputs: { x: series }, outputs: { y: series, n: { type: "number", value: 1 } } },
      { inputs: { x: series }, outputs: { y: series } },
    ], { y: "Smoothed" });
    expect(found.inputs.map((row) => row.key)).toEqual(["x"]);
    expect(found.series.map((row) => row.label)).toEqual(["Smoothed"]);
    expect(found.values[0].values[1]).toBeUndefined();
    expect(hasSamples(found.series[0])).toBe(true);
  });

  it("lines an algorithm's outputs and recorded series up by version", () => {
    const diagram = { nodes: [{ id: "pv", block: "input.signal", parameters: { role: "pv" } }, { id: "m", block: "model.fmu", record: ["y"] }], edges: [] };
    const found = algorithmComparison([
      { diagram, trace: { pv: { value: { type: "number", value: 1 } }, m: { y: { type: "number", value: 2 } } }, outputs: [{ node_id: "o", kind: "result", name: "Health", key: "health", status: "ok", value: 90, message: "" }] },
      { diagram, trace: {}, outputs: [] },
    ]);
    expect(found.inputs.map((row) => row.label)).toEqual(["pv · value"]);
    expect(found.values[0].values.map((value) => value?.type)).toEqual(["result", undefined]);
    expect(found.series[0].key).toBe("m.y");
  });
});
