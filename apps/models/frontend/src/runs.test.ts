import { describe, expect, it } from "vitest";
import { runPath } from "./paths";
import { runDownload } from "./RunsPage";
import type { Run } from "./types";

function run(kind: Run["kind"], extra: Partial<Run> = {}): Run {
  return { id: `${kind}-1`, project_id: "p2", project_name: "Drum", kind, status: "done", options: {}, model: "M", ...extra } as unknown as Run;
}

describe("the runs table", () => {
  it("offers the results of a simulation and the file of an export, once finished", () => {
    expect(runDownload(run("simulate"))?.url).toMatch(/\/api\/runs\/simulate-1\/results\.csv$/);
    expect(runDownload(run("fmu"))?.url).toMatch(/\/api\/runs\/fmu-1\/fmu$/);
    expect(runDownload(run("simulate", { status: "running" }))).toBeNull();
    expect(runDownload(run("fmu", { status: "failed" }))).toBeNull();
  });
});

describe("where a run's page is", () => {
  it("every run under /runs", () => {
    expect(runPath(run("simulate"))).toBe("/runs/simulate-1");
    expect(runPath(run("fmu"))).toBe("/runs/fmu-1");
  });
});
