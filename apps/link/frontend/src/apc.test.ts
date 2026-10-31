import { describe, expect, it } from "vitest";
import { apcPath, apcState, APC_WINDOWS } from "./ApcPage";

describe("multivariable controllers", () => {
  it("links a controller by its escaped id", () => {
    expect(apcPath()).toBe("/apc");
    expect(apcPath("unit 1/apc")).toBe("/apc/unit%201%2Fapc");
  });
  it("reads an unmeasured controller as unknown", () => {
    expect(apcState({ summary: { state: null } as never })).toBe("unknown");
    expect(apcState({ summary: { state: "warning" } as never })).toBe("warning");
  });
  it("offers a day, a week and a month", () => {
    expect(APC_WINDOWS).toEqual([1, 7, 31]);
  });
});
