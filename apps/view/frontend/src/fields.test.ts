import { describe, expect, it } from "vitest";
import { colorOf, effective, mappedText, optionsOf, stateOf, stepOf, stepValues, valueColor } from "./fields";
import { pickValues, expandValues, staticOptions } from "./variables";
import type { Thresholds, Variable } from "./types";

const steps: Thresholds = { steps: [{ level: "ok" }, { value: 80, level: "warning" }, { value: 90, level: "alarm" }] };

describe("thresholds and mappings (as fields.py)", () => {
  it("finds the step of a value, absolute or in percent of the range", () => {
    expect(stepOf(steps, 50)?.level).toBe("ok");
    expect(stepOf(steps, 85)?.level).toBe("warning");
    expect(stepOf(steps, 90)?.level).toBe("alarm");
    expect(stepOf(steps, null)).toBeNull();
    const percent: Thresholds = { mode: "percentage", steps: steps.steps };
    expect(stepOf(percent, 17, 0, 20)?.level).toBe("warning");
    expect(stepOf(percent, 17)).toBeNull();
    expect(stepValues({ thresholds: percent, min: 0, max: 200 }).map((item) => item.value)).toEqual([160, 180]);
  });
  it("states and colours come from mappings first, then thresholds", () => {
    const config = { thresholds: steps, mappings: [{ type: "value" as const, value: "1", text: "Open", color: "green", level: "ok" as const }, { type: "range" as const, low: 95, high: 100, text: "Trip", level: "alarm" as const }] };
    expect(mappedText(config, 1)).toBe("Open");
    expect(stateOf(config, 97)).toBe("alarm");
    expect(stateOf(config, 85)).toBe("warning");
    expect(valueColor(config, 1, 0, undefined, "light")).toBe(colorOf("green", "light"));
    expect(valueColor({ color_mode: "fixed", color: "#123456" }, 5)).toBe("#123456");
  });
  it("overrides change the options of the signals they match", () => {
    const card = { field: { unit: "m3/h", decimals: 1 }, overrides: [{ match: { by: "role" as const, value: "sp" }, field: { dash: "dash" as const, decimals: null } }, { match: { by: "signal" as const, value: "fic-*" }, field: { unit: "%" } }] };
    expect(effective(card, { role: "sp", signal: "x" })).toEqual({ unit: "m3/h", decimals: 1, dash: "dash" });
    expect(effective(card, { role: "pv", signal: "FIC-101.PV" }).unit).toBe("%");
    expect(optionsOf({ options: { legend: "table" } }).tooltip).toBe("all");
  });
});

describe("variables on the page", () => {
  const options = [{ value: "a", text: "A", group: null, description: "" }, { value: "b", text: "B", group: null, description: "" }];
  const loop: Variable = { name: "loop", type: "asset", asset_kind: "loop" };
  it("keeps what the address asks for when offered, else the default, else the first", () => {
    expect(pickValues(loop, options, ["b"])).toEqual(["b"]);
    expect(pickValues(loop, options, ["zzz"])).toEqual(["a"]);
    expect(pickValues({ ...loop, default: "b" }, options, undefined)).toEqual(["b"]);
    expect(pickValues(loop, options, ["a", "b"])).toEqual(["a"]);
    expect(pickValues({ ...loop, multi: true }, options, ["a", "b"])).toEqual(["a", "b"]);
    expect(pickValues(loop, options, ["$__all"])).toEqual(["a"]);
    expect(pickValues({ ...loop, include_all: true }, options, ["$__all"])).toEqual(["$__all"]);
    expect(pickValues(loop, [], undefined)).toEqual([]);
  });
  it("All stands for every option, with names", () => {
    expect(expandValues(options, ["$__all"])).toEqual({ values: ["a", "b"], texts: ["A", "B"] });
    expect(expandValues(options, ["b"])).toEqual({ values: ["b"], texts: ["B"] });
  });
  it("lists and time spans need no read", () => {
    expect(staticOptions({ name: "p", type: "interval", options: ["8h"] })).toEqual([{ value: "8h", text: "8 hours", group: null, description: "" }]);
    expect(staticOptions(loop)).toBeNull();
  });
});
