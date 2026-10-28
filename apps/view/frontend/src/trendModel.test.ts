import { describe, expect, it } from "vitest";
import { chipText, EMPTY_VIEW, lineName, readable, stateRuns, subplotDomains, trendCsv, trendTraces, viewFromAddress } from "./trendModel";
import type { TrendData } from "./types";

const line = (label: string, signal: string, t: string[], v: Array<number | null>) => ({ label, signal, unit: "m3/h", kind: "number", error: null, t, v });

describe("trends", () => {
  it("stacks subplots top to bottom without overlap", () => {
    expect(subplotDomains(1)).toEqual([[0, 1]]);
    const three = subplotDomains(3);
    expect(three[0][1]).toBe(1);
    expect(three[2][0]).toBeCloseTo(0);
    expect(three[1][1]).toBeLessThan(three[0][0]);
  });

  it("asks only for plots that have lines", () => {
    expect(readable(EMPTY_VIEW).plots).toEqual([]);
  });

  it("writes one column per signal, once, on the union of times", () => {
    const data: TrendData = {
      plots: [
        { title: "", lines: [line("Flow", "a", ["t1", "t2"], [1, 2])] },
        { title: "", lines: [line("Flow", "a", ["t1", "t2"], [1, 2]), line("=Level", "b", ["t2", "t3"], [5, null])] },
      ],
      range: { start: "t1", end: "t3", step: 60, shifted: false }, read_at: "2026-10-21T10:00:00Z",
    };
    expect(trendCsv(data).split("\r\n")).toEqual(["time (UTC),Flow (m3/h),'=Level (m3/h)", "t1,1,", "t2,2,5", "t3,,", ""]);
  });

  it("names a line by its summary and keeps a signal's mean and last apart", () => {
    expect(lineName({ label: "Flow", unit: "m3/h", agg: "mean" })).toBe("Flow (m3/h)");
    expect(lineName({ label: "Flow", unit: "", agg: "last" })).toBe("Flow · last");
    const data: TrendData = {
      plots: [{ title: "", lines: [line("Flow", "a", ["t1"], [1]), { ...line("Flow", "a", ["t1"], [3]), agg: "last" }] }],
      range: { start: "t1", end: "t1", step: 60, shifted: false }, read_at: "2026-10-21T10:00:00Z",
    };
    expect(trendCsv(data).split("\r\n")[0]).toBe("time (UTC),Flow (m3/h),Flow · last (m3/h)");
  });

  it("draws each line in its style, on a right axis when asked", () => {
    const right = { ...line("Level", "b", ["t1"], [5]), unit: "%", style: { mode: "markers" as const, shape: "hv" as const, color: "#ff0000", width: 3, dash: "dot" as const, marker_size: 9, axis: "right" as const } };
    const data: TrendData = {
      plots: [{ title: "A", lines: [line("Flow", "a", ["t1"], [1])] }, { title: "B", lines: [line("Flow", "a", ["t1"], [1]), right] }],
      range: { start: "t1", end: "t1", step: 60, shifted: false }, read_at: "2026-10-21T10:00:00Z",
    };
    const { traces, axes } = trendTraces(data);
    expect(traces.map((trace) => (trace as { yaxis: string }).yaxis)).toEqual(["y", "y2", "y4"]);
    const drawn = traces[2] as { mode: string; marker: { size: number; color: string }; line: { shape: string; dash: string } };
    expect(drawn.mode).toBe("markers");
    expect(drawn.marker).toEqual({ size: 9, color: "#ff0000" });
    expect(drawn.line.shape).toBe("hv");
    expect(axes.yaxis4).toMatchObject({ overlaying: "y2", side: "right", title: { text: "%" } });
    expect(Object.keys(axes).sort()).toEqual(["yaxis", "yaxis2", "yaxis4"]);
  });

  it("names a unit on an axis only when every line on it shares it", () => {
    const level = { ...line("Level", "b", ["t1"], [5]), unit: "%" };
    const data: TrendData = {
      plots: [{ title: "", lines: [line("Flow", "a", ["t1"], [1]), line("Flow 2", "c", ["t1"], [2])] }, { title: "Mixed", lines: [line("Flow", "a", ["t1"], [1]), level] }],
      range: { start: "t1", end: "t1", step: 60, shifted: false }, read_at: "2026-10-21T10:00:00Z",
    };
    const { axes } = trendTraces(data);
    expect(axes.yaxis).toMatchObject({ title: { text: "m3/h" } });
    expect(axes.yaxis2).toMatchObject({ title: { text: "Mixed" } });
  });

  it("names a line's own interval and summary on its chip", () => {
    expect(chipText({ signal_id: "fake:FIC-101.PV", label: "PV", step_seconds: 60 })).toBe("PV · 1 minute");
    expect(chipText({ signal_id: "fake:FIC-101.SP", step_seconds: 3600, agg: "max" })).toBe("fake:FIC-101.SP · 1 hour · max");
    expect(chipText({ signal_id: "fake:FIC-101.OP", label: "OP" })).toBe("OP");
  });

  it("keeps a signal read at two intervals as two CSV columns", () => {
    const data: TrendData = { plots: [{ title: "", lines: [{ ...line("PV", "s:PV", ["2026-10-01T00:00:00Z"], [1]), step: 60 }, { ...line("PV hourly", "s:PV", ["2026-10-01T00:00:00Z"], [2]), step: 3600 }] }], range: { start: "", end: "", step: 60, shifted: false }, read_at: "" };
    expect(trendCsv(data).split("\r\n")[0]).toBe("time (UTC),PV (m3/h),PV hourly (m3/h)");
  });
});

describe("text signals in a trend", () => {
  it("are runs of one state, each up to the next", () => {
    const t = ["2026-10-23T10:00:00Z", "2026-10-23T10:01:00Z", "2026-10-23T10:02:00Z", "2026-10-23T10:03:00Z", "2026-10-23T10:04:00Z"];
    expect(stateRuns(t, ["AUTO", "AUTO", "MAN", null, "AUTO"])).toEqual([
      { state: "AUTO", start: t[0], end: t[2] },
      { state: "MAN", start: t[2], end: t[3] },
      { state: "AUTO", start: t[4], end: t[4] },
    ]);
  });

  it("draw as a band of states under the plot's lines", () => {
    const line = (kind: string, v: Array<number | string | null>) => ({ label: kind, signal: kind, unit: "", kind, error: null, t: ["2026-10-23T10:00:00Z", "2026-10-23T10:01:00Z"], v: v as Array<number | null> });
    const data = { plots: [{ title: "", lines: [line("number", [1, 2]), line("text", ["AUTO", "MAN"])] }], range: { start: "", end: "", step: 60, shifted: false }, read_at: "" };
    const { traces, axes, anchor } = trendTraces(data);
    expect(anchor).toBe("y3");
    expect((axes.yaxis3 as { type: string }).type).toBe("category");
    expect((axes.yaxis as { domain: number[] }).domain[0]).toBeGreaterThan(0);
    expect(traces.map((trace) => trace.name)).toEqual(["AUTO", "MAN", "number"]);
  });
});

describe("a trend from the address", () => {
  it("draws the assistant's chart signals over its period", () => {
    const view = viewFromAddress("?signal=FIC-101.PV&signal=FIC-101.SP&signal=FIC-101.PV&start=2026-10-25T00:00:00Z&end=2026-10-26T00:00:00Z");
    expect(view?.plots[0].lines.map((line) => line.signal_id)).toEqual(["FIC-101.PV", "FIC-101.SP"]);
    expect(view?.period).toMatchObject({ mode: "fixed", start: "2026-10-25T00:00:00.000Z", end: "2026-10-26T00:00:00.000Z" });
    expect(viewFromAddress("?signal=A")?.period.mode).toBe("relative");
    expect(viewFromAddress("")).toBeNull();
  });
});
