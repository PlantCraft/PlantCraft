/**
 * The trend on a point's page: one signal looked at closely ("more options in
 * this chart, like a trend, for one signal"). Values as recorded or as averages, the min–max band
 * of each average, the archived values as dots, the compression's deviation around them, and the
 * same period a while earlier. Several signals together belong in View's Trends.
 */
import { timeFigure, PeriodPicker, qualityBands, periodRange, saveFile, type TimeLine, type TimePeriod, useBrandTheme } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { t } from "./i18n";
import { plotted } from "./kinds";
import type { Point, Series } from "./types";
import { ErrorBox, Loading } from "./ui";

// Up to this span values are drawn as recorded by default; longer ranges use averages.
const RAW_SPAN_SECONDS = 3600;
// As recorded is offered up to a day: past that a page would carry too many values.
const RECORDED_MAX_SECONDS = 86_400;

export type Show = "auto" | "recorded" | "averages";
export type Compare = "" | "previous" | "day" | "week";
export const COMPARE: Record<Exclude<Compare, "">, string> = { previous: "The period before", day: "A day earlier", week: "A week earlier" };

/** The grid step (s) of averages over ``seconds``, about 1,500 cells. */
export function averageStep(seconds: number): number {
  return Math.max(1, Math.round(seconds / 1500));
}

/** The step to read with: none (as recorded) or the averages' grid. */
export function stepFor(seconds: number, show: Show = "auto"): number | undefined {
  if (show === "recorded" && seconds <= RECORDED_MAX_SECONDS) return undefined;
  if (show === "auto" && seconds <= RAW_SPAN_SECONDS) return undefined;
  return averageStep(seconds);
}

/** How far back a comparison looks, in seconds. */
export function compareOffset(compare: Compare, range: number): number {
  return compare === "previous" ? range : compare === "day" ? 86_400 : compare === "week" ? 604_800 : 0;
}

/** ISO times moved later by ``seconds``: an earlier period drawn over this one. */
export function shifted(times: string[], seconds: number): string[] {
  return times.map((at) => new Date(Date.parse(at) + seconds * 1000).toISOString());
}

/** The deviation the compression allows around each value: fixed, or a share of the value. */
export function deviationAt(point: Pick<Point, "deviation" | "deviation_percent">, value: number): number {
  return point.deviation_percent != null ? Math.abs(value) * point.deviation_percent / 100 : point.deviation;
}

/** The series as a CSV file (time in UTC, value, and the band when there is one). */
export function seriesCsv(series: Series, tag: string): string {
  const band = series.low && series.high;
  const rows = [["time", tag, ...(band ? ["low", "high"] : [])].join(",")];
  series.t.forEach((at, index) => {
    const cell = (value: unknown) => (value === null || value === undefined ? "" : typeof value === "string" ? `"${value.replace(/"/g, '""')}"` : String(value));
    rows.push([at, cell(series.v[index]), ...(band ? [cell(series.low![index]), cell(series.high![index])] : [])].join(","));
  });
  return rows.join("\n") + "\n";
}

function rgba(hex: string, alpha: number): string {
  const value = parseInt(hex.replace("#", ""), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

/** Two edges filled between, drawn under the lines and left out of the hover. */
function bandTraces(t: string[], low: (number | null)[], high: (number | null)[], color: string, name: string) {
  const edge = { type: "scatter" as const, mode: "lines" as const, x: t, line: { width: 0, color }, hoverinfo: "skip" as const, showlegend: false, connectgaps: false };
  return [{ ...edge, y: high, name }, { ...edge, y: low, name, fill: "tonexty" as const, fillcolor: rgba(color, 0.18) }];
}

/** The trend panel; the page keeps the period (its notebook button opens the same one). */
export function PointTrend({ point, signal, tag, period, onPeriod }: { point: Point; signal: string; tag: string; period: TimePeriod; onPeriod: (period: TimePeriod) => void }) {
  const theme = useBrandTheme();
  const [show, setShow] = useState<Show>("auto");
  const [range_, setRange] = useState(true);
  const [dots, setDots] = useState(false);
  const [deviation, setDeviation] = useState(false);
  const [compare, setCompare] = useState<Compare>("");
  const [series, setSeries] = useState<Series | null>(null);
  const [earlier, setEarlier] = useState<Series | null>(null);
  const [error, setError] = useState("");
  const fixed = period.window === "fixed";
  const range = Math.max(1, periodRange(period).seconds || 0);
  const step = stepFor(range, show);
  const number = point.kind === "number";
  const recorded = step === undefined;
  const offset = compareOffset(compare, range);

  useEffect(() => {
    if (fixed && (!period.from || !period.to || range <= 1)) return;
    const load = () => {
      // A little past now: the newest value (the snapshot) is stamped by the collector's clock.
      const { start, end } = periodRange(period, Date.now(), 60_000);
      api.series(signal, start, end, step, !recorded && number && range_)
        .then((found) => { setSeries(found); setError(""); }).catch((err: Error) => setError(err.message));
      if (offset) {
        const back = (at: string) => new Date(Date.parse(at) - offset * 1000).toISOString();
        api.series(signal, back(start), back(end), step).then(setEarlier).catch(() => setEarlier(null));
      } else setEarlier(null);
    };
    load();
    if (fixed) return;
    const timer = window.setInterval(load, range <= 3600 ? 5000 : 60_000);
    return () => window.clearInterval(timer);
  }, [signal, range, fixed, period.from, period.to, step, range_, offset]);

  // Uncertain, substituted and bad periods shaded behind the line (G5), in their status tone.
  const bands = useMemo(() => series ? qualityBands(series.quality, series.t[series.t.length - 1] ?? new Date().toISOString()) : [], [series]);
  const figure = useMemo(() => {
    if (!series) return null;
    const lines: TimeLine[] = [{ name: tag, t: series.t, ...plotted(series.kind, series.v), unit: point.unit, step: point.step }];
    if (earlier) lines.push({ name: t("{tag}, {when}", { tag, when: t(COMPARE[compare as Exclude<Compare, "">]).toLowerCase() }), t: shifted(earlier.t, offset), ...plotted(earlier.kind, earlier.v), unit: point.unit, step: point.step, dash: "dash" });
    const drawn = timeFigure({ lines, bands, height: 340, filename: tag }, theme);
    const main = drawn.data[0];
    const color = main.line.color;
    const under = [];
    if (!recorded && series.low && series.high) {
      // A cell with no archived value inside (the line crosses it) has its average for both edges.
      const average = (index: number) => (typeof series.v[index] === "number" ? series.v[index] as number : null);
      under.push(...bandTraces(series.t, series.low.map((low, i) => low ?? average(i)), series.high.map((high, i) => high ?? average(i)), color, t("Lowest and highest")));
    }
    if (recorded && deviation && number && !point.step) {
      const values = series.v.map((value) => (typeof value === "number" ? value : null));
      const width = values.map((value) => (value === null ? null : deviationAt(point, value)));
      under.push(...bandTraces(series.t, values.map((value, i) => (value === null ? null : value - width[i]!)), values.map((value, i) => (value === null ? null : value + width[i]!)), color, t("Compression deviation")));
    }
    const lead = recorded && dots ? { ...main, mode: "lines+markers" as const, marker: { size: 5, color } } : main;
    return { ...drawn, data: [...under, lead, ...drawn.data.slice(1)] };
  }, [series, earlier, bands, theme, recorded, dots, deviation, compare, offset, point]);

  function download() {
    if (!series) return;
    saveFile(`${tag.replace(/[^\w.-]+/g, "_")}.csv`, seriesCsv(series, tag), "text/csv");
  }

  const what = recorded ? t("Archived values, as recorded.") : t("Time-weighted averages every {step} s.", { step: step! });
  return <div className="panel" data-tour="point-trend">
    <div className="panel-header"><div><h2>{t("Trend")}</h2><p>{what}{" "}
      {!recorded && series?.low ? t("Band: lowest and highest value in each average.") : ""}{" "}
      {bands.length ? t("Shaded: values whose quality was not good ({count} periods).", { count: bands.length }) : ""}</p></div>
      <PeriodPicker value={period} onChange={onPeriod} /></div>
    <div className="trend-options">
      <div className="segmented" role="group" aria-label={t("Values")}>
        {(["auto", "recorded", "averages"] as Show[]).map((key) => <button key={key} type="button" className={show === key ? "on" : ""} aria-pressed={show === key}
          disabled={key === "recorded" && range > RECORDED_MAX_SECONDS} title={key === "recorded" && range > RECORDED_MAX_SECONDS ? t("Up to a day") : undefined}
          onClick={() => setShow(key)}>{t(key === "auto" ? "Auto" : key === "recorded" ? "As recorded" : "Averages")}</button>)}
      </div>
      {number && !recorded && <label className="check"><input type="checkbox" checked={range_} onChange={(event) => setRange(event.target.checked)} />{t("Lowest and highest")}</label>}
      {recorded && <label className="check"><input type="checkbox" checked={dots} onChange={(event) => setDots(event.target.checked)} />{t("Archived values as dots")}</label>}
      {recorded && number && !point.step && <label className="check"><input type="checkbox" checked={deviation} onChange={(event) => setDeviation(event.target.checked)} />{t("Compression deviation")}</label>}
      <label className="inline-select">{t("Compare with")}<select value={compare} onChange={(event) => setCompare(event.target.value as Compare)}>
        <option value="">{t("Nothing")}</option>
        {Object.entries(COMPARE).map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}
      </select></label>
      <button type="button" className="button button-secondary button-small" onClick={download} disabled={!series?.t.length}><Download size={15} />{t("CSV")}</button>
    </div>
    {error && <ErrorBox text={error} />}
    {figure ? (series!.t.length ? <Plot data={figure.data} layout={figure.layout} config={figure.config} style={{ width: "100%" }} useResizeHandler />
      : <p className="muted empty">{t("No values in this range yet.")}</p>) : <Loading />}
  </div>;
}
