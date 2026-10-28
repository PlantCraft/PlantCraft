/** Executions: what every app of the suite runs and when, read-only (API v1 runs and schedules).
 *
 * Each app reports its runs and schedules to PlantCraft (docs/app-standard.md, section 6);
 * people start, stop or change them in the app itself, which each row links to.
 */
import { AlertTriangle, CalendarClock, ExternalLink, LoaderCircle, RefreshCw } from "lucide-react";
import { appDisplayName, DataTable, useAssistantPage, type DataColumn } from "@plantcraft/ui";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Heading } from "./CorePages";
import { locale, t } from "./i18n";
import { executionsApi, RUN_STATUSES, safeLink, type Run, type RunStatus, type Schedule } from "./executionsApi";
import { suiteApi, type SuiteApp } from "./suiteApi";
import "./executions.css";

const STATUS_LABELS: Record<RunStatus, string> = { queued: "Queued", running: "Running", done: "Done", failed: "Failed", cancelled: "Cancelled" };
const TRIGGER_LABELS: Record<Run["trigger"], string> = { manual: "Manual", schedule: "Schedule", api: "API" };

function when(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { dateStyle: "short", timeStyle: "short" }).format(date);
}

function AppLink({ url, children }: { url: string | null; children: ReactNode }) {
  const link = safeLink(url);
  if (!link) return <>{children}</>;
  return <a className="ex-link" href={link.href} {...(link.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>{children}{link.external && <ExternalLink size={12} aria-hidden="true" />}</a>;
}

export function ExecutionsPage() {
  const [apps, setApps] = useState<SuiteApp[]>([]);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [schedules, setSchedules] = useState<Schedule[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => { suiteApi.apps().then(setApps).catch(() => setApps([])); }, []);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [foundRuns, foundSchedules] = await Promise.all([executionsApi.runs("", ""), executionsApi.schedules("")]);
      setRuns(foundRuns);
      setSchedules(foundSchedules);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't load."));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const names = useMemo(() => new Map(apps.map((item) => [item.id, appDisplayName(item.id, item.name)])), [apps]);
  const appName = (id: string) => names.get(id) ?? id;
  // The assistant's work here (assistant_works/platform.py): what ran, what failed and why.
  useAssistantPage({ place: t("Runs and schedules"), page: "processcraft:executions", facts: { runs: runs?.length ?? 0, schedules: schedules?.length ?? 0 },
    view: { runs: (runs ?? []).slice(0, 25).map((run) => `${run.status} ${run.app}/${run.id} ${run.name.slice(0, 60)} ${run.started_at ?? ""}`) } });
  const appOptions = useMemo(() => {
    const ids = new Set([...apps.map((item) => item.id), ...(runs ?? []).map((run) => run.app), ...(schedules ?? []).map((item) => item.app)]);
    return [...ids].sort((a, b) => (names.get(a) ?? a).localeCompare(names.get(b) ?? b, locale)).map((id) => ({ value: id, label: names.get(id) ?? id }));
  }, [apps, runs, schedules, names]);
  const runColumns: DataColumn<Run>[] = [
    { key: "app", label: t("App"), sort: (run) => appName(run.app), render: (run) => appName(run.app), filter: { options: appOptions, value: (run) => run.app } },
    { key: "name", label: t("Run"), sort: (run) => run.name || run.id, render: (run) => <AppLink url={run.url}><strong>{run.name || run.id}</strong></AppLink> },
    { key: "status", label: t("Status"), sort: (run) => run.status, filter: { options: RUN_STATUSES.map((item) => ({ value: item, label: t(STATUS_LABELS[item]) })), value: (run) => run.status }, render: (run) => <span className={`ex-status ex-status-${run.status}`}>{t(STATUS_LABELS[run.status] ?? run.status)}</span> },
    { key: "trigger", label: t("Trigger"), sort: (run) => run.trigger, filter: { options: Object.entries(TRIGGER_LABELS).map(([value, label]) => ({ value, label: t(label) })), value: (run) => run.trigger }, render: (run) => t(TRIGGER_LABELS[run.trigger] ?? run.trigger) },
    { key: "started_at", label: t("Started"), sort: (run) => run.started_at, render: (run) => when(run.started_at) },
    { key: "finished_at", label: t("Finished"), sort: (run) => run.finished_at, render: (run) => when(run.finished_at) },
    { key: "subjects", label: t("Targets"), numeric: true, sort: (run) => run.subjects.length, render: (run) => run.subjects.length },
    { key: "summary", label: t("Summary"), className: "ex-summary", render: (run) => run.summary || "—" },
  ];
  const scheduleColumns: DataColumn<Schedule>[] = [
    { key: "app", label: t("App"), sort: (item) => appName(item.app), render: (item) => appName(item.app), filter: { options: appOptions, value: (item) => item.app } },
    { key: "name", label: t("Schedule"), sort: (item) => item.name || item.id, render: (item) => <AppLink url={item.url}><strong>{item.name || item.id}</strong></AppLink> },
    { key: "cadence", label: t("Cadence"), sort: (item) => item.cadence, render: (item) => item.cadence || "—" },
    { key: "next_run", label: t("Next run"), sort: (item) => (item.enabled ? item.next_run : null), render: (item) => (item.enabled ? when(item.next_run) : "—") },
    { key: "enabled", label: t("State"), sort: (item) => (item.enabled ? 0 : 1), filter: { options: [{ value: "on", label: t("On") }, { value: "paused", label: t("Paused") }], value: (item) => (item.enabled ? "on" : "paused") }, render: (item) => (item.enabled ? t("On") : t("Paused")) },
  ];

  return <div className="ex-page">
    <Heading
      eyebrow={t("Apps")}
      title={t("Runs and schedules")}
      description={t("What every app of the suite runs and when. Read-only: start, stop or change them in the app itself.")}
      action={<button type="button" className="button button-secondary button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={() => void load()} disabled={loading}>{loading ? <LoaderCircle className="spin" /> : <RefreshCw />}</button>}
    />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    <section className="panel ex-panel" aria-labelledby="ex-runs-title">
      <header className="panel-header"><div><h2 id="ex-runs-title">{t("Runs")}</h2><p>{t("The last 90 days, newest first.")}</p></div></header>
      {runs === null && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
      {runs !== null && !runs.length && <p className="muted ex-empty">{t("No runs reported yet.")}</p>}
      {runs !== null && runs.length > 0 && <DataTable rows={runs} columns={runColumns} rowKey={(run) => `${run.app}/${run.id}`} searchText={(run) => `${run.name} ${run.id} ${run.summary ?? ""} ${appName(run.app)}`} searchPlaceholder={t("Filter by name")} initialSort={{ key: "started_at", descending: true }} label={t("Runs")} className="ex-table" />}
    </section>
    <section className="panel ex-panel" aria-labelledby="ex-schedules-title">
      <header className="panel-header"><div><h2 id="ex-schedules-title"><CalendarClock size={16} /> {t("Schedules")}</h2><p>{t("Each app's schedules, as the app reported them.")}</p></div></header>
      {schedules !== null && !schedules.length && <p className="muted ex-empty">{t("No schedules reported yet.")}</p>}
      {schedules !== null && schedules.length > 0 && <DataTable rows={schedules} columns={scheduleColumns} rowKey={(item) => `${item.app}/${item.id}`} searchText={(item) => `${item.name} ${item.id} ${appName(item.app)}`} searchPlaceholder={t("Filter by name")} initialSort={{ key: "app", descending: false }} label={t("Schedules")} className="ex-table" />}
    </section>
  </div>;
}

export default ExecutionsPage;
