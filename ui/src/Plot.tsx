/**
 * `@plantcraft/ui/plot`: the suite's one Plotly build and its time chart. A subpath, so an
 * app without charts never loads Plotly; an app with charts installs `react-plotly.js` and
 * `plotly.js-cartesian-dist-min` and imports `Plot` from here instead of keeping its own.
 * Plotly (1.4 MB) itself is fetched the first time a chart is drawn, not when a page that
 * could draw one opens: a page whose charts sit behind a tab or a click opens without it. It
 * comes from the platform (/static/vendor/, one copy for all apps), or from the app's own
 * build where the platform does not serve it.
 */
import { lazy, Suspense, useEffect, useMemo, useRef, type ReactNode } from "react";
import type { PlotParams } from "react-plotly.js";
import type { BrandTheme } from "./brandTheme.js";
import { SHARED_PLOTLY, SHARED_VENDOR_URL } from "./sharedVendor.js";
import { timeFigure, type TimeFigureOptions } from "./timeChart.js";
import { zonedFigure } from "./timeZone.js";
import { useBrandTheme } from "./useBrandTheme.js";

type Plotly = typeof import("plotly.js-cartesian-dist-min").default;

let plotly: Plotly | null = null;

/** How long the platform's copy may take before the app's own is used instead. */
const SHARED_WAIT_MS = 20000;

/**
 * Plotly from the platform, one copy for every app (sharedVendor.ts). Rejects where the platform
 * does not have this exact build (404: an app run on its own, another Plotly version) or the
 * script does not load in time; the caller then imports the app's own copy.
 */
export function loadSharedPlotly(url = SHARED_VENDOR_URL + SHARED_PLOTLY.name, wait = SHARED_WAIT_MS): Promise<Plotly> {
  const host = globalThis as unknown as { Plotly?: Plotly; document?: Document; navigator?: Navigator };
  if (host.Plotly) return Promise.resolve(host.Plotly);
  // jsdom (unit tests) never runs a script it was given: go straight to the import.
  if (!host.document || /jsdom/i.test(host.navigator?.userAgent ?? "")) return Promise.reject(new Error("no shared Plotly here"));
  return new Promise((resolve, reject) => {
    const script = host.document!.createElement("script");
    const fail = (why: string) => { clearTimeout(timer); script.remove(); reject(new Error(why)); };
    const timer = setTimeout(() => fail("shared Plotly took too long"), wait);
    script.src = url;
    script.async = true;
    script.onload = () => { clearTimeout(timer); if (host.Plotly) resolve(host.Plotly); else fail("shared Plotly did not define Plotly"); };
    script.onerror = () => fail("shared Plotly not served");
    host.document!.head.appendChild(script);
  });
}

const PlotlyPlot = lazy(async () => {
  const [{ default: createPlotlyComponent }, Plotly] = await Promise.all([
    import("react-plotly.js/factory"),
    loadSharedPlotly().catch(() => import("plotly.js-cartesian-dist-min").then((module) => module.default)),
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
  // The display size changes the chart's type size (plotTheme reads it): part of the key.
  const size = typeof document === "undefined" ? undefined : document.documentElement.dataset.size;
  const figure = useMemo(() => timeFigure(props, theme), [props, theme, size]); // eslint-disable-line react-hooks/exhaustive-deps
  const hasValues = props.lines.some((line) => line.t.length > 0);
  return <div className={["pc-time-chart", props.className].filter(Boolean).join(" ")}>
    {props.toolbar && <div className="pc-time-chart-toolbar">{props.toolbar}</div>}
    {hasValues || !props.empty
      ? <Plot data={figure.data} layout={figure.layout} config={figure.config} style={{ width: "100%" }} useResizeHandler />
      : props.empty}
  </div>;
}
