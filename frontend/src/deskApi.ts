/** Desk, each person's day (docs/desk.md): its own API under /api/desk. */
import { requestJson } from "./api";
import type { ResolvedRef } from "./collabApi";

export type TodoRepeat = "" | "daily" | "weekdays" | "days";
export type TodoStep = { text: string; done: boolean };
export type Todo = { todo_id: number; username: string | null; group_id: string | null; list_id: number | null; title: string; notes: string; due: string | null; repeat: TodoRepeat; days: number[]; steps: TodoStep[]; my_day: string | null; done: boolean; done_at: string | null; done_by: string | null; action_id: number | null; position: number };
export type TodoList = { list_id: number; owner: string | null; group_id: string | null; name: string; color: string; position: number; group_name: string | null; open: number; editable: boolean };
export type TodoViewName = "today" | "planned" | "all" | "done" | "list" | "apps";
/** A to-do an app gave the person or their group ([[contributes.todo]], docs/api-v1.md). */
export type AppTodo = { app: string; app_name: string; key: string; kind: string; kind_title: string; title: string; for: string; group_name: string | null; due: string | null; ref: string | null; url: string | null; detail: string; done: boolean; done_at: string | null; done_by: string | null };
export type TodoView = { day: string; view: TodoViewName; repeats: Array<{ id: TodoRepeat; label: string }>; lists: TodoList[]; counts: { today: number; planned: number; all: number; inbox: number; apps: number }; groups: Array<{ group_id: string; name: string }>; items: Todo[]; actions?: Array<{ action_id: number; title: string; due_at: string; href: string; late: boolean }>; events?: CalendarEvent[]; app_todos?: AppTodo[] };
export type TodoDraft = { title?: string; list_id?: number | null; due?: string | null; repeat?: TodoRepeat; days?: number[]; my_day?: boolean; notes?: string; steps?: TodoStep[]; done?: boolean; position?: number };
export type Suggestion = { key: string; title: string; reason: string; state: string; href: string; action: string };
export type Followed = { ref: string; name: string; kind_label: string | null; href: string | null; exists: boolean; status: string; summary: string; app: string | null; kind: string | null; at: string | null; open_actions: number };
export type DeskToday = { day: string; todos: Todo[]; actions: { open: number; overdue: number; today: number }; followed: Followed[]; suggestions: Suggestion[]; unread: number };
export type CalendarKind = "event" | "action" | "todo" | "alarm" | "schedule" | "feed" | "external";
/** A calendar feed an app keeps ([[contributes.calendar]]): one chip each. */
export type AppFeed = { id: string; app: string; app_name: string; title: string; description: string; visible: boolean };
export type CalendarEvent = { id: string; title: string; start: string; end?: string | null; all_day: boolean; kind: CalendarKind; href?: string | null; done?: boolean; editable: boolean; state?: string; detail?: string; color?: string; calendar?: string; app?: string; feed?: string; event_id?: number; repeat?: Repeat; series_start?: string; series_end?: string; runs?: ScheduledRun[] };
export type Repeat = "" | "daily" | "weekdays" | "weekly" | "monthly";
export type ScheduledRun = { title: string; start: string; app: string; href?: string | null; detail?: string };
export type OwnEvent = { event_id: number; title: string; start: string; end: string; all_day: boolean; repeat: Repeat; until: string | null; notes: string };
export type EventDraft = { title?: string; start?: string; end?: string | null; all_day?: boolean; repeat?: Repeat; until?: string | null; notes?: string };
export type CalendarSource = { calendar_id: number; name: string; kind: "file" | "url"; color: string; fetched_at: string | null; error: string; count: number; host?: string };
export type CalendarRange = { start: string; end: string; today: string; events: CalendarEvent[]; calendars: CalendarSource[]; feeds?: AppFeed[]; links: boolean; repeats: Array<{ id: Repeat; label: string }> };
export type NoteShare = { ref: string; name: string };
export type NoteSummary = { note_id: number; owner: string; owner_name: string; mine: boolean; title: string; body_text: string; shared: NoteShare[]; event_ref: string | null; pinned: boolean; created_at: string; updated_at: string; updated_by: string };
export type Note = NoteSummary & { body: Record<string, unknown>; refs: ResolvedRef[] };
export type NoteDraft = { title?: string; body?: Record<string, unknown>; text?: string; shared?: string[]; pinned?: boolean; event_ref?: string | null };
export type TeamPerson = { username: string; display_name: string; leader: boolean; you: boolean; availability: "" | "away" | "busy"; open: number; late: number };
export type TeamCard = { action_id: number; title: string; status: string; status_label: string; priority: string; priority_label: string; owner: string | null; owner_name: string | null; due_at: string | null; late: boolean; href: string };
export type TeamAgendaItem = { day: string; kind: "action" | "todo" | "away"; title: string; who: string | null; href: string | null; late: boolean };
export type TeamHandover = { day: string; note_id: number; title: string; snippet: string; updated_at: string };
export type TeamAsset = { ref: string; name: string; href: string | null; status: string; summary: string; followers: string[] };
export type TeamGroup = {
  group_id: string; name: string; kind_label: string; leader: boolean; coordinator_name: string | null; day: string;
  people: TeamPerson[]; board: TeamCard[]; statuses: Array<{ id: string; label: string }>; agenda: TeamAgendaItem[];
  handover: TeamHandover | null; handovers: TeamHandover[]; assets: TeamAsset[]; lists: TodoList[];
};
export type TeamGlance = { group_id: string; name: string; kind_label: string; leader: boolean; coordinator_name: string | null; people: TeamPerson[]; open: number; late: number; away: number; busy: number };
export type Team = { groups: Array<{ group_id: string; name: string; kind_label: string; leader: boolean; mine?: boolean }>; group: TeamGroup | null; overview: TeamGlance[] | null };
export type DeskSettings = { calendar_links: boolean; enabled: boolean; hosts: string[] };

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const deskApi = {
  today: () => requestJson<DeskToday>("/api/desk/today"),
  todos: (view: TodoViewName, listId?: number) => requestJson<TodoView>(`/api/desk/todos?view=${view}${listId ? `&list_id=${listId}` : ""}`),
  createTodo: (draft: TodoDraft & { title: string }) => requestJson<Todo>("/api/desk/todos", { method: "POST", ...json(draft) }),
  changeTodo: (id: number, change: TodoDraft) => requestJson<Todo>(`/api/desk/todos/${id}`, { method: "PATCH", ...json(change) }),
  completeAppTodo: (todo: AppTodo, done: boolean) => requestJson<AppTodo>(`/api/desk/app-todos/${encodeURIComponent(todo.app)}/${encodeURIComponent(todo.key)}`, { method: "POST", ...json({ done }) }),
  deleteTodo: (id: number) => requestJson<{ deleted: number }>(`/api/desk/todos/${id}`, { method: "DELETE" }),
  todoToAction: (id: number, who: { owner?: string | null; group_id?: string | null }) => requestJson<{ action_id: number; href: string }>(`/api/desk/todos/${id}/action`, { method: "POST", ...json(who) }),
  createList: (name: string, groupId?: string | null) => requestJson<TodoList>("/api/desk/todo-lists", { method: "POST", ...json({ name, group_id: groupId ?? null }) }),
  changeList: (id: number, change: { name?: string; color?: string }) => requestJson<TodoList>(`/api/desk/todo-lists/${id}`, { method: "PATCH", ...json(change) }),
  deleteList: (id: number) => requestJson<{ deleted: number }>(`/api/desk/todo-lists/${id}`, { method: "DELETE" }),
  notes: (q = "", event?: string) => requestJson<{ items: NoteSummary[] }>(`/api/desk/notes?${new URLSearchParams({ q, ...(event ? { event } : {}) })}`),
  note: (id: number) => requestJson<Note>(`/api/desk/notes/${id}`),
  createNote: (draft: NoteDraft) => requestJson<Note>("/api/desk/notes", { method: "POST", ...json(draft) }),
  changeNote: (id: number, change: NoteDraft) => requestJson<Note>(`/api/desk/notes/${id}`, { method: "PATCH", ...json(change) }),
  deleteNote: (id: number) => requestJson<{ deleted: number }>(`/api/desk/notes/${id}`, { method: "DELETE" }),
  follows: () => requestJson<{ items: Followed[] }>("/api/desk/follows"),
  following: (ref: string) => requestJson<{ ref: string; following: boolean }>(`/api/desk/follows?ref=${encodeURIComponent(ref)}`),
  follow: (ref: string) => requestJson<{ ref: string; following: boolean }>("/api/desk/follows", { method: "PUT", ...json({ ref }) }),
  unfollow: (ref: string) => requestJson<{ ref: string; following: boolean }>(`/api/desk/follows?ref=${encodeURIComponent(ref)}`, { method: "DELETE" }),
  calendar: (start: string, end: string) => requestJson<CalendarRange>(`/api/desk/calendar?start=${start}&end=${end}`),
  event: (id: number) => requestJson<OwnEvent>(`/api/desk/events/${id}`),
  createEvent: (draft: EventDraft) => requestJson<OwnEvent>("/api/desk/events", { method: "POST", ...json(draft) }),
  changeEvent: (id: number, change: EventDraft) => requestJson<OwnEvent>(`/api/desk/events/${id}`, { method: "PATCH", ...json(change) }),
  deleteEvent: (id: number) => requestJson<{ deleted: number }>(`/api/desk/events/${id}`, { method: "DELETE" }),
  calendars: () => requestJson<{ items: CalendarSource[]; links: boolean }>("/api/desk/calendars"),
  importCalendar: (name: string, ics: string) => requestJson<CalendarSource>("/api/desk/calendars", { method: "POST", ...json({ name, ics }) }),
  subscribeCalendar: (name: string, url: string) => requestJson<CalendarSource>("/api/desk/calendars", { method: "POST", ...json({ name, url }) }),
  refreshCalendar: (id: number) => requestJson<CalendarSource>(`/api/desk/calendars/${id}/refresh`, { method: "POST" }),
  deleteCalendar: (id: number) => requestJson<{ deleted: number }>(`/api/desk/calendars/${id}`, { method: "DELETE" }),
  triage: (key: string, state: "done" | "snoozed" | null, until?: string) => requestJson<{ key: string }>("/api/desk/triage", { method: "POST", ...json({ key, state, until }) }),
  team: (group?: string) => requestJson<Team>(`/api/desk/team${group ? `?${new URLSearchParams({ group })}` : ""}`),
  assign: (group: string, change: { action_id: number; owner?: string | null; status?: string }) => requestJson<{ action_id: number; owner: string | null; status: string }>(`/api/desk/team/${encodeURIComponent(group)}/assign`, { method: "POST", ...json(change) }),
  handover: (group: string) => requestJson<Note>(`/api/desk/team/${encodeURIComponent(group)}/handover`, { method: "POST" }),
  settings: () => requestJson<DeskSettings>("/api/desk/settings"),
  teamPage: () => requestJson<{ enabled: boolean }>("/api/desk/team-page"),
  saveTeamPage: (enabled: boolean) => requestJson<{ enabled: boolean }>("/api/desk/team-page", { method: "PUT", ...json({ enabled }) }),
  saveSettings: (enabled: boolean, hosts: string[]) => requestJson<DeskSettings>("/api/desk/settings", { method: "PUT", ...json({ enabled, hosts }) }),
};

/** "2026-10-23" in the browser's own day (not UTC). */
export function isoDay(day: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

export function addDays(day: Date, count: number): Date {
  const next = new Date(day);
  next.setDate(next.getDate() + count);
  return next;
}

/** Events grouped by day for the coming-days list (a phone's calendar widget): today first. */
export function upcoming(events: CalendarEvent[], today: string, days: number): Array<{ day: string; events: CalendarEvent[] }> {
  const last = isoDay(addDays(new Date(`${today}T12:00:00`), days - 1));
  const groups = new Map<string, CalendarEvent[]>();
  for (const event of events) {
    const start = event.start.slice(0, 10);
    const end = (event.end ?? event.start).slice(0, 10);
    // A several-day event shows on today when it began before and still runs.
    const day = start < today && end >= today ? today : start;
    if (day < today || day > last) continue;
    if (!groups.has(day)) groups.set(day, []);
    groups.get(day)!.push(event);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([day, list]) => ({ day, events: list }));
}
