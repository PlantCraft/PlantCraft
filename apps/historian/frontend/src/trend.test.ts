import { describe, expect, it } from "vitest";
import { compareOffset, deviationAt, seriesCsv, shifted, stepFor } from "./PointTrend";

describe("point trend", () => {
  it("reads as recorded up to an hour by default, and up to a day when asked", () => {
    expect(stepFor(3600)).toBeUndefined();
    expect(stepFor(7200)).toBe(5);
    expect(stepFor(86_400, "recorded")).toBeUndefined();
    expect(stepFor(7 * 86_400, "recorded")).toBe(403);
    expect(stepFor(600, "averages")).toBe(1);
  });

  it("compares with the period before, a day or a week earlier", () => {
    expect(compareOffset("previous", 3600)).toBe(3600);
    expect(compareOffset("day", 3600)).toBe(86_400);
    expect(compareOffset("", 3600)).toBe(0);
    expect(shifted(["2026-10-24T10:00:00.000Z"], 86_400)).toEqual(["2026-10-25T10:00:00.000Z"]);
  });

  it("draws the deviation fixed or as a share of the value", () => {
    expect(deviationAt({ deviation: 0.5, deviation_percent: null }, 80)).toBe(0.5);
    expect(deviationAt({ deviation: 0, deviation_percent: 0.1 }, -50)).toBeCloseTo(0.05);
  });

  it("writes the series and its band as CSV", () => {
    const csv = seriesCsv({ signal: "p:A", kind: "number", t: ["2026-10-24T10:00:00Z", "2026-10-24T10:01:00Z"], v: [1.5, null], low: [1, null], high: [2, null] }, "A");
    expect(csv).toBe("time,A,low,high\n2026-10-24T10:00:00Z,1.5,1,2\n2026-10-24T10:01:00Z,,,\n");
  });
});
