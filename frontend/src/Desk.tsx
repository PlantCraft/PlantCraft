/**
 * Desk's first page, "Today" (owner, 2026-10-23): each person's day as widgets on the suite's
 * grid, the same board every Overview uses (WidgetBoard in @plantcraft/ui), arranged by each
 * person. At the top only the greeting, the date and the time (owner, 2026-10-24). Desk's widgets
 * (coming days, the month, the day's timeline, clocks, actions as a list or a board, notifications,
 * unread chats, My day's to-dos, a quick note, suggestions, followed assets, team), the platform's and
 * those each installed app publishes. Each widget has fixed sizes and draws what fits each one;
 * /widgets draws every widget at every size (the widget test page).
 */
import { CheckCircle2, Clock, Plus, Repeat, X } from "lucide-react";
import { AssistantTitleButton, bodyPixels, fetchSuiteWidgets, useAssistantPage, formatAgo, openMessages, statusVar, useOverviewLayout, WidgetBoard, WidgetGallery, type BoardItem, type WidgetConfig, type WidgetDef, displayTimeZone, wallClock } from "@plantcraft/ui";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AppLauncher } from "./AppLauncher";
import { Go, errorText } from "./collab";
import { collabApi, type Action, type ActionView } from "./collabApi";
import { addDays, deskApi, isoDay, upcoming, type CalendarEvent, type DeskToday, type Todo, type Followed, type Suggestion, type Team } from "./deskApi";
import { AgendaWidget, ChatsWidget, ClocksSettings, ClocksWidget, KanbanWidget, MonthWidget, QuickNoteWidget, useEvery, Waiting } from "./DeskWidgets";
import { locale, t } from "./i18n";
import { AttentionWidget } from "./PlatformHome";
import type { HomeData, WorkspaceUser } from "./types";
import "./desk.css";

export const DESK_APP = "desk";
/** A new person's Desk, in rows of whole widgets: the clocks; the coming days, their actions and
 * the month; notifications, My day's to-dos and unread chats; suggestions and what they follow. */
export const DESK_DEFAULT: BoardItem[] = [
  { i: "desk:clocks", widget: "desk:clocks", x: 0, y: 0, w: 12, h: 1 },
  { i: "desk:calendar", widget: "desk:calendar", x: 0, y: 1, w: 4, h: 3 },
  { i: "desk:actions", widget: "desk:actions", x: 4, y: 1, w: 4, h: 3 },
  { i: "desk:month", widget: "desk:month", x: 8, y: 1, w: 4, h: 3 },
  { i: "desk:inbox", widget: "desk:inbox", x: 0, y: 4, w: 4, h: 3 },
  { i: "desk:checklist", widget: "desk:checklist", x: 4, y: 4, w: 4, h: 3 },
  { i: "desk:chats", widget: "desk:chats", x: 8, y: 4, w: 4, h: 3 },
  { i: "desk:suggestions", widget: "desk:suggestions", x: 0, y: 7, w: 6, h: 2 },
  { i: "desk:followed", widget: "desk:followed", x: 6, y: 7, w: 6, h: 2 },
];
const KIND_COLORS: Record<string, string> = {
  event: "var(--pc-primary)", action: "var(--pc-app-desk)", todo: "var(--pc-good-fill)",
  alarm: "var(--pc-problem-fill)", schedule: "var(--pc-text-3)", external: "var(--pc-text-3)",
};

/** "Today", "Tomorrow", "Mon 26 Oct". */
export function dayLabel(day: string, today: string): string {
  if (day === today) return t("Today");
  if (day === isoDay(addDays(new Date(`${today}T12:00:00`), 1))) return t("Tomorrow");
  return new Date(`${day}T12:00:00`).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
}

function timeOf(event: CalendarEvent): string {
  if (event.all_day || event.start.length <= 10) return t("All day");
  return new Date(event.start).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: displayTimeZone() });
}

/** Lines of text (a day's name, an event) that fit in a card `h` rows high, with the link under them. */
export function lineBudget(h: number): number {
  return Math.max(2, Math.floor((bodyPixels(h) - 26) / 25));
}

/** The coming days, like a phone's calendar widget, as many lines as fit; the calendar is one click away. */
function UpcomingWidget({ days, h }: { days: number; h: number }) {
  const today = isoDay(new Date());
  const end = isoDay(addDays(new Date(), days - 1));
  const { data, error } = useEvery(`calendar:${today}:${end}`, () => deskApi.calendar(today, end), [today, end]);
  if (!data) return <Waiting error={error} />;
  const groups = upcoming(data.events.filter((event) => !event.done), data.today, days);
  // Each day's name and its events take a line each; what does not fit is counted.
  let budget = lineBudget(h);
  const shown = groups.flatMap((group) => {
    if (budget < 2) return [];
    budget -= 1;
    const fits = group.events.length <= budget ? group.events.length : Math.max(0, budget - 1);
    budget -= fits + (fits < group.events.length ? 1 : 0);
    return [{ ...group, shown: group.events.slice(0, fits), more: group.events.length - fits }];
  });
  return <div className="dk-upcoming">
    {!groups.length && <p className="muted small">{t("Nothing with a date in the coming days.")}</p>}
    {shown.map((group) => <section key={group.day}>
      <h3 className={group.day === data.today ? "dk-today" : undefined}>{dayLabel(group.day, data.today)}</h3>
      <ul>{group.shown.map((event) => <li key={event.id}>
        <i style={{ background: event.color ?? KIND_COLORS[event.kind] }} aria-hidden="true" />
        <span className="dk-when">{timeOf(event)}</span>
        {event.href ? <Go to={event.href} className="dk-what">{event.title}</Go> : <span className="dk-what">{event.title}</span>}
      </li>)}
        {group.more > 0 && <li className="muted small">{t("{count} more", { count: group.more })}</li>}</ul>
    </section>)}
    <Go to="/calendar" className="pc-wg-more">{t("Open the calendar")}</Go>
  </div>;
}

const ACTION_VIEWS: Array<{ id: ActionView; label: string }> = [
  { id: "mine", label: t("Mine") },
  { id: "groups", label: t("My groups'") },
  { id: "created", label: t("Created by me") },
];

/** The actions of one quick filter, late and due first. */
function ActionsWidget({ view, rows }: { view: ActionView; rows: number }) {
  const { data, error } = useEvery(`actions:${view}`, () => collabApi.actions({ view, status: ["open", "in_progress", "blocked"] }), [view]);
  if (!data) return <Waiting error={error} />;
  const today = isoDay(new Date());
  const items = [...data.items].sort((a, b) => (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999"));
  return <div className="pc-wg-list">
    {!items.length && <p className="muted small">{t("No open action.")}</p>}
    {items.slice(0, rows).map((action: Action) => {
      const late = Boolean(action.due_at && action.due_at < today);
      const state = late ? "alarm" : action.due_at === today ? "warning" : "unknown";
      return <Go key={action.action_id} to={`/actions/${action.action_id}`} className="pc-wg-row">
        <span className="pc-wg-dot" style={{ background: statusVar(state) }} aria-hidden="true" />
        <span className="pc-wg-row-text"><b>{action.title}</b><small>{view === "mine" ? action.group_name || action.status_label : action.owner_name || action.group_name || action.status_label}</small></span>
        <span className="pc-wg-row-value dk-due">{action.due_at ? (late ? t("late") : dayLabel(action.due_at, today)) : ""}</span>
      </Go>;
    })}
    <Go to={`/actions?view=${view}`} className="pc-wg-more">{t("See all")}</Go>
  </div>;
}

function snoozeDay(): string {
  return isoDay(addDays(new Date(), 1));
}

/** Messages' unread notifications (owner, 2026-10-24): alarms, runs and changes to the person's
 * actions; one opens Messages over Desk, at its Notifications. */
function NotificationsWidget({ rows }: { rows: number }) {
  const { data, error } = useEvery("notifications", () => collabApi.notifications(), []);
  if (!data) return <Waiting error={error} />;
  const unread = data.items.filter((item) => item.state === "unread");
  return <div className="pc-wg-list">
    {!unread.length && <p className="muted small"><CheckCircle2 size={14} /> {t("Nothing new.")}</p>}
    {unread.slice(0, rows).map((item) => {
      const state = item.category === "alarm" ? (item.priority === "critical" || item.priority === "high" ? "alarm" : "warning") : "unknown";
      return <a key={item.key} href="/messages/notifications" className="pc-wg-row" onClick={(event) => { if (event.metaKey || event.ctrlKey || event.button !== 0) return; event.preventDefault(); openMessages("notifications"); }}>
        <span className="pc-wg-dot" style={{ background: statusVar(state) }} aria-hidden="true" />
        <span className="pc-wg-row-text"><b>{item.title}</b><small>{item.from}{item.detail ? ` · ${item.detail}` : ""}</small></span>
        <span className="pc-wg-row-value dk-due">{formatAgo(item.at)}</span>
      </a>;
    })}
    <a href="/messages/notifications" className="pc-wg-more" onClick={(event) => { if (event.metaKey || event.ctrlKey || event.button !== 0) return; event.preventDefault(); openMessages("notifications"); }}>{t("Open the notifications")}</a>
  </div>;
}

/** Checklist lines that fit in a card `h` rows high, under the line to add one. */
export function checkLines(h: number): number {
  // The line to add one and the count line stay; each item is one 30 px line.
  return Math.max(1, Math.floor((bodyPixels(h) - 72) / 30));
}

/** My day's to-dos (Desk › To-do): check one, add one; a title opens it on the To-do page. */
function TodoWidget({ items, onChange, h }: { items: Todo[] | null; onChange: () => void; h: number }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  if (!items) return <Waiting />;
  async function add(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    try { await deskApi.createTodo({ title: text.trim(), my_day: true }); setText(""); setError(""); onChange(); } catch (err) { setError(errorText(err)); }
  }
  const done = items.filter((item) => item.done).length;
  const lines = checkLines(h);
  // Open items first; the rest is counted.
  const ordered = [...items.filter((item) => !item.done), ...items.filter((item) => item.done)];
  const shown = ordered.slice(0, lines);
  return <div className="dk-check">
    <ul>{shown.map((item) => <li key={item.todo_id} className={item.done ? "dk-done" : undefined}>
      <label><input type="checkbox" checked={item.done} onChange={() => { void deskApi.changeTodo(item.todo_id, { done: !item.done }).then(onChange); }} aria-label={item.title} /></label>
      <Go to={`/todo?item=${item.todo_id}`} className="dk-check-title">{item.title}</Go>
      {item.repeat && <Repeat size={12} className="muted" aria-label={t("Repeats")} />}
    </li>)}
    </ul>
    {!items.length && <p className="muted small">{t("Nothing for today yet.")}</p>}
    <form className="dk-add pc-cards-nodrag" onSubmit={(event) => void add(event)}>
      <input id="dk-check-new" value={text} maxLength={200} onChange={(event) => setText(event.target.value)} placeholder={t("Add to My day: call the analyzer supplier")} aria-label={t("Add to My day")} />
      <button type="submit" className="pcs-icon-button" aria-label={t("Add")}><Plus size={15} /></button>
    </form>
    {error && <p className="form-error small">{error}</p>}
    {items.length > 0 && <small className="muted dk-check-count">{t("{done} of {total} done", { done, total: items.length })}{shown.length < ordered.length ? ` · ${t("{count} more", { count: ordered.length - shown.length })}` : ""}</small>}
  </div>;
}

/** The day's suggestions, each with its reason; the person takes them or not. */
function SuggestionsWidget({ items, onChange, rows }: { items: Suggestion[] | null; onChange: () => void; rows: number }) {
  if (!items) return <Waiting />;
  const hide = (item: Suggestion, state: "done" | "snoozed") => { void deskApi.triage(item.key, state, state === "snoozed" ? snoozeDay() : undefined).then(onChange); };
  return <div className="pc-wg-list">
    {!items.length && <p className="muted small"><CheckCircle2 size={14} /> {t("No suggestion today. Your day is in order.")}</p>}
    {items.slice(0, rows).map((item) => <div key={item.key} className="pc-wg-row dk-inbox-row">
      <span className="pc-wg-dot" style={{ background: statusVar(item.state) }} aria-hidden="true" />
      <span className="pc-wg-row-text"><b>{item.title}</b><small>{item.reason}</small></span>
      <span className="dk-row-tools dk-row-tools-on">
        <Go to={item.href} className="button button-secondary button-small">{item.action}</Go>
        <button type="button" className="pcs-icon-button" onClick={() => hide(item, "snoozed")} aria-label={t("Snooze until tomorrow")} title={t("Snooze until tomorrow")}><Clock size={14} /></button>
        <button type="button" className="pcs-icon-button" onClick={() => hide(item, "done")} aria-label={t("Dismiss")} title={t("Dismiss")}><X size={14} /></button>
      </span>
    </div>)}
  </div>;
}

const STATUS_TEXT: Record<string, string> = { alarm: t("Critical"), warning: t("Warning"), unknown: t("No result"), ok: t("OK") };

/** The assets the person follows, worst first. */
function FollowedWidget({ items, rows }: { items: Followed[] | null; rows: number }) {
  if (!items) return <Waiting />;
  const rank: Record<string, number> = { alarm: 0, warning: 1, unknown: 2, ok: 3 };
  const sorted = [...items].sort((a, b) => (rank[a.status] ?? 2) - (rank[b.status] ?? 2));
  return <div className="pc-wg-list">
    {!sorted.length && <p className="muted small">{t("You follow no asset yet. Press Follow on an asset's page to see its alarms and results here.")}</p>}
    {sorted.slice(0, rows).map((item) => {
      const inner = <><span className="pc-wg-dot" style={{ background: statusVar(item.status) }} aria-hidden="true" />
        <span className="pc-wg-row-text"><b>{item.name}</b><small>{item.summary || STATUS_TEXT[item.status]}</small></span>
        <span className="pc-wg-row-value dk-due">{item.open_actions ? t("{count} actions", { count: item.open_actions }) : ""}</span></>;
      return item.href ? <Go key={item.ref} to={item.href} className="pc-wg-row">{inner}</Go> : <div key={item.ref} className="pc-wg-row">{inner}</div>;
    })}
  </div>;
}

/** The person's (first) group: who is away or busy, and who has late work. */
function TeamWidget({ rows }: { rows: number }) {
  const { data, error } = useEvery<Team>("team", () => deskApi.team(), []);
  if (!data) return <Waiting error={error} />;
  const group = data.group;
  if (!group) return <p className="muted small">{t("You are in no group yet. An administrator puts people in groups in People › Groups.")}</p>;
  const state = { away: t("Away today"), busy: t("Busy now"), "": "" };
  return <div className="pc-wg-list">
    {group.people.slice(0, rows).map((person) => <Go key={person.username} to={`/people/${person.username}`} className="pc-wg-row">
      <span className="pc-wg-dot" style={{ background: statusVar(person.late ? "alarm" : person.availability ? "warning" : "ok") }} aria-hidden="true" />
      <span className="pc-wg-row-text"><b>{person.display_name}</b><small>{[state[person.availability], t("{count} open", { count: person.open })].filter(Boolean).join(" · ")}</small></span>
      <span className="pc-wg-row-value">{person.late ? t("{count} late", { count: person.late }) : ""}</span>
    </Go>)}
    <Go to={`/team?group=${encodeURIComponent(group.group_id)}`} className="pc-wg-more">{t("Open {name}", { name: group.name })}</Go>
  </div>;
}

function OptionField({ label, value, options, onChange }: { label: string; value: string; options: Array<{ id: string; label: string }>; onChange: (value: string) => void }) {
  return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>;
}

function useToday(): { today: DeskToday | null; reload: () => void } {
  const { data, reload } = useEvery("today", () => deskApi.today(), []);
  return { today: data, reload };
}

/** Good morning / afternoon / evening, by the browser's clock. */
export function greeting(hour: number): string {
  if (hour < 12) return t("Good morning");
  if (hour < 18) return t("Good afternoon");
  return t("Good evening");
}

/** Sizes, smallest first: columns of 12 by rows. */
const LIST = [{ w: 4, h: 2 }, { w: 4, h: 3 }, { w: 6, h: 3 }];
const WIDE = [{ w: 6, h: 2 }, { w: 6, h: 3 }, { w: 12, h: 3 }];

export function DeskCatalog({ data, today, reload, me }: { data: HomeData; today: DeskToday | null; reload: () => void; me: string }): WidgetDef[] {
  const views = ACTION_VIEWS;
  const daysOptions = [{ id: "3", label: t("3 days") }, { id: "7", label: t("7 days") }, { id: "14", label: t("14 days") }];
  const viewField = ({ config, onChange }: { config: WidgetConfig; onChange: (config: WidgetConfig) => void }) => <OptionField label={t("Which actions")} value={String(config.view ?? "mine")} options={views} onChange={(value) => onChange({ ...config, view: value })} />;
  return [
    { id: "desk:calendar", app: DESK_APP, title: t("Coming days"), size: "m", sizes: [{ w: 3, h: 2 }, { w: 4, h: 3 }, { w: 6, h: 3 }], w: 4, h: 3, multiple: true, description: t("What has a date: your events, actions, to-dos, alarms, scheduled runs and your calendars."),
      defaultConfig: { days: 7 },
      settings: ({ config, onChange }) => <OptionField label={t("Days shown")} value={String(config.days ?? 7)} options={daysOptions} onChange={(value) => onChange({ ...config, days: Number(value) })} />,
      render: ({ config, h }) => <UpcomingWidget days={Number((config as WidgetConfig).days ?? 7)} h={h} /> },
    { id: "desk:agenda", app: DESK_APP, title: t("Today's timeline"), size: "m", sizes: [{ w: 3, h: 3 }, { w: 4, h: 3 }, { w: 6, h: 3 }], w: 4, h: 3, description: t("Today hour by hour, from an hour ago, with a line at now."),
      render: ({ h }) => <AgendaWidget h={h} /> },
    { id: "desk:month", app: DESK_APP, title: t("This month"), size: "s", sizes: [{ w: 3, h: 3 }, { w: 4, h: 3 }], w: 3, h: 3, description: t("The month at a glance; a dot under each day with something. A day opens the calendar on it."),
      render: () => <MonthWidget /> },
    { id: "desk:clocks", app: DESK_APP, title: t("World clocks"), size: "s", sizes: [{ w: 3, h: 1 }, { w: 6, h: 1 }, { w: 12, h: 1 }], w: 6, h: 1, multiple: true, description: t("The time here and in other places: up to six clocks."),
      settings: (props) => <ClocksSettings {...props} />,
      render: ({ config, w }) => <ClocksWidget config={config} w={w} /> },
    { id: "desk:actions", app: DESK_APP, title: t("My actions"), size: "m", sizes: LIST, w: 4, h: 3, multiple: true, description: t("Open actions of one quick filter, late and due first."),
      defaultConfig: { view: "mine" }, settings: viewField,
      render: ({ config, rows }) => <ActionsWidget view={(config.view as ActionView) ?? "mine"} rows={rows} /> },
    { id: "desk:kanban", app: DESK_APP, title: t("Actions board"), size: "l", sizes: [{ w: 8, h: 3 }, { w: 12, h: 3 }], w: 12, h: 3, multiple: true, description: t("Open, in progress and blocked as columns; drag a card to move it."),
      defaultConfig: { view: "mine" }, settings: viewField,
      render: ({ config, h }) => <KanbanWidget view={(config.view as ActionView) ?? "mine"} h={h} /> },
    { id: "desk:inbox", app: DESK_APP, title: t("Notifications"), size: "m", sizes: LIST, w: 4, h: 3, description: t("Unread notifications: alarms, runs and changes to your actions."), render: ({ rows }) => <NotificationsWidget rows={rows} /> },
    { id: "desk:chats", app: DESK_APP, title: t("Unread messages"), size: "s", sizes: [{ w: 3, h: 1 }, { w: 4, h: 2 }, { w: 4, h: 3 }], w: 3, h: 1, description: t("Unread chat messages: a count, or the conversations on a larger card."),
      render: ({ h, rows }) => <ChatsWidget me={me} h={h} rows={rows} /> },
    { id: "desk:checklist", app: DESK_APP, title: t("My day"), size: "m", sizes: [{ w: 4, h: 3 }, { w: 6, h: 3 }], w: 4, h: 3, description: t("Today's to-dos: due today, late or picked for today."), render: ({ h }) => <TodoWidget items={today?.todos ?? null} onChange={reload} h={h} /> },
    { id: "desk:note", app: DESK_APP, title: t("Quick note"), size: "s", sizes: [{ w: 3, h: 2 }, { w: 4, h: 2 }, { w: 6, h: 3 }], w: 3, h: 2, multiple: true, description: t("A note kept on the page, saved as you type."),
      render: ({ config, setConfig }) => <QuickNoteWidget config={config} setConfig={setConfig} /> },
    { id: "desk:suggestions", app: DESK_APP, title: t("Suggestions for today"), size: "m", sizes: WIDE, w: 6, h: 2, description: t("What could come first today, each with its reason."), render: ({ rows }) => <SuggestionsWidget items={today?.suggestions ?? null} onChange={reload} rows={rows} /> },
    { id: "desk:followed", app: DESK_APP, title: t("Assets I follow"), size: "l", sizes: WIDE, w: 6, h: 2, description: t("The assets you follow, worst first."), render: ({ rows }) => <FollowedWidget items={today?.followed ?? null} rows={rows} /> },
    { id: "desk:team", app: DESK_APP, title: t("My team"), size: "m", sizes: LIST, w: 4, h: 3, description: t("Your group: who is away or busy, and who has late work."), render: ({ rows }) => <TeamWidget rows={rows} /> },
    { id: "attention-list", app: "processcraft", title: t("Worst first"), size: "l", sizes: [{ w: 6, h: 3 }, { w: 12, h: 3 }], w: 12, h: 3, description: t("What needs someone, from every app, worst first."), render: ({ rows }) => <AttentionWidget apps={data.apps} rows={rows} /> },
    { id: "apps", app: "processcraft", title: t("Your apps"), size: "l", sizes: [{ w: 6, h: 2 }, { w: 12, h: 2 }], w: 12, h: 2, description: t("The apps you can open."), render: () => <AppLauncher apps={data.apps} compact /> },
  ];
}

/** "Good morning, Ana", the date and the time, at the top of Today. */
function TodayHeading({ me }: { me: WorkspaceUser | null }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 15_000);
    return () => window.clearInterval(timer);
  }, []);
  const first = (me?.display_name ?? "").split(/\s+/)[0];
  const hello = greeting(Number(wallClock(now.getTime()).slice(11, 13)));
  const zone = displayTimeZone();
  return <div className="page-heading dk-heading">
    <div>
      <div className="page-heading-title"><h1>{first ? t("{greeting}, {name}", { greeting: hello, name: first }) : hello}</h1><AssistantTitleButton /></div>
      <p className="dk-heading-when pc-heading-keep">
        <span>{now.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: zone })}</span>
        <time dateTime={now.toISOString()}>{now.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: zone })}</time>
      </p>
    </div>
  </div>;
}

function useCatalog(data: HomeData, me: WorkspaceUser | null) {
  const { today, reload } = useToday();
  const [appWidgets, setAppWidgets] = useState<WidgetDef[] | null>(null);
  useEffect(() => { fetchSuiteWidgets(data.apps.filter((app) => app.access && app.url).map(({ id, name, url }) => ({ id, name, url }))).then(setAppWidgets); }, [data.apps]);
  const catalog = useMemo(() => [...DeskCatalog({ data, today, reload, me: me?.username ?? "" }), ...(appWidgets ?? [])], [data, today, reload, appWidgets, me]);
  return { catalog, loading: appWidgets === null };
}

/** Every widget at every size it allows (/widgets): the page the widget test reads. */
export function WidgetGalleryPage({ data, me }: { data: HomeData; me: WorkspaceUser | null }) {
  const { catalog, loading } = useCatalog(data, me);
  return <>
    <div className="page-heading">
      <div><span className="eyebrow">{t("Desk")}</span><h1>{t("Widgets")}</h1><p>{t("Every widget of Desk and of the installed apps, at each size it allows.")}</p></div>
    </div>
    {loading ? <Waiting /> : <WidgetGallery catalog={catalog} apps={data.apps.map(({ id, name, url }) => ({ id, name, url }))} />}
  </>;
}

/** Desk's first page. */
export function DeskToday({ data, me }: { data: HomeData; me: WorkspaceUser | null }) {
  const { catalog, loading } = useCatalog(data, me);
  const [layout, save] = useOverviewLayout(DESK_APP);
  // The assistant's work here (assistant_works/platform.py): what needs attention today.
  useAssistantPage({ place: t("Desk › Today"), page: "processcraft:desk-today" });
  return <>
    <TodayHeading me={me} />
    <WidgetBoard catalog={catalog} layout={layout ?? DESK_DEFAULT} onLayout={save} onReset={layout ? () => save(null) : undefined}
      loading={loading || layout === undefined} apps={data.apps.map(({ id, name, url }) => ({ id, name, url }))} />
  </>;
}
