import { describe, expect, it } from "vitest";
import { resultLabel, resultTone, STATUS, STATUS_ORDER, statusLabel, statusTone, suiteLabel } from "./status";

describe("loop status", () => {
  it("names every status the API serves, worst first", () => {
    expect(STATUS_ORDER).toEqual(Object.keys(STATUS));
    expect(statusLabel("no_data")).toBe("Data not usable");
    expect(statusTone("critical")).toBe("problem");
    expect(statusTone("unknown")).toBe("info");
    expect(statusLabel("incomplete")).toBe("Incomplete record");
  });
});

describe("suite status words", () => {
  it("words ok, warning, alarm and unknown as the suite does", () => {
    expect(["ok", "warning", "alarm", "unknown"].map(suiteLabel)).toEqual(["OK", "Warning", "Critical", "Unknown"]);
    expect(suiteLabel("anything else")).toBe("Unknown");
  });
  it("words method results in the same vocabulary", () => {
    expect([resultLabel("ok"), resultLabel("warning"), resultLabel("bad")]).toEqual(["OK", "Warning", "Critical"]);
    expect(resultTone("bad")).toBe("problem");
  });
});
