import { describe, expect, it } from "vitest";
import { analogLayout, limitsFromSteps, normalRange } from "./analog";
import { setpointFor, sparkBand } from "./CardView";
import type { FieldConfig, ValueRow } from "./types";

const isa: FieldConfig = { thresholds: { steps: [{ level: "alarm" }, { value: 10, level: "warning" }, { value: 20, level: "ok" }, { value: 80, level: "warning" }, { value: 90, level: "alarm" }] } };

describe("ISA-101 analog indicator", () => {
  it("reads LL, L, H and HH from the thresholds' normal step", () => {
    expect(limitsFromSteps(isa)).toEqual({ ll: 10, l: 20, h: 80, hh: 90 });
    const above: FieldConfig = { thresholds: { steps: [{ level: "ok" }, { value: 70, level: "warning" }, { value: 85, level: "alarm" }] } };
    expect(limitsFromSteps(above)).toEqual({ h: 70, hh: 85 });
    const colours: FieldConfig = { thresholds: { steps: [{ level: "ok" }, { value: 50, level: "none", color: "blue" }] } };
    expect(limitsFromSteps(colours)).toEqual({ h: null, hh: null });
    expect(limitsFromSteps({})).toEqual({});
  });

  it("takes the field's normal range, else L to H", () => {
    expect(normalRange(isa, limitsFromSteps(isa))).toEqual({ low: 20, high: 80 });
    expect(normalRange({ ...isa, normal_low: 40, normal_high: 60 }, limitsFromSteps(isa))).toEqual({ low: 40, high: 60 });
    expect(normalRange({}, {})).toBeNull();
  });

  it("places the band, ticks, setpoint and a clamped pointer along the bar", () => {
    const layout = analogLayout({ value: 120, min: 0, max: 100, limits: { ll: 10, l: 20, h: 80, hh: 90 }, normal: { low: 40, high: 60 }, sp: 50, state: "alarm" });
    expect(layout.band).toEqual({ from: 0.4, to: 0.6 });
    expect(layout.ticks.map((tick) => [tick.name, tick.at])).toEqual([["ll", 0.1], ["l", 0.2], ["h", 0.8], ["hh", 0.9]]);
    expect(layout.sp).toBe(0.5);
    expect(layout.pointer).toEqual({ at: 1, over: true, under: false });
    expect(analogLayout({ value: null, min: 0, max: 1, limits: {}, state: "unknown" }).pointer).toBeNull();
  });

  it("marks a PV with the SP of the same asset", () => {
    const row = (role: string, asset: string, value: number) => ({ role, asset, value, label: role, signal: null, unit: "", kind: "number", error: null, at: null, agg: "last", state: "ok" }) as ValueRow;
    const rows = [row("pv", "FIC-1", 48), row("sp", "FIC-1", 50), row("pv", "FIC-2", 3), row("sp", "FIC-3", 7)];
    expect(setpointFor(rows, rows[0])).toBe(50);
    expect(setpointFor(rows, rows[2])).toBeNull();
    expect(setpointFor(rows, rows[1])).toBeNull();
  });

  it("shades a sparkline's normal range, an open end just past the line", () => {
    expect(sparkBand({ low: 20, high: 80 }, 0, 100)).toEqual([20, 80]);
    expect(sparkBand({ low: null, high: 80 }, 50, 90)).toEqual([48, 80]);
    expect(sparkBand(null, 0, 1)).toBeNull();
  });
});
