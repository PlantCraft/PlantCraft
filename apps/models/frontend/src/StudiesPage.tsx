/**
 * `/studies`: every study; `/studies/<id>`: one study on one page (no tabs).
 * Its runs ranked by the indicator chosen, the best first; their results overlaid, coloured by a
 * varied parameter, with the envelope of all of them; an indicator against a parameter; the runs
 * themselves; the settings; the statistics; and the export for Jupyter.
 */
import type * as Plotly from "plotly.js";
import { chosenFolder, DataTable, Pill, FolderColumn, FolderField, folderName, FolderPlaceLine, inFolder, newInFolder, putInFolder, rememberFolder, useAssistantPage, useFolders, confirmAction, currentTheme, magnitudeScale, plotTheme, seriesVar, type DataColumn } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import { CopyPlus, Download, FlaskConical, Plus, Square, Trash2, Trophy } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { api } from "./api";
import { formatAgo, formatDate, formatDuration, t } from "./i18n";
import { navigate } from "./nav";
import { modelPath, runPath, studyRunPath } from "./paths";
import { diagramParameters, scopeSignals } from "./SimulationSettings";
import { StudyForm, sweptLabel, type StudyParameter } from "./StudyForm";
import type { ClassInfo, Me, ModelItem, Run, SimSettings, StatisticRow, Study, StudySeries, StudySpec } from "./types";
import { Dialog, ErrorBox, Heading, Link, Loading, message, Progress, reading, RUN_WORDS, RunPill, STUDY_WORDS, StudyProgress, variantText } from "./ui";

export const STATISTICS = ["final", "overshoot", "settling", "iae", "min", "max", "mean", "integral"] as const;
export const STATISTIC_WORDS: Record<string, string> = {
  final: "Final value", overshoot: "Overshoot (%)", settling: "Settling time (s)", iae: "IAE (integral of |deviation|)",
  min: "Smallest", max: "Largest", mean: "Mean", integral: "Integral",
};
/** Whether a smaller value of the statistic is the better run (an overshoot, a settling time). */
export const SMALLER_IS_BETTER: Record<string, boolean> = { overshoot: true, settling: true, iae: true };

/** Whether the study still runs: simulations waiting or running, or an optimizer choosing the next. */
const active = (study: Pick<Study, "queued" | "running" | "optimization">) => study.queued + study.running > 0
  || study.optimization?.status === "running" || study.optimization?.status === "waiting";

/** Studies in the suite's table. */
export function StudiesTable({ studies }: { studies: Study[] }) {
  const columns: DataColumn<Study>[] = [
    { key: "name", label: t("Study"), sort: (study) => study.name, render: (study) => <><strong>{study.name}</strong>{study.description && <small>{study.description}</small>}</> },
    { key: "model", label: t("Model"), sort: (study) => study.model, render: (study) => study.model.split(".").pop(),
      filter: { value: (study) => study.model, options: [...new Set(studies.map((study) => study.model))].sort().map((value) => ({ value, label: value.split(".").pop() ?? value })) } },
    { key: "progress", label: t("Simulations"), sort: (study) => study.total, render: (study) => <StudyProgress study={study} /> },
    { key: "last", label: t("Last simulation"), sort: (study) => study.last_run_at ?? study.created_at, render: (study) => <span className="nowrap">{formatAgo(study.last_run_at ?? study.created_at)}<small>{study.created_by}</small></span> },
  ];
  return <DataTable rows={studies} columns={columns} rowKey={(study) => study.id} label={t("Studies")}
    searchText={(study) => [study.name, study.model, study.description, study.created_by].join(" ")}
    searchPlaceholder={t("Search study or model")} initialSort={{ key: "last", descending: true }}
    empty={t("No study matches these filters.")} onRowClick={(study) => navigate(`/studies/${study.id}`)} />;
}

export function StudiesPage({ me }: { me: Me }) {
  const [studies, setStudies] = useState<Study[] | null>(null);
  const [error, setError] = useState("");
  // Folders (round 9, M5), as Link's; the filter by model stays in the table.
  const [folders, reloadFolders] = useFolders("study");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  useEffect(() => {
    const load = () => api.studies().then((found) => setStudies(found.filter((study) => study.kind !== "quick"))).catch((err) => setError(message(err)));
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, []);
  // Models' work here (app.toml): ask about the studies.
  useAssistantPage({ place: t("Models › Studies"), page: "modelcraft:studies", facts: { studies: studies?.length ?? 0 },
    view: { studies: (studies ?? []).slice(0, 40).map((study) => `${study.name.slice(0, 80)} (${study.kind}, model ${study.model}${study.last_run_at ? `, last run ${study.last_run_at}` : ""})`) } });
  if (error) return <ErrorBox text={error} />;
  if (!studies) return <Loading />;
  return <>
    <Heading title={t("Studies")} actions={<Link to={newInFolder("/studies/new", folder)} className="button button-primary"><Plus />{t("New study")}</Link>} />
    {studies.length === 0 ? <div className="panel empty"><FlaskConical /><h2>{t("No study yet")}</h2><p className="muted">{t("Press New study and choose a model.")}</p></div>:
      <div className="pc-folder-layout">
        <FolderColumn kind="study" list={folders} chosen={folder} onChoose={(value) => { setFolder(value); rememberFolder("/studies", value); }} total={studies.length} canEdit={me.can_edit} onChanged={reloadFolders} />
        <section>
          {folder && <div className="pc-folder-head"><h2>{folderName(folders, folder)}</h2></div>}
          <StudiesTable studies={studies.filter((study) => inFolder(folders, study.id, folder))} />
        </section>
      </div>}
  </>;
}

/** A colour for a share 0..1 of a varied parameter's range: light for the smallest value, deep for the largest. */
function rampColor(share: number): string {
  const stops = magnitudeScale(currentTheme());
  const at = 0.3 + 0.7 * Math.max(0, Math.min(1, share));
  for (let index = 1; index < stops.length; index += 1) {
    const [x1, c1] = stops[index];
    const [x0, c0] = stops[index - 1];
    if (at <= x1) {
      const mix = x1 === x0 ? 0 : (at - x0) / (x1 - x0);
      const channel = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
      return `rgb(${[0, 1, 2].map((i) => Math.round(channel(c0, i) + (channel(c1, i) - channel(c0, i)) * mix)).join(",")})`;
    }
  }
  return stops[stops.length - 1][1];
}

/** The variables a study's results hold, read from its first finished run (round 9 M10: any of
 * them is measured and drawn, not only those named when it started). */
function useVariables(runs: Run[]): string[] {
  const first = runs.find((run) => run.status === "done")?.id;
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    if (!first) return;
    api.variables(first).then((found) => setNames(found.filter((item) => item.column !== null && !item.protected && !item.name.startsWith("der(") && !item.name.startsWith("$") && !item.constant && item.name !== "time").map((item) => item.name)))
      .catch(() => setNames([]));
  }, [first]);
  return names;
}

/** Each finished run's indicators of one variable: kept with the run when the study named it,
 * else computed by the server on asking. */
function useIndicator(study: Study, runs: Run[], variable: string): Record<string, Record<string, number | null>> {
  const named = study.spec && "indicators" in study.spec && study.spec.indicators.includes(variable);
  const done = runs.filter((run) => run.status === "done").length;
  const [asked, setAsked] = useState<Record<string, Record<string, number | null>>>({});
  useEffect(() => {
    if (named || !variable || !done) { setAsked({}); return; }
    api.studyIndicators(study.id, variable).then((found) => setAsked(found.runs)).catch(() => setAsked({}));
  }, [study.id, variable, named, done]);
  if (!named) return asked;
  return Object.fromEntries(runs.filter((run) => run.result?.indicators?.[variable]).map((run) => [run.id, run.result.indicators[variable]]));
}

/** A variable field: any variable of the results, the study's own first. */
function VariableField({ label, value, names, indicators, onChange }: { label: string; value: string; names: string[]; indicators: string[]; onChange: (value: string) => void }) {
  const id = useId();
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const all = [...new Set([...indicators, ...names])];
  const commit = (next: string) => { if (next !== value && (all.includes(next) || !all.length)) onChange(next); };
  return <label className="mc-inline-field">{label}
    <input list={id} value={text} aria-label={label} onChange={(event) => { setText(event.target.value); if (all.includes(event.target.value)) onChange(event.target.value); }} onBlur={() => commit(text.trim())} />
    <datalist id={id}>{all.slice(0, 1000).map((item) => <option key={item} value={item} />)}</datalist>
  </label>;
}

/** How the study drives an input, in words (round 9 M6); a swept value shows in the sweep. */
function inputText(item: NonNullable<StudySpec["options"]["inputs"]>[string]): string {
  const value = item.value ?? t("each value of the sweep");
  if (item.shape === "step") return t("Step from {before} to {value} at {at} s", { before: item.before ?? "", value, at: item.at ?? "" });
  if (item.shape === "ramp") return t("Ramp from {before} to {value}, {at} s to {end} s", { before: item.before ?? "", value, at: item.at ?? "", end: item.end ?? "" });
  return t("Held at {value}", { value });
}

function sweptNames(study: Study): string[] {
  if (study.spec && "optimization" in study.spec && study.spec.optimization) return study.spec.optimization.variables.map((item) => item.name);
  return study.spec && "sweep" in study.spec ? study.spec.sweep.map((item) => item.name) : [];
}

const GOAL_WORDS: Record<string, string> = { minimize: "Minimize", maximize: "Maximize", target: "Reach" };
const OPTIMIZATION_WORDS: Record<string, string> = {
  running: "Optimizing", waiting: "Waiting to go on", done: "Finished", stopped: "Cancelled", failed: "Failed",
};

/** An optimization study: how it goes, the best values found, the objective of every
 * simulation and the best so far. */
function OptimizationPanel({ study }: { study: Study }) {
  const spec = study.spec && "optimization" in study.spec ? study.spec.optimization : undefined;
  const state = study.optimization;
  if (!spec) return null;
  const evaluations = state?.evaluations ?? [];
  const best = state?.best;
  const objective = spec.objective;
  const what = `${objective.variable} · ${t(STATISTIC_WORDS[objective.statistic] ?? objective.statistic)}`;
  // The best feasible objective after each simulation (a line that only gets better).
  let bestCost: number | null = null;
  let bestValue: number | null = null;
  const bestSoFar = evaluations.map((item) => {
    if (item.objective !== null && item.feasible && (bestCost === null || item.cost < bestCost)) { bestCost = item.cost; bestValue = item.objective; }
    return bestValue;
  });
  const theme = plotTheme(currentTheme());
  const status = state?.status ?? "running";
  return <section className="panel mc-optimization" aria-label={t("Optimization")}>
    <div className="panel-header"><div>
      <h2>{t("Optimization")}</h2>
      <p>{t("{goal} {what}", { goal: t(GOAL_WORDS[objective.goal]), what })}{objective.goal === "target" ? ` = ${objective.target}` : ""}
        {spec.constraints.length > 0 && ` · ${spec.constraints.map((item) => `${item.variable} ${t(STATISTIC_WORDS[item.statistic] ?? item.statistic).toLowerCase()} ${item.op === "<=" ? "≤" : "≥"} ${item.value}`).join(", ")}`}</p>
    </div></div>
    <p className="mc-optimization-status">
      <Pill status={`run-${status === "stopped" ? "cancelled" : status === "waiting" ? "queued" : status}`} label={t(OPTIMIZATION_WORDS[status] ?? status)} />
      {t("{n} of at most {most} simulations", { n: evaluations.length, most: spec.max_simulations })} · {state?.method ?? spec.method}
      {state?.message && status !== "running" && <small>{t(state.message)}</small>}
    </p>
    {best ? <>
      <p className="mc-best-line"><Trophy aria-hidden="true" /> {t("Best: {what} = {value}", { what, value: reading(best.objective) })}
        {!best.feasible && <span className="danger small"> {t("(no simulation met every constraint: the closest)")}</span>}
        <Link to={studyRunPath(study.id, { id: best.run_id } as Run)}>{t("Open its simulation")}</Link></p>
      <div className="table-wrap"><table className="table mc-rank-table">
        <thead><tr><th>{t("Value")}</th><th className="numeric">{t("Start")}</th><th className="numeric">{t("Bounds")}</th><th className="numeric">{t("Best")}</th></tr></thead>
        <tbody>{spec.variables.map((item) => <tr key={item.name} className="mc-best">
          <td className="pc-mono">{item.name}</td><td className="numeric pc-mono">{item.start}</td>
          <td className="numeric pc-mono">{item.min} – {item.max}</td><td className="numeric pc-mono"><b>{reading(best.values[item.name])}</b></td>
        </tr>)}</tbody>
      </table></div>
    </> : <p className="muted">{status === "failed" ? t("No simulation gave the objective a value.") : t("The first simulation is on its way.")}</p>}
    {evaluations.length > 0 && <Plot data={[
      { type: "scatter", mode: "markers", name: t("Each simulation"), x: evaluations.map((item) => item.index), y: evaluations.map((item) => item.objective),
        text: evaluations.map((item) => Object.entries(item.values).map(([name, value]) => `${name}=${reading(value)}`).join("<br>")),
        hovertemplate: "#%{x}: %{y}<br>%{text}<extra></extra>",
        marker: { size: 8, color: evaluations.map((item) => (item.feasible ? seriesVar(0) : seriesVar(3))) } },
      { type: "scatter", mode: "lines", name: t("Best so far"), x: evaluations.map((item) => item.index), y: bestSoFar, line: { shape: "hv", width: 2, color: seriesVar(1) } },
    ] as Plotly.Data[]}
      useResizeHandler style={{ width: "100%", height: 300 }} config={{ displaylogo: false, responsive: true }}
      layout={{ ...theme, autosize: true, height: 300, margin: { l: 56, r: 16, t: 16, b: 48 }, showlegend: true, legend: { orientation: "h", y: -0.25 },
        xaxis: { ...theme.xaxis, title: { text: t("Simulation") }, dtick: evaluations.length < 15 ? 1 : undefined },
        yaxis: { ...theme.yaxis, title: { text: what } },
        shapes: objective.goal === "target" && typeof objective.target === "number" ? [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: objective.target, y1: objective.target, line: { dash: "dot", width: 1, color: seriesVar(2) } }] : [] }} />}
  </section>;
}

/** The study's results: one variable of every finished simulation (or those ticked), coloured
 * by a varied parameter, with the band the simulations cover. */
function Overlay({ study, runs, picked, names, initial, onRemove }: { study: Study; runs: Run[]; picked: string[]; names: string[]; initial: string; onRemove?: () => void }) {
  const done = runs.filter((run) => run.status === "done");
  const swept = sweptNames(study);
  const [name, setName] = useState(initial);
  const [colourBy, setColourBy] = useState(swept[0] ?? "");
  const [splitBy, setSplitBy] = useState("");
  const [band, setBand] = useState(true);
  const [answer, setAnswer] = useState<StudySeries | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (!name && names[0]) setName(names[0]); }, [name, names]);
  const pickedKey = picked.join(",");
  const doneKey = done.length;
  useEffect(() => {
    if (!name || !doneKey) return;
    api.studySeries(study.id, name, picked.length ? picked : undefined, band).then((found) => { setAnswer(found); setError(""); }).catch((err) => setError(message(err)));
    // Fetched again when more simulations finish (doneKey) or the ticked ones change (pickedKey).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [study.id, name, pickedKey, doneKey, band]);
  if (!done.length) return <div className="panel"><p className="muted">{t("No simulation has finished yet. The results show here as they do.")}</p></div>;
  const theme = plotTheme(currentTheme());
  // Side by side, the lines within each chart take the colour of another varied parameter.
  const shade = splitBy && colourBy === splitBy ? swept.find((item) => item !== splitBy) ?? "" : colourBy;
  const values = (answer?.series ?? []).map((item) => item.variant[shade]).filter((value): value is number => typeof value === "number");
  const low = Math.min(...values);
  const high = Math.max(...values);
  const traces: Plotly.Data[] = [];
  const envelope = answer?.envelope;
  if (envelope && band) {
    traces.push({ type: "scatter", mode: "lines", x: envelope.time, y: envelope.p95, line: { width: 0 }, hoverinfo: "skip", showlegend: false } as Plotly.Data);
    traces.push({ type: "scatter", mode: "lines", name: t("5–95 % of the simulations"), x: envelope.time, y: envelope.p5, fill: "tonexty", fillcolor: "rgba(120,140,160,0.18)", line: { width: 0 }, hoverinfo: "skip" } as Plotly.Data);
    traces.push({ type: "scatter", mode: "lines", name: t("Median"), x: envelope.time, y: envelope.p50, line: { color: theme.font.color, width: 1.5, dash: "dot" } } as Plotly.Data);
  }
  const many = (answer?.series.length ?? 0) > 12;
  (answer?.series ?? []).forEach((item, index) => {
    const value = item.variant[colourBy];
    const colour = colourBy && typeof value === "number" ? rampColor(high > low ? (value - low) / (high - low) : 1) : seriesVar(index);
    traces.push({ type: "scatter", mode: "lines", name: item.label, x: item.time, y: item.values, showlegend: !many,
      line: { color: colour, width: many ? 1.2 : 2 }, hovertemplate: `${item.label}<br>%{x}: %{y}<extra></extra>` } as Plotly.Data);
  });
  return <section className="panel">
    <div className="toolbar mc-compare-toolbar">
      <VariableField label={t("Variable")} value={name} names={names} indicators={[]} onChange={setName} />
      {swept.length > 0 && <label className="mc-inline-field">{t("Colour by")}
        <select value={colourBy} onChange={(event) => setColourBy(event.target.value)}>
          <option value="">{t("Each its own colour")}</option>
          {swept.map((item) => <option key={item} value={item}>{sweptLabel(item)}</option>)}
        </select>
      </label>}
      {swept.length > 0 && <label className="mc-inline-field">{t("Side by side")}
        <select value={splitBy} onChange={(event) => setSplitBy(event.target.value)} aria-label={t("Side by side")}>
          <option value="">{t("All in one chart")}</option>
          {swept.map((item) => <option key={item} value={item}>{t("One chart per {name}", { name: item })}</option>)}
        </select>
      </label>}
      <label className="check"><input type="checkbox" checked={band} onChange={(event) => setBand(event.target.checked)} /> {t("Envelope")}</label>
      <span className="muted small">{picked.length ? t("{n} ticked simulations", { n: picked.length }) : t("All {n} finished simulations", { n: done.length })}</span>
      {onRemove && <button type="button" className="link-button" onClick={onRemove}>{t("Remove this chart")}</button>}
    </div>
    {error && <ErrorBox text={error} />}
    {shade && values.length > 1 && <p className="muted small">{t("Lighter lines: smaller {name} ({low}); deeper: larger ({high}).", { name: shade, low: reading(low), high: reading(high) })}</p>}
    {splitBy ? <SideBySide series={answer?.series ?? []} splitBy={splitBy} name={name} colourOf={(item, index) => {
      const value = item.variant[shade];
      return shade && typeof value === "number" ? rampColor(high > low ? (value - low) / (high - low) : 1) : seriesVar(index);
    }} /> : <Plot data={traces} useResizeHandler style={{ width: "100%", height: 440 }} config={{ displaylogo: false, responsive: true }}
      layout={{ ...theme, autosize: true, height: 440, margin: { l: 56, r: 16, t: 16, b: 48 }, legend: { ...theme.legend, orientation: "h", y: -0.2 },
        xaxis: { ...theme.xaxis, title: { text: t("Time [s]") } }, yaxis: { ...theme.yaxis, title: { text: name } } }} />}
  </section>;
}

type SeriesItem = StudySeries["series"][number];

/** Small multiples: one chart per value of a varied parameter, on the same vertical scale, so
 * the outputs of each choice sit side by side. */
function SideBySide({ series, splitBy, name, colourOf }: { series: SeriesItem[]; splitBy: string; name: string; colourOf: (item: SeriesItem, index: number) => string }) {
  const groups = new Map<string, SeriesItem[]>();
  series.forEach((item) => {
    const key = String(item.variant[splitBy] ?? "–");
    groups.set(key, [...(groups.get(key) ?? []), item]);
  });
  const ordered = [...groups.entries()].sort(([a], [b]) => (Number.isFinite(Number(a)) && Number.isFinite(Number(b)) ? Number(a) - Number(b) : a.localeCompare(b)));
  const all = series.flatMap((item) => item.values.filter((value): value is number => typeof value === "number"));
  const range = all.length ? [Math.min(...all), Math.max(...all)] : undefined;
  const pad = range ? (range[1] - range[0]) * 0.05 || 1 : 0;
  const theme = plotTheme(currentTheme());
  return <div className="mc-side-by-side" data-testid="side-by-side">
    {ordered.map(([value, items]) => <figure key={value} className="mc-side-chart">
      <figcaption><span className="muted">{splitBy} =</span> <b className="pc-num">{Number.isFinite(Number(value)) ? reading(Number(value)) : value}</b> <span className="muted small">· {t("{n} simulations", { n: items.length })}</span></figcaption>
      <Plot data={items.map((item, index) => ({ type: "scatter", mode: "lines", name: item.label, x: item.time, y: item.values, showlegend: false,
        line: { color: colourOf(item, index), width: 1.5 }, hovertemplate: `${item.label}<br>%{x}: %{y}<extra></extra>` }) as Plotly.Data)}
        useResizeHandler style={{ width: "100%", height: 240 }} config={{ displaylogo: false, responsive: true }}
        layout={{ ...theme, autosize: true, height: 240, margin: { l: 48, r: 8, t: 8, b: 36 },
          xaxis: { ...theme.xaxis, title: { text: t("Time [s]") } },
          yaxis: { ...theme.yaxis, title: { text: name }, ...(range ? { range: [range[0] - pad, range[1] + pad] } : {}) } }} />
    </figure>)}
  </div>;
}

/** An indicator against a varied parameter: how the answer moves with the choice. */
function Scatter({ study, runs, names }: { study: Study; runs: Run[]; names: string[] }) {
  const swept = sweptNames(study).filter((name) => name !== "@method");
  const indicators = study.spec && "indicators" in study.spec ? study.spec.indicators : [];
  const [x, setX] = useState(swept[0] ?? "");
  const [variable, setVariable] = useState(indicators[0] ?? "");
  useEffect(() => { if (!variable && names[0]) setVariable(names[0]); }, [variable, names]);
  const measured = useIndicator(study, runs, variable);
  // The largest value by default: a peak (an overshoot, a hot spot) is what a sweep is often for.
  const [statistic, setStatistic] = useState<string>("max");
  const [colourBy, setColourBy] = useState(swept[1] ?? "");
  if (!swept.length || !variable) return null;
  const done = runs.filter((run) => run.status === "done" && measured[run.id]);
  const theme = plotTheme(currentTheme());
  const xs = done.map((run) => run.variant?.[x] as number);
  const ys = done.map((run) => measured[run.id][statistic] as number | null);
  const colours = colourBy ? done.map((run) => Number(run.variant?.[colourBy])) : undefined;
  return <section className="panel">
    <div className="panel-header"><div><h2>{t("Indicator against a parameter")}</h2><p>{t("Each point is one simulation.")}</p></div></div>
    <div className="toolbar mc-compare-toolbar">
      <VariableField label={t("Indicator")} value={variable} names={names} indicators={indicators} onChange={setVariable} />
      <label className="mc-inline-field">
        <select value={statistic} onChange={(event) => setStatistic(event.target.value)} aria-label={t("Statistic")}>{STATISTICS.map((item) => <option key={item} value={item}>{t(STATISTIC_WORDS[item])}</option>)}</select>
      </label>
      <label className="mc-inline-field">{t("Against")}
        <select value={x} onChange={(event) => setX(event.target.value)}>{swept.map((item) => <option key={item} value={item}>{sweptLabel(item)}</option>)}</select>
      </label>
      {swept.length > 1 && <label className="mc-inline-field">{t("Colour by")}
        <select value={colourBy} onChange={(event) => setColourBy(event.target.value)}>
          <option value="">{t("One colour")}</option>
          {swept.filter((item) => item !== x).map((item) => <option key={item} value={item}>{sweptLabel(item)}</option>)}
        </select>
      </label>}
    </div>
    <Plot data={[{ type: "scatter", mode: "markers", x: xs, y: ys, text: done.map((run) => run.label), hovertemplate: "%{text}<br>%{y}<extra></extra>",
      marker: colours ? { size: 9, color: colours, colorscale: [0, 0.25, 0.5, 0.75, 1].map((at) => [at, rampColor(at)]), showscale: true, colorbar: { title: { text: colourBy }, thickness: 12 } } : { size: 9, color: seriesVar(0) } } as Plotly.Data]}
      useResizeHandler style={{ width: "100%", height: 360 }} config={{ displaylogo: false, responsive: true }}
      layout={{ ...theme, autosize: true, height: 360, margin: { l: 56, r: 16, t: 16, b: 48 }, showlegend: false,
        xaxis: { ...theme.xaxis, title: { text: x } }, yaxis: { ...theme.yaxis, title: { text: `${variable} · ${t(STATISTIC_WORDS[statistic])}` } } }} />
  </section>;
}

/** The runs ranked by one indicator (a variable and a statistic), the best first. */
function Ranking({ study, runs, names }: { study: Study; runs: Run[]; names: string[] }) {
  const swept = sweptNames(study);
  const indicators = study.spec && "indicators" in study.spec ? study.spec.indicators : [];
  const [variable, setVariable] = useState(indicators[0] ?? "");
  const [statistic, setStatistic] = useState<string>("iae");
  const [smaller, setSmaller] = useState(true);
  useEffect(() => { if (!variable && names[0]) setVariable(names[0]); }, [variable, names]);
  const measured = useIndicator(study, runs, variable);
  if (!variable) return null;
  const value = (run: Run) => measured[run.id]?.[statistic] as number | null | undefined;
  const ranked = runs.filter((run) => run.status === "done" && typeof value(run) === "number" && Number.isFinite(value(run)))
    .sort((a, b) => (smaller ? 1 : -1) * ((value(a) as number) - (value(b) as number)));
  const best = ranked[0];
  const choose = (next: string) => { setStatistic(next); setSmaller(SMALLER_IS_BETTER[next] ?? false); };
  const shown = ["final", "overshoot", "settling", "iae"].filter((item) => item !== statistic);
  return <section className="panel mc-ranking" aria-label={t("Ranking")}>
    <div className="panel-header"><div><h2>{t("Ranking")}</h2></div></div>
    <div className="toolbar mc-compare-toolbar">
      <VariableField label={t("Indicator")} value={variable} names={names} indicators={indicators} onChange={setVariable} />
      <label className="mc-inline-field">
        <select value={statistic} onChange={(event) => choose(event.target.value)} aria-label={t("Statistic")}>{STATISTICS.map((item) => <option key={item} value={item}>{t(STATISTIC_WORDS[item])}</option>)}</select>
      </label>
      <label className="mc-inline-field">{t("Best is")}
        <select value={smaller ? "smaller" : "larger"} onChange={(event) => setSmaller(event.target.value === "smaller")}>
          <option value="smaller">{t("the smallest")}</option><option value="larger">{t("the largest")}</option>
        </select>
      </label>
    </div>
    {best ? <p className="mc-best-line"><Trophy aria-hidden="true" /> {t("Best: {run}, {value}", { run: best.label || variantText(best.variant) || best.id, value: reading(value(best)) })}</p>:
      <p className="muted">{t("No simulation has finished with this indicator yet.")}</p>}
    {ranked.length > 0 && <div className="table-wrap"><table className="table mc-rank-table">
      <thead><tr><th className="numeric">#</th><th>{t("Simulation")}</th>{swept.map((name) => <th key={name} className="numeric pc-mono">{sweptLabel(name)}</th>)}
        <th className="numeric">{t(STATISTIC_WORDS[statistic])}</th>{shown.map((item) => <th key={item} className="numeric">{t(STATISTIC_WORDS[item])}</th>)}<th className="numeric">{t("Run time")}</th></tr></thead>
      <tbody>{ranked.slice(0, 100).map((run, index) => <tr key={run.id} className={index === 0 ? "mc-best" : undefined} onClick={() => navigate(studyRunPath(study.id, run))}>
        <td className="numeric">{index + 1}</td>
        <td><Link to={studyRunPath(study.id, run)}>{run.label || variantText(run.variant) || run.id}</Link></td>
        {swept.map((name) => <td key={name} className="numeric pc-mono">{String(run.variant?.[name] ?? "–")}</td>)}
        <td className="numeric pc-mono"><b>{reading(value(run))}</b></td>
        {shown.map((item) => <td key={item} className="numeric pc-mono">{reading(measured[run.id]?.[item])}</td>)}
        <td className="numeric pc-mono">{run.seconds !== null ? formatDuration(run.seconds) : "–"}</td>
      </tr>)}</tbody>
    </table></div>}
    {ranked.length > 100 && <p className="muted small">{t("The first 100 of {n} simulations.", { n: ranked.length })}</p>}
  </section>;
}

function StatisticsTable({ studyId, doneCount }: { studyId: string; doneCount: number }) {
  const [rows, setRows] = useState<StatisticRow[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.studyStatistics(studyId).then(setRows).catch((err) => setError(message(err))); }, [studyId, doneCount]);
  if (error) return <ErrorBox text={error} />;
  if (!rows) return <Loading />;
  if (!rows.length) return <div className="panel"><p className="muted">{t("No indicator yet: the study measures the variables named when it started, once its simulations finish.")}</p></div>;
  const columns = ["n", "mean", "std", "min", "p5", "p50", "p95", "max"] as const;
  const words: Record<string, string> = { n: "n", mean: "Mean", std: "Std. dev.", min: "Smallest", p5: "P5", p50: "Median", p95: "P95", max: "Largest" };
  return <div className="panel table-panel"><table className="table mc-stats">
    <thead><tr><th>{t("Variable")}</th><th>{t("Indicator")}</th>{columns.map((key) => <th key={key} className="numeric">{t(words[key])}</th>)}</tr></thead>
    <tbody>{rows.map((row) => <tr key={`${row.variable}-${row.statistic}`}>
      <td className="pc-mono">{row.variable}</td><td>{t(STATISTIC_WORDS[row.statistic] ?? row.statistic)}</td>
      {columns.map((key) => <td key={key} className="numeric pc-mono">{key === "n" ? row.n : reading(row[key])}</td>)}
    </tr>)}</tbody>
  </table></div>;
}

/** The study's simulations: the values each one used, how far it is, its indicators. */
/** A study's simulations: the values each used and its indicators' final values. Ticking some
 * and comparing them needs `onCompare` (the study's page). */
export function SimulationsTable({ study, runs, me, onCompare, runLink = runPath }: { study: Study; runs: Run[]; me: Me; onCompare?: (ids: string[]) => void; runLink?: (run: Run) => string }) {
  const swept = sweptNames(study);
  const indicators = study.spec && "indicators" in study.spec ? study.spec.indicators : [];
  const cancel = async (run: Run) => { try { await api.cancelRun(run.id); } catch (err) { window.alert(message(err)); } };
  const columns: DataColumn<Run>[] = [
    { key: "label", label: t("Simulation"), sort: (run) => run.created_at, render: (run) => <strong>{run.label || variantText(run.variant) || run.id}</strong> },
    ...swept.map((name) => ({ key: `p:${name}`, label: <span className="pc-mono">{sweptLabel(name).split(".").pop()}</span>, numeric: true, sort: (run: Run) => Number(run.variant?.[name]), render: (run: Run) => <span className="pc-mono">{String(run.variant?.[name] ?? "–")}</span> })),
    { key: "status", label: t("Status"), sort: (run) => run.status, filter: { options: Object.entries(RUN_WORDS).map(([value, label]) => ({ value, label: t(label) })) },
      render: (run) => (run.status === "running" && typeof run.progress === "number" ? <Progress value={run.progress} text={`${Math.round(run.progress * 100)} %`} /> : <RunPill run={run} />) },
    ...indicators.slice(0, 3).map((name) => ({ key: `i:${name}`, label: <span className="pc-mono" title={t("Final value")}>{name}</span>, numeric: true,
      sort: (run: Run) => run.result?.indicators?.[name]?.final ?? null, render: (run: Run) => <span className="pc-mono">{reading(run.result?.indicators?.[name]?.final)}</span> })),
    { key: "seconds", label: <span title={t("How long the simulation took to run")}>{t("Run time")}</span>, numeric: true, sort: (run) => run.seconds, render: (run) => (run.seconds !== null ? formatDuration(run.seconds) : "–") },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, render: (run) => (me.can_edit && (run.status === "queued" || run.status === "running")
      ? <button type="button" className="icon-button" title={t("Cancel")} aria-label={t("Cancel")} onClick={(event) => { event.stopPropagation(); void cancel(run); }}><Square /></button> : null) },
  ];
  return <DataTable rows={runs} columns={columns} rowKey={(run) => run.id} label={t("Simulations")} selectable={Boolean(onCompare)}
    actions={onCompare && ((selected, clear) => <button type="button" className="button button-small button-primary" disabled={!selected.some((run) => run.status === "done")}
      onClick={() => { onCompare(selected.filter((run) => run.status === "done").map((run) => run.id)); clear(); }}>{t("Compare these ({n})", { n: selected.length })}</button>)}
    searchText={(run) => [run.label, variantText(run.variant), run.summary].join(" ")} searchPlaceholder={t("Search simulations")}
    initialSort={{ key: "label", descending: false }} empty={t("No simulation matches these filters.")} onRowClick={(run) => navigate(runLink(run))} />;
}

function Settings({ study }: { study: Study }) {
  const spec = study.spec && "options" in study.spec ? study.spec : null;
  if (!spec) return <div className="panel"><p className="muted">{t("The single simulations of {model}, each with its own settings: open one to see them.", { model: study.model })}</p></div>;
  const options = spec.options;
  return <div className="pc-grid pc-grid-2">
    <div className="panel">
      <div className="panel-header"><div><h2>{t("Simulation settings")}</h2></div></div>
      <dl className="mc-facts">
        <dt>{t("Start")}</dt><dd>{options.start} s</dd><dt>{t("Stop")}</dt><dd>{options.stop} s</dd>
        <dt>{t("Intervals")}</dt><dd>{options.intervals}</dd><dt>{t("Tolerance")}</dt><dd>{options.tolerance}</dd>
        <dt>{t("Solver")}</dt><dd>{options.method}</dd>
        {options.time_limit && <><dt>{t("Time limit")}</dt><dd>{formatDuration(options.time_limit)}</dd></>}
      </dl>
    </div>
    <div className="panel">
      <div className="panel-header"><div><h2>{t("Inputs and parameters")}</h2><p>{t("What the study changed from the model.")}</p></div></div>
      <table className="table"><tbody>
        {Object.entries(options.overrides ?? {}).map(([name, value]) => <tr key={name}><td className="pc-mono">{name}</td><td className="pc-mono">{String(value)}</td></tr>)}
        {Object.entries(options.inputs ?? {}).map(([name, item]) => <tr key={`input-${name}`}><td className="pc-mono">{name}</td><td>{inputText(item)}</td></tr>)}
        {(spec.optimization?.variables ?? []).map((item) => <tr key={`optimize-${item.name}`}><td className="pc-mono">{item.name}</td><td>{t("Optimized from {start}, between {min} and {max}", { start: item.start, min: item.min, max: item.max })}</td></tr>)}
        {spec.sweep.map((item) => <tr key={item.name}><td className="pc-mono">{sweptLabel(item.name)}</td><td className="pc-mono">{item.mode === "range" ? t("{count} values from {start} to {stop}", { count: item.count ?? 0, start: item.start ?? 0, stop: item.stop ?? 0 }) : (item.values ?? []).join(", ")}</td></tr>)}
        {!spec.sweep.length && !spec.optimization && !Object.keys(options.overrides ?? {}).length && !Object.keys(options.inputs ?? {}).length && <tr><td className="muted">{t("None: the model's own values.")}</td></tr>}
      </tbody></table>
      {spec.indicators.length > 0 && <p className="small"><strong>{t("Indicators")}:</strong> <span className="pc-mono">{spec.indicators.join(", ")}</span></p>}
    </div>
  </div>;
}

type StudyInputs = { models: Array<Pick<ClassInfo, "name" | "short"> & Partial<ClassInfo>>; parameters?: StudyParameter[]; settings?: SimSettings; indicators?: string[] };

/** What a study of a model needs: a diagram model's parameters, settings and scopes (a model
 * written as code has its parameters read by omc). */
async function studyInputs(projectId: string, name: string): Promise<StudyInputs> {
  try {
    const [model, catalog] = await Promise.all([api.model(projectId, name), api.catalog()]);
    // A model written as code (its one block) has its parameters and inputs read by omc.
    if (model.code_block) return { models: [{ name: model.model, short: model.name }], settings: model.settings };
    if (model.editable || model.diagram) {
      return {
        models: [{ name: model.model, short: model.name }],
        parameters: diagramParameters(model.diagram, catalog), settings: model.settings, indicators: scopeSignals(model.diagram, catalog),
      };
    }
  } catch { /* a model written as code: its parameters come from omc */ }
  return { models: [{ name, short: name.split(".").pop() ?? name }] };
}

/** The address of a new study: of a model, or like an earlier study (to run it again with changes). */
/** `/studies/new`: a new study on a page of its own (round 8 M2): any model of any project, chosen
 * here (a person no longer has to open the model first), its inputs and parameters, the preview. */
export function NewStudyPage() {
  const query = new URLSearchParams(window.location.search);
  const likeId = query.get("like") ?? "";
  const [models, setModels] = useState<ModelItem[] | null>(null);
  const [like, setLike] = useState<Study | undefined>();
  const [choice, setChoice] = useState({ project: query.get("project") ?? "", model: query.get("model") ?? "" });
  const [inputs, setInputs] = useState<StudyInputs | null>(null);
  const [error, setError] = useState("");
  const [folders] = useFolders("study");
  const [folder, setFolder] = useState(() => chosenFolder(window.location.search));
  useEffect(() => { api.models().then(setModels).catch((err) => setError(message(err))); }, []);
  // Run again with changes: the new study goes in the folder of the one it copies.
  useEffect(() => { const place = likeId ? folders?.items[likeId]?.folder_id : ""; if (place) setFolder(place); }, [likeId, folders]);
  useEffect(() => {
    if (!likeId) return;
    api.study(likeId).then((found) => { setLike(found); setChoice({ project: found.project_id, model: found.model }); }).catch((err) => setError(message(err)));
  }, [likeId]);
  useEffect(() => {
    setInputs(null);
    if (!choice.project || !choice.model) return;
    studyInputs(choice.project, choice.model).then(setInputs).catch((err) => setError(message(err)));
  }, [choice.project, choice.model]);
  const pick = (value: string) => {
    const [project, model] = value.split("\u0000");
    setChoice({ project, model });
    window.history.replaceState(null, "", window.location.pathname + `?${new URLSearchParams({ project, model }).toString()}`);
  };
  const groups = [...new Set((models ?? []).map((item) => item.project))];
  const started = async (found: Study) => {
    try { await putInFolder("study", found.id, folder); } catch { /* the study runs; it is just in no folder */ }
    navigate(`/studies/${found.id}`);
  };
  const select = <label>{t("Model")}
    <select value={choice.model ? `${choice.project}\u0000${choice.model}` : ""} disabled={Boolean(like)} onChange={(event) => pick(event.target.value)} aria-label={t("Model")}>
      {!choice.model && <option value="">{t("Choose a model")}</option>}
      {groups.map((group) => <optgroup key={group} label={group}>
        {(models ?? []).filter((item) => item.project === group).map((item) => <option key={`${item.project_id}/${item.model}`} value={`${item.project_id}\u0000${item.model}`}>{item.name}</option>)}
      </optgroup>)}
    </select>
  </label>;
  const field = <>{select}<FolderField kind="study" value={folder} onChange={setFolder} /></>;
  return <>
    <nav className="breadcrumb"><Link to="/studies">{t("Studies")}</Link></nav>
    <Heading eyebrow={t("Study")} title={like ? t("Run the study again") : t("New study")}
      detail={t("A model simulated over every combination of the values its inputs and parameters take, compared side by side.")} />
    {error && <ErrorBox text={error} />}
    {!models ? <Loading /> : !choice.model ? <section className="panel mc-study-section"><div className="form-grid">{field}</div><p className="muted small">{t("Choose the model to study.")}</p></section>:
      !inputs ? <Loading />:
      <StudyForm key={`${choice.project}/${choice.model}`} projectId={choice.project} models={inputs.models} model={choice.model} like={like}
        parameters={inputs.parameters} settings={inputs.settings} indicators={inputs.indicators} modelField={field}
        onClose={() => navigate(like ? `/studies/${like.id}` : "/studies")} onStarted={(found) => void started(found)} />}
  </>;
}

export function StudyPage({ studyId, me }: { studyId: string; me: Me }) {
  const [study, setStudy] = useState<Study | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [renaming, setRenaming] = useState(false);
  const load = useCallback(() => api.study(studyId).then((found) => { setStudy(found); return found; }), [studyId]);
  useEffect(() => {
    let timer = 0;
    const follow = () => load().then((found) => { if (active(found)) timer = window.setTimeout(follow, 1500); }).catch((err) => setError(message(err)));
    void follow();
    return () => window.clearTimeout(timer);
  }, [load]);
  const runs = useMemo(() => study?.runs ?? [], [study]);
  const names = useVariables(runs);
  // More charts, each its own variable (round 9 M10).
  const [charts, setCharts] = useState<string[]>([]);
  // Models' work here (app.toml): read the study's results.
  useAssistantPage(study && { title: study.name, place: t("Models › Study {name}", { name: study.name }), page: "modelcraft:study",
    facts: { study: study.id, model: study.model, kind: study.kind, runs: runs.length, description: study.description.slice(0, 280) },
    view: { spec: JSON.stringify(study.spec).slice(0, 1500), runs: runs.slice(0, 15).map((run) => JSON.stringify(run).slice(0, 200)) } });
  if (error) return <ErrorBox text={error} />;
  if (!study) return <Loading />;
  const busy = active(study);
  const cancel = async () => { try { await api.cancelStudy(study.id); await load(); } catch (err) { setError(message(err)); } };
  const remove = async () => {
    if (!(await confirmAction(t("Delete this study and its {n} simulations?", { n: study.total }), { confirm: t("Delete"), danger: true }))) return;
    try { await api.deleteStudy(study.id); navigate("/studies"); } catch (err) { setError(message(err)); }
  };
  const runAgain = () => navigate(`/studies/new?like=${encodeURIComponent(study.id)}`);
  return <>
    <nav className="breadcrumb"><Link to="/studies">{t("Studies")}</Link> › <Link to={modelPath(study.project_id, study.model)}>{study.model.split(".").pop()}</Link></nav>
    <Heading eyebrow={t(STUDY_WORDS[study.kind] ?? study.kind)} title={study.name}
      detail={study.description || t("Started {when} by {who}.", { when: formatDate(study.created_at), who: study.created_by })}
      actions={<>
        {me.can_edit && busy && <button type="button" className="button button-secondary" onClick={() => void cancel()}><Square />{t("Cancel the rest")}</button>}
        {me.can_edit && study.kind !== "quick" && <button type="button" className="button button-secondary" onClick={runAgain}><CopyPlus />{t("Run again with changes")}</button>}
        {study.done > 0 && <a className="button button-primary" href={api.studyExportUrl(study.id)} download title={t("Parameters, results and a Jupyter notebook that reads them, in a .zip")}><Download />{t("Export for Jupyter")}</a>}
        {me.can_edit && !busy && <button type="button" className="button button-danger button-icon" title={t("Delete the study")} aria-label={t("Delete the study")} onClick={() => void remove()}><Trash2 /></button>}
      </>} />
    {study.kind !== "quick" && <FolderPlaceLine kind="study" itemId={study.id} canEdit={me.can_edit} />}
    <div className="panel mc-study-bar">
      <StudyProgress study={study} />
      {me.can_edit && study.kind !== "quick" && <button type="button" className="link-button" onClick={() => setRenaming(true)}>{t("Rename")}</button>}
    </div>
    {picked.length > 0 && <div className="notice mc-notice-info">{t("Comparing {n} ticked simulations.", { n: picked.length })} <button type="button" className="link-button" onClick={() => setPicked([])}>{t("Show all")}</button></div>}
    {study.kind === "optimization" && <OptimizationPanel study={study} />}
    <Ranking study={study} runs={runs} names={names} />
    <Overlay study={study} runs={runs} picked={picked} names={names} initial={(study.spec && "indicators" in study.spec ? study.spec.indicators[0] : "") ?? ""} />
    {charts.map((chart, index) => <Overlay key={chart} study={study} runs={runs} picked={picked} names={names} initial={names[index + 1] ?? names[0] ?? ""} onRemove={() => setCharts(charts.filter((_, other) => other !== index))} />)}
    {study.done > 0 && <div className="row-actions"><button type="button" className="button button-secondary" onClick={() => setCharts([...charts, `chart-${Date.now()}`])}><Plus />{t("Add a chart of another variable")}</button></div>}
    <Scatter study={study} runs={runs} names={names} />
    <h2 className="section-title">{t("Simulations")}</h2>
    <SimulationsTable study={study} runs={runs} me={me} runLink={(run) => studyRunPath(study.id, run)} onCompare={(ids) => { setPicked(ids); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
    <h2 className="section-title">{t("Settings")}</h2>
    <Settings study={study} />
    <details className="mc-statistics"><summary className="section-title">{t("Statistics over the simulations")}</summary>
      <StatisticsTable studyId={study.id} doneCount={study.done} />
    </details>
    {renaming && <RenameStudy study={study} onClose={() => setRenaming(false)} onSaved={() => { setRenaming(false); void load(); }} />}
  </>;
}

function RenameStudy({ study, onClose, onSaved }: { study: Study; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(study.name);
  const [description, setDescription] = useState(study.description);
  const [error, setError] = useState("");
  const save = async () => { try { await api.changeStudy(study.id, { name: name.trim(), description }); onSaved(); } catch (err) { setError(message(err)); } };
  return <Dialog title={t("Rename the study")} onClose={onClose} footer={<>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
    <button type="button" className="button button-primary" disabled={!name.trim()} onClick={() => void save()}>{t("Save")}</button>
  </>}>
    {error && <div className="notice notice-error">{error}</div>}
    <div className="form-grid">
      <label>{t("Name")}<input value={name} maxLength={120} autoFocus onChange={(event) => setName(event.target.value)} /></label>
      <label className="pc-span-all">{t("Description")}<input value={description} maxLength={2000} onChange={(event) => setDescription(event.target.value)} /></label>
    </div>
  </Dialog>;
}
