import { describe, expect, it } from "vitest";
import { chosenLibrary } from "./BlocksPage";
import { studyParameters, sweepOf } from "./StudyForm";
import type { Diagram } from "./types";
import { variantText } from "./ui";

const row = (change: Record<string, string>) => ({ mode: "model", value: "", start: "", stop: "", count: "5", values: "", ...change }) as Parameters<typeof sweepOf>[0][string];

describe("a study's parameters", () => {
  it("become fixed values and the sweep the API takes", () => {
    const { sweep, overrides } = sweepOf({
      "controller.k": row({ mode: "range", start: "1", stop: "4", count: "4" }),
      "controller.Ti": row({ mode: "list", values: "30, 60 90" }),
      "tank.area": row({ mode: "fixed", value: "2.5" }),
      "valve.open": row({ mode: "fixed", value: "true" }),
      "tank.height": row({ mode: "model" }),
    });
    expect(sweep).toEqual([
      { name: "controller.k", mode: "range", start: 1, stop: 4, count: 4 },
      { name: "controller.Ti", mode: "list", values: [30, 60, 90] },
    ]);
    expect(overrides).toEqual({ "tank.area": 2.5, "valve.open": true });
  });

  it("become the values an optimization changes, within their bounds", () => {
    const { sweep, variables, overrides } = sweepOf({
      "controller.k": row({ mode: "optimize", start: "2", stop: "8", value: "4" }),
      "tank.A": row({ mode: "optimize", start: "1", stop: "3" }),
      "tank.Cv": row({ mode: "fixed", value: "0.05" }),
    });
    expect(sweep).toEqual([]);
    expect(overrides).toEqual({ "tank.Cv": 0.05 });
    expect(variables).toEqual([{ name: "controller.k", start: 4, min: 2, max: 8 }, { name: "tank.A", start: 2, min: 1, max: 3 }]);
    expect(() => sweepOf({ k: row({ mode: "optimize", start: "3", stop: "1" }) })).toThrow(/k:/);
    expect(() => sweepOf({ k: row({ mode: "optimize", start: "1", stop: "3", value: "9" }) })).toThrow(/k:/);
  });

  it("refuse what is not a number", () => {
    expect(() => sweepOf({ k: row({ mode: "list", values: "1 two" }) })).toThrow(/k:/);
    expect(() => sweepOf({ k: row({ mode: "range", start: "", stop: "2" }) })).toThrow(/k:/);
  });

  it("include the parameters of the model's components", () => {
    const diagram = {
      parameters: [{ name: "setpoint", value: "1", default: null }],
      components: [
        { name: "controller", connector: false, values: { k: "2" }, parameters: [{ name: "k", value: null, default: "1" }] },
        { name: "u", connector: true, values: {}, parameters: [{ name: "nominal", value: null, default: "0" }] },
      ],
    } as unknown as Diagram;
    expect(studyParameters(diagram).map((item) => [item.path, item.value])).toEqual([["setpoint", "1"], ["controller.k", "2"]]);
  });
});

describe("a variant", () => {
  it("reads as the short names and values", () => {
    expect(variantText({ "controller.k": 2, "controller.Ti": 30.000000001, on: true })).toBe("k=2, Ti=30, on=true");
  });
});

describe("the library a Blocks page opens on", () => {
  it("is the one in the address, else the first", () => {
    const libraries = [{ library: "a" }, { library: "b" }];
    expect(chosenLibrary(libraries, "?library=b")).toBe("b");
    expect(chosenLibrary(libraries, "?library=zzz")).toBe("a");
    expect(chosenLibrary([], "")).toBe("");
  });
});
