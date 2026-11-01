import { describe, expect, it } from "vitest";
import { BUILD_ORDER, BUILD_WORDS, buildText } from "./Build";
import type { Build, ModelBuild } from "./types";

const build = (version: number | null): Build => ({
  id: "fmu-1", status: "done", created_at: "2026-11-01T12:00:00Z", created_by: "engineer", finished_at: "2026-11-01T12:00:20Z",
  seconds: 20, summary: "", current: true, version, fmi_version: "2.0", fmu_type: "cs", size: 2048, sha256: "ab", variables: 12,
  errors: 0, warnings: 0, messages: [],
});

describe("a model's compiled version", () => {
  it("says the version it was compiled from", () => {
    const compiled: ModelBuild = { state: "compiled", compiled: build(4), builds: [build(4)] };
    expect(buildText(compiled)).toBe("Compiled · version 4");
    expect(buildText({ state: "out_of_date", compiled: build(3), builds: [] })).toBe("Out of date");
    expect(buildText({ state: "not_compiled", compiled: null, builds: [] })).toBe("Not compiled");
  });
  it("has words for every state", () => {
    for (const state of BUILD_ORDER) expect(BUILD_WORDS[state].label).toBeTruthy();
  });
});
