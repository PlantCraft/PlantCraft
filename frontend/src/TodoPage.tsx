/**
 * Desk › To-do (owner, round 7, 2026-10-24): what a person has to do, in the shape of Microsoft
 * To Do and the Mac's Reminders. My day (due by today, picked for today, the day's actions and
 * events beside them), Planned, All and Done; lists of their own and their groups' shared lists,
 * each with a colour. A one-line box adds a to-do; one opens on the right with its steps, date,
 * repeat (every day, on weekdays or on some days), list and notes, and turns into an action when
 * it needs someone else. Dragging a row (or Alt + an arrow key) changes the order. The day's
 * checklists and the routines of before became to-dos.
 */
import { AppWindow, ArrowRightCircle, CalendarDays, Check, CheckCircle2, Circle, GripVertical, Inbox, ListPlus, Plus, Repeat, Sun, Trash2, Users, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type DragEvent, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { displayTimeZone, useAssistantPage, askText, confirmAction } from "@plantcraft/ui";
import { errorText, isLocalHref } from "./collab";
import { PageHeading } from "./DeskPages";
import { addDays, deskApi, isoDay, type AppTodo, type Todo, type TodoList, type TodoRepeat, type TodoStep, type TodoView, type TodoViewName } from "./deskApi";
import { language, t } from "./i18n";
import { navigate } from "./nav";
import "./desk.css";

const WEEKDAYS = [t("Mon"), t("Tue"), t("Wed"), t("Thu"), t("Fri"), t("Sat"), t("Sun")];
const COLORS = ["#6a3d9a", "#0a64b2", "#00726b", "#9c4419", "#80591a", "#4a5a6e"];

type Place = { view: TodoViewName; list: number | null };

/** `?view=planned`, `?list=3` and `?item=12` (a to-do opened from the calendar). */
export function placeOf(search: string): Place & { item: number | null } {
  const params = new URLSearchParams(search);
  const list = Number(params.get("list")) || null;
  const view = (["today", "planned", "all", "done", "apps"] as const).find((name) => name === params.get("view"));
  return { view: list ? "list" : view ?? "today", list, item: Number(params.get("item")) || null };
}

/** "Today", "Tomorrow", "Late · Oct 22" or the day, for a to-do's date. */
export function dueText(due: string | null, today: string): { text: string; late: boolean } | null {
  if (!due) return null;
  const late = due < today;
  if (due === today) return { text: t("Today"), late: false };
  if (due === isoDay(addDays(new Date(`${today}T12:00:00`), 1))) return { text: t("Tomorrow"), late: false };
  const day = new Date(`${due}T12:00:00`).toLocaleDateString(language, { weekday: "short", day: "numeric", month: "short" });
  return { text: late ? t("Late · {day}", { day }) : day, late };
}

/** The order after moving `id` to `index` among `items`: the positions to send (only those that change). */
export function reorder(items: Todo[], id: number, index: number): Array<{ todo_id: number; position: number }> {
  const moving = items.find((item) => item.todo_id === id);
  if (!moving) return [];
  const rest = items.filter((item) => item.todo_id !== id);
  rest.splice(Math.max(0, Math.min(index, rest.length)), 0, moving);
  return rest.map((item, position) => ({ todo_id: item.todo_id, position: position * 10 })).filter((entry) => items.find((item) => item.todo_id === entry.todo_id)?.position !== entry.position);
}

function repeatText(todo: Todo, labels: Map<string, string>): string {
  if (todo.repeat !== "days") return labels.get(todo.repeat) ?? "";
  return todo.days.map((day) => WEEKDAYS[day]).join(", ");
}

function Row({ todo, data, labels, selected, onOpen, onToggle, onDrag, onKey }: {
  todo: Todo; data: TodoView; labels: Map<string, string>; selected: boolean;
  onOpen: () => void; onToggle: () => void; onDrag: (event: DragEvent<HTMLLIElement>) => void; onKey: (event: KeyboardEvent<HTMLLIElement>) => void;
}) {
  const list = data.lists.find((item) => item.list_id === todo.list_id);
  const due = dueText(todo.due, data.day);
  const steps = todo.steps.length ? `${todo.steps.filter((step) => step.done).length}/${todo.steps.length}` : "";
  const meta = [
    list ? <span key="list" className="dk-todo-list-tag"><i style={{ background: list.color }} aria-hidden="true" />{list.name}</span> : null,
    todo.my_day === data.day && data.view !== "today" ? <span key="day"><Sun size={12} aria-hidden="true" /> {t("My day")}</span> : null,
    due ? <span key="due" className={due.late && !todo.done ? "dk-todo-late" : undefined}><CalendarDays size={12} aria-hidden="true" /> {due.text}</span> : null,
    todo.repeat ? <span key="repeat" title={repeatText(todo, labels)}><Repeat size={12} aria-label={t("Repeats")} /> {repeatText(todo, labels)}</span> : null,
    steps ? <span key="steps">{t("{done} steps", { done: steps })}</span> : null,
    todo.group_id && !list ? <span key="group"><Users size={12} aria-hidden="true" /></span> : null,
  ].filter(Boolean);
  return <li className={`dk-todo-row${selected ? " on" : ""}${todo.done ? " dk-done" : ""}`} data-todo={todo.todo_id} draggable={!todo.done} onDragStart={onDrag} onKeyDown={onKey} tabIndex={-1}>
    {!todo.done && <GripVertical size={14} className="dk-todo-grip" aria-hidden="true" />}
    <button type="button" className="dk-todo-check" onClick={onToggle} aria-label={todo.done ? t("Mark {title} not done", { title: todo.title }) : t("Mark {title} done", { title: todo.title })}>
      {todo.done ? <CheckCircle2 size={18} /> : <Circle size={18} />}
    </button>
    <button type="button" className="dk-todo-open" onClick={onOpen} aria-label={t("Open {title}", { title: todo.title })} aria-pressed={selected}>
      <span className="dk-todo-title">{todo.title}</span>
      {meta.length > 0 && <small className="dk-todo-meta">{meta}</small>}
    </button>
  </li>;
}

/** A to-do an app gave the person or their group: ticked here, read back by the app; its title opens the app. */
function AppRow({ todo, today, onToggle }: { todo: AppTodo; today: string; onToggle: () => void }) {
  const due = dueText(todo.due, today);
  const label = todo.done ? t("Mark {title} not done", { title: todo.title }) : t("Mark {title} done", { title: todo.title });
  return <li className={`dk-todo-row${todo.done ? " dk-done" : ""}`} data-app-todo={`${todo.app}:${todo.key}`}>
    <button type="button" className="dk-todo-check" onClick={onToggle} aria-label={label}>{todo.done ? <CheckCircle2 size={18} /> : <Circle size={18} />}</button>
    <span className="dk-todo-open">
      {todo.url ? <a className="dk-todo-title" href={todo.url} onClick={(event) => { if (isLocalHref(todo.url!)) { event.preventDefault(); navigate(todo.url!); } }}>{todo.title}</a> : <span className="dk-todo-title">{todo.title}</span>}
      <small className="dk-todo-meta">
        <span><AppWindow size={12} aria-hidden="true" /> {todo.app_name} · {todo.kind_title}</span>
        {due && <span className={due.late && !todo.done ? "dk-todo-late" : undefined}><CalendarDays size={12} aria-hidden="true" /> {due.text}</span>}
        {todo.group_name && <span><Users size={12} aria-hidden="true" /> {todo.group_name}</span>}
        {todo.detail && <span>{todo.detail}</span>}
      </small>
    </span>
  </li>;
}

function Detail({ todo, data, labels, onChange, onClose }: { todo: Todo; data: TodoView; labels: Map<string, string>; onChange: () => void; onClose: () => void }) {
  const [title, setTitle] = useState(todo.title);
  const [notes, setNotes] = useState(todo.notes);
  const [step, setStep] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { setTitle(todo.title); setNotes(todo.notes); setError(""); }, [todo.todo_id, todo.title, todo.notes]);
  async function save(change: Parameters<typeof deskApi.changeTodo>[1]) {
    try { await deskApi.changeTodo(todo.todo_id, change); setError(""); onChange(); } catch (err) { setError(errorText(err)); }
  }
  const steps = (next: TodoStep[]) => void save({ steps: next });
  async function asAction() {
    try {
      const made = await deskApi.todoToAction(todo.todo_id, { group_id: todo.group_id });
      if (isLocalHref(made.href)) navigate(made.href);
    } catch (err) { setError(errorText(err)); }
  }
  async function remove() {
    if (!(await confirmAction(t("Delete the to-do {title}?", { title: todo.title }), { confirm: t("Delete"), danger: true }))) return;
    try { await deskApi.deleteTodo(todo.todo_id); onClose(); onChange(); } catch (err) { setError(errorText(err)); }
  }
  const myDay = todo.my_day === data.day;
  const days = new Set(todo.days);
  return <aside className="panel dk-todo-detail" aria-label={t("To-do")}>
    <header>
      <button type="button" className="dk-todo-check" onClick={() => void save({ done: !todo.done })} aria-label={todo.done ? t("Mark {title} not done", { title: todo.title }) : t("Mark {title} done", { title: todo.title })}>
        {todo.done ? <CheckCircle2 size={20} /> : <Circle size={20} />}
      </button>
      <input id="dk-todo-title" className="dk-todo-title-input" value={title} maxLength={200} aria-label={t("Title")}
        onChange={(event) => setTitle(event.target.value)} onBlur={() => { if (title.trim() && title.trim() !== todo.title) void save({ title: title.trim() }); }}
        onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />
      <button type="button" className="pcs-icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button>
    </header>
    <section className="dk-todo-steps" aria-label={t("Steps")}>
      <ul>{todo.steps.map((item, index) => <li key={index}>
        <label><input type="checkbox" checked={item.done} onChange={() => steps(todo.steps.map((entry, at) => (at === index ? { ...entry, done: !entry.done } : entry)))} /><span>{item.text}</span></label>
        <button type="button" className="pcs-icon-button dk-row-tools" onClick={() => steps(todo.steps.filter((_, at) => at !== index))} aria-label={t("Remove {title}", { title: item.text })}><X size={13} /></button>
      </li>)}</ul>
      <form className="dk-add" onSubmit={(event) => { event.preventDefault(); if (step.trim()) { steps([...todo.steps, { text: step.trim(), done: false }]); setStep(""); } }}>
        <input id="dk-todo-step" value={step} maxLength={200} onChange={(event) => setStep(event.target.value)} placeholder={t("Add a step")} aria-label={t("Add a step")} />
        <button type="submit" className="pcs-icon-button" aria-label={t("Add the step")}><Plus size={15} /></button>
      </form>
    </section>
    <button type="button" className={`button button-secondary dk-todo-myday${myDay ? " on" : ""}`} aria-pressed={myDay} onClick={() => void save({ my_day: !myDay })}>
      <Sun size={15} /> {myDay ? t("In My day") : t("Add to My day")}
    </button>
    <label>{t("Date")}<span className="dk-todo-inline">
      <input id="dk-todo-due" type="date" value={todo.due ?? ""} onChange={(event) => void save({ due: event.target.value || null })} />
      {todo.due && <button type="button" className="pcs-icon-button" onClick={() => void save({ due: null })} aria-label={t("Take the date away")}><X size={14} /></button>}
    </span></label>
    <label>{t("Repeat")}<select id="dk-todo-repeat" value={todo.repeat} onChange={(event) => {
      const repeat = event.target.value as TodoRepeat;
      void save(repeat === "days" ? { repeat, days: todo.days.length ? todo.days : [new Date(`${todo.due ?? data.day}T12:00:00`).getDay() === 0 ? 6 : new Date(`${todo.due ?? data.day}T12:00:00`).getDay() - 1] } : { repeat });
    }}>
      {data.repeats.map((option) => <option key={option.id} value={option.id}>{labels.get(option.id) ?? option.label}</option>)}
    </select></label>
    {todo.repeat === "days" && <div className="dk-weekdays" role="group" aria-label={t("Days")}>
      {WEEKDAYS.map((name, day) => <button key={name} type="button" className={`dk-chip${days.has(day) ? " on" : ""}`} aria-pressed={days.has(day)}
        onClick={() => { const next = new Set(days); if (next.has(day)) next.delete(day); else next.add(day); if (next.size) void save({ days: [...next].sort() }); }}>{name}</button>)}
    </div>}
    <label>{t("List")}<select id="dk-todo-list" value={todo.list_id ?? ""} onChange={(event) => void save({ list_id: event.target.value ? Number(event.target.value) : null })}>
      <option value="">{t("Tasks (no list)")}</option>
      {data.lists.map((list) => <option key={list.list_id} value={list.list_id}>{list.group_name ? `${list.name} · ${list.group_name}` : list.name}</option>)}
    </select></label>
    <label>{t("Notes")}<textarea id="dk-todo-notes" rows={4} maxLength={2000} value={notes} onChange={(event) => setNotes(event.target.value)} onBlur={() => { if (notes !== todo.notes) void save({ notes }); }} /></label>
    {error && <p className="form-error small">{error}</p>}
    <footer>
      {todo.action_id
        ? <a className="button button-secondary" href={`/actions/${todo.action_id}`} onClick={(event) => { event.preventDefault(); navigate(`/actions/${todo.action_id}`); }}><ArrowRightCircle size={15} /> {t("Open the action")}</a>
        : <button type="button" className="button button-secondary" onClick={() => void asAction()} title={t("When it needs someone else: an action can be handed to a person or a group and followed.")}><ArrowRightCircle size={15} /> {t("Turn into an action")}</button>}
      <button type="button" className="button button-secondary danger" onClick={() => void remove()}><Trash2 size={14} /> {t("Delete")}</button>
    </footer>
  </aside>;
}

function NewList({ groups, onDone }: { groups: TodoView["groups"]; onDone: (list: TodoList) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [group, setGroup] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try { const list = await deskApi.createList(name.trim(), group || null); setName(""); setOpen(false); setError(""); onDone(list); } catch (err) { setError(errorText(err)); }
  }
  if (!open) return <button type="button" className="dk-todo-nav-item dk-todo-newlist" onClick={() => setOpen(true)}><ListPlus size={15} /> {t("New list")}</button>;
  return <form className="dk-todo-newlist-form" onSubmit={(event) => void submit(event)}>
    <input id="dk-todo-list-name" value={name} maxLength={200} autoFocus onChange={(event) => setName(event.target.value)} placeholder={t("List name")} aria-label={t("List name")} />
    {groups.length > 0 && <select value={group} onChange={(event) => setGroup(event.target.value)} aria-label={t("For")}>
      <option value="">{t("Only me")}</option>
      {groups.map((item) => <option key={item.group_id} value={item.group_id}>{t("Shared with {name}", { name: item.name })}</option>)}
    </select>}
    <span className="dk-todo-inline">
      <button type="submit" className="button button-primary button-small">{t("Add")}</button>
      <button type="button" className="button button-secondary button-small" onClick={() => setOpen(false)}>{t("Cancel")}</button>
    </span>
    {error && <p className="form-error small">{error}</p>}
  </form>;
}

function ListTools({ list, onChange, onGone }: { list: TodoList; onChange: () => void; onGone: () => void }) {
  if (!list.editable) return list.group_name ? <small className="muted">{t("Shared with {name}", { name: list.group_name })}</small> : null;
  async function rename() {
    const name = await askText(t("List name"), { title: t("Rename the list"), value: list.name, confirm: t("Rename") });
    if (name && name.trim() && name.trim() !== list.name) { await deskApi.changeList(list.list_id, { name: name.trim() }).catch(() => undefined); onChange(); }
  }
  async function remove() {
    if (!(await confirmAction(t("Delete the list {name} and its to-dos?", { name: list.name }), { confirm: t("Delete"), danger: true }))) return;
    await deskApi.deleteList(list.list_id).catch(() => undefined);
    onGone();
  }
  return <span className="dk-todo-list-tools">
    {list.group_name && <small className="muted">{t("Shared with {name}", { name: list.group_name })}</small>}
    <span className="dk-todo-colors" role="group" aria-label={t("Colour")}>
      {COLORS.map((color) => <button key={color} type="button" className={color === list.color ? "on" : undefined} style={{ background: color }} aria-label={t("Colour {color}", { color })} aria-pressed={color === list.color}
        onClick={() => { void deskApi.changeList(list.list_id, { color }).then(onChange); }} />)}
    </span>
    <button type="button" className="button button-secondary button-small" onClick={() => void rename()}>{t("Rename")}</button>
    <button type="button" className="pcs-icon-button" onClick={() => void remove()} aria-label={t("Delete the list {name}", { name: list.name })}><Trash2 size={14} /></button>
  </span>;
}

const EXAMPLES = [t("Read the shift handover"), t("Review my late actions"), t("Walk the unit and check the field instruments"), t("Prepare the weekly meeting")];

export function TodoPage() {
  const first = useMemo(() => placeOf(window.location.search), []);
  const [place, setPlace] = useState<Place>({ view: first.view, list: first.list });
  const [selected, setSelected] = useState<number | null>(first.item);
  const [data, setData] = useState<TodoView | null>(null);
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [dragging, setDragging] = useState<number | null>(null);
  const load = useCallback(() => {
    deskApi.todos(place.view, place.list ?? undefined).then((value) => { setData(value); setError(""); }).catch((err) => setError(errorText(err)));
  }, [place]);
  useEffect(load, [load]);
  useEffect(() => {
    const params = new URLSearchParams();
    if (place.list) params.set("list", String(place.list));
    else if (place.view !== "today") params.set("view", place.view);
    if (selected) params.set("item", String(selected));
    const search = params.toString();
    window.history.replaceState(window.history.state, "", `/todo${search ? `?${search}` : ""}`);
  }, [place, selected]);
  const labels = useMemo(() => new Map((data?.repeats ?? []).map((item) => [item.id, item.label])), [data]);
  useAssistantPage({
    place: t("Desk › To-do"), page: "processcraft:todo",
    facts: { day: data?.day ?? "", ...(data?.counts ?? {}) },
    view: { view: place.view, list: data?.lists.find((item) => item.list_id === place.list)?.name ?? "", items: (data?.items ?? []).slice(0, 30).map((item) => `${item.title.slice(0, 80)}${item.due ? ` (due ${item.due})` : ""}${item.done ? " (done)" : ""}`) },
  });
  const go = (next: Place) => { setPlace(next); setSelected(null); };
  async function add(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || !data) return;
    try {
      await deskApi.createTodo({ title: text.trim(), list_id: place.list, my_day: place.view === "today", due: place.view === "planned" ? data.day : null });
      setText("");
      load();
    } catch (err) { setError(errorText(err)); }
  }
  async function toggleApp(todo: AppTodo) {
    try { await deskApi.completeAppTodo(todo, !todo.done); load(); } catch (err) { setError(errorText(err)); }
  }
  async function toggle(todo: Todo) {
    try { await deskApi.changeTodo(todo.todo_id, { done: !todo.done }); load(); } catch (err) { setError(errorText(err)); }
  }
  const open = (data?.items ?? []).filter((item) => !item.done);
  const done = (data?.items ?? []).filter((item) => item.done);
  async function move(id: number, index: number) {
    const changes = reorder(open, id, index);
    try { await Promise.all(changes.map((change) => deskApi.changeTodo(change.todo_id, { position: change.position }))); } catch (err) { setError(errorText(err)); }
    load();
  }
  function drop(event: DragEvent<HTMLUListElement>) {
    event.preventDefault();
    const id = dragging ?? Number(event.dataTransfer.getData("text/plain"));
    setDragging(null);
    const rows = [...event.currentTarget.querySelectorAll<HTMLLIElement>("li[data-todo]")];
    const index = rows.filter((row) => row.getBoundingClientRect().top + row.offsetHeight / 2 < event.clientY && Number(row.dataset.todo) !== id).length;
    if (id) void move(id, index);
  }
  function key(todo: Todo, index: number, event: KeyboardEvent<HTMLLIElement>) {
    if (!event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    event.preventDefault();
    void move(todo.todo_id, event.key === "ArrowUp" ? index - 1 : index + 1);
  }
  const list = data?.lists.find((item) => item.list_id === place.list) ?? null;
  const heading = place.view === "list" ? list?.name ?? t("List") : { today: t("My day"), planned: t("Planned"), all: t("All"), done: t("Done"), apps: t("From apps") }[place.view];
  const today = data ? new Date(`${data.day}T12:00:00`).toLocaleDateString(language, { weekday: "long", day: "numeric", month: "long" }) : "";
  const current = data?.items.find((item) => item.todo_id === selected) ?? null;
  const views: Array<{ view: TodoViewName; label: string; icon: ReactNode; count?: number }> = [
    { view: "today", label: t("My day"), icon: <Sun size={15} />, count: data?.counts.today },
    { view: "planned", label: t("Planned"), icon: <CalendarDays size={15} />, count: data?.counts.planned },
    { view: "all", label: t("All"), icon: <Inbox size={15} />, count: data?.counts.all },
    { view: "done", label: t("Done"), icon: <Check size={15} /> },
  ];
  // What the apps asked of the person ([[contributes.todo]]): a view of its own once there is any.
  if (data?.counts.apps || place.view === "apps") views.push({ view: "apps", label: t("From apps"), icon: <AppWindow size={15} />, count: data?.counts.apps });
  const fromApps = data?.app_todos ?? [];
  const appRow = (todo: AppTodo) => <AppRow key={`${todo.app}:${todo.key}`} todo={todo} today={data!.day} onToggle={() => void toggleApp(todo)} />;
  const own = (data?.lists ?? []).filter((item) => !item.group_id);
  const shared = (data?.lists ?? []).filter((item) => item.group_id);
  const listButton = (item: TodoList) => <button key={item.list_id} type="button" className={`dk-todo-nav-item${place.list === item.list_id ? " on" : ""}`} aria-current={place.list === item.list_id ? "page" : undefined} onClick={() => go({ view: "list", list: item.list_id })}>
    <i className="dk-todo-dot" style={{ background: item.color }} aria-hidden="true" /><span>{item.name}</span>{item.group_id && <Users size={12} className="muted" aria-label={t("Shared")} />}{item.open ? <small>{item.open}</small> : null}
  </button>;
  // An empty to-do (nothing anywhere yet): a few examples, each added with a click (round 8).
  const fresh = data !== null && !data.counts.all && !done.length && place.view !== "done" && place.view !== "apps";
  async function example(title: string) {
    try { await deskApi.createTodo({ title, list_id: place.list, my_day: place.view === "today", due: place.view === "planned" ? data!.day : null }); load(); } catch (err) { setError(errorText(err)); }
  }
  const row = (todo: Todo, index: number) => <Row key={todo.todo_id} todo={todo} data={data!} labels={labels} selected={todo.todo_id === selected}
    onOpen={() => setSelected(todo.todo_id === selected ? null : todo.todo_id)} onToggle={() => void toggle(todo)}
    onDrag={(event) => { setDragging(todo.todo_id); event.dataTransfer.setData("text/plain", String(todo.todo_id)); event.dataTransfer.effectAllowed = "move"; }}
    onKey={(event) => key(todo, index, event)} />;
  return <>
    <PageHeading eyebrow={t("Desk")} title={t("To-do")} description={t("What you have to do: My day, with a date and a repeat, in your lists and your groups' shared lists. Turn a to-do into an action when it needs someone else.")} />
    {error && <div className="form-error">{error}</div>}
    <div className={`dk-todo${current ? " with-detail" : ""}`}>
      <nav className="panel dk-todo-nav" aria-label={t("To-do lists")}>
        {views.map((item) => <button key={item.view} type="button" className={`dk-todo-nav-item${place.view === item.view ? " on" : ""}`} aria-current={place.view === item.view ? "page" : undefined} onClick={() => go({ view: item.view, list: null })}>
          {item.icon}<span>{item.label}</span>{item.count ? <small>{item.count}</small> : null}
        </button>)}
        <hr />
        {/* The views above are fixed (they gather to-dos from every list); the lists below are the person's own and their groups', the only ones renamed or deleted (round 8). */}
        <h2 className="dk-todo-nav-label">{t("My lists")}</h2>
        {own.map(listButton)}
        {data && !own.length && <p className="dk-todo-nav-hint">{t("No lists yet.")}</p>}
        {shared.length > 0 && <h2 className="dk-todo-nav-label">{t("Shared with my groups")}</h2>}
        {shared.map(listButton)}
        {data && <NewList groups={data.groups} onDone={(made) => { go({ view: "list", list: made.list_id }); }} />}
      </nav>
      <section className="panel dk-todo-main" aria-label={heading}>
        <header className="dk-todo-head">
          <div><h2>{heading}</h2>{place.view === "today" && <p className="muted small">{today}</p>}</div>
          {list && <ListTools list={list} onChange={load} onGone={() => go({ view: "today", list: null })} />}
        </header>
        {place.view !== "done" && place.view !== "apps" && <form className="dk-todo-add" onSubmit={(event) => void add(event)}>
          <Plus size={16} aria-hidden="true" />
          <input id="dk-todo-new" value={text} maxLength={200} onChange={(event) => setText(event.target.value)} placeholder={t("Add a to-do")} aria-label={t("Add a to-do")} disabled={!data} />
          {text.trim() && <button type="submit" className="button button-primary button-small">{t("Add")}</button>}
        </form>}
        {!data && !error && <p className="muted">{t("Loading…")}</p>}
        {data && <>
          <ul className="dk-todo-items" onDragOver={(event) => event.preventDefault()} onDrop={drop} aria-label={t("Open to-dos")}>{open.map(row)}</ul>
          {fresh && <div className="dk-todo-examples">
            <p className="muted">{t("Some to start with:")}</p>
            {EXAMPLES.map((title) => <button key={title} type="button" className="dk-chip" onClick={() => void example(title)}><Plus size={13} aria-hidden="true" /> {title}</button>)}
          </div>}
          {place.view === "apps" && <>
            <ul className="dk-todo-items" aria-label={t("From apps")}>{fromApps.filter((todo) => !todo.done).map(appRow)}</ul>
            {!fromApps.some((todo) => !todo.done) && <p className="muted dk-todo-empty">{t("Nothing from your apps.")}</p>}
            {fromApps.some((todo) => todo.done) && <details className="dk-todo-done">
              <summary>{t("Done ({count})", { count: fromApps.filter((todo) => todo.done).length })}</summary>
              <ul className="dk-todo-items">{fromApps.filter((todo) => todo.done).map(appRow)}</ul>
            </details>}
          </>}
          {data && !open.length && !fresh && place.view !== "done" && place.view !== "apps" && <p className="muted dk-todo-empty">{place.view === "today" ? t("Nothing for today yet. Add a to-do, or add one from your lists to My day.") : t("Nothing here yet.")}</p>}
          {place.view === "today" && fromApps.length > 0 && <section className="dk-todo-aside">
            <h3>{t("From apps")}</h3>
            <ul className="dk-todo-items">{fromApps.map(appRow)}</ul>
          </section>}
          {place.view === "today" && (data.actions?.length ?? 0) > 0 && <section className="dk-todo-aside">
            <h3>{t("Actions due")}</h3>
            <ul>{data.actions!.map((action) => <li key={action.action_id}><a href={action.href} onClick={(event) => { event.preventDefault(); navigate(action.href); }}>{action.title}</a>{action.late && <small className="dk-todo-late">{t("Late")}</small>}</li>)}</ul>
          </section>}
          {place.view === "today" && (data.events?.length ?? 0) > 0 && <section className="dk-todo-aside">
            <h3>{t("On the calendar")}</h3>
            <ul>{data.events!.map((event) => <li key={event.id}><time>{event.all_day ? t("All day") : new Date(event.start).toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit", timeZone: displayTimeZone() })}</time><a href="/calendar" onClick={(click) => { click.preventDefault(); navigate(`/calendar?date=${data.day}`); }}>{event.title}</a></li>)}</ul>
          </section>}
          {done.length > 0 && <details className="dk-todo-done" open={place.view === "done"}>
            <summary>{place.view === "done" ? t("Done") : t("Done ({count})", { count: done.length })}</summary>
            <ul className="dk-todo-items">{done.map(row)}</ul>
          </details>}
        </>}
      </section>
      {current && data && <Detail todo={current} data={data} labels={labels} onChange={load} onClose={() => setSelected(null)} />}
    </div>
  </>;
}
