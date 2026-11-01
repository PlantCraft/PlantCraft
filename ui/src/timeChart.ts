/**
 * The suite's time chart: one look for every trend (Trends in View, a point's page in the
 * Historian, …). Pure helpers for Plotly, so this package needs no chart library: each app
 * draws with its own Plotly build and takes the periods, the layout, the hover text and the
 * buttons from here ("the same chart everywhere").
 */
import { BRAND_COLORS, plotFontSize, plotTheme, statusColors, type BrandTheme } from "./brandTheme.js";
import { t } from "./i18n.js";
import { fromWallClock, wallClock } from "./timeZone.js";

/** The relative periods a trend offers ("Last 2 hours"), shortest first. */
export const TIME_WINDOWS = ["15m", "1h", "2h", "8h", "24h", "7d", "30d"] as const;

const UNIT_SECONDS: Record<string, number> = { s: 1, m: 60, h: 3600, d: 86400 };

/** "2h" as seconds (NaN when it is not a period). */
export function windowSeconds(window: string): number {
  const match = /^(\d+)([smhd])$/.exec(window);
  return match ? Number(match[1]) * UNIT_SECONDS[match[2]] : Number.NaN;
}

/** "2h" as "2 hours". */
export function windowLabel(window: string): string {
  const match = /^(\d+)([smhd])$/.exec(window);
  if (!match) return window;
  const count = Number(match[1]);
  const unit = { s: ["second", "seconds"], m: ["minute", "minutes"], h: ["hour", "hours"], d: ["day", "days"] }[match[2] as "s"]!;
  return t("{count} {unit}", { count, unit: t(count === 1 ? unit[0] : unit[1]) });
}

/** The modebar keeps zoom, pan, autoscale, reset and the picture. */
export const PLOT_BUTTONS_OFF = ["select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "toggleSpikelines", "hoverClosestCartesian", "hoverCompareCartesian"] as const;

/** Plotly's config of a time chart; `modeBar: false` hides the buttons (small cards). */
export function timePlotConfig(options: { modeBar?: boolean } = {}) {
  return { displaylogo: false, responsive: true, ...(options.modeBar === false ? { displayModeBar: false } : {}), modeBarButtonsToRemove: [...PLOT_BUTTONS_OFF] };
}

export type TimeChartOptions = {
  /** Pixels; left out, 320. */
  height?: number;
  /** The time axis's range (ISO times); left out, the data's. */
  start?: string;
  end?: string;
  /** Room for a right-hand y axis. */
  rightAxis?: boolean;
  /** The legend above the plot; off for a single line. */
  legend?: boolean;
};

/**
 * The layout every time chart starts from: the suite's theme (`plotTheme()`), a date axis,
 * one hover box for every line at the time under the cursor, the legend in a row above.
 * Add the y axes (`yaxis`, `yaxis2`, …) on top of it.
 */
export function timeChartLayout(theme: Record<string, any>, options: TimeChartOptions = {}) {
  const legend = options.legend ?? true;
  return {
    ...theme,
    autosize: true,
    height: options.height ?? 320,
    margin: { l: 56, r: options.rightAxis ? 56 : 16, t: legend ? 8 : 16, b: 32 },
    showlegend: legend,
    legend: { ...(theme.legend ?? {}), orientation: "h" as const, y: 1.05, yanchor: "bottom" as const, x: 0 },
    xaxis: { ...(theme.xaxis ?? {}), type: "date" as const, ...(options.start && options.end ? { range: [options.start, options.end] } : {}) },
    hovermode: "x unified" as const,
  };
}

/** A line's hover text: "12.3 m³/h" with its name. */
export function timeHover(name: string, unit = "", text = false): string {
  return `${text ? "%{y}" : "%{y:.4~g}"}${unit ? ` ${unit}` : ""}<extra>${name}</extra>`;
}

/** A change of quality in a series: from `t` on, its values have `quality`. */
export type QualityChange = { t: string; quality: string };
/** A period whose values were not good, marked over the line (`markStrip()`). */
export type QualityBand = { from: string; to: string; quality: string };

/** The periods whose values were not good: from each change to the next (or `end`). */
export function qualityBands(changes: QualityChange[] | undefined, end: string): QualityBand[] {
  const out: QualityBand[] = [];
  (changes ?? []).forEach((change, i) => {
    if (change.quality === "good") return;
    out.push({ from: change.t, to: changes![i + 1]?.t ?? end, quality: change.quality });
  });
  return out;
}

/**
 * A marked stretch of a time chart (a bad-quality period, a check's event, an alarm): a strip in
 * its colour along the top edge of the plot. The plot itself
 * stays on the card's white or black, the same in every chart of the suite (2026-11-01: a tinted
 * fill over the whole plot read as a different chart). Needs a top margin of 14 px or more.
 */
export function markStrip(x0: string | number, x1: string | number, color: string) {
  return [
    { type: "rect" as const, xref: "x" as const, yref: "paper" as const, x0, x1, y0: 1.004, y1: 1.034, fillcolor: color, opacity: 0.9, line: { width: 0 }, layer: "above" as const },
  ];
}

/** Plotly shapes that mark the bands in their status colour (`statusColors()`, `markStrip()`). */
export function bandShapes(bands: QualityBand[], tones: Record<string, string>) {
  return bands.flatMap((band) => markStrip(band.from, band.to, tones[band.quality] ?? tones.warning ?? tones.attention));
}

/** The y axis's unit: the lines' one unit, or nothing when they differ (each hover keeps its own). */
export function sharedUnit(units: (string | undefined)[]): string {
  const found = new Set(units.map((unit) => unit ?? ""));
  return found.size === 1 ? [...found][0] : "";
}

/** An ISO time as a `datetime-local` input's value (display time zone, to the minute). */
export function localOf(iso: string): string {
  if (!iso) return "";
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return "";
  return wallClock(ms).slice(0, 16).replace(" ", "T");
}

/** A `datetime-local` value (display time zone) as an ISO time. */
export function isoOf(local: string): string {
  if (!local) return "";
  const ms = fromWallClock(local);
  return Number.isNaN(ms) ? "" : new Date(ms).toISOString();
}

/** A chart's period: a relative window ("2h") or "fixed" with its `from` and `to` (`datetime-local` values). */
export type TimePeriod = { window: string; from: string; to: string };

/** The period's start and end (ISO) and its length in seconds; a relative one ends `ahead` ms past now. */
export function periodRange(period: TimePeriod, now = Date.now(), ahead = 0): { start: string; end: string; seconds: number } {
  if (period.window === "fixed") {
    const start = isoOf(period.from), end = isoOf(period.to);
    const seconds = start && end ? (new Date(end).getTime() - new Date(start).getTime()) / 1000 : Number.NaN;
    return { start, end, seconds };
  }
  const seconds = windowSeconds(period.window);
  return { start: new Date(now - seconds * 1000).toISOString(), end: new Date(now + ahead).toISOString(), seconds };
}

/** The period after choosing `window`; "fixed" starts as the last 24 hours when it has no dates yet. */
export function choosePeriod(period: TimePeriod, window: string, now = Date.now()): TimePeriod {
  if (window === "fixed" && !period.from) return { window, from: localOf(new Date(now - 86_400_000).toISOString()), to: localOf(new Date(now).toISOString()) };
  return { ...period, window };
}

/** A line of a time chart. */
export type TimeLine = {
  name: string;
  t: string[];
  v: (number | string | null)[];
  unit?: string;
  /** Left out, the theme's series colour in order. */
  color?: string;
  /** Held until the next value (a step), as for states and set points. */
  step?: boolean;
  /** Text values (states): a category axis. */
  text?: boolean;
  dash?: "solid" | "dot" | "dash";
};

export type TimeFigureOptions = {
  lines: TimeLine[];
  /** Periods whose values were not good, marked on the chart (`qualityBands()`). */
  bands?: QualityBand[];
  height?: number;
  /** The time axis's range (ISO); left out, the data's. */
  start?: string;
  end?: string;
  /** Left out, the legend shows from two lines. */
  legend?: boolean;
  /** Off for small cards: no buttons. */
  modeBar?: boolean;
  /** The picture's file name (the camera button), without .png. */
  filename?: string;
};

/** The figure a time chart draws: pure, so tests and apps that need more can start from it. */
export function timeFigure(props: TimeFigureOptions, theme: BrandTheme) {
  const colors = BRAND_COLORS[theme];
  const base = plotTheme(theme);
  const text = props.lines.length > 0 && props.lines.every((line) => line.text);
  const unit = sharedUnit(props.lines.map((line) => line.unit));
  const data = props.lines.map((line, index) => ({
    x: line.t, y: line.v, name: line.name, type: "scatter" as const, mode: "lines" as const, connectgaps: false,
    line: { color: line.color ?? colors.series[index % colors.series.length], width: 2, dash: line.dash ?? "solid", shape: (line.step || line.text ? "hv" : "linear") as "hv" | "linear" },
    hovertemplate: timeHover(line.name, line.unit ?? "", line.text),
  }));
  const layout = {
    ...timeChartLayout(base, { height: props.height, start: props.start, end: props.end, legend: props.legend ?? props.lines.length > 1 }),
    // A solid background, so the picture (PNG) reads in the theme it was taken in.
    paper_bgcolor: colors.surface, plot_bgcolor: colors.surface,
    shapes: bandShapes(props.bands ?? [], statusColors(theme)),
    yaxis: { ...base.yaxis, title: { text: unit, font: { size: plotFontSize(10) } }, type: (text ? "category" : "linear") as "category" | "linear" },
  };
  const config = { ...timePlotConfig({ modeBar: props.modeBar }), toImageButtonOptions: { format: "png" as const, filename: props.filename ?? "chart", scale: 2 } };
  return { data, layout, config };
}
