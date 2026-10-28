/**
 * `@plantcraft/ui/plot`: the suite's one Plotly build and its time chart. A subpath, so an
 * app without charts never loads Plotly; an app with charts installs `react-plotly.js` and
 * `plotly.js-cartesian-dist-min` and imports `Plot` from here instead of keeping its own.
 */
import { useEffect, useMemo, useRef, type ComponentProps, type ReactNode } from "react";
import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js-cartesian-dist-min";
import type { BrandTheme } from "./brandTheme.js";
import { timeFigure, type TimeFigureOptions } from "./timeChart.js";
import { zonedFigure } from "./timeZone.js";
import { useBrandTheme } from "./useBrandTheme.js";

const PlotlyPlot = createPlotlyComponent(Plotly);

export type PlotProps = ComponentProps<typeof PlotlyPlot>;

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
      current.frame = requestAnimationFrame(() => { if (node.isConnected) void Plotly.Plots.resize(node); });
    }) };
    current.observer.observe(parent);
    watch.current = current;
  };
  useEffect(() => () => { watch.current?.observer.disconnect(); if (watch.current) cancelAnimationFrame(watch.current.frame); watch.current = null; }, []);
  return <PlotlyPlot
    {...props}
    data={figure.data as PlotProps["data"]}
    layout={figure.layout as PlotProps["layout"]}
    onInitialized={(state, node) => { follow(node); onInitialized?.(state, node); }}
  />;
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
