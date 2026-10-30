/**
 * Desk's visual widgets ("widgets mais visuais"): world clocks, the month at a
 * glance, the day as a timeline, the actions as a board, unread chats and a quick note. Each draws
 * what fits the size it was given (WidgetContext's w, h, rows), so none spills out of its card.
 */
import { ChevronLeft, ChevronRight, MessagesSquare } from "lucide-react";
import { bodyPixels, cityName, displayTimeZone, formatAgo, formatDate, openMessages, statusVar, wallClock, zoneOffset, type WidgetConfig } from "@plantcraft/ui";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { boardColumns } from "./actionsBoard";
import { Go, errorText, plainMentions } from "./collab";
import { collabApi, type Action, type ActionStatus, type ActionView, type Conversation } from "./collabApi";
import { addDays, deskApi, isoDay, type CalendarEvent } from "./deskApi";
import { navigate } from "./nav";
import { locale, t } from "./i18n";

const EVERY_MS = 60_000;

/** A query read now and every minute; the last answer is kept across redraws (Customize, a move). */
const LAST = new Map<string, unknown>();
export function useEvery<T>(key: string, load: () => Promise<T>, deps: unknown[]): { data: T | null; error: string; reload: () => void } {
  const [data, setData] = useState<T | null>(() => (LAST.get(key) as T | undefined) ?? null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    const run = () => load().then((value) => { LAST.set(key, value); if (live) { setData(value); setError(""); } }).catch((err) => { if (live) setError(errorText(err)); });
    void run();
    const timer = window.setInterval(run, EVERY_MS);
    return () => { live = false; window.clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((value) => value + 1) };
}

export function Waiting({ error }: { error?: string }) {
  return error ? <p className="form-error small">{error}</p> : <p className="muted small">{t("Loading…")}</p>;
}

/** The time now, redrawn every `ms`. */
function useNow(ms: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), ms);
    return () => window.clearInterval(timer);
  }, [ms]);
  return now;
}

// --- World clocks ------------------------------------------------------------------------

export const CLOCK_MAX = 6;

/** "America/Sao_Paulo" -> "São Paulo"; "UTC" stays. */
export function zoneCity(zone: string): string {
  return cityName(zone).split(" / ").pop() ?? zone;
}

/** "+3 h", "−1 h 30", "" when the same as here. */
export function offsetText(minutes: number): string {
  if (!minutes) return "";
  const sign = minutes > 0 ? "+" : "−";
  const hours = Math.floor(Math.abs(minutes) / 60);
  const rest = Math.abs(minutes) % 60;
  return `${sign}${hours} h${rest ? ` ${rest}` : ""}`;
}

/** The time zones offered (the browser's list), with UTC first. */
export function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  const zones = intl.supportedValuesOf?.("timeZone") ?? ["America/Sao_Paulo", "America/New_York", "Europe/London", "Europe/Berlin", "Asia/Tokyo"];
  return ["UTC", ...zones.filter((zone) => zone !== "UTC")];
}

/** UTC under another name (the server's zone is often "Etc/UTC"). */
export function sameAsUtc(zone: string): boolean {
  return /^(Etc\/)?(UTC|UCT|GMT|GMT[+-]?0|Universal|Zulu|Greenwich)$/.test(zone);
}

export function clockZones(config: WidgetConfig): string[] {
  const raw = Array.isArray(config.zones) ? config.zones.filter((zone): zone is string => typeof zone === "string" && zone.length < 64) : [];
  if (raw.length) return raw.slice(0, CLOCK_MAX);
  // Here first, then UTC and the main time zones of the day (each once; "Etc/UTC" is UTC).
  return [...new Set([sameAsUtc(displayTimeZone()) ? "UTC" : displayTimeZone(), "UTC", "America/New_York", "Europe/London", "Asia/Shanghai", "Asia/Tokyo", "America/Sao_Paulo"])].slice(0, CLOCK_MAX);
}

/** One clock per zone, as many as the width holds (one in three columns, three in six, six across). */
export function ClocksWidget({ config, w }: { config: WidgetConfig; w: number }) {
  const now = useNow(15_000);
  const zones = clockZones(config).slice(0, Math.max(1, Math.floor(w / 2)));
  const here = zoneOffset(now.getTime());
  return <div className="dk-clocks" style={{ gridTemplateColumns: `repeat(${zones.length}, minmax(0, 1fr))` }}>
    {zones.map((zone, index) => {
      let offset = 0;
      try { offset = Math.round((zoneOffset(now.getTime(), zone) - here) / 60_000); } catch { offset = 0; }
      let time = "";
      try { time = now.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: zone }); } catch { time = "—"; }
      return <div key={`${zone}-${index}`} className="dk-clock">
        <strong>{time}</strong>
        <small title={zone}>{zoneCity(zone)}{offset ? ` · ${offsetText(offset)}` : ""}</small>
      </div>;
    })}
  </div>;
}

export function ClocksSettings({ config, onChange }: { config: WidgetConfig; onChange: (config: WidgetConfig) => void }) {
  const zones = clockZones(config);
  const all = useMemo(timeZones, []);
  const set = (next: string[]) => onChange({ ...config, zones: next });
  return <fieldset className="dk-zone-fields">
    <legend>{t("Time zones")}</legend>
    {zones.map((zone, index) => <div key={index} className="dk-zone-row">
      <select aria-label={t("Clock {count}", { count: index + 1 })} value={zone} onChange={(event) => set(zones.map((item, at) => (at === index ? event.target.value : item)))}>
        {[zone, ...all.filter((item) => item !== zone)].map((item) => <option key={item} value={item}>{item.replace(/_/g, " ")}</option>)}
      </select>
      {zones.length > 1 && <button type="button" className="button button-secondary button-small" onClick={() => set(zones.filter((_, at) => at !== index))}>{t("Remove")}</button>}
    </div>)}
    {zones.length < CLOCK_MAX && <button type="button" className="button button-secondary button-small" onClick={() => set([...zones, "UTC"])}>{t("Add a clock")}</button>}
    <p className="muted small">{t("A small clock shows the first; a medium one three; a large one six.")}</p>
  </fieldset>;
}

// --- The month ---------------------------------------------------------------------------

/** The month's weeks, Monday first: six rows of seven days (null outside the month). */
export function monthWeeks(year: number, month: number): Array<Array<string | null>> {
  const first = new Date(year, month, 1, 12);
  const lead = (first.getDay() + 6) % 7;
  const days = new Date(year, month + 1, 0, 12).getDate();
  const cells: Array<string | null> = [...Array(lead).fill(null), ...Array.from({ length: days }, (_, index) => isoDay(new Date(year, month, index + 1, 12)))];
  while (cells.length % 7) cells.push(null);
  const weeks: Array<Array<string | null>> = [];
  for (let at = 0; at < cells.length; at += 7) weeks.push(cells.slice(at, at + 7));
  return weeks;
}

/** The days with something, by kind (a dot under each). */
function busyDays(events: CalendarEvent[]): Map<string, number> {
  const days = new Map<string, number>();
  for (const event of events) {
    if (event.done || event.kind === "schedule") continue;
    const day = event.start.slice(0, 10);
    days.set(day, (days.get(day) ?? 0) + 1);
  }
  return days;
}

/** The month at a glance: today ringed, a dot under each day with something; a day opens the calendar on it. */
export function MonthWidget() {
  const today = isoDay(new Date());
  const [shown, setShown] = useState(() => { const now = new Date(); return { year: now.getFullYear(), month: now.getMonth() }; });
  const weeks = monthWeeks(shown.year, shown.month);
  const start = isoDay(new Date(shown.year, shown.month, 1, 12));
  const end = isoDay(new Date(shown.year, shown.month + 1, 0, 12));
  const { data } = useEvery(`month:${start}`, () => deskApi.calendar(start, end), [start, end]);
  const busy = busyDays(data?.events ?? []);
  const step = (by: number) => setShown(({ year, month }) => { const next = new Date(year, month + by, 1, 12); return { year: next.getFullYear(), month: next.getMonth() }; });
  const title = new Date(shown.year, shown.month, 1, 12).toLocaleDateString(locale, { month: "long", year: "numeric" });
  const names = Array.from({ length: 7 }, (_, index) => new Date(2026, 0, 5 + index, 12).toLocaleDateString(locale, { weekday: "narrow" }));
  return <div className="dk-month">
    <div className="dk-month-head pc-cards-nodrag">
      <button type="button" className="pcs-icon-button" onClick={() => step(-1)} aria-label={t("Previous month")}><ChevronLeft size={15} /></button>
      <b>{title}</b>
      <button type="button" className="pcs-icon-button" onClick={() => step(1)} aria-label={t("Next month")}><ChevronRight size={15} /></button>
    </div>
    <table className="dk-month-grid" style={{ ["--dk-weeks" as string]: weeks.length }}>
      <thead><tr>{names.map((name, index) => <th key={index} scope="col">{name}</th>)}</tr></thead>
      <tbody>{weeks.map((week, row) => <tr key={row}>{week.map((day, col) => <td key={col}>
        {day && <a href={`/calendar?date=${day}`} className={`dk-month-day${day === today ? " today" : ""}${busy.has(day) ? " busy" : ""}`}
          aria-label={busy.has(day) ? t("{day}, {count} items", { day, count: busy.get(day) ?? 0 }) : day}
          onClick={(event) => { if (event.metaKey || event.ctrlKey) return; event.preventDefault(); navigate(`/calendar?date=${day}`); }}>{Number(day.slice(8))}</a>}
      </td>)}</tr>)}</tbody>
    </table>
  </div>;
}

// --- The day as a timeline -------------------------------------------------------------

export const HOUR_PX = 34;

export type Placed = { event: CalendarEvent; top: number; height: number; column: number; columns: number };

/** Minutes since midnight in the installation's time. */
function minutesOf(value: string): number {
  const clock = wallClock(new Date(value).getTime());
  return Number(clock.slice(11, 13)) * 60 + Number(clock.slice(14, 16));
}

/** The day's timed events laid out from `from` (minutes), side by side when they overlap. */
export function layOutDay(events: CalendarEvent[], from: number, to: number, hourPx = HOUR_PX): Placed[] {
  const timed = events.filter((event) => !event.all_day && event.start.length > 10)
    .map((event) => {
      const start = minutesOf(event.start);
      const end = Math.max(start + 20, event.end ? minutesOf(event.end) : start + 30);
      return { event, start, end };
    })
    .filter((item) => item.end > from && item.start < to)
    .sort((a, b) => a.start - b.start || b.end - a.end);
  const placed: Placed[] = [];
  let group: Array<{ end: number; index: number; column: number }> = [];
  let groupStart = 0;
  for (const item of timed) {
    if (group.length && group.every((entry) => entry.end <= item.start)) {
      const columns = Math.max(...group.map((entry) => entry.column)) + 1;
      for (let at = groupStart; at < placed.length; at += 1) placed[at].columns = columns;
      group = [];
      groupStart = placed.length;
    }
    const used = new Set(group.filter((entry) => entry.end > item.start).map((entry) => entry.column));
    let column = 0;
    while (used.has(column)) column += 1;
    const top = ((Math.max(item.start, from) - from) / 60) * hourPx;
    const height = Math.max(18, ((Math.min(item.end, to) - Math.max(item.start, from)) / 60) * hourPx - 2);
    group.push({ end: item.end, index: placed.length, column });
    placed.push({ event: item.event, top, height, column, columns: 1 });
  }
  if (group.length) {
    const columns = Math.max(...group.map((entry) => entry.column)) + 1;
    for (let at = groupStart; at < placed.length; at += 1) placed[at].columns = columns;
  }
  return placed;
}

const KIND_COLORS: Record<string, string> = {
  event: "var(--pc-primary)", action: "var(--pc-app-desk)", todo: "var(--pc-good-fill)",
  alarm: "var(--pc-problem-fill)", schedule: "var(--pc-text-3)", external: "var(--pc-text-3)",
};

/** Today as a timeline from an hour ago, as many hours as the card holds, with a line at now. */
export function AgendaWidget({ h }: { h: number }) {
  const now = useNow(60_000);
  const today = isoDay(now);
  const { data, error } = useEvery(`agenda:${today}`, () => deskApi.calendar(today, today), [today]);
  if (!data) return <Waiting error={error} />;
  const events = data.events.filter((event) => !event.done && event.kind !== "schedule" && event.start.slice(0, 10) <= today && (event.end ?? event.start).slice(0, 10) >= today);
  const allDay = events.filter((event) => event.all_day || event.start.length <= 10);
  const height = bodyPixels(h) - (allDay.length ? 24 : 0);
  // Whole hours that fill the card: about HOUR_PX each, stretched to the card's height.
  const hours = Math.max(2, Math.round(height / HOUR_PX));
  const hourPx = Math.floor(height / hours);
  const nowMinutes = minutesOf(now.toISOString());
  const from = Math.min(24 - hours, Math.max(0, Math.floor(nowMinutes / 60) - 1)) * 60;
  const placed = layOutDay(events, from, from + hours * 60, hourPx);
  const label = (hour: number) => `${String(hour).padStart(2, "0")}:00`;
  return <div className="dk-agenda">
    {allDay.length > 0 && <div className="dk-agenda-allday">{allDay.slice(0, 3).map((event) => <span key={event.id} style={{ borderColor: event.color ?? KIND_COLORS[event.kind] }}>{event.title}</span>)}{allDay.length > 3 && <small>+{allDay.length - 3}</small>}</div>}
    <div className="dk-agenda-hours" style={{ height: hours * hourPx }}>
      {Array.from({ length: hours }, (_, index) => <div key={index} className="dk-agenda-hour" style={{ top: index * hourPx }}><small>{label(from / 60 + index)}</small></div>)}
      {placed.map((item) => {
        const body = <><b>{item.event.title}</b><small>{new Date(item.event.start).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: displayTimeZone() })}</small></>;
        const style = { top: item.top, height: item.height, left: `calc(44px + (100% - 44px) * ${item.column / item.columns})`, width: `calc((100% - 44px) / ${item.columns} - 3px)`, borderColor: item.event.color ?? KIND_COLORS[item.event.kind] };
        return item.event.href ? <Go key={item.event.id} to={item.event.href} className="dk-agenda-event" style={style}>{body}</Go> : <div key={item.event.id} className="dk-agenda-event" style={style}>{body}</div>;
      })}
      {nowMinutes >= from && nowMinutes <= from + hours * 60 && <div className="dk-agenda-now" style={{ top: ((nowMinutes - from) / 60) * hourPx }} aria-label={t("Now")} />}
      {!events.length && <p className="dk-agenda-empty muted small">{t("Nothing on the calendar today.")}</p>}
    </div>
  </div>;
}

// --- Actions as a board ------------------------------------------------------------------

const KANBAN_STATUSES = ["open", "in_progress", "blocked"];

/** How many cards a column holds in a card `h` rows high. */
export function kanbanCards(h: number): number {
  return Math.max(1, Math.floor((bodyPixels(h) - 30) / 46));
}

/** The person's open actions as a small board; an editor drags a card to another column to move it. */
export function KanbanWidget({ view, h }: { view: ActionView; h: number }) {
  const { data, error, reload } = useEvery(`kanban:${view}`, () => collabApi.actions({ view, status: ["open", "in_progress", "blocked"] }), [view]);
  const [over, setOver] = useState<string | null>(null);
  const [moveError, setMoveError] = useState("");
  if (!data) return <Waiting error={error} />;
  const columns = boardColumns(data.items, data.statuses).filter((column) => KANBAN_STATUSES.includes(column.id));
  const fits = kanbanCards(h);
  async function drop(event: DragEvent, status: string) {
    event.preventDefault();
    setOver(null);
    const id = event.dataTransfer.getData("text/x-action");
    const action = data?.items.find((item) => String(item.action_id) === id);
    if (!action || action.status === status) return;
    try {
      await collabApi.updateAction(action.action_id, { title: action.title, description: action.description, priority: action.priority, owner: action.owner, group_id: action.group_id ?? null, due_at: action.due_at ? action.due_at.slice(0, 10) : null, refs: action.refs.map((ref) => ref.ref), status: status as ActionStatus });
      setMoveError("");
      reload();
    } catch (err) {
      setMoveError(errorText(err));
    }
  }
  const today = isoDay(new Date());
  return <div className="dk-kanban pc-cards-nodrag">
    {columns.map((column) => <section key={column.id} className={`dk-kanban-col${over === column.id ? " over" : ""}`} aria-label={column.label}
      onDragOver={(event) => { event.preventDefault(); setOver(column.id); }} onDragLeave={() => setOver((current) => (current === column.id ? null : current))} onDrop={(event) => void drop(event, column.id)}>
      <header><span className={`act-status act-status-${column.id}`}>{column.label}</span><b className="pc-num">{column.items.length}</b></header>
      <ol>{column.items.slice(0, fits).map((action: Action) => {
        const late = Boolean(action.due_at && action.due_at.slice(0, 10) < today);
        return <li key={action.action_id}>
          <Go to={`/actions/${action.action_id}`} className={`dk-kanban-card priority-edge-${action.priority}`} draggable onDragStart={(event: DragEvent) => { event.dataTransfer.setData("text/x-action", String(action.action_id)); event.dataTransfer.effectAllowed = "move"; }}>
            <b>{action.title}</b>
            <small className={late ? "due-overdue" : undefined}>{action.due_at ? (late ? t("late") : new Date(`${action.due_at.slice(0, 10)}T12:00:00`).toLocaleDateString(locale, { day: "numeric", month: "short" })) : action.owner_name ?? ""}</small>
          </Go>
        </li>;
      })}</ol>
      {column.items.length > fits && <Go to={`/actions?view=${view}`} className="dk-kanban-more">{t("{count} more", { count: column.items.length - fits })}</Go>}
    </section>)}
    {moveError && <p className="form-error small dk-kanban-error">{moveError}</p>}
  </div>;
}

// --- Unread chats ------------------------------------------------------------------------

/** The person's conversations with people (not the suite's notices), unread first. */
export function chatsOf(items: Conversation[], me: string): Conversation[] {
  return items.filter((item) => item.members.some((member) => member.username !== me && member.kind !== "system"))
    .sort((a, b) => (b.unread > 0 ? 1 : 0) - (a.unread > 0 ? 1 : 0) || (b.last_message?.created_at ?? b.updated_at).localeCompare(a.last_message?.created_at ?? a.updated_at));
}

/** Unread chat messages: a count on a small card, the conversations on a larger one; one opens Messages over Desk. */
export function ChatsWidget({ me, h, rows }: { me: string; h: number; rows: number }) {
  const { data, error } = useEvery("chats", () => collabApi.conversations(), []);
  if (!data) return <Waiting error={error} />;
  const chats = chatsOf(data.items, me);
  const unread = chats.reduce((sum, item) => sum + item.unread, 0);
  const open = (id = "") => (event: { metaKey: boolean; ctrlKey: boolean; preventDefault: () => void }) => { if (event.metaKey || event.ctrlKey) return; event.preventDefault(); openMessages(id); };
  if (h <= 1) return <a className="pc-wg-link" href="/messages" onClick={open()}>
    <strong className="pc-wg-number" style={unread ? { color: statusVar("warning", "text") } : undefined}>{unread}</strong>
    <span className="pc-wg-label">{unread === 1 ? t("unread message") : t("unread messages")}</span>
  </a>;
  return <div className="pc-wg-list">
    {!chats.length && <p className="muted small"><MessagesSquare size={14} /> {t("No conversation yet.")}</p>}
    {chats.slice(0, rows).map((item) => <a key={item.conversation_id} href={`/messages/${item.conversation_id}`} className={`pc-wg-row${item.unread ? " dk-unread" : ""}`} onClick={open(String(item.conversation_id))}>
      <span className="pc-wg-dot" style={{ background: item.unread ? "var(--pc-primary)" : "transparent" }} aria-hidden="true" />
      <span className="pc-wg-row-text"><b>{item.display_title}</b><small>{item.last_message ? `${item.last_message.author_name}: ${plainMentions(item.last_message.text).replace(/\s+/g, " ")}` : t("No message yet")}</small></span>
      <span className="pc-wg-row-value dk-due">{item.unread ? item.unread : item.last_message ? shortAgo(item.last_message.created_at) : ""}</span>
    </a>)}
    <a href="/messages" className="pc-wg-more" onClick={open()}>{t("Open Messages")}</a>
  </div>;
}

/** "5 min ago", "3 days ago", then the day alone ("Oct 18"): the row's corner is narrow. */
export function shortAgo(value: string, now: number = Date.now()): string {
  const stamp = Date.parse(value);
  return !Number.isNaN(stamp) && now - stamp > 7 * 86_400_000 ? formatDate(value, { month: "short", day: "numeric" }) : formatAgo(value, now);
}

// --- Quick note --------------------------------------------------------------------------

export const NOTE_MAX = 4000;

/** A note kept with the widget, saved as the person types (Notes, with mentions, come with Desk's Notes page). */
export function QuickNoteWidget({ config, setConfig }: { config: WidgetConfig; setConfig?: (config: WidgetConfig) => void }) {
  const [text, setText] = useState(typeof config.text === "string" ? config.text : "");
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef(config);
  latest.current = config;
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const change = (value: string) => {
    setText(value);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setConfig?.({ ...latest.current, text: value }), 700);
  };
  return <textarea className="dk-note pc-cards-nodrag" value={text} maxLength={NOTE_MAX} readOnly={!setConfig}
    onChange={(event) => change(event.target.value)} onBlur={() => { window.clearTimeout(timer.current); if (setConfig && text !== config.text) setConfig({ ...latest.current, text }); }}
    placeholder={t("A quick note: a phone number, what to say at the meeting…")} aria-label={t("Quick note")} />;
}

export { addDays };
