/** One card on the grid: reads its data and draws it as a stat, gauge, time series, bar chart,
 * table, scatter or note, with its options (round 7, after Grafana's panels). */
import { timePlotConfig, renderMarkdown, errorMessage as message, saveFile, BRAND_COLORS, currentTheme, plotTheme, statusVar, timeScale } from "@plantcraft/ui";
import { AlertTriangle, Download, GripVertical, LoaderCircle, Maximize2, Repeat2, X } from "lucide-react";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import type { Data, PlotHoverEvent, Shape } from "plotly.js";
import type { CardSource } from "./api";
import { colorOf, effective, legible, levelLabel, mappedText, textOn, optionsOf, stepColor, stepValues, sortedSteps, stepOf, valueColor } from "./fields";
import { formatDate, t } from "./i18n";
import { AGG_LABELS, cardCsv, cardPixels, cardCsvName, cardTitle, formatValue, interpolate, stateLabel, stateStatus, windowLabel } from "./model";
import { cursorShape, useSharedCursor } from "./cursor";
import { DiagramCardBody } from "./diagrams/DiagramCard";
import { AnalogBar, limitsFromSteps, normalRange } from "./analog";
import { ApcPanel } from "./apc";
import { Plot } from "@plantcraft/ui/plot";
import type { Card, CardData, CardOptions, FieldConfig, Line, State, ValueRow } from "./types";

/** A plot's height in a card `rows` high: the card less its padding and heading. */
const plotHeight = (rows: number) => cardPixels(rows) - 58;
// The suite's chart buttons (@plantcraft/ui): small cards hide them.
const plotConfig = (full: boolean) => timePlotConfig({ modeBar: full });

/** Reads one card, again on every `tick` (the dashboard's refresh). */
export function useCardData(load: () => Promise<CardData>, key: string, tick: number) {
  const [data, setData] = useState<CardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    setLoading(true);
    load()
      .then((result) => { if (live) { setData(result); setError(""); } })
      .catch((err) => { if (live) setError(message(err)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // `load` changes identity every render; `key` names what it reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);
  return { data, error, loading };
}

function Problems({ items }: { items: Array<{ label: string; error: string | null }> }) {
  const failed = items.filter((item) => item.error);
  if (!failed.length) return null;
  return <ul className="tc-problems">{failed.map((item, index) => <li key={index}><AlertTriangle size={13} /><span><b>{item.label}</b> {item.error}</span></li>)}</ul>;
}

/** The value as shown: its mapping's words, else the number with the field's decimals, else "No value" text. */
export function shownValue(config: FieldConfig, value: number | string | null | undefined): string {
  const mapped = mappedText(config, value);
  if (mapped) return mapped;
  if ((value === null || value === undefined) && config.no_value) return config.no_value;
  return formatValue(value, config.decimals);
}

function unitOf(config: FieldConfig, row: { unit: string }): string {
  return config.unit ?? row.unit ?? "";
}

function rangeOf(row: { low?: number | null; high?: number | null }) {
  return { low: row.low, high: row.high };
}

/** Whether a state is shown in words (alarm, warning): not for "none". */
function hasState(state: State | undefined): boolean {
  return Boolean(state) && state !== "none";
}

/** The value's colour: a mapping's or a threshold's, the fixed one, or none (plain text). */
function toneOf(config: FieldConfig, row: ValueRow, index: number): string | undefined {
  const coloured = config.mappings?.length || config.thresholds?.steps?.length || config.color_mode === "fixed" || config.color;
  if (row.result) return hasState(row.state) ? statusVar(stateStatus(row.state), "text") : undefined;
  return coloured ? valueColor(config, row.value, index, rangeOf(row)) : undefined;
}

/** The value with its line over the window underneath (no axes), over the normal range shaded
 * grey when there is one (ISA-101: the line leaving the band is what catches the eye). */
export function Sparkline({ line, color, normal }: { line: Line | undefined; color: string; normal?: { low: number | null; high: number | null } | null }) {
  const points = (line?.t ?? []).map((time, index) => [Date.parse(time), line!.v[index]] as const).filter((pair): pair is readonly [number, number] => typeof pair[1] === "number");
  if (points.length < 2) return null;
  const xs = points.map((pair) => pair[0]);
  const ys = points.map((pair) => pair[1]);
  let [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const band = sparkBand(normal, y0, y1);
  if (band) [y0, y1] = [Math.min(y0, band[0]), Math.max(y1, band[1])];
  const yOf = (y: number) => 56 - ((y - y0) / (y1 - y0 || 1)) * 52;
  const path = points.map(([x, y], index) => `${index ? "L" : "M"} ${((x - x0) / (x1 - x0 || 1)) * 300} ${yOf(y)}`).join(" ");
  return <svg className="tc-spark" viewBox="0 0 300 60" preserveAspectRatio="none" aria-hidden="true">
    {band && <rect className="tc-spark-normal" x="0" width="300" y={yOf(band[1])} height={Math.max(1, yOf(band[0]) - yOf(band[1]))} />}
    <path d={`${path} L 300 60 L 0 60 Z`} fill={color} opacity={band ? "0.08" : "0.14"} /><path d={path} stroke={color} fill="none" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
  </svg>;
}

/** The shaded band of a sparkline: the normal range, an open end reaching just past the line. */
export function sparkBand(normal: { low: number | null; high: number | null } | null | undefined, y0: number, y1: number): [number, number] | null {
  if (!normal || (normal.low === null && normal.high === null)) return null;
  const pad = (y1 - y0 || Math.abs(y1) || 1) * 0.05;
  const low = normal.low ?? Math.min(y0, normal.high as number) - pad;
  const high = normal.high ?? Math.max(y1, normal.low as number) + pad;
  return high > low ? [low, high] : null;
}

/** How several values are laid out: in a row when the card is wide, else in a column. */
function across(options: CardOptions, card: Card, count: number): boolean {
  if (options.orientation === "horizontal") return true;
  if (options.orientation === "vertical") return false;
  return card.width >= card.height * 1.5 || count <= 2 && card.width >= 4;
}

/** Stat: big numbers, one per signal (Grafana's Stat), coloured on the value or the background. */
function Stats({ card, rows, lines }: { card: Card; rows: ValueRow[]; lines?: Line[] }) {
  const options = optionsOf(card);
  const shown = rows.filter((row) => !row.error);
  if (!shown.length) return null;
  const row = across(options, card, shown.length);
  const single = shown.length === 1;
  return <div className={`tc-stats${row ? " tc-stats-row" : ""}${single ? " tc-stats-one" : ""}`} style={{ "--tc-stat-count": shown.length } as CSSProperties}>
    {shown.map((item, index) => {
      const config = effective(card, item);
      const tone = toneOf(config, item, index);
      const background = options.color_by === "background" && tone;
      const valueColour = options.color_by === "value" ? legible(tone) : undefined;
      const unit = unitOf(config, item);
      const line = options.graph === "area" ? lines?.[rows.indexOf(item)] : undefined;
      const name = config.display_name ? config.display_name : item.label;
      return <div key={index} className={`tc-stat${background ? " tc-stat-filled" : ""}`} style={background ? { background: tone, color: textOn(tone) } : undefined}>
        {options.show_name && !single && <span className="tc-stat-name" title={name}>{name}</span>}
        <div className="tc-kpi-value" style={{ color: valueColour }}>
          <b className="pc-num">{shownValue(config, item.value)}</b>
          {unit && !mappedText(config, item.value) && <span>{unit}</span>}
        </div>
        {single && <div className="tc-kpi-meta">
          {hasState(item.state) && <span className="pill" style={{ color: statusVar(stateStatus(item.state), "text"), background: statusVar(stateStatus(item.state), "soft") }}><i style={{ background: statusVar(stateStatus(item.state)) }} />{stateLabel(item.state)}</span>}
          <small>{options.show_name ? `${name} · ` : ""}{item.result ? (item.stale ? t("stale: its app has not updated it") : item.at ? formatDate(item.at) : "") : item.agg === "last" ? (item.at ? formatDate(item.at) : t("no recent value")) : `${AGG_LABELS[item.agg as "mean"]?.toLowerCase() ?? item.agg}, ${windowLabel(card.window)}`}</small>
          {item.summary && <small className="tc-kpi-summary">{item.summary}</small>}
        </div>}
        {line && <Sparkline line={line} color={background ? "currentColor" : tone ?? BRAND_COLORS[currentTheme()].series[index % 8]} normal={background ? null : normalRange(config, limitsFromSteps(config, rangeOf(item)))} />}
      </div>;
    })}
  </div>;
}

/** The value's place between the dial's ends: the field's min and max, else the signal's range,
 * else the thresholds around it. */
export function gaugeRange(config: FieldConfig, row: ValueRow): [number, number] {
  const limits = stepValues(config, rangeOf(row)).map((item) => item.value);
  const value = typeof row.value === "number" ? row.value : 0;
  let low = config.min ?? row.low ?? (limits.length ? Math.min(...limits, value) : Math.min(0, value));
  let high = config.max ?? row.high ?? (limits.length ? Math.max(...limits, value) : Math.max(100, value));
  if (!(high > low)) { low = Math.min(low, value - 1); high = Math.max(high, value + 1); }
  const span = high - low;
  if (config.min === undefined || config.min === null) if ((row.low === undefined || row.low === null) && limits.length) low -= span * 0.1;
  if (config.max === undefined || config.max === null) if ((row.high === undefined || row.high === null) && limits.length) high += span * 0.1;
  return [low, high];
}

/** A half dial: grey track, threshold bands, the value's arc in its colour. */
function GaugeDial({ card, row, index, options }: { card: Card; row: ValueRow; index: number; options: CardOptions }) {
  const config = effective(card, row);
  const [low, high] = gaugeRange(config, row);
  const value = typeof row.value === "number" ? row.value : null;
  const share = (x: number) => Math.max(0, Math.min(1, (x - low) / (high - low)));
  const point = (x: number, radius = 80) => { const angle = Math.PI * (1 - share(x)); return [100 + radius * Math.cos(angle), 100 - radius * Math.sin(angle)]; };
  const arc = (from: number, to: number) => { const [x0, y0] = point(from); const [x1, y1] = point(to); return `M ${x0} ${y0} A 80 80 0 0 1 ${x1} ${y1}`; };
  const marks = stepValues(config, rangeOf(row));
  const steps = config.thresholds?.steps?.length ? sortedSteps(config.thresholds.steps) : [];
  // Bands: each step from its value to the next one's, in its colour (the base from the low end).
  const bands: Array<[number, number, string]> = [];
  if (steps.length > 1 && options.threshold_markers) {
    const edges = [low, ...marks.map((item) => item.value), high];
    const coloured = [steps[0], ...marks.map((item) => item.step)];
    coloured.forEach((step, n) => { if (edges[n + 1] > edges[n] && (step.level !== "ok" || step.color)) bands.push([edges[n], edges[n + 1], stepColor(step)]); });
  }
  const tone = value === null ? undefined : toneOf(config, row, index) ?? BRAND_COLORS[currentTheme()].series[index % 8];
  const unit = unitOf(config, row);
  return <div className="tc-gauge">
    <svg viewBox="-16 -14 232 128" role="img" aria-label={`${row.label}: ${shownValue(config, row.value)} ${unit}`}>
      <path d={arc(low, high)} className="tc-gauge-track" />
      {bands.map(([from, to, color], n) => <path key={n} d={arc(from, Math.min(to, high))} stroke={color} className="tc-gauge-band" />)}
      {value !== null && <path d={arc(low, value)} stroke={tone} className="tc-gauge-value" />}
      {options.threshold_labels && marks.map(({ value: at }, n) => { const [x, y] = point(at, 98); return <text key={n} x={x} y={y} className="tc-gauge-end" textAnchor={x < 90 ? "end" : x > 110 ? "start" : "middle"}>{formatValue(at, config.decimals ?? (Number.isInteger(at) ? 0 : undefined))}</text>; })}
      <text x="20" y="110" className="tc-gauge-end" textAnchor="middle">{formatValue(low, Number.isInteger(low) ? 0 : config.decimals)}</text>
      <text x="180" y="110" className="tc-gauge-end" textAnchor="middle">{formatValue(high, Number.isInteger(high) ? 0 : config.decimals)}</text>
    </svg>
    <div className="tc-gauge-number"><b className="pc-num" style={{ color: legible(tone) }}>{shownValue(config, row.value)}</b>{unit && <span>{unit}</span>}</div>
    {card.items.length > 1 || row.label !== cardTitle(card) ? <small className="tc-gauge-name" title={row.label}>{config.display_name || row.label}</small> : null}
  </div>;
}

/** The setpoint of a value: a row of role SP of the same asset (a card of FIC-101 with PV and SP). */
export function setpointFor(rows: ValueRow[], row: ValueRow): number | null {
  if ((row.role ?? "").toLowerCase() === "sp") return null;
  const found = rows.find((other) => other !== row && (other.role ?? "").toLowerCase() === "sp" && (other.asset ?? null) === (row.asset ?? null) && typeof other.value === "number");
  return found ? found.value as number : null;
}

/** ISA-101 analog indicators, one per value; a setpoint row marks its PV's bar instead of its own. */
function AnalogGauges({ card, rows }: { card: Card; rows: ValueRow[] }) {
  const options = optionsOf(card);
  const paired = rows.filter((row) => (row.role ?? "").toLowerCase() !== "sp" || !rows.some((other) => other !== row && (other.asset ?? null) === (row.asset ?? null) && (other.role ?? "").toLowerCase() !== "sp"));
  return <div className={`tc-analogs${across(options, card, paired.length) ? " tc-stats-row" : ""}`} style={{ "--tc-stat-count": paired.length } as CSSProperties}>
    {paired.map((row, index) => {
      const config = effective(card, row);
      const [low, high] = gaugeRange(config, row);
      const limits = limitsFromSteps(config, rangeOf(row));
      const sp = setpointFor(rows, row);
      const value = typeof row.value === "number" ? row.value : null;
      const state = value === null ? "unknown" : row.state;
      const unit = unitOf(config, row);
      const spec = { value, min: low, max: high, limits, normal: normalRange(config, limits), sp, state };
      return <div key={index} className="tc-analog" data-state={state}>
        <div className="tc-analog-head">
          <span className="tc-analog-name" title={row.label}>{config.display_name || row.label}</span>
          <b className="pc-num">{shownValue(config, row.value)}</b>{unit && <span className="tc-analog-unit">{unit}</span>}
          {sp !== null && <small className="tc-analog-sp">SP {formatValue(sp, config.decimals ?? undefined)}</small>}
        </div>
        <svg viewBox="-8 0 216 34" role="img" aria-label={`${row.label}: ${shownValue(config, row.value)} ${unit}${sp !== null ? `, SP ${formatValue(sp, config.decimals ?? undefined)}` : ""}${hasState(state) && state !== "ok" ? `, ${stateLabel(state)}` : ""}`}>
          <AnalogBar spec={spec} width={200} height={30} decimals={config.decimals} />
        </svg>
        <div className="tc-analog-ends"><span>{formatValue(low, Number.isInteger(low) ? 0 : config.decimals)}</span><span>{formatValue(high, Number.isInteger(high) ? 0 : config.decimals)}</span></div>
      </div>;
    })}
  </div>;
}

function Gauges({ card, rows }: { card: Card; rows: ValueRow[] }) {
  const options = optionsOf(card);
  const shown = rows.filter((row) => !row.error);
  if (!shown.length) return null;
  if (options.gauge_style === "analog") return <AnalogGauges card={card} rows={shown} />;
  return <div className={`tc-gauges${across(options, card, shown.length) ? " tc-stats-row" : ""}`} style={{ "--tc-stat-count": shown.length } as CSSProperties}>
    {shown.map((row, index) => <GaugeDial key={index} card={card} row={row} index={index} options={options} />)}
  </div>;
}

/** Threshold lines (dashed, labelled at the end) and bands on a chart's value axis. */
function thresholdShapes(config: FieldConfig, horizontal: boolean, range?: { low?: number | null; high?: number | null }, extent?: number[]): { shapes: Partial<Shape>[]; annotations: Array<Record<string, unknown>> } {
  const show = config.thresholds?.show ?? "lines";
  const marks = stepValues(config, range);
  if (!marks.length || show === "off") return { shapes: [], annotations: [] };
  const shapes: Partial<Shape>[] = [];
  const annotations: Array<Record<string, unknown>> = [];
  const steps = sortedSteps(config.thresholds!.steps);
  if (show === "area" || show === "lines+area") {
    // The open ends of the first and last bands: a little past the values and thresholds drawn
    // (Plotly widens its axis to every shape, so an "infinite" band would flatten the chart).
    const seen = [...(extent ?? []), ...marks.map((item) => item.value)].filter((value) => Number.isFinite(value));
    const [least, most] = [Math.min(...seen), Math.max(...seen)];
    const pad = (most - least || Math.abs(most) || 1) * 0.04;
    const edges: number[] = [least - pad, ...marks.map((item) => item.value), most + pad];
    [steps[0], ...marks.map((item) => item.step)].forEach((step, n) => {
      if (step.level === "ok" && !step.color) return;
      const color = stepColor(step);
      const from = edges[n];
      const to = edges[n + 1];
      shapes.push(horizontal
        ? { type: "rect", xref: "x", yref: "paper", x0: from, x1: to, y0: 0, y1: 1, fillcolor: color, opacity: 0.1, line: { width: 0 }, layer: "below" }
        : { type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: from, y1: to, fillcolor: color, opacity: 0.1, line: { width: 0 }, layer: "below" });
    });
  }
  if (show === "lines" || show === "lines+area") {
    const values = marks.map((item) => item.value);
    const span = (Math.max(...values, ...(extent ?? [])) - Math.min(...values, ...(extent ?? []))) || 1;
    marks.forEach(({ value, step }, n) => {
      // Two thresholds close together: the lower one's words go under its line, not on the other's.
      const under = n + 1 < marks.length && marks[n + 1].value - value < span * 0.08;
      const color = stepColor(step);
      shapes.push(horizontal
        ? { type: "line", xref: "x", yref: "paper", x0: value, x1: value, y0: 0, y1: 1, line: { color, width: 1.2, dash: "dash" } }
        : { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: value, y1: value, line: { color, width: 1.2, dash: "dash" } });
      // The legend (round 7): each line says what it is.
      const words = `${step.level && step.level !== "none" ? t(levelLabel(step.level)) : ""} ${formatValue(value, config.decimals)}`.trim();
      annotations.push(horizontal
        ? { xref: "x", yref: "paper", x: value, y: under ? 0.9 : 1, text: words, showarrow: false, xanchor: under ? "right" : "left", yanchor: "top", font: { size: 10, color } }
        : { xref: "paper", yref: "y", x: 1, y: value, text: words, showarrow: false, xanchor: "right", yanchor: under ? "top" : "bottom", font: { size: 10, color } });
    });
  }
  return { shapes, annotations };
}

/** Bar gauges (Grafana's bar gauge): each value a bar filled from min to max in its colour. */
function BarGauges({ card, rows, vertical }: { card: Card; rows: ValueRow[]; vertical: boolean }) {
  return <div className={`tc-bargauges${vertical ? " tc-bargauges-v" : ""}`}>
    {rows.map((row, index) => {
      const config = effective(card, row);
      const [low, high] = gaugeRange(config, row);
      const value = typeof row.value === "number" ? row.value : null;
      const share = value === null ? 0 : Math.max(0, Math.min(1, (value - low) / (high - low)));
      const color = valueColor(config, row.value, index, rangeOf(row));
      return <div key={index} className="tc-bargauge" title={`${row.label}: ${shownValue(config, row.value)} ${unitOf(config, row)}`}>
        <span className="tc-bargauge-name">{config.display_name || row.label}</span>
        <span className="tc-bargauge-track"><i style={vertical ? { height: `${share * 100}%`, background: color } : { width: `${share * 100}%`, background: color }} /></span>
        <b className="pc-num" style={{ color: legible(color) }}>{shownValue(config, row.value)}<small>{unitOf(config, row)}</small></b>
      </div>;
    })}
  </div>;
}

function Bars({ card, rows, height }: { card: Card; rows: ValueRow[]; height?: number }) {
  const options = optionsOf(card);
  const theme = plotTheme();
  let shown = rows.filter((row) => typeof row.value === "number");
  if (!shown.length) return <p className="muted tc-empty">{t("No values in this window.")}</p>;
  if (options.sort !== "none") shown = [...shown].sort((a, b) => ((a.value as number) - (b.value as number)) * (options.sort === "asc" ? 1 : -1));
  const horizontal = options.orientation === "horizontal" || (options.orientation === "auto" && (shown.length > 6 || card.width < card.height * 2));
  if (options.bar_style === "gauge") return <BarGauges card={card} rows={shown} vertical={!horizontal} />;
  const configs = shown.map((row) => effective(card, row));
  const colors = shown.map((row, index) => valueColor(configs[index], row.value, index, rangeOf(row)));
  const labels = shown.map((row, index) => configs[index].display_name || row.label);
  const text = shown.map((row, index) => `${shownValue(configs[index], row.value)} ${unitOf(configs[index], row)}`.trim());
  const values = shown.map((row) => row.value as number);
  const textposition = options.value_labels === "never" ? "none" : options.value_labels === "always" ? "outside" : "auto";
  // Labels inside a bar in the colour that reads on it; outside, the theme's text.
  const insidetextfont = { color: colors.map((color) => textOn(color) ?? "#ffffff") };
  const data: Data[] = [horizontal
    ? { type: "bar", orientation: "h", y: labels, x: values, marker: { color: colors }, text, textposition, insidetextfont, hovertemplate: "%{y}: %{text}<extra></extra>", cliponaxis: false }
    : { type: "bar", x: labels, y: values, marker: { color: colors }, text, textposition, insidetextfont, hovertemplate: "%{x}: %{text}<extra></extra>", cliponaxis: false }];
  const field = card.field ?? {};
  const range = field.min !== undefined && field.min !== null && field.max !== undefined && field.max !== null ? [field.min, field.max] : undefined;
  const marks = thresholdShapes(field, horizontal, rangeOf(shown[0]), [0, ...values]);
  const valueAxis = { ...theme.xaxis, range, title: options.y_label ? { text: options.y_label, font: { size: 10 } } : undefined };
  const layout = horizontal
    ? { ...theme, height: height ?? plotHeight(card.height), margin: { l: 8, r: 16, t: 14, b: 26 }, yaxis: { ...theme.yaxis, autorange: "reversed" as const, automargin: true }, xaxis: valueAxis, shapes: marks.shapes, annotations: marks.annotations, showlegend: false }
    : { ...theme, height: height ?? plotHeight(card.height), margin: { l: 40, r: 12, t: 14, b: 34 }, xaxis: { ...theme.xaxis, automargin: true }, yaxis: { ...theme.yaxis, ...valueAxis }, shapes: marks.shapes, annotations: marks.annotations, showlegend: false };
  return <Plot data={data} layout={layout} config={plotConfig(Boolean(height))} useResizeHandler style={{ width: "100%" }} />;
}

const COLUMN_LABELS: Record<string, string> = { last: "Last", mean: "Mean", min: "Min", max: "Max", std: "Std dev", unit: "Unit", time: "Time", state: "State" };

function Table({ card, rows }: { card: Card; rows: CardData["rows"] }) {
  const options = optionsOf(card);
  const columns = options.columns;
  return <div className="tc-table-wrap"><table className="table tc-table">
    <thead><tr><th>{t("Signal")}</th>{columns.map((column) => <th key={column}>{t(COLUMN_LABELS[column])}</th>)}</tr></thead>
    <tbody>{(rows ?? []).map((row, index) => {
      const config = effective(card, row);
      const last = row.values?.last;
      const colour = valueColor(config, last, index, rangeOf(row));
      const coloured = Boolean(config.thresholds?.steps?.length || config.mappings?.length || config.color_mode === "fixed") || (row.result && hasState(row.state));
      const tone = row.result ? statusVar(stateStatus(row.state), "text") : colour;
      const rowStyle = options.row_color && (row.state === "alarm" || row.state === "warning") ? { background: statusVar(stateStatus(row.state), "soft") } : undefined;
      const [low, high] = gaugeRange(config, { ...row, value: typeof last === "number" ? last : null } as ValueRow);
      const share = typeof last === "number" ? Math.max(0, Math.min(1, (last - low) / (high - low))) : 0;
      return <tr key={index} style={rowStyle}>
        <td><b>{config.display_name || row.label}</b>{!columns.includes("unit") && unitOf(config, row) && <small>{unitOf(config, row)}</small>}</td>
        {columns.map((column) => {
          if (column === "unit") return <td key={column}>{unitOf(config, row)}</td>;
          if (column === "time") return <td key={column} className="pc-num">{row.at ? formatDate(row.at) : "—"}</td>;
          if (column === "state") return <td key={column}>{hasState(row.state) ? <span className="pill" style={{ color: statusVar(stateStatus(row.state), "text"), background: statusVar(stateStatus(row.state), "soft") }}><i style={{ background: statusVar(stateStatus(row.state)) }} />{stateLabel(row.state)}</span> : "—"}</td>;
          const value = row.values?.[column as "last"];
          const text = row.error ? "—" : shownValue(config, value);
          if (column === "last" && options.cell === "bar") return <td key={column} className="pc-num tc-cell-bar"><span><i style={{ width: `${share * 100}%`, background: coloured ? tone : BRAND_COLORS[currentTheme()].series[index % 8] }} /></span>{text}</td>;
          if (column !== "last" || !coloured || options.cell === "text" || last === null || last === undefined) return <td key={column} className="pc-num">{text}</td>;
          if (options.cell === "color_background") return <td key={column} className="pc-num tc-cell-filled" style={{ background: tone, color: textOn(tone) }}>{text}</td>;
          return <td key={column} className="pc-num" style={{ color: legible(tone, 4.5), fontWeight: 700 }}>{text}</td>;
        })}
      </tr>;
    })}</tbody>
  </table></div>;
}

/** Plotly line shape of an interpolation. */
const SHAPES = { linear: "linear", smooth: "spline", step: "hv" } as const;

function lineStats(line: Line) {
  const values = line.v.filter((value): value is number => typeof value === "number");
  if (!values.length) return { last: null, mean: null, min: null, max: null };
  return { last: values[values.length - 1], mean: values.reduce((a, b) => a + b, 0) / values.length, min: Math.min(...values), max: Math.max(...values) };
}

function Trend({ card, lines, range, height }: { card: Card; lines: Line[]; range: CardData["range"]; height?: number }) {
  const options = optionsOf(card);
  const theme = plotTheme();
  const cursor = useSharedCursor();
  const drawn = lines.filter((line) => line.t.length);
  if (!drawn.length) return <p className="muted tc-empty">{t("No samples in this window.")}</p>;
  const configs = drawn.map((line) => effective(card, line));
  const units = [...new Set(drawn.map((line, index) => unitOf(configs[index], line)))];
  // Axis: the line's own choice, else by unit (one unit left, two: one axis each).
  const axisOf = (index: number) => {
    const chosen = configs[index].axis;
    if (chosen === "left" || chosen === "right" || chosen === "hidden") return chosen;
    return units.length === 2 && unitOf(configs[index], drawn[index]) === units[1] ? "right" : "left";
  };
  const right = drawn.some((_, index) => axisOf(index) === "right");
  const seriesColors = BRAND_COLORS[currentTheme()].series;
  const marks = cursor?.at && cursor.from !== card.card_id ? [cursorShape(cursor.at, String((theme.xaxis as { color?: string })?.color ?? "#888"))] : [];
  const stacked = options.stack !== "none";
  const data: Data[] = [];
  drawn.forEach((line, index) => {
    const config = configs[index];
    const color = config.color_mode === "fixed" || config.color ? colorOf(config.color ?? "blue") : seriesColors[index % 8];
    const unit = unitOf(config, line);
    const name = config.display_name || line.label;
    const draw = config.draw ?? "lines";
    const axis = axisOf(index) === "right" ? "y2" : "y";
    const fill = config.fill ?? 0;
    const base = {
      name: unit ? `${name} (${unit})` : name, x: line.t, y: line.v, yaxis: axis, connectgaps: options.connect_gaps,
      hovertemplate: `%{y:.4~g} ${unit}<extra>${name}</extra>`, visible: axisOf(index) === "hidden" ? ("legendonly" as const) : true,
    };
    if (draw === "bars") data.push({ ...base, type: "bar", marker: { color, opacity: 0.85 } });
    else data.push({
      ...base, type: "scatter",
      mode: draw === "points" ? "markers" : draw === "lines+points" ? "lines+markers" : "lines",
      line: { width: config.line_width ?? 1.6, shape: SHAPES[config.interpolation ?? "linear"], color, dash: config.dash ?? "solid" },
      marker: { size: 4, color },
      ...(stacked ? { stackgroup: axis, groupnorm: options.stack === "percent" ? ("percent" as const) : undefined, fill: "tonexty" as const } : fill > 0 ? { fill: "tozeroy" as const, fillcolor: `${color}${Math.round(fill * 2.55).toString(16).padStart(2, "0")}` } : {}),
    });
    // Coloured by thresholds: the stretches past a threshold drawn again in its colour.
    if (config.color_mode === "thresholds" && config.thresholds?.steps?.length && draw !== "bars" && !stacked) {
      const steps = sortedSteps(config.thresholds.steps);
      steps.forEach((step, n) => {
        if (n === 0 && step.level === "ok" && !step.color) return;
        const y = line.v.map((value, at) => {
          const found = stepOf(config.thresholds, value, config.min ?? line.low, config.max ?? line.high);
          const next = line.v[at + 1] ?? null;
          const nextStep = stepOf(config.thresholds, next, config.min ?? line.low, config.max ?? line.high);
          return found === step || nextStep === step ? value : null;
        });
        if (y.some((value) => value !== null)) data.push({ type: "scatter", mode: "lines", x: line.t, y, yaxis: axis, showlegend: false, hoverinfo: "skip", connectgaps: false, line: { width: (config.line_width ?? 1.6) + 0.6, color: stepColor(step), shape: SHAPES[config.interpolation ?? "linear"] } });
      });
    }
  });
  const field = card.field ?? {};
  const fixed = field.min !== undefined && field.min !== null && field.max !== undefined && field.max !== null ? [field.min, field.max] : undefined;
  const soft = !fixed && (options.soft_min !== null || options.soft_max !== null || field.min !== null && field.min !== undefined || field.max !== null && field.max !== undefined);
  const leftValues = drawn.filter((_, index) => axisOf(index) === "left").flatMap((line) => line.v.filter((value): value is number => typeof value === "number"));
  const thresholds = thresholdShapes(field, false, rangeOf(drawn[0]), leftValues.length ? [Math.min(...leftValues), Math.max(...leftValues)] : []);
  const legendShown = options.legend !== "hidden" && drawn.length > 1;
  const legendRight = options.legend_place === "right";
  const tableLegend = options.legend === "table" || options.legend_values.length > 0;
  const yTitle = options.y_label || (units.length <= 2 ? units[0] ?? "" : "");
  const layout = {
    ...theme,
    height: (height ?? plotHeight(card.height)) - (legendShown && tableLegend && !legendRight ? Math.min(140, 22 + drawn.length * 20) : 0),
    margin: { l: 44, r: right ? 44 : 12, t: 8, b: 28 },
    showlegend: legendShown && !tableLegend,
    legend: { ...theme.legend, ...(legendRight ? { orientation: "v" as const, x: 1.02, y: 1, xanchor: "left" as const } : { orientation: "h" as const, y: 1.02, yanchor: "bottom" as const, x: 0 }) },
    xaxis: { ...theme.xaxis, type: "date" as const, range: range ? [range.start, range.end] : undefined },
    yaxis: {
      ...theme.yaxis, type: options.y_scale === "log" ? ("log" as const) : ("linear" as const), title: { text: yTitle, font: { size: 10 } },
      ...(fixed && options.y_scale !== "log" ? { range: fixed, autorange: false } : {}),
      ...(soft && options.y_scale !== "log" ? { autorangeoptions: { include: [options.soft_min ?? field.min, options.soft_max ?? field.max].filter((value): value is number => typeof value === "number") } } : {}),
    },
    ...(right ? { yaxis2: { ...theme.yaxis, overlaying: "y" as const, side: "right" as const, title: { text: units[1] ?? "", font: { size: 10 } }, showgrid: false } } : {}),
    shapes: [...thresholds.shapes, ...marks],
    annotations: thresholds.annotations,
    hovermode: options.tooltip === "hidden" ? (false as const) : options.tooltip === "single" ? ("closest" as const) : ("x unified" as const),
    barmode: stacked ? ("stack" as const) : ("group" as const),
  };
  const hover = cursor ? {
    onHover: (event: Readonly<PlotHoverEvent>) => { const at = event.points?.[0]?.x; if (at !== undefined) cursor.set(String(at), card.card_id); },
    onUnhover: () => cursor.set(null, card.card_id),
  } : {};
  const plot = <Plot data={data} layout={layout} config={plotConfig(Boolean(height))} useResizeHandler style={{ width: "100%", flex: "none" }} {...hover} />;
  if (!legendShown || !tableLegend) return plot;
  const wanted = options.legend_values.length ? options.legend_values : (["last"] as const);
  const legend = <div className="tc-legend-wrap"><table className="tc-legend-table">
    <thead><tr><th>{t("Signal")}</th>{wanted.map((value) => <th key={value}>{t(COLUMN_LABELS[value])}</th>)}</tr></thead>
    <tbody>{drawn.map((line, index) => {
      const stats = lineStats(line);
      const color = configs[index].color ? colorOf(configs[index].color) : seriesColors[index % 8];
      return <tr key={index}><td><i style={{ background: color }} />{configs[index].display_name || line.label}</td>{wanted.map((value) => <td key={value} className="pc-num">{formatValue(stats[value], configs[index].decimals)}</td>)}</tr>;
    })}</tbody>
  </table></div>;
  return <div className={`tc-trend-with-legend${legendRight ? " tc-legend-right" : ""}`}>{plot}{legend}</div>;
}

/** One signal against another on the same grid: x is the first, y the second. */
function Scatter({ card, lines, height }: { card: Card; lines: Line[]; height?: number }) {
  const options = optionsOf(card);
  const theme = plotTheme();
  const [x, y] = lines;
  if (!x || !y || !x.t.length || !y.t.length) return <p className="muted tc-empty">{t("No samples in this window.")}</p>;
  const byTime = new Map(y.t.map((time, index) => [time, y.v[index]]));
  const pairs = x.t.map((time, index) => [x.v[index], byTime.get(time), time] as const).filter((pair) => typeof pair[0] === "number" && typeof pair[1] === "number");
  if (!pairs.length) return <p className="muted tc-empty">{t("The two signals have no samples at the same times.")}</p>;
  const name = (line: Line) => (line.unit ? `${line.label} (${line.unit})` : line.label);
  const config = effective(card, y);
  const fixedColor = config.color_mode === "fixed" || config.color ? colorOf(config.color ?? "blue") : null;
  const data: Data[] = [{
    type: "scatter", mode: "markers", x: pairs.map((pair) => pair[0] as number), y: pairs.map((pair) => pair[1] as number), text: pairs.map((pair) => formatDate(pair[2])),
    marker: fixedColor ? { size: options.point_size, opacity: 0.7, color: fixedColor } : { size: options.point_size, opacity: 0.7, color: pairs.map((_, index) => index), colorscale: timeScale(), showscale: false },
    hovertemplate: `${x.label} %{x:.4~g}<br>${y.label} %{y:.4~g}<br>%{text}<extra></extra>`,
  }];
  const yRange = config.min !== undefined && config.min !== null && config.max !== undefined && config.max !== null ? [config.min, config.max] : undefined;
  return <Plot data={data} layout={{ ...theme, height: height ?? plotHeight(card.height), margin: { l: 48, r: 12, t: 8, b: 40 }, showlegend: false, xaxis: { ...theme.xaxis, title: { text: name(x), font: { size: 10 } } }, yaxis: { ...theme.yaxis, range: yRange, title: { text: name(y), font: { size: 10 } } } }} config={plotConfig(Boolean(height))} useResizeHandler style={{ width: "100%" }} />;
}

/** The drawing of a card from its data (no reads here): used by the grid and the editor's preview. */
export function CardBody({ card, data, height, texts = {} }: { card: Card; data: CardData; height?: number; texts?: Record<string, string[]> }) {
  const rows = data.rows ?? [];
  const items = data.lines && card.kind !== "stat" ? data.lines : rows;
  // Charts leave room for the lines under them (signals that failed, the shifted window note).
  const below = items.filter((item) => item.error).length * 20 + (data.range?.shifted ? 34 : 0);
  if (!height && below) height = Math.max(80, plotHeight(card.height) - below);
  if (card.kind === "text") return <div className="tc-text markdown">{renderMarkdown(interpolate(card.text ?? "", texts))}</div>;
  if (card.kind === "diagram") return <DiagramCardBody data={data} />;
  if (card.kind === "apc") return <ApcPanel data={data.apc} />;
  return <>
    {card.kind === "stat" && <Stats card={card} rows={rows} lines={data.lines} />}
    {card.kind === "gauge" && <Gauges card={card} rows={rows} />}
    {card.kind === "bar" && <Bars card={card} rows={rows} height={height} />}
    {card.kind === "table" && <Table card={card} rows={rows} />}
    {card.kind === "trend" && <Trend card={card} lines={data.lines ?? []} range={data.range} height={height} />}
    {card.kind === "scatter" && <Scatter card={card} lines={data.lines ?? []} height={height} />}
    {data.range?.shifted && <p className="tc-note">{t("No samples in the last {window}: showing the newest data, up to {end}.", { window: windowLabel(data.window), end: formatDate(data.range.end) })}</p>}
    <Problems items={items} />
  </>;
}

/** Saves the data a card is showing as a CSV file, as read (no new request). */
function saveCsv(card: Card, data: CardData) {
  saveFile(cardCsvName(card, data), new Blob(["﻿", cardCsv(data)], { type: "text/csv;charset=utf-8" }));
}

export function CardView({ card, source, vars, texts = {}, window, tick, actions, editing = false, copy = false }: {
  card: Card; source: CardSource; vars: Record<string, string[]>; texts?: Record<string, string[]>; window: string | null; tick: number;
  actions?: ReactNode; editing?: boolean;
  /** A repeated copy (not the card itself): it reads the same but is not edited apart. */
  copy?: boolean;
}) {
  const key = `${card.card_id}|${JSON.stringify(vars)}|${window}|${JSON.stringify({ ...card, x: 0, y: 0 })}`;
  const text = card.kind === "text";
  const { data, error, loading } = useCardData(() => (text ? Promise.resolve({ card_id: card.card_id, kind: card.kind, window: card.window, read_at: new Date().toISOString() }) : source.card(card.card_id, vars, window)), key, tick);
  const [full, setFull] = useState(false);
  const plotted = ["trend", "bar", "scatter"].includes(card.kind);
  useEffect(() => {
    if (!full) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setFull(false); };
    globalThis.addEventListener("keydown", close);
    return () => globalThis.removeEventListener("keydown", close);
  }, [full]);
  // A diagram card without a title of its own takes the diagram's name.
  const title = card.kind === "diagram" && !card.title.trim() && data?.diagram ? data.diagram.name : cardTitle(card, texts);
  const shownWindow = data?.window ?? window ?? card.window;
  return <article className={`tc-card${card.height === 1 ? " tc-h1" : ""}${text ? " tc-card-text" : ""}${editing ? " tc-card-editing" : ""}`} style={{ "--tc-px": `${cardPixels(card.height)}px` } as CSSProperties} data-card={card.card_id} data-kind={card.kind}>
    <header className={editing && !copy ? "pc-cards-handle" : undefined}>
      {editing && !copy && <GripVertical size={14} className="tc-grip" aria-hidden="true" />}
      <h2 title={card.description ? `${title}\n${card.description}` : title}>{title}</h2>
      <span className="tc-card-meta">{loading && !text && <LoaderCircle size={13} className="spin" />}
        {card.repeat && <Repeat2 size={13} aria-label={t("Repeats for each {name}", { name: card.repeat.variable })} />}
        {!["stat", "gauge", "text"].includes(card.kind) && <small>{windowLabel(shownWindow)}</small>}
        {data && !error && !text && card.kind !== "diagram" && !editing && <button type="button" className="tc-card-csv" title={t("Download this panel's data (CSV)")} aria-label={t("Download this panel's data (CSV)")} onClick={() => saveCsv(card, data)}><Download size={13} /></button>}
        {data && !error && plotted && !editing && <button type="button" className="tc-card-csv" title={t("Full screen")} aria-label={t("Full screen")} onClick={() => setFull(true)}><Maximize2 size={13} /></button>}
        {!copy && actions}</span>
    </header>
    <div className="tc-card-body">
      {error ? <div className="tc-card-error" role="alert"><AlertTriangle size={15} /> {error}</div>
        : data ? <CardBody card={card} data={data} texts={texts} />
        : <div className="tc-card-loading"><LoaderCircle className="spin" /></div>}
    </div>
    {full && data && <div className="tc-full" role="dialog" aria-modal="true" aria-label={title}>
      <header><h2>{title}</h2><small>{windowLabel(shownWindow)}</small><button type="button" className="icon-button" onClick={() => setFull(false)} aria-label={t("Close full screen")}><X size={18} /></button></header>
      <CardBody card={card} data={data} texts={texts} height={Math.max(320, globalThis.innerHeight - 120)} />
    </div>}
  </article>;
}
