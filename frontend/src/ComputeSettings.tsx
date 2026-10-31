/** Settings › Compute (admins): the compute workers that run the apps' calculations, apart from
 * the platform and with no network of their own, and the limits of each app's tasks
 * (docs/compute.md). A worker is added here; its machine enrolls with a one-time code. */
import { AlertTriangle, Ban, Copy, Cpu, KeyRound, LoaderCircle, Pause, Play, Plus, Save, Trash2 } from "lucide-react";
import { DataTable, confirmAction, Heading } from "@plantcraft/ui";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { appLabel } from "./appMarks";
import { locale, t } from "./i18n";
import { computeApi, type ComputeEnrollment, type ComputeLimits, type ComputeOverview, type ComputeWorker } from "./computeApi";

const REFRESH_MS = 10_000;

function message(error: unknown) {
  return error instanceof Error ? error.message : t("Couldn't complete the operation.");
}

function when(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).format(date);
}

function statusText(worker: ComputeWorker) {
  switch (worker.status) {
    case "pending": return t("Waiting for its machine");
    case "expired": return t("Code expired");
    case "active": return t("Online");
    case "paused": return t("Paused");
    case "offline": return t("Offline");
    default: return t("Revoked");
  }
}

/** A task size as people read it: small (1 CPU, 1 GB), medium (2, 4 GB), large (4, 16 GB). */
function sizeText(size?: string) {
  switch (size) {
    case "medium": return t("medium (2 CPUs, 4 GB)");
    case "large": return t("large (4 CPUs, 16 GB)");
    default: return t("small (1 CPU, 1 GB)");
  }
}

function machine(worker: ComputeWorker) {
  const { cpus, load, memory_mb, memory_used_mb } = worker.stats ?? {};
  if (!cpus) return "—";
  const memory = memory_mb ? ` · ${Math.round((memory_used_mb ?? 0) / 1024)}/${Math.round(memory_mb / 1024)} GB` : "";
  return `${t("{cpus} CPUs, load {load}", { cpus, load: load ?? "—" })}${memory}`;
}

function Reveal({ enrollment, onClose }: { enrollment: ComputeEnrollment; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try { await navigator.clipboard.writeText(enrollment.command); setCopied(true); } catch { setCopied(false); }
  }
  return <div className="ac-notice ac-key-reveal">
    <KeyRound size={15} />
    <span>
      <strong>{t("Run this on the worker's machine, in the folder of the installation bundle, within {minutes} minutes. The code works once and is not shown again.", { minutes: enrollment.expires_minutes })}</strong>
      <code>{enrollment.command}</code>
    </span>
    <button type="button" className="button button-secondary" onClick={() => void copy()}><Copy size={15} /> {copied ? t("Copied") : t("Copy")}</button>
    <button type="button" className="button button-secondary" onClick={onClose}>{t("Done")}</button>
  </div>;
}

function LimitsRow({ app, name, limits, onSave }: { app: string; name: string; limits?: ComputeLimits; onSave: (app: string, timeout: number | null, memory: number | null) => Promise<void> }) {
  const [timeout, setTimeoutValue] = useState(limits?.timeout_seconds ? String(limits.timeout_seconds) : "");
  const [memory, setMemory] = useState(limits?.memory_mb ? String(limits.memory_mb) : "");
  const [busy, setBusy] = useState(false);
  const changed = timeout !== (limits?.timeout_seconds ? String(limits.timeout_seconds) : "") || memory !== (limits?.memory_mb ? String(limits.memory_mb) : "");
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    await onSave(app, timeout ? Number(timeout) : null, memory ? Number(memory) : null);
    setBusy(false);
  }
  return <form className="cp-limits-row" onSubmit={save} aria-label={t("Limits of {app}", { app: name })}>
    <strong>{name}</strong>
    <label>{t("Time per task (s)")}<input type="number" min={1} max={21600} value={timeout} placeholder="300" onChange={(event) => setTimeoutValue(event.target.value)} /></label>
    <label>{t("Memory per task (MB)")}<input type="number" min={64} max={65536} value={memory} placeholder="2048" onChange={(event) => setMemory(event.target.value)} /></label>
    <button className="button button-secondary" disabled={busy || !changed}>{busy ? <LoaderCircle className="spin" size={15} /> : <Save size={15} />} {t("Save")}</button>
  </form>;
}

export default function ComputeSettingsPage() {
  const [data, setData] = useState<ComputeOverview | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [labels, setLabels] = useState("");
  const [busy, setBusy] = useState(false);
  const [enrollment, setEnrollment] = useState<ComputeEnrollment | null>(null);
  const load = useCallback(() => computeApi.overview().then((found) => { setData(found); setError(""); }).catch((err) => setError(message(err))), []);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  async function act(run: () => Promise<unknown>) {
    try { await run(); await load(); } catch (err) { setError(message(err)); }
  }
  async function add(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    await act(async () => {
      setEnrollment(await computeApi.addWorker(name.trim(), labels.split(",").map((item) => item.trim()).filter(Boolean)));
      setName("");
      setLabels("");
    });
    setBusy(false);
  }
  const appName = (id: string) => appLabel(id, data?.apps.find((app) => app.id === id)?.name ?? id);
  const revoke = async (worker: ComputeWorker) => {
    if (!(await confirmAction(t("Revoke {name}? Its credential stops working at once and what it runs goes back to the queue.", { name: worker.name }), { confirm: t("Revoke"), danger: true }))) return;
    void act(() => computeApi.revoke(worker.id));
  };
  const remove = async (worker: ComputeWorker) => {
    if (!(await confirmAction(t("Remove {name} from the list?", { name: worker.name }), { confirm: t("Remove"), danger: true }))) return;
    void act(() => computeApi.remove(worker.id));
  };
  const saveLimits = (app: string, timeout: number | null, memory: number | null) => act(() => computeApi.setLimits(app, timeout, memory));
  const totals = (app: string) => (data?.queue ?? []).filter((row) => row.app === app).reduce((sum, row) => ({ queued: sum.queued + row.queued, running: sum.running + row.running, done: sum.done + row.done_24h, failed: sum.failed + row.failed_24h }), { queued: 0, running: 0, done: 0, failed: 0 });

  return <>
    <Heading title={t("Compute")} />
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {data?.waiting_without_worker.map((item) => <div key={`${item.app}:${item.version}:${item.environment}:${item.size}`} className="ac-notice ac-notice-warn"><AlertTriangle size={15} /> {t("{count} tasks of {app} wait and no online worker runs them (version {version}, environment {environment}, size {size}).", { count: item.queued, app: appName(item.app), version: item.version ?? "—", environment: item.environment ?? "standard", size: sizeText(item.size) })}</div>)}
    <section className="panel ac-users ac-keys" aria-labelledby="compute-workers-title">
      <header className="ac-keys-head">
        <div><h2 id="compute-workers-title"><Cpu size={17} /> {t("Workers")}</h2><p>{t("A worker asks the platform for tasks; it opens no port. Its machine enrolls once with a code from here. Pausing lets it end what it runs; revoking stops its credential at once.")}</p></div>
      </header>
      {enrollment && <Reveal enrollment={enrollment} onClose={() => setEnrollment(null)} />}
      <form className="ac-keys-form" onSubmit={add}>
        <label>{t("Name")}<input required maxLength={80} value={name} placeholder={t("E.g. compute-2")} onChange={(event) => setName(event.target.value)} /></label>
        <label>{t("Labels (optional, comma separated)")}<input maxLength={400} value={labels} placeholder="gpu, large" onChange={(event) => setLabels(event.target.value)} /></label>
        <button className="button button-primary" disabled={busy || !name.trim()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} {t("Add worker")}</button>
      </form>
      {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading workers…")}</span></div>}
      {data && !data.workers.length && <p className="muted ac-keys-empty">{t("No workers yet: the apps' calculations wait until one is online.")}</p>}
      {data && data.workers.length > 0 && <DataTable rows={data.workers} rowKey={(worker) => worker.id} label={t("Workers")} rowClassName={(worker) => (worker.status === "revoked" ? "ac-inactive" : undefined)} initialSort={{ key: "name", descending: false }}
        columns={[
          { key: "name", label: t("Name"), sort: (worker) => worker.name, render: (worker) => <><strong>{worker.name}</strong>{worker.labels.length > 0 && <span className="cp-labels">{worker.labels.join(", ")}</span>}</> },
          { key: "status", label: t("Status"), sort: (worker) => worker.status, filter: { value: statusText }, render: (worker) => <span className={`cp-status cp-${worker.status}`}>{statusText(worker)}</span> },
          { key: "apps", label: t("Runs"), render: (worker) => worker.executors.length ? worker.executors.map((item) => `${appName(item.app)} ${item.version ?? ""}${item.environment && item.environment !== "standard" ? ` [${item.environment}]` : ""} (${item.free ?? "?"}/${item.slots ?? "?"})`).join(" · ") : "—" },
          { key: "machine", label: t("Machine"), render: (worker) => <>{worker.host && <code>{worker.host}</code>} {machine(worker)}{worker.largest_size && <span className="cp-labels">{t("Takes tasks up to {size}", { size: sizeText(worker.largest_size) })}</span>}</> },
          { key: "tasks", label: t("Tasks (24 h)"), sort: (worker) => worker.done_24h, render: (worker) => t("{running} running, {done} done, {failed} failed", { running: worker.running, done: worker.done_24h, failed: worker.failed_24h }) },
          { key: "seen", label: t("Last seen"), sort: (worker) => worker.last_seen_at, render: (worker) => when(worker.last_seen_at) },
          { key: "actions", label: <span className="sr-only">{t("Actions")}</span>, className: "ac-row-actions", render: (worker) => <>
            {(worker.status === "pending" || worker.status === "expired") && <button className="icon-button" title={t("New code")} aria-label={t("New code for {name}", { name: worker.name })} onClick={() => void act(async () => setEnrollment(await computeApi.newCode(worker.id)))}><KeyRound size={15} /></button>}
            {worker.state === "active" && <button className="icon-button" title={t("Pause")} aria-label={t("Pause {name}", { name: worker.name })} onClick={() => void act(() => computeApi.pause(worker.id))}><Pause size={15} /></button>}
            {worker.state === "paused" && <button className="icon-button" title={t("Resume")} aria-label={t("Resume {name}", { name: worker.name })} onClick={() => void act(() => computeApi.resume(worker.id))}><Play size={15} /></button>}
            {worker.state !== "revoked" && <button className="icon-button" title={t("Revoke")} aria-label={t("Revoke {name}", { name: worker.name })} onClick={() => revoke(worker)}><Ban size={15} /></button>}
            {(worker.state === "revoked" || worker.status === "expired") && <button className="icon-button" title={t("Remove")} aria-label={t("Remove {name}", { name: worker.name })} onClick={() => remove(worker)}><Trash2 size={15} /></button>}
          </> },
        ]} />}
    </section>
    <section className="panel ac-users ac-keys" aria-labelledby="compute-apps-title">
      <header className="ac-keys-head">
        <div><h2 id="compute-apps-title">{t("Apps")}</h2><p>{t("What each app has waiting and running, and the most time and memory one of its tasks may take. Empty: the suite's defaults (300 s, 2048 MB).")}</p></div>
      </header>
      {data && <div className="cp-apps">
        {data.apps.map((app) => {
          const sum = totals(app.id);
          return <div key={app.id} className="cp-app">
            <LimitsRow app={app.id} name={appLabel(app.id, app.name)} limits={data.limits[app.id]} onSave={saveLimits} />
            <span className="muted">{t("{queued} waiting, {running} running, {done} done and {failed} failed in 24 h", { queued: sum.queued, running: sum.running, done: sum.done, failed: sum.failed })}</span>
          </div>;
        })}
      </div>}
    </section>
  </>;
}
