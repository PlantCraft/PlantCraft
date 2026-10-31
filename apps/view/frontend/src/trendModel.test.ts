import { describe, expect, it } from "vitest";
import { chipText, EMPTY_VIEW, labDetail, lineName, MAX_COMPARISONS, readable, stateRuns, subplotDomains, TREND_COMPARISONS, trendCsv, trendTraces, viewFromAddress } from "./trendModel";
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

  it("draws laboratory results as markers at their sampling times, with their times in the tooltip", () => {
    const samples = [
      { sampled_at: "2026-10-31T06:00:00Z", value: 412, status: "approved", received_at: "2026-10-31T08:00:00Z", approved_at: "2026-10-31T09:30:00Z" },
      { sampled_at: "2026-10-31T10:00:00Z", value: 415, status: "entered", received_at: null, approved_at: null },
      { sampled_at: "2026-10-31T11:00:00Z", value: 9, status: "rejected" },
    ];
    const lab = { ...line("Viscosity", "laboratory:VISC", samples.map((s) => s.sampled_at), [412, 415, 9]), unit: "cP", samples };
    const data: TrendData = { plots: [{ title: "", lines: [lab] }], range: { start: "t1", end: "t2", step: 60, shifted: false }, read_at: "2026-10-31T12:00:00Z" };
    const [trace] = trendTraces(data).traces as Array<{ mode: string; x: string[]; marker: { symbol: string[] }; customdata: string[]; hovertemplate: string }>;
    expect(trace.mode).toBe("markers");
    expect(trace.x).toEqual(samples.map((s) => s.sampled_at));
    expect(trace.marker.symbol).toEqual(["circle", "circle-open", "x"]);
    expect(trace.customdata[0]).toMatch(/^Approved<br>Received .+<br>Approved .+$/);
    expect(labDetail(samples[1])).toBe("Not yet approved");
    expect(trace.hovertemplate).toContain("%{customdata}");
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

describe("earlier periods over the trend (V11)", () => {
  const line = (label: string, extra: Record<string, unknown> = {}) => ({ label, unit: "m3/h", t: ["2026-10-31T00:00:00Z"], v: [1], kind: "number", error: null, ...extra });
  const data = {
    plots: [{ title: "", lines: [
      line("FIC-101"), line("FIC-102", { style: { color: "#123456" } }),
      line("FIC-101 · 1 day earlier", { compare: "1d", source: 0 }), line("FIC-102 · 1 day earlier", { compare: "1d", source: 1 }),
    ] }],
    range: { start: "2026-10-30T00:00:00Z", end: "2026-10-31T00:00:00Z", step: 60, shifted: false }, read_at: "2026-10-31T00:00:00Z",
  } as unknown as TrendData;

  it("draws each earlier line dotted, lighter, in its own line's colour", () => {
    const { traces } = trendTraces(data, {}, ["#aa0000", "#00aa00"]);
    const colour = (index: number) => (traces[index] as { line: { color?: string } }).line.color;
    expect(colour(0)).toBe("#aa0000");
    expect(colour(1)).toBe("#123456");
    expect(colour(2)).toBe("#aa0000");
    expect(colour(3)).toBe("#123456");
    expect((traces[2] as { line: { dash: string } }).line.dash).toBe("dot");
    expect((traces[2] as { opacity?: number }).opacity).toBe(0.7);
    expect((traces[0] as { opacity?: number }).opacity).toBeUndefined();
  });

  it("leaves the colours to the chart when nothing is compared", () => {
    const own = { ...data, plots: [{ title: "", lines: data.plots[0].lines.slice(0, 1) }] } as TrendData;
    expect((trendTraces(own, {}, ["#aa0000"]).traces[0] as { line: { color?: string } }).line.color).toBeUndefined();
  });

  it("offers four earlier periods, at most three at once", () => {
    expect(TREND_COMPARISONS.map((item) => item.id)).toEqual(["previous", "1d", "7d", "28d"]);
    expect(MAX_COMPARISONS).toBe(3);
  });
});
