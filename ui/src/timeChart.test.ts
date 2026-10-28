import { describe, expect, it } from "vitest";
import { BRAND_COLORS } from "./brandTheme.js";
import { choosePeriod, isoOf, localOf, periodRange, qualityBands, sharedUnit, timeChartLayout, timeFigure, timeHover, timePlotConfig, windowLabel, windowSeconds } from "./timeChart.js";

describe("time chart", () => {
  it("reads periods", () => {
    expect(windowSeconds("2h")).toBe(7200);
    expect(windowSeconds("7d")).toBe(604800);
    expect(Number.isNaN(windowSeconds("x"))).toBe(true);
    expect(windowLabel("1h")).toBe("1 hour");
    expect(windowLabel("15m")).toBe("15 minutes");
  });
  it("lays out a date axis with one hover box", () => {
    const layout = timeChartLayout({ xaxis: { gridcolor: "#eee" } }, { start: "a", end: "b", rightAxis: true });
    expect(layout.xaxis).toEqual({ gridcolor: "#eee", type: "date", range: ["a", "b"] });
    expect(layout.hovermode).toBe("x unified");
    expect(layout.margin.r).toBe(56);
    expect(timeChartLayout({}, { legend: false }).showlegend).toBe(false);
  });
  it("writes the hover and hides the buttons when asked", () => {
    expect(timeHover("FIC-101", "m³/h")).toBe("%{y:.4~g} m³/h<extra>FIC-101</extra>");
    expect(timePlotConfig({ modeBar: false }).displayModeBar).toBe(false);
    expect(timePlotConfig().modeBarButtonsToRemove).toContain("lasso2d");
  });
  it("shades the periods that were not good, up to the next change", () => {
    const bands = qualityBands([{ t: "a", quality: "good" }, { t: "b", quality: "uncertain" }, { t: "c", quality: "good" }, { t: "d", quality: "bad" }], "z");
    expect(bands).toEqual([{ from: "b", to: "c", quality: "uncertain" }, { from: "d", to: "z", quality: "bad" }]);
    expect(qualityBands(undefined, "z")).toEqual([]);
  });
  it("titles the y axis only with a unit every line shares", () => {
    expect(sharedUnit(["m³/h", "m³/h"])).toBe("m³/h");
    expect(sharedUnit(["m³/h", "°C"])).toBe("");
    expect(sharedUnit([undefined, ""])).toBe("");
  });
  it("turns periods into start and end", () => {
    const now = Date.parse("2026-10-23T12:00:00Z");
    const relative = periodRange({ window: "2h", from: "", to: "" }, now, 60_000);
    expect(relative).toEqual({ start: "2026-10-23T10:00:00.000Z", end: "2026-10-23T12:01:00.000Z", seconds: 7200 });
    const fixed = choosePeriod({ window: "1h", from: "", to: "" }, "fixed", now);
    expect(fixed.window).toBe("fixed");
    expect(periodRange(fixed).seconds).toBe(86400);
    expect(isoOf(localOf("2026-10-23T12:00:00.000Z"))).toBe("2026-10-23T12:00:00.000Z");
    expect(localOf("")).toBe("");
    expect(choosePeriod(fixed, "8h", now)).toEqual({ ...fixed, window: "8h" });
  });
  it("draws lines in the theme, on a solid background for the picture", () => {
    const lines = [{ name: "FT-1", t: ["a"], v: [1], unit: "m³/h" }, { name: "XV-1", t: ["a"], v: ["OPEN"], text: true }];
    const dark = timeFigure({ lines, bands: [{ from: "a", to: "b", quality: "bad" }], filename: "FT-1" }, "dark");
    expect(dark.layout.paper_bgcolor).toBe(BRAND_COLORS.dark.surface);
    expect(dark.data[0].line.color).toBe(BRAND_COLORS.dark.series[0]);
    expect(dark.data[1].line.shape).toBe("hv");
    expect(dark.layout.yaxis.title.text).toBe("");
    expect(dark.layout.yaxis.type).toBe("linear");
    expect(dark.layout.showlegend).toBe(true);
    expect(dark.layout.shapes).toHaveLength(1);
    expect(dark.config.toImageButtonOptions.filename).toBe("FT-1");
    const one = timeFigure({ lines: [lines[0]] }, "light");
    expect(one.layout.yaxis.title.text).toBe("m³/h");
    expect(one.layout.showlegend).toBe(false);
  });
});
