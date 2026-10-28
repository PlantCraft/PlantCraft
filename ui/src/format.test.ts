import { describe, expect, it } from "vitest";
import { formatReading } from "./format";

describe("readings", () => {
  it("keeps 4 significant digits and puts the unit after", () => {
    expect(formatReading(12.3456, "bar")).toBe("12.35 bar");
    expect(formatReading(0.000123456)).toBe("0.0001235");
    expect(formatReading(1500000, "kg/h")).toBe("1500000 kg/h");
    expect(formatReading(null, "bar")).toBe("–");
    expect(formatReading(Number.NaN)).toBe("–");
  });
});
