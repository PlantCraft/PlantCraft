/** Pure helpers of the Trends page: the empty view, the period text, the subplot layout and the CSV. */
import { fileTime, fileTimeHeader, localOf, sharedUnit } from "@plantcraft/ui";
import { t } from "./i18n";
import { windowLabel } from "./model";
import type { Data } from "plotly.js";
import type { LineStyle, TrendAgg, TrendData, TrendLine, TrendLineSpec, TrendView } from "./types";

export const TREND_WINDOWS = ["15m", "1h", "2h", "8h", "24h", "7d", "30d"];
/** The interval each value summarises (each line says how): null = chosen from the period, 0 = as recorded. */
export const TREND_STEPS: Array<{ seconds: number | null; label: string }> = [
  { seconds: null, label: "Automatic interval" },
  { seconds: 60, label: "1 minute" },
  { seconds: 600, label: "10 minutes" },
  { seconds: 3600, label: "1 hour" },
  { seconds: 86400, label: "1 day" },
  { seconds: 0, label: "As recorded" },
];
/** How a line summarises each interval. */
export const TREND_AGGS: Array<{ id: TrendAgg; label: string; short: string }> = [
  { id: "mean", label: "Mean", short: "mean" },
  { id: "last", label: "Last value", short: "last" },
  { id: "first", label: "First value", short: "first" },
  { id: "min", label: "Minimum", short: "min" },
  { id: "max", label: "Maximum", short: "max" },
];
export const DEFAULT_STYLE: LineStyle = { mode: "lines", shape: "linear", color: "", width: 2, dash: "solid", marker_size: 6, axis: "left" };

/** A line's style with every field filled in. */
export function styleOf(style?: Partial<LineStyle> | null): LineStyle {
  return { ...DEFAULT_STYLE, ...(style ?? {}) };
}

/** A line's name in the legend and the CSV: its label, the summary when not the mean, the unit. */
export function lineName(line: Pick<TrendLine, "label" | "unit" | "agg">): string {
  const agg = line.agg && line.agg !== "mean" && line.agg !== "recorded" ? ` · ${t(TREND_AGGS.find((item) => item.id === line.agg)?.short ?? line.agg)}` : "";
  return `${line.label}${agg}${line.unit ? ` (${line.unit})` : ""}`;
}

/** A line's own interval as text: "1 minute", or "" when it follows the trend's. */
export function intervalText(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "";
  return t(TREND_STEPS.find((item) => item.seconds === seconds)?.label ?? "{seconds} s", { seconds });
}

/** A line's chip on the page: its label, its own interval and its summary when not the mean. */
export function chipText(line: TrendLineSpec): string {
  const agg = line.agg && line.agg !== "mean" ? t(TREND_AGGS.find((item) => item.id === line.agg)?.short ?? line.agg) : "";
  return [line.label || line.signal_id, intervalText(line.step_seconds), agg].filter(Boolean).join(" · ");
}

/**
 * The Plotly traces and y axes of a trend: plot i draws on y axis i (left) and, for lines set
 * to the right axis, on an axis overlaying it on the right.
 */
export function trendTraces(data: TrendData, axisTheme: Record<string, unknown> = {}): { traces: Data[]; axes: Record<string, unknown>; anchor: string } {
  const count = data.plots.length;
  const domains = subplotDomains(count);
  const axes: Record<string, unknown> = {};
  const traces: Data[] = [];
  const stateColors = new Map<string, string>();
  // The time axis sits under the lowest plot: its band of states when it has one.
  let anchor = count > 1 ? `y${count}` : "y";
  data.plots.forEach((plot, index) => {
    const left = index ? `y${index + 1}` : "y";
    const right = `y${count + index + 1}`;
    const states = plot.lines.filter((line) => line.kind === "text" && line.t.length);
    const numbers = plot.lines.filter((line) => line.kind !== "text");
    // A text signal (a mode, running or stopped) is a band of states under the plot's lines.
    const [bottom, top] = domains[index];
    const band = !states.length ? 0 : numbers.some((line) => line.t.length) ? Math.min((top - bottom) * 0.35, 0.05 + 0.04 * states.length) : top - bottom;
    // An axis names a unit only when every line on it shares it (owner, 2026-10-23): with
    // two units, either would mislabel the other; each line keeps its own in the legend.
    const units = (side: "left" | "right") => sharedUnit(numbers.filter((line) => styleOf(line.style).axis === side).map((line) => line.unit));
    axes[index ? `yaxis${index + 1}` : "yaxis"] = { ...axisTheme, domain: [band && band < top - bottom ? bottom + band + 0.02 : bottom, top], anchor: "x", title: { text: [plot.title, units("left")].filter(Boolean).join(" · "), font: { size: 10 } } };
    if (numbers.some((line) => styleOf(line.style).axis === "right")) {
      axes[`yaxis${count + index + 1}`] = { ...axisTheme, overlaying: left, side: "right", anchor: "x", showgrid: false, title: { text: units("right"), font: { size: 10 } } };
    }
    if (states.length) {
      const axis = 2 * count + index + 1;
      axes[`yaxis${axis}`] = { ...axisTheme, domain: [bottom, bottom + band], anchor: "x", type: "category", fixedrange: true, showgrid: false, zeroline: false, automargin: true, categoryorder: "array", categoryarray: states.map(lineName).reverse() };
      for (const line of states) traces.push(...stateTraces(line, `y${axis}`, stateColors));
      if (index === count - 1) anchor = `y${axis}`;
    }
    for (const line of numbers) {
      if (!line.t.length) continue;
      const style = styleOf(line.style);
      traces.push({
        type: "scatter", mode: style.mode, x: line.t, y: line.v, connectgaps: false, name: lineName(line),
        line: { width: style.width, dash: style.dash, shape: style.shape, ...(style.color ? { color: style.color } : {}) },
        marker: { size: style.marker_size, ...(style.color ? { color: style.color } : {}) },
        xaxis: "x", yaxis: style.axis === "right" ? right : left,
        hovertemplate: `%{y:.4~g} ${line.unit}<extra>${lineName(line)}</extra>`,
      } as Data);
    }
  });
  return { traces, axes, anchor };
}

/** A text signal's values as runs of one state: each from its first sample to the next state's. */
export function stateRuns(times: string[], values: Array<number | string | null>): Array<{ state: string; start: string; end: string }> {
  const runs: Array<{ state: string; start: string; end: string }> = [];
  times.forEach((time, index) => {
    const value = values[index];
    const state = value === null || value === undefined || value === "" ? null : String(value);
    const last = runs[runs.length - 1];
    if (last) last.end = time;
    if (state === null) { if (last && last.state !== "") runs.push({ state: "", start: time, end: time }); return; }
    if (!last || last.state !== state) runs.push({ state, start: time, end: time });
  });
  return runs.filter((run) => run.state !== "");
}

const STATE_PALETTE = ["#2f6fdb", "#e8833a", "#3aa76d", "#9b59b6", "#c0392b", "#16a2b8", "#b8860b", "#7f8c8d"];

/** One thick bar per state of `line` on its band axis; a state keeps its colour across the trend. */
function stateTraces(line: TrendLine, yaxis: string, colors: Map<string, string>): Data[] {
  const name = lineName(line);
  const byState = new Map<string, { x: Array<string | null>; y: Array<string | null> }>();
  for (const run of stateRuns(line.t, line.v as Array<number | string | null>)) {
    const points = byState.get(run.state) ?? { x: [], y: [] };
    points.x.push(run.start, run.end, null);
    points.y.push(name, name, null);
    byState.set(run.state, points);
  }
  return [...byState.entries()].map(([state, points]) => {
    const known = colors.has(state);
    if (!known) colors.set(state, STATE_PALETTE[colors.size % STATE_PALETTE.length]);
    return {
      type: "scatter", mode: "lines", x: points.x, y: points.y, name: state, legendgroup: `state:${state}`, showlegend: !known,
      line: { width: 14, color: colors.get(state) }, connectgaps: false, xaxis: "x", yaxis,
      hovertemplate: `${state}<extra>${name}</extra>`,
    } as Data;
  });
}
export const MAX_PLOTS = 6;
export const MAX_LINES = 8;

export const EMPTY_VIEW: TrendView = { plots: [{ title: "", lines: [] }], period: { mode: "relative", window: "2h" }, step_seconds: null };

/** A new trend from the address, `/trends?signal=A&signal=B&start=&end=` (owner, 2026-10-26: a
 * chart of the assistant goes on in Trends): its signals on one plot, over its period. */
export function viewFromAddress(search: string): TrendView | null {
  const params = new URLSearchParams(search);
  const signals = [...new Set(params.getAll("signal").map((item) => item.trim()).filter(Boolean))].slice(0, MAX_LINES);
  if (!signals.length) return null;
  const start = params.get("start");
  const end = params.get("end");
  const fixed = Boolean(start && end && !Number.isNaN(Date.parse(start)) && !Number.isNaN(Date.parse(end)));
  return {
    plots: [{ title: "", lines: signals.map((signal_id) => ({ signal_id, label: "" })) }],
    period: fixed ? { mode: "fixed", window: EMPTY_VIEW.period.window, start: new Date(start as string).toISOString(), end: new Date(end as string).toISOString() } : EMPTY_VIEW.period,
    step_seconds: null,
  };
}

/** The view the server reads: plots without lines are left out. */
export function readable(view: TrendView): TrendView {
  return { ...view, plots: view.plots.filter((plot) => plot.lines.length) };
}

export function periodLabel(view: TrendView): string {
  const period = view.period;
  if (period.mode === "fixed") return t("{start} to {end}", { start: localOf(period.start ?? "").replace("T", " "), end: localOf(period.end ?? "").replace("T", " ") });
  return t("Last {window}", { window: windowLabel(period.window) });
}

/** One Plotly layout for every plot stacked on a shared time axis: plot i draws on y axis i. */
export function subplotDomains(count: number, gap = 0.06): Array<[number, number]> {
  if (count <= 1) return [[0, 1]];
  const height = (1 - gap * (count - 1)) / count;
  return Array.from({ length: count }, (_, index) => {
    const top = 1 - index * (height + gap);
    return [Math.max(0, top - height), top] as [number, number];
  });
}

function csvCell(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  const safe = /^[=+\-@\t\r]/.test(text) && !/^-?\d/.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

/** The trend as a wide CSV: the time, then one column per line (`label (unit)`); a signal read
 * at two intervals or summaries is two columns. */
export function trendCsv(data: TrendData): string {
  const lines = data.plots.flatMap((plot) => plot.lines).filter((line) => line.t.length);
  const seen = new Set<string>();
  const unique = lines.filter((line) => { const key = `${line.signal ?? line.label}|${line.agg ?? "mean"}|${line.step ?? ""}`; if (seen.has(key)) return false; seen.add(key); return true; });
  const rows = new Map<string, Array<number | null>>();
  unique.forEach((line, column) => line.t.forEach((time, index) => {
    const row = rows.get(time) ?? Array<number | null>(unique.length).fill(null);
    row[column] = line.v[index];
    rows.set(time, row);
  }));
  const header = [fileTimeHeader(), ...unique.map((line) => lineName(line))];
  const body = [...rows.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([time, values]) => [fileTime(time), ...values]);
  return [header, ...body].map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
