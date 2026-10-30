/**
 * The suite's work queues in every app's sidebar: one of the four quick
 * buttons (round 8, 2026-10-24) says what runs and waits across the suite ("4 running · 12
 * waiting"), and opens a panel with each app's numbers and a link to its executions. It reads the same
 * `GET <app>/api/queue` the app's own QueuePanel draws (format `plantcraft-queue/1`,
 * `plantcraft_sdk.server.queue`); an app without a queue (404, another format) is asked once
 * and then left alone, so the line shows only when some app queues work.
 */
import { ChevronRight, CircleAlert, CircleCheck, Hourglass, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AppMark } from "./Brand.js";
import { appIdFor, appLabel } from "./appMarks.js";
import { formatAgo, formatDuration, formatNumber } from "./format.js";
import { t } from "./i18n.js";
import { QUEUE_FORMAT, type QueueNow } from "./Queue.js";
import { claimPanel, registerPanel, SidePanel, usePresence } from "./SidePanel.js";
import type { SuiteApp } from "./SuiteShell.js";
import { runNoticeAction } from "./UrgentNotice.js";

/** How often the line asks again while the page is visible. */
export const SUITE_QUEUE_POLL_MS = 30_000;
/** The oldest item has waited this long: the line turns to attention. */
export const QUEUE_LATE_SECONDS = 30 * 60;

/** One piece of work in the Queue panel (docs/quick-access.md): a run an app wrote to PlantCraft
 * or an item of an app's own queue (an app without an app key, Historian). */
export type QueueJob = {
  app: string;
  appName: string;
  id: string;
  name: string;
  status: string;
  by: string | null;
  progress: number | null;
  step: string;
  url: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  /** A path of the app, POSTed as the person, while it can be cancelled. */
  cancel: { label: string; href: string } | null;
};

export type AppQueue = { app: string; appName: string; url: string; now: QueueNow; items?: QueueJob[] };

const ACTIVE = new Set(["queued", "running"]);

function suitePath(value: unknown): string | null {
  return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\") ? value : null;
}

/** A run of `GET /api/v1/queue` or an item of `GET <app>/api/queue` as the panel draws it; null when it is not one. */
export function queueJob(raw: unknown, app: string, appName: string): QueueJob | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Record<string, unknown>;
  const id = typeof item.id === "string" || typeof item.id === "number" ? String(item.id) : "";
  if (!id || typeof item.status !== "string") return null;
  const text = (value: unknown) => (typeof value === "string" ? value : null);
  const progress = typeof item.progress === "number" && Number.isFinite(item.progress) ? Math.min(1, Math.max(0, item.progress)) : null;
  // A run names the path to cancel; an app's own queue may give the whole button.
  const rawCancel = item.cancel as unknown;
  const cancelHref = typeof rawCancel === "string" ? suitePath(rawCancel) : rawCancel && typeof rawCancel === "object" ? suitePath((rawCancel as Record<string, unknown>).href) : null;
  const cancelLabel = rawCancel && typeof rawCancel === "object" && typeof (rawCancel as Record<string, unknown>).label === "string" ? String((rawCancel as Record<string, unknown>).label) : t("Cancel");
  return {
    app: typeof item.app === "string" ? item.app : app,
    // A run of a suite app reads by the suite's name for it ("Models", "Analytics"), as the
    // app's own queue does, not by the manifest's ("PlantCraft Models", "PlantCraft Analytics").
    appName: typeof item.app === "string" ? appLabel(item.app, typeof item.app_name === "string" ? item.app_name : appName) : typeof item.app_name === "string" ? item.app_name : appName,
    id,
    name: text(item.name) || text(item.file_name) || id,
    status: item.status === "error" ? "failed" : item.status,
    by: text(item.by),
    progress,
    step: text(item.step) ?? "",
    url: suitePath(item.url),
    startedAt: text(item.started_at),
    finishedAt: text(item.finished_at),
    cancel: cancelHref && ACTIVE.has(item.status) ? { label: cancelLabel, href: cancelHref } : null,
  };
}

export type SuiteQueueTotals = { queued: number; running: number; workers: number; failedHour: number; delaySeconds: number; late: boolean };

function base(app: SuiteApp): string {
  return app.url.endsWith("/") ? app.url : `${app.url}/`;
}

/** One app's queue now; "none" when the app has no queue of this format (it is not asked again), null on a passing failure. */
export async function fetchAppQueue(app: SuiteApp, fetcher: typeof fetch = fetch): Promise<AppQueue | "none" | null> {
  try {
    const response = await fetcher(`${base(app)}api/queue?window=1h`, { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (response.status === 404 || response.status === 405) return "none";
    if (!response.ok) return null;
    const body = (await response.json()) as { format?: unknown; now?: unknown } | null;
    if (!body || body.format !== QUEUE_FORMAT || !body.now || typeof body.now !== "object") return "none";
    const appName = appLabel(app.id, app.name);
    // The app's own page of its queue (`url`, relative to its prefix or a path of the suite), else its executions.
    const own = (body as { url?: unknown }).url;
    const url = typeof own === "string" && own && !own.startsWith("//") && !/^[a-z]+:/i.test(own) ? (own.startsWith("/") ? own : `${base(app)}${own.replace(/^\.?\//, "")}`) : `${base(app)}executions`;
    const rawItems = (body as { items?: unknown }).items;
    const items = Array.isArray(rawItems) ? rawItems.flatMap((item) => { const job = queueJob(item, app.id, appName); return job ? [job] : []; }) : undefined;
    return { app: app.id, appName, url, now: body.now as QueueNow, ...(items ? { items } : {}) };
  } catch {
    return null;
  }
}

/** The numbers of the line: summed over the apps, the longest wait, late past QUEUE_LATE_SECONDS. */
export function queueTotals(queues: AppQueue[]): SuiteQueueTotals {
  const sum = (pick: (now: QueueNow) => number) => queues.reduce((total, item) => total + (Number(pick(item.now)) || 0), 0);
  const delaySeconds = queues.reduce((most, item) => Math.max(most, item.now.queued > 0 ? Number(item.now.delay_seconds) || 0 : 0), 0);
  return { queued: sum((now) => now.queued), running: sum((now) => now.running), workers: sum((now) => now.workers), failedHour: sum((now) => now.failed_hour), delaySeconds, late: delaySeconds >= QUEUE_LATE_SECONDS };
}

/** The line's text: "Nothing running", "3 running", "3 running · 12 waiting". */
export function queueLine(totals: SuiteQueueTotals): string {
  if (!totals.running && !totals.queued) return t("Queue idle");
  const parts = [t("{count} running", { count: formatNumber(totals.running, 0) })];
  if (totals.queued) parts.push(t("{count} waiting", { count: formatNumber(totals.queued, 0) }));
  return parts.join(" · ");
}

/** Every app's queue, asked at once, every SUITE_QUEUE_POLL_MS while the page is visible and when it gets the focus again. */
export function useSuiteQueues(apps: SuiteApp[], options: { enabled?: boolean; fetcher?: typeof fetch } = {}): AppQueue[] {
  const { enabled = true, fetcher = fetch } = options;
  const [queues, setQueues] = useState<Record<string, AppQueue>>({});
  const none = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!enabled || !apps.length) return;
    let live = true;
    const read = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      for (const app of apps) {
        if (none.current.has(app.id)) continue;
        void fetchAppQueue(app, fetcher).then((found) => {
          if (!live || found === null) return;
          if (found === "none") {
            none.current.add(app.id);
            setQueues((current) => {
              if (!(app.id in current)) return current;
              const next = { ...current };
              delete next[app.id];
              return next;
            });
            return;
          }
          setQueues((current) => ({ ...current, [app.id]: found }));
        });
      }
    };
    read();
    const timer = window.setInterval(read, SUITE_QUEUE_POLL_MS);
    window.addEventListener("focus", read);
    return () => {
      live = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", read);
    };
  }, [apps, enabled, fetcher]);
  return apps.flatMap((app) => (queues[app.id] ? [queues[app.id]] : []));
}

/** `GET /api/v1/queue`: what the person started and what runs now, from the runs apps write. */
export type SuiteJobs = { me: string | null; mine: QueueJob[]; running: QueueJob[] };

/** The platform's list for the panel; null when PlantCraft has none (an older version) or on a failure. */
export async function fetchSuiteJobs(fetcher: typeof fetch = fetch): Promise<SuiteJobs | null> {
  try {
    const response = await fetcher("/api/v1/queue", { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const body = (await response.json()) as { me?: unknown; mine?: unknown; running?: unknown } | null;
    if (!body || typeof body !== "object") return null;
    const list = (value: unknown) => (Array.isArray(value) ? value.flatMap((item) => { const job = queueJob(item, "", ""); return job && job.app ? [job] : []; }) : []);
    return { me: typeof body.me === "string" ? body.me : null, mine: list(body.mine), running: list(body.running) };
  } catch {
    return null;
  }
}

const jobKey = (job: QueueJob) => `${job.app}/${job.id}`;
const byRecent = (a: QueueJob, b: QueueJob) => Number(ACTIVE.has(b.status)) - Number(ACTIVE.has(a.status)) || String(b.startedAt ?? b.finishedAt ?? "").localeCompare(String(a.startedAt ?? a.finishedAt ?? ""));

/** One app of the panel: its numbers (from its own queue, else counted from its jobs), its jobs
 * newest first (what runs and waits on top), and how many of the active ones I started. */
export type AppJobs = { app: string; appName: string; url: string | null; now: QueueNow | null; jobs: QueueJob[]; mineActive: number };

/** The panel's apps (the overview first, an app's jobs when it is opened): every
 * app with a queue, in the shell's order, then the apps only the platform's runs name. */
export function jobsByApp(platform: SuiteJobs | null, queues: AppQueue[]): AppJobs[] {
  const me = platform?.me ?? null;
  const all = new Map<string, QueueJob>();
  for (const job of [...(platform?.mine ?? []), ...(platform?.running ?? []), ...queues.flatMap((queue) => queue.items ?? [])]) if (!all.has(jobKey(job))) all.set(jobKey(job), job);
  const grouped = new Map<string, QueueJob[]>();
  for (const job of all.values()) grouped.set(job.app, [...(grouped.get(job.app) ?? []), job]);
  const entry = (app: string, appName: string, url: string | null, now: QueueNow | null): AppJobs => {
    const jobs = (grouped.get(app) ?? []).sort(byRecent);
    return { app, appName, url, now, jobs, mineActive: jobs.filter((job) => me !== null && job.by === me && ACTIVE.has(job.status)).length };
  };
  const found = queues.map((queue) => entry(queue.app, queue.appName, queue.url, queue.now));
  for (const [app, jobs] of grouped) if (!queues.some((queue) => queue.app === app)) found.push(entry(app, jobs[0].appName || app, null, null));
  return found;
}

/** One compute worker as the Queue panel shows it under an app (`GET /api/compute/summary`,
 * anyone signed in): no host, label or credential. */
export type ComputeWorkerSummary = { name: string; status: string; environments: string[]; slots: number; running: number; largestSize: string };
/** The suite's compute workers per app; an app that sends no tasks to them is absent. */
export type ComputeSummary = Record<string, { queued: number; running: number; workers: ComputeWorkerSummary[] }>;

/** The workers per app; null when PlantCraft has no compute summary (an older version) or on a failure. */
export async function fetchComputeSummary(fetcher: typeof fetch = fetch): Promise<ComputeSummary | null> {
  try {
    const response = await fetcher("/api/compute/summary", { credentials: "same-origin", headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const body = (await response.json()) as { apps?: unknown } | null;
    if (!body || !body.apps || typeof body.apps !== "object") return null;
    const found: ComputeSummary = {};
    const count = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : 0);
    for (const [app, raw] of Object.entries(body.apps as Record<string, unknown>)) {
      if (!raw || typeof raw !== "object") continue;
      const entry = raw as Record<string, unknown>;
      const workers = Array.isArray(entry.workers) ? entry.workers.flatMap((item): ComputeWorkerSummary[] => {
        if (!item || typeof item !== "object" || typeof (item as Record<string, unknown>).name !== "string") return [];
        const worker = item as Record<string, unknown>;
        return [{
          name: String(worker.name),
          status: typeof worker.status === "string" ? worker.status : "offline",
          environments: Array.isArray(worker.environments) ? worker.environments.filter((env): env is string => typeof env === "string") : [],
          slots: count(worker.slots),
          running: count(worker.running),
          largestSize: typeof worker.largest_size === "string" ? worker.largest_size : "small",
        }];
      }) : [];
      found[app] = { queued: count(entry.queued), running: count(entry.running), workers };
    }
    return found;
  } catch {
    return null;
  }
}

/** The workers per app while the panel is open, every QUEUE_OPEN_POLL_MS. */
export function useComputeSummary(open: boolean, fetcher: typeof fetch = fetch): ComputeSummary | null {
  const [summary, setSummary] = useState<ComputeSummary | null>(null);
  useEffect(() => {
    if (!open) return;
    let live = true;
    const read = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void fetchComputeSummary(fetcher).then((found) => { if (live) setSummary(found); });
    };
    read();
    const timer = window.setInterval(read, QUEUE_OPEN_POLL_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [open, fetcher]);
  return summary;
}

const WORKER_STATUS: Record<string, () => string> = {
  active: () => t("Online"),
  paused: () => t("Paused"),
  offline: () => t("Offline"),
};

/** The sizes of docs/compute.md as people read them. */
const SIZE_LABELS: Record<string, () => string> = {
  small: () => t("small tasks (1 CPU, 1 GB)"),
  medium: () => t("tasks up to medium (2 CPUs, 4 GB)"),
  large: () => t("tasks up to large (4 CPUs, 16 GB)"),
};

/** The compute workers that run an app's tasks, under the app opened in the Queue panel. */
export function AppWorkers({ workers, appName }: { workers: ComputeWorkerSummary[]; appName: string }) {
  if (!workers.length) return <p className="pc-queue-warn pc-queue-workers-none">{t("No compute worker runs {app}'s tasks: they wait until an administrator adds one (Settings › Compute).", { app: appName })}</p>;
  return (
    <div className="pc-queue-workers">
      <small className="pc-queue-workers-title">{t("Compute workers")}</small>
      <ul>
        {workers.map((worker) => (
          <li key={worker.name} className={`pc-queue-worker pc-queue-worker-${worker.status}`}>
            <span className="pc-queue-worker-dot" aria-hidden="true" />
            <span className="pc-queue-worker-text">
              <strong>{worker.name}</strong>
              <small>{[(WORKER_STATUS[worker.status] ?? (() => worker.status))(), t("{running} of {slots} running", { running: worker.running, slots: worker.slots }), worker.environments.join(", "), (SIZE_LABELS[worker.largestSize] ?? SIZE_LABELS.small)()].filter(Boolean).join(" · ")}</small>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** How often the panel's lists are read while it is open (the button keeps SUITE_QUEUE_POLL_MS). */
export const QUEUE_OPEN_POLL_MS = 5_000;

/** The platform's list, while `enabled`: every SUITE_QUEUE_POLL_MS, every QUEUE_OPEN_POLL_MS while the panel is open. */
export function useSuiteJobs(enabled: boolean, open: boolean, fetcher: typeof fetch = fetch): [SuiteJobs | null, () => void] {
  const [jobs, setJobs] = useState<SuiteJobs | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    const read = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void fetchSuiteJobs(fetcher).then((found) => { if (live && found) setJobs(found); });
    };
    read();
    const timer = window.setInterval(read, open ? QUEUE_OPEN_POLL_MS : SUITE_QUEUE_POLL_MS);
    return () => { live = false; window.clearInterval(timer); };
  }, [enabled, open, fetcher, tick]);
  return [jobs, () => setTick((value) => value + 1)];
}

let queuesOpen = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };

/** Open the work queues' panel (one panel at a time, SidePanel.tsx). */
export function openQueues() { claimPanel("queues"); queuesOpen = true; emit(); }
export function closeQueues() { if (!queuesOpen) return; queuesOpen = false; emit(); }
export function useQueuesOpen(): boolean { return useSyncExternalStore(subscribe, () => queuesOpen, () => false); }
registerPanel("queues", closeQueues, () => queuesOpen);

/** What the button and the panel say about the queues now: the line, the hint and the tone. */
function queueSummary(queues: AppQueue[]) {
  const totals = queueTotals(queues);
  const line = queueLine(totals);
  const busy = totals.running > 0 || totals.queued > 0;
  const attention = totals.late || totals.failedHour > 0;
  const hint = [line, totals.late ? t("the oldest has waited {time}", { time: formatDuration(totals.delaySeconds) }) : "", totals.failedHour ? t("{count} failed in the last hour", { count: totals.failedHour }) : ""].filter(Boolean).join(", ");
  return { totals, line, busy, attention, hint };
}

/** How long the button stays green after the last running work finished well. */
export const QUEUE_DONE_MS = 8_000;

/** What the button shows: failed (red, until the person opens the panel),
 * running (a turning circle), done (green, for a moment after the last run finished well), late
 * (the oldest has waited long), waiting, idle. */
export type QueueLook = "failed" | "running" | "done" | "late" | "waiting" | "idle";

export function queueLook(totals: SuiteQueueTotals, { unseenFailures, justDone }: { unseenFailures: boolean; justDone: boolean }): QueueLook {
  if (unseenFailures) return "failed";
  if (totals.running > 0) return "running";
  if (justDone) return "done";
  if (totals.late) return "late";
  if (totals.queued > 0) return "waiting";
  return "idle";
}

const LOOK_ICONS: Record<QueueLook, typeof Hourglass> = { failed: CircleAlert, running: LoaderCircle, done: CircleCheck, late: Hourglass, waiting: Hourglass, idle: Hourglass };

/** The work queues' quick button in the sidebar (round 8: one of the four, beside Messages). Its
 * look follows the queues (`queueLook`), the count is what runs and waits. Hidden while no app
 * queues work. */
export function SuiteQueueButton({ queues, collapsed }: { queues: AppQueue[]; collapsed: boolean }) {
  const open = useQueuesOpen();
  const { totals, hint } = queueSummary(queues);
  // Failures the person has seen (the panel was open with them); the count is of the last hour,
  // so it also goes down by itself.
  const seenFailed = useRef(totals.failedHour);
  if (open || totals.failedHour < seenFailed.current) seenFailed.current = totals.failedHour;
  // Green for a moment when the last running work finished and nothing new failed.
  const before = useRef({ running: totals.running, failed: totals.failedHour });
  const [doneUntil, setDoneUntil] = useState(0);
  useEffect(() => {
    const was = before.current;
    before.current = { running: totals.running, failed: totals.failedHour };
    if (was.running > 0 && totals.running === 0 && totals.failedHour <= was.failed) {
      setDoneUntil(Date.now() + QUEUE_DONE_MS);
      const timer = window.setTimeout(() => setDoneUntil(0), QUEUE_DONE_MS);
      return () => window.clearTimeout(timer);
    }
  }, [totals.running, totals.failedHour]);
  if (!queues.length) return null;
  const look = queueLook(totals, { unseenFailures: totals.failedHour > seenFailed.current, justDone: doneUntil > Date.now() });
  const Icon = LOOK_ICONS[look];
  const count = totals.queued + totals.running;
  const label = t("Queues: {line}", { line: hint });
  return (
    <button type="button" className={`pcs-quick-button pcs-queue-button pcs-queue-${look}${open ? " pcs-active" : ""}`} data-look={look} onClick={() => (open ? closeQueues() : openQueues())} aria-pressed={open} aria-label={label} title={collapsed ? label : hint}>
      <Icon size={18} aria-hidden="true" className={look === "running" ? "pcs-spin" : undefined} />
      {count > 0 && <b className="pcs-badge" aria-hidden="true">{count > 99 ? "99+" : count}</b>}
    </button>
  );
}

const STATUS_LABELS: Record<string, () => string> = {
  queued: () => t("Waiting"),
  running: () => t("Running"),
  done: () => t("Done"),
  failed: () => t("Failed"),
  cancelled: () => t("Cancelled"),
};

/** One piece of work: its name and app, how far it went, what it does now, Cancel while it can. */
function JobRow({ job, onChanged }: { job: QueueJob; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const cancel = async () => {
    if (!job.cancel) return;
    setBusy(true);
    const answer = await runNoticeAction(job.cancel.href);
    setBusy(false);
    setProblem(answer.ok ? "" : answer.message);
    if (answer.ok) onChanged();
  };
  const family = appIdFor(job.app);
  const percent = job.progress === null ? null : Math.round(job.progress * 100);
  const when = job.finishedAt && !ACTIVE.has(job.status) ? formatAgo(job.finishedAt) : job.startedAt ? formatAgo(job.startedAt) : "";
  const title = <strong>{job.name}</strong>;
  return (
    <li className={`pc-job pc-job-${job.status}`}>
      {family ? <AppMark app={family} size={22} /> : <span className="pcs-app-fallback">{job.appName.slice(0, 1)}</span>}
      <div className="pc-job-main">
        <div className="pc-job-top">{job.url ? <a href={job.url}>{title}</a> : title}<span className={`pc-job-status pc-job-status-${job.status}`}>{(STATUS_LABELS[job.status] ?? (() => job.status))()}{percent !== null && ACTIVE.has(job.status) ? ` · ${percent} %` : ""}</span></div>
        {job.status === "running" && percent !== null && <div className="pc-job-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={job.name}><i style={{ width: `${percent}%` }} /></div>}
        <small>{[job.appName, job.step, when].filter(Boolean).join(" · ")}</small>
        {problem && <small className="pc-queue-warn">{problem}</small>}
      </div>
      {job.cancel && <button type="button" className="pc-job-cancel" disabled={busy} onClick={() => void cancel()}>{busy ? t("Working…") : job.cancel.label}</button>}
    </li>
  );
}

/** One app in the panel: its mark, name and numbers; opened, its jobs and a link to its own page. */
function AppQueueRow({ item, open, workers, onToggle, onChanged }: { item: AppJobs; open: boolean; workers?: ComputeWorkerSummary[]; onToggle: () => void; onChanged: () => void }) {
  const family = appIdFor(item.app);
  const now = item.now;
  const running = now ? now.running : item.jobs.filter((job) => job.status === "running").length;
  const queued = now ? now.queued : item.jobs.filter((job) => job.status === "queued").length;
  const failed = now ? now.failed_hour : 0;
  const warn = (now ? now.delay_seconds >= QUEUE_LATE_SECONDS : false) || failed > 0;
  const numbers = now ? t("{running} of {workers} running · {queued} waiting", { running, workers: now.workers, queued }) : t("{running} running · {queued} waiting", { running, queued });
  const detail = [now && queued > 0 ? t("oldest waiting {time}", { time: formatDuration(now.delay_seconds) }) : "", failed > 0 ? t("{count} failed in the last hour", { count: failed }) : ""].filter(Boolean).join(" · ");
  const panelId = `pc-queue-app-${item.app.replace(/[^a-z0-9_-]/gi, "-")}`;
  return (
    <li className={`pc-queue-entry${open ? " pc-queue-entry-open" : ""}`}>
      <button type="button" className="pc-queue-app" aria-expanded={open} aria-controls={panelId} onClick={onToggle}>
        {family ? <AppMark app={family} size={22} /> : <span className="pcs-app-fallback">{item.appName.slice(0, 1)}</span>}
        <span className="pc-queue-app-text">
          <strong>{item.appName}{item.mineActive > 0 && <em className="pc-queue-mine">{t("{count} mine", { count: item.mineActive })}</em>}</strong>
          <small>{numbers}</small>
          {detail && <small className={warn ? "pc-queue-warn" : undefined}>{detail}</small>}
        </span>
        <ChevronRight size={16} aria-hidden="true" className="pc-queue-chevron" />
      </button>
      {open && (
        <div id={panelId} className="pc-queue-jobs">
          {workers && <AppWorkers workers={workers} appName={item.appName} />}
          {item.jobs.length ? <ul className="pc-job-list">{item.jobs.map((job) => <JobRow key={jobKey(job)} job={job} onChanged={onChanged} />)}</ul> : <p className="pc-drawer-wait">{t("Nothing listed by name in the last day.")}</p>}
          {item.url && <a className="pc-queue-open" href={item.url}>{t("Open {app}'s executions", { app: item.appName })}</a>}
        </div>
      )}
    </li>
  );
}

/** The work queues' panel (docs/quick-access.md): each app's numbers first; an
 * app opened lists its work (mine marked, progress, Cancel while it can, what ended in the last
 * day) and links to its own page of its queue. */
export function SuiteQueueHost({ queues, fullHref, jobs = null, onChanged = () => {} }: { queues: AppQueue[]; fullHref?: string | null; jobs?: SuiteJobs | null; onChanged?: () => void }) {
  const shown = useQueuesOpen();
  const { value: open, leaving } = usePresence(shown ? true : null);
  const compute = useComputeSummary(shown);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  if (!open) return null;
  const { line, attention, hint } = queueSummary(queues);
  const apps = jobsByApp(jobs, queues);
  const toggle = (app: string) => setOpened((current) => { const next = new Set(current); if (next.has(app)) next.delete(app); else next.add(app); return next; });
  return (
    <SidePanel label={t("Queues")} subtitle={hint || line} icon={<Hourglass size={18} aria-hidden="true" />} fullHref={fullHref} leaving={leaving} className="pc-queue-panel" onClose={closeQueues}>
      <div className="pc-drawer-body">
        {!apps.length && <p className="pc-drawer-wait">{t("No app has a queue here.")}</p>}
        <ul className={`pc-queue-list${attention ? " pc-queue-list-attention" : ""}`}>
          {apps.map((item) => <AppQueueRow key={item.app} item={item} open={opened.has(item.app)} workers={compute?.[item.app]?.workers} onToggle={() => toggle(item.app)} onChanged={onChanged} />)}
        </ul>
      </div>
    </SidePanel>
  );
}
