import { BRAND_COLORS, currentTheme, plotTheme } from "@plantcraft/ui";
import { t } from "./i18n";
import { Plot } from "@plantcraft/ui/plot";
import type { Chart, Occurrence } from "./types";

/** A rule's first value with its limits (and the clear line, the limit less the deadband, on the
 * side the value comes back from), each occurrence shaded. */
export function AlarmChart({ chart, limit = null, high = null, deadband = 0, occurrences, end, unit }: {
  chart: Chart; limit?: number | null; high?: number | null; deadband?: number; occurrences: Occurrence[]; end: string; unit?: string;
}) {
  const mode = currentTheme();
  const colors = BRAND_COLORS[mode];
  const last = chart.v.length ? chart.v[chart.v.length - 1] : null;
  // The clear line sits on the side of the limit the value lies on most of the time.
  const below = limit !== null && chart.v.filter((value) => value < limit).length >= chart.v.length / 2;
  const lines = [
    ...(limit === null ? [] : [{ y: limit, color: colors.problem, dash: "solid" }]),
    ...(high === null ? [] : [{ y: high, color: colors.problem, dash: "solid" }]),
    ...(limit !== null && high === null && deadband > 0 && last !== null ? [{ y: below ? limit - deadband : limit + deadband, color: colors.attention, dash: "dot" }] : []),
  ];
  const shapes = [
    ...lines.map((line) => ({ type: "line" as const, xref: "paper" as const, x0: 0, x1: 1, y0: line.y, y1: line.y, line: { color: line.color, width: 1.5, dash: line.dash } })),
    ...occurrences.map((item) => ({
      type: "rect" as const, xref: "x" as const, yref: "paper" as const, y0: 0, y1: 1, line: { width: 0 },
      x0: item.start ?? item.started_at, x1: (item.end ?? item.ended_at) || end, fillcolor: colors.problem, opacity: 0.12,
    })),
  ];
  const theme = plotTheme(mode);
  return <Plot
    data={[{ type: "scatter", mode: "lines", x: chart.t, y: chart.v, name: t("Value"), line: { color: colors.series[0], width: 1.4 }, hovertemplate: `%{x}<br>%{y:.4g}${unit ? ` ${unit}` : ""}<extra></extra>` }]}
    // A time axis even with no samples (an alarm on events): the occurrences are dates.
    layout={{ ...theme, xaxis: { ...theme.xaxis, type: "date" }, height: 300, margin: { l: 50, r: 10, t: 10, b: 40 }, showlegend: false, shapes }}
    config={{ displaylogo: false, responsive: true }}
    style={{ width: "100%" }}
    useResizeHandler
  />;
}
