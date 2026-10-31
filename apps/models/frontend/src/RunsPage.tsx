/**
 * Runs: the table of runs (a group's page, Executions), the lists of what runs now and what
 * waits, and `/runs/<id>`: one simulation or FMU export, its messages and, for a simulation, its
 * results as a plot (variables picked from a tree), compared with another run of the same model
 * and with the plant signals it was asked to match.
 */
import type * as Plotly from "plotly.js";
import { DataTable, confirmAction, showToast, currentTheme, plotTheme, seriesVar, type DataColumn, type FilterState } from "@plantcraft/ui";
import { Plot } from "@plantcraft/ui/plot";
import { Download, Package, Play, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { formatAgo, formatDate, formatDuration, t } from "./i18n";
import { navigate } from "./nav";
import { modelPath, runPath, studyPath } from "./paths";
import type { Me, QueueState, Run, SeriesAnswer, Variable } from "./types";
import { ErrorBox, Heading, KIND_WORDS, LevelPill, Link, Loading, message, Progress, reading, RUN_WORDS, RunPill, STUDY_WORDS } from "./ui";

const MAX_PLOTTED = 12;

/** What a finished run gives to download: a simulation's results, an export's FMU. */
export function runDownload(run: Run): { url: string; label: string } | null {
  if (run.status !== "done") return null;
  if (run.kind === "fmu") return { url: api.fmuUrl(run.id), label: t("Download the FMU") };
  return { url: api.resultsUrl(run.id), label: t("Download the results (CSV)") };
}


/** Runs in the suite's table: sorted by any column, searched, in pages; download, cancel and delete per row. */
export function RunsTable({ runs, me, onChanged, initialFilters, label = t("Simulations") }: { runs: Run[]; me: Me; onChanged: () => void; initialFilters?: FilterState; label?: string }) {
  const remove = async (run: Run) => {
    if (!(await confirmAction(t("Delete this simulation and its results?"), { confirm: t("Delete"), danger: true }))) return;
    try { await api.deleteRun(run.id); onChanged(); } catch (err) { showToast(message(err), { tone: "error" }); }
  };
  const cancel = async (run: Run) => {
    try { await api.cancelRun(run.id); onChanged(); } catch (err) { showToast(message(err), { tone: "error" }); }
  };
  const kinds = new Set(runs.map((run) => run.kind));
  const columns: DataColumn<Run>[] = [
    { key: "model", label: t("Model"), sort: (run) => run.model, render: (run) => <><strong>{run.model.split(".").pop()}</strong><small className="pc-mono">{run.label || run.model}</small></> },
    ...(kinds.size > 1 ? [{ key: "kind", label: t("Type"), sort: (run: Run) => run.kind, filter: { options: Object.entries(KIND_WORDS).map(([value, label]) => ({ value, label: t(label) })) }, render: (run: Run) => <span className="nowrap">{run.kind === "simulate" ? <Play className="mc-inline-icon" aria-hidden="true" /> : <Package className="mc-inline-icon" aria-hidden="true" />}{t(KIND_WORDS[run.kind])}</span> }] : []),
    ...(kinds.has("simulate") ? [{ key: "study", label: t("Study"), sort: (run: Run) => run.study?.name ?? "", render: (run: Run) => (run.study ? <span className="small">{run.study.name}</span> : "–"), filter: { value: (run: Run) => run.study?.kind ?? "", label: t("Study"), options: Object.entries(STUDY_WORDS).map(([value, label]) => ({ value, label: t(label) })) } }] : []),
    { key: "status", label: t("Status"), sort: (run) => run.status, filter: { options: Object.entries(RUN_WORDS).map(([value, label]) => ({ value, label: t(label) })) }, render: (run) => (run.status === "running" && typeof run.progress === "number" ? <Progress value={run.progress} text={`${Math.round(run.progress * 100)} %`} /> : <RunPill run={run} />) },
    { key: "summary", label: t("Result"), render: (run) => <span className="small">{run.summary}</span> },
    { key: "created_at", label: t("Started"), sort: (run) => run.created_at, render: (run) => <span className="nowrap">{formatAgo(run.created_at)}<small>{run.created_by}</small></span> },
    { key: "seconds", label: t("Time"), numeric: true, sort: (run) => run.seconds, render: (run) => (run.seconds !== null ? formatDuration(run.seconds) : "–") },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, render: (run) => {
      const file = runDownload(run);
      return <span className="row-actions">
        {file && <a className="icon-button" href={file.url} download title={file.label} aria-label={file.label}><Download /></a>}
        {me.can_edit && (run.status === "queued" || run.status === "running") && <button type="button" className="icon-button" title={t("Cancel")} aria-label={t("Cancel")} onClick={(event) => { event.stopPropagation(); void cancel(run); }}><Square /></button>}
        {me.can_edit && run.status !== "queued" && run.status !== "running" && <button type="button" className="icon-button" title={t("Delete")} aria-label={t("Delete")} onClick={(event) => { event.stopPropagation(); void remove(run); }}><Trash2 /></button>}
      </span>;
    } },
  ];
  return <DataTable rows={runs} columns={columns} rowKey={(run) => run.id} label={label}
    searchText={(run) => [run.model, run.label, run.summary, run.created_by, run.study?.name].filter(Boolean).join(" ")}
    searchPlaceholder={t("Search model or label")} initialSort={{ key: "created_at", descending: true }}
    initialFilters={initialFilters} empty={t("No simulation matches these filters.")} onRowClick={(run) => navigate(runPath(run))} />;
}

/** What runs now, how far each is, and what waits, in the order it will run. */
export function QueueLists({ queue, me, onChanged }: { queue: QueueState; me: Me; onChanged: () => void }) {
  const cancel = async (run: Run) => { try { await api.cancelRun(run.id); onChanged(); } catch (err) { showToast(message(err), { tone: "error" }); } };
  const row = (run: Run) => <li key={run.id} className="mc-queue-row">
    <Link to={runPath(run)} className="mc-queue-name"><strong>{run.label || run.model.split(".").pop()}</strong><small className="muted">{run.study ? run.study.name : run.project_name} · {run.created_by}</small></Link>
    {run.status === "running" ? <Progress value={run.progress ?? 0} text={typeof run.progress === "number" ? `${Math.round(run.progress * 100)} %` : t("Starting")} /> : <RunPill run={run} />}
    {me.can_edit && <button type="button" className="icon-button" title={t("Cancel")} aria-label={t("Cancel {name}", { name: run.label || run.model })} onClick={() => void cancel(run)}><Square /></button>}
  </li>;
  return <div className="pc-grid pc-grid-2 mc-queue">
    <section className="panel">
      <div className="panel-header"><div><h2>{t("Running")} <small className="muted">{queue.running}</small></h2><p>{t("{n} at a time: the Modelica runner's workers.", { n: queue.workers })}</p></div></div>
      {queue.running_runs.length === 0 ? <p className="muted">{t("Nothing is running.")}</p> : <ul className="mc-queue-list">{queue.running_runs.map(row)}</ul>}
    </section>
    <section className="panel">
      <div className="panel-header"><div><h2>{t("Waiting")} <small className="muted">{queue.queued}</small></h2><p>{t("Quick simulations go ahead of studies; a study's simulations run in batches.")}</p></div></div>
      {queue.queued_runs.length === 0 ? <p className="muted">{t("Nothing is waiting.")}</p> : <ul className="mc-queue-list">{queue.queued_runs.slice(0, 20).map(row)}</ul>}
      {queue.queued > 20 && <p className="muted small">{t("And {n} more.", { n: queue.queued - 20 })}</p>}
    </section>
  </div>;
}

/** Variables grouped by their component path (tank.level → tank), searchable. */
function VariableList({ variables, chosen, onToggle }: { variables: Variable[]; chosen: string[]; onToggle: (name: string) => void }) {
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<"main" | "all">("main");
  const shown = variables.filter((item) => item.column !== null
    && (kinds === "all" || (!item.name.startsWith("der(") && !item.protected && !item.name.startsWith("$")))
    && (!query || `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase())));
  const groups = new Map<string, Variable[]>();
  for (const item of shown) {
    const group = item.name.includes(".") ? item.name.slice(0, item.name.lastIndexOf(".")) : "";
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return <div className="mc-variables">
    <input type="search" value={query} placeholder={t("Search variables")} aria-label={t("Search variables")} onChange={(event) => setQuery(event.target.value)} />
    <div className="segmented" role="group">
      <button type="button" className={kinds === "main" ? "on" : ""} onClick={() => setKinds("main")}>{t("Main")}</button>
      <button type="button" className={kinds === "all" ? "on" : ""} onClick={() => setKinds("all")}>{t("All")}</button>
    </div>
    <div className="mc-variable-groups">
      {[...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([group, items]) => <details key={group} open={groups.size < 8 || Boolean(query)}>
        <summary className="pc-mono">{group || t("(model)")} <small className="muted">{items.length}</small></summary>
        {items.map((item) => <label key={item.name} className="mc-variable" title={item.description}>
          <input type="checkbox" checked={chosen.includes(item.name)} disabled={!chosen.includes(item.name) && chosen.length >= MAX_PLOTTED} onChange={() => onToggle(item.name)} />
          <span className="pc-mono">{item.name.slice(group ? group.length + 1 : 0)}</span>
          <small className="muted">{reading(item.final, item.unit)}</small>
        </label>)}
      </details>)}
      {shown.length === 0 && <p className="muted small">{t("No variable matches.")}</p>}
    </div>
  </div>;
}

function firstChoice(variables: Variable[], initial: string[] = []): string[] {
  const known = new Set(variables.filter((item) => item.column !== null).map((item) => item.name));
  const asked = initial.filter((name) => known.has(name));
  if (asked.length) return asked.slice(0, MAX_PLOTTED);
  const plain = variables.filter((item) => item.column !== null && !item.constant && !item.protected && !item.name.startsWith("der("));
  const outputs = plain.filter((item) => item.kind === "output" || item.kind === "state");
  return (outputs.length ? outputs : plain).slice(0, 3).map((item) => item.name);
}

/** A simulation's results as a plot; `initial` names the variables shown first (a diagram's
 * scopes), else its outputs and states. */
export function ResultsPlot({ run, others, initial }: { run: Run; others: Run[]; initial?: string[] }) {
  const [variables, setVariables] = useState<Variable[] | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [series, setSeries] = useState<SeriesAnswer | null>(null);
  const [against, setAgainst] = useState("");
  const [otherSeries, setOtherSeries] = useState<SeriesAnswer | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.variables(run.id).then((found) => { setVariables(found); setChosen(firstChoice(found, initial)); }).catch((err) => setError(message(err)));
    // The first choice is made once per run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id]);
  useEffect(() => {
    if (!chosen.length) { setSeries(null); return; }
    api.series(run.id, chosen).then(setSeries).catch((err) => setError(message(err)));
  }, [run.id, chosen]);
  useEffect(() => {
    if (!against || !chosen.length) { setOtherSeries(null); return; }
    api.series(against, chosen).then(setOtherSeries).catch(() => setOtherSeries(null));
  }, [against, chosen]);
  const plant = run.options?.plant as { start?: string } | undefined;
  const origin = plant?.start ? Date.parse(plant.start) : null;
  const x = (values: number[]) => (origin !== null ? values.map((s) => new Date(origin + s * 1000).toISOString()) : values);
  const units = useMemo(() => new Map((variables ?? []).map((item) => [item.name, item.unit])), [variables]);
  if (error) return <ErrorBox text={error} />;
  if (!variables) return <Loading />;
  const theme = plotTheme(currentTheme());
  const traces: Plotly.Data[] = [];
  (series?.series ?? []).forEach((item, index) => {
    const unit = units.get(item.name);
    traces.push({ type: "scatter", mode: "lines", name: unit ? `${item.name} [${unit}]` : item.name, x: x(item.time), y: item.values, line: { color: seriesVar(index), width: 2 } } as Plotly.Data);
  });
  (otherSeries?.series ?? []).forEach((item) => {
    const index = chosen.indexOf(item.name);
    traces.push({ type: "scatter", mode: "lines", name: t("{name} ({run})", { name: item.name, run: others.find((o) => o.id === against)?.label || against }), x: x(item.time), y: item.values, line: { color: seriesVar(index), width: 1.5, dash: "dash" } } as Plotly.Data);
  });
  (series?.compare ?? []).forEach((item) => {
    const index = chosen.indexOf(item.name);
    traces.push({ type: "scatter", mode: "markers", name: t("{signal} (plant)", { signal: item.signal }), x: x(item.time), y: item.values, marker: { size: 4, color: seriesVar(index >= 0 ? index : 6) } } as Plotly.Data);
  });
  return <div className="mc-results">
    <aside className="panel"><VariableList variables={variables} chosen={chosen} onToggle={(name) => setChosen(chosen.includes(name) ? chosen.filter((item) => item !== name) : [...chosen, name])} /></aside>
    <section className="panel">
      <div className="toolbar">
        <label className="mc-inline-field">{t("Compare with")}
          <select value={against} onChange={(event) => setAgainst(event.target.value)}>
            <option value="">{t("No other simulation")}</option>
            {others.map((other) => <option key={other.id} value={other.id}>{other.label || other.id} · {formatAgo(other.created_at)}</option>)}
          </select>
        </label>
      </div>
      {chosen.length === 0 ? <p className="muted">{t("Pick variables on the left to plot them.")}</p>
        : <Plot data={traces} useResizeHandler style={{ width: "100%", height: 460 }} config={{ displaylogo: false, responsive: true }}
          layout={{ ...theme, autosize: true, height: 460, margin: { l: 56, r: 16, t: 16, b: 48 }, legend: { ...theme.legend, orientation: "h", y: -0.18 },
            xaxis: { ...theme.xaxis, title: { text: origin !== null ? t("Plant time") : t("Time [s]") }, type: origin !== null ? "date" : "linear" }, yaxis: { ...theme.yaxis } }} />}
      {series?.missing.length ? <p className="muted small">{t("Not in the results: {names}", { names: series.missing.join(", ") })}</p> : null}
    </section>
  </div>;
}

/** One run; `inStudy` when it opens inside its study's page (round 9 M9). */
export function RunPage({ runId, me, inStudy }: { runId: string; me: Me; inStudy?: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [others, setOthers] = useState<Run[]>([]);
  const [error, setError] = useState("");
  const [label, setLabel] = useState<string | null>(null);
  useEffect(() => {
    let timer = 0;
    const load = () => api.run(runId).then((found) => {
      setRun(found);
      if (found.status === "queued" || found.status === "running") timer = window.setTimeout(load, 1000);
      else if (found.kind === "simulate") api.runs({ model: found.model, kind: "simulate", limit: "30" }).then((list) => setOthers(list.filter((item) => item.id !== found.id && item.status === "done"))).catch(() => undefined);
    }).catch((err) => setError(message(err)));
    void load();
    return () => window.clearTimeout(timer);
  }, [runId]);
  if (error) return <ErrorBox text={error} />;
  if (!run) return <Loading />;
  const busy = run.status === "queued" || run.status === "running";
  const saveLabel = async () => {
    if (label === null) return;
    try { setRun(await api.labelRun(run.id, label)); setLabel(null); } catch (err) { setError(message(err)); }
  };
  const options = run.options ?? {};
  const overrides = Object.entries((options.overrides ?? {}) as Record<string, unknown>);
  const plant = options.plant as { start: string; end: string; inputs: Record<string, string>; compare: Record<string, string> } | undefined;
  const result = run.result ?? {};
  const cancel = async () => { try { setRun(await api.cancelRun(run.id)); } catch (err) { setError(message(err)); } };
  return <>
    <nav className="breadcrumb">{inStudy && run.study ? <><Link to="/studies">{t("Studies")}</Link> › <Link to={studyPath(run.study)}>{run.study.name}</Link></>
      : <><Link to="/executions">{t("Simulations")}</Link>
      {run.study && <> › <Link to={studyPath(run.study)}>{run.study.kind === "quick" ? t("Single simulations of {model}", { model: run.model.split(".").pop() ?? run.model }) : run.study.name}</Link></>}</>}</nav>
    <Heading eyebrow={<>{t(KIND_WORDS[run.kind])} · <RunPill run={run} /></>} title={run.label || run.model}
      detail={run.summary || (busy ? t("omc is working on it…") : "")}
      actions={<>
        {run.kind === "fmu" && run.status === "done" && <>
          <a className="button button-secondary" href={api.fmuUrl(run.id)} download><Download />{t("Download the FMU")}</a>
        </>}
        {run.kind === "simulate" && run.status === "done" && <a className="button button-secondary" href={api.resultsUrl(run.id)} download><Download />{t("Download the results (CSV)")}</a>}
        {me.can_edit && busy && <button type="button" className="button button-secondary" onClick={() => void cancel()}><Square />{t("Cancel")}</button>}
        {run.study && run.study.kind !== "quick" && !inStudy && <Link to={studyPath(run.study)} className="button button-secondary">{t("Open the study")}</Link>}
        <Link to={modelPath(run.project_id, run.model)} className="button button-secondary">{t("Open the model")}</Link>
      </>} />
    <div className="pc-grid">
      <div className="panel kpi-card"><small>{t("Model")}</small><b className="mc-break">{run.model.split(".").pop()}</b><small className="pc-mono">{run.model}</small></div>
      <div className="panel kpi-card"><small>{t("Started")}</small><b>{formatDate(run.created_at)}</b><small>{run.created_by}</small></div>
      <div className="panel kpi-card"><small>{t("Run time")}</small><b>{run.seconds !== null ? formatDuration(run.seconds) : busy ? t("Running…") : "–"}</b><small>{run.kind === "simulate" ? `${options.method ?? ""} · ${t("{n} intervals", { n: options.intervals ?? "" })}` : `FMI ${options.version ?? ""} · ${options.type ?? ""}`}</small></div>
      <div className="panel kpi-card"><small>{t("Label")}</small>
        {label === null ? <b>{run.label || "–"} {me.can_edit && <button type="button" className="link-button" onClick={() => setLabel(run.label)}>{t("Change")}</button>}</b>
          : <form onSubmit={(event) => { event.preventDefault(); void saveLabel(); }} className="mc-inline-field"><input value={label} maxLength={120} autoFocus onChange={(event) => setLabel(event.target.value)} /><button type="submit" className="button button-small button-primary">{t("Save")}</button></form>}
      </div>
    </div>
    {busy && <div className="panel mc-run-progress">
      {run.status === "running" && typeof run.progress === "number" ? <Progress value={run.progress} text={t("{n} % of the simulated time. This page follows it.", { n: Math.round(run.progress * 100) })} />
        : <Loading text={t("The simulation is {status}. This page follows it.", { status: t(run.status === "queued" ? "queued" : "running") })} />}
    </div>}
    {run.kind === "simulate" && run.status === "done" && <ResultsPlot run={run} others={others} />}
    {run.kind === "fmu" && run.status === "done" && <div className="pc-grid">
      <div className="panel kpi-card"><small>{t("FMI version")}</small><b>{String(result.fmi_version ?? "–")}</b></div>
      <div className="panel kpi-card"><small>{t("Platforms")}</small><b>{(result.platforms as string[] | undefined)?.join(", ") || "–"}</b></div>
      <div className="panel kpi-card"><small>{t("Inputs · outputs")}</small><b>{(result.inputs as string[] | undefined)?.length ?? 0} · {(result.outputs as string[] | undefined)?.length ?? 0}</b><small>{t("{n} parameters", { n: Number(result.parameters ?? 0) })}</small></div>
      <div className="panel kpi-card"><small>{t("File")}</small><b className="mc-break pc-mono">{String(result.file ?? "")}</b><small className="pc-mono mc-break">{String(result.sha256 ?? "").slice(0, 16)}</small></div>
      <div className="panel pc-span-all">
        {(result.inputs as string[] | undefined)?.length ? <p className="small"><strong>{t("Inputs")}:</strong> <span className="pc-mono">{(result.inputs as string[]).join(", ")}</span></p> : null}
        {(result.outputs as string[] | undefined)?.length ? <p className="small"><strong>{t("Outputs")}:</strong> <span className="pc-mono">{(result.outputs as string[]).join(", ")}</span></p> : null}
      </div>
    </div>}
    <div className="pc-grid pc-grid-2">
      {(overrides.length > 0 || plant) && <div className="panel">
        <div className="panel-header"><div><h2>{t("Settings")}</h2><p>{t("What this simulation changed from the model.")}</p></div></div>
        {overrides.length > 0 && <table className="table"><tbody>{overrides.map(([name, value]) => <tr key={name}><td className="pc-mono">{name}</td><td className="pc-mono">{String(value)}</td></tr>)}</tbody></table>}
        {plant && <p className="small">{t("Plant data from {start} to {end}.", { start: formatDate(plant.start), end: formatDate(plant.end) })}<br />
          {Object.entries(plant.inputs ?? {}).map(([variable, signal]) => <span key={variable} className="tag mc-tag">{variable} ← {signal}</span>)}
          {Object.entries(plant.compare ?? {}).map(([variable, signal]) => <span key={variable} className="tag mc-tag">{variable} ≈ {signal}</span>)}
        </p>}
      </div>}
      <div className="panel">
        <div className="panel-header"><div><h2>{t("Messages")}</h2><p>{t("What omc and the solver said.")}</p></div></div>
        {run.messages.length === 0 ? <p className="muted">{busy ? t("Not yet.") : t("No message.")}</p>
          : <ul className="mc-run-messages">{run.messages.map((item, index) => <li key={index}><LevelPill level={item.level} /> <span>{item.file && item.line ? <span className="pc-mono muted">{item.file}:{item.line} </span> : null}{item.text}</span></li>)}</ul>}
      </div>
    </div>
  </>;
}
