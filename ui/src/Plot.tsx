/**
 * `@plantcraft/ui/plot`: the suite's one Plotly build and its time chart. A subpath, so an
 * app without charts never loads Plotly; an app with charts installs `react-plotly.js` and
 * `plotly.js-cartesian-dist-min` and imports `Plot` from here instead of keeping its own.
 * Plotly (1.4 MB) itself is fetched the first time a chart is drawn, not when a page that
 * could draw one opens: a page whose charts sit behind a tab or a click opens without it.
 */
import { lazy, Suspense, useEffect, useMemo, useRef, type ReactNode } from "react";
import type { PlotParams } from "react-plotly.js";
import type { BrandTheme } from "./brandTheme.js";
import { timeFigure, type TimeFigureOptions } from "./timeChart.js";
import { zonedFigure } from "./timeZone.js";
import { useBrandTheme } from "./useBrandTheme.js";

let plotly: typeof import("plotly.js-cartesian-dist-min").default | null = null;

const PlotlyPlot = lazy(async () => {
  const [{ default: createPlotlyComponent }, { default: Plotly }] = await Promise.all([
    import("react-plotly.js/factory"),
    import("plotly.js-cartesian-dist-min"),
  ]);
  plotly = Plotly;
  return { default: createPlotlyComponent(Plotly) };
});

export type PlotProps = PlotParams;

/**
 * The one Plotly build the interface ships: lines, bars, pie, histograms, box and heatmaps.
 * UTC times (ISO with "Z" or an offset) are drawn in the display time zone (see timeZone.ts);
 * a zoom or click hands back that zone's wall clock, which `fromWallClock` turns into a time.
 */
export function Plot(props: PlotProps) {
  const figure = useMemo(() => zonedFigure({ data: props.data as unknown[], layout: props.layout as Record<string, unknown> }), [props.data, props.layout]);
  const watch = useRef<{ observer: ResizeObserver; frame: number } | null>(null);
  const { onInitialized, useResizeHandler } = props;
  // `useResizeHandler` follows the window only; a chart also follows its own box, which changes
  // without the window when the sidebar folds, a panel opens or a dashboard grid lays out again.
  const follow = (node: HTMLElement) => {
    const parent = node.parentElement;
    if (!useResizeHandler || watch.current || !parent || typeof ResizeObserver === "undefined") return;
    const current = { frame: 0, observer: new ResizeObserver(() => {
      cancelAnimationFrame(current.frame);
      current.frame = requestAnimationFrame(() => { if (node.isConnected && plotly) void plotly.Plots.resize(node); });
    }) };
    current.observer.observe(parent);
    watch.current = current;
  };
  useEffect(() => () => { watch.current?.observer.disconnect(); if (watch.current) cancelAnimationFrame(watch.current.frame); watch.current = null; }, []);
  // Until Plotly arrives, an empty box of the chart's size keeps the page from jumping.
  const height = props.style?.height ?? (props.layout as { height?: number } | undefined)?.height ?? 450;
  return <Suspense fallback={<div className={props.className} style={{ ...props.style, height }} aria-busy="true" />}>
    <PlotlyPlot
      {...props}
      data={figure.data as PlotProps["data"]}
      layout={figure.layout as PlotProps["layout"]}
      onInitialized={(state, node) => { follow(node); onInitialized?.(state, node); }}
    />
  </Suspense>;
}

export type { TimeLine } from "./timeChart.js";

export type TimeChartProps = TimeFigureOptions & {
  /** "auto" follows the user's theme; "light" or "dark" fixes it (a printed report). */
  theme?: "auto" | BrandTheme;
  /** Controls above the chart, on the right (period, export…). */
  toolbar?: ReactNode;
  /** Shown instead of the chart when no line has a value. */
  empty?: ReactNode;
  className?: string;
};

/** The suite's time chart: one look for every trend, in the user's theme, with quality bands. */
export function TimeChart(props: TimeChartProps) {
  const userTheme = useBrandTheme();
  const theme = !props.theme || props.theme === "auto" ? userTheme : props.theme;
  const figure = useMemo(() => timeFigure(props, theme), [props, theme]);
  const hasValues = props.lines.some((line) => line.t.length > 0);
  return <div className={["pc-time-chart", props.className].filter(Boolean).join(" ")}>
    {props.toolbar && <div className="pc-time-chart-toolbar">{props.toolbar}</div>}
    {hasValues || !props.empty
      ? <Plot data={figure.data} layout={figure.layout} config={figure.config} style={{ width: "100%" }} useResizeHandler />
      : props.empty}
  </div>;
}
