import { describe, expect, it } from "vitest";
import type { ExplorePick } from "@plantcraft/ui";
import { EMPTY_RULE, inputLabel, pythonDiagram, pythonForm, pythonFromSimple, relativeSignal, scheduleRule, valueCondition, valueOfPick } from "./rules";
import { scopeOf } from "./RuleEditor";

const step = (id: string, name = id) => ({ id, name });

describe("a new rule", () => {
  it("starts as one Simple condition on a value, telling the responsible", () => {
    const rule = EMPTY_RULE();
    expect(rule.editor).toBe("simple");
    expect(rule.simple?.conditions).toHaveLength(1);
    expect(rule.simple?.conditions[0].input).toBe("value");
    expect(rule.notify.recipients).toEqual(["owner"]);
    expect(scopeOf(rule.where)).toBe("none");
  });
  it("for a Link schedule covers its execution's assets, critical in it", () => {
    const rule = scheduleRule("unit-100-health", "Unit 100 health");
    expect(rule.name).toBe("Unit 100 health: asset critical");
    expect(rule.where.executions).toEqual(["linkcraft:unit-100-health"]);
    expect(scopeOf(rule.where)).toBe("executions");
    const [condition] = rule.simple!.conditions;
    expect(condition.event?.kinds).toEqual(["linkcraft.status.changed"]);
    expect(condition.event?.severities).toEqual(["critical"]);
  });
});

describe("a value picked in the Explorer", () => {
  const output: ExplorePick = { type: "output", id: "app-linkcraft:FIC-1001.health.score", name: "Health", unit: "/100", app: "linkcraft", relativeTo: "FIC-1001", path: [step("U-100"), step("FIC-1001")] };
  const signal: ExplorePick = { type: "signal", id: "plantcraft:FIC-1001.PV", name: "PV", unit: "m3/h", role: "pv", relativeTo: "FIC-1001", path: [step("FIC-1001")] };
  it("is read on each asset of the rule: its role, or the app's series with the asset left open", () => {
    expect(valueOfPick(signal, true)).toEqual({ signal: "", role: "pv", name: "PV", unit: "m3/h" });
    expect(valueOfPick(output, true).signal).toBe("app-linkcraft:{asset}.health.score");
    expect(relativeSignal("app-x:A.b", "B")).toBeNull();
  });
  it("or as the one signal it is", () => {
    expect(valueOfPick(signal, false)).toEqual({ signal: "plantcraft:FIC-1001.PV", role: "", name: "FIC-1001 › PV", unit: "m3/h" });
  });
});

describe("the Python form", () => {
  it("is values wired into one Python block and the alarm, and reads back", () => {
    const form = pythonFromSimple({ conditions: [valueCondition({ signal: "", role: "pv", name: "Flow PV", unit: "" })], combine: "and", clear_after_seconds: 60 });
    expect(form.inputs.map((item) => item.label)).toEqual(["flow_pv"]);
    const diagram = pythonDiagram(form);
    expect(diagram.nodes.map((node) => node.block)).toEqual(["alarm.value", "alarm.python", "alarm.raise"]);
    expect(pythonForm(diagram)).toEqual({ ...form, inputs: [{ label: "flow_pv", value: { signal: "", role: "pv", name: "flow_pv", unit: "" } }] });
    expect(pythonForm({ nodes: [...diagram.nodes, { id: "x", block: "alarm.not", x: 0, y: 0 }], edges: diagram.edges })).toBeNull();
  });
  it("names inputs as Python can read them", () => {
    expect(inputLabel("2nd flow", [])).toBe("v_2nd_flow");
    expect(inputLabel("pv", ["pv"])).toBe("pv_2");
  });
});
