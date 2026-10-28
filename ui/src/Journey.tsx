/**
 * The way through the suite: a path of four steps on a page's first screen (where to start and
 * what is done), the next pages at the bottom of a page, and the follow-up of an asset (the
 * actions about it, from PlantCraft's API v1). Their styles are in base.css.
 */
import { ArrowRight, Check, ChevronDown, ChevronRight, ClipboardList, Plus } from "lucide-react";
import { useEffect, useState, type MouseEvent, type ReactNode } from "react";
import { Pill } from "./Blocks.js";
import { t, uiLocale } from "./i18n.js";

/** done: nothing to do here now; next: the step to take; todo: comes later; info: always open. */
export type JourneyState = "done" | "next" | "todo" | "info";

/** A step or a next page: `to` is a page of this app (href/navigate), `url` a page elsewhere. */
export type JourneyStep = {
  title: ReactNode;
  /** One line: why this step, or what it found. */
  detail?: ReactNode;
  /** The number that matters at this step, with its label. */
  value?: ReactNode;
  valueLabel?: ReactNode;
  state?: JourneyState;
  to?: string;
  url?: string;
  /** The link's words ("Open the loop"). */
  cta?: ReactNode;
};

type Links = { href?: (to: string) => string; navigate?: (to: string) => void };

function StepLink({ step, href, navigate, className, children }: Links & { step: JourneyStep; className: string; children: ReactNode }) {
  const target = step.url ?? (step.to !== undefined ? (href ? href(step.to) : step.to) : undefined);
  if (!target) return <div className={className}>{children}</div>;
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (step.url || step.to === undefined || !navigate || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    navigate(step.to);
  }
  return <a href={target} className={className} onClick={follow}>{children}</a>;
}

/** The first step not done is the next one, unless a step says otherwise. */
export function journeyStates(steps: JourneyStep[]): JourneyState[] {
  let found = steps.some((step) => step.state === "next");
  return steps.map((step) => {
    if (step.state) return step.state;
    if (found) return "todo";
    found = true;
    return "next";
  });
}

/** Where a person's choice to fold a path is kept: one key per page (the app's path in the address). */
export function journeyKey(storageKey?: string): string {
  const where = storageKey ?? (typeof window === "undefined" ? "" : window.location.pathname);
  return `pc-journey:${where}`;
}

function readFolded(key: string): boolean | null {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? null : value === "folded";
  } catch {
    return null;
  }
}

function writeFolded(key: string, folded: boolean) {
  try {
    window.localStorage.setItem(key, folded ? "folded" : "open");
  } catch {
    // Private windows and blocked storage: the choice lasts until the page is left.
  }
}

/**
 * Whether a path starts folded: the person's own choice when they made one, else folded once
 * every step is done (the path has nothing left to teach) and open while one is still to do.
 */
export function journeyFolded(states: JourneyState[], choice: boolean | null): boolean {
  if (choice !== null) return choice;
  return states.length > 0 && states.every((state) => state === "done" || state === "info");
}

/**
 * A path of up to four numbered steps on the page grid: done ones carry a check, the next one is
 * highlighted. Steps without a state are filled in by journeyStates(). The person can fold it to
 * one line ("Hide"), and the choice is kept in this browser for the page (`storageKey`, default the
 * address); a path whose steps are all done starts folded.
 */
export function JourneyPath({ title, detail, steps, href, navigate, label, storageKey }: Links & { title?: ReactNode; detail?: ReactNode; steps: JourneyStep[]; label?: string; storageKey?: string }) {
  const states = journeyStates(steps);
  const key = journeyKey(storageKey);
  const [choice, setChoice] = useState<boolean | null>(() => readFolded(key));
  const folded = journeyFolded(states, choice);
  const shown = steps.slice(0, 4);
  const done = states.slice(0, 4).filter((state) => state === "done").length;
  function toggle() {
    writeFolded(key, !folded);
    setChoice(!folded);
  }
  const heading = title ?? label ?? t("Where to start");
  if (folded) {
    return (
      <section className="pc-journey pc-journey-folded" aria-label={label ?? t("Where to start")}>
        <button type="button" className="pc-journey-toggle" onClick={toggle} aria-expanded={false}>
          <ChevronRight size={16} aria-hidden="true" />
          <span className="pc-journey-toggle-title">{heading}</span>
          <small>{t("{done} of {total} steps done", { done, total: shown.length })} · {t("Show")}</small>
        </button>
      </section>
    );
  }
  return (
    <section className="pc-journey" aria-label={label ?? t("Where to start")}>
      <div className="pc-journey-head">
        <div>{title && <h2>{title}</h2>}{detail && <p>{detail}</p>}</div>
        <button type="button" className="pc-journey-hide" onClick={toggle} aria-expanded={true}>
          <ChevronDown size={14} aria-hidden="true" />{t("Hide")}
        </button>
      </div>
      <ol className="pc-grid">
        {shown.map((step, index) => {
          const state = states[index];
          return (
            <li key={index} className={`pc-journey-step pc-journey-${state}`} aria-current={state === "next" ? "step" : undefined}>
              <StepLink step={step} href={href} navigate={navigate} className="pc-journey-card">
                <span className="pc-journey-mark" aria-hidden="true">{state === "done" ? <Check size={14} /> : index + 1}</span>
                <span className="pc-journey-text">
                  <strong>{step.title}</strong>
                  {step.detail && <small>{step.detail}</small>}
                </span>
                {step.value !== undefined && <span className="pc-journey-value"><b className="pc-num">{step.value}</b>{step.valueLabel && <small>{step.valueLabel}</small>}</span>}
                {(step.to !== undefined || step.url) && <span className="pc-journey-cta">{step.cta ?? t("Open")} <ArrowRight size={14} /></span>}
                <span className="sr-only">{state === "done" ? t("Done") : state === "next" ? t("Next step") : ""}</span>
              </StepLink>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** The bottom of a page: where to go from here (up to four pages, one row of the grid; `limit`
 * for a page whose links are its content, like Setup). */
export function NextSteps({ title, items, href, navigate, limit = 4 }: Links & { title?: ReactNode; items: JourneyStep[]; limit?: number }) {
  const shown = items.filter((item) => item.to !== undefined || item.url).slice(0, limit);
  if (!shown.length) return null;
  return (
    <nav className="pc-next" aria-label={t("Next steps")}>
      <h2 className="section-title">{title ?? t("Next steps")}</h2>
      <div className="pc-grid">
        {shown.map((item, index) => (
          <StepLink key={index} step={item} href={href} navigate={navigate} className="panel card pc-next-card">
            <strong>{item.title}</strong>
            {item.detail && <p>{item.detail}</p>}
            <span className="pc-journey-cta">{item.cta ?? t("Open")} <ArrowRight size={14} /></span>
          </StepLink>
        ))}
      </div>
    </nav>
  );
}

/** GET /api/v1/actions: an action as the follow-up panel shows it. */
export type FollowUpAction = {
  action_id: number;
  title: string;
  status: string;
  status_label?: string;
  priority: string;
  priority_label?: string;
  owner_name?: string | null;
  due_at?: string | null;
  overdue?: boolean;
  updated_at?: string | null;
  completed_at?: string | null;
};

/** The statuses of an action still to do. */
export const OPEN_ACTION_STATUSES = ["open", "in_progress", "blocked"];
const OPEN = new Set(OPEN_ACTION_STATUSES);
const TONE: Record<string, string> = { open: "warning", in_progress: "running", blocked: "alarm", done: "ok", cancelled: "cancelled" };

/** A due date ("2026-10-22") as the person reads dates: a day, not an instant (utc-day). */
function dueDate(value: string): string {
  const stamp = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(stamp.getTime()) ? value : stamp.toLocaleDateString(uiLocale(), { dateStyle: "medium", timeZone: "UTC" });
}

/** The actions about `ref` (all when null), of the given statuses; null when PlantCraft has none
 * to give (an older version, 401, 403). */
export async function fetchActions(ref: string | null, options: { status?: string[]; limit?: number } = {}): Promise<FollowUpAction[] | null> {
  const query = new URLSearchParams();
  if (ref) query.set("ref", ref);
  for (const status of options.status ?? []) query.append("status", status);
  if (options.limit) query.set("limit", String(options.limit));
  try {
    const response = await fetch(`/api/v1/actions${query.size ? `?${query.toString()}` : ""}`, { credentials: "same-origin" });
    if (!response.ok) return null;
    const data = (await response.json()) as { items?: FollowUpAction[] } | null;
    return Array.isArray(data?.items) ? data.items : null;
  } catch {
    return null;
  }
}

/** PlantCraft's address joined with a path of its own ("/" + "actions" -> "/actions"). */
export function platformPath(base: string | null | undefined, path: string): string {
  const root = (base || "/").replace(/\/+$/, "");
  return `${root}/${path.replace(/^\/+/, "")}`;
}

/** The new-action form of PlantCraft, filled in with the asset and a title. */
export function newActionUrl(base: string | null | undefined, ref: string, title: string): string {
  return `${platformPath(base, "actions")}?${new URLSearchParams({ new: "1", ref, title }).toString()}`;
}

/** The open actions first, then the last three closed. */
export function followUpRows(items: FollowUpAction[]): { open: FollowUpAction[]; closed: FollowUpAction[]; closedTotal: number } {
  const open = items.filter((item) => OPEN.has(item.status));
  const closed = items.filter((item) => !OPEN.has(item.status)).sort((a, b) => String(b.completed_at ?? b.updated_at ?? "").localeCompare(String(a.completed_at ?? a.updated_at ?? "")));
  return { open, closed: closed.slice(0, 3), closedTotal: closed.length };
}

/**
 * The follow-up of an asset: what was decided about it (PlantCraft's actions that reference
 * it), with a button to open a new one. Hidden when PlantCraft cannot answer.
 */
export function FollowUp({ subject, newTitle, platformUrl, canCreate, detail }: { subject: string; newTitle: string; platformUrl?: string | null; canCreate?: boolean; detail?: ReactNode }) {
  const [items, setItems] = useState<FollowUpAction[] | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    void fetchActions(subject).then((value) => { if (live) setItems(value); });
    return () => { live = false; };
  }, [subject]);
  if (items === null) return null;
  const rows = items ? followUpRows(items) : null;
  const shown = rows ? [...rows.open, ...rows.closed] : [];
  return (
    <section className="panel pc-follow-up" aria-label={t("Follow-up")}>
      <div className="panel-header">
        <div><h2>{t("Follow-up")}</h2><p>{detail ?? t("The actions decided about this asset, in PlantCraft.")}</p></div>
        {canCreate && <a className="button button-secondary button-small" href={newActionUrl(platformUrl, subject, newTitle)}><Plus size={14} />{t("New action")}</a>}
      </div>
      {items === undefined
        ? <p className="muted">{t("Loading…")}</p>
        : shown.length === 0
          ? <p className="muted pc-follow-up-empty"><ClipboardList size={16} aria-hidden="true" />{t("No action yet. When a finding needs someone to act, open an action: it gets an owner and a due date, and shows here.")}</p>
          : <ul className="pc-follow-up-list">{shown.map((item) => (
            <li key={item.action_id}>
              <a href={platformPath(platformUrl, `actions/${item.action_id}`)}>
                <Pill status={TONE[item.status] ?? "unknown"} label={item.status_label ?? item.status} />
                <span className="pc-follow-up-title"><b>{item.title}</b><small>{[item.owner_name, item.due_at && OPEN.has(item.status) ? (item.overdue ? t("overdue since {date}", { date: dueDate(item.due_at) }) : t("due {date}", { date: dueDate(item.due_at) })) : null].filter(Boolean).join(" · ") || t("No owner yet")}</small></span>
              </a>
            </li>
          ))}</ul>}
      {rows && rows.closedTotal > rows.closed.length && <p className="muted small">{t("{count} more closed actions in PlantCraft.", { count: rows.closedTotal - rows.closed.length })}</p>}
    </section>
  );
}
