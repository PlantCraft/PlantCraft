/**
 * Compare versions (owner D18, 2026-10-26): on a block's or an algorithm's Versions tab, tick two
 * or three versions; the Compare tab runs each one on the same asset and the same data window and
 * shows what they read once, then each version's outputs side by side: values in columns, series
 * drawn on one chart, one line per version. Nothing is saved.
 */
import { ComparePicker as SuitePicker, plotTheme } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import type { Diagram, DiagramTrace, TraceValue } from "@plantcraft/ui/blockEditor";
import { formatDate, t } from "./i18n";
import { navigate } from "./nav";
import { resultLabel } from "./status";
import type { AlgorithmOutput } from "./types";
import { Pill } from "./ui";

/** Under the versions list: the suite's picker; Compare opens the Compare tab with them. */
export function ComparePicker({ numbers, base }: { numbers: number[]; base: string }) {
  return <SuitePicker numbers={numbers} text={t("Tick two or three versions: they run on the same asset and the same data, and their outputs show side by side.")}
    onCompare={(ticked) => navigate(`${base}/compare?versions=${ticked.join(",")}`)} />;
}

/** One thing the versions gave, a value per version (undefined: that version has no such output). */
export type CompareRow = { key: string; label: string; values: (TraceValue | undefined)[] };
export type Comparison = { inputs: CompareRow[]; values: CompareRow[]; series: CompareRow[] };

function outputValue(item: AlgorithmOutput | undefined): TraceValue | undefined {
  if (!item) return undefined;
  return { type: "result", status: item.status, value: item.value, message: item.message || item.text || "" };
}

/**
 * What a comparison of algorithm versions shows, from each version's diagram and test: the
 * signals read (from the first version: the data is the same), each output's verdict, and each
 * series the version records in the Historian.
 */
export function algorithmComparison(runs: Array<{ diagram: Diagram; trace?: DiagramTrace; outputs?: AlgorithmOutput[] }>): Comparison {
  const first = runs[0];
  const inputs: CompareRow[] = (first?.diagram.nodes ?? [])
    .filter((node) => node.block.startsWith("input."))
    .flatMap((node) => Object.entries(first.trace?.[node.id] ?? {}).map(([port, value]) => ({ key: `${node.id}.${port}`, label: `${node.label || String(node.parameters?.role ?? node.parameters?.signal ?? node.id)} · ${port}`, values: [value] })));
  const keys = new Map<string, string>();
  for (const run of runs) for (const item of run.outputs ?? []) if (!keys.has(item.key)) keys.set(item.key, item.name || item.key);
  const values = [...keys].map(([key, label]) => ({ key, label, values: runs.map((run) => outputValue((run.outputs ?? []).find((item) => item.key === key))) }));
  const recorded = new Map<string, string>();
  for (const run of runs) for (const node of run.diagram.nodes) for (const port of node.record ?? []) recorded.set(`${node.id}.${port}`, `${node.label || node.id} · ${port}`);
  const series = [...recorded].map(([key, label]) => {
    const [node, port] = [key.slice(0, key.lastIndexOf(".")), key.slice(key.lastIndexOf(".") + 1)];
    return { key, label, values: runs.map((run) => run.trace?.[node]?.[port]) };
  });
  return { inputs, values, series };
}

/** What a comparison of block versions shows: the inputs once (the first answer), then each
 * output port, a value or verdict in a column per version, a series on one chart. */
export function blockComparison(answers: Array<{ inputs?: Record<string, TraceValue>; outputs?: Record<string, TraceValue> }>, labels: Record<string, string> = {}): Comparison {
  const label = (port: string) => labels[port] || port;
  const inputs = Object.entries(answers[0]?.inputs ?? {}).map(([port, value]) => ({ key: port, label: label(port), values: [value] }));
  const ports = [...new Set(answers.flatMap((answer) => Object.keys(answer.outputs ?? {})))];
  const rows = ports.map((port) => ({ key: port, label: label(port), values: answers.map((answer) => answer.outputs?.[port]) }));
  const isSeries = (row: CompareRow) => row.values.some((value) => value?.type === "series" || value?.type === "state");
  return { inputs, values: rows.filter((row) => !isSeries(row)), series: rows.filter(isSeries) };
}

/** A value as a cell: a verdict, a number, a series' last value, or why there is none. */
function Cell({ value }: { value: TraceValue | undefined }) {
  if (!value) return <span className="muted">{t("Not in this version")}</span>;
  switch (value.type) {
    case "result":
      return <span className="compare-result"><Pill status={value.status} label={resultLabel(value.status)} />{value.value !== null && <b className="pc-num">{Math.round(value.value * 100) / 100}</b>}<small>{value.message}</small></span>;
    case "number":
      return <b className="pc-num">{value.value.toLocaleString(undefined, { maximumFractionDigits: 6 })}</b>;
    case "series":
    case "state":
      return <span className="pc-num">{t("{count} values, last {value}", { count: value.count, value: value.last ?? "—" })}</span>;
    case "missing":
      return <span className="muted">{value.reason}</span>;
    default:
      return <span className="muted">—</span>;
  }
}

/** Whether a row has samples to draw (a series with points in some version). */
export function hasSamples(row: CompareRow): boolean {
  return row.values.some((value) => (value?.type === "series" || value?.type === "state") && value.t.length > 0);
}

/** One chart, one line per version, for a series output. */
function Overlay({ row, columns }: { row: CompareRow; columns: string[] }) {
  const data = row.values.flatMap((value, index) => (value && (value.type === "series" || value.type === "state")
    ? [{ x: value.t, y: value.v, type: "scatter" as const, mode: "lines" as const, name: columns[index], line: { width: 1.5, shape: value.type === "state" ? "hv" as const : "linear" as const } }]
    : []));
  if (!data.length) return <p className="muted small">{t("No samples in this window.")}</p>;
  return <Plot data={data} layout={{ ...plotTheme(), autosize: true, height: 220, margin: { l: 48, r: 12, t: 8, b: 32 }, showlegend: true, legend: { orientation: "h", y: -0.2 } }}
    config={{ displaylogo: false, displayModeBar: false, responsive: true }} style={{ width: "100%" }} useResizeHandler />;
}

/** The comparison: the window and what was read, then each output, one column per version. */
export function CompareView({ columns, comparison, window: span, subject }: { columns: string[]; comparison: Comparison; window?: { start: string; end: string } | null; subject?: string }) {
  const table = (rows: CompareRow[], label: string, many: boolean) => <div className="blk-table-wrap"><table className="table compare-table">
    <thead><tr><th scope="col">{label}</th>{(many ? columns : [t("Same for every version")]).map((name) => <th key={name} scope="col">{name}</th>)}</tr></thead>
    <tbody>{rows.map((row) => <tr key={row.key}><th scope="row">{row.label}</th>{row.values.map((value, index) => <td key={index}><Cell value={value} /></td>)}</tr>)}</tbody>
  </table></div>;
  return <div className="compare-view">
    <p className="muted">{t("{subject}, the same data for every version: {start} to {end}.", { subject: subject ?? "", start: formatDate(span?.start), end: formatDate(span?.end) })}</p>
    {comparison.inputs.length > 0 && <section className="panel" aria-label={t("What they read")}>
      <div className="panel-header"><div><h2>{t("What they read")}</h2><p>{t("The inputs, once: every version read the same data.")}</p></div></div>
      {table(comparison.inputs, t("Input"), false)}
      {comparison.inputs.some(hasSamples) && <div className="pc-grid pc-grid-2 compare-charts">
        {comparison.inputs.filter(hasSamples).map((row) => <div key={row.key}><h3>{row.label}</h3><Overlay row={row} columns={[t("Read")]} /></div>)}
      </div>}
    </section>}
    {comparison.values.length > 0 && <section className="panel" aria-label={t("What each version said")}>
      <div className="panel-header"><div><h2>{t("What each version said")}</h2><p>{t("Each output, one column per version.")}</p></div></div>
      {table(comparison.values, t("Output"), true)}
    </section>}
    {comparison.series.length > 0 && <section className="panel" aria-label={t("Signals")}>
      <div className="panel-header"><div><h2>{t("Signals")}</h2><p>{t("Each signal an output gives, one line per version.")}</p></div></div>
      {table(comparison.series, t("Signals"), true)}
      <div className="compare-charts">{comparison.series.filter(hasSamples).map((row) => <div key={row.key}><h3>{row.label}</h3><Overlay row={row} columns={columns} /></div>)}</div>
    </section>}
  </div>;
}
