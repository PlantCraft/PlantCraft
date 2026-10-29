/**
 * The guided tour: a card that walks a first visitor through an app, one step at a time. A step
 * may open a page of the app (`path`) and point at something on it (`target`, a CSS selector);
 * the rest of the screen dims. Each app's tour opens by itself the first time the person opens
 * the app in this browser, and again from the user menu ("Take the tour"). The card has its own
 * language picker (tourLanguage.ts): tour texts go through `tt()`, not the interface's `t()`.
 */
import { ArrowLeft, ArrowRight, Check, Languages, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { AnyAppId } from "./appMarks.js";
import { assistantStatus } from "./AssistantDrawer.js";
import { AppMark } from "./Brand.js";
import { translationsOn } from "./i18n.js";
import { setTourLanguage, TOUR_LANGUAGES, tt, useTourLanguage, type TourLanguage } from "./tourLanguage.js";

export type TourStep = {
  /** App path the step shows; the tour opens it first. */
  path?: string;
  /** CSS selector of what the step points at; left out, the card sits in the middle. */
  target?: string;
  /** Already translated, with `tt()`. */
  title: string;
  body: ReactNode;
  /** Runs once the step shows (opens a panel, a menu); what it returns runs when the step goes. */
  onShow?: () => void | (() => void);
};

const PREFIX = "plantcraft-ui:tour:";
/** Set to "1" to never open a tour by itself (browser tests, kiosks). */
export const TOURS_OFF_KEY = "plantcraft-ui:tours-off";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Private mode: the tour shows again next time.
  }
}

/** Whether the tour `id` should open by itself: not seen in this browser and tours not switched off. */
export function tourDue(id: string): boolean {
  return read(TOURS_OFF_KEY) !== "1" && read(PREFIX + id) !== "done";
}

export function markTourSeen(id: string) {
  write(PREFIX + id, "done");
}

export function resetTour(id: string) {
  write(PREFIX + id, null);
}

/** The page a tour step opens, or null to stay. The first step never leaves the page the person
 * opened: a tour that opens by itself on a link someone followed (a message, an alarm) shows its
 * welcome there, and moves only once the person goes on. */
export function tourPageFor(index: number, stepPath: string | undefined, current: string): string | null {
  if (index === 0 || !stepPath || stepPath === current) return null;
  return stepPath;
}

type Box = { top: number; left: number; width: number; height: number };

const CARD_WIDTH = 380;
const GAP = 14;
const PAD = 6;
const FIND_FOR_MS = 3000;
/** How long a step's ``openPanel`` waits for its button to be drawn. */
const WAIT_FOR_BUTTON_MS = 8000;

/** Where the card goes: beside the target if there is room, else below or above it, else centred. */
function cardPlace(box: Box | null, card: { width: number; height: number }): CSSProperties {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  if (!box || vw < 640) return {};
  const fitsY = (top: number) => Math.min(Math.max(top, 16), vh - card.height - 16);
  const fitsX = (left: number) => Math.min(Math.max(left, 16), vw - card.width - 16);
  if (box.left + box.width + GAP + card.width + 16 <= vw) return { top: fitsY(box.top), left: box.left + box.width + GAP };
  if (box.left - GAP - card.width >= 16) return { top: fitsY(box.top), left: box.left - GAP - card.width };
  if (box.top + box.height + GAP + card.height + 16 <= vh) return { top: box.top + box.height + GAP, left: fitsX(box.left) };
  if (box.top - GAP - card.height >= 16) return { top: box.top - GAP - card.height, left: fitsX(box.left) };
  return {};
}

function visibleBox(element: Element | null): Box | null {
  if (!element) return null;
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  // A target taller than the screen is outlined where it shows.
  const top = Math.max(rect.top, 8);
  const bottom = Math.min(rect.bottom, window.innerHeight - 8);
  if (bottom <= top) return null;
  return { top: top - PAD, left: rect.left - PAD, width: rect.width + 2 * PAD, height: bottom - top + 2 * PAD };
}

export type GuidedTourProps = {
  app: AnyAppId;
  steps: TourStep[];
  /** The current app path, and client navigation to another. */
  path: string;
  navigate: (to: string) => void;
  /** Called when the tour ends: finished (true) or skipped (false). */
  onClose: (finished: boolean) => void;
};

export function GuidedTour({ app, steps, path, navigate, onClose }: GuidedTourProps) {
  const language = useTourLanguage();
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const [cardSize, setCardSize] = useState({ width: CARD_WIDTH, height: 240 });
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[Math.min(index, steps.length - 1)];
  const last = index >= steps.length - 1;

  // Open the step's page (once per step: a page that redirects is left alone).
  const pathRef = useRef(path);
  pathRef.current = path;
  const stepPath = step?.path;
  useEffect(() => {
    const to = tourPageFor(index, stepPath, pathRef.current);
    if (to) navigate(to);
  }, [index, stepPath, navigate]);

  // What the step opens on its page, once that page has drawn. Once per step: steps rebuilt while
  // it shows (a panel that marks notifications read reloads the page's data) must not close and
  // reopen what it opened.
  const onShowRef = useRef(step?.onShow);
  onShowRef.current = step?.onShow;
  useEffect(() => {
    let undo: void | (() => void);
    const timer = window.setTimeout(() => { undo = onShowRef.current?.(); }, 700);
    return () => {
      window.clearTimeout(timer);
      if (typeof undo === "function") undo();
    };
  }, [index]);

  // Find the target (pages load their data first), bring it into view and follow it.
  const selector = step?.target;
  useEffect(() => {
    setBox(null);
    if (!selector) return;
    const started = Date.now();
    let scrolled = false;
    const measure = () => {
      const element = document.querySelector(selector);
      if (element && !scrolled) {
        scrolled = true;
        phoneMenu(element);
        element.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      }
      const found = visibleBox(element);
      setBox((now) => (now && found && now.top === found.top && now.left === found.left && now.width === found.width && now.height === found.height ? now : found));
    };
    measure();
    const timer = window.setInterval(() => {
      if (Date.now() - started > FIND_FOR_MS && !document.querySelector(selector)) return;
      measure();
    }, 150);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [index, selector]);

  useLayoutEffect(() => {
    const card = cardRef.current;
    if (card) setCardSize({ width: card.offsetWidth, height: card.offsetHeight });
  }, [index, box]);

  useEffect(() => {
    nextRef.current?.focus({ preventScroll: true });
  }, [index]);

  const go = useCallback((to: number) => {
    if (to < 0) return;
    if (to >= steps.length) onClose(true);
    else setIndex(to);
  }, [steps.length, onClose]);

  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose(false);
      else if (event.key === "ArrowRight") go(index + 1);
      else if (event.key === "ArrowLeft") go(index - 1);
    };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  }, [index, go, onClose]);

  if (!step) return null;
  const place = cardPlace(box, cardSize);
  const centred = !("top" in place);
  return (
    <div className="pct-tour" data-step={index + 1}>
      <div className={`pct-blocker${box ? "" : " pct-dim"}`} onClick={(event) => event.stopPropagation()} />
      {box && <div className="pct-spot" style={{ top: box.top, left: box.left, width: box.width, height: box.height }} aria-hidden="true" />}
      <div ref={cardRef} className={`pct-card${centred ? " pct-centred" : ""}`} style={place} role="dialog" aria-modal="true" aria-labelledby="pct-title" aria-describedby="pct-body">
        <header>
          <AppMark app={app} size={26} />
          <span className="pct-count">{tt("Step {n} of {total}", { n: index + 1, total: steps.length })}</span>
          {translationsOn() && <label className="pct-language" title={tt("Tour language")}>
            <Languages size={15} aria-hidden="true" />
            <select value={language} onChange={(event) => setTourLanguage(event.target.value as TourLanguage)} aria-label={tt("Tour language")}>
              {TOUR_LANGUAGES.map((option) => <option key={option.code} value={option.code}>{option.label}</option>)}
            </select>
          </label>}
          <button type="button" className="pct-close" onClick={() => onClose(false)} aria-label={tt("Close the tour")} title={tt("Close the tour")}><X size={16} /></button>
        </header>
        <div className="pct-progress" aria-hidden="true"><span style={{ width: `${((index + 1) / steps.length) * 100}%` }} /></div>
        <h2 id="pct-title">{step.title}</h2>
        <div id="pct-body" className="pct-body">{step.body}</div>
        <footer>
          {index === 0 ? <button type="button" className="pct-skip" onClick={() => onClose(false)}>{tt("Not now")}</button> : <button type="button" className="pct-skip" onClick={() => onClose(false)}>{tt("Skip the tour")}</button>}
          <span className="pct-buttons">
            {index > 0 && <button type="button" className="button button-secondary" onClick={() => go(index - 1)}><ArrowLeft size={15} /> {tt("Back")}</button>}
            <button ref={nextRef} type="button" className="button button-primary" onClick={() => go(index + 1)}>
              {last ? <><Check size={15} /> {tt("Finish")}</> : index === 0 ? <>{tt("Start the tour")} <ArrowRight size={15} /></> : <>{tt("Next")} <ArrowRight size={15} /></>}
            </button>
          </span>
        </footer>
      </div>
    </div>
  );
}

/** The last step of every app's tour: where help is, how to take the tour again, the way back. */
export function tourClosing(): TourStep {
  return {
    target: ".pcs-sidebar",
    title: tt("Help, and this tour again"),
    body: tt("Help, the last page of the menu, has a guide for every page of this app. The menu under your name holds this tour, the theme and About. PlantCraft, first in the Apps, brings you back to the platform."),
  };
}

/** The step every app's tour has (owner, 2026-10-28): the assistant's menu on one page, open,
 * with a few things it does in this app (`items`, already translated with `tt()`); in a public
 * demo it says the model is off and where the team's chats are. `path` must be a page with the
 * assistant's title button. */
export function assistantTourStep(path: string, items: string[] = []): TourStep {
  return {
    path,
    // The menu itself, open, so the step shows this page's questions (owner, 2026-10-28: not the icon).
    // Without a menu (no model, outside a demo) the button itself.
    target: '.pc-title-assistant-menu, [data-tour="assistant-title"]:not([aria-haspopup])',
    title: tt("The assistant on this page"),
    body: <AssistantStepBody items={items} />,
    // The button draws once the assistant's status arrives; until then it has no menu to open.
    onShow: openPanel('[data-tour="assistant-title"][aria-haspopup="menu"]', ".pc-title-assistant-menu"),
  };
}

function AssistantStepBody({ items }: { items: string[] }) {
  const [demo, setDemo] = useState(false);
  useEffect(() => {
    let alive = true;
    void assistantStatus().then((status) => alive && setDemo(Boolean(status?.demo)));
    return () => { alive = false; };
  }, []);
  return <>
    <p>{tt("Every page has its own questions for the assistant: this menu lists the ones for this page.")}</p>
    {items.length > 0 && <><p>{tt("In this app it can, for instance:")}</p><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></>}
    <p>{demo
      ? tt("It is off in this public demo: the Assistant button at the foot of the menu opens the team's chats, each with the steps it took.")
      : tt("It reads only what you may see, shows each step it took, and changes nothing without you.")}</p>
  </>;
}

/** On a phone the side menu is a drawer: a step pointing into it opens it, any other closes it. */
function phoneMenu(element: Element) {
  const button = document.querySelector<HTMLElement>('[data-tour="menu-button"]');
  if (!button || !button.getClientRects().length) return;
  const open = document.querySelector(".pcs-sidebar.pcs-drawer-open");
  if (element.closest(".pcs-sidebar")) {
    if (!open) button.click();
  } else if (open) {
    document.querySelector<HTMLElement>(".pcs-scrim")?.click();
  }
}

/** A step's ``onShow`` that opens a quick panel (Messages, Notifications, the assistant) or a menu
 * (the apps, the user's) by its button, so the step shows what is in it, and closes it when the
 * step goes (owner, 2026-10-28). */
export function openPanel(button: string, panel: string): () => () => void {
  return () => {
    const find = () => document.querySelector<HTMLElement>(button);
    // The button says whether its own panel is open (another panel may still be closing).
    const open = () => {
      const found = find();
      return Boolean(found && (found.classList.contains("pcs-active") || found.getAttribute("aria-pressed") === "true" || found.getAttribute("aria-expanded") === "true"));
    };
    // A button drawn late (the assistant waits for its status, a slow server) is waited for.
    const started = Date.now();
    const timer = window.setInterval(() => {
      const found = find();
      if (found || Date.now() - started > WAIT_FOR_BUTTON_MS) window.clearInterval(timer);
      if (found && !open()) found.click();
    }, 150);
    return () => {
      window.clearInterval(timer);
      if (open() && document.querySelector(panel)) find()?.click();
    };
  };
}

/** The tour of one app: opens by itself the first time (once there are steps), and on request. */
export function useTour(id: string, steps: TourStep[] | undefined) {
  const [open, setOpen] = useState(false);
  const ready = Boolean(steps?.length);
  useEffect(() => {
    if (ready && tourDue(id)) setOpen(true);
  }, [ready, id]);
  const start = useCallback(() => setOpen(true), []);
  const close = useCallback(() => {
    markTourSeen(id);
    setOpen(false);
  }, [id]);
  return { open: open && ready, start, close };
}
