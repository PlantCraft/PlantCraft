import { describe, expect, it } from "vitest";
import { cadenceText, countsText, versionMarks } from "./ExecutionGroups";
import type { ExecutionGroup } from "./types";

const group = (fields: Partial<ExecutionGroup>): ExecutionGroup => ({
  id: "s", name: "S", kind: "protocol", algorithm: null, subject_kind: "asset", subjects: 0,
  counts: { ok: 0, warning: 0, alarm: 0, unknown: 0 }, enabled: true, priority: 50, owner: "",
  last_run_at: null, next_run_at: null, interval_minutes: null, cadence: null, path: "/executions/s", schedule_path: null, ...fields,
});

describe("executions by schedule", () => {
  it("says how the last execution ended in one quiet line", () => {
    expect(countsText({ ok: 3, warning: 1, alarm: 2, unknown: 0 })).toBe("3 OK · 1 warning · 2 critical");
    expect(countsText({ ok: 0, warning: 0, alarm: 0, unknown: 0 })).toBe("Nothing ran yet");
  });

  it("says how often a schedule runs as people say it", () => {
    expect(cadenceText(group({ cadence: "interval", interval_minutes: 15 }))).toBe("Every 15 min");
    expect(cadenceText(group({ cadence: "interval", interval_minutes: 120 }))).toBe("Every 2 h");
    expect(cadenceText(group({ kind: "manual" }))).toBe("When a person asks");
  });

  it("marks where each version started", () => {
    expect(versionMarks({ signal: "x", t: ["2026-10-24T00:00:00Z", "2026-10-25T00:00:00Z"], v: ["v1", "v2"] })).toEqual([
      { t: "2026-10-24T00:00:00Z", label: "v1" },
      { t: "2026-10-25T00:00:00Z", label: "v2" },
    ]);
    expect(versionMarks(undefined)).toEqual([]);
  });
});
