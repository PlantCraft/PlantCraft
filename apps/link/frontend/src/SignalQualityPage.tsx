import { DataTable, useAssistantPage, type DataColumn } from "@plantcraft/ui";
import { ChevronRight, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { api, checkCatalog } from "./api";
import { formatAgo, formatDate, formatDuration, formatNumber, t } from "./i18n";
import { COUNTED, runLabel, signalLabel } from "./signalStatus";
import type { Me, QualityRun, QualityRunResult, SignalAlgorithm } from "./types";
import { ErrorBox, Heading, Link, Loading, Pill, Quality } from "./ui";
import { navigate, SIGNAL_RUN_PREFIX } from "./nav";
import { resultsPath, SUITE_OF } from "./ResultsPage";
import { LinkAssistant } from "./Assistant";

export const signalRunPath = (run: QualityRun | number) => `/runs/${SIGNAL_RUN_PREFIX}${typeof run === "number" ? run : run.id}`;

/** A run's verdicts as pills: "3 bad", "5 good". */
export function RunCounts({ run }: { run: QualityRun }) {
  const counts = run.counts ?? {};
  const shown = COUNTED.filter((key) => counts[key]);
  if (!shown.length) return <span className="muted">—</span>;
  return <span className="counts">{shown.map((key) => <Pill key={key} status={key} label={`${counts[key]} ${signalLabel(key).toLowerCase()}`} />)}</span>;
}

export const triggerLabel = (trigger: string) => t(trigger === "schedule" ? "Schedule" : trigger === "manual" ? "Run now" : trigger);

function Settings({ algorithm, me, onSaved }: { algorithm: SignalAlgorithm; me: Me; onSaved: (next: SignalAlgorithm) => void }) {
  const [form, setForm] = useState({ enabled: Boolean(algorithm.schedule.enabled), interval: String(algorithm.schedule.interval_minutes ?? 15), window: String(algorithm.settings.window_hours) });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const admin = me.is_admin;
  async function send(payload: Record<string, unknown>) {
    setError(""); setSaved("");
    try { const next = await api.saveSignalAlgorithm(payload); void checkCatalog(true); setSaved(t("Saved.")); onSaved(next); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  function save() {
    const interval = Number(form.interval);
    const window = Number(form.window);
    if (!Number.isFinite(interval) || interval < 1) { setError(t("The interval is at least 1 minute.")); return; }
    if (!Number.isFinite(window) || window <= 0) { setError(t("The window must be longer than zero.")); return; }
    void send({ enabled: form.enabled, interval_minutes: interval, window_hours: window });
  }
  function toggle(checkId: string, on: boolean) {
    const enabled = algorithm.checks.filter((item) => (item.id === checkId ? on : item.enabled)).map((item) => item.id);
    void send(enabled.length === algorithm.checks.length ? { all_checks: true } : { enabled_checks: enabled });
  }
  return <div className="pc-grid pc-grid-2">
    <section className="panel">
      <div className="panel-header"><div><h2>{t("Monitor")}</h2><p>{admin ? t("How often the algorithm runs and how much data each run reads.") : t("Only admins change the monitor.")}</p></div></div>
      <div className="form-grid">
        <label className="check"><input type="checkbox" checked={form.enabled} disabled={!admin} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />{t("Run on its cadence")}</label>
      </div>
      <div className="form-grid settings-fields narrow-fields">
        <label>{t("Every (minutes)")}<input type="number" min={1} value={form.interval} disabled={!admin} onChange={(event) => setForm({ ...form, interval: event.target.value })} /><small>{t("Time between the end of one run and the start of the next.")}</small></label>
        <label>{t("Window (hours)")}<input type="number" min={0.1} step="any" value={form.window} disabled={!admin} onChange={(event) => setForm({ ...form, window: event.target.value })} /><small>{t("Data each run reads, ending at the newest sample.")}</small></label>
      </div>
      {admin && <div className="row-actions"><button className="button button-primary" onClick={save}>{t("Save")}</button></div>}
      {saved && <div className="notice notice-ok">{saved}</div>}
      {error && <div className="notice notice-error" role="alert">{error}</div>}
    </section>
    <section className="panel">
      <div className="panel-header"><div><h2>{t("Methods")}</h2><p>{admin ? t("The Data quality methods every signal runs; a signal can still switch one off or on for itself.") : t("Only admins change which methods run.")}</p></div></div>
      <ul className="toggles">{algorithm.checks.map((item) => <li key={item.id}><label className="check">
        <input type="checkbox" checked={item.enabled} disabled={!admin} onChange={(event) => toggle(item.id, event.target.checked)} />
        <span><Link to={`/methods/${item.id}`}><b>{item.name}</b></Link><small>{item.description}</small></span>
      </label></li>)}</ul>
    </section>
  </div>;
}

/** The Signal quality algorithm: a system algorithm over every signal, its schedule, methods and where it is used. */
export function SignalQualityPage({ me }: { me: Me }) {
  const [algorithm, setAlgorithm] = useState<SignalAlgorithm | null>(null);
  const [runs, setRuns] = useState<QualityRun[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [version, setVersion] = useState(0);
  const load = () => Promise.all([api.signalAlgorithm(), api.qualityRuns(1)]).then(([value, items]) => { setAlgorithm(value); setRuns(items); setError(""); }).catch((err: Error) => setError(err.message));
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), algorithm?.running ? 2_000 : 15_000);
    return () => window.clearInterval(timer);
  }, [algorithm?.running]);
  // Link's work here (app.toml): which signals have problems.
  useAssistantPage({ place: t("Analytics › Signal quality"), page: "linkcraft:signal-quality", platformUrl: me.processcraft_url,
    facts: { last_run: runs[0]?.finished_at ?? "", signals: runs[0]?.signals ?? "", counts: runs[0]?.counts ?? {}, window_hours: algorithm?.settings.window_hours ?? "" } });

  async function runNow() {
    setMessage(""); setError("");
    try { await api.runSignalQuality(); setMessage(t("Run started.")); window.setTimeout(() => void load(), 500); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }

  if (!algorithm && error) return <ErrorBox text={error} />;
  if (!algorithm) return <Loading />;
  const last = runs[0];
  const progress = algorithm.progress;
  const sync = algorithm.sync ?? {};
  return <>
    <nav className="breadcrumb"><Link to="/algorithms">{t("Algorithms")}</Link><ChevronRight size={12} /><Link to="/algorithms/signal_quality">{algorithm.name}</Link><ChevronRight size={12} /><span>{t("Monitor and checks")}</span></nav>
    <Heading eyebrow={t("System algorithm · every signal")} title={algorithm.name} detail={algorithm.description}
      actions={<><LinkAssistant kind="algorithm" id="signal_quality" me={me} title={algorithm.name} />{me.can_edit && <button className="button button-primary" disabled={algorithm.running} onClick={() => void runNow()}><Play size={16} />{algorithm.running ? t("Running…") : t("Run now")}</button>}</>} />
    {message && <div className="notice notice-ok">{message}</div>}
    {error && <ErrorBox text={error} />}
    <div className="pc-grid">
      <div className="panel kpi-card"><span className="pc-overline">{t("Now")}</span>
        {algorithm.running
          ? <><Pill status="running" label={t("Running")} /><span className="health"><span className="health-bar"><span style={{ width: `${progress.total ? (100 * (progress.done ?? 0)) / progress.total : 0}%`, background: "var(--pc-info-fill)" }} /></span><b className="pc-num">{t("{done} of {total}", { done: progress.done ?? 0, total: progress.total ?? "?" })}</b></span></>
          : <><b>{t("Idle")}</b><small>{algorithm.schedule.enabled ? t("Next run {when}.", { when: formatDate(algorithm.schedule.next_run_at) }) : t("Not on a cadence.")}</small></>}
      </div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Last run")}</span>{last ? <><Pill status={last.status} label={runLabel(last.status)} /><small>{t("{ago}, {count} signals in {duration}", { ago: formatAgo(last.finished_at ?? last.started_at), count: last.signals ?? 0, duration: formatDuration(last.duration_seconds) })}</small></> : <b>—</b>}</div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Active signals")}</span><b className="pc-num">{formatNumber(algorithm.signal_count, 0)}</b><small>{t("Every {minutes} min, {hours} h of data each", { minutes: formatNumber(algorithm.schedule.interval_minutes ?? null, 0), hours: formatNumber(algorithm.settings.window_hours, 1) })}</small></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Signal list")}</span>{sync.status === "error" ? <><Pill status="error" label={t("Sync failed")} /><small>{sync.error}</small></> : sync.at ? <><b>{t("{found} signals", { found: sync.found ?? 0 })}</b><small>{t("Read from PlantCraft {ago}: {added} added, {updated} updated, {missing} gone.", { ago: formatAgo(sync.at), added: sync.added ?? 0, updated: sync.updated ?? 0, missing: sync.missing ?? 0 })}</small></> : <b>—</b>}</div>
    </div>
    <Settings key={version} algorithm={algorithm} me={me} onSaved={(next) => { setAlgorithm(next); setVersion(version + 1); }} />
    {/* Configuration, not history (owner, 2026-10-21): where the algorithm is used; its runs are on Results > Run history. */}
    <h2 className="section-title">{t("Where it is used")}</h2>
    <div className="panel used-by">
      <p>{t("Every active signal PlantCraft knows: {count} today. The loop algorithms read its results before they judge a loop.", { count: formatNumber(algorithm.signal_count, 0) })}</p>
      <div className="row-actions">
        <Link to={resultsPath({ kind: ["signal"] })} className="button button-secondary">{t("See the signals' results")}</Link>
        <Link to="/results/runs" className="button button-secondary">{t("See its runs")}</Link>
      </div>
    </div>
  </>;
}

/** One run of the Signal quality algorithm. */
const signalPath = (signal: string) => `/signals/${encodeURIComponent(signal)}`;
const RUN_RESULT_COLUMNS: DataColumn<QualityRunResult>[] = [
  { key: "name", label: t("Signal"), sort: (row) => row.name, render: (row) => <Link to={signalPath(row.signal_id)} className="pc-mono nowrap" title={row.signal_id}>{row.name}</Link> },
  { key: "status", label: t("Result"), sort: (row) => COUNTED.indexOf(row.status as (typeof COUNTED)[number]), render: (row) => <Pill status={row.status} label={signalLabel(row.status)} /> },
  { key: "quality", label: t("Quality"), numeric: true, sort: (row) => row.quality, render: (row) => <Quality value={row.quality} /> },
  { key: "message", label: t("What it found"), className: "hide-narrow", render: (row) => <small className="clamp" title={row.message}>{row.message}</small> },
];

export function SignalRunPage({ runId, me }: { runId: string; me: Me }) {
  const [run, setRun] = useState<QualityRun | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.qualityRun(runId).then(setRun).catch((err: Error) => setError(err.message)); }, [runId]);
  if (error) return <ErrorBox text={error} />;
  if (!run) return <Loading />;
  const counts = run.counts ?? {};
  return <>
    <nav className="breadcrumb"><Link to="/results/runs">{t("Run history")}</Link><ChevronRight size={12} /><span>{t("Signal quality")} #{run.id}</span></nav>
    <Heading eyebrow={t("Run of the Signal quality algorithm")} title={t("Signal quality, {when}", { when: formatDate(run.started_at) })}
      detail={run.window_start ? t("Window {start} to {end}.", { start: formatDate(run.window_start), end: formatDate(run.window_end) }) : run.error ?? runLabel(run.status)}
      actions={<>{run.status !== "running" && <LinkAssistant kind="run" id={`${SIGNAL_RUN_PREFIX}${run.id}`} me={me} title={`${t("Signal quality")} #${run.id}`} failed={run.status === "error"} />}<Link to="/algorithms/signal_quality/settings" className="button button-secondary">{t("Monitor and checks")}</Link></>} />
    <div className="pc-grid">
      <div className="panel kpi-card"><span className="pc-overline">{t("Run")}</span><Pill status={run.status} label={runLabel(run.status)} /><small>{triggerLabel(run.trigger)}{run.started_by ? ` · ${run.started_by}` : ""}</small></div>
      <div className="panel kpi-card"><span className="pc-overline">{t("Signals")}</span><b className="kpi-value pc-num">{run.signals ?? "—"}</b><small>{t("in {duration}", { duration: formatDuration(run.duration_seconds) })}</small></div>
      <div className="panel kpi-card pc-span-2"><span className="pc-overline">{t("By result")}</span><div className="kpi-split">{COUNTED.map((key) => <Link key={key} to={resultsPath({ kind: ["signal"], status: [SUITE_OF[key] ?? "unknown"] })} className="kpi-split-item"><Pill status={key} label={signalLabel(key)} /><b className="kpi-value pc-num">{counts[key] ?? 0}</b></Link>)}</div></div>
    </div>
    {run.error && <div className="notice notice-error">{run.error}</div>}
    <h2 className="section-title">{t("Signals it judged")}</h2>
    {run.results?.length
      ? <DataTable rows={run.results} columns={RUN_RESULT_COLUMNS} rowKey={(row) => row.signal_id} onRowClick={(row) => navigate(signalPath(row.signal_id))} label={t("Signals it judged")} />
      : <div className="panel empty"><p>{run.status === "running" ? t("The run is still judging the signals.") : t("Every signal was judged again by a later run: each signal's page keeps its history.")}</p></div>}
    <p className="muted small">{t("The Signals page shows each signal's latest result; a signal's page shows its history.")}</p>
  </>;
}
