import { configureTimeZone } from "@plantcraft/ui";
import { afterEach, describe, expect, it } from "vitest";
import { eventShapes, opBins, plotTime } from "./chart";
import type { CheckResult } from "./types";

const results: CheckResult[] = [
  { check: "sq_spikes", name: "Spikes", status: "warning", score: 28, message: "", events: [{ start_time: "2026-10-18T13:00:00+00:00", end_time: "2026-10-18T13:00:00+00:00", label: "Spike" }] },
  { check: "sq_frozen", name: "Frozen", status: "bad", score: 60, message: "", events: [{ start_time: "2026-10-18T20:00:00+00:00", end_time: "2026-10-19T02:00:00+00:00", label: "Frozen" }] },
  { check: "sq_noise", name: "Noise", status: "ok", score: 0, message: "", events: [{ start_time: "2026-10-18T14:00:00+00:00", end_time: "2026-10-18T15:00:00+00:00", label: "x" }] },
];

describe("chart", () => {
  it("writes times as naive UTC for Plotly", () => {
    expect(plotTime("2026-10-18T12:00:10+00:00")).toBe("2026-10-18 12:00:10.000");
    expect(plotTime("2026-10-18T09:00:00-03:00")).toBe("2026-10-18 12:00:00.000");
  });
  afterEach(() => configureTimeZone({ plant: null, mode: null }));
  it("writes them on the plant's wall clock when the plant is not on UTC", () => {
    configureTimeZone({ plant: "America/Sao_Paulo", mode: "plant" });
    expect(plotTime("2026-10-18T12:00:10Z")).toBe("2026-10-18 09:00:10.000");
  });
  it("shades events of failing checks only, widening instants", () => {
    const shapes = eventShapes(results, (check) => (check === "sq_spikes" ? "#a" : "#b"), "2026-10-18T12:00:00Z", "2026-10-19T12:00:00Z");
    expect(shapes).toHaveLength(2);
    const [spike, frozen] = shapes;
    expect(spike.fillcolor).toBe("#a");
    expect(spike.yref).toBe("paper");
    // 0.4% of 24 h = 345.6 s, centred on the instant.
    expect(spike.x0).toBe("2026-10-18 12:57:07.200");
    expect(spike.x1).toBe("2026-10-18 13:02:52.800");
    expect(frozen.x0).toBe("2026-10-18 20:00:00.000");
    expect(frozen.x1).toBe("2026-10-19 02:00:00.000");
  });
});

describe("opBins", () => {
  it("gives each 5% band of the controller output its share of the window", () => {
    const bins = opBins([0, 2, 99, 100, 101, -3, null, undefined, Number.NaN, 50]);
    expect(bins.x).toHaveLength(20);
    expect(bins.x[0]).toBe(2.5);
    // 7 finite values: 0, 2 and -3 in the first band; 99, 100 and 101 in the last; 50 alone.
    expect(bins.y[0]).toBeCloseTo((100 * 3) / 7);
    expect(bins.y[19]).toBeCloseTo((100 * 3) / 7);
    expect(bins.y[10]).toBeCloseTo(100 / 7);
    expect(bins.y.reduce((a, b) => a + b, 0)).toBeCloseTo(100);
  });

  it("is all zero without values", () => {
    expect(opBins([null, undefined]).y.every((share) => share === 0)).toBe(true);
  });
});
