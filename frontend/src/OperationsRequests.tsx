/** Operations › Requests: what the people who use the suite ask of IT or an integrator. A request
 * is an action of kind "request" (plantcraft.actions): it has a category, a queue (the group that
 * answers it), its first answer timed, and the time spent on it. Anyone signed in asks ("Ask for
 * help" in every app's menu opens the form here) and sees their own; Operations sees them all.
 * See docs/operations.md, section 4. */
import { AlertTriangle, LifeBuoy, LoaderCircle, Plus, Timer } from "lucide-react";
import { type DataColumn, DataTable, Dialog, Heading } from "@plantcraft/ui";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { dayText, errorText, fullWhen, Go, PersonLink, shortWhen } from "./collab";
import { collabApi, type Action, type ActionList, type SlaClock } from "./collabApi";
import { hoursText } from "./actionsBoard";
import { t } from "./i18n";
import { navigate } from "./nav";
import { operationsApi, type DayName, type Priority, type TargetsAnswer } from "./operationsApi";
import { useCanOperate, useIsAdmin } from "./session";
import "./apps.css";
import "./collab.css";
import "./operations.css";

const OPEN = ["open", "in_progress", "blocked"];

/** The address of the request form filled in (a log line, an incident). */
export function askUrl(prefill: { title: string; text?: string; category?: string }): string {
  const params = new URLSearchParams({ new: "1", title: prefill.title.slice(0, 200) });
  if (prefill.text) params.set("text", prefill.text.slice(0, 1500));
  if (prefill.category) params.set("category", prefill.category);
  return `/ops/requests?${params.toString()}`;
}

/** What "Ask for help" (or a log line, an incident) put in the address: ?new=1&title=&text=&from=&page=. */
export interface AskPrefill { title: string; text: string; category: string }

export function readAskPrefill(search: string): AskPrefill | null {
  const params = new URLSearchParams(search);
  if (!params.get("new")) return null;
  const from = params.get("from");
  const page = params.get("page");
  const lines = [params.get("text") ?? ""];
  if (from || page) lines.push("", t("Asked from {place}", { place: [from, page].filter(Boolean).join(" · ") }));
  return { title: params.get("title") ?? "", text: lines.join("\n").trim(), category: params.get("category") ?? "other" };
}

/** How long a request waited for its first answer ("12 min", "3 h"), or has been waiting. */
export function answerTime(request: Pick<Action, "created_at" | "first_response_at">, now = Date.now()): { text: string; waiting: boolean } {
  const start = Date.parse(request.created_at);
  const end = request.first_response_at ? Date.parse(request.first_response_at) : now;
  const minutes = Math.max(0, Math.round((end - start) / 60000));
  const text = minutes < 60 ? t("{count} min", { count: minutes }) : minutes < 48 * 60 ? t("{count} h", { count: Math.round(minutes / 60) }) : t("{count} days", { count: Math.round(minutes / 1440) });
  return { text, waiting: !request.first_response_at };
}

/** A length of time in minutes as people read it ("45 min", "3 h", "2 days"). */
export function minutesText(minutes: number): string {
  const value = Math.max(0, Math.round(minutes));
  return value < 60 ? t("{count} min", { count: value }) : value < 48 * 60 ? t("{count} h", { count: Math.round(value / 60) }) : t("{count} days", { count: Math.round(value / 1440) });
}

/** One target as a chip: "2 h left", "late by 3 h", "met", "paused · 5 h left". */
export function slaText(clock: SlaClock | null | undefined): { text: string; tone: "" | "warn" | "bad" | "good" } | null {
  if (!clock) return null;
  const left = clock.target_minutes - clock.used_minutes;
  if (clock.state === "met") return { text: t("met"), tone: "good" };
  if (clock.state === "breached") return { text: t("late by {time}", { time: minutesText(-left) }), tone: "bad" };
  const text = t("{time} left", { time: minutesText(left) });
  if (clock.paused) return { text: t("paused · {text}", { text }), tone: "" };
  return { text, tone: clock.state === "at_risk" ? "warn" : "" };
}

/** The target that matters now: the first answer until there is one, then the resolution. */
export function currentTarget(request: Pick<Action, "sla" | "first_response_at">): { label: string; clock: SlaClock } | null {
  if (!request.sla) return null;
  if (!request.first_response_at && request.sla.response.state !== "met") return { label: t("First answer"), clock: request.sla.response };
  return { label: t("Resolution"), clock: request.sla.resolution };
}

function SlaChip({ clock }: { clock: SlaClock | null | undefined }) {
  const shown = slaText(clock);
  if (!shown) return <span className="muted">—</span>;
  return <span className={`apps-chip ops-sla${shown.tone ? ` ops-sla-${shown.tone}` : ""}`}>{shown.text}</span>;
}

/** A request's two targets, for its page: target, where it stands. */
export function RequestTargets({ request }: { request: Action }) {
  const admin = useIsAdmin();
  if (!request.sla) return null;
  const support = new URLSearchParams({ new: "1", request: String(request.action_id), ...(request.owner ? { user: request.owner } : {}) });
  return <>
    {admin && OPEN.includes(request.status) && <div><span>{t("Support access")}</span><strong><Go to={`/ops/support?${support.toString()}`}>{t("Give someone Operations for a few hours")}</Go></strong></div>}
    <div><span>{t("First answer target")}</span><strong>{minutesText(request.sla.response.target_minutes)} <SlaChip clock={request.sla.response} /></strong></div>
    {request.sla.service_hours && <div><span>{t("Working hours")}</span><strong>{workingHoursText(request.sla.service_hours)} <small className="muted">{t("the clocks stop outside them")}</small></strong></div>}
    <div><span>{t("Resolution target")}</span><strong>{minutesText(request.sla.resolution.target_minutes)} <SlaChip clock={request.sla.resolution} />{(request.sla.resolution.paused_minutes ?? 0) > 0 && <small className="muted"> · {t("{time} blocked, not counted", { time: minutesText(request.sla.resolution.paused_minutes ?? 0) })}</small>}</strong></div>
  </>;
}

const COLUMNS: DataColumn<Action>[] = [
  { key: "id", label: "#", className: "act-id", sort: (item) => Number(item.action_id), render: (item) => <span className="muted">{item.action_id}</span> },
  { key: "title", label: t("Request"), sort: (item) => item.title, render: (item) => <><strong className="ops-request-title">{item.title}</strong><small className="apps-sub">{item.category_label}</small></> },
  { key: "asked", label: t("Asked by"), phone: "hide", sort: (item) => item.created_by_name, render: (item) => <span onClick={(event) => event.stopPropagation()}><PersonLink username={item.created_by} name={item.created_by_name} /></span> },
  { key: "queue", label: t("Queue"), phone: "hide", sort: (item) => item.group_name ?? "", filter: { value: (item) => item.group_name ?? t("No queue") }, render: (item) => item.group_name ?? <span className="muted">—</span> },
  { key: "status", label: t("Status"), sort: (item) => OPEN.indexOf(item.status), filter: { value: (item) => item.status_label }, render: (item) => <span className={`act-status act-status-${item.status}`}>{item.status_label}</span> },
  { key: "answer", label: t("First answer"), sort: (item) => item.first_response_at ?? "~", render: (item) => { const time = answerTime(item); return <span className={time.waiting && OPEN.includes(item.status) ? "ops-waiting" : ""} title={item.first_response_at ? fullWhen(item.first_response_at) : undefined}>{time.waiting ? t("waiting {time}", { time: time.text }) : t("after {time}", { time: time.text })}</span>; } },
  { key: "target", label: t("Target"), sort: (item) => { const now = currentTarget(item); return now ? now.clock.used_minutes / now.clock.target_minutes : -1; }, filter: { value: (item) => { const now = currentTarget(item); return now ? (now.clock.state === "breached" ? t("Late") : now.clock.state === "at_risk" ? t("At risk") : now.clock.state === "met" ? t("Met") : t("On time")) : t("No target"); } },
    render: (item) => { const now = currentTarget(item); return now ? <span title={now.label}><SlaChip clock={now.clock} /><small className="apps-sub">{now.label}</small></span> : <span className="muted">—</span>; } },
  { key: "time", label: t("Time"), phone: "hide", className: "num", sort: (item) => item.hours_logged ?? 0, render: (item) => (item.hours_logged ? hoursText(item.hours_logged) : "—") },
  { key: "asked_at", label: t("Asked"), phone: "hide", sort: (item) => item.created_at, render: (item) => <time dateTime={item.created_at} title={fullWhen(item.created_at)}>{shortWhen(item.created_at)}</time> },
];

export function RequestsPage() {
  const operate = useCanOperate();
  const [list, setList] = useState<ActionList | null>(null);
  const [open, setOpen] = useState(true);
  const [error, setError] = useState("");
  const [asking, setAsking] = useState<AskPrefill | null>(null);
  const load = useCallback(() => collabApi.actions({ kind: "request", status: open ? OPEN : [] }).then((value) => { setList(value); setError(""); }, (err) => setError(errorText(err))), [open]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    // The form opened from the address (also when already on this page: "Ask for help" again, a
    // log line): it opens, and the page keeps its own address afterwards.
    const take = () => {
      const prefill = readAskPrefill(window.location.search);
      if (!prefill) return;
      setAsking(prefill);
      window.history.replaceState(window.history.state, "", window.location.pathname);
    };
    take();
    window.addEventListener("popstate", take);
    return () => window.removeEventListener("popstate", take);
  }, []);
  const items = list?.items ?? [];
  const waiting = items.filter((item) => !item.first_response_at && OPEN.includes(item.status)).length;
  const late = items.filter((item) => OPEN.includes(item.status) && currentTarget(item)?.clock.state === "breached").length;
  const admin = useIsAdmin();
  const [targeting, setTargeting] = useState(false);
  return <div className="apps-page ops-requests">
    <Heading title={t("Requests")} actions={<button type="button" className="button button-primary" onClick={() => setAsking({ title: "", text: "", category: "other" })}><Plus size={15} /> {t("New request")}</button>} />
    <p className="muted ops-intro">{operate ? t("What the people of the suite asked of IT and the integrators. A request is an action: open one to answer, change its status or log the time spent.") : t("What you asked of IT or an integrator, and their answers.")}</p>
    <div className="act-toolbar">
      <div className="act-filters" role="group" aria-label={t("Status")}>
        <button type="button" className={open ? "active" : ""} aria-pressed={open} onClick={() => setOpen(true)}>{t("Not done")}</button>
        <button type="button" className={!open ? "active" : ""} aria-pressed={!open} onClick={() => setOpen(false)}>{t("All")}</button>
      </div>
      {waiting > 0 && <span className="apps-chip apps-chip-warn">{t("{count} waiting for a first answer", { count: waiting })}</span>}
      {late > 0 && <span className="apps-chip apps-chip-bad">{t("{count} late", { count: late })}</span>}
      {operate && <button type="button" className="button button-secondary ops-targets-open" onClick={() => setTargeting(true)}><Timer size={15} /> {t("Targets")}</button>}
    </div>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
    {!list && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {list && <DataTable rows={items} columns={COLUMNS} rowKey={(item) => String(item.action_id)} label={t("Requests")} onRowClick={(item) => navigate(`/actions/${encodeURIComponent(String(item.action_id))}`)}
      searchText={(item) => `${item.title} ${item.created_by_name} ${item.category_label ?? ""}`} searchPlaceholder={t("Filter requests")} initialSort={{ key: "asked_at", descending: true }}
      empty={open ? t("No open requests.") : t("No requests yet.")} />}
    {targeting && <TargetsDialog editable={admin} groups={list?.groups ?? []} onClose={() => setTargeting(false)} onSaved={() => { setTargeting(false); void load(); }} />}
    {asking && list && <AskDialog list={list} prefill={asking} onClose={() => setAsking(null)} onAsked={(action) => { setAsking(null); navigate(`/actions/${encodeURIComponent(String(action.action_id))}`); }} />}
  </div>;
}

/** The request form: what is wrong, which kind of problem, who should answer. */
export function AskDialog({ list, prefill, onClose, onAsked }: { list: ActionList; prefill: AskPrefill; onClose: () => void; onAsked: (action: Action) => void }) {
  const [title, setTitle] = useState(prefill.title);
  const [text, setText] = useState(prefill.text);
  const categories = list.categories ?? [];
  const [category, setCategory] = useState(categories.some((item) => item.id === prefill.category) ? prefill.category : "other");
  const [queue, setQueue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try { onAsked(await collabApi.ask({ title: title.trim(), description: text.trim(), category, group_id: queue || null, refs: [] })); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  return <Dialog title={t("Ask for help")} onClose={onClose} onSubmit={() => void submit()} wide
    footer={<><button type="button" className="button button-secondary" onClick={onClose}>{t("Cancel")}</button><button className="button button-primary" disabled={busy || !title.trim()}>{busy ? <LoaderCircle className="spin" size={15} /> : <LifeBuoy size={15} />} {t("Send request")}</button></>}>
    <div className="ops-ask">
      <label><span>{t("What do you need?")}</span><input value={title} maxLength={200} required autoFocus onChange={(event) => setTitle(event.target.value)} placeholder={t("The trend of FIC-101 does not load")} /></label>
      <label><span>{t("Kind of problem")}</span><select value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <label><span>{t("Who should answer")}</span><select value={queue} onChange={(event) => setQueue(event.target.value)}>
        <option value="">{t("The administrators")}</option>
        {(list.groups ?? []).map((group) => <option key={group.group_id} value={group.group_id}>{group.name}</option>)}
      </select></label>
      <label className="ops-ask-text"><span>{t("Details")}</span><textarea value={text} rows={6} maxLength={4000} onChange={(event) => setText(event.target.value)} placeholder={t("What you did, what you expected, what happened; since when.")} /></label>
    </div>
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
  </Dialog>;
}

/** The month's day range as people read it ("Oct 1 – Oct 31"). */
export function monthRange(first: string, last: string): string {
  return `${dayText(first)} – ${dayText(last)}`;
}

const PRIORITY_ORDER: Priority[] = ["critical", "high", "medium", "low"];
const PRIORITY_LABEL: Record<Priority, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

/** The requests' targets by priority, in hours: the first answer and the resolution (Blocked
 * time not counted). Administrators change them; Operations reads them. */
export function TargetsDialog({ editable, groups, onClose, onSaved }: { editable: boolean; groups: Array<{ group_id: string; name: string }>; onClose: () => void; onSaved: () => void }) {
  const [answer, setAnswer] = useState<TargetsAnswer | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    operationsApi.targets().then((found) => {
      setAnswer(found);
      setDraft(Object.fromEntries(PRIORITY_ORDER.flatMap((key) => [[`${key}.response`, String(found.targets[key].response_hours)], [`${key}.resolution`, String(found.targets[key].resolution_hours)]])));
    }, (err) => setError(errorText(err)));
  }, []);
  async function save() {
    const targets = Object.fromEntries(PRIORITY_ORDER.map((key) => [key, { response_hours: Number(draft[`${key}.response`]?.replace(",", ".")), resolution_hours: Number(draft[`${key}.resolution`]?.replace(",", ".")) }])) as TargetsAnswer["targets"];
    setBusy(true);
    try { await operationsApi.setTargets(targets); onSaved(); } catch (err) { setError(errorText(err)); setBusy(false); }
  }
  return <Dialog title={t("Request targets")} onClose={onClose} onSubmit={editable ? () => void save() : undefined}
    footer={<><button type="button" className="button button-secondary" onClick={onClose}>{editable ? t("Cancel") : t("Close")}</button>{editable && <button className="button button-primary" disabled={busy || !answer}>{busy ? <LoaderCircle className="spin" size={15} /> : null} {t("Save targets")}</button>}</>}>
    <p className="muted">{t("Hours on the clock: day and night, or only in the queue's working hours below. The resolution clock stops while a request is Blocked: waiting for who asked, or for a third party.")}</p>
    {!answer && !error && <div className="module-state"><LoaderCircle className="spin" /><span>{t("Loading…")}</span></div>}
    {answer && <table className="ops-targets">
      <thead><tr><th>{t("Priority")}</th><th>{t("First answer (h)")}</th><th>{t("Resolution (h)")}</th></tr></thead>
      <tbody>{PRIORITY_ORDER.map((key) => <tr key={key}>
        <th scope="row">{t(PRIORITY_LABEL[key])}</th>
        {(["response", "resolution"] as const).map((part) => <td key={part}>{editable
          ? <input inputMode="decimal" value={draft[`${key}.${part}`] ?? ""} aria-label={`${t(PRIORITY_LABEL[key])} · ${part === "response" ? t("First answer (h)") : t("Resolution (h)")}`} onChange={(event) => setDraft((now) => ({ ...now, [`${key}.${part}`]: event.target.value }))} />
          : <span>{draft[`${key}.${part}`]}</span>}</td>)}
      </tr>)}</tbody>
    </table>}
    {answer && <ServiceHoursPanel answer={answer} groups={groups} editable={editable} onChanged={setAnswer} />}
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
  </Dialog>;
}

const DAYS: DayName[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const DAY_LABEL: Record<DayName, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

/** "Mon–Fri 08:00–17:00", "Mon, Wed 06:00–14:00". */
export function workingHoursText(hours: { days: string[]; start: string; end: string }): string {
  const index = hours.days.map((day) => DAYS.indexOf(day as DayName)).filter((day) => day >= 0).sort();
  const run = index.length > 2 && index.every((day, at) => at === 0 || day === index[at - 1] + 1);
  const days = run ? `${t(DAY_LABEL[DAYS[index[0]]])}–${t(DAY_LABEL[DAYS[index[index.length - 1]]])}` : index.map((day) => t(DAY_LABEL[DAYS[day]])).join(", ");
  return `${days} ${hours.start}–${hours.end}`;
}

/** When each queue works: its requests' clocks run only then (none: day and night). */
function ServiceHoursPanel({ answer, groups, editable, onChanged }: { answer: TargetsAnswer; groups: Array<{ group_id: string; name: string }>; editable: boolean; onChanged: (answer: TargetsAnswer) => void }) {
  const set = answer.service_hours ?? [];
  const [queue, setQueue] = useState("");
  const current = set.find((item) => (item.queue ?? "") === queue);
  const [days, setDays] = useState<DayName[]>(["mon", "tue", "wed", "thu", "fri"]);
  const [start, setStart] = useState("08:00");
  const [end, setEnd] = useState("17:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (current) { setDays(current.days); setStart(current.start); setEnd(current.end); }
  }, [current]);
  async function save(clear: boolean) {
    setBusy(true);
    try { onChanged(await operationsApi.setServiceHours(queue || null, clear ? null : { days, start, end })); setError(""); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  return <section className="ops-service-hours" aria-labelledby="ops-service-hours-title">
    <h3 id="ops-service-hours-title">{t("Working hours")} {answer.timezone && <small className="muted">{answer.timezone}</small>}</h3>
    {set.length ? <ul>{set.map((item) => <li key={item.queue ?? ""}><strong>{item.queue_name ?? t("Default")}</strong> {workingHoursText(item)}</li>)}</ul> : <p className="muted">{t("Every queue works day and night.")}</p>}
    {editable && <div className="ops-service-hours-form">
      <label><span>{t("Queue")}</span><select value={queue} onChange={(event) => setQueue(event.target.value)}>
        <option value="">{t("Default (no queue, or a queue without its own)")}</option>
        {groups.map((group) => <option key={group.group_id} value={group.group_id}>{group.name}</option>)}
      </select></label>
      <fieldset><legend>{t("Days")}</legend>{DAYS.map((day) => <label key={day} className="act-mine"><input type="checkbox" checked={days.includes(day)} onChange={(event) => setDays((now) => event.target.checked ? DAYS.filter((item) => now.includes(item) || item === day) : now.filter((item) => item !== day))} /> {t(DAY_LABEL[day])}</label>)}</fieldset>
      <label><span>{t("From")}</span><input type="time" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label><span>{t("To")}</span><input type="time" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      <div className="ops-service-hours-actions">
        <button type="button" className="button button-secondary" disabled={busy || !days.length} onClick={() => void save(false)}>{t("Save working hours")}</button>
        {current && <button type="button" className="button button-ghost" disabled={busy} onClick={() => void save(true)}>{t("Day and night")}</button>}
      </div>
    </div>}
    {error && <div className="form-error" role="alert"><AlertTriangle size={15} /> {error}</div>}
  </section>;
}
