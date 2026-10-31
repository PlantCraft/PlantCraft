import { Activity, ArrowUpRight, BookOpen, ChevronRight, ClipboardList, FileDown, Pencil, Pin, Play, RotateCcw, Trash2, Wrench } from "lucide-react";
import { DataTable, FollowUp, NextSteps, PhoneFold, confirmAction, useAssistantPage, plotTheme, statusVar, type DataColumn, type JourneyStep } from "@plantcraft/ui";
import { useEffect, useMemo, useState } from "react";
import { processCraftAssetUrl } from "./AssetLink";
import { chartsImage, leaveAttachment, resultActionUrl } from "./loopResult";
import { api } from "./api";
import { formatDate, formatNumber, t } from "./i18n";
import { formatPercent, methodLabel, performanceOf } from "./labels";
import { LoopForm } from "./LoopForm";
import { href, navigate } from "./nav";
import { Plot } from "@plantcraft/ui/plot";
import { opBins } from "./chart";
import { resultLabel, statusLabel, suiteLabel } from "./status";
import type { Algorithm, LoopDetail, Me, MethodResult, SettingSource, SetpointStep, StepResponses, TuningSuggestion } from "./types";
import { AlgorithmDiagram } from "./AlgorithmDiagramLazy";
import { algorithmOf } from "./algorithms";
import { ErrorBox, Health, Heading, Link, Loading, Pill, ResultHeadline } from "./ui";
import { resultsPath } from "./ResultsPage";

const ORDER: Record<string, number> = { bad: 0, warning: 1, ok: 2, insufficient_data: 3, not_applicable: 4 };

type LoopJob = LoopDetail["jobs"][number];
const RUN_COLUMNS: DataColumn<LoopJob>[] = [
  { key: "name", label: t("Run"), sort: (job) => job.name, render: (job) => <Link to={`/runs/${job.job_id}`}>{job.name}</Link> },
  { key: "status", label: t("Status"), sort: (job) => job.status, render: (job) => <Pill status={job.status} label={t(job.status)} />, filter: { value: (job) => t(job.status) } },
  { key: "requested_at", label: t("Requested"), sort: (job) => job.requested_at, render: (job) => formatDate(job.requested_at) },
  { key: "created_by", label: t("By"), sort: (job) => job.created_by, filter: true },
];

function Trends({ detail }: { detail: LoopDetail }) {
  const theme = plotTheme();
  const times = detail.series.map((point) => point.timestamp);
  const line = (name: string, values: Array<number | null | undefined>, dash?: string) => ({ type: "scatter" as const, mode: "lines" as const, name, x: times, y: values.map((value) => value ?? null), line: { width: 1.6, ...(dash ? { dash } : {}) } });
  const layout = (title: string) => ({ ...theme, height: 260, margin: { l: 48, r: 12, t: 30, b: 32 }, title: { text: title, font: { size: 12 } }, showlegend: true, legend: { ...theme.legend, orientation: "h" as const, y: 1.18, x: 1, xanchor: "right" as const } });
  if (!times.length) return <p className="muted">{t("No trend data for this window.")}</p>;
  return <div className="charts loop-result-charts">
    <Plot data={[line("PV", detail.series.map((p) => p.pv)), line("SP", detail.series.map((p) => p.sp), "dot")]} layout={layout(t("PV and SP"))} config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} />
    <Plot data={[line("OP", detail.series.map((p) => p.op))]} layout={layout(t("Controller output (%)"))} config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} />
    <OpHistogram values={detail.series.map((p) => p.op)} />
  </div>;
}

function OpHistogram({ values }: { values: Array<number | null | undefined> }) {
  const theme = plotTheme();
  const bins = opBins(values);
  if (!bins.y.some((share) => share > 0)) return null;
  return <Plot
    data={[{ type: "bar", name: "OP", x: bins.x, y: bins.y, width: 4.6, hovertemplate: "%{x:.0f}% ± 2.5: %{y:.1f}%<extra></extra>" }]}
    layout={{ ...theme, height: 220, margin: { l: 48, r: 12, t: 30, b: 40 }, title: { text: t("Controller output: share of the window in each 5% band"), font: { size: 12 } }, showlegend: false, bargap: 0.05, xaxis: { ...theme.xaxis, range: [0, 100], title: { text: t("Controller output (%)") } }, yaxis: { ...theme.yaxis, title: { text: t("% of the window") } } }}
    config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} />;
}

const CHOICE_LABELS: Record<string, string> = { tight: "Tight (λ = dead time)", moderate: "Moderate (λ = time constant)", robust: "Robust (λ = 3 × time constant)" };

/** PI settings from a model fitted to the loop's last window (Lambda/IMC rules), read only (A12):
 * asked for on demand, since the fit reads the window again. */
function TuningSuggestionPanel({ detail }: { detail: LoopDetail }) {
  const [found, setFound] = useState<TuningSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function ask() {
    setBusy(true); setError("");
    try { setFound(await api.tuningSuggestion(detail.loop.loop_id)); } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  const model = found?.model;
  return <section className="panel" data-testid="tuning-suggestion">
    <div className="panel-header"><div><h2>{t("Tuning suggestion")}</h2><p>{t("PI settings from a first-order-plus-dead-time model fitted to the last window (OP to PV), by Lambda (IMC) rules. Read only: nothing is sent to the controller.")}</p></div>
      {!detail.incomplete && <div className="row-actions"><button className="button button-secondary" disabled={busy} onClick={() => void ask()}><Wrench size={15} />{busy ? t("Fitting…") : found ? t("Fit again") : t("Suggest tuning")}</button></div>}
    </div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {found && !found.available && <p className="muted">{found.reason}</p>}
    {found?.available && model && <>
      <div className={found.reliable ? "notice" : "notice notice-error"}>{found.reliable
        ? t("Fitted from closed-loop data: a starting point to confirm with a step test, not settings to apply as they are.")
        : t("Not reliable: {why}. Use it only with a step test.", { why: (found.caveats ?? []).join("; ") })}</div>
      <dl className="facts">
        <div><dt>{t("Process gain")}</dt><dd>{formatNumber(model.gain, 3)}</dd></div>
        <div><dt>{t("Time constant")}</dt><dd>{t("{n} s", { n: formatNumber(model.tau_seconds, 1) })}</dd></div>
        <div><dt>{t("Dead time")}</dt><dd>{t("{n} s", { n: formatNumber(model.dead_time_seconds, 1) })}</dd></div>
        <div><dt>{t("Fit (R²)")}</dt><dd>{formatNumber(model.r2, 3)}</dd></div>
        <div><dt>{t("Controller action")}</dt><dd>{found.action === "reverse" ? t("Reverse (more OP raises the PV)") : t("Direct (more OP lowers the PV)")}</dd></div>
      </dl>
      <DataTable rows={found.settings ?? []} rowKey={(item) => item.choice} label={t("Tuning suggestion")} columns={[
        { key: "choice", label: t("Closed-loop speed"), render: (item) => t(CHOICE_LABELS[item.choice] ?? item.choice) },
        { key: "lambda", label: t("λ (s)"), render: (item) => formatNumber(item.lambda_seconds, 1) },
        { key: "kc", label: t("Kc (% OP per PV unit)"), render: (item) => formatNumber(item.kc, 4) },
        { key: "ti", label: t("Ti (s)"), render: (item) => formatNumber(item.ti_seconds, 1) },
      ]} />
    </>}
  </section>;
}

const seconds = (value: number | null) => (value === null ? "—" : t("{n} s", { n: formatNumber(value, 0) }));

const STEP_COLUMNS: DataColumn<SetpointStep>[] = [
  { key: "at", label: t("Step at"), sort: (item) => item.at ?? "", render: (item) => (item.at ? formatDate(item.at) : "—") },
  { key: "size", label: t("SP change"), sort: (item) => item.size, render: (item) => `${formatNumber(item.sp_before, 2)} → ${formatNumber(item.sp_after, 2)}` },
  { key: "overshoot", label: t("Overshoot"), sort: (item) => item.overshoot_pct, render: (item) => `${formatNumber(item.overshoot_pct, 1)} %` },
  { key: "rise", label: t("Rise time"), sort: (item) => item.rise_seconds ?? Infinity, render: (item) => (item.reached ? seconds(item.rise_seconds) : t("Not reached")) },
  { key: "settling", label: t("Settling time"), sort: (item) => item.settling_seconds ?? Infinity, render: (item) => (item.settled ? seconds(item.settling_seconds) : t("Not settled")) },
  { key: "iae", label: t("IAE per unit of step"), sort: (item) => item.iae_seconds, render: (item) => seconds(item.iae_seconds) },
];

/** How the loop answered the setpoint steps of its last window (A10): overshoot, rise and
 * settling times and IAE, asked for on demand since it reads the window again. */
function StepResponsePanel({ detail }: { detail: LoopDetail }) {
  const [found, setFound] = useState<StepResponses | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function ask() {
    setBusy(true); setError("");
    try { setFound(await api.stepResponses(detail.loop.loop_id)); } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  const summary = found?.summary;
  return <section className="panel" data-testid="step-response">
    <div className="panel-header"><div><h2>{t("Setpoint steps")}</h2><p>{t("Each setpoint change in the last window and how the PV answered it: overshoot, rise time (10 to 90 %), settling time (inside 5 % of the step) and IAE. Read from the history, no test on the plant.")}</p></div>
      {!detail.incomplete && <div className="row-actions"><button className="button button-secondary" disabled={busy} onClick={() => void ask()}><Activity size={15} />{busy ? t("Reading…") : found ? t("Read again") : t("Find steps")}</button></div>}
    </div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {found && !found.available && <p className="muted">{found.reason}</p>}
    {found?.available && summary && <>
      <dl className="facts">
        <div><dt>{t("Steps")}</dt><dd>{summary.steps}</dd></div>
        <div><dt>{t("Median overshoot")}</dt><dd>{summary.overshoot_pct === null ? "—" : `${formatNumber(summary.overshoot_pct, 1)} %`}</dd></div>
        <div><dt>{t("Median rise time")}</dt><dd>{seconds(summary.rise_seconds)}</dd></div>
        <div><dt>{t("Median settling time")}</dt><dd>{seconds(summary.settling_seconds)}</dd></div>
        <div><dt>{t("Settled")}</dt><dd>{`${formatNumber(summary.settled_pct, 0)} %`}</dd></div>
      </dl>
      <DataTable rows={found.steps ?? []} rowKey={(item) => `${item.at}-${item.sp_after}`} label={t("Setpoint steps")} columns={STEP_COLUMNS} initialSort={{ key: "at", descending: true }} />
    </>}
  </section>;
}

/** The last run against the run recorded as the loop's reference (A8): what got worse since a
 * window someone called good, after commissioning or a retune. */
function AgainstReference({ detail, me, onChanged }: { detail: LoopDetail; me: Me; onChanged: () => void }) {
  const [error, setError] = useState("");
  const reference = detail.reference;
  const canRecord = me.can_edit && !detail.incomplete && detail.results.length > 0;
  async function record() {
    setError("");
    if (reference && !(await confirmAction(t("Replace the reference of {date} with the last run?", { date: formatDate(reference.recorded_at) }), { confirm: t("Replace") }))) return;
    try { await api.recordReference(detail.loop.loop_id); onChanged(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function remove() {
    if (!(await confirmAction(t("Remove this loop's reference?"), { confirm: t("Remove"), danger: true }))) return;
    try { await api.deleteReference(detail.loop.loop_id); onChanged(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  const change = (value: number | null) => (value === null ? "—" : `${value > 0 ? "+" : ""}${formatNumber(value, 1)}`);
  const moved = (item: NonNullable<LoopDetail["reference"]>["methods"][number]) => {
    const found = Object.entries(item.indicators).filter(([, value]) => value.index !== null && value.index !== 1).sort((a, b) => Math.abs(Math.log(b[1].index as number)) - Math.abs(Math.log(a[1].index as number)))[0];
    return found ? `${found[0]}: ${formatNumber(found[1].reference, 3)} → ${formatNumber(found[1].now, 3)} (×${formatNumber(found[1].index as number, 2)})` : t("Unchanged");
  };
  return <section className="panel" data-testid="loop-reference">
    <div className="panel-header"><div><h2>{t("Against the reference")}</h2><p>{reference
      ? t("The last run against the run recorded on {date} by {who} (window up to {end}).", { date: formatDate(reference.recorded_at), who: reference.recorded_by, end: reference.source_end ? formatDate(reference.source_end) : "—" })
      : t("Record a run you call good (after commissioning or a retune) and later runs are shown against it.")}</p></div>
      {canRecord && <div className="row-actions">
        <button className="button button-secondary" onClick={() => void record()}><Pin size={15} />{t("Record as reference")}</button>
        {reference && <button className="button button-secondary danger" onClick={() => void remove()}><Trash2 size={15} />{t("Remove")}</button>}
      </div>}
    </div>
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {reference && <>
      {reference.version_changed && <div className="notice">{t("The algorithm changed since the reference was recorded: some scores may differ for that reason alone.")}</div>}
      <dl className="facts">
        <div><dt>{t("Health then")}</dt><dd>{reference.health_reference === null ? "—" : formatNumber(reference.health_reference, 1)}</dd></div>
        <div><dt>{t("Health now")}</dt><dd>{reference.health_now === null ? "—" : formatNumber(reference.health_now, 1)}</dd></div>
        <div><dt>{t("Change")}</dt><dd>{change(reference.health_change)}</dd></div>
      </dl>
      {reference.methods.length ? <DataTable rows={reference.methods} rowKey={(item) => item.method_id} label={t("Against the reference")} columns={[
        { key: "method", label: t("Method"), sort: (item) => methodLabel(item.method_id), render: (item) => methodLabel(item.method_id) },
        { key: "status", label: t("Status then → now"), render: (item) => <><Pill status={item.status_reference} label={resultLabel(item.status_reference)} /> → <Pill status={item.status_now} label={resultLabel(item.status_now)} /></> },
        { key: "score", label: t("Score change"), sort: (item) => item.score_change ?? 0, render: (item) => change(item.score_change) },
        { key: "moved", label: t("Indicator that moved most"), render: moved },
      ]} /> : <p className="muted">{t("No method was judged in both runs.")}</p>}
    </>}
  </section>;
}

function HealthHistory({ detail }: { detail: LoopDetail }) {
  if (detail.history.length < 2) return <section className="panel"><div className="panel-header"><div><h2>{t("Derived signals")}</h2><p>{t("The loop's health, one value per run: it shows once it has run twice.")}</p></div></div></section>;
  const theme = plotTheme();
  return <section className="panel"><div className="panel-header"><div><h2>{t("Derived signals")}</h2><p>{t("The loop's health over 30 days, one value per run.")}</p></div></div>
    <Plot data={[{ type: "scatter", mode: "lines+markers", x: detail.history.map((item) => item.source_end), y: detail.history.map((item) => item.health), marker: { size: 4 }, line: { width: 1.5 }, name: t("Health") }]}
      layout={{ ...theme, height: 200, margin: { l: 40, r: 12, t: 8, b: 30 }, yaxis: { ...theme.yaxis, range: [0, 100] } }} config={{ displaylogo: false, responsive: true }} useResizeHandler style={{ width: "100%" }} />
  </section>;
}

/** The algorithm's outputs as the last round left them: results, series and messages. */
function Outputs({ detail }: { detail: LoopDetail }) {
  const outputs = detail.summary?.outputs ?? [];
  if (!outputs.length) return null;
  type Output = (typeof outputs)[number];
  const kind = (item: Output) => t(item.kind === "result" ? "Result" : item.kind === "series" ? "Series" : "Message");
  const columns: DataColumn<Output>[] = [
    { key: "name", label: t("Output"), sort: (item) => item.name, render: (item) => <b>{item.name}</b> },
    { key: "kind", label: t("Type"), sort: kind, render: kind, filter: { value: kind } },
    { key: "status", label: t("Status"), sort: (item) => ORDER[item.status] ?? 9, render: (item) => <Pill status={item.status} label={resultLabel(item.status)} />, filter: { value: (item) => item.status, options: [...new Set(outputs.map((item) => item.status))].map((value) => ({ value, label: resultLabel(value) })) } },
    { key: "value", label: t("Value"), numeric: true, sort: (item) => item.value ?? null, render: (item) => (item.value === null || item.value === undefined ? "—" : formatNumber(item.value, 1)) },
    { key: "says", label: t("Says"), render: (item) => (item.kind === "message" ? (item.triggered ? item.text || item.message : t("Not sent in this run.")) : item.message) },
  ];
  return <DataTable rows={outputs} columns={columns} rowKey={(item) => item.node_id} label={t("Outputs")} />;
}

const SOURCE_LABEL: Record<SettingSource, string> = { asset: "from the asset record", here: "set here", default: "Link default" };

function Source({ source }: { source?: SettingSource }) {
  if (!source) return null;
  return <small className={`source-tag source-${source}`} data-source={source}>{t(SOURCE_LABEL[source])}</small>;
}


function IncompleteRecord({ detail, me }: { detail: LoopDetail; me: Me }) {
  const loop = detail.loop;
  const missing = detail.missing_roles ?? [];
  const required = loop.asset_record?.required_roles?.length ? loop.asset_record.required_roles : ["pv", "op"];
  return <section className="panel incomplete-record" role="status">
    <div className="panel-header"><div><h2>{t("Incomplete record")}</h2>
      <p>{t("PlantCraft's asset {id} has no signal for {roles}, which a control loop needs. Analytics lists the loop but does not analyse it.", { id: String(loop.metadata?.asset_id ?? loop.loop_id), roles: missing.map((role) => role.toUpperCase()).join(", ") })}</p></div></div>
    <dl className="facts">{required.map((role) => <div key={role}><dt>{role.toUpperCase()}</dt><dd className={missing.includes(role) ? "missing" : "pc-mono"}>{missing.includes(role) ? t("Missing") : String(loop.signals[role as keyof typeof loop.signals] ?? "—")}</dd></div>)}</dl>
    <p>{t("Bind the missing signals on the asset's page in PlantCraft (Assets); the next sync picks them up and the loop is analysed from the next run.")}</p>
    <a className="button button-secondary" href={processCraftAssetUrl(me, String(loop.metadata?.asset_id ?? loop.loop_id))}>{t("Open the asset in PlantCraft")}<ArrowUpRight size={15} /></a>
  </section>;
}

function AssetFacts({ detail }: { detail: LoopDetail }) {
  const record = detail.loop.asset_record;
  if (!record) return null;
  const loopType = record.loop_type ? `${record.loop_type}${detail.loop_type_known ? "" : ` (${t("not known to Analytics: generic defaults")})`}` : "—";
  return <>
    <h3>{t("Asset record (PlantCraft)")}</h3>
    <dl className="facts">
      <div><dt>{t("TYPE")}</dt><dd>{record.type_path.join(" › ") || record.type_id}</dd></div>
      <div><dt>{t("LOOP TYPE")}</dt><dd>{loopType}</dd></div>
      <div><dt>{t("CRITICALITY")}</dt><dd>{record.criticality ?? "—"}</dd></div>
      <div><dt>{t("ACTION")}</dt><dd>{record.action ?? "—"}</dd></div>
      <div><dt>{t("CONTROLLER")}</dt><dd>{record.controller ?? "—"}</dd></div>
      <div><dt>{t("RELATIONS")}</dt><dd>{record.relations.length ? record.relations.map((item) => `${t(item.type.replaceAll("_", " "))} ${item.to}`).join(", ") : "—"}</dd></div>
    </dl>
  </>;
}

function Findings({ results }: { results: MethodResult[] }) {
  const columns: DataColumn<MethodResult>[] = [
    { key: "method", label: t("Method"), sort: (item) => methodLabel(item.method_id), render: (item) => <><Link to={`/methods/${item.method_id}`} className="strong">{methodLabel(item.method_id)}</Link>{item.method_id.startsWith("dq_") && <small>{t("Data quality gate")}</small>}</> },
    { key: "status", label: t("Result"), sort: (item) => ORDER[item.status] ?? 9, render: (item) => <Pill status={item.status} label={resultLabel(item.status)} />, filter: { value: (item) => item.status, options: Object.keys(ORDER).filter((value) => results.some((item) => item.status === value)).map((value) => ({ value, label: resultLabel(value) })) } },
    { key: "performance", label: t("Performance"), numeric: true, sort: (item) => (rated(item) ? performanceOf(item) : null), render: (item) => (rated(item) ? formatPercent(performanceOf(item)) : "—") },
    { key: "finding", label: t("Finding"), render: (item) => item.finding || item.message },
    { key: "help", label: <span className="sr-only">{t("Help")}</span>, render: (item) => <Link to={`/help/methods/${item.method_id}`} className="help-link"><BookOpen size={14} />{t("How to read this")}</Link> },
  ];
  return <DataTable rows={results} columns={columns} rowKey={(item) => item.method_id} initialSort={{ key: "status", descending: false }} label={t("Findings")} />;
}

const rated = (item: MethodResult) => item.status === "ok" || item.status === "warning" || item.status === "bad";

function Settings({ detail, me, onChanged }: { detail: LoopDetail; me: Me; onChanged: () => void }) {
  const [algorithms, setAlgorithms] = useState<Algorithm[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.algorithms().then(setAlgorithms).catch(() => setAlgorithms([])); }, []);
  const loop = detail.loop;
  const fromPlantCraft = detail.origin === "processcraft";
  const sources = detail.settings_source;
  const defaults = detail.record_defaults;
  const canReset = me.can_edit && fromPlantCraft && !!defaults;
  const profileName = (id?: string) => algorithmOf(algorithms, id)?.name ?? id ?? "";
  async function change(payload: Record<string, unknown>) {
    setError("");
    try { await api.updateLoop(loop.loop_id, payload); onChanged(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  async function remove() {
    if (!(await confirmAction(t("Delete loop {id}? Its run history stays."), { confirm: t("Delete"), danger: true }))) return;
    try { await api.deleteLoop(loop.loop_id); navigate("/"); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  return <section className="panel">
    <div className="panel-header"><div><h2>{t("Settings")}</h2><p>{fromPlantCraft ? t("From PlantCraft asset {id}: its name, signals and record are edited there; the CPM settings below are Analytics'.", { id: String(loop.metadata?.asset_id ?? loop.loop_id) }) : t("Defined in Analytics.")}</p></div></div>
    <dl className="facts">
      {(["pv", "sp", "op", "mode"] as const).map((role) => <div key={role}><dt>{role.toUpperCase()}</dt><dd className="pc-mono">{loop.signals[role] || "—"}</dd></div>)}
    </dl>
    <AssetFacts detail={detail} />
    <div className="form-grid">
      <label><span className="label-line">{t("Algorithm")}<Source source={sources?.profile_id} /></span><select value={algorithmOf(algorithms, loop.profile_id)?.algorithm_id ?? loop.profile_id} disabled={!me.can_edit} onChange={(event) => void change({ profile_id: event.target.value })}>{algorithms.filter((item) => item.subject_kind === "loop").map((item) => <option key={item.algorithm_id} value={item.algorithm_id}>{item.name}</option>)}</select>
        {canReset && sources?.profile_id === "here" && <button type="button" className="link-button" onClick={() => void change({ reset: ["profile_id"] })}><RotateCcw size={13} />{t("Use the asset record ({value})", { value: profileName(defaults?.profile_id) })}</button>}</label>
      <label><span className="label-line">{t("Criticality")}<Source source={sources?.criticality} /></span><select value={String(loop.metadata?.criticality ?? "medium")} disabled={!me.can_edit} onChange={(event) => void change({ criticality: event.target.value })}>{["critical", "high", "medium", "low"].map((item) => <option key={item} value={item}>{t(item[0].toUpperCase() + item.slice(1))}</option>)}</select>
        {canReset && sources?.criticality === "here" && <button type="button" className="link-button" onClick={() => void change({ reset: ["criticality"] })}><RotateCcw size={13} />{t("Use the asset record ({value})", { value: t(defaults?.criticality ?? "medium") })}</button>}</label>
      <label className="check"><input type="checkbox" checked={loop.enabled} disabled={!me.can_edit} onChange={(event) => void change({ enabled: event.target.checked })} />{t("Analysed in every run")}</label>
    </div>
    {sources && <p className="muted small">{sources.method_parameters === "asset" ? t("Method parameters: the algorithm's, over the defaults of the loop type ({type}). See Help for the table.", { type: String(loop.asset_record?.loop_type ?? "") }) : sources.method_parameters === "here" ? t("Method parameters: some are set here, over the algorithm's.") : t("Method parameters: the algorithm's and the method defaults.")}</p>}
    {error && <div className="notice notice-error" role="alert">{error}</div>}
    {me.can_edit && !fromPlantCraft && <div className="row-actions">
      <button className="button button-secondary" onClick={() => setEditing(true)}><Pencil size={15} />{t("Edit")}</button>
      <button className="button button-secondary danger" onClick={() => void remove()}><Trash2 size={15} />{t("Delete")}</button>
    </div>}
    {editing && <LoopForm loop={loop} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); onChanged(); }} />}
  </section>;
}

/** The loop's id and its short name ("FIC-1003 · Recycle flow"); its service, a sentence, only
 * when it has no name of its own, so the title stays on one line beside the assistant's button. */
export function loopTitle(loop: { loop_id: string; name: string; service: string }): string {
  const name = loop.name && loop.name !== loop.loop_id ? loop.name : loop.service;
  return name ? `${loop.loop_id} · ${name}` : loop.loop_id;
}

const assetId = (detail: LoopDetail) => String(detail.loop.metadata?.asset_id ?? detail.loop.loop_id);

/** "FIC-1003: Valve stiction": the new action's title, from the limiting finding. */
function actionTitle(detail: LoopDetail): string {
  const limiting = detail.summary?.limiting;
  return limiting ? `${detail.loop.loop_id}: ${methodLabel(limiting.method_id)}` : detail.loop.loop_id;
}

/** Where to go from a loop: its worst signal, how to read its limiting method, the asset, the list. */
export function loopNextSteps(detail: LoopDetail, me: Me): JourneyStep[] {
  const items: JourneyStep[] = [];
  const limiting = detail.summary?.limiting;
  const pv = detail.loop.signals.pv;
  if (detail.summary?.data_quality?.apt === false && pv) items.push({ title: t("Check the PV signal"), detail: t("The data quality gate rejected this window: see what is wrong with the signal."), to: `/signals/${encodeURIComponent(pv)}`, cta: t("Open the signal") });
  if (limiting) items.push({ title: t("How to read {method}", { method: methodLabel(limiting.method_id) }), detail: t("What the limiting method measures, its usual causes and what to check in the field."), to: `/help/methods/${limiting.method_id}`, cta: t("Read the guide") });
  if (detail.origin === "processcraft") items.push({ title: t("The asset in PlantCraft"), detail: t("Its record, signals, history and the other apps that look at it."), url: processCraftAssetUrl(me, assetId(detail)), cta: t("Open the asset") });
  items.push({ title: t("Back to the results"), detail: t("The other loops, worst first."), to: resultsPath({ kind: ["loop"] }), cta: t("Open the results") });
  return items;
}

export function LoopPage({ loopId, me }: { loopId: string; me: Me }) {
  const [detail, setDetail] = useState<LoopDetail | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = () => api.loop(loopId).then((value) => { setDetail(value); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => { setDetail(null); void load(); }, [loopId]);
  const results = useMemo(() => detail?.results ?? [], [detail]);
  const [algorithm, setAlgorithm] = useState<{ id: string; name: string } | null>(null);
  useEffect(() => { if (detail) api.algorithms().then((items) => { const found = algorithmOf(items, detail.loop.profile_id); setAlgorithm(found ? { id: found.algorithm_id, name: found.name } : null); }).catch(() => setAlgorithm(null)); }, [detail?.loop.profile_id]);
  const profileName = algorithm?.name ?? "";
  const algorithmId = algorithm?.id ?? detail?.loop.profile_id ?? "";

  const [opening, setOpening] = useState(false);
  // A19: PlantCraft's action form with this result written out and the loop's charts as one image.
  async function newAction() {
    if (!detail) return;
    setOpening(true);
    let key: string | null = null;
    try {
      const plotly = (await import("plotly.js-cartesian-dist-min")).default as unknown as Parameters<typeof chartsImage>[1];
      const image = await chartsImage(document.querySelector<HTMLElement>(".loop-result-charts"), plotly);
      if (image) key = leaveAttachment(`${detail.loop.loop_id} ${(detail.source_end ?? "").slice(0, 16).replace("T", " ")}.png`, image);
    } catch { key = null; } // without the image the form still opens with the result
    window.location.assign(resultActionUrl(me, detail, key));
  }

  async function runNow() {
    setMessage("");
    try {
      const job = await api.createJob({ loop_id: loopId, name: t("Run from the loop page"), lookback_minutes: 1440 });
      setMessage(t("Run queued ({id}). See Runs for the result.", { id: job.job_id.slice(0, 8) }));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  // What the assistant can do on this page (the button beside the title): Link's works for a loop
  // (app.toml: its health, a plot, the field checks) and one task of its own.
  const loopSummary = detail?.summary;
  useAssistantPage(detail && {
    page: "linkcraft:loop", facts: { pv: detail.loop.signals.pv ?? "", sp: detail.loop.signals.sp ?? "", op: detail.loop.signals.op ?? "", window_start: detail.source_start ?? "", window_end: detail.source_end ?? "" },
    subject: assetId(detail) ? `asset:${assetId(detail)}` : undefined, title: detail.loop.loop_id, place: t("Analytics › Loop {loop}", { loop: detail.loop.loop_id }),
    context: [`Control loop ${detail.loop.loop_id}${detail.loop.service ? ` (${detail.loop.service})` : ""}, area ${detail.loop.area || "—"}.`,
      detail.incomplete ? "Its record is incomplete: not analysed." : `Health ${loopSummary?.health ?? "—"}, status ${loopSummary?.status ?? "pending"}; limiting criterion ${loopSummary?.limiting ? `${loopSummary.limiting.method_id}: ${loopSummary.limiting.finding}` : "none"}.`,
      loopSummary?.operating_state ? `Operation: ${loopSummary.operating_state} ${loopSummary.operating_state_reason ?? ""}.` : "",
      (detail.likely_causes ?? []).length ? `Likely causes: ${(detail.likely_causes ?? []).slice(0, 4).map((item) => `${item.cause} (${Math.round(100 * item.strength)} %)`).join("; ")}.` : "",
      detail.source_end ? `Window ${detail.source_start} to ${detail.source_end}.` : ""].filter(Boolean).join("\n"),
  });
  if (error && !detail) return <ErrorBox text={error} />;
  if (!detail) return <Loading text={t("Loading the loop…")} />;
  const summary = detail.summary;
  const status = summary?.status ?? "pending";
  const quality = summary?.data_quality;
  return <>
    <nav className="breadcrumb"><Link to={resultsPath({ kind: ["loop"] })}>{t("Results")}</Link><ChevronRight size={12} />{detail.loop.metadata?.asset_id ? <Link to={`/assets/${encodeURIComponent(String(detail.loop.metadata.asset_id))}`} className="pc-mono">{detail.loop.loop_id}</Link> : <span className="pc-mono">{detail.loop.loop_id}</span>}<ChevronRight size={12} /><span>{t("Loop analysis")}</span></nav>
    <Heading
      eyebrow={[detail.loop.area, detail.loop.unit].filter(Boolean).join(" · ")}
      title={loopTitle(detail.loop)}
      detail={detail.incomplete ? t("Incomplete record: not analysed.") : detail.source_end ? t("Window {start} to {end}.", { start: formatDate(detail.source_start), end: formatDate(detail.source_end) }) : t("Not analysed yet: results appear after the next run.")}
      actions={<>
        <a className="button button-secondary" href={api.loopReportUrl(loopId)}><FileDown size={16} />{t("PDF report")}</a>
        {me.can_edit && !detail.incomplete && <button type="button" className="button button-secondary" disabled={opening} onClick={() => void newAction()} title={t("Opens PlantCraft's action form with this result and the loop's charts attached")}><ClipboardList size={16} />{opening ? t("Preparing…") : t("New action")}</button>}
        {me.can_edit && !detail.incomplete && <button className="button button-primary" onClick={() => void runNow()}><Play size={16} />{t("Run now")}</button>}
      </>}
    />
    {message && <div className="notice notice-ok">{message}</div>}
    {error && <ErrorBox text={error} />}
    {!detail.incomplete && <div className="pc-grid">
      <ResultHeadline measure={{ label: t("Health"), value: summary?.health ?? null, format: "percent" }} status={detail.suite_status ?? "unknown"} native={{ label: statusLabel(status), status }} algorithm={{ id: algorithmId, name: profileName }} at={detail.analyzed_at} />
      <div className="panel kpi-card"><span className="pc-overline">{t("Limiting criterion")}</span>{summary?.limiting ? <><b>{methodLabel(summary.limiting.method_id)}</b><small>{summary.limiting.finding}</small></> : <span className="muted">—</span>}</div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Operation")}</span><b>{summary?.operating_state ? t(summary.operating_state.replaceAll("_", " ")) : "—"}</b><small>{summary?.operating_state_reason}{summary?.valid_fraction !== undefined ? ` · ${t("{share} valid data, {count} samples", { share: formatPercent(100 * summary.valid_fraction), count: formatNumber(summary?.sample_count ?? 0, 0) })}` : ""}</small></div>
    </div>}
    {detail.incomplete && <IncompleteRecord detail={detail} me={me} />}
    {quality && quality.apt === false && <div className="notice notice-error"><b>{t("The data quality gate rejected this window; the CPM methods did not run.")}</b> {(quality.reasons ?? []).join(" ")}</div>}
    {!!detail.likely_causes?.length && <section className="panel" data-testid="likely-causes"><div className="panel-header"><div><h2>{t("Likely causes")}</h2><p>{t("Ranked from the findings below; confirm in the field before acting.")}</p></div></div>
      <ol className="causes">{detail.likely_causes.map((cause) => <li key={cause.cause_id}><b>{cause.cause}</b><span>{cause.evidence.map((item) => methodLabel(item.method_id)).join(" · ")}</span><p>{cause.action}</p></li>)}</ol></section>}
    {!!summary?.alerts?.length && <section className="panel"><div className="panel-header"><div><h2>{t("Alerts")}</h2></div></div>
      <ul className="alerts">{summary.alerts.map((item) => <li key={item.method_id}><Pill status={item.severity ?? "warning"} label={`${resultLabel(item.severity ?? "warning")} · ${methodLabel(item.method_id)}`} /><span>{item.finding}</span></li>)}</ul></section>}
    {!detail.incomplete && <>
      <PhoneFold title={t("Algorithm and outputs")}><section className="panel result-algorithm"><div className="panel-header"><div><h2>{t("Algorithm and outputs")}</h2><p>{t("The {algorithm} algorithm as it ran on this loop in the last run: each block with what it said.", { algorithm: profileName || algorithmId })}</p></div><Link to={`/algorithms/${encodeURIComponent(algorithmId)}`} className="text-link">{t("Open the algorithm")}</Link></div>
        {detail.summary && <AlgorithmDiagram algorithmId={algorithmId} blocks={detail.summary.blocks} />}</section>
      <Outputs detail={detail} /></PhoneFold>
      <PhoneFold title={t("Method results")} hint={results.length ? String(results.length) : undefined}>
        <h2 className="section-title">{t("Method results")}</h2>
        {results.length ? <Findings results={results} /> : <p className="muted">{t("No results yet.")}</p>}
      </PhoneFold>
      <PhoneFold title={t("Input signals")}><section className="panel"><div className="panel-header"><div><h2>{t("Input signals")}</h2><p>{t("The window the algorithm read, from PlantCraft.")}</p></div></div><Trends detail={detail} /></section></PhoneFold>
      <PhoneFold title={t("Derived signals")}><HealthHistory detail={detail} /></PhoneFold>
      <PhoneFold title={t("Setpoint steps")}><StepResponsePanel detail={detail} /></PhoneFold>
      <PhoneFold title={t("Tuning suggestion")}><TuningSuggestionPanel detail={detail} /></PhoneFold>
      <PhoneFold title={t("Against the reference")}><AgainstReference detail={detail} me={me} onChanged={() => void load()} /></PhoneFold>
    </>}
    <div className="pc-grid pc-grid-2">
      {detail.origin === "processcraft" && <FollowUp subject={`asset:${assetId(detail)}`} newTitle={actionTitle(detail)} platformUrl={me.processcraft_url} canCreate={me.can_edit}
        detail={t("What was decided about this loop, in PlantCraft: who acts, by when.")} />}
      <PhoneFold title={t("Settings")}><Settings detail={detail} me={me} onChanged={() => void load()} /></PhoneFold>
    </div>
    {!!detail.jobs.length && <PhoneFold title={t("Recent runs")} hint={String(detail.jobs.length)}><h2 className="section-title">{t("Recent runs")}</h2><DataTable rows={detail.jobs} columns={RUN_COLUMNS} rowKey={(job) => job.job_id} initialSort={{ key: "requested_at", descending: true }} label={t("Recent runs")} /></PhoneFold>}
    <NextSteps items={loopNextSteps(detail, me)} href={href} navigate={navigate} />
  </>;
}
