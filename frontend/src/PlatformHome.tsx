/** PlantCraft's Overview (/admin): is the installation healthy? Widgets each person arranges;
 *the default board is the installation's health only:
 * what answers, the data connections, the system and the last changes. The apps' widgets, what
 * needs attention and the apps stay in the catalog; each person's day is Desk's first page
 * (Desk.tsx). What needs attention is listed on its own page (/attention). */
import { ArrowRight, CheckCircle2, LoaderCircle, Settings2 } from "lucide-react";
import { DataTable, useAssistantPage, fetchSuiteWidgets, formatAgo, MultiSelect, Pill, statusVar, useOverviewLayout, WidgetBoard, type BoardItem, type DataColumn, type WidgetDef } from "@plantcraft/ui";
import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { api } from "./api";
import { AppLauncher } from "./AppLauncher";
import { appLabel } from "./appMarks";
import { t } from "./i18n";
import { navigate } from "./nav";
import { RecentChanges, SystemWidget } from "./SystemWidgets";
import type { HomeAttention, HomeData, HomeJourney, HomeStatus, LiveState } from "./types";
import "./home.css";

const EMPTY: HomeJourney = { last_run: null, schedules: 0, findings: {}, actions: { open: 0, overdue: 0, done: 0, total: 0 } };
const STATUS_LABELS: Record<string, string> = { alarm: t("Critical"), warning: t("Warning"), unknown: t("Unknown"), ok: t("OK") };
const LIVE_LABELS: Record<LiveState, string> = { online: t("Online"), offline: t("Offline"), off: t("Turned off"), unknown: t("No news") };
const LIVE_STATUS: Record<LiveState, string> = { online: "ok", offline: "alarm", off: "unknown", unknown: "unknown" };
const STATUS_EVERY_MS = 60_000;

/** Whether the plant is set up enough for the apps to work: signals and assets. */
export function plantReady(data: HomeData): boolean {
  const assets = Object.values(data.counts.assets).reduce((sum, count) => sum + count, 0);
  return data.counts.signals > 0 && assets > 0;
}

/** Subjects in alarm and in warning, across the apps (each subject counted once per app). */
export function alarmCounts(journey: HomeJourney): { alarm: number; warning: number } {
  return Object.values(journey.findings).reduce((sum, counts) => ({ alarm: sum.alarm + (counts.alarm ?? 0), warning: sum.warning + (counts.warning ?? 0) }), { alarm: 0, warning: 0 });
}

/** "4 of 5 online", counting what is not turned off. */
export function onlineText(items: Array<{ state: LiveState }>): string {
  const watched = items.filter((item) => item.state !== "off");
  return t("{count} of {total} online", { count: watched.filter((item) => item.state === "online").length, total: watched.length });
}

/** A page of this app opens in place; a page of another app by address. */
function follow(url: string | null) {
  if (!url) return;
  if (url.startsWith("/assets/") || url === "/actions") navigate(url);
  else window.location.assign(url);
}

function go(to: string) {
  return (event: MouseEvent) => { if (event.metaKey || event.ctrlKey || event.button !== 0) return; event.preventDefault(); navigate(to); };
}

function LiveDot({ state }: { state: LiveState }) {
  return <i className="hm-dot" style={{ background: statusVar(LIVE_STATUS[state]) }} aria-hidden="true" />;
}

/** The PlantCraft widgets of the Overview; the apps add theirs (Widgets.tsx in @plantcraft/ui). */
export const PLATFORM_WIDGETS = ["apps-status", "historian-status", "system", "recent-changes", "attention", "actions", "attention-list", "apps"] as const;

/** A new person's board (12 columns): what answers and the data connections, then the system and,
 * for those who may read the audit log, its last changes. Only PlantCraft's own widgets, so the
 * board draws without waiting for the apps. A board the person arranged is kept as it is. */
export function defaultBoard(auditor: boolean): BoardItem[] {
  const place = (widget: string, x: number, y: number, w: number, h: number): BoardItem => ({ i: widget, widget, x, y, w, h });
  return [
    place("apps-status", 0, 0, 6, 3),
    place("historian-status", 6, 0, 6, 3),
    place("system", 0, 3, 6, 2),
    ...(auditor ? [place("recent-changes", 6, 3, 6, 2)] : []),
  ];
}

/** Whether a saved board shows an app's widget ("<app>:<widget>"): only then the page waits for the apps. */
export function showsAppWidgets(layout: Array<BoardItem | string> | null | undefined): boolean {
  return (layout ?? []).some((item) => (typeof item === "string" ? item : item.widget).includes(":"));
}

function useStatus(): { status: HomeStatus | null; error: string } {
  const [status, setStatus] = useState<HomeStatus | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    const load = () => api.homeStatus().then((value) => { if (alive) { setStatus(value); setError(""); } }).catch((err) => { if (alive) setError(err instanceof Error ? err.message : String(err)); });
    void load();
    const timer = window.setInterval(load, STATUS_EVERY_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);
  return { status, error };
}

function Waiting({ error }: { error: string }) {
  return error ? <p className="form-error">{error}</p> : <p className="muted"><LoaderCircle className="spin" size={14} /> {t("Loading…")}</p>;
}

function AppsStatus({ status, error }: { status: HomeStatus | null; error: string }) {
  if (!status) return <Waiting error={error} />;
  return <div className="hm-status">
    <small className="hm-status-count">{status.apps.length ? onlineText(status.apps) : ""}</small>
    <ul>{status.apps.map((app) => <li key={app.id} title={app.detail || undefined}><LiveDot state={app.state} /><span>{appLabel(app.id, app.name)}</span><small>{app.state === "offline" && app.detail ? app.detail : LIVE_LABELS[app.state]}</small></li>)}
      {!status.apps.length && <li className="muted">{t("No apps installed.")}</li>}</ul>
  </div>;
}

function HistorianStatus({ status, error }: { status: HomeStatus | null; error: string }) {
  if (!status) return <Waiting error={error} />;
  const historian = status.historian;
  return <div className="hm-status">
    <small className="hm-status-count">{historian.ok && historian.sources.length ? onlineText(historian.sources) : ""}</small>
    {!historian.ok ? <p className="hm-status-down"><LiveDot state="offline" /> {t("The Historian does not answer: {detail}", { detail: historian.detail })}</p>:
      <ul>{historian.sources.map((source) => <li key={source.id} title={source.detail || undefined}><LiveDot state={source.state} /><span>{source.name}<small> · {source.type}</small></span><small>{source.state === "offline" && source.detail ? source.detail : LIVE_LABELS[source.state]}</small></li>)}
        {!historian.sources.length && <li className="muted">{t("No connection yet.")}</li>}</ul>}
  </div>;
}

function CountWidget({ to, value, state, text }: { to: string; value: number; state: string; text: string }) {
  return <a className="pc-wg-link hm-count" href={to} onClick={go(to)}>
    <strong className="pc-wg-number" style={{ color: statusVar(state, "text") }}>{value}</strong>
    <span className="pc-wg-label">{text}</span>
    <ArrowRight size={16} className="hm-kpi-go" aria-hidden="true" />
  </a>;
}

export function AttentionWidget({ apps, rows = 6 }: { apps: HomeData["apps"]; rows?: number }) {
  const [items, setItems] = useState<HomeAttention[] | null>(null);
  useEffect(() => { api.attention().then(setItems).catch(() => setItems([])); }, []);
  if (!items) return <Waiting error="" />;
  if (!items.length) return <p className="muted small">{t("Nothing needs attention.")}</p>;
  return <><ul className="hm-attention-list hm-attention-compact">{items.slice(0, rows).map((item) => <AttentionRow key={`${item.app}|${item.subject}|${item.kind}`} item={item} apps={apps} />)}</ul>
    {items.length > rows && <a className="pc-wg-more" href="/attention" onClick={go("/attention")}>{t("See all {count}", { count: items.length })}</a>}</>;
}

/** Overview: widgets each person arranges. The platform's (what needs attention,
 * open actions, what is online, the apps) and those each installed app publishes; nothing here
 * depends on a given app being installed. */
export function PlatformHome({ data, admin }: { data: HomeData; admin: boolean }) {
  const journey = data.journey ?? EMPTY;
  const actions = journey.actions;
  const alarms = alarmCounts(journey);
  const published = Object.keys(journey.findings).length > 0;
  const { status, error } = useStatus();
  const [appWidgets, setAppWidgets] = useState<WidgetDef[] | null>(null);
  const [layout, save] = useOverviewLayout();
  useEffect(() => { fetchSuiteWidgets(data.apps.filter((app) => app.access && app.url).map(({ id, name, url }) => ({ id, name, url }))).then(setAppWidgets); }, [data.apps]);
  const own: WidgetDef[] = [
    { id: "system", app: "processcraft", title: t("System"), size: "m", description: t("Problems open, free disk, last backup, version and who signed in today."), sizes: [{ w: 4, h: 2 }, { w: 6, h: 2 }, { w: 6, h: 3 }], w: 6, h: 2, render: ({ w, h }) => <SystemWidget w={w} h={h} /> },
    // The audit log is the administrators' (Setup › Audit log): nobody else is offered its changes.
    ...(admin ? [{ id: "recent-changes", app: "processcraft", title: t("Recent changes"), size: "m", description: t("The last changes in the audit log: what, who and when."), sizes: [{ w: 4, h: 2 }, { w: 6, h: 2 }, { w: 6, h: 3 }], w: 6, h: 2, render: ({ rows }) => <RecentChanges users={data.users} rows={rows} /> } satisfies WidgetDef] : []),
    { id: "attention", app: "processcraft", title: t("Needs attention"), size: "s", description: t("Results of every app in alarm or attention."), render: () => <CountWidget to="/attention" value={alarms.alarm + alarms.warning} state={alarms.alarm ? "alarm" : alarms.warning ? "warning" : "ok"} text={!published ? t("No results yet") : alarms.alarm || alarms.warning ? t("{alarm} in alarm, {warning} in attention", { alarm: alarms.alarm, warning: alarms.warning }) : t("Nothing needs attention")} /> },
    { id: "actions", app: "processcraft", title: t("Open actions"), size: "s", description: t("Follow-up to do, and how much is late."), render: () => <CountWidget to="/actions" value={actions.open} state={actions.overdue ? "alarm" : actions.open ? "warning" : "ok"} text={actions.overdue ? t("{count} past their due date", { count: actions.overdue }) : actions.open ? t("None past its due date") : t("Nothing waiting")} /> },
    { id: "apps-status", app: "processcraft", title: t("Apps online"), size: "m", description: t("Whether each app answers."), render: () => <AppsStatus status={status} error={error} /> },
    { id: "historian-status", app: "processcraft", title: t("Data connections"), size: "m", description: t("Whether each connection of the Historian is online."), render: () => <HistorianStatus status={status} error={error} /> },
    { id: "attention-list", app: "processcraft", title: t("Worst first"), size: "l", description: t("What needs someone, from every app, worst first."), render: ({ rows }) => <AttentionWidget apps={data.apps} rows={rows} /> },
    { id: "apps", app: "processcraft", title: t("Your apps"), size: "l", description: t("The apps you can open."), sizes: [{ w: 6, h: 2 }, { w: 12, h: 2 }], w: 12, h: 2, render: () => <AppLauncher apps={data.apps} compact /> },
  ];
  const catalog = [...own, ...(appWidgets ?? [])];
  // Nothing is drawn until the person's board is read: a saved board never flashes the default.
  const shown = layout === undefined ? [] : layout ?? defaultBoard(admin);
  return <>
    <div className="page-heading">
      <div><span className="eyebrow">{data.scenario.display_name || data.scenario.name}</span><h1>{t("Overview")}</h1><p>{t("The suite at a glance: what answers, the data connections and what needs attention. Each person's day is in Desk.")}</p></div>
    </div>
    {!plantReady(data) && <div className="panel hm-setup" data-tour="setup-notice">
      <Settings2 size={20} aria-hidden="true" />
      <div><strong>{t("The plant is not set up yet")}</strong><p>{admin ? t("Connect the data, map the plant and install the apps in Settings, under Administration. It is done once.") : t("An administrator sets up the plant's data and assets. The apps fill this page once it is done.")}</p></div>
      {admin && <a className="button button-primary" href="/setup" onClick={(event) => { event.preventDefault(); navigate("/setup"); }}>{t("Open the setup")}</a>}
    </div>}
    <WidgetBoard catalog={catalog} layout={shown} onLayout={save} onReset={layout ? () => save(null) : undefined} loading={layout === undefined || (appWidgets === null && showsAppWidgets(layout))} apps={data.apps.map(({ id, name, url }) => ({ id, name, url }))} />
  </>;
}

function AttentionRow({ item, apps }: { item: HomeAttention; apps: HomeData["apps"] }) {
  const app = apps.find((entry) => entry.id === item.app);
  return <li>
    <a href={item.url ?? undefined} onClick={(event) => { if (!item.url || event.metaKey || event.ctrlKey || event.button !== 0) return; event.preventDefault(); follow(item.url); }} className="hm-attention-row">
      <Pill status={item.status} label={STATUS_LABELS[item.status] ?? item.status} />
      <span className="hm-attention-text"><b>{item.name}</b><small>{item.summary || item.kind}</small></span>
      <span className="hm-attention-meta"><small>{appLabel(item.app, app?.name ?? item.app)}</small><small>{formatAgo(item.at)}</small></span>
      <ArrowRight size={15} aria-hidden="true" />
    </a>
  </li>;
}

const STATUS_RANK: Record<string, number> = { alarm: 0, warning: 1, unknown: 2, ok: 3 };

/** What needs attention: every result the apps published that needs someone, worst first, in pages. */
export function AttentionPage({ data }: { data: HomeData }) {
  const [items, setItems] = useState<HomeAttention[] | null>(null);
  const [error, setError] = useState("");
  const [statuses, setStatuses] = useState<string[]>([]);
  const [apps, setApps] = useState<string[]>([]);
  useEffect(() => { api.attention().then(setItems).catch((err) => setError(err instanceof Error ? err.message : String(err))); }, []);
  const count = (key: "status" | "app", id: string) => (items ?? []).filter((item) => item[key] === id).length;
  const appName = (id: string) => appLabel(id, data.apps.find((app) => app.id === id)?.name ?? id);
  const statusOptions = useMemo(() => ["alarm", "warning", "unknown"].map((id) => ({ id, label: STATUS_LABELS[id], count: count("status", id), icon: <i className="hm-dot" style={{ background: statusVar(id) }} /> })), [items]);
  const appOptions = useMemo(() => [...new Set((items ?? []).map((item) => item.app))].map((id) => ({ id, label: appName(id), count: count("app", id) })), [items, data.apps]);
  const shown = useMemo(() => (items ?? []).filter((item) => (!statuses.length || statuses.includes(item.status)) && (!apps.length || apps.includes(item.app))), [items, statuses, apps]);
  // The assistant's work here (assistant_works/platform.py): what to look at first, from the rows shown.
  useAssistantPage({ place: t("Needs attention"), page: "processcraft:attention", facts: { items: items?.length ?? 0, shown: shown.length },
    view: { status: statuses, apps, rows: shown.slice(0, 30).map((item) => `${item.status} ${item.name} (${item.subject}, ${item.app}): ${(item.summary || item.kind).slice(0, 140)}`) } });
  const columns = useMemo<DataColumn<HomeAttention>[]>(() => [
    { key: "status", label: t("Status"), sort: (item) => STATUS_RANK[item.status] ?? 9, render: (item) => <Pill status={item.status} label={STATUS_LABELS[item.status] ?? item.status} /> },
    { key: "name", label: t("Target"), sort: (item) => item.name, render: (item) => <span className="hm-attention-text"><b>{item.name}</b><small>{item.summary || item.kind}</small></span> },
    { key: "app", label: t("App"), sort: (item) => appName(item.app), render: (item) => appName(item.app) },
    { key: "at", label: t("When"), sort: (item) => item.at, render: (item) => formatAgo(item.at) },
    { key: "open", label: "", render: (item) => item.url ? <a href={item.url} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.button !== 0) return; event.preventDefault(); follow(item.url); }} aria-label={t("Open {name}", { name: item.name })}><ArrowRight size={15} /></a> : null },
  ], [data.apps]);
  return <>
    <div className="page-heading">
      <div><span className="eyebrow"><a href="/" onClick={go("/")}>{t("Desk")}</a></span><h1>{t("Needs attention")}</h1><p>{t("The results of every app that need someone, worst first. Each opens where it can be acted on.")}</p></div>
    </div>
    {error && <div className="form-error">{error}</div>}
    {!items && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {items && (items.length
      ? <DataTable rows={shown} columns={columns} rowKey={(item) => `${item.app}|${item.subject}|${item.kind}`} searchText={(item) => `${item.name} ${item.summary ?? ""} ${item.kind}`} searchPlaceholder={t("Filter by name")} initialSort={{ key: "status", descending: false }} label={t("Needs attention")} onRowClick={(item) => follow(item.url)}
          toolbar={<><MultiSelect label={t("Status")} options={statusOptions} value={statuses} onChange={setStatuses} />{appOptions.length > 1 && <MultiSelect label={t("App")} options={appOptions} value={apps} onChange={setApps} />}</>} empty={t("Nothing matches the filters")} />:
      <div className="panel hm-empty"><strong><CheckCircle2 size={16} aria-hidden="true" /> {t("Nothing needs attention")}</strong><p>{t("Once the apps run on the plant's data, what needs someone shows here, worst first.")}</p></div>)}
  </>;
}
