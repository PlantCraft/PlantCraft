/**
 * Desk › Calendar (round 7 2026-10-24): everything with a date in one
 * calendar, month, week, day or list (FullCalendar, MIT): the person's own events (a click or a
 * drag on the calendar makes one; they move, stretch and repeat), their actions and their
 * groups' by due date (dragging one changes its due date), their to-dos (a repeated one on each day ahead), alarms
 * on the assets they follow, the scheduled runs of their apps (an hour's runs together, hidden
 * until asked for), and calendars read from elsewhere (Outlook, Google, any .ics), read only.
 */
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import listPlugin from "@fullcalendar/list";
import multiMonthPlugin from "@fullcalendar/multimonth";
import timeGridPlugin from "@fullcalendar/timegrid";
import ptBrLocale from "@fullcalendar/core/locales/pt-br";
import type { DatesSetArg, DateSelectArg, EventApi, EventClickArg, EventDropArg, EventInput } from "@fullcalendar/core";
import type { EventResizeDoneArg } from "@fullcalendar/interaction";
import { CalendarPlus, ChevronLeft, ChevronRight, Link2, LoaderCircle, Plus, RefreshCw, StickyNote, Trash2, Upload, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { useAssistantPage } from "@plantcraft/ui";
import { errorText } from "./collab";
import { collabApi } from "./collabApi";
import { PageHeading } from "./DeskPages";
import { addDays, deskApi, isoDay, type AppFeed, type CalendarEvent, type CalendarKind, type CalendarRange, type CalendarSource, type EventDraft, type Repeat, type ScheduledRun } from "./deskApi";
import { language, t } from "./i18n";
import { navigate } from "./nav";
import { isLocalHref } from "./collab";
import "./desk.css";

const KINDS: Array<{ id: CalendarKind; label: string; color: string }> = [
  { id: "event", label: t("My events"), color: "var(--pc-primary)" },
  { id: "action", label: t("Actions"), color: "var(--pc-app-desk)" },
  { id: "todo", label: t("To-do"), color: "var(--pc-good-fill)" },
  { id: "alarm", label: t("Alarms on what I follow"), color: "var(--pc-problem-fill)" },
  { id: "schedule", label: t("Scheduled runs"), color: "var(--pc-text-3)" },
  { id: "external", label: t("Other calendars"), color: "var(--pc-text-3)" },
];
// The apps' runs start hidden: a plant runs many, and they would bury the rest (round 7).
const HIDDEN_KEY = "processcraft:desk-calendar-hidden-2";
const HIDDEN_DEFAULT: string[] = ["schedule"];
const MAX_FILE = 2_000_000;

function readHidden(): string[] {
  try {
    const stored = window.localStorage.getItem(HIDDEN_KEY);
    return stored ? JSON.parse(stored) as string[] : HIDDEN_DEFAULT;
  } catch { return HIDDEN_DEFAULT; }
}

/** The key a feed's chip keeps in the hidden list: off for a visible feed, on for one that starts off. */
export function feedKey(feed: AppFeed): string {
  return feed.visible ? `feed:${feed.id}` : `+feed:${feed.id}`;
}

/** Whether an app's feed is shown, given the chips the person switched. */
export function feedShown(feed: AppFeed, hidden: string[]): boolean {
  return hidden.includes(feedKey(feed)) !== feed.visible;
}

/** One event as FullCalendar draws it. */
export function toInput(event: CalendarEvent): EventInput {
  const color = event.color ?? KINDS.find((kind) => kind.id === event.kind)?.color;
  const external = event.kind === "external" || event.kind === "schedule" || event.kind === "feed";
  const own = event.kind === "event";
  return {
    id: event.id, title: event.title, start: event.start, end: event.end ?? undefined, allDay: event.all_day,
    editable: (own || event.kind === "action") && event.editable, durationEditable: own,
    backgroundColor: external ? "transparent" : color, borderColor: color, textColor: external ? "var(--pc-text)" : "var(--pc-on-accent)",
    classNames: [`dk-ev-${event.kind}`, ...(event.done ? ["dk-ev-done"] : []), ...(external ? ["dk-ev-outline"] : [])],
    extendedProps: {
      href: event.href ?? null, kind: event.kind, detail: event.detail ?? "", calendar: event.calendar ?? "",
      eventId: event.event_id ?? null, repeat: event.repeat ?? "", seriesStart: event.series_start ?? null, seriesEnd: event.series_end ?? null, runs: event.runs ?? null,
    },
  };
}

/** A day ("2026-10-24", the browser's midnight) or an instant ("…Z") as a Date. */
function when(value: string): Date {
  return value.length <= 10 ? new Date(`${value}T00:00:00`) : new Date(value);
}

function stamp(day: Date, allDay: boolean): string {
  return allDay ? isoDay(day) : day.toISOString();
}

/**
 * What a drag or a stretch of one time of an event changes: the series moves by as much as that
 * time moved (a repeat moves whole). Moved between the all-day row and the hours, it keeps its
 * new start and takes the default length.
 */
export function seriesMove(series: { start: string; end: string; allDay: boolean }, before: { start: Date; end: Date | null }, after: { start: Date; end: Date | null; allDay: boolean }): EventDraft {
  const shift = after.start.getTime() - before.start.getTime();
  const start = new Date(when(series.start).getTime() + shift);
  if (after.allDay !== series.allDay) {
    // The series' first day moves by as many days; the hours (if any) are the new ones.
    const days = Math.round((when(isoDay(after.start)).getTime() - when(isoDay(before.start)).getTime()) / 86_400_000);
    const day = addDays(when(series.start.length <= 10 ? series.start : isoDay(when(series.start))), days);
    if (!after.allDay) day.setHours(after.start.getHours(), after.start.getMinutes(), 0, 0);
    return { all_day: after.allDay, start: stamp(day, after.allDay), end: null };
  }
  const endShift = (after.end ?? after.start).getTime() - (before.end ?? before.start).getTime();
  const end = new Date(when(series.end).getTime() + endShift);
  return { start: stamp(start, after.allDay), end: stamp(end, after.allDay) };
}

/** "2026-10-24T09:30" in the browser's time for a datetime-local field. */
export function localInput(value: Date): string {
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${isoDay(value)}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

type Draft = { id: number | null; title: string; allDay: boolean; start: string; end: string; repeat: Repeat; until: string; notes: string };

/** The dialog's fields for an event: an all-day event shows its last day (stored as the day after). */
export function draftOf(event: { title: string; start: string; end: string; all_day: boolean; repeat?: Repeat; until?: string | null; notes?: string }, id: number | null = null): Draft {
  return {
    id, title: event.title, allDay: event.all_day, repeat: event.repeat ?? "", until: event.until ?? "", notes: event.notes ?? "",
    start: event.all_day ? event.start.slice(0, 10) : localInput(when(event.start)),
    end: event.all_day ? isoDay(addDays(when(event.end), -1)) : localInput(when(event.end)),
  };
}

export function draftBody(draft: Draft): EventDraft {
  const start = draft.allDay ? draft.start.slice(0, 10) : new Date(draft.start).toISOString();
  const end = draft.allDay ? isoDay(addDays(when((draft.end || draft.start).slice(0, 10)), 1)) : draft.end ? new Date(draft.end).toISOString() : null;
  return { title: draft.title.trim(), all_day: draft.allDay, start, end, repeat: draft.repeat, until: draft.repeat && draft.until ? draft.until : null, notes: draft.notes };
}

function EventDialog({ initial, repeats, onDone, onClose }: { initial: Draft; repeats: Array<{ id: Repeat; label: string }>; onDone: () => void; onClose: () => void }) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (change: Partial<Draft>) => setDraft((current) => ({ ...current, ...change }));
  function allDay(on: boolean) {
    // The day stays; the hours come back as 09:00 to 10:00.
    const day = draft.start.slice(0, 10);
    set(on ? { allDay: true, start: day, end: draft.end.slice(0, 10) || day } : { allDay: false, start: `${day}T09:00`, end: `${day}T10:00` });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = draftBody(draft);
      if (draft.id === null) await deskApi.createEvent(body);
      else await deskApi.changeEvent(draft.id, body);
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (draft.id === null) return;
    setBusy(true);
    try {
      await deskApi.deleteEvent(draft.id);
      onDone();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }
  const title = draft.id === null ? t("New event") : t("Event");
  return <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="dialog dk-cal-dialog" role="dialog" aria-label={title} onSubmit={(event) => void submit(event)}>
      <header><h2>{title}</h2><button type="button" className="pcs-icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <label>{t("Title")}<input id="dk-ev-title" value={draft.title} maxLength={200} required autoFocus onChange={(event) => set({ title: event.target.value })} placeholder={t("Shift handover")} /></label>
      <label className="dk-check-label"><input type="checkbox" checked={draft.allDay} onChange={(event) => allDay(event.target.checked)} /> {t("All day")}</label>
      <div className="dk-ev-times">
        <label>{t("Starts")}<input id="dk-ev-start" type={draft.allDay ? "date" : "datetime-local"} value={draft.start} required onChange={(event) => set({ start: event.target.value })} /></label>
        <label>{draft.allDay ? t("Last day") : t("Ends")}<input id="dk-ev-end" type={draft.allDay ? "date" : "datetime-local"} value={draft.end} min={draft.start} onChange={(event) => set({ end: event.target.value })} /></label>
      </div>
      <div className="dk-ev-times">
        <label>{t("Repeat")}<select id="dk-ev-repeat" value={draft.repeat} onChange={(event) => set({ repeat: event.target.value as Repeat })}>
          {repeats.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
        </select></label>
        {draft.repeat && <label>{t("Until (optional)")}<input id="dk-ev-until" type="date" value={draft.until} min={draft.start.slice(0, 10)} onChange={(event) => set({ until: event.target.value })} /></label>}
      </div>
      {draft.id !== null && initial.repeat && <p className="muted small">{t("A change here, or a drag on the calendar, changes every time it repeats.")}</p>}
      <label>{t("Notes")}<textarea id="dk-ev-notes" rows={3} maxLength={2000} value={draft.notes} onChange={(event) => set({ notes: event.target.value })} /></label>
      {error && <p className="form-error">{error}</p>}
      <footer>
        {draft.id !== null && <button type="button" className="button button-secondary danger dk-ev-delete" disabled={busy} onClick={() => void remove()}><Trash2 size={14} /> {t("Delete")}</button>}
        {draft.id !== null && <button type="button" className="button button-secondary" onClick={() => navigate(`/notes?${new URLSearchParams({ event: `event:${draft.id}`, title: draft.title })}`)} title={t("A note for this event: the agenda, what was said, what comes next.")}><StickyNote size={14} /> {t("Event note")}</button>}
        <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button type="submit" className="button button-primary" disabled={busy || !draft.title.trim()}>{busy ? <LoaderCircle size={14} className="spin" /> : null} {t("Save")}</button>
      </footer>
    </form>
  </div>;
}

function RunsDialog({ title, runs, onClose }: { title: string; runs: ScheduledRun[]; onClose: () => void }) {
  // The calendar draws on this device's clock (FullCalendar's), so its times do too: device clock.
  const time = (value: string) => new Date(value).toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });
  return <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="dialog dk-cal-dialog" role="dialog" aria-label={title}>
      <header><h2>{title}</h2><button type="button" className="pcs-icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <ul className="dk-runs">{runs.map((run) => <li key={`${run.app}:${run.title}:${run.start}`}>
        <time>{time(run.start)}</time>
        {run.href ? <a href={run.href} onClick={(event) => { if (run.href && isLocalHref(run.href)) { event.preventDefault(); navigate(run.href); } }}>{run.title}</a> : <span>{run.title}</span>}
        <small className="muted">{run.detail}</small>
      </li>)}</ul>
    </div>
  </div>;
}

function AddCalendar({ links, onDone, onClose }: { links: boolean; onDone: () => void; onClose: () => void }) {
  const [mode, setMode] = useState<"file" | "url">("file");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function pick(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_FILE) { setError(t("The calendar is larger than 2 MB.")); return; }
    if (!name) setName(file.name.replace(/\.ics$/i, ""));
    void file.text().then(setText);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "file") {
        if (!text) throw new Error(t("Choose an .ics file."));
        await deskApi.importCalendar(name || t("Calendar"), text);
      } else {
        await deskApi.subscribeCalendar(name || t("Calendar"), url);
      }
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return <div className="dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form className="dialog dk-cal-dialog" role="dialog" aria-label={t("Add a calendar")} onSubmit={(event) => void submit(event)}>
      <header><h2>{t("Add a calendar")}</h2><button type="button" className="pcs-icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="pc-segmented" role="group" aria-label={t("How")}>
        <button type="button" className={mode === "file" ? "on" : ""} onClick={() => setMode("file")}><Upload size={14} /> {t("Import an .ics file")}</button>
        <button type="button" className={mode === "url" ? "on" : ""} onClick={() => setMode("url")}><Link2 size={14} /> {t("Calendar link")}</button>
      </div>
      <label>{t("Name")}<input id="dk-cal-name" value={name} maxLength={200} onChange={(event) => setName(event.target.value)} placeholder={t("Outlook")} /></label>
      {mode === "file" ? <>
        <label>{t("File")}<input id="dk-cal-file" type="file" accept=".ics,text/calendar" onChange={pick} /></label>
        <p className="muted small">{t("In Outlook: File › Save calendar (or Export). In Google Calendar: Settings › Import and export › Export. The events are copied once; import the file again to bring it up to date.")}</p>
      </> : <>
        <label>{t("Link (https:// or webcal://)")}<input id="dk-cal-url" value={url} maxLength={2000} onChange={(event) => setUrl(event.target.value)} placeholder="https://outlook.office365.com/owa/calendar/…/calendar.ics" /></label>
        <p className="muted small">{links
          ? t("In Outlook: Settings › Calendar › Shared calendars › Publish a calendar, then copy the ICS link. In Google Calendar: the calendar's settings › Secret address in iCal format. It is read again every 15 minutes."):
          t("Calendar links are off: PlantCraft may run with no internet. An administrator turns them on in Settings › Calendars and names the servers allowed. Until then, import an .ics file.")}</p>
      </>}
      {error && <p className="form-error">{error}</p>}
      <footer>
        <button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button>
        <button type="submit" className="button button-primary" disabled={busy || (mode === "url" && !links)}>{busy ? <LoaderCircle size={14} className="spin" /> : <CalendarPlus size={14} />} {t("Add")}</button>
      </footer>
    </form>
  </div>;
}

function Sources({ sources, onChange }: { sources: CalendarSource[]; onChange: () => void }) {
  if (!sources.length) return null;
  return <ul className="dk-sources">{sources.map((source) => <li key={source.calendar_id}>
    <i style={{ borderColor: source.color }} aria-hidden="true" />
    <span><b>{source.name}</b><small>{source.kind === "url" ? `${source.host ?? ""} · ${t("read every 15 minutes")}` : t("{count} events imported", { count: source.count })}{source.error ? ` · ${source.error}` : ""}</small></span>
    {source.kind === "url" && <button type="button" className="pcs-icon-button" onClick={() => { void deskApi.refreshCalendar(source.calendar_id).then(onChange); }} aria-label={t("Read {name} again", { name: source.name })}><RefreshCw size={14} /></button>}
    <button type="button" className="pcs-icon-button" onClick={() => { void deskApi.deleteCalendar(source.calendar_id).then(onChange); }} aria-label={t("Remove {name}", { name: source.name })}><Trash2 size={14} /></button>
  </li>)}</ul>;
}

/** `?date=2026-10-24` (the month widget's day) opens the calendar on that day. */
export function linkedDay(search: string): string | null {
  const day = new URLSearchParams(search).get("date");
  return day && /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : null;
}

/** The month names of the person's language, January first. */
export function monthNames(locale: string, style: "long" | "short" = "short"): string[] {
  const format = new Intl.DateTimeFormat(locale, { month: style });
  return Array.from({ length: 12 }, (_, month) => format.format(new Date(2026, month, 1)));
}

/** The title's drop-down (round 8, like Apple's Calendar): a year with arrows, then its twelve
 * months; a month opens that month, the year opens the year view. */
function MonthPicker({ date, locale, onMonth, onYear, onClose }: { date: Date; locale: string; onMonth: (year: number, month: number) => void; onYear: (year: number) => void; onClose: () => void }) {
  const [year, setYear] = useState(date.getFullYear());
  const box = useRef<HTMLDivElement | null>(null);
  const now = new Date();
  useEffect(() => {
    const away = (event: MouseEvent) => { if (box.current && !box.current.contains(event.target as Node) && !(event.target as Element).closest?.(".fc-pickDate-button")) onClose(); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    box.current?.querySelector<HTMLButtonElement>(".on, button")?.focus();
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [onClose]);
  return <div className="dk-cal-picker" ref={box} role="dialog" aria-label={t("Go to a month")}>
    <div className="dk-cal-picker-year">
      <button type="button" className="button button-ghost button-icon" onClick={() => setYear(year - 1)} aria-label={t("Previous year")}><ChevronLeft size={16} /></button>
      <button type="button" className="dk-cal-picker-yearname" onClick={() => onYear(year)} title={t("Show the whole year")}>{year}</button>
      <button type="button" className="button button-ghost button-icon" onClick={() => setYear(year + 1)} aria-label={t("Next year")}><ChevronRight size={16} /></button>
    </div>
    <div className="dk-cal-picker-months">
      {monthNames(locale).map((name, month) => {
        const on = year === date.getFullYear() && month === date.getMonth();
        const today = year === now.getFullYear() && month === now.getMonth();
        return <button key={name} type="button" className={`${on ? "on" : ""}${today ? " today" : ""}`} aria-pressed={on} onClick={() => onMonth(year, month)}>{name}</button>;
      })}
    </div>
  </div>;
}

const VIEWS = { multiMonthYear: { dayMaxEvents: 1, multiMonthMaxColumns: 4, multiMonthMinWidth: 220 } };

export function CalendarPage() {
  const [day] = useState(() => linkedDay(window.location.search));
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);
  const [data, setData] = useState<CalendarRange | null>(null);
  const [error, setError] = useState("");
  const [hidden, setHidden] = useState<string[]>(readHidden);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Draft | null>(null);
  const [runs, setRuns] = useState<{ title: string; runs: ScheduledRun[] } | null>(null);
  const calendarRef = useRef<FullCalendar | null>(null);
  const [title, setTitle] = useState("");
  const [shown, setShown] = useState(() => new Date());
  const [picking, setPicking] = useState(false);
  const locale = language === "pt-BR" ? "pt-BR" : "en";
  const load = useCallback(() => {
    if (!range) return;
    deskApi.calendar(range.start, range.end).then((value) => { setData(value); setError(""); }).catch((err) => setError(errorText(err)));
  }, [range]);
  useEffect(load, [load]);
  // An event the assistant proposed and the person created from its card: show it.
  useEffect(() => { window.addEventListener("pc-assistant-created", load); return () => window.removeEventListener("pc-assistant-created", load); }, [load]);
  useAssistantPage({
    place: t("Desk › Calendar"), page: "processcraft:calendar",
    facts: { period: title, today: data?.today ?? "" },
    view: { start: range?.start ?? "", end: range?.end ?? "", items: (data?.events ?? []).slice(0, 30).map((event) => `${event.all_day ? event.start.slice(0, 10) : event.start.slice(0, 16)} ${event.title.slice(0, 80)} (${event.kind})`) },
  });
  useEffect(() => { try { window.localStorage.setItem(HIDDEN_KEY, JSON.stringify(hidden)); } catch { /* per browser only */ } }, [hidden]);
  const feeds = useMemo(() => new Map((data?.feeds ?? []).map((feed) => [feed.id, feed])), [data]);
  const events = useMemo(() => (data?.events ?? []).filter((event) => {
    if (event.kind !== "feed") return !hidden.includes(event.kind);
    const feed = feeds.get(event.feed ?? "");
    return feed ? feedShown(feed, hidden) : false;
  }).map(toInput), [data, hidden, feeds]);
  const datesSet = useCallback((arg: DatesSetArg) => {
    // FullCalendar draws its arrows as role="img" with no name; the button already has one.
    document.querySelectorAll<HTMLElement>('.dk-calendar .fc-icon[role="img"]').forEach((icon) => { icon.removeAttribute("role"); icon.setAttribute("aria-hidden", "true"); });
    // Unchanged values keep their state: FullCalendar calls this again on any option change.
    setTitle(arg.view.title);
    const start = arg.view.currentStart;
    setShown((current) => (current.getTime() === start.getTime() ? current : start));
    // FullCalendar's end is exclusive; the widest view (a year) is what the server answers at most.
    const end = new Date(arg.end);
    end.setDate(end.getDate() - 1);
    setRange((current) => {
      const next = { start: isoDay(arg.start), end: isoDay(end) };
      return current && current.start === next.start && current.end === next.end ? current : next;
    });
  }, []);
  function open(arg: EventClickArg) {
    const props = arg.event.extendedProps;
    if (props.kind === "event" && props.eventId) {
      arg.jsEvent.preventDefault();
      deskApi.event(props.eventId as number).then((event) => setEditing(draftOf(event, event.event_id))).catch((err) => setError(errorText(err)));
      return;
    }
    if (props.runs) {
      arg.jsEvent.preventDefault();
      setRuns({ title: arg.event.title, runs: props.runs as ScheduledRun[] });
      return;
    }
    const href = props.href as string | null;
    if (!href) return;
    arg.jsEvent.preventDefault();
    if (isLocalHref(href)) navigate(href);
    else window.location.assign(href);
  }
  function create(arg: DateSelectArg) {
    arg.view.calendar.unselect();
    // A click on a day of the month makes an all-day event; in the hours, an hour from there.
    const end = arg.allDay ? addDays(arg.end, -1) : arg.end.getTime() - arg.start.getTime() <= 30 * 60_000 ? new Date(arg.start.getTime() + 3_600_000) : arg.end;
    setEditing({ id: null, title: "", allDay: arg.allDay, repeat: "", until: "", notes: "", start: arg.allDay ? isoDay(arg.start) : localInput(arg.start), end: arg.allDay ? isoDay(end) : localInput(end) });
  }
  function newEvent() {
    const start = new Date();
    start.setMinutes(0, 0, 0);
    start.setHours(start.getHours() + 1);
    setEditing({ id: null, title: "", allDay: false, repeat: "", until: "", notes: "", start: localInput(start), end: localInput(new Date(start.getTime() + 3_600_000)) });
  }
  async function reshaped(event: EventApi, before: EventApi, revert: () => void) {
    const props = event.extendedProps;
    try {
      await deskApi.changeEvent(props.eventId as number, seriesMove(
        { start: props.seriesStart as string, end: props.seriesEnd as string, allDay: before.allDay },
        { start: before.start!, end: before.end },
        { start: event.start!, end: event.end, allDay: event.allDay },
      ));
      load();
    } catch (err) {
      revert();
      setError(errorText(err));
    }
  }
  async function moved(arg: EventDropArg) {
    if (arg.event.extendedProps.kind === "event") { await reshaped(arg.event, arg.oldEvent, arg.revert); return; }
    const id = String(arg.event.id).replace(/^action:/, "");
    const day = arg.event.start ? isoDay(arg.event.start) : null;
    try {
      const action = await collabApi.action(id);
      await collabApi.updateAction(id, {
        title: action.title, description: action.description, priority: action.priority, owner: action.owner,
        group_id: action.group_id ?? null, due_at: day, refs: action.refs.map((ref) => ref.ref), status: action.status,
      });
      load();
    } catch (err) {
      arg.revert();
      setError(errorText(err));
    }
  }
  const goMonth = (year: number, month: number) => { setPicking(false); calendarRef.current?.getApi().changeView("dayGridMonth", new Date(year, month, 1)); };
  const goYear = (year: number) => { setPicking(false); calendarRef.current?.getApi().changeView("multiMonthYear", new Date(year, 0, 1)); };
  const closePicker = useCallback(() => setPicking(false), []);
  const customButtons = useMemo(() => ({ pickDate: { text: title || " ", hint: t("Go to a month"), click: () => setPicking((open) => !open) } }), [title]);
  const openDay = useCallback((date: Date) => calendarRef.current?.getApi().changeView("timeGridDay", date), []);
  const toggle = (kind: string) => setHidden((current) => (current.includes(kind) ? current.filter((item) => item !== kind) : [...current, kind]));
  return <>
    <PageHeading eyebrow={t("Desk")} title={t("Calendar")} description={t("Everything with a date: your events, your actions and your groups', your to-dos, alarms on what you follow, your apps' scheduled runs and the calendars you add. Click or drag on the calendar to add an event; drag an action to change its due date.")}
      action={<div className="heading-actions">
        <button type="button" className="button button-secondary" onClick={() => setAdding(true)}><CalendarPlus size={15} /> {t("Add a calendar")}</button>
        <button type="button" className="button button-primary" onClick={newEvent}><Plus size={15} /> {t("New event")}</button>
      </div>} />
    <div className="dk-cal-filters" role="group" aria-label={t("Show")}>
      {KINDS.map((kind) => <button key={kind.id} type="button" className={`dk-chip${hidden.includes(kind.id) ? "" : " on"}`} aria-pressed={!hidden.includes(kind.id)} onClick={() => toggle(kind.id)}>
        <i style={{ background: kind.color }} aria-hidden="true" />{kind.label}
      </button>)}
      {/* One chip per feed an app keeps ([[contributes.calendar]]); a feed declared not visible starts off. */}
      {(data?.feeds ?? []).map((feed) => {
        const on = feedShown(feed, hidden);
        return <button key={feed.id} type="button" className={`dk-chip${on ? " on" : ""}`} aria-pressed={on} title={feed.description || undefined} onClick={() => toggle(feedKey(feed))}>
          <i style={{ background: "var(--pc-text-3)" }} aria-hidden="true" />{feed.app_name}: {feed.title}
        </button>;
      })}
    </div>
    {error && <div className="form-error">{error}</div>}
    <div className="panel dk-calendar">
      {picking && <MonthPicker date={shown} locale={locale} onMonth={goMonth} onYear={goYear} onClose={closePicker} />}
      <FullCalendar ref={calendarRef} plugins={[dayGridPlugin, timeGridPlugin, listPlugin, multiMonthPlugin, interactionPlugin]} initialView={day ? "timeGridDay" : window.innerWidth < 720 ? "listWeek" : "dayGridMonth"} initialDate={day ?? undefined}
        /* The title is a button: a click opens the month and year picker (round 8). */
        customButtons={customButtons}
        headerToolbar={{ left: "prev,next today", center: "pickDate", right: "multiMonthYear,dayGridMonth,timeGridWeek,timeGridDay,listWeek" }}
        views={VIEWS} navLinks navLinkDayClick={openDay}
        locales={[ptBrLocale]} locale={language === "pt-BR" ? "pt-br" : "en"} firstDay={1} height="auto" dayMaxEvents={4} nowIndicator
        selectable selectMirror slotEventOverlap={false} eventMaxStack={3} scrollTime="07:00:00" eventResizableFromStart={false}
        events={events} datesSet={datesSet} eventClick={open} select={create}
        eventDrop={(arg) => void moved(arg)} eventResize={(arg: EventResizeDoneArg) => void reshaped(arg.event, arg.oldEvent, arg.revert)} />
    </div>
    {data && <Sources sources={data.calendars} onChange={load} />}
    {editing && <EventDialog initial={editing} repeats={data?.repeats ?? [{ id: "", label: t("Does not repeat") }]} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
    {runs && <RunsDialog title={runs.title} runs={runs.runs} onClose={() => setRuns(null)} />}
    {adding && <AddCalendar links={data?.links ?? false} onClose={() => setAdding(false)} onDone={() => { setAdding(false); load(); }} />}
  </>;
}
