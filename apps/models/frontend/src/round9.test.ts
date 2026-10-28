import { describe, expect, it } from "vitest";
import { modelFileProblem } from "./ModelNew";
import { modelVersions } from "./ModelPage";
import { blockTab, modelTab, movedTo, studyRunPath } from "./paths";
import { sweepOf } from "./StudyForm";
import { comparedRuns, contractRows, revisionOf, seriesFacts, shownVersion } from "./Versions";

describe("round 9: Models follows Link's pages", () => {
  it("numbers a model's versions: the file now, then each text a save replaced", () => {
    const found = modelVersions([
      { id: 9, path: "A.mo", saved_by: "ana", saved_at: "2026-10-25T10:00:00Z", bytes: 10 },
      { id: 4, path: "A.mo", saved_by: "bia", saved_at: "2026-10-24T10:00:00Z", bytes: 9 },
    ], { by: "ana", at: "2026-10-25T10:00:00Z" });
    expect(found.map((item) => [item.number, Boolean(item.current)])).toEqual([[3, true], [2, false], [1, false]]);
    expect(found[0].author).toBe("ana");
    expect(found[1].note).toContain("replaced by ana");
    expect(modelVersions([], {})).toEqual([expect.objectContaining({ number: 1, current: true, note: "As Models ships it" })]);
    const named = modelVersions([{ id: 9, path: "A.mo", saved_by: "ana", saved_at: "2026-10-25T10:00:00Z", bytes: 10, version_name: "First", version_note: "" }],
      { by: "ana", at: "2026-10-25T11:00:00Z", name: "Faster valve", note: "Valve time 2 s." });
    expect(named.map((item) => [item.name, item.description])).toEqual([["Faster valve", "Valve time 2 s."], ["First", null]]);
  });

  it("has a Versions tab on models and blocks and a page for a new model", () => {
    expect(modelTab("versions")).toBe("versions");
    expect(blockTab("versions")).toBe("versions");
    expect(movedTo("/models", "?new=1")).toBe("/models/new");
    expect(movedTo("/models", "")).toBeNull();
  });

  it("imports only a Modelica file with a model in it", () => {
    expect(modelFileProblem("Heater.mo", "model Heater\nend Heater;")).toBe("");
    expect(modelFileProblem("Heater.txt", "model Heater\nend Heater;")).not.toBe("");
    expect(modelFileProblem("Pkg.mo", "package Pkg\nend Pkg;")).not.toBe("");
  });
});

describe("round 9 Q7c: studies", () => {
  const row = (change: Record<string, string>) => ({ mode: "model", value: "", start: "", stop: "", count: "5", values: "", ...change }) as Parameters<typeof sweepOf>[0][string];

  it("drive the model's inputs: a fixed or swept value, held, stepped or ramped", () => {
    const { sweep, overrides, inputs } = sweepOf({
      u: row({ mode: "list", values: "60 70", shape: "step", before: "50", at: "100" }),
      d: row({ mode: "fixed", value: "55" }),
      e: row({ mode: "fixed", value: "1", shape: "ramp", before: "0", at: "10", end: "20" }),
      f: row({ mode: "model", shape: "step" }),
    }, ["u", "d", "e", "f"]);
    expect(sweep).toEqual([{ name: "u", mode: "list", values: [60, 70] }]);
    expect(overrides).toEqual({ d: 55, e: 1 });
    expect(inputs).toEqual({ u: { shape: "step", before: 50, at: 100 }, d: { shape: "constant" }, e: { shape: "ramp", before: 0, at: 10, end: 20 } });
    expect(() => sweepOf({ e: row({ mode: "fixed", value: "1", shape: "ramp", before: "0", at: "10", end: "5" }) }, ["e"])).toThrow(/ramp/);
  });

  it("vary the simulation settings, the integrators by name", () => {
    const { sweep } = sweepOf({
      "@method": row({ mode: "list", values: "dassl ida" }),
      "@tolerance": row({ mode: "list", values: "1e-6 1e-4" }),
      "@stop": row({ mode: "model" }),
    });
    expect(sweep).toEqual([{ name: "@method", mode: "list", values: ["dassl", "ida"] }, { name: "@tolerance", mode: "list", values: [1e-6, 1e-4] }]);
    expect(() => sweepOf({ "@method": row({ mode: "list", values: "nope" }) })).toThrow(/nope/);
    expect(() => sweepOf({ "@method": row({ mode: "list", values: "" }) })).toThrow(/Solver/);
  });

  it("open a study's run inside the study", () => {
    expect(studyRunPath("st-1", { id: "sim-2" })).toBe("/studies/st-1/runs/sim-2");
  });

  it("finds the save a version number names and what a comparison shows (Q7b)", () => {
    const revisions = [
      { id: 9, path: "A.mo", saved_by: "ana", saved_at: "2026-10-25T10:00:00Z", bytes: 10 },
      { id: 4, path: "A.mo", saved_by: "bia", saved_at: "2026-10-24T10:00:00Z", bytes: 9 },
    ];
    expect([3, 2, 1, 4, 0].map((number) => revisionOf(revisions, number))).toEqual([0, 9, 4, null, null]);
    expect(shownVersion("?version=2")).toBe(2);
    expect(shownVersion("?version=x")).toBeNull();
    expect(comparedRuns("?versions=1,2&runs=a,b")).toEqual(["a", "b"]);
    expect(seriesFacts([null, 3, 1, 2])).toEqual({ final: 2, min: 1, max: 3 });
    expect(seriesFacts([null])).toEqual({ final: null, min: null, max: null });
    const port = (name: string) => ({ port: name, types: [], type: "Real", label: name, description: "", unit: "", required: true });
    const rows = contractRows([
      { inputs: [port("u")], outputs: [port("y")], parameters: [{ name: "k", default: 2 }] },
      { inputs: [port("u"), port("b")], outputs: [port("y")], parameters: [{ name: "k", default: 3 }] },
    ] as never);
    expect(rows.map((row) => `${row.name}:${row.values.join("|")}:${row.changed}`)).toEqual(["u:Real|Real:false", "b:–|Real:true", "y:Real|Real:false", "k:2|3:true"]);
  });
});
