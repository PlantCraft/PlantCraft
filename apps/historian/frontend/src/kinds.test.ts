import { describe, expect, it } from "vitest";
import { kindLabel, plotted } from "./kinds";

describe("point kinds on a trend", () => {
  it("draws on/off as 1 and 0, and times and structured values as labels", () => {
    expect(plotted("boolean", [true, false, null])).toEqual({ v: [1, 0, null], text: false });
    expect(plotted("integer", [3, null])).toEqual({ v: [3, null], text: false });
    expect(plotted("instant", ["2026-10-19T00:00:00+00:00"]).text).toBe(true);
    expect(plotted("structured", [{ a: 1 }])).toEqual({ v: ['{"a":1}'], text: true });
    expect(kindLabel("boolean")).toBe("on/off");
  });
});
