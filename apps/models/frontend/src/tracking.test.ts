import { describe, expect, it } from "vitest";
import { bodyOf, limitsOf, pairs } from "./TrackingPage";
import type { Tracking } from "./types";

describe("tracking form", () => {
  it("reads variable = signal lines", () => {
    expect(pairs("tank.level = plant:LT-101\n\nnot a pair\n x= \nqin=plant:FT=1")).toEqual({ "tank.level": "plant:LT-101", qin: "plant:FT=1" });
  });
  it("takes positive limits only", () => {
    expect(limitsOf("tank.level = 0.05")).toEqual({ "tank.level": 0.05 });
    expect(() => limitsOf("tank.level = -1")).toThrow();
  });
  it("keeps the project, model and config when paused", () => {
    const tracking = { id: "a", project_id: "p", model: "M", name: "n", enabled: true, config: { inputs: {}, compare: { x: "s" }, window_minutes: 60, every_minutes: 15, step_seconds: null, intervals: 500, overrides: {}, limits: {} } } as unknown as Tracking;
    expect(bodyOf(tracking, { enabled: false })).toMatchObject({ project_id: "p", model: "M", enabled: false, compare: { x: "s" } });
  });
});
