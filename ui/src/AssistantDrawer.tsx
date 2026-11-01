/**
 * The assistant's side panel: one button at the top right of every page
 * opens the assistant in a panel from the left, over the page (SidePanel.tsx, round 8). It first asks what the person wants: the
 * tasks the page's developer offers there (`useAssistantPage`), or their own words. The task
 * steers the model (its instructions and the context it reads), so one page can offer several
 * things to do. Like a chat in Messages (round 8), the panel opens on the
 * person's earlier chats and a new one: a new chat is about the page it was started on, and every
 * chat is kept, private to the person, in Desk's Assistant ("Full page" opens it there). The model reads the
 * plant as the person, through PlantCraft's Assistant (docs/assistant.md); the context only tells
 * it where the person is and what they chose (the person can read it: "See the context").
 *
 * One panel at a time for the whole page: `openAssistant(...)` from anywhere, drawn by the
 * `AssistantHost` that `SuiteShell` renders. Every page's title carries the button that opens it
 * (`AssistantTitleButton`, drawn by `Heading`; owner, 2026-10-25, round 9).
 *
 * Works: what the assistant does on a page is declared as data, PlantCraft's
 * and each app's (docs/assistant.md, "Works"). A page names itself (`page: "<app>:<page id>"`) with a
 * few facts and what it shows (`facts`, `view`); the button beside the title lists that page's works
 * and tasks, and PlantCraft builds the chosen work's context. A "create" work ends in a card with the
 * object's fields, editable there: the person clicks Create and the object's own route creates it
 * with their session (the model never writes).
 */
import { AlertTriangle, ArrowLeft, ArrowUp, Check, ChevronRight, ExternalLink, LoaderCircle, Plus, RotateCcw, Settings2, Sparkles, X } from "lucide-react";
import { AnswerProgress, AssistantChart, type AssistantChartData } from "./AssistantAnswer.js";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type FormEvent, type KeyboardEvent } from "react";
import { useDismiss } from "./dismiss.js";
import { platformPath } from "./Journey.js";
import { renderMarkdown } from "./Markdown.js";
import { formatDate } from "./format.js";
import { isoOf, localOf } from "./timeChart.js";
import { t } from "./i18n.js";
import { claimPanel, registerPanel, SidePanel, usePresence } from "./SidePanel.js";

/** Often enough to follow the text as it is written (streamed into the message). */
export const DRAWER_POLL_MS = 700;

/** One thing the assistant can do on a page, offered when the panel opens. */
export type AssistantTask = {
  /** What the person sees: "Explain this run". */
  label: string;
  /** One line under it. */
  hint?: string;
  /** What the model is asked to do, in the page's words; not shown as a message (the person can read it). */
  instructions: string;
  /** The person completes the question first ("Which execution?"); without it the task is asked at once. */
  ask?: string;
  /** What this task adds to the context, read when it is chosen (a table's rows, an object's state). */
  context?: () => string | undefined | null;
  /** The object this task is about, when not the page's. */
  subject?: string;
  /** Runs first, as the page's `prepare`. */
  prepare?: () => Promise<unknown>;
  /** The declared work this stands for (`<app>:<id>`): PlantCraft builds its context. */
  work?: string;
  /** A work that ends in a card to create an object. */
  creates?: boolean;
};

/** One field of the object a "create" work proposes (the SDK's `WorkField`). */
export type AssistantWorkField = {
  key: string;
  title: string;
  help?: string;
  type: "text" | "long_text" | "number" | "integer" | "boolean" | "choice" | "date" | "datetime" | "list";
  required?: boolean;
  options?: string[];
  max_length?: number;
  min?: number | null;
  max?: number | null;
};

/** A work PlantCraft offers on a page (`GET /api/assistant/works?page=`). */
export type AssistantWork = {
  key: string;
  app: string;
  kind: "ask" | "create";
  title: string;
  hint?: string;
  ask?: string;
  object?: string;
  fields?: AssistantWorkField[];
  create?: string;
  open?: string | null;
  /** The object's own form, opened with the fields as a draft (`takeAssistantDraft`) instead of `create`. */
  form?: string | null;
};

/** What a proposal's card needs to draw itself and create the object, kept with the proposal. */
export type ProposalCardSpec = { app: string; title: string; fields: AssistantWorkField[]; create?: string | null; open?: string | null; form?: string | null };
/** An object the model proposed (`meta.proposals` of an answer). */
export type AssistantProposal = {
  work: string;
  object: string;
  fields: Record<string, unknown>;
  state: "proposed" | "created" | "opened" | "discarded";
  ref?: string;
  href?: string;
  card?: ProposalCardSpec;
};

/** What the panel is about: the place, the object, what the page shows and offers. */
export type AssistantRequest = {
  /** The object (`run:linkcraft/42`, `asset:FIC-101`); empty for a whole page. */
  subject?: string;
  /** Its name in the panel's header. */
  title?: string;
  /** Where the person is: "Alarms › Active alarms". */
  place?: string;
  /** What the page shows and offers, for the model (the person can read it). 4,000 characters at most. */
  context?: string;
  /** What the assistant can do here, offered first. The suite's own ("Explain this page") follow. */
  tasks?: AssistantTask[];
  /** Questions offered as one click (older pages; tasks are the way now). */
  suggestions?: string[];
  /** PlantCraft's address; the host's when left out. */
  platformUrl?: string | null;
  /** Runs first: the app writes what it knows about the object (`/api/v1/knowledge`). A failure is ignored. */
  prepare?: () => Promise<unknown>;
  /** The page, as the suite names it (`processcraft:actions`, `linkcraft:blocks`): its works are offered. */
  page?: string;
  /** A few facts about the page or its object (counts, states), never whole tables. */
  facts?: Record<string, unknown>;
  /** What the page shows: its filters, the selection, the ids of the rows on screen. */
  view?: Record<string, unknown>;
  /** Start at once with this work (`<app>:<id>`), as picked from the menu beside the title. */
  work?: string;
  /** Start at once with the task of this label, as picked from the menu beside the title. */
  task?: string;
};

// One panel for the page, opened from anywhere (a button, the corner, a page's own code).
let current: AssistantRequest | null = null;
let place: AssistantRequest | null = null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); };

/** Open the assistant's panel about ``request`` (replacing an open one). */
export function openAssistant(request: AssistantRequest) { claimPanel("assistant"); current = { ...request }; emit(); }
export function closeAssistant() { if (current === null) return; current = null; emit(); }
registerPanel("assistant", closeAssistant, () => current !== null);
export function useOpenAssistant(): AssistantRequest | null { return useSyncExternalStore(subscribe, () => current, () => null); }

/** A page tells the assistant what it is about and what it can do there (its tasks). The page's
 * developer writes this once per page; the button at the top opens the panel with it. */
export function useAssistantPage(request: AssistantRequest | null) {
  const key = JSON.stringify(request);
  const latest = useRef(request);
  latest.current = request;
  // The newest functions (a task's context reads the page's state) without opening anything again.
  useEffect(() => { if (place && latest.current) place = latest.current; });
  useEffect(() => {
    const mine = latest.current;
    place = mine;
    emit();
    return () => { if (place === mine || place === latest.current) { place = null; emit(); } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
/** The former name of `useAssistantPage`. */
export const useAssistantPlace = useAssistantPage;
export function useAssistantPlaceValue(): AssistantRequest | null { return useSyncExternalStore(subscribe, () => place, () => null); }

/** The assistant's mark: a small rounded box with a spark, the same everywhere it is offered. */
export function AssistantMark({ size = 18, className }: { size?: number; className?: string }) {
  return <svg className={["pc-assistant-mark", className].filter(Boolean).join(" ")} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <rect x="1.5" y="1.5" width="21" height="21" rx="6.5" className="pc-assistant-mark-box" />
    <path className="pc-assistant-mark-spark" d="M11 5.6c.3 2.9 1.9 4.6 4.9 5-3 .4-4.6 2.1-4.9 5-.3-2.9-1.9-4.6-4.9-5 3-.4 4.6-2.1 4.9-5Z" />
    <path className="pc-assistant-mark-spark" d="M16.6 14.2c.15 1.35.9 2.1 2.2 2.25-1.3.15-2.05.9-2.2 2.25-.15-1.35-.9-2.1-2.2-2.25 1.3-.15 2.05-.9 2.2-2.25Z" />
  </svg>;
}

/** The mark as a button beside an object, opening the panel about it. Pages now describe their tasks
 * with `useAssistantPage` and the person opens the panel from the top; this stays
 * for a place outside a page (a dialog of its own). */
export function AskAssistant({ label, className, ...request }: AssistantRequest & { label?: string; className?: string }) {
  const text = label ?? t("Ask the assistant about {title}", { title: request.title || request.subject || t("this page") });
  return <button type="button" className={["pc-ask-assistant", className].filter(Boolean).join(" ")} title={text} aria-label={text} onClick={(event) => { event.stopPropagation(); openAssistant(request); }}>
    <AssistantMark size={18} />
  </button>;
}

type Chart = AssistantChartData;
type Step = { tool: string; title: string; summary: string; state: "running" | "ok" | "error"; error?: string };
type Message = { message_id: number; role: "user" | "assistant"; text: string; state: "working" | "done" | "failed"; steps: Step[]; charts: Chart[]; created_at?: string; meta: { model?: string; queued?: boolean; proposals?: AssistantProposal[] } };
/** `can_set_up`: the person is an administrator, who connects the model in Setup. */
/** `demo`: a public demo's visitor, who reads what the assistant does but never asks it. */
type Status = { available: boolean; allowed?: boolean; reason: string; can_set_up?: boolean; demo?: boolean };
/** One of the person's earlier chats, as `GET /api/assistant` lists them. */
export type AssistantChatSummary = { chat_id: number; title: string; place?: string; updated_at?: string; working?: boolean };

/** How many earlier chats the panel lists; the rest are in Desk. */
export const PANEL_CHATS = 8;

async function call<T>(base: string | null | undefined, path: string, init?: RequestInit): Promise<T> {
  return fetchJson<T>(platformPath(base, path), init);
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin", ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload ? String((payload as { detail: unknown }).detail) : "";
    throw new Error(detail || t("Couldn't connect to the server."));
  }
  return payload as T;
}

/** The assistant's state from PlantCraft, read once per page: whether to offer it at all. */
let statusPromise: Promise<Status | null> | null = null;
export function assistantStatus(base?: string | null): Promise<Status | null> {
  statusPromise ??= call<Status>(base, "api/assistant").catch(() => null);
  return statusPromise;
}
/** Read the state again on the next call (tests; after an administrator changed the model). */
export function forgetAssistantStatus() { statusPromise = null; }

/** The works PlantCraft offers the person on `page`, the create works first; none when it cannot say. */
export async function assistantWorks(base: string | null | undefined, page: string | undefined): Promise<AssistantWork[]> {
  if (!page) return [];
  try {
    const found = await call<{ works?: AssistantWork[] }>(base, `api/assistant/works?${new URLSearchParams({ page }).toString()}`);
    return found.works ?? [];
  } catch { return []; }
}

/** A work as the panel offers it, beside the page's tasks. */
export function workTask(work: AssistantWork): AssistantTask {
  return { label: work.title, hint: work.hint || undefined, instructions: "", ask: work.ask || undefined, work: work.key, creates: work.kind === "create" };
}

/** A work's route as this page reaches it: PlantCraft's under its address, an app's as declared (under the app's prefix). */
export function workRoute(base: string | null | undefined, app: string, route: string): string {
  return app === "processcraft" ? platformPath(base, route) : route;
}

/** The new object's id in what its create route answered (`{action_id}`, `{id}`, `{block: {id}}`). */
export function createdId(object: string, answer: unknown): string {
  const read = (value: unknown): string => {
    if (!value || typeof value !== "object") return "";
    const record = value as Record<string, unknown>;
    for (const key of [`${object}_id`, "id"]) {
      const found = record[key];
      if (typeof found === "string" || typeof found === "number") return String(found);
    }
    return "";
  };
  return read(answer) || read((answer as Record<string, unknown> | null)?.[object]);
}

/** A value as its input shows it ("2026-10-27T09:00" for a date and time, in local time). */
export function fieldInput(field: AssistantWorkField, value: unknown): string | boolean {
  if (field.type === "boolean") return value === true;
  if (value === undefined || value === null) return "";
  if (field.type === "list") return Array.isArray(value) ? value.join(", ") : String(value);
  if (field.type === "datetime") {
    // In the zone every page shows times in, as the person reads it there.
    return localOf(String(value)) || String(value);
  }
  return String(value);
}

/** The card's inputs as the create route takes them: typed, empty ones left out, dates in UTC. */
export function fieldValues(fields: AssistantWorkField[], inputs: Record<string, string | boolean>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const field of fields) {
    const input = inputs[field.key];
    if (field.type === "boolean") { if (input !== undefined) body[field.key] = input === true; continue; }
    const text = typeof input === "string" ? input.trim() : "";
    if (!text) continue;
    if (field.type === "number" || field.type === "integer") body[field.key] = Number(text);
    else if (field.type === "list") body[field.key] = text.split(",").map((item) => item.trim()).filter(Boolean);
    else if (field.type === "datetime") body[field.key] = isoOf(text) || text;
    else body[field.key] = text;
  }
  return body;
}

/** The required fields still empty on the card. */
export function missingFields(fields: AssistantWorkField[], inputs: Record<string, string | boolean>): string[] {
  return fields.filter((field) => field.required && field.type !== "boolean" && !String(inputs[field.key] ?? "").trim()).map((field) => field.title);
}

function FieldInput({ field, value, onChange, disabled }: { field: AssistantWorkField; value: string | boolean; onChange: (value: string | boolean) => void; disabled: boolean }) {
  const id = `pc-proposal-${field.key}`;
  const text = typeof value === "string" ? value : "";
  const label = <span>{field.title}{field.required && <b aria-hidden="true"> *</b>}</span>;
  if (field.type === "boolean") return <label className="pc-proposal-check"><input type="checkbox" checked={value === true} disabled={disabled} onChange={(event) => onChange(event.target.checked)} />{label}</label>;
  let input;
  if (field.type === "long_text") input = <textarea id={id} rows={3} value={text} maxLength={field.max_length} disabled={disabled} onChange={(event) => onChange(event.target.value)} />;
  else if (field.type === "choice") input = <select id={id} value={text} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
    {(!field.required || !text) && <option value="">—</option>}
    {(field.options ?? []).map((option) => <option key={option} value={option}>{option}</option>)}
  </select>;
  else {
    const type = { number: "number", integer: "number", date: "date", datetime: "datetime-local" }[field.type as string] ?? "text";
    input = <input id={id} type={type} value={text} step={field.type === "integer" ? 1 : field.type === "number" ? "any" : undefined} min={field.min ?? undefined} max={field.max ?? undefined}
      maxLength={type === "text" ? field.max_length : undefined} placeholder={field.type === "list" ? t("Separated by commas") : undefined} disabled={disabled} onChange={(event) => onChange(event.target.value)} />;
  }
  return <label className="pc-proposal-field" htmlFor={id}>{label}{input}{field.help && <small>{field.help}</small>}</label>;
}

const DRAFT_KEY = "pc-assistant-draft:";
/** How long a draft waits for its form (the person clicked and the page is loading). */
export const DRAFT_MS = 10 * 60_000;

/** The fields a card handed to this form (a work with a `form`), read once: the form fills itself
 * in with them and the person saves there. Null when there is none (or it is older than DRAFT_MS). */
export function takeAssistantDraft(work: string): Record<string, unknown> | null {
  try {
    const raw = window.sessionStorage.getItem(DRAFT_KEY + work);
    if (raw === null) return null;
    window.sessionStorage.removeItem(DRAFT_KEY + work);
    const draft = JSON.parse(raw) as { fields?: Record<string, unknown>; at?: number };
    if (!draft.fields || typeof draft.at !== "number" || Date.now() - draft.at > DRAFT_MS) return null;
    return draft.fields;
  } catch { return null; }
}

/** The card of a proposed object: its fields, editable, and Create, which calls the object's own
 * route with the person's session (or, for a work with a form, opens the object's form filled in);
 * or Put aside. What the person did is kept with the chat. */
export function ProposalCard({ base, chatId, messageId, index, proposal }: { base?: string | null; chatId: number | null; messageId: number; index: number; proposal: AssistantProposal }) {
  const card = proposal.card;
  const fields = card?.fields ?? [];
  const [inputs, setInputs] = useState<Record<string, string | boolean>>(() => Object.fromEntries(fields.map((field) => [field.key, fieldInput(field, proposal.fields[field.key])])));
  const [state, setState] = useState(proposal.state);
  const [href, setHref] = useState(proposal.href ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const missing = missingFields(fields, inputs);
  const object = proposal.object;

  async function record(next: "created" | "opened" | "discarded", ref = "", link = "") {
    if (chatId === null) return;
    await call(base, `api/assistant/chats/${chatId}/proposals`, { method: "POST", body: JSON.stringify({ message_id: messageId, index, state: next, ref, href: link.startsWith("/") ? link : "" }) }).catch(() => undefined);
  }
  // The fields handed to the object's form; again on each Open, as a form reads them once
  // (an opened card's Open gave an empty form, 2026-10-26).
  const handOver = () => {
    try { window.sessionStorage.setItem(DRAFT_KEY + proposal.work, JSON.stringify({ fields: fieldValues(fields, inputs), at: Date.now() })); } catch { /* no storage: the form starts empty */ }
  };
  async function create() {
    if (!card || busy || missing.length) return;
    setBusy(true); setError("");
    if (card.form) {
      // The person finishes it in its own form (code to test, a diagram to draw): hand the fields over.
      const link = workRoute(base, card.app, card.form);
      handOver();
      await record("opened", "", link);
      setHref(link); setState("opened"); setBusy(false);
      window.location.assign(link);
      return;
    }
    try {
      const made = await fetchJson<unknown>(workRoute(base, card.app, card.create ?? ""), { method: "POST", body: JSON.stringify(fieldValues(fields, inputs)) });
      const id = createdId(object, made);
      const link = id && card.open ? workRoute(base, card.app, card.open.replace("{id}", encodeURIComponent(id))) : "";
      await record("created", id ? `${object}:${id}` : "", link);
      setHref(link); setState("created");
      // The page shows the new object without a reload (a calendar, a list): it listens for this.
      window.dispatchEvent(new CustomEvent("pc-assistant-created", { detail: { work: proposal.work, object, id } }));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }
  async function putAside() {
    setBusy(true);
    await record("discarded");
    setState("discarded"); setBusy(false);
  }

  if (state === "created") return <div className="pc-proposal pc-proposal-done"><Check size={14} aria-hidden="true" /><span>{t("Created: {object}", { object: String(inputs.title || proposal.fields.title || object) })}</span>
    {href && <a href={href}><ExternalLink size={13} aria-hidden="true" />{t("Open")}</a>}</div>;
  if (state === "opened") return <div className="pc-proposal pc-proposal-done"><Check size={14} aria-hidden="true" /><span>{t("Opened in its form: {object}", { object: String(inputs.title || inputs.name || proposal.fields.title || proposal.fields.name || object) })}</span>
    {href && <a href={href} onClick={handOver}><ExternalLink size={13} aria-hidden="true" />{t("Open")}</a>}</div>;
  if (state === "discarded") return <div className="pc-proposal pc-proposal-aside"><span>{t("Put aside: {object}", { object: String(proposal.fields.title || object) })}</span></div>;
  return <form className="pc-proposal" aria-label={t("Proposed {object}", { object })} onSubmit={(event) => { event.preventDefault(); void create(); }}>
    <header><Plus size={14} aria-hidden="true" /><strong>{card?.title || t("New {object}", { object })}</strong></header>
    {card ? fields.map((field) => <FieldInput key={field.key} field={field} value={inputs[field.key] ?? ""} disabled={busy} onChange={(value) => setInputs((current) => ({ ...current, [field.key]: value }))} />)
      : <dl>{Object.entries(proposal.fields).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>}
    {missing.length > 0 && <small className="pc-proposal-missing">{t("Still needed: {fields}", { fields: missing.join(", ") })}</small>}
    {error && <p className="pc-drawer-failed"><AlertTriangle size={14} /> {error}</p>}
    <footer>
      <button type="submit" className="pc-proposal-create" disabled={!card || busy || missing.length > 0}>{busy ? <LoaderCircle className="spin" size={14} /> : <Check size={14} aria-hidden="true" />}{card?.form ? t("Continue in the {object} form", { object }) : t("Create {object}", { object })}</button>
      <button type="button" onClick={() => void putAside()} disabled={busy}>{t("Put aside")}</button>
    </footer>
    <small className="pc-proposal-note">{card?.form ? t("The form opens filled in with these fields; you check it and save there.") : t("Nothing is created until you click Create; you can change any field first.")}</small>
  </form>;
}

function merge(current: Message[], fresh: Message[]): Message[] {
  const byId = new Map(current.map((item) => [item.message_id, item]));
  for (const item of fresh) byId.set(item.message_id, item);
  return [...byId.values()].sort((a, b) => a.message_id - b.message_id);
}

function Answer({ message, base, chatId, onRetry }: { message: Message; base?: string | null; chatId: number | null; onRetry?: () => void }) {
  const [open, setOpen] = useState(false);
  const working = message.state === "working";
  const reads = message.steps.length;
  return <div className="pc-drawer-answer">
    {reads > 0 && <button type="button" className="pc-drawer-steps" aria-expanded={open || working} onClick={() => setOpen((value) => !value)}>
      {working ? <LoaderCircle className="spin" size={13} /> : <ChevronRight size={13} className={open ? "open" : ""} />}
      {working ? t("Reading the plant…") : t("{count} reads of the plant", { count: reads })}
    </button>}
    {(open || working) && reads > 0 && <ol className="pc-drawer-step-list">{message.steps.map((step, index) => <li key={index} className={step.state}>{step.state === "error" ? <AlertTriangle size={12} /> : step.state === "ok" ? <Check size={12} /> : <LoaderCircle className="spin" size={12} />}<span><b>{t(step.title)}</b> {step.summary}</span></li>)}</ol>}
    {message.state === "failed" ? <div className="pc-drawer-failed"><AlertTriangle size={14} /> <span>{message.text || t("The answer was interrupted. Ask again.")}</span>
      {onRetry && <button type="button" className="pc-answer-retry" onClick={onRetry}><RotateCcw size={13} aria-hidden="true" />{t("Try again")}</button>}</div>
      : message.text && <div className={`pc-drawer-markdown${working ? " pc-answer-writing" : ""}`}>{renderMarkdown(message.text, { plainExternalLinks: true })}</div>}
    <AnswerProgress message={message} />
    {message.charts.map((chart, index) => <AssistantChart key={index} chart={chart} base={base} height={200} />)}
    {message.state === "done" && (message.meta?.proposals ?? []).map((proposal, index) => <ProposalCard key={index} base={base} chatId={chatId} messageId={message.message_id} index={index} proposal={proposal} />)}
    {message.state === "done" && message.meta?.model && <small className="pc-drawer-model">{message.meta.model}</small>}
  </div>;
}

/** The suite's own task, offered on every page after the page's: explaining the page. What else
 * fits a page is that page's own works (a generic "what needs attention" fits
 * no list of blocks). */
export function suiteTasks(): AssistantTask[] {
  return [
    { label: t("Explain this page"), hint: t("What it shows and what you can do here"), instructions: "Explain what this page shows and what the person can do on it, from the page's text and the suite's help. Be short; use the page's own words for its buttons and tabs." },
  ];
}

/** The tasks offered: the page's, then the suite's (unless the page has one with the same label). */
export function assistantTasks(request: AssistantRequest): AssistantTask[] {
  const own = [...(request.tasks ?? []), ...(request.suggestions ?? []).map((text) => ({ label: text, instructions: "" }))];
  const labels = new Set(own.map((task) => task.label));
  return [...own, ...suiteTasks().filter((task) => !labels.has(task.label))];
}

/** What the model gets as the place's context: the chosen task first, then the page. 4,000 characters at most.
 * A declared work's own context is built by PlantCraft; the page's text only follows it. */
export function taskContext(request: AssistantRequest, task: AssistantTask | null): string {
  if (task?.work) return (request.context ?? "").trim().slice(0, 4000);
  let extra = "";
  try { extra = task?.context?.() ?? ""; } catch { extra = ""; }
  const chosen = task ? [`The person chose: ${task.label}`, task.instructions && `What to do: ${task.instructions}`].filter(Boolean).join("\n") : "";
  return [chosen, extra.trim(), (request.context ?? "").trim()].filter(Boolean).join("\n\n").slice(0, 4000);
}

/** The person's chats for the panel; with the model off, the ones shared with them after. */
async function readChats(base: string | null | undefined, available: boolean): Promise<AssistantChatSummary[]> {
  try {
    const value = await call<{ chats?: AssistantChatSummary[]; shared?: AssistantChatSummary[] }>(base, "api/assistant");
    return available ? value.chats ?? [] : [...(value.chats ?? []), ...(value.shared ?? [])];
  } catch {
    return [];
  }
}

/** The list of earlier chats the panel opens (the rest are in Desk). */
function EarlierChats({ chats, base, opening, onOpen, label }: { chats: AssistantChatSummary[]; base: string | null | undefined; opening: boolean; onOpen: (id: number) => Promise<void>; label?: string }) {
  return <section className="pc-drawer-earlier" aria-label={t("Your chats")}>
    <h4>{t("Your chats")}</h4>
    {label && <p className="pc-drawer-note">{label}</p>}
    <ul>{chats.slice(0, PANEL_CHATS).map((item) => <li key={item.chat_id}>
      <button type="button" onClick={() => void onOpen(item.chat_id)} disabled={opening}>
        <strong>{item.title || t("Chat")}</strong>
        {(item.place || item.updated_at) && <small>{[item.place, item.updated_at ? formatDate(item.updated_at, { dateStyle: "short", timeStyle: "short" }) : ""].filter(Boolean).join(" · ")}</small>}
      </button>
    </li>)}</ul>
    {chats.length > PANEL_CHATS && <a className="pc-drawer-all" href={platformPath(base, "assistant")}>{t("All your chats in Desk")}</a>}
  </section>;
}

/** The panel: what the person wants (the page's tasks or their words), the conversation, and "Continue in Desk". */
export function AssistantDrawer({ request, onClose, leaving = false }: { request: AssistantRequest; onClose: () => void; leaving?: boolean }) {
  const base = request.platformUrl;
  const [status, setStatus] = useState<Status | null | undefined>(undefined);
  const [chatId, setChatId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [earlier, setEarlier] = useState<AssistantChatSummary[] | null>(null);
  const [opening, setOpening] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showContext, setShowContext] = useState(false);
  // The task chosen, waiting for the person's words when it asks for them.
  const [task, setTask] = useState<AssistantTask | null>(null);
  const [sent, setSent] = useState<{ context: string; task: AssistantTask | null } | null>(null);
  const [works, setWorks] = useState<AssistantWork[] | null>(request.page ? null : []);
  const tasks = [...(works ?? []).map(workTask), ...assistantTasks(request)];
  const preselected = useRef(false);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const prepared = useRef(request.prepare);
  const working = messages.some((item) => item.state === "working");

  useEffect(() => { void Promise.resolve(prepared.current?.()).catch(() => undefined); }, []);
  useEffect(() => { let alive = true; void assistantStatus(base).then((value) => alive && setStatus(value)); return () => { alive = false; }; }, [base]);
  useEffect(() => { input.current?.focus(); }, [status]);
  // The page's works, for this person (PlantCraft says which: by access level and installed apps).
  useEffect(() => {
    if (!status?.available || !request.page) return;
    let alive = true;
    void assistantWorks(base, request.page).then((found) => alive && setWorks(found));
    return () => { alive = false; };
  }, [base, status, request.page]);
  // The person's earlier chats, read each time the panel opens (newest first). With the model off
  // (a public demo) the chats shared with them too: reading them shows what the assistant does
  //.
  useEffect(() => {
    if (!status) return;
    let alive = true;
    void readChats(base, status.available).then((value) => alive && setEarlier(value));
    return () => { alive = false; };
  }, [base, status]);
  // Follow the answer being written.
  useEffect(() => {
    if (chatId === null || !working) return;
    const timer = window.setInterval(async () => {
      try {
        const view = await call<{ messages: Message[] }>(base, `api/assistant/chats/${chatId}`);
        setMessages((value) => merge(value, view.messages));
      } catch { /* the next poll tries again */ }
    }, DRAWER_POLL_MS);
    return () => window.clearInterval(timer);
  }, [base, chatId, working]);
  useEffect(() => { const box = scroller.current; if (box && typeof box.scrollTo === "function") box.scrollTo({ top: box.scrollHeight, behavior: "smooth" }); }, [messages]);

  const ask = useCallback(async (text: string, chosen: AssistantTask | null = null) => {
    const clean = text.trim();
    if (!clean || busy) return;
    setBusy(true); setError("");
    try {
      if (chatId === null) {
        const context = taskContext(request, chosen);
        if (chosen?.prepare) await chosen.prepare().catch(() => undefined);
        const page = request.page || request.facts || request.view ? { page: request.page ?? "", subject: request.subject ?? "", facts: request.facts ?? {}, view: request.view ?? {} } : undefined;
        const started = await call<{ chat: { chat_id: number }; messages: Message[] }>(base, "api/assistant/chats", { method: "POST", body: JSON.stringify({ text: clean, ref: chosen?.subject ?? request.subject ?? "", place: request.place ?? "", context, keep: true, ...(chosen?.work ? { work: chosen.work } : {}), page }) });
        setChatId(started.chat.chat_id);
        setMessages(started.messages);
        setSent({ context, task: chosen });
      } else {
        const asked = await call<{ messages: Message[] }>(base, `api/assistant/chats/${chatId}/messages`, { method: "POST", body: JSON.stringify({ text: clean }) });
        setMessages((value) => merge(value, asked.messages));
      }
      setDraft(""); setTask(null);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }, [base, busy, chatId, request]);

  /** The last question asked again after its answer failed. */
  async function retry() {
    if (chatId === null || busy) return;
    setBusy(true); setError("");
    try {
      const asked = await call<{ messages: Message[] }>(base, `api/assistant/chats/${chatId}/retry`, { method: "POST" });
      setMessages((value) => merge(value.filter((item) => item.state !== "failed"), asked.messages));
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  }

  /** A task asked at once, or kept beside the box until the person writes what it needs. */
  function choose(chosen: AssistantTask) {
    if (chosen.ask) { setTask(chosen); input.current?.focus(); return; }
    void ask(chosen.label, chosen);
  }
  // Picked from the menu beside the title: start with that work or task once the works are known.
  useEffect(() => {
    if (preselected.current || !status?.available || works === null || (!request.work && !request.task)) return;
    preselected.current = true;
    const found = tasks.find((item) => (request.work ? item.work === request.work : item.label === request.task));
    if (found) choose(found);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, works, request.work, request.task]);
  /** The person's words, with the task they complete. */
  function send() {
    if (task) void ask(`${task.label}: ${draft.trim()}`, task);
    else void ask(draft);
  }

  /** An earlier chat, read whole and continued here. */
  async function resume(id: number) {
    setOpening(true); setError("");
    try {
      const view = await call<{ messages: Message[] }>(base, `api/assistant/chats/${id}`);
      setChatId(id); setMessages(view.messages); setSent(null); setTask(null);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setOpening(false); }
  }
  /** Back to the start: the earlier chats and a new one about this page. */
  function fresh() {
    setChatId(null); setMessages([]); setSent(null); setTask(null); setDraft(""); setError(""); setEarlier(null);
    void readChats(base, Boolean(status?.available)).then(setEarlier);
  }
  function submit(event: FormEvent) { event.preventDefault(); send(); }
  function keys(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
  }

  const heading = request.title || request.place || t("This page");
  const hasContext = Boolean(request.place || request.context || request.subject);
  const inChat = chatId !== null;
  return <SidePanel label={t("Assistant")} subtitle={heading} icon={<Sparkles size={18} aria-hidden="true" />} leaving={leaving} className="pc-assistant-panel" onClose={onClose}
    fullHref={platformPath(base, inChat ? `assistant/${chatId}` : "assistant")}>
    {hasContext && !(inChat && !sent) && <div className="pc-drawer-context">
      <button type="button" aria-expanded={showContext} onClick={() => setShowContext((value) => !value)}><ChevronRight size={13} className={showContext ? "open" : ""} />{t("See the context")}</button>
      {showContext && <dl>
        {request.place && <div><dt>{t("Where")}</dt><dd>{request.place}</dd></div>}
        {request.subject && <div><dt>{t("About")}</dt><dd><code>{request.subject}</code></dd></div>}
        {(sent?.context ?? request.context) && <div><dt>{t("What the page tells the assistant")}</dt><dd className="pc-drawer-context-text">{sent?.context ?? request.context}</dd></div>}
      </dl>}
    </div>}
    <div className="pc-drawer-body" ref={scroller}>
      {status === undefined && <p className="pc-drawer-wait"><LoaderCircle className="spin" size={14} /> {t("Loading…")}</p>}
      {status === null && <p className="pc-drawer-failed"><AlertTriangle size={14} /> {t("The assistant could not be reached.")}</p>}
      {status && !status.available && !inChat && <div className="pc-drawer-off"><AssistantMark size={28} /><p>{status.reason}</p>
        {status.can_set_up ? <a className="pc-drawer-keep" href={platformPath(base, "setup/language-model")}><Settings2 size={14} aria-hidden="true" />{t("Set up the language model")}</a> : <small>{t("An administrator turns it on.")}</small>}
      </div>}
      {status && !status.available && !inChat && earlier && earlier.length > 0 && <EarlierChats chats={earlier} base={base} opening={opening} onOpen={resume} label={t("Read the chats kept here: each answer shows the steps the assistant took and its sources.")} />}
      {status?.available && !messages.length && <div className="pc-drawer-intro">
        <h3>{t("What do you want to do?")}</h3>
        <ul className="pc-drawer-tasks">{tasks.slice(0, 10).map((item) => <li key={item.work ?? item.label}>
          <button type="button" className={task === item ? "pc-on" : undefined} onClick={() => choose(item)} disabled={busy}>
            <strong>{item.label}{item.creates && <span className="pc-work-creates">{t("Creates")}</span>}</strong>{item.hint && <small>{item.hint}</small>}
          </button>
        </li>)}</ul>
        <p className="pc-drawer-note">{t("Or write what you want below. The assistant reads only what you may see, and changes nothing. Your chats are kept, only for you, in Desk's Assistant.")}</p>
        {earlier && earlier.length > 0 && <EarlierChats chats={earlier} base={base} opening={opening} onOpen={resume} />}
      </div>}
      {inChat && <button type="button" className="pc-drawer-back" onClick={fresh}><ArrowLeft size={13} aria-hidden="true" />{t("Your chats")}</button>}
      {messages.length > 0 && <ol className="pc-drawer-messages">{messages.map((message) => <li key={message.message_id} className={message.role === "user" ? "mine" : "theirs"}>
        {message.role === "user" ? <p className="pc-drawer-question">{message.text}</p> : <Answer message={message} base={base} chatId={chatId} onRetry={message === messages[messages.length - 1] && message.state === "failed" ? () => void retry() : undefined} />}
      </li>)}</ol>}
      {error && <p className="pc-drawer-failed"><AlertTriangle size={14} /> {error}</p>}
    </div>
    {status?.available && <form className="pc-drawer-composer" onSubmit={submit}>
      {task && <span className="pc-drawer-task">{task.label}<button type="button" onClick={() => setTask(null)} aria-label={t("Not this")}><X size={12} /></button></span>}
      <textarea ref={input} value={draft} rows={2} maxLength={8000} onChange={(event) => setDraft(event.target.value)} onKeyDown={keys} placeholder={task?.ask ?? (messages.length ? t("Ask a follow-up") : t("Write what you want"))} aria-label={t("Your question")} />
      <button type="submit" className="pc-drawer-send" disabled={busy || working || !draft.trim()} aria-label={t("Send")}>{busy ? <LoaderCircle className="spin" size={16} /> : <ArrowUp size={16} />}</button>
    </form>}
  </SidePanel>;
}

/** The assistant's button, the same at the top right of every page: opens
 * the panel about the page, or closes it. Hidden where models are forbidden. */
/** The assistant's button: in the sidebar's row of buttons above the person's name, in every app
 * (`variant="sidebar"`), or at the top of a page (`"top"`, older shells). */
export function AssistantTopButton({ platformUrl, page, variant = "top", collapsed = false, control }: { platformUrl?: string | null; page: () => AssistantRequest; variant?: "top" | "sidebar"; collapsed?: boolean; control?: { active: boolean; toggle: () => void } }) {
  const [state, setState] = useState<Status | null>(null);
  const local = useOpenAssistant();
  const open = control ? control.active : local;
  const described = useAssistantPlaceValue();
  useEffect(() => {
    let alive = true;
    void assistantStatus(platformUrl).then((value) => alive && setState(value));
    return () => { alive = false; };
  }, [platformUrl]);
  const offered = Boolean(state && state.allowed !== false);
  // Ready: a model answers. Until then the button stays, dimmed, saying why; an administrator's
  // click goes straight to Setup › Language models.
  const ready = Boolean(state?.available);
  // In the sidebar the button stays where people look for it, dimmed, saying why it is off
  // (models forbidden in the installation, the public demo); its panel says the same.
  if (!offered && !(variant === "sidebar" && state)) return null;
  const setUp = !ready && offered && Boolean(state?.can_set_up);
  function toggle() {
    if (setUp) { window.location.assign(platformPath(platformUrl, "setup/language-model")); return; }
    if (control) { control.toggle(); return; }
    if (open) { closeAssistant(); return; }
    const seen = page();
    openAssistant({ ...seen, ...described, context: described?.context ?? seen.context, platformUrl: described?.platformUrl ?? platformUrl });
  }
  const label = t("Assistant");
  const off = `${label}: ${state?.reason || t("Language models are turned off in this installation.")}${setUp ? ` ${t("Click to set it up.")}` : ""}`;
  if (variant === "sidebar") {
    const hint = ready ? (collapsed ? label : t("Ask the assistant about this page")) : off;
    return <button type="button" className={`pcs-quick-button${open ? " pcs-active" : ""}${ready ? "" : " pcs-quick-off"}`} onClick={toggle} aria-pressed={Boolean(open)} aria-label={hint} title={hint} data-tour="assistant-button">
      <Sparkles size={18} aria-hidden="true" />
    </button>;
  }
  const hint = ready ? t("Ask the assistant about this page") : off;
  return <button type="button" className={`pcs-assistant-top${open ? " pcs-on" : ""}${ready ? "" : " pcs-quick-off"}`} onClick={toggle} aria-pressed={Boolean(open)} aria-label={hint} title={hint}>
    <AssistantMark size={18} />
    <span>{label}</span>
  </button>;
}

/** What a page shows, as the assistant's context: its text as the person sees it, cut. */
export function pageContext(root: Element | null, limit = 3000): string {
  const text = ((root instanceof HTMLElement ? root.innerText : undefined) ?? root?.textContent ?? "").replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n").trim();
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

// The shell's view of the page, set while an `AssistantHost` is drawn: the button beside a page's
// title opens the same panel as the sidebar's, so it needs what the shell knows (place, platform).
type PageSource = { page: () => AssistantRequest; platformUrl?: string | null };
let pageSource: PageSource | null = null;
const getPageSource = () => pageSource;

/** Open the panel about the page as it is now: the page's own description (`useAssistantPage`)
 * over what the shell reads from the screen. The button beside a title and the sidebar's do this. */
export function openPageAssistant(start: Pick<AssistantRequest, "work" | "task"> = {}) {
  const source = pageSource;
  const seen = source?.page() ?? {};
  const described = place;
  openAssistant({ ...seen, ...described, ...start, context: described?.context ?? seen.context, platformUrl: described?.platformUrl ?? source?.platformUrl });
}

/**
 * The assistant's button beside a page's title (round 9): the same mark on every
 * page. It opens a menu of what the assistant does here (the page's works, then its tasks); the
 * person picks one and the panel opens on it, its context loaded, or asks something else.
 * `Heading` draws it, so every page of every app has it in the same place. It shows only where the
 * shell draws the panel and the installation offers a model; until a model answers it stays dimmed,
 * saying why, and an administrator's click goes to Setup › Language models.
 */
export function AssistantTitleButton() {
  const source = useSyncExternalStore(subscribe, getPageSource, () => null);
  const open = useOpenAssistant() !== null;
  const described = useAssistantPlaceValue();
  const [state, setState] = useState<Status | null>(null);
  const [menu, setMenu] = useState(false);
  const [works, setWorks] = useState<AssistantWork[] | null>(null);
  const box = useRef<HTMLSpanElement>(null);
  const platformUrl = described?.platformUrl ?? source?.platformUrl;
  const close = useCallback(() => setMenu(false), []);
  useDismiss(menu, close, box);
  // The menu opens under the button and stays inside the screen: on a phone a page with a long
  // title puts the button near the right edge, and a menu past it widens the page.
  // It sizes and places the menu against the visible width (clientWidth: a phone's innerWidth and
  // 100vw grow with anything wider than the screen), again when the works arrive.
  const panel = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const node = panel.current;
    if (!menu || !node || !box.current) return;
    const screen = document.documentElement.clientWidth || window.innerWidth;
    const width = Math.min(340, screen - 32);
    node.style.width = `${width}px`;
    const left = box.current.getBoundingClientRect().left;
    node.style.left = `${Math.max(16 - left, Math.min(0, screen - 16 - left - width))}px`;
  }, [menu, works]);
  useEffect(() => {
    if (!source) return;
    let alive = true;
    void assistantStatus(platformUrl).then((value) => alive && setState(value));
    return () => { alive = false; };
  }, [Boolean(source), platformUrl]);
  // A public demo shows it too: the menu lists what it does on this page, to read.
  const demo = Boolean(state?.demo);
  if (!source || !state || (state.allowed === false && !demo)) return null;
  const ready = Boolean(state.available);
  const setUp = !ready && Boolean(state.can_set_up);
  const hint = ready ? t("Ask the assistant about this page")
    : `${t("Assistant")}: ${state.reason || t("Language models are turned off in this installation.")}${setUp ? ` ${t("Click to set it up.")}` : ""}`;
  function toggle() {
    if (setUp) { window.location.assign(platformPath(platformUrl, "setup/language-model")); return; }
    if (open) { closeAssistant(); return; }
    if (!ready && !demo) { openPageAssistant(); return; }
    if (menu) { setMenu(false); return; }
    setMenu(true); setWorks(null);
    void assistantWorks(platformUrl, described?.page).then(setWorks);
  }
  // In the demo a pick opens the panel on the team's chats: nothing is asked.
  function start(begin: Pick<AssistantRequest, "work" | "task">) { setMenu(false); openPageAssistant(ready ? begin : {}); }
  const tasks = assistantTasks(described ?? {});
  return <span className="pc-title-assistant-box" ref={box}>
    <button type="button" className={`pc-title-assistant${open || menu ? " pc-on" : ""}${ready ? "" : " pc-off"}`} onClick={toggle} aria-pressed={open} aria-expanded={ready || demo ? menu : undefined} aria-haspopup={ready || demo ? "menu" : undefined} aria-label={hint} title={hint} data-tour="assistant-title">
      <AssistantMark size={20} />
    </button>
    {menu && <div className="pc-title-assistant-menu" ref={panel} role="menu" aria-label={t("What the assistant does here")}>
      <h4>{t("What the assistant does here")}</h4>
      {demo && <p className="pc-drawer-note">{t("In this public demo it does not answer: these are what you could ask on this page. Pick one to read the team's chats.")}</p>}
      {works === null && described?.page && <p className="pc-drawer-wait"><LoaderCircle className="spin" size={13} /> {t("Loading…")}</p>}
      {(works ?? []).map((work) => <button key={work.key} type="button" role="menuitem" onClick={() => start({ work: work.key })}>
        <strong>{work.title}{work.kind === "create" && <span className="pc-work-creates">{t("Creates")}</span>}</strong>{work.hint && <small>{work.hint}</small>}
      </button>)}
      {tasks.slice(0, 8).map((task) => <button key={task.label} type="button" role="menuitem" onClick={() => start({ task: task.label })}>
        <strong>{task.label}</strong>{task.hint && <small>{task.hint}</small>}
      </button>)}
      <button type="button" role="menuitem" className="pc-title-assistant-own" onClick={() => start({})}><Sparkles size={13} aria-hidden="true" />{demo ? t("Read the team's chats") : t("Ask something else")}</button>
    </div>}
  </span>;
}

/** The panel for the whole page, opened by the button at the top or by a page's own code. */
export function AssistantHost({ platformUrl, page }: { platformUrl?: string | null; page: () => AssistantRequest }) {
  const latestPage = useRef(page);
  latestPage.current = page;
  useEffect(() => {
    const mine: PageSource = { page: () => latestPage.current(), platformUrl };
    pageSource = mine;
    emit();
    return () => { if (pageSource === mine) { pageSource = null; emit(); } };
  }, [platformUrl]);
  const { value: open, leaving } = usePresence(useOpenAssistant());
  const close = useCallback(() => closeAssistant(), []);
  if (!open) return null;
  return <AssistantDrawer key={JSON.stringify(open)} request={{ place: open.place ?? page().place, ...open, platformUrl: open.platformUrl ?? platformUrl }} onClose={close} leaving={leaving} />;
}
