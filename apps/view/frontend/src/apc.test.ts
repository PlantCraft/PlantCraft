import { describe, expect, it } from "vitest";
import { apcScale, apcState, sparkPath } from "./apc";

describe("multivariable controller panel", () => {
  it("scales a variable's bar to its limits with a margin, widened to an outside value", () => {
    expect(apcScale({ lo: 0, hi: 100, value: 50, target: 60 })).toEqual({ min: -10, max: 110 });
    expect(apcScale({ lo: 0, hi: 100, value: 150, target: null })).toEqual({ min: -10, max: 150 });
    expect(apcScale({ lo: null, hi: 100, value: 50, target: null })).toBeNull();
    expect(apcScale({ lo: 5, hi: 5, value: 5, target: null })).toBeNull();
  });

  it("draws the horizon's line and breaks it at a gap", () => {
    expect(sparkPath([0, 10, null, 5], 30, 10, 0, 10)).toBe("M0.0 10.0L10.0 0.0M30.0 5.0");
    expect(sparkPath([], 30, 10, 0, 10)).toBe("");
  });

  it("names the state a row is in, out of service first", () => {
    expect(apcState({ at_limit: "hi", in_service: true })).toBe("At high limit");
    expect(apcState({ at_limit: "lo", in_service: null })).toBe("At low limit");
    expect(apcState({ at_limit: "hi", in_service: false })).toBe("Out of service");
    expect(apcState({ at_limit: null, in_service: true })).toBe("");
  });
});
