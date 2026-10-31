/** Administration › Health, Backups and Updates (administrators): the suite's health, backups and
 * their checks, restore, the restore drill, the schedule, and updates. */
import { Activity, AlertTriangle, ArchiveRestore, CalendarClock, CheckCircle2, DatabaseBackup, Download, FlaskConical, History, LoaderCircle, RefreshCw, ShieldCheck, ShieldQuestion, Sparkles, X } from "lucide-react";
import { type DataColumn, DataTable, displayTimeZone, FormSection, formatDate, Heading, timeZoneLabel, saveFile, TimeZoneSelect } from "@plantcraft/ui";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { locale, t } from "./i18n";
import { navigate } from "./nav";
import { forecastText, operationsApi, type Backup, type Certificate, type Operation, type OperationsOverview, type ServiceMetrics, type Schedule, type SuiteHealth, type SuiteStatus } from "./operationsApi";
import { useAdminView, useCanOperate, useIsAdmin } from "./session";
import "./access.css";
import "./apps.css";
import "./operations.css";

const STATES: Record<string, string> = {
  ok: t("Checked"),
  failed: t("Failed"),
  aside: t("Set aside"),
  returned: t("Returned"),
  unknown: t("Not checked"),
};
const REASONS: Record<string, string> = {
  daily: t("Daily"),
  manual: t("Manual"),
  "pre-update": t("Before an update"),
  "pre-restore": t("Before a restore"),
  "before-restore": t("Set aside by a restore"),
};
const HISTORIAN_KINDS: Record<string, string> = {
  full: t("Full"),
  incremental: t("Incremental"),
};
const ACTIONS: Record<string, string> = {
  backup: t("Backup"),
  verify: t("Check"),
  restore: t("Restore"),
  drill: t("Restore drill"),
  prune: t("Retention"),
  update: t("Suite update"),
};
const WEEKDAYS = [t("Monday"), t("Tuesday"), t("Wednesday"), t("Thursday"), t("Friday"), t("Saturday"), t("Sunday")];

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

function size(bytes?: number | null) {
  if (bytes == null) return "—";
  const format = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value);
  if (bytes < 1024 ** 2) return `${format(bytes / 1024)} KB`;
  if (bytes < 1024 ** 3) return `${format(bytes / 1024 ** 2)} MB`;
  return `${format(bytes / 1024 ** 3)} GB`;
}

/** A time as every page of the suite writes it ("Oct 27, 2026, 11:00 PM"). */
function when(value?: string | null) {
  return formatDate(value);
}

/** What the three pages share: the installer's overview, polled while an operation runs. */
function useOperations(withHealth = false) {
  const [data, setData] = useState<OperationsOverview | null>(null);
  const [health, setHealth] = useState<SuiteHealth | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const isAdmin = useAdminView();
  // The Operations role reads the health, never the backups (the overview is the admins').
  const operate = useCanOperate();
  const load = useCallback(() => Promise.all([
    isAdmin ? operationsApi.overview().then((value) => { setData(value); setError(""); }) : Promise.resolve(),
    withHealth ? operationsApi.health().then((value) => { setHealth(value); setError(""); }) : Promise.resolve(),
  ]).catch((err) => setError(message(err))), [withHealth, isAdmin]);
  useEffect(() => { if (isAdmin || (withHealth && operate)) void load(); }, [isAdmin, operate, withHealth, load]);
  // The load moves: the status page reads it again every 30 s, like the watch.
  useEffect(() => {
    if (!withHealth || !(isAdmin || operate)) return;
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [withHealth, isAdmin, operate, load]);
  const running = Boolean(data?.running);
  useEffect(() => {
    if (!running && !busy) return;
    const timer = window.setInterval(() => void load(), 3000);
    return () => window.clearInterval(timer);
  }, [running, busy, load]);
  async function act(label: string, run: () => Promise<unknown>, done: string) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await run();
      setNotice(done);
      await load();
    } catch (err) { setError(message(err)); }
    setBusy("");
  }
  return { isAdmin, operate, data, health, error, notice, setNotice, setError, busy, running, load, act };
}

type Operations = ReturnType<typeof useOperations>;

function RefreshButton({ onClick }: { onClick: () => void }) {
  return <button type="button" className="button button-secondary button-icon" title={t("Refresh")} aria-label={t("Refresh")} onClick={onClick}><RefreshCw /></button>;
}

function Notices({ ops }: { ops: Operations }) {
  return <>
    {ops.error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {ops.error}</div>}
    {ops.notice && <div className="ac-notice"><ShieldCheck size={15} /> {ops.notice}</div>}
    {!ops.data && !ops.error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
  </>;
}

function RunningChip({ data }: { data: OperationsOverview }) {
  return data.running ? <span className="apps-chip apps-chip-warn"><LoaderCircle className="spin" size={13} /> {t("{action} running: {phase}", { action: ACTIONS[data.running.action] ?? data.running.action, phase: data.running.phase ?? "" })}</span> : <span className="apps-chip">{t("No operation running")}</span>;
}

const ADMIN_ONLY_TEXT = () => <div className="module-state module-error"><AlertTriangle /><span>{t("Only admins manage health, backups and updates.")}</span></div>;
const EYEBROW = () => <><Activity size={14} /> {t("Operations")}</>;

/** Administration › Health: is every part of the suite running, and the bundle support asks for.
 * Health, Backups and Updates were one Operations page until 2026-10-24 (owner: separate them). */
export function HealthPage() {
  const ops = useOperations(true);
  const canAct = useIsAdmin();
  if (!ops.isAdmin && !ops.operate) return <HealthStatusPage />;
  const { data, health } = ops;
  return <div className="apps-page">
    <Heading eyebrow={<EYEBROW />} title={t("Status")} detail={t("The suite watches itself every 30 seconds and tells the administrators in Messages when a part of it stops or is loaded.")}
      actions={<>{canAct && <DiagnosticsButton />}<RefreshButton onClick={() => void ops.load()} /></>} />
    {ops.isAdmin ? <Notices ops={ops} /> : ops.error ? <div className="form-error" role="alert"><AlertTriangle size={15} /> {ops.error}</div> : null}
    {data && <section className="apps-status" aria-label={t("State")}>
      <span className={`apps-chip ${data.installer.online ? "apps-chip-on" : "apps-chip-warn"}`}>{data.installer.online ? t("Installer running") : t("Installer not running: requests wait until it starts")}</span>
      <RunningChip data={data} />
      {data.free_bytes != null && <span className="apps-chip">{t("Free disk: {size}", { size: size(data.free_bytes) })}</span>}
    </section>}
    {health && <HealthPanel health={health} canAct={canAct} />}
    {health?.certificates && health.certificates.length > 0 && <CertificatesPanel certificates={health.certificates} onRenewed={() => void ops.load()} />}
  </div>;
}

/** Health for everyone: whether each part of the suite runs, to check an
 * app that does not answer. Read only; the disk, backups and certificates stay with the admins. */
function HealthStatusPage() {
  const [status, setStatus] = useState<SuiteStatus | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => operationsApi.status().then((value) => { setStatus(value); setError(""); }, (err) => setError(message(err))), []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [load]);
  return <div className="apps-page">
    <Heading title={t("System health")} actions={<RefreshButton onClick={() => void load()} />} />
    {error && <div className="module-state module-error"><AlertTriangle /><span>{error}</span></div>}
    {status && (!status.watching
      ? <section className="panel apps-installed"><h2><Activity size={17} /> {t("Suite health")}</h2><p className="muted">{t("Nothing to watch: this PlantCraft runs without the suite's installer.")}</p></section>
      : <section className="panel apps-installed" aria-labelledby="ops-status-title">
        <div className="ops-health-head"><h2 id="ops-status-title"><Activity size={17} /> {t("Suite health")}</h2></div>
        <p className="muted">{t("Whether each part of the suite is running, checked every 30 s. Last check: {date}.", { date: when(status.at) })}{status.held ? ` ${t("Service checks are on hold while an operation runs or the installer is silent.")}` : ""}</p>
        {status.open.length ? <ul className="ops-incidents">{status.open.map((item) => <li key={item.incident_id}><AlertTriangle size={14} /> <strong>{item.subject}</strong>: {item.detail} <small>{t("since {date}", { date: when(item.opened_at) })}</small></li>)}</ul>
          : <p className="ops-all-good"><CheckCircle2 size={15} /> {t("Everything is running.")}</p>}
        {status.services.length > 0 && <DataTable rows={status.services} columns={serviceColumns().slice(0, 2)} rowKey={(item) => item.service} searchText={(item) => item.service} searchPlaceholder={t("Filter by name")} initialSort={{ key: "service", descending: false }} label={t("Services")} />}
      </section>)}
  </div>;
}

const CERT_USE: Record<string, string> = {
  https: "The suite's HTTPS (certs/cert.pem)",
  "https-local": "The suite's HTTPS, from its own certificate authority",
  "opcua-client": "The Historian's client certificate for OPC UA",
  "opcua-server-pinned": "An OPC UA server the Historian trusts",
};

function certState(item: Certificate): { label: string; status: string } {
  if (item.state === "auto") return { label: t("Renews by itself"), status: "running" };
  // A pinned server's end date is known once the Historian has seen its certificate.
  if (item.state === "unknown") return item.error ? { label: item.error, status: "failed" } : { label: item.use === "opcua-server-pinned" ? t("Not seen yet") : t("Unknown"), status: "unknown" };
  if (item.state === "expired") return { label: t("Expired"), status: "failed" };
  const days = Math.max(0, Math.floor(item.days_left ?? 0));
  return item.state === "expiring" ? { label: t("Expires in {days} days", { days }), status: "failed" } : { label: t("Valid, {days} days left", { days }), status: "running" };
}

function downloadPem(item: Certificate) {
  if (!item.pem) return;
  saveFile(`${item.id}.pem`, item.pem, "application/x-pem-file");
}

/** Health › Certificates: every certificate and when it expires; the
 * administrators get a message 30 days before, and a reminder 7 days before. */
function CertificatesPanel({ certificates, onRenewed }: { certificates: Certificate[]; onRenewed: () => void }) {
  const [renewing, setRenewing] = useState<Certificate | null>(null);
  // A public demo's visitor reads this page; only an administrator acts on it.
  const canAct = useIsAdmin();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [renewed, setRenewed] = useState<Certificate | null>(null);
  async function renew(item: Certificate) {
    setBusy(true);
    setError("");
    try { const value = await operationsApi.renewCertificate(item.id); setRenewed(value); setRenewing(null); onRenewed(); } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  const columns: DataColumn<Certificate>[] = [
    { key: "name", label: t("Certificate"), sort: (item) => item.name, render: (item) => <><strong>{item.name}</strong><small className="apps-sub">{t(CERT_USE[item.use] ?? item.use)}{item.source_id ? ` · ${item.source_id}` : ""}</small></> },
    { key: "not_after", label: t("Valid until"), sort: (item) => item.not_after ?? "9999", render: (item) => (item.not_after ? when(item.not_after) : "—") },
    { key: "state", label: t("State"), sort: (item) => item.days_left ?? 1e9, render: (item) => { const state = certState(item); return <span className={`apps-state apps-state-${state.status}`}>{state.label}</span>; } },
    { key: "actions", label: "", render: (item) => canAct && item.use === "opcua-client" ? <button type="button" className="button button-secondary" disabled={busy} onClick={() => setRenewing(item)}><RefreshCw size={15} /> {t("Renew")}</button> : null },
  ];
  return <section className="panel apps-installed" aria-labelledby="ops-certs-title">
    <h2 id="ops-certs-title"><ShieldCheck size={17} /> {t("Certificates")}</h2>
    <p className="muted">{t("A certificate that expires stops its connection without a word on any screen. The administrators get a message 30 days before, and a reminder 7 days before.")}</p>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {renewing && <div className="ac-notice ac-notice-warn" role="alertdialog" aria-label={t("Renew")}>
      <AlertTriangle size={15} />
      <span>{t("The OPC UA servers trust the current certificate, not a new one: until someone adds the new certificate to each server's trusted list, the Historian's secure connections are refused. Renew now?")}</span>
      <button type="button" className="button button-primary" disabled={busy} onClick={() => void renew(renewing)}>{busy && <LoaderCircle className="spin" />} {t("Renew")}</button>
      <button type="button" className="button button-secondary" onClick={() => setRenewing(null)}>{t("Cancel")}</button>
    </div>}
    {renewed && <div className="ac-notice" role="status">
      <CheckCircle2 size={15} />
      <span>{t("Renewed. Add the new certificate to the trusted list of every OPC UA server the Historian reads.")}</span>
      {renewed.pem && <button type="button" className="button button-secondary" onClick={() => downloadPem(renewed)}><Download size={15} /> {t("Download the new certificate")}</button>}
    </div>}
    <DataTable rows={certificates} columns={columns} rowKey={(item) => item.id} label={t("Certificates")} initialSort={{ key: "state", descending: false }} />
  </section>;
}

/** Administration › Backups: back up now, the schedule, the restore drill, the list and restore.
 * The schedule was Setup › Backups until 2026-10-24: one page for everything about backups. */
export function BackupsPage() {
  const ops = useOperations();
  const canAct = useIsAdmin();
  const [restoring, setRestoring] = useState<Backup | null>(null);
  if (!ops.isAdmin) return <ADMIN_ONLY_TEXT />;
  const { data, busy, running } = ops;
  const good = data?.backups.filter((item) => item.state === "ok") ?? [];
  async function save(value: Schedule) {
    ops.setError("");
    ops.setNotice("");
    try { await operationsApi.schedule(value); ops.setNotice(t("Schedule saved.")); await ops.load(); } catch (err) { ops.setError(message(err)); }
  }
  return <div className="apps-page">
    <Heading eyebrow={<EYEBROW />} title={t("Backups")} detail={t("The suite backs itself up while it runs, checks every backup before it counts, and proves each week that the latest one can be restored.")}
      actions={<>
        {canAct && <><button type="button" className="button button-primary" disabled={!data || running || !!busy} onClick={() => void ops.act("backup", () => operationsApi.start("backup"), t("Backup handed to the installer."))}>{busy === "backup" ? <LoaderCircle className="spin" /> : <DatabaseBackup />} {t("Back up now")}</button>
        <button type="button" className="button button-secondary" disabled={!data || running || !!busy || !good.length} title={t("Restores the latest good backup into a separate copy of the suite, with no network out and no port, starts it, checks it and removes it. The running suite is not touched.")} onClick={() => void ops.act("drill", () => operationsApi.start("drill"), t("Restore drill handed to the installer."))}>{busy === "drill" ? <LoaderCircle className="spin" /> : <FlaskConical />} {t("Test a restore now")}</button></>}
        <RefreshButton onClick={() => void ops.load()} />
      </>} />
    <Notices ops={ops} />
    {data && <>
      <section className="apps-status" aria-label={t("State")}>
        <RunningChip data={data} />
        <span className={`apps-chip ${good.length ? "apps-chip-on" : "apps-chip-warn"}`}>{good.length ? t("Latest good backup: {date}", { date: when(good[0].created_at) }) : t("No good backup yet")}</span>
        {data.drill && <span className={`apps-chip ${data.drill.state === "ok" ? "apps-chip-on" : "apps-chip-warn"}`}>{data.drill.state === "ok" ? t("Last restore drill passed {date}", { date: when(data.drill.at) }) : t("Last restore drill failed {date}", { date: when(data.drill.at) })}</span>}
        {data.free_bytes != null && <span className="apps-chip">{t("Free disk: {size}", { size: size(data.free_bytes) })}</span>}
      </section>
      {restoring && <RestorePanel backup={restoring} onCancel={() => setRestoring(null)} onDone={(name) => { setRestoring(null); ops.setNotice(t("Restore of {name} handed to the installer. The suite stops for a few minutes and this page comes back when it is up.", { name })); void ops.load(); }} />}
      <ScheduleForm schedule={data.schedule} onSave={save} readOnly={!canAct} />
      <BackupsTable backups={data.backups} readOnly={!canAct} disabled={running || !!busy} onVerify={(name) => void ops.act(`verify-${name}`, () => operationsApi.start("verify", name), t("Check of {name} handed to the installer.", { name }))} onRestore={setRestoring} />
      <HistoryTable history={data.history.filter((item) => item.action !== "update")} />
    </>}
  </div>;
}

/** Administration › Updates: the installed version, the last update and how to update. */
export function UpdatesPage() {
  const ops = useOperations();
  if (!ops.isAdmin) return <ADMIN_ONLY_TEXT />;
  const { data } = ops;
  return <div className="apps-page">
    <Heading eyebrow={<EYEBROW />} title={t("Updates")} detail={t("Updates back up first and return by themselves when the new version is not healthy.")}
      actions={<RefreshButton onClick={() => void ops.load()} />} />
    <Notices ops={ops} />
    {data && <>
      <UpdateCard data={data} />
      <HistoryTable history={data.history.filter((item) => item.action === "update")} />
    </>}
  </div>;
}

function RestorePanel({ backup, onCancel, onDone }: { backup: Backup; onCancel: () => void; onDone: (name: string) => void }) {
  const [typed, setTyped] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try { await operationsApi.restore(backup.name, typed, password); onDone(backup.name); } catch (err) { setError(message(err)); }
    setBusy(false);
  }
  return <section className="panel apps-preview" aria-labelledby="ops-restore-title">
    <header>
      <div><span className="eyebrow"><ArchiveRestore size={13} /> {t("Restore")}</span><h2 id="ops-restore-title"><code>{backup.name}</code></h2>
        <p>{t("Every database, setting and image returns to this backup ({date}). The suite stops for a few minutes. What is there now is set aside, not deleted, and the suite returns to it by itself if the restore does not come up healthy.", { date: when(backup.created_at) })}</p></div>
      <button className="icon-button" onClick={onCancel} aria-label={t("Cancel")}><X /></button>
    </header>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    <form className="apps-form" onSubmit={submit}>
      <label>{t("Type the backup's name")}<input required value={typed} autoComplete="off" placeholder={backup.name} onChange={(event) => setTyped(event.target.value)} /></label>
      <label>{t("Your password")}<input required type="password" value={password} autoComplete="current-password" onChange={(event) => setPassword(event.target.value)} /></label>
      <button className="button button-primary" disabled={busy || typed.trim() !== backup.name || !password}>{busy ? <LoaderCircle className="spin" size={15} /> : <ArchiveRestore size={15} />} {t("Restore this backup")}</button>
    </form>
  </section>;
}

/** What the schedule is, read only: Operations watches, Setup changes. */
export function scheduleText(schedule: Schedule): string {
  const backup = schedule.enabled ? t("Daily backup at {time}", { time: schedule.daily_at }) : t("No daily backup");
  const drill = schedule.drill ? t("restore drill on {day} at {time}", { day: WEEKDAYS[schedule.drill_weekday] ?? "", time: schedule.drill_at }) : t("no restore drill");
  return `${backup}; ${drill} (${timeZoneLabel(schedule.timezone || "local", t("Local time"))}).`;
}

function ScheduleForm({ schedule, onSave, readOnly }: { schedule: Schedule; onSave: (value: Schedule) => Promise<void>; readOnly: boolean }) {
  const [form, setForm] = useState<Schedule>(schedule);
  const [saving, setSaving] = useState(false);
  useEffect(() => setForm(schedule), [schedule]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    await onSave(form);
    setSaving(false);
  }
  const changed = JSON.stringify(form) !== JSON.stringify(schedule);
  return <form className="panel form-panel" onSubmit={(event) => void submit(event)}>
    <FormSection id="ops-schedule" icon={<CalendarClock size={17} />} title={t("Schedule")} detail={<><p>{scheduleText(schedule)}</p><p>{t("Kept: 7 daily, 4 weekly, 3 monthly and the backup before the last update.")}</p></>}>
      <div className="form-grid">
        <label className="check field-span"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /> {t("Back up every day")}</label>
        <label>{t("Daily backup time")}<input type="time" required value={form.daily_at} disabled={!form.enabled} onChange={(event) => setForm({ ...form, daily_at: event.target.value })} /></label>
        <label>{t("Time zone")}<TimeZoneSelect value={form.timezone} onChange={(timezone) => setForm({ ...form, timezone })} /></label>
        <label className="check field-span"><input type="checkbox" checked={form.drill} onChange={(event) => setForm({ ...form, drill: event.target.checked })} /> {t("Test a restore every week")}</label>
        <label>{t("Restore drill day")}<select value={form.drill_weekday} disabled={!form.drill} onChange={(event) => setForm({ ...form, drill_weekday: Number(event.target.value) })}>{WEEKDAYS.map((day, index) => <option key={day} value={index}>{day}</option>)}</select></label>
        <label>{t("Restore drill time")}<input type="time" required value={form.drill_at} disabled={!form.drill} onChange={(event) => setForm({ ...form, drill_at: event.target.value })} /></label>
      </div>
      {!readOnly && <div className="heading-actions"><button className="button button-primary" disabled={saving || !changed}>{saving && <LoaderCircle className="spin" />} {t("Save")}</button>{changed && <button type="button" className="button button-secondary" onClick={() => setForm(schedule)}>{t("Cancel")}</button>}</div>}
    </FormSection>
  </form>;
}

function UpdateCard({ data }: { data: OperationsOverview }) {
  const [notes, setNotes] = useState(false);
  const update = data.update;
  const release = data.release;
  return <section className="panel form-panel">
    <FormSection id="ops-version" icon={<Sparkles size={17} />} title={t("Version")} detail={t("To update, run install.sh from the new bundle on the server: it checks the signature, backs up, updates and verifies.")}>
      <p className="ops-version">{release?.version ? t("PlantCraft {version} is installed.", { version: release.version }) : t("The installed version is shown after the first backup.")}</p>
      {update && <div className={`ac-notice ${update.state === "ok" ? "" : "ac-notice-warn"}`}>
        {update.state === "ok" ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
        {update.state === "ok" && t("Updated from {from} to {to} on {date}.", { from: update.from ?? "", to: update.to ?? "", date: when(update.at) })}
        {update.state === "returned" && t("The update to {to} did not come up healthy; the suite returned to {from} by itself on {date}.", { from: update.from ?? "", to: update.to ?? "", date: when(update.at) })}
        {update.state === "rolled-back" && t("Rolled back from {from} to {to} on {date}.", { from: update.from ?? "", to: update.to ?? "", date: when(update.at) })}
      </div>}
      <pre className="ops-command"><code>sudo ./install.sh</code></pre>
      {release?.notes && <div className="heading-actions"><button type="button" className="button button-secondary" onClick={() => setNotes(!notes)}>{notes ? t("Hide the release notes") : t("Release notes")}</button></div>}
      {notes && release?.notes && <pre className="ops-notes">{release.notes}</pre>}
    </FormSection>
  </section>;
}

const serviceGood = (item: ServiceMetrics) => item.state === "running" && item.health !== "unhealthy";
type Levels = { warning: number; critical: number };
const DEFAULT_LEVELS: Levels = { warning: 80, critical: 95 };

const serviceColumns = (cpu: Levels = DEFAULT_LEVELS, memory: Levels = DEFAULT_LEVELS): DataColumn<ServiceMetrics>[] => [
  { key: "service", label: t("Service"), sort: (item) => item.service, render: (item) => <><strong>{item.service}</strong>{item.started_at && <small className="apps-sub">{t("since {date}", { date: when(item.started_at) })}</small>}</> },
  { key: "state", label: t("State"), sort: (item) => (serviceGood(item) ? 1 : 0), filter: { value: (item) => item.health ? `${item.state} · ${item.health}` : item.state }, render: (item) => <span className={`apps-state apps-state-${serviceGood(item) ? "running" : "failed"}`}>{item.health ? `${item.state} · ${item.health}` : item.state}</span> },
  { key: "cpu_pct", label: t("CPU"), numeric: true, sort: (item) => item.cpu_load_pct ?? item.cpu_pct, render: (item) => <LoadCell pct={item.cpu_load_pct ?? null} levels={cpu} detail={cpuDetail(item)} /> },
  { key: "mem_bytes", label: t("Memory"), numeric: true, sort: (item) => item.mem_pct ?? item.mem_bytes, render: (item) => <LoadCell pct={item.mem_pct ?? null} levels={memory} detail={item.mem_bytes != null ? t("{size} of its limit", { size: size(item.mem_bytes) }) : ""} /> },
  { key: "restarts", label: t("Restarts"), numeric: true, phone: "hide", sort: (item) => item.restarts, render: (item) => item.restarts ?? "—" },
];

/** "1.2 of 4 CPUs": what Docker's percentage of one core means for this service. */
function cpuDetail(item: ServiceMetrics): string {
  if (item.cpu_pct == null) return "";
  const used = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(item.cpu_pct / 100);
  return item.cpus ? t("{used} of {cpus} CPUs", { used, cpus: item.cpus }) : t("{used} CPUs, no limit", { used });
}

/** A load against the watch's levels (Operations › Load alerts). */
export function loadLevel(pct: number | null | undefined, levels: Levels = DEFAULT_LEVELS): "" | "warning" | "critical" {
  if (pct == null) return "";
  if (pct >= levels.critical) return "critical";
  return pct >= levels.warning ? "warning" : "";
}

function LoadCell({ pct, levels, detail }: { pct: number | null; levels: Levels; detail: string }) {
  if (pct == null) return <span className="muted">—{detail && <small className="apps-sub">{detail}</small>}</span>;
  const level = loadLevel(pct, levels);
  return <span className="ops-load">
    <span className={level ? `ops-load-${level}` : undefined}>{Math.round(pct)} %</span>
    <span className="ops-meter" aria-hidden="true"><i className={level ? `ops-meter-${level}` : undefined} style={{ width: `${Math.max(2, Math.min(100, pct))}%` }} /></span>
    {detail && <small className="apps-sub">{detail}</small>}
  </span>;
}

/** The machine the suite runs on: its CPU, memory and CPU count, beside the free disk. */
function HostLine({ health }: { health: SuiteHealth }) {
  const host = health.metrics?.host;
  const disk = health.metrics?.disk;
  if (!host && !disk) return null;
  const limits = health.limits;
  const chip = (label: string, pct: number | null | undefined, levels: Levels, extra = "") => {
    const level = loadLevel(pct, levels);
    return <span className={`apps-chip${level ? " apps-chip-warn" : ""}`}>{label}: {pct == null ? "—" : `${Math.round(pct)} %`}{extra}</span>;
  };
  return <div className="ops-host" aria-label={t("The machine")}>
    {host && chip(t("Machine CPU"), host.cpu_pct, limits ? { warning: limits.cpu_warning, critical: limits.cpu_critical } : DEFAULT_LEVELS, host.cpus ? ` · ${t("{count} CPUs", { count: host.cpus })}` : "")}
    {host && chip(t("Memory in use"), host.mem_pct, limits ? { warning: limits.memory_warning, critical: limits.memory_critical } : DEFAULT_LEVELS, host.mem_total_bytes ? ` · ${t("{size} in all", { size: size(host.mem_total_bytes) })}` : "")}
    {host?.load_1m != null && <span className="apps-chip">{t("Load average {value}", { value: host.load_1m })}</span>}
    {disk && <span className="apps-chip">{t("Free disk: {size}", { size: size(disk.free_bytes) })}{disk.free_pct != null ? ` (${disk.free_pct} %)` : ""}</span>}
  </div>;
}

function HealthPanel({ health, canAct }: { health: SuiteHealth; canAct: boolean }) {
  const limits = health.limits;
  const columns = limits ? serviceColumns({ warning: limits.cpu_warning, critical: limits.cpu_critical }, { warning: limits.memory_warning, critical: limits.memory_critical }) : serviceColumns();
  if (!health.watching) return <section className="panel apps-installed"><h2><Activity size={17} /> {t("Suite health")}</h2><p className="muted">{t("Nothing to watch: this PlantCraft runs without the suite's installer.")}</p></section>;
  const services = health.metrics?.services ?? [];
  const disk = health.metrics?.disk;
  const recent = health.recent.filter((item) => item.closed_at).slice(0, 8);
  return <section className="panel apps-installed" aria-labelledby="ops-health-title" data-tour="health">
    <div className="ops-health-head">
      <h2 id="ops-health-title"><Activity size={17} /> {t("Suite health")}</h2>
      <div className="ops-health-actions">
        {canAct && health.conversation_id != null && <button className="button button-secondary" onClick={() => navigate(`/messages/${health.conversation_id}`)}>{t("Open the conversation")}</button>}
      </div>
    </div>
    <p className="muted">{t("Checked every 30 s from Docker's health checks of each service, each one's load against its limits, the free disk, the backups and the last restore drill. Last check: {date}.", { date: when(health.at) })}{health.held ? ` ${t("Service checks are on hold while an operation runs or the installer is silent.")}` : ""}</p>
    <HostLine health={health} />
    {health.open.length ? <ul className="ops-incidents">{health.open.map((item) => <li key={item.incident_id}><AlertTriangle size={14} /> <strong>{item.subject}</strong>: {item.detail} <small>{t("since {date}", { date: when(item.opened_at) })}</small></li>)}</ul>
      : <p className="ops-all-good"><CheckCircle2 size={15} /> {t("Everything is running.")}</p>}
    {services.length > 0 && <DataTable rows={services} columns={columns} rowKey={(item) => item.service} searchText={(item) => item.service} searchPlaceholder={t("Filter by name")} initialSort={{ key: "service", descending: false }} label={t("Services")} />}
    {disk && forecastText(health.disk_forecast, size) && <p className="muted">{t("Disk: {forecast}", { forecast: forecastText(health.disk_forecast, size) })}</p>}
    {recent.length > 0 && <details className="ops-recent"><summary>{t("Recent incidents")}</summary>
      <ul className="ops-incidents">{recent.map((item) => <li key={item.incident_id}><strong>{item.subject}</strong>: {item.detail} <small>{when(item.opened_at)} → {when(item.closed_at)}</small></li>)}</ul>
    </details>}
  </section>;
}

/** "Download diagnostic bundle": the installer collects a zip (versions, Docker's view, health,
 * the end of each log, settings without secrets; never data or keys), kept 24 h. */
function DiagnosticsButton() {
  const [state, setState] = useState<{ busy: boolean; url?: string; error?: string }>({ busy: false });
  async function collect() {
    setState({ busy: true });
    try {
      const queued = await operationsApi.diagnostics();
      for (let tries = 0; tries < 150; tries += 1) {
        await new Promise((done) => window.setTimeout(done, 2000));
        const outcome = await operationsApi.outcome(queued.request_id);
        if (outcome.state === "failed") throw new Error(outcome.message || t("The diagnostic bundle could not be written."));
        if (outcome.state === "done") {
          const url = operationsApi.diagnosticsUrl(queued.request_id);
          setState({ busy: false, url });
          window.location.assign(url);
          return;
        }
      }
      throw new Error(t("The installer did not answer; is it running?"));
    } catch (err) {
      setState({ busy: false, error: err instanceof Error ? err.message : String(err) });
    }
  }
  return <>
    <button className="button button-secondary" disabled={state.busy} title={t("Versions, Docker's view of every service, health, the end of each log and the settings without any secret: what support needs. Never databases, plant data or keys.")} onClick={() => void collect()}>
      {state.busy ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />} {state.busy ? t("Collecting…") : t("Download diagnostic bundle")}
    </button>
    {state.url && !state.busy && <a className="ops-diagnostics-link" href={state.url} download>{t("Download again")}</a>}
    {state.error && <span className="ops-diagnostics-error" role="alert">{state.error}</span>}
  </>;
}

const options = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }));

/** The Historian database's part of a backup: full, or incremental on the backup before it, and
 * the newer backups that build on it (retention keeps it for them). */
function HistorianCell({ backup }: { backup: Backup }) {
  const info = backup.histcraft_db;
  if (!info) return <span className="muted">—</span>;
  return <>{HISTORIAN_KINDS[info.kind] ?? info.kind}
    <small className="apps-sub">{info.kind === "incremental" && info.base ? t("on {name}", { name: info.base }) : info.why_full ? FULL_REASONS[info.why_full] ?? info.why_full : ""}</small>
    {backup.needed_by?.length ? <small className="apps-sub">{t("Kept: {count} newer backups build on it", { count: backup.needed_by.length })}</small> : null}</>;
}

const FULL_REASONS: Record<string, string> = {
  "first backup of this database": t("First backup of this database"),
  "no good backup of this database to build on": t("No good backup to build on"),
  "the chain reached 7 backups": t("Weekly full copy"),
};

function BackupsTable({ backups, readOnly, disabled, onVerify, onRestore }: { backups: Backup[]; readOnly: boolean; disabled: boolean; onVerify: (name: string) => void; onRestore: (backup: Backup) => void }) {
  const columns: DataColumn<Backup>[] = [
    { key: "created_at", label: t("Backup"), sort: (item) => item.created_at, render: (item) => <><strong>{when(item.created_at)}</strong><small className="apps-sub"><code>{item.name}</code></small></> },
    { key: "reason", label: t("Kind"), phone: "hide", sort: (item) => REASONS[item.reason] ?? item.reason, render: (item) => REASONS[item.reason] ?? item.reason, filter: { options: options(REASONS), value: (item) => item.reason } },
    { key: "historian", label: t("Historian"), phone: "hide", sort: (item) => item.histcraft_db?.kind ?? "", filter: { options: options(HISTORIAN_KINDS), value: (item) => item.histcraft_db?.kind ?? "" }, render: (item) => <HistorianCell backup={item} /> },
    { key: "suite_version", label: t("Version"), phone: "hide", sort: (item) => item.suite_version, render: (item) => item.suite_version ?? "—", filter: true },
    { key: "size", label: t("Size"), numeric: true, sort: (item) => item.size, render: (item) => size(item.size) },
    { key: "state", label: t("State"), sort: (item) => STATES[item.state] ?? item.state, filter: { options: options(STATES), value: (item) => item.state }, render: (item) => <><span className={`apps-state apps-state-${item.state === "ok" ? "running" : "failed"}`}>{STATES[item.state] ?? item.state}</span>
      {item.problems?.length ? <small className="apps-sub">{item.problems[0]}</small> : null}
      {item.drill && <small className="apps-sub">{item.drill.state === "ok" ? t("Restore drill passed") : t("Restore drill failed: {problem}", { problem: item.drill.problems[0] ?? "" })}</small>}</> },
    { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions apps-actions", render: (item) => <>
      {!readOnly && item.state !== "aside" && item.state !== "returned" && <button className="icon-button" disabled={disabled} title={t("Check again")} onClick={() => onVerify(item.name)}><ShieldQuestion size={15} /></button>}
      {!readOnly && item.state === "ok" && <button className="icon-button" disabled={disabled} title={t("Restore")} aria-label={t("Restore {name}", { name: item.name })} onClick={() => onRestore(item)}><ArchiveRestore size={15} /></button>}
    </> },
  ];
  return <section className="panel apps-installed" aria-labelledby="ops-backups-title">
    <h2 id="ops-backups-title">{t("Backups kept")}</h2>
    {!backups.length ? <p className="muted">{t("No backups yet. The first one runs tonight, or now with Back up now.")}</p>
      : <DataTable rows={backups} columns={columns} rowKey={(item) => item.name} searchText={(item) => `${item.name} ${item.suite_version ?? ""} ${(item.problems ?? []).join(" ")}`} searchPlaceholder={t("Filter by name")} initialSort={{ key: "created_at", descending: true }} label={t("Backups")} />}
  </section>;
}

function HistoryTable({ history }: { history: OperationsOverview["history"] }) {
  if (!history.length) return null;
  const outcome = (item: Operation) => item.state === "ok" ? "ok" : item.state ?? "";
  const columns: DataColumn<Operation>[] = [
    { key: "when", label: t("When"), sort: (item) => item.finished_at ?? item.started_at, render: (item) => when(item.finished_at ?? item.started_at) },
    { key: "action", label: t("Operation"), sort: (item) => ACTIONS[item.action] ?? item.action, filter: { options: options(ACTIONS), value: (item) => item.action }, render: (item) => <>{ACTIONS[item.action] ?? item.action}{item.name ? <small className="apps-sub"><code>{item.name}</code></small> : null}</> },
    { key: "state", label: t("Outcome"), sort: outcome, filter: { value: outcome, options: [{ value: "ok", label: t("Done") }, ...[...new Set(history.map(outcome))].filter((value) => value && value !== "ok").map((value) => ({ value, label: value }))] }, render: (item) => <><span className={`apps-state apps-state-${item.state === "ok" ? "running" : "failed"}`}>{item.state === "ok" ? t("Done") : item.state ?? "—"}</span>{item.message && <small className="apps-sub">{item.message}</small>}</> },
  ];
  return <section className="panel apps-installed" aria-labelledby="ops-history-title">
    <h2 id="ops-history-title"><History size={17} /> {t("History")}</h2>
    <DataTable rows={history} columns={columns} rowKey={(item) => `${item.action}|${item.started_at ?? ""}|${item.finished_at ?? ""}|${item.name ?? ""}`} searchText={(item) => `${ACTIONS[item.action] ?? item.action} ${item.name ?? ""} ${item.message ?? ""}`} searchPlaceholder={t("Filter")} initialSort={{ key: "when", descending: true }} label={t("History")} />
  </section>;
}
