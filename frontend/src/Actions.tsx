/** Actions: follow-up tasks about assets, signals and runs (docs/collaboration.md). A Kanban
 * board by status with how long each card has been there (or a list), and a full page per
 * action (a board, and a page rather than a side panel). An action goes to a
 * person, a group or both, and each person sees theirs, their groups' and those below a group
 * they lead, with Jira's quick filters. */
import { useCallback, useEffect, useState, type DragEvent, type FormEvent } from "react";
import { AssistantTitleButton, DataTable, Heading, useAssistantPage } from "@plantcraft/ui";
import { AlertTriangle, ArrowLeft, AtSign, CalendarClock, CheckSquare, ClipboardCheck, Clock, Columns3, Hash, List, ListChecks, LoaderCircle, Lock, MessageSquare, Pencil, Plus, Rows2, Rows3, Search, SendHorizontal, Trash2, UserRound, Users, X } from "lucide-react";
import { boardColumns, hoursText, timeText, type BoardColumn } from "./actionsBoard";
import { Avatar, dayText, errorText, fullWhen, Go, MentionText, optionFromRef, PersonLink, plainMentions, ReferencePicker, RefChip, resolveOption, shortWhen } from "./collab";
import { collabApi, type Action, type ActionDraft, type ActionItem, type ActionList, type ActionStatus, type ActionView, type Id, type RefOption } from "./collabApi";
import { t } from "./i18n";
import { navigate } from "./nav";
import { READ_ONLY, useAccess, useCanEdit, useIsAdmin, useUsername } from "./session";
import { Modal } from "./Modal";
import { RequestTargets } from "./OperationsRequests";

export const DEFAULT_OPEN_STATUSES = ["open", "in_progress", "blocked"];

type Prefill = { title: string; refs: string[] };

function readPrefill(): Prefill | null {
  const params = new URLSearchParams(window.location.search);
  if (!params.get("new")) return null;
  return { title: params.get("title") ?? "", refs: params.getAll("ref").filter(Boolean) };
}

function StatusBadge({ action }: { action: Pick<Action, "status" | "status_label"> }) {
  return <span className={`act-status act-status-${action.status}`}>{action.status_label}</span>;
}

function Due({ action }: { action: Action }) {
  if (!action.due_at) return <span className="muted">—</span>;
  return <span className={action.overdue ? "due-overdue" : "due"}><CalendarClock size={13} />{dayText(action.due_at)}</span>;
}

type View = "board" | "list";
type Density = "compact" | "detailed";
const VIEW_KEY = "processcraft.actions.view";
const DENSITY_KEY = "processcraft.actions.density";
const SCOPE_KEY = "processcraft.actions.scope";
const SCOPES: ActionView[] = ["visible", "mine", "groups", "created"];
function savedView(): View {
  try { return window.localStorage.getItem(VIEW_KEY) === "list" ? "list" : "board"; } catch { return "board"; }
}
// Compact cards by default (round 8): twice as many on screen; the detailed card stays a click away.
function savedDensity(): Density {
  try { return window.localStorage.getItem(DENSITY_KEY) === "detailed" ? "detailed" : "compact"; } catch { return "compact"; }
}
function savedScope(): ActionView {
  // Desk's actions widget opens this page on its own filter (?view=mine).
  const asked = new URLSearchParams(window.location.search).get("view") as ActionView | null;
  if (asked && SCOPES.includes(asked)) return asked;
  try { const value = window.localStorage.getItem(SCOPE_KEY) as ActionView | null; return value && SCOPES.includes(value) ? value : "visible"; } catch { return "visible"; }
}

export function ActionsPage({ actionId }: { actionId: string | null }) {
  const canEdit = useCanEdit();
  const [data, setData] = useState<ActionList | null>(null);
  const [error, setError] = useState("");
  const [view, setViewState] = useState<View>(savedView);
  const [density, setDensityState] = useState<Density>(savedDensity);
  const [statuses, setStatuses] = useState<string[]>(DEFAULT_OPEN_STATUSES);
  const [showCancelled, setShowCancelled] = useState(false);
  const [scope, setScopeState] = useState<ActionView>(savedScope);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [prefill] = useState(readPrefill);
  const [form, setForm] = useState<{ action: Action | null; prefill: Prefill | null } | null>(null);
  const [notice, setNotice] = useState("");
  const setView = (value: View) => { setViewState(value); try { window.localStorage.setItem(VIEW_KEY, value); } catch { /* a private window */ } };
  const setDensity = (value: Density) => { setDensityState(value); try { window.localStorage.setItem(DENSITY_KEY, value); } catch { /* a private window */ } };
  const setScope = (value: ActionView) => { setScopeState(value); try { window.localStorage.setItem(SCOPE_KEY, value); } catch { /* a private window */ } };

  useEffect(() => { const timer = window.setTimeout(() => setSearch(q), 250); return () => window.clearTimeout(timer); }, [q]);
  // The board shows every status in its columns; the list filters by status.
  const load = useCallback(() => collabApi.actions({ status: view === "board" || actionId ? [] : statuses, view: actionId ? "visible" : scope, q: search }).then((value) => { setData(value); setError(""); }).catch((err) => setError(errorText(err))), [statuses, scope, search, view, actionId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    // /actions?new=1&ref=asset:FIC-101&title=... opens the create form filled in.
    if (!prefill) return;
    window.history.replaceState(window.history.state, "", window.location.pathname);
    if (canEdit) setForm({ action: null, prefill });
  }, [prefill, canEdit]);

  const toggleStatus = (id: string) => setStatuses((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const openSet = data?.open_statuses?.length ? data.open_statuses : DEFAULT_OPEN_STATUSES;
  const showingOpen = statuses.length === openSet.length && openSet.every((id) => statuses.includes(id));
  function saved(action: Action, created: boolean) {
    setForm(null);
    setNotice(created ? t("Action #{id} was created.", { id: action.action_id }) : t("Action #{id} was saved.", { id: action.action_id }));
    window.setTimeout(() => setNotice(""), 3000);
    void load();
    if (created) navigate(`/actions/${encodeURIComponent(String(action.action_id))}`);
  }
  async function move(action: Action, status: ActionStatus) {
    if (action.status === status) return;
    setData((current) => current && { ...current, items: current.items.map((item) => item.action_id === action.action_id ? { ...item, status, status_since: new Date().toISOString() } : item) });
    try { await collabApi.updateAction(action.action_id, { ...draftOf(action), status }); } catch (err) { setError(errorText(err)); }
    void load();
  }

  if (actionId) return <>
    {data && <ActionPage key={actionId} actionId={actionId} list={data} canEdit={canEdit} onEdit={(action) => setForm({ action, prefill: null })} onChanged={() => void load()} />}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading actions…")}</span></div>}
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {form && data && <ActionForm list={data} action={form.action} prefill={form.prefill} onClose={() => setForm(null)} onSaved={(action, created) => { saved(action, created); window.dispatchEvent(new Event("pc-action-saved")); }} />}
  </>;

  return <>
    <ActionsAssistant data={data} view={view} scope={scope} statuses={statuses} search={search} />
    <Heading title={t("Actions")} actions={canEdit ? <button className="button button-primary" onClick={() => setForm({ action: null, prefill: null })} disabled={!data}><Plus size={16} /> {t("New action")}</button> : <span className="muted">{READ_ONLY}</span>} />
    {notice && <div className="ac-notice">{notice}</div>}
    <div className="act-toolbar">
      <div className="act-filters act-view" role="group" aria-label={t("View")}>
        <button type="button" className={view === "board" ? "active" : ""} aria-pressed={view === "board"} onClick={() => setView("board")}><Columns3 size={14} /> {t("Board")}</button>
        <button type="button" className={view === "list" ? "active" : ""} aria-pressed={view === "list"} onClick={() => setView("list")}><List size={14} /> {t("List")}</button>
      </div>
      <label className="co-search act-search"><Search /><input value={q} onChange={(event) => setQ(event.target.value)} placeholder={t("Search actions")} aria-label={t("Search actions")} /></label>
      {view === "list" && <div className="act-filters" role="group" aria-label={t("Status")}>
        <button type="button" className={showingOpen ? "active" : ""} onClick={() => setStatuses(openSet)}>{t("Not done")}</button>
        {(data?.statuses ?? []).map((status) => <button type="button" key={status.id} className={statuses.includes(status.id) ? "active" : ""} aria-pressed={statuses.includes(status.id)} onClick={() => toggleStatus(status.id)}>{status.label}</button>)}
      </div>}
      {view === "board" && <div className="act-filters act-density" role="group" aria-label={t("Cards")}>
        <button type="button" className={density === "compact" ? "active" : ""} aria-pressed={density === "compact"} onClick={() => setDensity("compact")} title={t("Compact cards")}><Rows3 size={14} /> {t("Compact")}</button>
        <button type="button" className={density === "detailed" ? "active" : ""} aria-pressed={density === "detailed"} onClick={() => setDensity("detailed")} title={t("Detailed cards")}><Rows2 size={14} /> {t("Detailed")}</button>
      </div>}
      {view === "board" && <label className="act-mine"><input type="checkbox" checked={showCancelled} onChange={(event) => setShowCancelled(event.target.checked)} /> {t("Show archived")}</label>}
      <label className="act-scope"><span>{t("Show")}</span><select value={scope} onChange={(event) => setScope(event.target.value as ActionView)} aria-label={t("Which actions")}>
        {(data?.views ?? SCOPES.map((id) => ({ id, label: id }))).map((item) => <option key={item.id} value={item.id}>{item.id === "visible" && data?.everything ? t("All actions") : item.label}</option>)}
      </select></label>
    </div>
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {!data && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading actions…")}</span></div>}
    {data && view === "board" && <Board list={data} showCancelled={showCancelled} compact={density === "compact"} canEdit={canEdit} onMove={(action, status) => void move(action, status)} />}
    {data && view === "list" && <section className="panel act-panel" data-tour="actions">
      {data.items.length ? <DataTable rows={data.items} rowKey={(action) => String(action.action_id)} label={t("Actions")} className="act-table" onRowClick={(action) => navigate(actionPath(action.action_id))} initialSort={{ key: "updated", descending: true }}
        columns={[
          { key: "id", label: "#", className: "act-id", sort: (action) => Number(action.action_id) || String(action.action_id) },
          { key: "title", label: t("Action"), sort: (action) => action.title, render: (action) => <><a href={actionPath(action.action_id)} className="act-title" onClick={(event) => { if (!event.metaKey && !event.ctrlKey) event.preventDefault(); }}>{action.title}</a>{action.refs.length > 0 && <span className="act-refs" onClick={(event) => event.stopPropagation()}>{action.refs.slice(0, 3).map((ref) => <RefChip key={ref.ref} item={ref} label={ref.id} />)}{action.refs.length > 3 && <small>+{action.refs.length - 3}</small>}</span>}</> },
          { key: "status", label: t("Status"), sort: (action) => action.status_label, render: (action) => <StatusBadge action={action} /> },
          { key: "priority", label: t("Priority"), sort: (action) => PRIORITY_RANK[action.priority] ?? 9, filter: { options: data.priorities.map((item) => ({ value: item.id, label: item.label })), value: (action) => action.priority }, render: (action) => <span className={`priority-pill priority-${action.priority}`}>{action.priority_label}</span> },
          { key: "owner", label: t("Owner"), sort: (action) => action.owner_name, filter: { value: (action) => action.owner_name || t("Nobody") }, render: (action) => <span onClick={(event) => event.stopPropagation()}><PersonLink username={action.owner} name={action.owner_name} /></span> },
          { key: "group", label: t("Group"), sort: (action) => action.group_name ?? "", filter: { value: (action) => action.group_name || t("No group") }, render: (action) => action.group_id ? <span onClick={(event) => event.stopPropagation()}><Go to={`/groups/${encodeURIComponent(action.group_id)}`}>{action.group_name ?? action.group_id}</Go></span> : <span className="muted">—</span> },
          { key: "due", label: t("Due"), sort: (action) => action.due_at, render: (action) => <Due action={action} /> },
          { key: "updated", label: t("Updated"), sort: (action) => action.updated_at, render: (action) => <span title={fullWhen(action.updated_at)}>{shortWhen(action.updated_at)}</span> },
        ]} /> : <div className="empty-state"><ClipboardCheck /><strong>{t("No actions here")}</strong><p>{scope !== "visible" || search || !showingOpen ? t("Change the filters to see more.") : t("Nothing is waiting. Create an action when something needs following up.")}</p></div>}
    </section>}
    {form && data && <ActionForm list={data} action={form.action} prefill={form.prefill} onClose={() => setForm(null)} onSaved={saved} />}
  </>;
}

/** What the assistant gets on the board (docs/assistant.md, "Works"): the filters and the actions on
 * screen, by number, title and state; it reads the rest with list_actions. */
function ActionsAssistant({ data, view, scope, statuses, search }: { data: ActionList | null; view: View; scope: ActionView; statuses: string[]; search: string }) {
  const items = data?.items ?? [];
  useAssistantPage({
    place: t("Desk › Actions"),
    page: "processcraft:actions",
    facts: { shown: items.length, overdue: items.filter((item) => item.overdue).length, unowned: items.filter((item) => !item.owner && !item.group_id).length },
    view: { view, scope, statuses: view === "list" ? statuses : "all", search, rows: items.slice(0, 30).map((item) => `#${item.action_id} ${item.title.slice(0, 80)} (${item.status}, ${item.priority}${item.due_at ? `, due ${item.due_at}` : ""})`) },
  });
  return null;
}

const PRIORITY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const actionPath = (id: Id) => `/actions/${encodeURIComponent(String(id))}`;

/** The Kanban board: one column per status; editors drag a card to another column to move it. */
function Board({ list, showCancelled, compact, canEdit, onMove }: { list: ActionList; showCancelled: boolean; compact: boolean; canEdit: boolean; onMove: (action: Action, status: ActionStatus) => void }) {
  const [over, setOver] = useState<string | null>(null);
  const columns = boardColumns(list.items, list.statuses, showCancelled);
  const drop = (event: DragEvent, status: string) => {
    event.preventDefault();
    setOver(null);
    const id = event.dataTransfer.getData("text/x-action");
    const action = list.items.find((item) => String(item.action_id) === id);
    if (action) onMove(action, status as ActionStatus);
  };
  return <div className="act-board" data-tour="actions" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(240px, 1fr))` }}>
    {columns.map((column) => <section key={column.id} className={`act-column act-column-${column.id}${over === column.id ? " act-column-over" : ""}`} aria-label={column.label}
      onDragOver={canEdit ? (event) => { event.preventDefault(); setOver(column.id); } : undefined} onDragLeave={() => setOver((current) => current === column.id ? null : current)} onDrop={canEdit ? (event) => drop(event, column.id) : undefined}>
      <ColumnHeader column={column} />
      <ol>{column.items.map((action) => <li key={action.action_id}>
        {compact ? <CompactCard action={action} canEdit={canEdit} /> : <a href={actionPath(action.action_id)} className={`act-card priority-edge-${action.priority}`} draggable={canEdit} onDragStart={(event) => { event.dataTransfer.setData("text/x-action", String(action.action_id)); event.dataTransfer.effectAllowed = "move"; }} onClick={(event) => { if (event.metaKey || event.ctrlKey) return; event.preventDefault(); navigate(actionPath(action.action_id)); }}>
          <span className="act-card-top"><span className="act-id">#{action.action_id}</span><span className={`priority-pill priority-${action.priority}`}>{action.priority_label}</span></span>
          <strong>{action.title}</strong>
          {action.description && <span className="act-card-desc">{plainMentions(action.description)}</span>}
          {action.refs.length > 0 && <span className="act-card-refs">{action.refs.slice(0, 2).map((ref) => ref.title || ref.id).join(" · ")}{action.refs.length > 2 ? ` +${action.refs.length - 2}` : ""}</span>}
          <span className="act-card-meta">
            <span><UserRound size={12} /> {action.owner_name ?? action.owner ?? t("Nobody")}</span>
            {action.group_name && <span title={t("Group")}><Users size={12} /> {action.group_name}</span>}
            <span title={fullWhen(action.status_since ?? action.updated_at)}><Clock size={12} /> {timeText(action)}</span>
            {action.due_at && <span className={action.overdue ? "due-overdue" : ""}><CalendarClock size={12} /> {dayText(action.due_at)}</span>}
            {action.checklist && action.checklist.total > 0 && <span className={action.checklist.done === action.checklist.total ? "act-card-checklist act-card-checklist-done" : "act-card-checklist"} title={t("Checklist: {done} of {total} done", { done: action.checklist.done, total: action.checklist.total })}><CheckSquare size={12} /> {action.checklist.done}/{action.checklist.total}</span>}
          </span>
        </a>}
      </li>)}</ol>
      {!column.items.length && <p className="act-column-empty">{canEdit ? t("Drop a card here") : t("Nothing here")}</p>}
    </section>)}
  </div>;
}

/** A column's name with how many cards it holds (only the number; a late
 * action is marked on its own card). */
function ColumnHeader({ column }: { column: BoardColumn }) {
  return <header>
    <span className={`act-status act-status-${column.id}`}>{column.label}</span>
    <span className="act-counts">
      <span className="act-count pc-num" title={column.items.length === 1 ? t("1 action") : t("{count} actions", { count: column.items.length })} aria-label={column.items.length === 1 ? t("1 action") : t("{count} actions", { count: column.items.length })}>{column.items.length}</span>
    </span>
  </header>;
}

/** The board's card in two lines: the title, then number, owner, due date and checklist. The
 * priority is the coloured edge. On hover (or keyboard focus) the card opens in place to show the
 * rest: the description, what it is about, who has it and since when (no bare
 * text tooltip). */
function CompactCard({ action, canEdit }: { action: Action; canEdit: boolean }) {
  const owner = action.owner_name ?? action.owner ?? "";
  return <a href={actionPath(action.action_id)} className={`act-card act-card-compact priority-edge-${action.priority}`} draggable={canEdit}
    onDragStart={(event) => { event.dataTransfer.setData("text/x-action", String(action.action_id)); event.dataTransfer.effectAllowed = "move"; }}
    onClick={(event) => { if (event.metaKey || event.ctrlKey) return; event.preventDefault(); navigate(actionPath(action.action_id)); }}>
    <strong>{action.title}</strong>
    <span className="act-card-meta">
      <span className="act-id">#{action.action_id}</span>
      {action.due_at && <span className={action.overdue ? "due-overdue" : ""}><CalendarClock size={12} /> {dayText(action.due_at)}</span>}
      {action.checklist && action.checklist.total > 0 && <span className={action.checklist.done === action.checklist.total ? "act-card-checklist act-card-checklist-done" : "act-card-checklist"} title={t("Checklist: {done} of {total} done", { done: action.checklist.done, total: action.checklist.total })}><CheckSquare size={12} /> {action.checklist.done}/{action.checklist.total}</span>}
      {owner ? <span className="act-card-owner" title={owner}><Avatar name={owner} size="sm" /></span> : action.group_name ? <span className="act-card-owner" title={action.group_name}><Users size={12} /></span> : null}
    </span>
    <span className="act-card-more">
      <span className="act-card-more-inner">
        {action.description && <span className="act-card-desc">{plainMentions(action.description)}</span>}
        {action.refs.length > 0 && <span className="act-card-refs">{action.refs.slice(0, 3).map((ref) => ref.title || ref.id).join(" · ")}{action.refs.length > 3 ? ` +${action.refs.length - 3}` : ""}</span>}
        <span className="act-card-meta act-card-more-meta">
          <span className={`priority-pill priority-${action.priority}`}>{action.priority_label}</span>
          <span><UserRound size={12} /> {owner || t("Nobody")}</span>
          {action.group_name && <span><Users size={12} /> {action.group_name}</span>}
          <span><Clock size={12} /> {timeText(action)}</span>
        </span>
      </span>
    </span>
  </a>;
}

function draftOf(action: Action): ActionDraft {
  return { title: action.title, description: action.description, priority: action.priority, owner: action.owner, group_id: action.group_id ?? null, due_at: action.due_at ? action.due_at.slice(0, 10) : null, refs: action.refs.map((item) => item.ref) };
}

const HISTORY_ICON = { created: <Plus size={13} />, changed: <Pencil size={13} />, status: <ClipboardCheck size={13} />, comment: <MessageSquare size={13} />, checklist: <ListChecks size={13} />, hours: <Clock size={13} /> };

/** Puts a #reference into a text at the end, with a space before it when needed. */
export function withMention(text: string, ref: string): string {
  return `${text}${text && !/\s$/.test(text) ? " " : ""}#${ref} `;
}

/** One action on its own page: what, who, when, what it is about, its history and comments. */
function ActionPage({ actionId, list, canEdit, onEdit, onChanged }: { actionId: Id; list: ActionList; canEdit: boolean; onEdit: (action: Action) => void; onChanged: () => void }) {
  const [action, setAction] = useState<Action | null>(null);
  const [error, setError] = useState("");
  const [comment, setComment] = useState("");
  const [mentioning, setMentioning] = useState(false);
  const [busy, setBusy] = useState(false);
  const operate = Boolean(useAccess().can_operate);
  const reload = useCallback(() => collabApi.action(actionId).then(setAction).catch((err) => setError(errorText(err))), [actionId]);
  // The Operations role answers requests (status, edit) whatever its access level.
  const editable = canEdit || (operate && action?.kind === "request");
  useEffect(() => { void reload(); }, [reload]);
  useAssistantPage({
    subject: `action:${actionId}`, title: action?.title ?? t("Action #{id}", { id: actionId }), place: t("Actions › #{id}", { id: actionId }), page: "processcraft:action",
    facts: action ? { status: action.status, priority: action.priority, owner: action.owner ?? "", group: action.group_id ?? "", due: action.due_at ?? "", overdue: Boolean(action.overdue), checklist_open: (action.items ?? []).filter((item) => !item.done).length } : {},
  });
  // Saved in the edit form (on the list page's state): read it again.
  useEffect(() => { const again = () => void reload(); window.addEventListener("pc-action-saved", again); return () => window.removeEventListener("pc-action-saved", again); }, [reload]);
  async function move(status: ActionStatus) {
    if (!action || status === action.status) return;
    setBusy(true);
    try { setAction(await collabApi.updateAction(action.action_id, { ...draftOf(action), status })); setError(""); onChanged(); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!action || !comment.trim()) return;
    setBusy(true);
    try { setAction(await collabApi.comment(action.action_id, comment.trim())); setComment(""); setError(""); onChanged(); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  return <>
    {/* A request goes back to Operations › Requests, where it was asked or answered. */}
    <nav className="as-breadcrumb act-breadcrumb">{action?.kind === "request"
      ? <a href="/ops/requests" onClick={(event) => { event.preventDefault(); navigate("/ops/requests"); }}><ArrowLeft size={13} /> {t("Requests")}</a>
      : <a href="/actions" onClick={(event) => { event.preventDefault(); navigate("/actions"); }}><ArrowLeft size={13} /> {t("Actions")}</a>}</nav>
    <div className="page-heading">
      <div><span className="eyebrow"><ClipboardCheck size={14} /> {action?.kind === "request" ? t("Request #{id}", { id: actionId }) : t("Action #{id}", { id: actionId })}</span><div className="page-heading-title"><h1>{action?.title ?? ""}</h1><AssistantTitleButton /></div>
        {action && <p className="act-page-sub pc-heading-keep"><StatusBadge action={action} /> <span className="muted"><Clock size={13} /> {timeText(action)}</span></p>}</div>
      {action && <div className="heading-actions">
        {editable && <label className="act-move"><span>{t("Status")}</span><select value={action.status} disabled={busy} onChange={(event) => void move(event.target.value as ActionStatus)}>{list.statuses.map((status) => <option key={status.id} value={status.id}>{status.label}</option>)}</select></label>}
        {editable && <button type="button" className="button button-secondary" onClick={() => onEdit(action)}><Pencil size={15} /> {t("Edit")}</button>}
      </div>}
    </div>
    {!action && !error && <div className="module-state"><LoaderCircle className="spin" /></div>}
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {action && <div className="act-page">
      <section className="panel act-page-main">
        <h2 className="section-title">{t("Description")}</h2>
        {action.description ? <MentionText className="action-description act-description" text={action.description} refs={action.mentions ?? []} /> : <p className="muted">{t("No description.")}</p>}
        <Checklist action={action} list={list} canEdit={canEdit} onChanged={(next) => { setAction(next); onChanged(); }} />
        {(action.kind === "request" || (action.hours ?? []).length > 0) && <TimeLog action={action} onChanged={(next) => { setAction(next); onChanged(); }} />}
        <h2 className="section-title">{t("About")}</h2>
        {action.refs.length ? <div className="act-ref-list">{action.refs.map((ref) => <RefChip key={ref.ref} item={ref} label={`${ref.kind_label}: ${ref.title || ref.id}`} />)}</div> : <p className="muted">{t("No references.")}</p>}
        <h2 className="section-title">{t("History and comments")}</h2>
        <ol className="act-history">{(action.history ?? []).map((item, index) => <li key={index} className={`act-history-${item.kind}`}>
          <span className="act-history-icon">{HISTORY_ICON[item.kind] ?? <UserRound size={13} />}</span>
          <div>{item.kind === "comment" ? <MentionText text={item.text} refs={action.mentions ?? []} /> : <p>{item.text || (item.kind === "created" ? t("Created the action") : "")}</p>}<small><PersonLink username={item.actor} name={item.actor_name} /> · <time dateTime={item.created_at} title={fullWhen(item.created_at)}>{shortWhen(item.created_at)}</time></small></div>
        </li>)}</ol>
        <form className="comment-form" onSubmit={send}><input value={comment} onChange={(event) => setComment(event.target.value)} placeholder={t("Write a comment; # to mention an asset, a person or a run")} aria-label={t("Comment")} maxLength={4000} /><button type="button" className="act-mention" onClick={() => setMentioning(!mentioning)} aria-label={t("Mention")} title={t("Mention an asset, a person or a run")}><AtSign size={15} /></button><button disabled={busy || !comment.trim()} aria-label={t("Comment")}><SendHorizontal size={15} /></button></form>
        {mentioning && <ReferencePicker className="msg-picker-inline" onClose={() => setMentioning(false)} onPick={(option) => { setComment((current) => withMention(current, option.ref)); setMentioning(false); }} />}
      </section>
      <aside className="panel act-page-facts">
        <div className="fact-grid act-facts">
          <div><span>{t("Status")}</span><strong><StatusBadge action={action} /></strong></div>
          {action.kind === "request" && <div><span>{t("Category")}</span><strong>{action.category_label ?? "—"}</strong></div>}
          {action.kind === "request" && <div><span>{t("First answer")}</span><strong>{action.first_response_at ? fullWhen(action.first_response_at) : <span className="muted">{t("Waiting")}</span>}</strong></div>}
          {action.kind === "request" && <RequestTargets request={action} />}
          {(action.hours_logged ?? 0) > 0 && <div><span>{t("Time logged")}</span><strong>{hoursText(action.hours_logged ?? 0)}</strong></div>}
          <div><span>{t("Priority")}</span><strong><span className={`priority-pill priority-${action.priority}`}>{action.priority_label}</span></strong></div>
          <div><span>{t("Owner")}</span><strong><PersonLink username={action.owner} name={action.owner_name} /></strong></div>
          <div><span>{t("Group")}</span><strong>{action.group_id ? <Go to={`/groups/${encodeURIComponent(action.group_id)}`}>{action.group_name ?? action.group_id}</Go> : "—"}</strong></div>
          <div><span>{t("Due")}</span><strong>{action.due_at ? <span className={action.overdue ? "due-overdue" : ""}>{dayText(action.due_at)}{action.overdue ? ` · ${t("overdue")}` : ""}</span> : "—"}</strong></div>
          <div><span>{t("Created by")}</span><strong><PersonLink username={action.created_by} name={action.created_by_name} /></strong></div>
          <div><span>{t("Created")}</span><strong>{fullWhen(action.created_at)}</strong></div>
          {action.status_since && action.status_since !== action.created_at && <div><span>{t("In this status since")}</span><strong>{fullWhen(action.status_since)}</strong></div>}
          {action.completed_at && <div><span>{t("Finished")}</span><strong>{fullWhen(action.completed_at)}</strong></div>}
        </div>
      </aside>
    </div>}
  </>;
}

/** Time spent on a request (or an action): who, which day, how long, a note, billable or not.
 * Whoever sees the action logs their own time; who logged it, or an administrator, removes it. */
function TimeLog({ action, onChanged }: { action: Action; onChanged: (action: Action) => void }) {
  const me = useUsername();
  const admin = useIsAdmin();
  const entries = action.hours ?? [];
  const [hours, setHours] = useState("");
  const [day, setDay] = useState("");
  const [note, setNote] = useState("");
  const [billable, setBillable] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function add(event: FormEvent) {
    event.preventDefault();
    const value = Number(hours.replace(",", "."));
    if (!(value > 0)) return;
    setBusy(true);
    try { onChanged(await collabApi.logHours(action.action_id, { hours: value, day: day || null, note: note.trim(), billable })); setHours(""); setNote(""); setError(""); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  async function remove(entryId: number) {
    setBusy(true);
    try { onChanged(await collabApi.deleteHours(action.action_id, entryId)); setError(""); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  return <section className="act-time" aria-labelledby="act-time-title">
    <h2 className="section-title" id="act-time-title">{t("Time")} {entries.length > 0 && <small className="muted">{hoursText(action.hours_logged ?? 0)}</small>}</h2>
    {entries.length > 0 && <ul className="act-time-list">{entries.map((entry) => <li key={entry.entry_id}>
      <strong>{hoursText(entry.hours)}</strong>
      <span>{dayText(entry.day)}</span>
      <PersonLink username={entry.username} name={entry.display_name} />
      <span className="act-time-note">{entry.note}{!entry.billable && <small className="muted"> · {t("not billable")}</small>}</span>
      {entry.locked ? <span className="act-time-locked" title={t("Its month's hours are approved")} aria-label={t("Its month's hours are approved")}><Lock size={14} /></span> : (entry.username === me || admin) && <button type="button" className="icon-button" disabled={busy} onClick={() => void remove(entry.entry_id)} aria-label={t("Remove this time")} title={t("Remove this time")}><Trash2 size={14} /></button>}
    </li>)}</ul>}
    <form className="act-time-form" onSubmit={add} aria-label={t("Log time")}>
      <input inputMode="decimal" value={hours} onChange={(event) => setHours(event.target.value)} placeholder={t("Hours")} aria-label={t("Hours")} />
      <input type="date" value={day} onChange={(event) => setDay(event.target.value)} aria-label={t("Day (today when empty)")} title={t("Day (today when empty)")} />
      <input value={note} maxLength={300} onChange={(event) => setNote(event.target.value)} placeholder={t("What was done")} aria-label={t("What was done")} />
      <label className="act-mine"><input type="checkbox" checked={billable} onChange={(event) => setBillable(event.target.checked)} /> {t("Billable")}</label>
      <button className="button button-secondary" disabled={busy || !(Number(hours.replace(",", ".")) > 0)}><Clock size={14} /> {t("Log time")}</button>
    </form>
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
  </section>;
}

/** The action's checklist: tick items, add one with its owner and due date, remove one. */
function Checklist({ action, list, canEdit, onChanged }: { action: Action; list: ActionList; canEdit: boolean; onChanged: (action: Action) => void }) {
  const items = action.items ?? [];
  const [text, setText] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run(work: () => Promise<Action>) {
    setBusy(true);
    try { onChanged(await work()); setError(""); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  async function add(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    await run(() => collabApi.addItem(action.action_id, { text: text.trim(), owner: owner || null, due_at: due || null }));
    setText(""); setOwner(""); setDue("");
  }
  const done = items.filter((item) => item.done).length;
  return <>
    <h2 className="section-title act-checklist-title"><span>{t("Checklist")}</span>{items.length > 0 && <small>{t("{done} of {total} done", { done, total: items.length })}</small>}</h2>
    {items.length > 0 && <div className="act-progress" role="progressbar" aria-label={t("Checklist")} aria-valuemin={0} aria-valuemax={items.length} aria-valuenow={done}><i style={{ width: `${(100 * done) / items.length}%` }} /></div>}
    {error && <div className="form-error"><AlertTriangle size={15} /> {error}</div>}
    {items.length > 0 ? <ul className="act-checklist">{items.map((item: ActionItem) => <li key={item.item_id} className={item.done ? "act-item-done" : ""}>
      <input type="checkbox" checked={item.done} disabled={!canEdit || busy} aria-label={item.text} onChange={(event) => void run(() => collabApi.changeItem(action.action_id, item.item_id, { done: event.target.checked }))} />
      <span className="act-item-text">{item.text}</span>
      <span className="act-item-meta">
        {canEdit ? <select aria-label={t("Responsible for {item}", { item: item.text })} value={item.owner ?? ""} disabled={busy} onChange={(event) => void run(() => collabApi.changeItem(action.action_id, item.item_id, { owner: event.target.value || null }))}><option value="">{t("Nobody")}</option>{list.people.map((person) => <option key={person.username} value={person.username}>{person.display_name}</option>)}</select>
          : item.owner ? <PersonLink username={item.owner} name={item.owner_name} /> : null}
        {canEdit ? <input type="date" aria-label={t("Due date of {item}", { item: item.text })} value={item.due_at ?? ""} disabled={busy} className={item.overdue ? "due-overdue" : ""} onChange={(event) => void run(() => collabApi.changeItem(action.action_id, item.item_id, { due_at: event.target.value || null }))} />
          : item.due_at ? <span className={item.overdue ? "due-overdue" : "due"}><CalendarClock size={13} />{dayText(item.due_at)}</span> : null}
        {item.done && item.done_by && <small title={fullWhen(item.done_at)}>{t("done by {name}", { name: item.done_by_name ?? item.done_by })}</small>}
        {canEdit && <button type="button" className="icon-button" disabled={busy} aria-label={t("Remove {item}", { item: item.text })} onClick={() => void run(() => collabApi.deleteItem(action.action_id, item.item_id))}><Trash2 size={14} /></button>}
      </span>
    </li>)}</ul> : <p className="muted">{canEdit ? t("No items yet: break the action into steps, each with who and by when.") : t("No checklist.")}</p>}
    {canEdit && <form className="act-item-add" onSubmit={add}>
      <input value={text} maxLength={300} onChange={(event) => setText(event.target.value)} placeholder={t("New item")} aria-label={t("New item")} />
      <select value={owner} onChange={(event) => setOwner(event.target.value)} aria-label={t("Responsible")}><option value="">{t("Responsible")}</option>{list.people.map((person) => <option key={person.username} value={person.username}>{person.display_name}</option>)}</select>
      <input type="date" value={due} onChange={(event) => setDue(event.target.value)} aria-label={t("Due date")} />
      <button className="button button-secondary" disabled={busy || !text.trim()}><Plus size={14} /> {t("Add")}</button>
    </form>}
  </>;
}

function ActionForm({ list, action, prefill, onClose, onSaved }: { list: ActionList; action: Action | null; prefill: Prefill | null; onClose: () => void; onSaved: (action: Action, created: boolean) => void }) {
  const [draft, setDraft] = useState<ActionDraft>(() => action ? draftOf(action) : { title: prefill?.title ?? "", description: "", priority: list.priorities.find((item) => item.id === "medium")?.id ?? list.priorities[0]?.id ?? "medium", owner: null, group_id: null, due_at: null, refs: prefill?.refs ?? [] });
  const [status, setStatus] = useState<ActionStatus>(action?.status ?? "open");
  const [options, setOptions] = useState<Record<string, RefOption>>(() => Object.fromEntries((action?.refs ?? []).map((ref) => [ref.ref, { ref: ref.ref, kind: ref.kind, kind_label: ref.kind_label, title: ref.title || ref.id, detail: "" }])));
  const [picking, setPicking] = useState(false);
  const [mentioning, setMentioning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (!action && prefill?.refs.length) prefill.refs.forEach((ref) => void resolveOption(ref).then((option) => setOptions((current) => ({ ...current, [ref]: option })))); }, [action, prefill]);
  function pick(option: RefOption) {
    setOptions((current) => ({ ...current, [option.ref]: option }));
    setDraft((current) => current.refs.includes(option.ref) ? current : { ...current, refs: [...current.refs, option.ref] });
    setPicking(false);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    const payload = { ...draft, title: draft.title.trim(), owner: draft.owner || null, group_id: draft.group_id || null, due_at: draft.due_at || null };
    try { onSaved(action ? await collabApi.updateAction(action.action_id, { ...payload, status }) : await collabApi.createAction(payload), !action); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  const title = action ? t("Edit action #{id}", { id: action.action_id }) : t("New action");
  return <Modal label={title} eyebrow={<><ClipboardCheck size={13} /> {t("Action")}</>} title={title} description={t("Creating an action or changing its status shows in the timeline of what it is about.")} onClose={onClose} className="ac-form">
    <form onSubmit={submit}>
      <div className="form-grid">
        {error && <div className="form-error field-span"><AlertTriangle size={15} /> {error}</div>}
        <label className="field-span">{t("Title")}<input required autoFocus maxLength={200} value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} placeholder={t("E.g. Check the FIC-1003 valve for stiction")} /></label>
        <div className="field-span act-form-description">
          <label>{t("Description")}<textarea rows={5} maxLength={4000} value={draft.description} placeholder={t("What has to be done and why. Write # to mention an asset, a person or a run.")} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
          <button type="button" className="as-link-button" onClick={() => setMentioning(!mentioning)}><AtSign size={13} /> {t("Mention an asset, a person or a run")}</button>
          {mentioning && <ReferencePicker className="msg-picker-inline" onClose={() => setMentioning(false)} onPick={(option) => { setDraft((current) => ({ ...current, description: withMention(current.description, option.ref) })); setMentioning(false); }} />}
        </div>
        <label>{t("Priority")}<select value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })}>{list.priorities.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <label>{t("Owner")}<select value={draft.owner ?? ""} onChange={(event) => setDraft({ ...draft, owner: event.target.value || null })}><option value="">{t("Nobody")}</option>{list.people.map((person) => <option key={person.username} value={person.username}>{person.display_name}</option>)}</select></label>
        <label>{t("Group")}<select value={draft.group_id ?? ""} onChange={(event) => setDraft({ ...draft, group_id: event.target.value || null })}><option value="">{t("No group")}</option>{(list.groups ?? []).map((group) => <option key={group.group_id} value={group.group_id}>{group.name}</option>)}</select></label>
        <p className="ac-hint field-span">{t("The owner and the group's people see the action, and so do the leaders of the groups above them. Without either, only you and the administrators see it.")}</p>
        <label>{t("Due date")}<input type="date" value={draft.due_at ?? ""} onChange={(event) => setDraft({ ...draft, due_at: event.target.value || null })} /></label>
        {action ? <label>{t("Status")}<select value={status} onChange={(event) => setStatus(event.target.value as ActionStatus)}>{list.statuses.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label> : <span />}
        <div className="field-span act-form-refs">
          <span className="act-label">{t("About")}</span>
          <div className="act-ref-list">
            {draft.refs.map((ref) => { const option = options[ref] ?? optionFromRef(ref); return <span key={ref} className="msg-about-chip"><Hash /><strong>{option.kind_label}: {option.title}</strong><button type="button" className="co-icon" onClick={() => setDraft({ ...draft, refs: draft.refs.filter((item) => item !== ref) })} aria-label={t("Remove {name}", { name: option.title })}><X /></button></span>; })}
            <button type="button" className="button button-secondary act-add-ref" onClick={() => setPicking(!picking)}><Plus size={14} /> {t("Reference")}</button>
          </div>
          {picking && <ReferencePicker className="msg-picker-inline" onClose={() => setPicking(false)} onPick={pick} />}
        </div>
      </div>
      <footer><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy || !draft.title.trim()}>{busy && <LoaderCircle className="spin" size={15} />} {action ? t("Save") : t("Create action")}</button></footer>
    </form>
  </Modal>;
}

export default ActionsPage;
