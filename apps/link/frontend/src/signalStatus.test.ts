import { describe, expect, it } from "vitest";
import { STATUS_TONES } from "@plantcraft/ui";
import { SIGNAL_ORDER, SIGNAL_STATUS, runLabel, signalCaption, signalLabel, signalStatus, tagOf } from "./signalStatus";

describe("signal verdicts", () => {
  it("read a missing verdict as not checked", () => {
    expect(signalStatus(null)).toBe("unchecked");
    expect(signalLabel(undefined)).toBe("Not checked");
    expect(signalLabel("suspect")).toBe("Suspect");
  });
  it("colour every verdict the way its pill says", () => {
    for (const key of SIGNAL_ORDER) expect(STATUS_TONES[key]).toBe(SIGNAL_STATUS[key].tone);
  });
  it("word the algorithm's runs", () => {
    expect(runLabel("ok")).toBe("Finished");
    expect(runLabel("other")).toBe("other");
  });
  it("name a signal by its tag and what it measures", () => {
    expect(tagOf({ id: "plantcraft:CPM.Loops.FIC-1214.OP", source: "plantcraft" })).toBe("CPM.Loops.FIC-1214.OP");
    expect(tagOf({ id: "FT-101", source: "" })).toBe("FT-101");
    expect(signalCaption({ name: "OP", description: "", assets: ["FIC-1214"] })).toBe("OP · FIC-1214");
    expect(signalCaption({ name: "OP", description: "FIC-1214 controller output", assets: ["FIC-1214"] })).toBe("FIC-1214 controller output");
  });
});
