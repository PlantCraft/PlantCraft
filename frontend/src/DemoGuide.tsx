/** The demo's guide by role (demoGuides.ts): the picker ("What do you do?") and the card that walks
 * the visitor through their stops. The card is the frame's, above the apps, so one guide goes from
 * app to app; it stays in this tab (sessionStorage) across reloads, and may be folded away. */
import { useEffect, useState, useSyncExternalStore } from "react";
import { ArrowLeft, ArrowRight, Briefcase, Check, ChevronDown, ChevronUp, Compass, Gauge, LineChart, ShieldCheck, SlidersHorizontal, Wrench, X } from "lucide-react";
import { TOURS_OFF_KEY } from "@plantcraft/ui";
import { requestJson } from "./api";
import { demoGuides, guideById, stopHref, type Guide, type GuideId } from "./demoGuides";
import { t } from "./i18n";
import { navigate } from "./nav";

const KEY = "processcraft:demo-guide";
/** What the tours' switch was before a guide turned it on (a guide and a tour never show together). */
const TOURS_KEY = "processcraft:demo-guide-tours";
const CHANGED = "processcraft:demo-guide-changed";

/** `opened`: the stop whose page the guide opened already (a reload does not open it again). */
export type GuideState = { guide: GuideId; step: number; folded: boolean; opened?: number; picking?: false } | { picking: true };

function storage(kind: "session" | "local"): Storage | null {
  try { return kind === "session" ? window.sessionStorage : window.localStorage; } catch { return null; }
}

function read(): GuideState | null {
  try {
    const value = JSON.parse(storage("session")?.getItem(KEY) ?? "null") as GuideState | null;
    if (value && "picking" in value && value.picking) return value;
    return value && guideById((value as { guide: string }).guide) ? value : null;
  } catch {
    return null;
  }
}

let current: GuideState | null = typeof window === "undefined" ? null : read();

function write(next: GuideState | null) {
  current = next;
  const session = storage("session");
  const local = storage("local");
  try {
    if (next && !next.picking) {
      // The apps' own tours wait while a guide is on: put back what was there when it ends.
      if (session && local && session.getItem(TOURS_KEY) === null) session.setItem(TOURS_KEY, local.getItem(TOURS_OFF_KEY) ?? "");
      local?.setItem(TOURS_OFF_KEY, "1");
    } else if (!next && session && local) {
      const before = session.getItem(TOURS_KEY);
      if (before !== null) {
        if (before) local.setItem(TOURS_OFF_KEY, before); else local.removeItem(TOURS_OFF_KEY);
        session.removeItem(TOURS_KEY);
      }
    }
    if (next) session?.setItem(KEY, JSON.stringify(next)); else session?.removeItem(KEY);
  } catch {
    // Private mode: the guide lasts as long as the page.
  }
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(listener: () => void) {
  window.addEventListener(CHANGED, listener);
  return () => window.removeEventListener(CHANGED, listener);
}

export function useGuideState(): GuideState | null {
  return useSyncExternalStore(subscribe, () => current, () => null);
}

/** Start the guide `id` (from its first stop), or none. */
export function startGuide(id: GuideId | null) {
  write(id ? { guide: id, step: 0, folded: false } : null);
}

/** Open the picker over the current screen. */
export function pickGuide() {
  write({ picking: true });
}

const ICONS: Record<GuideId, typeof Gauge> = {
  operator: Gauge,
  process: LineChart,
  control: SlidersHorizontal,
  maintenance: Wrench,
  manager: Briefcase,
  it: ShieldCheck,
};

/** The roles as choices: on the sign-in page's demo card, and in the picker. */
export function GuideChoices({ value, onPick, explore = true }: { value: GuideId | null; onPick: (id: GuideId | null) => void; explore?: boolean }) {
  const guides = demoGuides();
  return <div className="demo-guide-choices" role="radiogroup" aria-label={t("What do you do?")}>
    {guides.map((guide) => {
      const Icon = ICONS[guide.id];
      return <button key={guide.id} type="button" role="radio" aria-checked={value === guide.id} className={value === guide.id ? "active" : ""} onClick={() => onPick(guide.id)} title={guide.pitch}>
        <Icon size={16} aria-hidden="true" /><span>{guide.label}</span>
      </button>;
    })}
    {explore && <button type="button" role="radio" aria-checked={value === null} className={`demo-guide-explore${value === null ? " active" : ""}`} onClick={() => onPick(null)}>
      <Compass size={16} aria-hidden="true" /><span>{t("Just look around")}</span>
    </button>}
  </div>;
}

/** The pages the story's names open here; null until known (a stop waits for them to open its page). */
function useGuideLinks(): Record<string, string> | null {
  const [links, setLinks] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    requestJson<{ links: Record<string, string> }>("/api/demo/guides").then((answer) => setLinks(answer.links ?? {}), () => setLinks({}));
  }, []);
  return links;
}

/** The picker or the guide's card, whichever is on; nothing otherwise. */
export function DemoGuide() {
  const state = useGuideState();
  if (!state) return null;
  if (state.picking) return <GuidePicker />;
  const guide = guideById(state.guide);
  return guide ? <GuideCard guide={guide} step={Math.min(state.step, guide.stops.length - 1)} folded={state.folded} opened={state.opened} /> : null;
}

function GuidePicker() {
  useEffect(() => {
    const keys = (event: KeyboardEvent) => { if (event.key === "Escape") write(null); };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  }, []);
  return <div className="demo-guide-scrim" onClick={() => write(null)}>
    <div className="demo-guide-picker" role="dialog" aria-modal="true" aria-labelledby="demo-guide-pick" onClick={(event) => event.stopPropagation()}>
      <header>
        <h2 id="demo-guide-pick">{t("What do you do?")}</h2>
        <button type="button" className="demo-guide-icon" onClick={() => write(null)} aria-label={t("Close")} title={t("Close")}><X size={16} /></button>
      </header>
      <p>{t("Pick your role: a short guide opens the screens that matter most to it, across the apps.")}</p>
      <GuideChoices value={null} explore={false} onPick={(id) => startGuide(id)} />
    </div>
  </div>;
}

function GuideCard({ guide, step, folded, opened }: { guide: Guide; step: number; folded: boolean; opened?: number }) {
  const links = useGuideLinks();
  const stop = guide.stops[step];
  const last = step >= guide.stops.length - 1;
  const Icon = ICONS[guide.id];
  // Each stop opens its page once, when it is reached: the visitor may wander from there.
  useEffect(() => {
    if (links === null || opened === step) return;
    const href = stopHref(stop, links);
    if (`${window.location.pathname}${window.location.search}` !== href) navigate(href);
    write({ guide: guide.id, step, folded, opened: step });
  }, [links, opened, step, stop, guide.id, folded]);
  const go = (to: number) => write({ guide: guide.id, step: to, folded: false, opened: to === step ? opened : undefined });
  if (folded) {
    return <button type="button" className="demo-guide-pill" onClick={() => go(step)} aria-label={t("Open the guide")}>
      <Icon size={15} aria-hidden="true" /><span>{guide.label}</span><small>{step + 1}/{guide.stops.length}</small><ChevronUp size={15} aria-hidden="true" />
    </button>;
  }
  return <aside className="demo-guide-card" aria-labelledby="demo-guide-title" data-guide={guide.id} data-step={step + 1}>
    <header>
      <span className="demo-guide-role"><Icon size={15} aria-hidden="true" />{guide.label}</span>
      <span className="demo-guide-count">{t("{n} of {total}", { n: step + 1, total: guide.stops.length })}</span>
      <button type="button" className="demo-guide-icon" onClick={() => write({ guide: guide.id, step, folded: true, opened })} aria-label={t("Fold the guide")} title={t("Fold the guide")}><ChevronDown size={16} /></button>
      <button type="button" className="demo-guide-icon" onClick={() => write(null)} aria-label={t("Close the guide")} title={t("Close the guide")}><X size={16} /></button>
    </header>
    <div className="demo-guide-progress" aria-hidden="true"><span style={{ width: `${((step + 1) / guide.stops.length) * 100}%` }} /></div>
    <h2 id="demo-guide-title">{stop.title}</h2>
    <p>{stop.body}</p>
    {last && <p className="demo-guide-end">{t("That is the guide. Look around as long as you like, or take another role's guide.")}</p>}
    <footer>
      <button type="button" className="demo-guide-other" onClick={pickGuide}>{t("Another role")}</button>
      <span>
        {step > 0 && <button type="button" className="button button-secondary" onClick={() => go(step - 1)}><ArrowLeft size={15} /> {t("Back")}</button>}
        {last
          ? <button type="button" className="button button-primary" onClick={() => write(null)}><Check size={15} /> {t("Finish")}</button>
          : <button type="button" className="button button-primary" onClick={() => go(step + 1)}>{t("Next")} <ArrowRight size={15} /></button>}
      </span>
    </footer>
  </aside>;
}
